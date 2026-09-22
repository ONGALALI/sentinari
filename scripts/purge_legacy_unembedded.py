"""Purge legacy never-embedded chunks outside the Sentinel field containers.

Owner-approved scope (2026-09-22, after review listing):
  - documents with a BLANK scientific_field,
  - whose source_path is OUTSIDE data/knowledge_taxonomy/scientific_fields,
  - whose chunks carry no embedding (the never-embedded backlog),
  - which are duplicates of archived originals or stale session instructions.

Everything else — including the 104,784 computer-and-information-sciences
chunks (Qwen-era coding corpus) — is deliberately KEPT pending the owner's
separate decision, and every field-labeled document (Sentinel-v2, the
Constitution, concept papers) is untouched.

Safety: a gzip backup of every doomed document row + full chunk text is
written BEFORE deletion, and file_ingest_state 'ok' rows prevent auto-ingest
from resurrecting the purged sources. Run with --apply to execute; default
is a dry-run that prints exactly what would go.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DB = PROJECT_ROOT / "data" / "library_gemma.db"
BACKUP = PROJECT_ROOT / "data" / "exports" / "purge-backup-legacy-unembedded.json.gz"
MANIFEST = PROJECT_ROOT / "Logs" / "purge-legacy-unembedded-manifest.json"

DOOMED_SQL = r"""
    SELECT DISTINCT d.id
    FROM chunks c JOIN documents d ON d.id = c.document_id
    WHERE (c.embedding_json IS NULL OR length(c.embedding_json) < 10)
      AND c.content IS NOT NULL AND length(c.content) > 0
      AND REPLACE(d.source_path, '\', '/') NOT LIKE '%scientific_fields%'
      AND COALESCE(NULLIF(d.scientific_field, ''), '') = ''
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Execute the purge (default: dry-run).")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000;")

    doc_ids = [int(r["id"]) for r in conn.execute(DOOMED_SQL).fetchall()]
    if not doc_ids:
        print("Nothing matches the purge predicate — already clean.")
        return 0
    placeholders = ",".join("?" for _ in doc_ids)

    docs = conn.execute(
        f"SELECT * FROM documents WHERE id IN ({placeholders})", doc_ids
    ).fetchall()
    chunks = conn.execute(
        f"SELECT id, document_id, chunk_index, content FROM chunks WHERE document_id IN ({placeholders})",
        doc_ids,
    ).fetchall()

    print(f"purge set: {len(doc_ids)} documents, {len(chunks)} chunks (blank field, outside containers, never embedded)")
    for d in docs:
        print(f"  #{d['id']:<6} [{d['source_type'] or '?':<6}] {(d['title'] or '')[:60]}")

    if not args.apply:
        print("DRY-RUN — add --apply to execute. No changes written.")
        return 0

    # 1. Backup before anything is deleted.
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "purged_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "documents": [dict(d) for d in docs],
        "chunks": [dict(c) for c in chunks],
    }
    with gzip.open(BACKUP, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "backup": str(BACKUP),
                "document_ids": doc_ids,
                "chunk_count": len(chunks),
                "titles": [str(d["title"] or "") for d in docs],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"backup written: {BACKUP.name} ({BACKUP.stat().st_size:,} bytes) + manifest")

    # 2. Prevent auto-ingest resurrection of the purged source files.
    #    file_ingest_state lives in the MAIN app database, not the library —
    #    use the app's own connection factory so the schema matches exactly.
    from app.db import get_connection as _app_connection

    state_rows = []
    for d in docs:
        src = Path(str(d["source_path"] or ""))
        try:
            stat = src.stat()
            state_rows.append((str(src), stat.st_size, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(stat.st_mtime)), str(d["checksum"] or ""), "ok", "purged-legacy-unembedded 2026-09-22"))
        except OSError:
            state_rows.append((str(src), 0, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), str(d["checksum"] or ""), "ok", "purged-legacy-unembedded 2026-09-22 (source gone)"))
    with _app_connection() as app_conn:
        app_conn.executemany(
            """
            INSERT INTO file_ingest_state (path, file_size, mtime_utc, checksum, last_status, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(path) DO UPDATE SET
                last_status = excluded.last_status,
                last_error = excluded.last_error,
                updated_at = datetime('now')
            """,
            state_rows,
        )
        app_conn.commit()

    # 3. Delete chunks + FTS + documents, atomically.
    conn.execute("BEGIN")
    conn.execute(f"DELETE FROM chunk_fts WHERE document_id IN ({placeholders})", doc_ids)
    conn.execute(f"DELETE FROM chunks WHERE document_id IN ({placeholders})", doc_ids)
    conn.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", doc_ids)
    conn.commit()

    remaining_docs = conn.execute(
        f"SELECT COUNT(*) AS n FROM documents WHERE id IN ({placeholders})", doc_ids
    ).fetchone()["n"]
    remaining_chunks = conn.execute(
        f"SELECT COUNT(*) AS n FROM chunks WHERE document_id IN ({placeholders})", doc_ids
    ).fetchone()["n"]
    total_chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
    total_missing = conn.execute(
        "SELECT COUNT(*) AS n FROM chunks WHERE (embedding_json IS NULL OR length(embedding_json) < 10) AND content IS NOT NULL AND length(content) > 0"
    ).fetchone()["n"]
    print(f"verified: {remaining_docs} doomed docs remain, {remaining_chunks} doomed chunks remain (must be 0)")
    print(f"library now: {total_chunks:,} chunks total, {total_missing:,} never-embedded remain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
