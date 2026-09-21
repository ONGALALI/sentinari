from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .chunking import split_into_chunks
from .config import get_project_root, get_settings
from .parsing import parse_document_from_path
from .retrieval import _fts_query_from_text

PERSONAL_GROWTH_MEDIA_SUFFIXES = {".mp3", ".mp4"}


def personal_growth_db_path() -> Path:
    return (get_project_root() / "data" / "smi_personal_growth.db").resolve()


def get_personal_growth_connection() -> sqlite3.Connection:
    db_path = personal_growth_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    busy_timeout_ms = max(1000, int(runtime.get("sqlite_busy_timeout_ms") or 1000))
    conn = sqlite3.connect(str(db_path), timeout=max(1.0, busy_timeout_ms / 1000.0))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms};")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def initialize_personal_growth_database() -> None:
    with get_personal_growth_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS personal_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_path TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                authors TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '',
                published_date TEXT NOT NULL DEFAULT '',
                checksum TEXT NOT NULL,
                raw_char_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_personal_documents_checksum
                ON personal_documents(checksum);
            CREATE INDEX IF NOT EXISTS idx_personal_documents_category
                ON personal_documents(category, created_at DESC);

            CREATE TABLE IF NOT EXISTS personal_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                token_estimate INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (document_id) REFERENCES personal_documents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_personal_chunks_document
                ON personal_chunks(document_id, chunk_index);

            CREATE VIRTUAL TABLE IF NOT EXISTS personal_chunk_fts
            USING fts5(content, document_id UNINDEXED, tokenize='unicode61');

            CREATE TABLE IF NOT EXISTS personal_ingest_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                document_id INTEGER,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                char_count INTEGER NOT NULL DEFAULT 0,
                category TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_personal_ingest_events_created
                ON personal_ingest_events(created_at DESC);

            CREATE TABLE IF NOT EXISTS personal_media_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                media_type TEXT NOT NULL,
                source_path TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                checksum TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_personal_media_type
                ON personal_media_assets(media_type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_personal_media_category
                ON personal_media_assets(category, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_personal_media_checksum
                ON personal_media_assets(checksum);

            CREATE TABLE IF NOT EXISTS personal_mp3_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER NOT NULL UNIQUE,
                media_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                source_path TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                checksum TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (media_asset_id) REFERENCES personal_media_assets(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_personal_mp3_category
                ON personal_mp3_assets(category, created_at DESC);

            CREATE TABLE IF NOT EXISTS personal_mp4_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id INTEGER NOT NULL UNIQUE,
                media_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                source_path TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                checksum TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (media_asset_id) REFERENCES personal_media_assets(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_personal_mp4_category
                ON personal_mp4_assets(category, created_at DESC);

            CREATE TABLE IF NOT EXISTS personal_finetune_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                model_name TEXT NOT NULL DEFAULT '',
                categories_json TEXT NOT NULL DEFAULT '[]',
                sample_style TEXT NOT NULL DEFAULT 'source_grounded',
                output_path TEXT NOT NULL DEFAULT '',
                total_records INTEGER NOT NULL DEFAULT 0,
                records_digested INTEGER NOT NULL DEFAULT 0,
                percent_complete REAL NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_personal_finetune_runs_updated
                ON personal_finetune_runs(updated_at DESC);

            CREATE TABLE IF NOT EXISTS personal_finetune_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                document_id INTEGER NOT NULL,
                chunk_id INTEGER NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                sample_kind TEXT NOT NULL DEFAULT '',
                instruction TEXT NOT NULL,
                input TEXT NOT NULL DEFAULT '',
                output TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (document_id) REFERENCES personal_documents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_personal_finetune_samples_run
                ON personal_finetune_samples(run_id, id);
            """
        )
        conn.commit()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=True, default=str)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _token_estimate(text: str) -> int:
    return max(1, int(len((text or "").split()) * 1.15))


def _normalize_text_list(values: Any, *, max_items: int = 40) -> list[str]:
    if isinstance(values, list):
        raw_items = values
    else:
        raw_items = str(values or "").replace(";", ",").split(",")
    seen: set[str] = set()
    result: list[str] = []
    for item in raw_items:
        text = " ".join(str(item or "").strip().split())
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= max(1, int(max_items)):
            break
    return result


def _personal_finetune_root() -> Path:
    root = get_project_root() / "data" / "personal_growth_finetune"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _source_id(conn: sqlite3.Connection) -> str:
    while True:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        candidate = f"PG-{stamp[-12:]}"
        if conn.execute("SELECT 1 FROM personal_documents WHERE source_id = ?;", (candidate,)).fetchone() is None:
            return candidate


def _media_id(conn: sqlite3.Connection, prefix: str) -> str:
    while True:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        candidate = f"{prefix.upper()}-{stamp[-12:]}"
        if conn.execute("SELECT 1 FROM personal_media_assets WHERE media_id = ?;", (candidate,)).fetchone() is None:
            return candidate


def is_personal_growth_media_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in PERSONAL_GROWTH_MEDIA_SUFFIXES


def _clear_chunks(conn: sqlite3.Connection, document_id: int) -> None:
    chunk_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM personal_chunks WHERE document_id = ?;", (document_id,))]
    if chunk_ids:
        placeholders = ",".join("?" for _ in chunk_ids)
        conn.execute(f"DELETE FROM personal_chunk_fts WHERE rowid IN ({placeholders});", chunk_ids)
    conn.execute("DELETE FROM personal_chunks WHERE document_id = ?;", (document_id,))


def ingest_personal_growth_file(path: str, *, category: str = "", purpose: str = "") -> dict[str, Any]:
    initialize_personal_growth_database()
    source_path = Path(path).resolve()
    data = source_path.read_bytes()
    checksum = _sha256_bytes(data)
    strip_noise = bool(get_settings().get("ingestion", {}).get("strip_noise", True))
    parsed = parse_document_from_path(str(source_path), strip_noise=strip_noise)
    text = str(parsed.get("text") or "").strip()
    if not text:
        raise ValueError("No extractable text found for personal-growth material.")

    ingestion = get_settings().get("ingestion", {}) if isinstance(get_settings().get("ingestion"), dict) else {}
    chunks = split_into_chunks(
        text,
        max_chunk_chars=int(ingestion.get("max_chunk_chars") or 1100),
        overlap_chars=int(ingestion.get("chunk_overlap_chars") or 180),
        min_chunk_chars=int(ingestion.get("min_chunk_chars") or 220),
    )
    title = str(parsed.get("title") or source_path.stem).strip() or source_path.stem
    source_type = str(parsed.get("source_type") or source_path.suffix.lower().lstrip(".") or "file")
    meta = {
        "personal_growth": True,
        "storage_lane": "smi_personal_growth",
        "original_name": source_path.name,
        "extra_metadata": parsed.get("extra_metadata") or {},
    }

    with get_personal_growth_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, source_id
            FROM personal_documents
            WHERE checksum = ? OR source_path = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (checksum, str(source_path)),
        ).fetchone()
        if existing:
            document_id = int(existing["id"])
            source_id = str(existing["source_id"])
            _clear_chunks(conn, document_id)
            conn.execute(
                """
                UPDATE personal_documents
                SET title = ?, source_type = ?, source_path = ?, category = ?, purpose = ?,
                    authors = ?, publisher = ?, published_date = ?, checksum = ?,
                    raw_char_count = ?, metadata_json = ?
                WHERE id = ?;
                """,
                (
                    title,
                    source_type,
                    str(source_path),
                    category,
                    purpose,
                    str(parsed.get("authors") or ""),
                    str(parsed.get("publisher") or ""),
                    str(parsed.get("published_date") or ""),
                    checksum,
                    len(text),
                    _json_dumps(meta),
                    document_id,
                ),
            )
        else:
            source_id = _source_id(conn)
            cur = conn.execute(
                """
                INSERT INTO personal_documents (
                    source_id, title, source_type, source_path, category, purpose,
                    authors, publisher, published_date, checksum, raw_char_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    source_id,
                    title,
                    source_type,
                    str(source_path),
                    category,
                    purpose,
                    str(parsed.get("authors") or ""),
                    str(parsed.get("publisher") or ""),
                    str(parsed.get("published_date") or ""),
                    checksum,
                    len(text),
                    _json_dumps(meta),
                ),
            )
            document_id = int(cur.lastrowid)

        for idx, chunk in enumerate(chunks):
            cur = conn.execute(
                """
                INSERT INTO personal_chunks (document_id, chunk_index, content, token_estimate, metadata_json)
                VALUES (?, ?, ?, ?, ?);
                """,
                (document_id, idx, chunk, _token_estimate(chunk), _json_dumps({"source_id": source_id})),
            )
            conn.execute(
                "INSERT INTO personal_chunk_fts (rowid, content, document_id) VALUES (?, ?, ?);",
                (int(cur.lastrowid), chunk, document_id),
            )

        conn.execute(
            """
            INSERT INTO personal_ingest_events (
                source_path, source_type, status, source_id, document_id, chunk_count, char_count, category, purpose
            ) VALUES (?, ?, 'ok', ?, ?, ?, ?, ?, ?);
            """,
            (str(source_path), source_type, source_id, document_id, len(chunks), len(text), category, purpose),
        )
        conn.commit()

    return {
        "ok": True,
        "document_id": document_id,
        "source_id": source_id,
        "title": title,
        "source_type": source_type,
        "chunk_count": len(chunks),
        "char_count": len(text),
        "checksum": checksum,
    }


def register_personal_growth_media(path: str, *, category: str = "", purpose: str = "") -> dict[str, Any]:
    initialize_personal_growth_database()
    source_path = Path(path).resolve()
    suffix = source_path.suffix.lower()
    if suffix not in PERSONAL_GROWTH_MEDIA_SUFFIXES:
        raise ValueError(f"Unsupported personal-growth media type: {suffix or 'unknown'}")
    media_type = "audio" if suffix == ".mp3" else "video"
    data = source_path.read_bytes()
    checksum = _sha256_bytes(data)
    title = source_path.stem.strip() or source_path.name
    meta = {
        "personal_growth": True,
        "storage_lane": "smi_personal_growth",
        "media_suffix": suffix,
        "original_name": source_path.name,
        "analysis_status": "stored_not_transcribed",
    }

    with get_personal_growth_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, media_id
            FROM personal_media_assets
            WHERE checksum = ? OR source_path = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (checksum, str(source_path)),
        ).fetchone()
        if existing:
            asset_id = int(existing["id"])
            media_id = str(existing["media_id"])
            conn.execute(
                """
                UPDATE personal_media_assets
                SET title = ?, media_type = ?, source_path = ?, category = ?, purpose = ?,
                    file_size = ?, checksum = ?, metadata_json = ?
                WHERE id = ?;
                """,
                (
                    title,
                    media_type,
                    str(source_path),
                    category,
                    purpose,
                    len(data),
                    checksum,
                    _json_dumps(meta),
                    asset_id,
                ),
            )
        else:
            media_id = _media_id(conn, "PGA" if media_type == "audio" else "PGV")
            cur = conn.execute(
                """
                INSERT INTO personal_media_assets (
                    media_id, title, media_type, source_path, category, purpose, file_size, checksum, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (media_id, title, media_type, str(source_path), category, purpose, len(data), checksum, _json_dumps(meta)),
            )
            asset_id = int(cur.lastrowid)

        typed_table = "personal_mp3_assets" if media_type == "audio" else "personal_mp4_assets"
        conn.execute(
            f"""
            INSERT INTO {typed_table} (
                media_asset_id, media_id, title, source_path, category, purpose, file_size, checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_asset_id) DO UPDATE SET
                media_id = excluded.media_id,
                title = excluded.title,
                source_path = excluded.source_path,
                category = excluded.category,
                purpose = excluded.purpose,
                file_size = excluded.file_size,
                checksum = excluded.checksum;
            """,
            (asset_id, media_id, title, str(source_path), category, purpose, len(data), checksum),
        )

        conn.execute(
            """
            INSERT INTO personal_ingest_events (
                source_path, source_type, status, source_id, document_id, chunk_count, char_count, category, purpose
            ) VALUES (?, ?, 'ok', ?, NULL, 0, 0, ?, ?);
            """,
            (str(source_path), media_type, media_id, category, purpose),
        )
        conn.commit()

    return {
        "ok": True,
        "asset_id": asset_id,
        "media_id": media_id,
        "title": title,
        "media_type": media_type,
        "file_size": len(data),
        "checksum": checksum,
        "chunk_count": 0,
        "char_count": 0,
        "analysis_status": "stored_not_transcribed",
    }


def record_personal_growth_failure(path: str, *, error: str, category: str = "", purpose: str = "") -> None:
    initialize_personal_growth_database()
    source_path = str(Path(path).resolve()) if path else ""
    source_type = Path(path).suffix.lower().lstrip(".") if path else ""
    with get_personal_growth_connection() as conn:
        conn.execute(
            """
            INSERT INTO personal_ingest_events (source_path, source_type, status, error, category, purpose)
            VALUES (?, ?, 'failed', ?, ?, ?);
            """,
            (source_path, source_type, error, category, purpose),
        )
        conn.commit()


def personal_growth_status() -> dict[str, Any]:
    initialize_personal_growth_database()
    with get_personal_growth_connection() as conn:
        docs = int(conn.execute("SELECT COUNT(*) AS c FROM personal_documents;").fetchone()["c"] or 0)
        chunks = int(conn.execute("SELECT COUNT(*) AS c FROM personal_chunks;").fetchone()["c"] or 0)
        chars = int(conn.execute("SELECT COALESCE(SUM(raw_char_count), 0) AS c FROM personal_documents;").fetchone()["c"] or 0)
        audio_count = int(conn.execute("SELECT COUNT(*) AS c FROM personal_mp3_assets;").fetchone()["c"] or 0)
        video_count = int(conn.execute("SELECT COUNT(*) AS c FROM personal_mp4_assets;").fetchone()["c"] or 0)
        latest = conn.execute(
            """
            SELECT title, category, purpose, created_at, 'document' AS asset_type, id AS sort_id
            FROM personal_documents
            UNION ALL
            SELECT title, category, purpose, created_at, media_type AS asset_type, id AS sort_id
            FROM personal_media_assets
            ORDER BY created_at DESC, sort_id DESC
            LIMIT 8;
            """
        ).fetchall()
        categories = conn.execute(
            """
            WITH doc_stats AS (
                SELECT category, COUNT(*) AS documents, COALESCE(SUM(raw_char_count), 0) AS chars
                FROM personal_documents
                GROUP BY category
            ),
            chunk_stats AS (
                SELECT d.category AS category, COUNT(c.id) AS chunks
                FROM personal_documents d
                LEFT JOIN personal_chunks c ON c.document_id = d.id
                GROUP BY d.category
            ),
            media_stats AS (
                SELECT category, COUNT(*) AS media_assets
                FROM personal_media_assets
                GROUP BY category
            )
            SELECT
                COALESCE(doc_stats.category, media_stats.category, '') AS category,
                COALESCE(doc_stats.documents, 0) AS documents,
                COALESCE(chunk_stats.chunks, 0) AS chunks,
                COALESCE(doc_stats.chars, 0) AS chars,
                COALESCE(media_stats.media_assets, 0) AS media_assets
            FROM doc_stats
            LEFT JOIN chunk_stats ON chunk_stats.category = doc_stats.category
            LEFT JOIN media_stats ON media_stats.category = doc_stats.category
            UNION ALL
            SELECT
                media_stats.category AS category,
                0 AS documents,
                0 AS chunks,
                0 AS chars,
                media_stats.media_assets AS media_assets
            FROM media_stats
            LEFT JOIN doc_stats ON doc_stats.category = media_stats.category
            WHERE doc_stats.category IS NULL
            ORDER BY documents DESC, chars DESC, category ASC;
            """
        ).fetchall()
        latest_finetune = conn.execute(
            """
            SELECT run_id, status, model_name, sample_style, output_path, total_records,
                   records_digested, percent_complete, message, updated_at, completed_at
            FROM personal_finetune_runs
            ORDER BY updated_at DESC, id DESC
            LIMIT 1;
            """
        ).fetchone()
    category_rows: list[dict[str, Any]] = []
    for row in categories:
        item = dict(row)
        item_chars = int(item.get("chars") or 0)
        item_docs = int(item.get("documents") or 0)
        item["char_percent"] = round((item_chars / chars) * 100.0, 2) if chars > 0 else 0.0
        item["document_percent"] = round((item_docs / docs) * 100.0, 2) if docs > 0 else 0.0
        item["text_digest_status"] = "parsed" if item_docs > 0 and item_chars > 0 else "stored_media_only"
        category_rows.append(item)
    category_percent = {str(item.get("category") or ""): float(item.get("char_percent") or 0.0) for item in category_rows}
    latest_rows = []
    for row in latest:
        item = dict(row)
        item["category_digest_percent"] = round(category_percent.get(str(item.get("category") or ""), 0.0), 2)
        latest_rows.append(item)
    return {
        "ok": True,
        "db_path": str(personal_growth_db_path()),
        "documents": docs,
        "chunks": chunks,
        "characters": chars,
        "text_digest_percent": 100.0 if docs > 0 and chunks > 0 and chars > 0 else 0.0,
        "audio_assets": audio_count,
        "video_assets": video_count,
        "media_assets": audio_count + video_count,
        "latest": latest_rows,
        "categories": category_rows,
        "latest_finetune": dict(latest_finetune) if latest_finetune else None,
    }


def _personal_finetune_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["categories"] = json.loads(str(item.get("categories_json") or "[]"))
    except Exception:
        item["categories"] = []
    return item


def personal_growth_finetune_status(run_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    initialize_personal_growth_database()
    with get_personal_growth_connection() as conn:
        if run_id:
            rows = conn.execute(
                """
                SELECT run_id, status, model_name, categories_json, sample_style, output_path,
                       total_records, records_digested, percent_complete, message,
                       created_at, updated_at, completed_at
                FROM personal_finetune_runs
                WHERE run_id = ?;
                """,
                (str(run_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT run_id, status, model_name, categories_json, sample_style, output_path,
                       total_records, records_digested, percent_complete, message,
                       created_at, updated_at, completed_at
                FROM personal_finetune_runs
                ORDER BY updated_at DESC, id DESC
                LIMIT ?;
                """,
                (max(1, min(100, int(limit or 20))),),
            ).fetchall()
    runs = [_personal_finetune_row_to_dict(row) for row in rows]
    return {"ok": True, "latest": runs[0] if runs else None, "runs": runs, "timestamp_utc": _utc_now()}


def create_personal_growth_finetune_dataset(
    *,
    categories: list[str] | str | None = None,
    model_name: str = "SMI4:26b",
    max_samples: int = 2000,
    sample_style: str = "source_grounded",
) -> dict[str, Any]:
    initialize_personal_growth_database()
    category_list = _normalize_text_list(categories)
    max_records = max(1, min(100000, int(max_samples or 2000)))
    style = str(sample_style or "source_grounded").strip().lower().replace("-", "_")
    if style not in {"source_grounded", "role_guardrail", "mixed"}:
        style = "source_grounded"
    run_id = f"pgft-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    output_path = _personal_finetune_root() / f"{run_id}.jsonl"

    clauses = ["IFNULL(c.content, '') <> ''"]
    params: list[Any] = []
    if category_list:
        placeholders = ",".join("?" for _ in category_list)
        clauses.append(f"IFNULL(d.category, '') IN ({placeholders})")
        params.extend(category_list)
    where = "WHERE " + " AND ".join(clauses)

    with get_personal_growth_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                d.id AS document_id,
                c.id AS chunk_id,
                c.chunk_index AS chunk_index,
                d.source_id AS source_id,
                d.title AS title,
                d.source_type AS source_type,
                d.source_path AS source_path,
                d.category AS category,
                d.purpose AS purpose,
                d.authors AS authors,
                d.publisher AS publisher,
                d.published_date AS published_date,
                c.content AS content
            FROM personal_chunks c
            JOIN personal_documents d ON d.id = c.document_id
            {where}
            ORDER BY d.category ASC, d.id ASC, c.chunk_index ASC
            LIMIT ?;
            """,
            [*params, max_records],
        ).fetchall()
        total = len(rows)
        conn.execute(
            """
            INSERT INTO personal_finetune_runs (
                run_id, status, model_name, categories_json, sample_style, output_path,
                total_records, records_digested, percent_complete, message, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, datetime('now'));
            """,
            (
                run_id,
                "initialized" if total else "empty",
                str(model_name or "SMI4:26b").strip() or "SMI4:26b",
                json.dumps(category_list, ensure_ascii=True),
                style,
                str(output_path),
                total,
                "Personal-growth fine-tune export initialized." if total else "No personal-growth chunks found for the selected categories.",
            ),
        )
        conn.commit()

        digested = 0
        with output_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                title = str(row["title"] or "")
                category = str(row["category"] or "")
                purpose = str(row["purpose"] or "")
                content = str(row["content"] or "").strip()
                source_id = str(row["source_id"] or "")
                context_bits = [bit for bit in [category, purpose, title] if bit]
                context = " / ".join(context_bits)
                instruction = (
                    "Use the provided SMi personal-growth source to answer in a calm, evidence-aware, "
                    "developmental style. Preserve uncertainty, avoid invented facts, and keep the advice practical."
                )
                if context:
                    instruction += f" Context: {context}."
                if style in {"role_guardrail", "mixed"} and category.lower() in {"role-purpose-and-guardrails", "ooda-observation-lab", "rehabilitation-protocol"}:
                    sample_kind = "guardrail_reinforcement"
                    output = (
                        "Operational principle:\n"
                        f"{content}\n\n"
                        "Application rule: use this as a boundary or conduct reminder; do not claim authority, access, or certainty beyond the source."
                    )
                else:
                    sample_kind = "source_grounded_recall"
                    output = (
                        "Source-grounded note:\n"
                        f"{content}\n\n"
                        "Use note: answer from this material only, cite the local source when asked, and state uncertainty where the source is incomplete."
                    )
                sample = {
                    "instruction": instruction,
                    "input": f"Source title: {title}\nSource category: {category}\nSource purpose: {purpose}\n\n{content}",
                    "output": output,
                    "metadata": {
                        "run_id": run_id,
                        "storage_lane": "smi_personal_growth",
                        "document_id": int(row["document_id"]),
                        "chunk_id": int(row["chunk_id"]),
                        "chunk_index": int(row["chunk_index"]),
                        "source_id": source_id,
                        "title": title,
                        "source_type": str(row["source_type"] or ""),
                        "source_path": str(row["source_path"] or ""),
                        "category": category,
                        "purpose": purpose,
                        "authors": str(row["authors"] or ""),
                        "publisher": str(row["publisher"] or ""),
                        "published_date": str(row["published_date"] or ""),
                        "sample_kind": sample_kind,
                        "model_target": str(model_name or "SMI4:26b").strip() or "SMI4:26b",
                    },
                }
                handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
                conn.execute(
                    """
                    INSERT INTO personal_finetune_samples (
                        run_id, document_id, chunk_id, category, sample_kind,
                        instruction, input, output, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        run_id,
                        int(row["document_id"]),
                        int(row["chunk_id"]),
                        category,
                        sample_kind,
                        instruction,
                        sample["input"],
                        output,
                        json.dumps(sample["metadata"], ensure_ascii=True),
                    ),
                )
                digested += 1
                if digested % 100 == 0:
                    percent = round((digested / max(1, total)) * 100.0, 2)
                    conn.execute(
                        """
                        UPDATE personal_finetune_runs
                        SET status = 'building', records_digested = ?, percent_complete = ?,
                            message = ?, updated_at = datetime('now')
                        WHERE run_id = ?;
                        """,
                        (digested, percent, f"Building personal-growth fine-tune export: {digested}/{total}", run_id),
                    )
                    conn.commit()

        final_status = "dataset_ready" if total else "empty"
        conn.execute(
            """
            UPDATE personal_finetune_runs
            SET status = ?, records_digested = ?, percent_complete = ?,
                message = ?, updated_at = datetime('now'), completed_at = datetime('now')
            WHERE run_id = ?;
            """,
            (
                final_status,
                digested,
                100.0 if total else 0.0,
                "Personal-growth fine-tune JSONL is ready for review and external training runtime." if total else "No dataset rows created.",
                run_id,
            ),
        )
        conn.commit()
    return personal_growth_finetune_status(run_id=run_id)


def search_personal_growth(query: str, limit: int = 4) -> list[dict[str, Any]]:
    initialize_personal_growth_database()
    fts_query = _fts_query_from_text(query)
    if not fts_query:
        return []
    with get_personal_growth_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS chunk_id,
                c.document_id AS document_id,
                c.chunk_index AS chunk_index,
                c.content AS content,
                bm25(personal_chunk_fts) AS lexical_score,
                d.source_id AS source_id,
                d.title AS title,
                d.source_type AS source_type,
                '' AS source_url,
                d.source_path AS source_path,
                d.authors AS authors,
                d.publisher AS publisher,
                d.published_date AS published_date,
                'SMi personal growth' AS module,
                d.category AS topic,
                'humanities-and-development' AS scientific_field,
                '' AS vocational_discipline,
                'SMi personal growth database' AS source_collection,
                0 AS priority
            FROM personal_chunk_fts
            JOIN personal_chunks c ON c.id = personal_chunk_fts.rowid
            JOIN personal_documents d ON d.id = c.document_id
            WHERE personal_chunk_fts MATCH ?
            ORDER BY lexical_score ASC
            LIMIT ?;
            """,
            (fts_query, max(1, min(40, int(limit) * 4))),
        ).fetchall()

    results = [dict(row) for row in rows]
    for row in results:
        lexical = float(row.get("lexical_score") or 0.0)
        row["relevance_score"] = 1.0 / (1.0 + max(0.0, lexical))
        row["storage_lane"] = "smi_personal_growth"
    results.sort(key=lambda r: r.get("relevance_score", 0.0), reverse=True)
    return results[: max(1, min(20, int(limit)))]

