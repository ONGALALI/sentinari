from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import get_settings
from .library_router import gemma_library_path, library_name_for_field

_libraries_bootstrapped = False

try:
    import psycopg2
    from psycopg2.extras import DictCursor
except ImportError:
    psycopg2 = None


class PostgresRowWrapper:
    def __init__(self, row: Any) -> None:
        self._row = row

    def __getitem__(self, key: Any) -> Any:
        try:
            val = self._row[key]
        except (KeyError, IndexError):
            if key == "embedding_json" and "embedding" in self._row:
                val = self._row["embedding"]
            elif key == "document_metadata_json" and "document_metadata" in self._row:
                val = self._row["document_metadata"]
            else:
                raise
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return val

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def keys(self) -> Any:
        return self._row.keys()

    def __contains__(self, key: Any) -> bool:
        return (
            key in self._row
            or (key == "embedding_json" and "embedding" in self._row)
            or (key == "document_metadata_json" and "document_metadata" in self._row)
        )


class PostgresCursorWrapper:
    def __init__(self, cursor: Any, lastrowid: Any = None) -> None:
        self._cur = cursor
        self._lastrowid = lastrowid

    def fetchone(self) -> Any:
        row = self._cur.fetchone()
        return PostgresRowWrapper(row) if row is not None else None

    def fetchall(self) -> list[Any]:
        return [PostgresRowWrapper(r) for r in self._cur.fetchall()]

    def fetchmany(self, size: int | None = None) -> list[Any]:
        rows = self._cur.fetchmany(size) if size else self._cur.fetchmany()
        return [PostgresRowWrapper(r) for r in rows]

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def lastrowid(self) -> Any:
        return self._lastrowid

    @property
    def description(self) -> Any:
        return self._cur.description

    def __iter__(self) -> Any:
        for r in self._cur:
            yield PostgresRowWrapper(r)


class DummyCursor:
    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []

    @property
    def rowcount(self) -> int:
        return 0

    @property
    def lastrowid(self) -> None:
        return None

    @property
    def description(self) -> None:
        return None

    def __iter__(self) -> Any:
        return iter([])


class PostgresConnectionWrapper:
    """Adapts psycopg2 connection to SQLite connection interface for seamless cloud execution."""

    def __init__(self, pg_conn: Any) -> None:
        self._conn = pg_conn
        self.row_factory = None

    def _convert_sql(self, sql: str) -> str:
        s = sql.strip()
        u = s.upper()
        m = re.match(r"PRAGMA\s+table_info\s*\(\s*['\"]?(\w+)['\"]?\s*\)", s, re.IGNORECASE)
        if m:
            table = m.group(1).lower()
            return f"SELECT column_name AS name FROM information_schema.columns WHERE table_schema='public' AND table_name='{table}'"
        if (
            u.startswith("PRAGMA")
            or u.startswith("ATTACH")
            or "TEMP VIEW" in u
            or "DROP VIEW" in u
            or "VIRTUAL TABLE" in u
            or ("CHUNK_FTS" in u and (u.startswith("INSERT INTO") or u.startswith("DELETE FROM") or u.startswith("UPDATE ")))
        ):
            return ""
        if "sqlite_master" in s:
            s = s.replace(
                "sqlite_master",
                "(SELECT table_name AS name, 'table' AS type FROM information_schema.tables WHERE table_schema='public') AS sqlite_master",
            )
        s = re.sub(r"\bINTEGER PRIMARY KEY AUTOINCREMENT\b", "SERIAL PRIMARY KEY", s, flags=re.IGNORECASE)
        s = re.sub(r"\bAUTOINCREMENT\b", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\bCASE\s+WHEN\b(.*?)\bdatetime\('now'\)(.*?)\bEND\b", r"CASE WHEN\1CURRENT_TIMESTAMP::text\2END", s, flags=re.IGNORECASE | re.DOTALL)
        s = re.sub(r"\bdatetime\('now'\)", "CURRENT_TIMESTAMP", s, flags=re.IGNORECASE)
        s = re.sub(r"\bIFNULL\s*\(", "COALESCE(", s, flags=re.IGNORECASE)
        s = re.sub(
            r"\bGROUP_CONCAT\s*\(\s*DISTINCT\s+([^)]+)\)",
            r"STRING_AGG(DISTINCT (\1)::text, ',')",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bGROUP_CONCAT\s*\(\s*([^,)]+)\s*\)",
            r"STRING_AGG((\1)::text, ',')",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bMAX\s*\(\s*([^,()]+?)\s*,\s*([^,()]+?)\s*\)",
            r"GREATEST(\1, \2)",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"\bMIN\s*\(\s*([^,()]+?)\s*,\s*([^,()]+?)\s*\)",
            r"LEAST(\1, \2)",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(r"\blast_insert_rowid\s*\(\s*\)", "LASTVAL()", s, flags=re.IGNORECASE)
        s = re.sub(r"\b(\w+\.)?embedding_json\s*!=\s*''", r"1=1", s)
        if not re.search(r"\bembedding\b", s):
            s = re.sub(r"\bembedding_json\b", "embedding", s)
        if re.search(r"\bALTER\s+TABLE\s+\w+\s+ADD\s+COLUMN\b", s, re.IGNORECASE) and "IF NOT EXISTS" not in s.upper():
            s = re.sub(r"\bADD\s+COLUMN\b", "ADD COLUMN IF NOT EXISTS", s, flags=re.IGNORECASE)
        if re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", s, re.IGNORECASE):
            s = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", s, flags=re.IGNORECASE)
            s = s.rstrip("; \t\n") + " ON CONFLICT DO NOTHING"
        s = s.replace("?", "%s")
        return s

    def execute(self, sql: str, params: Any = None) -> Any:
        clean_sql = self._convert_sql(sql)
        if not clean_sql:
            return DummyCursor()
        cur = self._conn.cursor(cursor_factory=DictCursor)
        lastrowid = None
        is_insert = clean_sql.strip().upper().startswith("INSERT INTO")
        if is_insert and "RETURNING" not in clean_sql.upper():
            try:
                cur.execute("SAVEPOINT _agy_ret_id;")
                insert_sql = clean_sql.rstrip(";") + " RETURNING id;"
                if params is not None:
                    cur.execute(insert_sql, params)
                else:
                    cur.execute(insert_sql)
                row = cur.fetchone()
                if row:
                    lastrowid = row[0]
                cur.execute("RELEASE SAVEPOINT _agy_ret_id;")
                return PostgresCursorWrapper(cur, lastrowid=lastrowid)
            except Exception:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT _agy_ret_id;")
                    cur.execute("RELEASE SAVEPOINT _agy_ret_id;")
                except Exception:
                    self._conn.rollback()
                cur = self._conn.cursor(cursor_factory=DictCursor)

        try:
            cur.execute("SAVEPOINT _agy_exec;")
            if params is not None:
                cur.execute(clean_sql, params)
            else:
                cur.execute(clean_sql)
            return PostgresCursorWrapper(cur, lastrowid=lastrowid)
        except Exception:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT _agy_exec;")
                cur.execute("RELEASE SAVEPOINT _agy_exec;")
            except Exception:
                self._conn.rollback()
            raise

    def executescript(self, sql: str) -> None:
        clean = re.sub(r"--[^\n]*", "", sql)
        clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)
        for stmt in clean.split(";"):
            stmt = stmt.strip()
            if stmt:
                self.execute(stmt)

    def executemany(self, sql: str, seq_of_params: Iterable[Any]) -> Any:
        clean_sql = self._convert_sql(sql)
        if not clean_sql:
            return DummyCursor()
        cur = self._conn.cursor(cursor_factory=DictCursor)
        params_list = list(seq_of_params)
        if not params_list:
            return PostgresCursorWrapper(cur)
        try:
            cur.execute("SAVEPOINT _agy_batch;")
            from psycopg2.extras import execute_batch

            execute_batch(cur, clean_sql, params_list, page_size=200)
            cur.execute("RELEASE SAVEPOINT _agy_batch;")
        except Exception:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT _agy_batch;")
                cur.execute("RELEASE SAVEPOINT _agy_batch;")
            except Exception:
                self._conn.rollback()
            raise
        return PostgresCursorWrapper(cur)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> PostgresConnectionWrapper:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if exc_type:
                self.rollback()
            else:
                self.commit()
        finally:
            self.close()


def _ensure_library_files() -> None:
    """Create the physical library file (full schema) once per process.

    Attaching an EMPTY library file would make the TEMP views fail, so the
    file is bootstrapped through library_connection() — which runs the
    library schema (tables AND indexes) directly inside it.
    """
    global _libraries_bootstrapped
    if _libraries_bootstrapped or os.environ.get("DATABASE_URL"):
        return
    library_connection("gemma").close()
    _libraries_bootstrapped = True



def _db_path() -> Path:
    settings = get_settings()
    return Path(settings["paths"]["sqlite_db"]).resolve()


def _attach_libraries(conn: sqlite3.Connection) -> None:
    """ATTACH the physical library and expose unified TEMP views.

    The main database keeps chat/tasks/qualia state. The knowledge library
    (documents / chunks / chunk_fts / ingest_events) lives in ONE physical
    database — sentinari.db (Sentinel / Guardian fields; §51 renamed from
    the legacy library_gemma.db filename — same file, new name).
    Every existing query in the app keeps working unchanged against the TEMP
    views; writes go through the routing helpers below.
    """
    gemma_path = gemma_library_path()
    gemma_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_library_files()
    conn.execute("ATTACH DATABASE ? AS gemma_lib;", (str(gemma_path),))
    # SQLite forbids PERSISTENT views that reference other databases and views
    # cannot be written through. TEMP views scoped to THIS connection work for
    # unified reads; every writer routes through library_connection() instead.
    conn.execute("DROP VIEW IF EXISTS main.documents;")
    conn.execute("DROP VIEW IF EXISTS main.chunks;")
    conn.execute("DROP VIEW IF EXISTS main.ingest_events;")
    conn.executescript(
        """
        CREATE TEMP VIEW documents AS
            SELECT * FROM gemma_lib.documents;

        CREATE TEMP VIEW chunks AS
            SELECT * FROM gemma_lib.chunks;

        CREATE TEMP VIEW ingest_events AS
            SELECT * FROM gemma_lib.ingest_events;
        """
    )


def _get_pg_url() -> str | None:
    socket_path = Path("/cloudsql/seninari:us-central1:sentinari-db")
    if socket_path.exists():
        return "postgresql://postgres:Sentinari_2026_Cloud_Db!@/sentinari?host=/cloudsql/seninari:us-central1:sentinari-db"
    return os.environ.get("DATABASE_URL")


_PG_COOLDOWN_UNTIL = 0.0


def _connect_pg(db_url: str) -> PostgresConnectionWrapper | None:
    global _PG_COOLDOWN_UNTIL
    import time
    if psycopg2 is None or not db_url:
        return None
    if time.time() < _PG_COOLDOWN_UNTIL:
        return None
    try:
        raw_conn = psycopg2.connect(db_url, connect_timeout=3)
        return PostgresConnectionWrapper(raw_conn)
    except Exception as ex:
        _PG_COOLDOWN_UNTIL = time.time() + 15.0
        print(f"[db] PostgreSQL connection failed ({ex}); fallback to local SQLite library.", flush=True)
        return None


def try_library_write_lock(timeout_ms: int = 750) -> bool:
    """True when the Gemma library accepts a write transaction right now.

    §77: the status endpoint must know whether a count refresh can proceed
    without stalling behind a bulk writer (e.g. the learning engine writing
    chunks mid-load). Uses a bare connection — no schema script, no views.
    """
    db_url = _get_pg_url()
    if db_url and _connect_pg(db_url) is not None:
        return True
    conn = None
    try:
        target = gemma_library_path()
        if not target.exists():
            return False
        conn = sqlite3.connect(str(target), timeout=max(0.1, timeout_ms / 1000.0))
        conn.execute(f"PRAGMA busy_timeout = {max(100, int(timeout_ms))};")
        conn.execute("BEGIN IMMEDIATE;")
        conn.execute("ROLLBACK;")
        return True
    except sqlite3.OperationalError:
        return False
    except Exception:
        return False
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def library_read_connection(*, busy_timeout_ms: int = 750) -> Any:
    """Read-only connection to the physical Gemma library database.

    Never writes and never runs the schema ensure script, so it succeeds
    instantly even while a bulk ingestion writer holds the write lock
    (WAL mode allows concurrent readers). Status/dashboard endpoints use
    this so a long load can no longer stall them until the browser gives
    up with `TypeError: Failed to fetch`.
    """
    db_url = _get_pg_url()
    if db_url:
        pg_conn = _connect_pg(db_url)
        if pg_conn is not None:
            return pg_conn
    target = gemma_library_path()
    if not target.exists():
        raise FileNotFoundError(f"Library database not found at {target}")
    uri = f"file:{target.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, timeout=max(0.1, busy_timeout_ms / 1000.0), uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {max(100, int(busy_timeout_ms))};")
    conn.execute("PRAGMA query_only = ON;")
    return conn


def library_connection(library: str = "gemma", *, busy_timeout_ms: int | None = None) -> Any:
    """Direct read/write connection to the physical library database.

    All writes route to the single Gemma library. Creates the library schema
    on first use. Pass ``busy_timeout_ms`` to cap how long the built-in schema
    ensure write may wait for the lock (§77: status/dashboard callers pass a
    small cap so a mid-load writer cannot stall them for the configured 20s).
    """
    db_url = _get_pg_url()
    if db_url:
        pg_conn = _connect_pg(db_url)
        if pg_conn is not None:
            return pg_conn
    target = gemma_library_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    runtime = settings.get("runtime", {})
    if busy_timeout_ms is None:
        busy_timeout_ms = max(1000, int(runtime.get("sqlite_busy_timeout_ms") or 1000))
    busy_timeout_ms = max(250, int(busy_timeout_ms))
    conn = sqlite3.connect(str(target), timeout=max(1.0, busy_timeout_ms / 1000.0))
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms};")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.executescript(_LIBRARY_SCHEMA)
    return conn


_LIBRARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT,
    title TEXT,
    source_type TEXT,
    source_path TEXT,
    source_url TEXT,
    domain TEXT,
    module TEXT,
    topic TEXT,
    language TEXT,
    license TEXT,
    published_date TEXT,
    authors TEXT,
    publisher TEXT,
    scientific_field TEXT,
    vocational_discipline TEXT,
    source_collection TEXT,
    document_metadata_json TEXT NOT NULL DEFAULT '{}',
    priority INTEGER DEFAULT 0,
    checksum TEXT NOT NULL,
    archive_path TEXT,
    raw_char_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_checksum ON documents(checksum);
CREATE INDEX IF NOT EXISTS idx_documents_module_topic ON documents(module, topic);
CREATE INDEX IF NOT EXISTS idx_documents_field ON documents(scientific_field);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    embedding_json TEXT,
    chunk_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, chunk_index);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts
USING fts5(content, document_id UNINDEXED, tokenize='unicode61');

CREATE TABLE IF NOT EXISTS ingest_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT,
    source_type TEXT,
    status TEXT,
    error TEXT,
    source_id TEXT,
    document_id INTEGER,
    chunk_count INTEGER,
    char_count INTEGER,
    pdf_engine TEXT,
    module TEXT,
    topic TEXT,
    scientific_field TEXT,
    vocational_discipline TEXT,
    source_collection TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ingest_events_field ON ingest_events(scientific_field);
"""


def get_connection() -> Any:
    db_url = _get_pg_url()
    if db_url:
        pg_conn = _connect_pg(db_url)
        if pg_conn is not None:
            return pg_conn
    settings = get_settings()
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = settings.get("runtime", {})
    busy_timeout_ms = max(1000, int(runtime.get("sqlite_busy_timeout_ms") or 1000))
    conn = sqlite3.connect(str(db_path), timeout=max(1.0, busy_timeout_ms / 1000.0))
    conn.row_factory = sqlite3.Row
    _attach_libraries(conn)
    def safe_pragma(sql: str) -> None:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower():
                conn.close()
                raise

    safe_pragma(f"PRAGMA busy_timeout = {busy_timeout_ms};")
    safe_pragma("PRAGMA foreign_keys = ON;")
    journal_mode = str(runtime.get("chat_db_journal_mode", "WAL") or "WAL").strip().upper()
    if journal_mode not in {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}:
        journal_mode = "WAL"
    safe_pragma(f"PRAGMA journal_mode = {journal_mode};")
    safe_pragma("PRAGMA synchronous = NORMAL;")
    return conn


def try_write_lock(timeout_ms: int = 1500) -> Any:
    """Acquire the database write lock briefly, or return None if busy."""
    db_url = _get_pg_url()
    if db_url:
        pg_conn = _connect_pg(db_url)
        if pg_conn is not None:
            return pg_conn
    conn = None
    try:
        settings = get_settings()
        conn = sqlite3.connect(str(_db_path()), timeout=max(0.1, timeout_ms / 1000.0))
        conn.execute(f"PRAGMA busy_timeout = {max(100, int(timeout_ms))};")
        conn.execute("BEGIN IMMEDIATE;")
        conn.execute("ROLLBACK;")  # release; caller re-begins on their own connection
        return conn
    except sqlite3.OperationalError:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        return None
    except Exception:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        return None


def get_read_connection(*, busy_timeout_ms: int = 750) -> Any:
    db_url = _get_pg_url()
    if db_url:
        pg_conn = _connect_pg(db_url)
        if pg_conn is not None:
            return pg_conn
    settings = get_settings()
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_library_files()
    timeout_ms = max(100, min(5000, int(busy_timeout_ms or 750)))
    uri = f"file:{db_path.as_posix()}?mode=ro&cache=shared"
    conn = sqlite3.connect(uri, timeout=max(0.1, timeout_ms / 1000.0), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout = {timeout_ms};")
        _attach_libraries_readonly(conn)
        conn.execute("PRAGMA query_only = ON;")
    except sqlite3.OperationalError:
        conn.close()
        raise
    return conn


def _attach_libraries_readonly(conn: sqlite3.Connection) -> None:
    """ATTACH the libraries for read-only connections + TEMP union views.

    TEMP views are created BEFORE the caller switches the connection into
    query_only mode (creating a TEMP view is a schema write, and query_only
    would block it).
    """
    conn.execute("ATTACH DATABASE ? AS gemma_lib;", (str(gemma_library_path()),))
    conn.executescript(
        """
        CREATE TEMP VIEW documents AS
            SELECT * FROM gemma_lib.documents;
        CREATE TEMP VIEW chunks AS
            SELECT * FROM gemma_lib.chunks;
        CREATE TEMP VIEW ingest_events AS
            SELECT * FROM gemma_lib.ingest_events;
        """
    )


# Derived tables that were originally created with FK clauses pointing at
# documents/chunks. Those knowledge tables now live in the attached library
# databases and their union names are TEMP views — neither can be an FK
# parent. Rebuild these tables without the unenforceable constraints (ids are
# kept; they remain the audit trail).
_FK_TABLE_FIXES = (
    "unsupervised_clusters",
    "unsupervised_cluster_members",
)


def _migrate_library_fk_tables(conn: Any) -> None:
    if isinstance(conn, PostgresConnectionWrapper):
        return
    for table in _FK_TABLE_FIXES:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        sql = str(row["sql"] or "") if row else ""
        if not sql or ("REFERENCES documents" not in sql and "REFERENCES chunks" not in sql):
            continue
        lines = [
            line
            for line in sql.splitlines()
            if "REFERENCES documents" not in line and "REFERENCES chunks" not in line
        ]
        fixed = re.sub(r",\s*\)", ")", "\n".join(lines))
        if fixed == sql:
            continue
        tmp = f"{table}__fkfix"
        create_sql = re.sub(
            rf"CREATE TABLE (IF NOT EXISTS )?{re.escape(table)}",
            f"CREATE TABLE {tmp}",
            fixed,
            count=1,
        )
        conn.execute("PRAGMA foreign_keys=OFF;")
        previous_isolation = conn.isolation_level
        conn.isolation_level = None  # explicit transaction control
        conn.execute("BEGIN IMMEDIATE;")
        try:
            conn.execute(f"DROP TABLE IF EXISTS {tmp};")
            conn.execute(create_sql)
            conn.execute(f"INSERT INTO {tmp} SELECT * FROM {table};")
            index_rows = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                (table,),
            ).fetchall()
            conn.execute(f"DROP TABLE {table};")
            conn.execute(f"ALTER TABLE {tmp} RENAME TO {table};")
            for idx in index_rows:
                conn.execute(str(idx["sql"]))
            conn.execute("COMMIT;")
            conn.isolation_level = previous_isolation
        except Exception:
            conn.execute("ROLLBACK;")
            conn.isolation_level = previous_isolation
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON;")
        print(f"[db] rebuilt {table} without cross-library foreign keys", flush=True)


def initialize_database() -> None:
    db_url = _get_pg_url()
    if db_url and _connect_pg(db_url) is not None:
        try:
            with library_connection() as lib_conn:
                lib_conn.executescript(_LIBRARY_SCHEMA)
                lib_conn.commit()
        except Exception as ex:
            print(f"[db] Postgres schema initialization failed ({ex}); continuing.", flush=True)

    # NOTE: documents / chunks / chunk_fts / ingest_events are NOT created here.
    # They live in the attached physical library (sentinari.db — the former
    # coding library was folded in), created by _attach_libraries() on every connection.
    schema = """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        session_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        citations_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id_desc ON chat_messages(session_id, id DESC);

    CREATE TABLE IF NOT EXISTS chat_session_memory (
        session_id TEXT PRIMARY KEY,
        rolling_summary TEXT NOT NULL DEFAULT '',
        last_compacted_message_id INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS smi_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_to_perform TEXT NOT NULL,
        target_datetime TEXT NOT NULL DEFAULT '',
        quality_standard_expected TEXT NOT NULL DEFAULT '',
        knowledge_library_applicable TEXT NOT NULL DEFAULT '',
        attachments_json TEXT NOT NULL DEFAULT '[]',
        smi_feedback TEXT NOT NULL DEFAULT '',
        evaluation TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        last_smi_feedback_at TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_smi_tasks_status_updated
        ON smi_tasks(status, updated_at DESC);

    CREATE TABLE IF NOT EXISTS smi_profile_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL DEFAULT 'manual',
        purpose TEXT NOT NULL DEFAULT '',
        domain_focus TEXT NOT NULL DEFAULT '',
        out_of_scope_policy TEXT NOT NULL DEFAULT '',
        goals_json TEXT NOT NULL DEFAULT '[]',
        personality_json TEXT NOT NULL DEFAULT '{}',
        safety_json TEXT NOT NULL DEFAULT '{}',
        addendums_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_smi_profile_snapshots_created
        ON smi_profile_snapshots(created_at DESC);

    CREATE TABLE IF NOT EXISTS smi_operator_state (
        state_key TEXT PRIMARY KEY,
        last_saved_source TEXT NOT NULL DEFAULT 'manual',
        name TEXT NOT NULL DEFAULT '',
        tone TEXT NOT NULL DEFAULT '',
        purpose TEXT NOT NULL DEFAULT '',
        default_language TEXT NOT NULL DEFAULT '',
        supported_languages_json TEXT NOT NULL DEFAULT '[]',
        domain_focus TEXT NOT NULL DEFAULT '',
        out_of_scope_policy TEXT NOT NULL DEFAULT '',
        goals_json TEXT NOT NULL DEFAULT '[]',
        general_addendum TEXT NOT NULL DEFAULT '',
        coding_mode_system_addendum TEXT NOT NULL DEFAULT '',
        personality_json TEXT NOT NULL DEFAULT '{}',
        safety_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_smi_operator_state_updated
        ON smi_operator_state(updated_at DESC);

    CREATE TABLE IF NOT EXISTS qualia_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_type TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT '',
        session_id TEXT NOT NULL DEFAULT '',
        behavior_variant REAL,
        effective_variant_ratio REAL,
        gamma_requested REAL,
        gamma_effective REAL,
        stability_bias REAL,
        stability_index REAL,
        influence REAL,
        attention_score REAL,
        reasoning_score REAL,
        logic_score REAL,
        confidence REAL,
        before_state_json TEXT NOT NULL DEFAULT '{}',
        after_state_json TEXT NOT NULL DEFAULT '{}',
        recommendation_json TEXT NOT NULL DEFAULT '{}',
        benchmark_summary_json TEXT NOT NULL DEFAULT '{}',
        bell_curve_json TEXT NOT NULL DEFAULT '{}',
        trajectory_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_qualia_history_created
        ON qualia_history(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_qualia_history_type_created
        ON qualia_history(run_type, created_at DESC);

    CREATE TABLE IF NOT EXISTS taxonomy_nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        name TEXT NOT NULL,
        slug TEXT NOT NULL,
        path TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_taxonomy_nodes_category_slug ON taxonomy_nodes(category, slug);

    CREATE TABLE IF NOT EXISTS file_ingest_state (
        path TEXT PRIMARY KEY,
        file_size INTEGER NOT NULL DEFAULT 0,
        mtime_utc TEXT NOT NULL DEFAULT '',
        checksum TEXT NOT NULL DEFAULT '',
        last_status TEXT NOT NULL DEFAULT 'unknown',
        last_error TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- NOTE: ingest_events is intentionally NOT created in the main database.
    -- It is a TEMP view over the physical library (created in
    -- _attach_libraries); ingest events are written inside the library.

    CREATE TABLE IF NOT EXISTS unsupervised_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        algorithm TEXT NOT NULL DEFAULT 'kmeans-cosine',
        vector_source TEXT NOT NULL DEFAULT 'pending',
        requested_clusters INTEGER,
        resolved_clusters INTEGER NOT NULL DEFAULT 0,
        min_points INTEGER NOT NULL DEFAULT 0,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        scientific_field TEXT,
        vocational_discipline TEXT,
        source_collection TEXT,
        started_at TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at TEXT,
        notes TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_unsupervised_runs_started ON unsupervised_runs(started_at DESC);

    CREATE TABLE IF NOT EXISTS unsupervised_clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        cluster_index INTEGER NOT NULL,
        label TEXT NOT NULL,
        size INTEGER NOT NULL DEFAULT 0,
        top_terms_json TEXT NOT NULL DEFAULT '[]',
        exemplar_chunk_id INTEGER,
        centroid_json TEXT,
        FOREIGN KEY (run_id) REFERENCES unsupervised_runs(id) ON DELETE CASCADE
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_unsupervised_clusters_run_cluster
        ON unsupervised_clusters(run_id, cluster_index);
    CREATE INDEX IF NOT EXISTS idx_unsupervised_clusters_run_size
        ON unsupervised_clusters(run_id, size DESC);

    CREATE TABLE IF NOT EXISTS unsupervised_cluster_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_id INTEGER NOT NULL,
        run_id INTEGER NOT NULL,
        chunk_id INTEGER NOT NULL,
        assignment_score REAL NOT NULL DEFAULT 0,
        FOREIGN KEY (cluster_id) REFERENCES unsupervised_clusters(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES unsupervised_runs(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_unsupervised_members_cluster
        ON unsupervised_cluster_members(cluster_id, assignment_score DESC);
    CREATE INDEX IF NOT EXISTS idx_unsupervised_members_run
        ON unsupervised_cluster_members(run_id);
    CREATE INDEX IF NOT EXISTS idx_unsupervised_members_chunk
        ON unsupervised_cluster_members(chunk_id);



    """
    with get_connection() as conn:
        _migrate_library_fk_tables(conn)
        conn.executescript(schema)
        _ensure_columns(
            conn,
            "smi_tasks",
            (
                ("attachments_json", "TEXT NOT NULL DEFAULT '[]'"),
            ),
        )
        conn.commit()
    # Library-side migration (§77): deterministic chunk hashing for the
    # ingestion dedup gate. Existing rows backfill to '' lazily on write.
    with library_connection() as conn:
        _ensure_columns(
            conn,
            "chunks",
            (
                ("chunk_hash", "TEXT NOT NULL DEFAULT ''"),
            ),
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(chunk_hash);"
        )
        conn.commit()
        # Graph-relational map (§77 corrections 1): structural edges between
        # documents and authors/publishers/fields so retrieval can traverse
        # metadata relationships instead of relying on flat vector search alone.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_edges (
                src_type TEXT NOT NULL,
                src_value TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                dst_type TEXT NOT NULL,
                dst_value TEXT NOT NULL,
                document_id INTEGER NOT NULL,
                PRIMARY KEY (src_type, src_value, edge_type, dst_type, dst_value, document_id)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_src ON document_edges(src_type, src_value);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON document_edges(dst_type, dst_value);
            CREATE INDEX IF NOT EXISTS idx_edges_doc ON document_edges(document_id);
            """
        )
        conn.commit()
        if isinstance(conn, PostgresConnectionWrapper):
            _sync_postgres_sequences(conn)


def _sync_postgres_sequences(conn: PostgresConnectionWrapper) -> None:
    """Ensure PostgreSQL SERIAL sequences are at least MAX(id) + 1 after bulk migrations."""
    for tbl in (
        "documents",
        "chunks",
        "ingest_events",
        "skill_review_candidates",
        "chat_messages",
        "smi_tasks",
        "smi_profile_snapshots",
        "qualia_history",
        "taxonomy_nodes",
        "unsupervised_runs",
        "unsupervised_clusters",
        "unsupervised_cluster_members",
        "pattern_entities",
        "pattern_relations",
        "patterns",
        "pattern_evidence",
        "pattern_templates",
        "pattern_extraction_log",
        "future_requests",
    ):
        try:
            conn.execute(
                f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), COALESCE((SELECT MAX(id) FROM {tbl}), 0) + 1, false);"
            )
            conn.commit()
        except Exception:
            conn.rollback()


def reset_document_chunks(conn: sqlite3.Connection, document_id: int) -> None:
    existing_ids = conn.execute(
        "SELECT id FROM chunks WHERE document_id = ? ORDER BY id;",
        (document_id,),
    ).fetchall()
    for row in existing_ids:
        conn.execute("DELETE FROM chunk_fts WHERE rowid = ?;", (int(row["id"]),))
    conn.execute("DELETE FROM chunks WHERE document_id = ?;", (document_id,))


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name});").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_columns(conn: sqlite3.Connection, table_name: str, column_defs: Iterable[tuple[str, str]]) -> None:
    existing = _table_columns(conn, table_name)
    for column_name, sql_type in column_defs:
        if column_name in existing:
            continue
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type};")

