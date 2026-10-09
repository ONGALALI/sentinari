"""Sentinari Telemetry Extractor & Normalization Pipeline (§77, corrections 1).

Gemma is the Analytical Engine (the Brain); the databases are the Open-Book
Library (the Memory). This module converts unstructured stored text into the
strict Article V structure — falsifiable claims, numerical metrics, provenance
— so retrieval can feed Gemma crisp, weight-stable context slices instead of
raw document dumps.

Design constraints from the corrections file:
- Batch-oriented and resumable: (source_table, source_rowid) pairs already
  mapped are skipped, so re-running only processes new rows.
- Never re-parses the telemetry table itself.
- Deterministic observation ids (hash-based) so re-runs are idempotent.

Run directly, or call ``extract_and_map_telemetry()`` from a worker.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_project_root
from .rag.indexer import scan_text_columns

# Databases eligible for telemetry capture: the live Gemma library first,
# then any legacy SMI libraries still on disk.
def _candidate_databases() -> list[Path]:
    from .library_router import gemma_library_path

    dbs = [gemma_library_path()]
    legacy = get_project_root() / "data" / "smi_vocationalllm.db"
    if legacy.exists() and legacy != dbs[0]:
        dbs.append(legacy)
    return dbs


_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:\s*(?:%|percent|kg|km|ms|s|GHz|MHz|MB|GB|K|°C))?", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?])\s+")

_FIELD_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("gene", "covid", "virus", "protein", "receptor", "enzyme", "cell", "genome"),
        "life-and-biological-systems",
    ),
    (
        ("temp", "thermo", "velocity", "quantum", "particle", "gravity", "enthalpy", "entropy"),
        "foundations-of-reality",
    ),
    (
        ("algorithm", "sqlite", "matrix", "network", "compiler", "latency", "throughput", "runtime"),
        "computer-and-information-sciences",
    ),
    (
        ("market", "policy", "population", "survey", "wage", "governance", "education"),
        "human-behavior-and-society",
    ),
    (
        ("diagnosis", "clinical", "patient", "safety", "wellbeing", "symptom", "treatment"),
        "health-safety-and-well-being",
    ),
)

# Tables whose rows are operational logs, not knowledge.
_SKIP_TABLE_MARKERS = (
    "article_v_knowledge",
    "sqlite_sequence",
    "chat_",
    "smi_tasks",
    "smi_profile",
    "smi_operator",
    "qualia",
    "file_ingest_state",
    "ingest_events",
    "unsupervised_",
    "skill_review_",
    "scout_blocklist",
    "session_",
    "learning_",
    "app_runtime_state",
    "taxonomy_nodes",
    "coding_agent_",
    "video_",
    "_fts",
    "_data",
    "_idx",
    "_docsize",
    "_config",
    "legacy",  # archived snapshots are already captured elsewhere
)


def initialize_telemetry_table(conn: sqlite3.Connection) -> None:
    """Establishes the immutable, structured table for Article V knowledge maps."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS article_v_knowledge (
            observation_id TEXT PRIMARY KEY,
            source_db TEXT NOT NULL DEFAULT '',
            source_table TEXT NOT NULL,
            source_rowid INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            scientific_field TEXT,
            falsifiable_claims TEXT NOT NULL DEFAULT '[]',
            numerical_metrics TEXT NOT NULL DEFAULT '[]',
            epistemic_confidence REAL NOT NULL DEFAULT 1.0,
            provenance_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_article_v_source ON article_v_knowledge(source_table, source_rowid);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_article_v_field ON article_v_knowledge(scientific_field);"
    )
    conn.commit()


def _is_skippable_table(table: str) -> bool:
    lowered = table.lower()
    return any(marker in lowered for marker in _SKIP_TABLE_MARKERS)


def _infer_field(text_lower: str, declared: str = "") -> str:
    """Declared field wins; otherwise a conservative keyword inference."""
    declared = (declared or "").strip()
    if declared:
        return declared
    for hints, field in _FIELD_HINTS:
        if any(hint in text_lower for hint in hints):
            return field
    return "general-science"


def _extract_claims(text: str, max_claims: int = 3) -> list[str]:
    """Atomic, falsifiable-looking sentences (longest first, deduplicated)."""
    candidates = [
        s.strip()
        for s in _SENTENCE_SPLIT_RE.split(text)
        if len(s.strip()) >= 60 and any(ch.isalpha() for ch in s)
    ]
    candidates.sort(key=len, reverse=True)
    claims: list[str] = []
    for candidate in candidates:
        if any(candidate.lower()[:80] in c.lower() for c in claims):
            continue
        claims.append(candidate)
        if len(claims) >= max_claims:
            break
    return claims


def _extract_metrics(text: str, max_metrics: int = 8) -> list[str]:
    metrics: list[str] = []
    for match in _NUMBER_RE.finditer(text):
        token = match.group(0).strip()
        if token and token not in metrics:
            metrics.append(token)
            if len(metrics) >= max_metrics:
                break
    return metrics


def _observation_id(source_db: str, table: str, rowid: int, text: str) -> str:
    digest = hashlib.sha256(f"{source_db}|{table}|{rowid}|{text[:512]}".encode("utf-8", errors="replace")).hexdigest()
    return f"telemetry:{source_db}:{table}:{rowid}:{digest[:16]}"


def _already_mapped(conn: sqlite3.Connection) -> set[tuple[str, int]]:
    return {
        (str(row["source_table"]), int(row["source_rowid"]))
        for row in conn.execute("SELECT source_table, source_rowid FROM article_v_knowledge;")
    }


_UNWANTED_COLUMN_MARKERS = (
    "embedding", "json", "hash", "checksum", "path", "url", "id", "key", "token",
)


def _is_prose_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    """Keep only columns that actually hold long prose (not numeric ids,
    not stored JSON blobs like embedding_json)."""
    lowered = col.lower()
    if any(marker in lowered for marker in _UNWANTED_COLUMN_MARKERS):
        return False
    try:
        rows = conn.execute(f'SELECT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL LIMIT 5').fetchall()
    except sqlite3.Error:
        return False
    text_like = 0
    for r in rows:
        val = r[0]
        if isinstance(val, bytes):
            val = val.decode("utf-8", errors="ignore")
        if isinstance(val, str) and len(val.strip()) >= 40 and not val.lstrip().startswith(("{", "[")):
            text_like += 1
    return text_like >= max(1, len(rows) // 2)


def extract_from_database(db_path: Path, *, batch_commit: int = 200) -> int:
    """Capture telemetry from one database. Returns the number of new entries."""
    if not db_path.exists():
        raise FileNotFoundError(f"Source database not found at {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    initialize_telemetry_table(conn)
    mapped = _already_mapped(conn)
    candidates = [
        (t, c)
        for (t, c) in scan_text_columns(conn)
        if not _is_skippable_table(t) and _is_prose_column(conn, t, c)
    ]
    if not candidates:
        print("[-] No valid source columns identified for telemetry capture.")
        conn.close()
        return 0

    source_db_key = db_path.stem
    processed = 0
    pending = 0
    timestamp_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for table, col in candidates:
        print(f"[*] Extracting telemetry signatures from {table}.{col}...")
        try:
            rows = conn.execute(
                f'SELECT rowid AS _rid, "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL'
            ).fetchall()
        except sqlite3.Error as exc:
            print(f"[-] Read failure on {table}.{col}: {exc}")
            continue

        for row in rows:
            rowid = int(row["_rid"])
            if (table, rowid) in mapped:
                continue
            raw_text = row[col]
            if isinstance(raw_text, bytes):
                raw_text = raw_text.decode("utf-8", errors="ignore")
            raw_text = str(raw_text or "").strip()
            if len(raw_text) < 40:
                continue

            text_lower = raw_text.lower()
            declared = ""
            try:
                meta_row = conn.execute(
                    f'SELECT scientific_field FROM "{table}" WHERE rowid = ?',
                    (rowid,),
                ).fetchone()
                declared = str(meta_row["scientific_field"]) if meta_row is not None else ""
            except sqlite3.Error:
                declared = ""

            observation_id = _observation_id(source_db_key, table, rowid, raw_text)
            claims = _extract_claims(raw_text)
            metrics = _extract_metrics(raw_text)
            provenance = {
                "origin_database": db_path.name,
                "origin_table": table,
                "origin_column": col,
                "origin_rowid": rowid,
                "ingest_timestamp": timestamp_iso,
            }
            try:
                conn.execute(
                    """
                    INSERT INTO article_v_knowledge (
                        observation_id, source_db, source_table, source_rowid, timestamp,
                        scientific_field, falsifiable_claims, numerical_metrics,
                        epistemic_confidence, provenance_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        source_db_key,
                        table,
                        rowid,
                        timestamp_iso,
                        _infer_field(text_lower, declared),
                        json.dumps(claims, ensure_ascii=False),
                        json.dumps({"values": metrics, "text_length_chars": len(raw_text)}),
                        0.90,
                        json.dumps(provenance, ensure_ascii=False),
                    ),
                )
                processed += 1
                pending += 1
                if pending >= batch_commit:
                    conn.commit()
                    pending = 0
            except sqlite3.Error as write_err:
                print(f"[-] Insertion failure for observation {observation_id}: {write_err}")

        conn.commit()

    print(f"[+] Telemetry sync for {db_path.name} complete. Structured {processed} new entries.")
    conn.close()
    return processed


def extract_and_map_telemetry() -> dict[str, Any]:
    """Capture Article V telemetry from every eligible database."""
    results: dict[str, int] = {}
    for db_path in _candidate_databases():
        try:
            results[db_path.name] = extract_from_database(db_path)
        except FileNotFoundError:
            print(f"[-] Skipping missing database: {db_path.name}")
        except sqlite3.Error as exc:
            print(f"[-] Database error on {db_path.name}: {exc}")
            results[db_path.name] = 0
    total = sum(results.values())
    print(f"[+] Telemetry pipeline sync complete. Structured {total} new entries across {len(results)} database(s).")
    return {"total_new": total, "per_database": results}


def fetch_telemetry_for_query(
    query: str,
    *,
    limit: int = 3,
    fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Crisp telemetry context slices for Gemma (open-book memory read).

    Matches query terms against stored falsifiable claims; optionally scoped
    to one or more scientific fields. Never raises.
    """
    try:
        from .library_router import gemma_library_path

        db_path = gemma_library_path()
        if not db_path.exists():
            return []
        terms = [t for t in re.findall(r"[a-zA-Z]{4,}", (query or "").lower()) if t][:8]
        if not terms:
            return []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            initialize_telemetry_table(conn)
            like_clauses = " OR ".join("falsifiable_claims LIKE ?" for _ in terms)
            args: list[Any] = [f"%{t}%" for t in terms]
            sql = f"""
                SELECT observation_id, scientific_field, falsifiable_claims,
                       numerical_metrics, provenance_json, timestamp
                FROM article_v_knowledge
                WHERE ({like_clauses})
            """
            if fields:
                placeholders = ",".join("?" for _ in fields)
                sql += f" AND scientific_field IN ({placeholders})"
                args.extend(fields)
            sql += " ORDER BY epistemic_confidence DESC, timestamp DESC LIMIT ?"
            args.append(max(1, min(8, int(limit))))
            return [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]
        finally:
            conn.close()
    except Exception:
        return []


if __name__ == "__main__":
    extract_and_map_telemetry()
