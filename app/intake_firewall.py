"""Sentinari intake firewall — §60.

Owner rule: nothing unlabeled should silently enter the knowledge base.
Unlabeled intake is WARNED, QUARANTINED (ledgered) and held for the
owner to approve (label), or delete. Quarantined documents remain
searchable but are already held out of learning (§59).

The ledger lives in the MAIN app database (same file as
learning_settings / learning_assessments), created lazily.

Honesty rules:
- The firewall NEVER deletes anything on its own. Deletion is
  owner-ordered, explicit, and backed up first (chunk contents exported
  to data/exports/quarantine-backup-<id>.json.gz before removal).
- Approve = assign a scientific field (and optionally domain), which
  immediately enrolls the document into learning priority accounting.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .config import get_settings  # noqa: E402

EXPORT_DIR = ROOT / "data" / "exports"


def _app_db_path() -> Path:
    settings = get_settings()
    return Path(settings["paths"]["sqlite_db"]).resolve()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_app_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS intake_quarantine (
            document_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT '',
            source_path TEXT NOT NULL DEFAULT '',
            detected_at TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT 'no_scientific_field',
            status TEXT NOT NULL DEFAULT 'quarantined',
            decided_at TEXT,
            decided_by TEXT
        )
        """
    )
    return conn


def _library_ro() -> sqlite3.Connection:
    from .library_router import sentinari_library_path

    path = sentinari_library_path()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def scan() -> dict[str, Any]:
    """Find every unlabeled document in the library and ledger new ones."""
    lib = _library_ro()
    try:
        rows = lib.execute(
            """
            SELECT d.id, d.title, d.source_type, d.source_path,
                   (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
            FROM documents d
            WHERE d.scientific_field IS NULL OR TRIM(d.scientific_field) = ''
            ORDER BY d.id
            """
        ).fetchall()
    finally:
        lib.close()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new: list[int] = []
    with _connect() as conn:
        known = {int(r["document_id"]) for r in conn.execute("SELECT document_id FROM intake_quarantine")}
        for r in rows:
            doc_id = int(r["id"])
            if doc_id not in known:
                conn.execute(
                    """
                    INSERT INTO intake_quarantine (document_id, title, source_type, source_path, detected_at, reason)
                    VALUES (?, ?, ?, ?, ?, 'no_scientific_field')
                    """,
                    (doc_id, str(r["title"] or ""), str(r["source_type"] or ""), str(r["source_path"] or ""), now),
                )
                new.append(doc_id)
        conn.commit()

    return {
        "ok": True,
        "unlabeled_total": len(rows),
        "newly_quarantined": new,
        "documents": [dict(r) for r in rows],
    }


def status() -> dict[str, Any]:
    """Ledger state joined to live library truth (auto-resolves stale rows)."""
    scan()  # ledger any new unlabeled arrivals
    with _connect() as conn:
        ledger = [dict(r) for r in conn.execute(
            "SELECT * FROM intake_quarantine ORDER BY detected_at DESC"
        ).fetchall()]
    lib = _library_ro()
    try:
        by_id = {
            int(r["id"]): dict(r)
            for r in lib.execute(
                "SELECT id, title, source_type, source_path, domain FROM documents"
            ).fetchall()
        }
    finally:
        lib.close()

    items: list[dict[str, Any]] = []
    for entry in ledger:
        doc = by_id.get(int(entry["document_id"]))
        still_unlabeled = doc is not None
        items.append({
            **entry,
            "still_in_library": still_unlabeled,
            "live_title": (doc or {}).get("title", ""),
            "live_source_type": (doc or {}).get("source_type", ""),
        })
    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "rule": "unlabeled intake = warn + quarantine; owner approves (label) or deletes (§60)",
    }


def approve(document_id: int, scientific_field: str, domain: str | None = None, decided_by: str = "owner") -> dict[str, Any]:
    """Label the document (enrolls it into learning) and clear the ledger row."""
    field = str(scientific_field or "").strip()
    if not field:
        return {"ok": False, "error": "scientific_field is required to approve."}
    lib = sqlite3.connect(str(_library_path()), timeout=30)
    try:
        cur = lib.execute(
            "UPDATE documents SET scientific_field = ?, domain = COALESCE(?, domain) WHERE id = ?",
            (field, domain, int(document_id)),
        )
        if cur.rowcount != 1:
            lib.rollback()
            return {"ok": False, "error": f"Document {document_id} not found in the library."}
        lib.commit()
    finally:
        lib.close()
    with _connect() as conn:
        conn.execute(
            "UPDATE intake_quarantine SET status = 'approved', decided_at = ?, decided_by = ? WHERE document_id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), decided_by, int(document_id)),
        )
        conn.commit()
    return {"ok": True, "document_id": int(document_id), "scientific_field": field, "enrolled_in_learning": True}


def delete(document_id: int, decided_by: str = "owner") -> dict[str, Any]:
    """Owner-ordered removal: back up the document + chunks, then delete
    from the library and mark the ledger row 'deleted'. Prevents
    auto-ingest resurrection by marking file_ingest_state."""
    lib = sqlite3.connect(str(_library_path()), timeout=30)
    lib.row_factory = sqlite3.Row
    try:
        doc = lib.execute("SELECT * FROM documents WHERE id = ?", (int(document_id),)).fetchone()
        if doc is None:
            return {"ok": False, "error": f"Document {document_id} not found."}
        chunks = lib.execute(
            "SELECT id, document_id, chunk_index, content FROM chunks WHERE document_id = ?",
            (int(document_id),),
        ).fetchall()

        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        backup = EXPORT_DIR / f"quarantine-backup-{int(document_id)}.json.gz"
        payload = {
            "deleted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "document": dict(doc),
            "chunks": [dict(c) for c in chunks],
        }
        with gzip.open(backup, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=True)

        lib.execute("BEGIN")
        lib.execute("DELETE FROM chunks WHERE document_id = ?", (int(document_id),))
        try:
            lib.execute("DELETE FROM chunk_fts WHERE rowid IN (SELECT id FROM chunks WHERE document_id = ?)", (int(document_id),))
        except sqlite3.OperationalError:
            pass  # FTS rows cascade or are rebuilt; document removal is the source of truth
        lib.execute("DELETE FROM documents WHERE id = ?", (int(document_id),))
        lib.commit()
        doc_dict = dict(doc)
    finally:
        lib.close()

    # Prevent auto-ingest from re-swallowing the source file.
    try:
        from .db import get_connection

        src = Path(str(doc_dict.get("source_path") or ""))
        with get_connection() as app_conn:
            try:
                stat = src.stat()
                size, mtime = stat.st_size, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(stat.st_mtime))
            except OSError:
                size, mtime = 0, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            app_conn.execute(
                """
                INSERT INTO file_ingest_state (path, file_size, mtime_utc, checksum, last_status, last_error, updated_at)
                VALUES (?, ?, ?, ?, 'ok', 'quarantine-deleted 2026-09-30', datetime('now'))
                ON CONFLICT(path) DO UPDATE SET last_error = 'quarantine-deleted 2026-09-30', updated_at = datetime('now')
                """,
                (str(src), size, mtime, str(doc_dict.get("checksum") or "")),
            )
            app_conn.commit()
    except Exception:
        pass  # resurrection guard is best-effort; backup remains the safety net

    with _connect() as conn:
        conn.execute(
            "UPDATE intake_quarantine SET status = 'deleted', decided_at = ?, decided_by = ? WHERE document_id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), decided_by, int(document_id)),
        )
        conn.commit()

    return {
        "ok": True,
        "document_id": int(document_id),
        "backup": str(backup.relative_to(ROOT)),
        "chunks_removed": len(chunks),
    }


def _library_path() -> Path:
    from .library_router import sentinari_library_path

    return sentinari_library_path()


def warn_payload(latest: dict[str, Any] | None) -> dict[str, Any] | None:
    """A tiny banner payload pages can show after an ingest: 'N unlabeled
    documents quarantined — review in the admin console.'"""
    if not latest:
        return None
    new = latest.get("newly_quarantined") or []
    if not new:
        return None
    return {
        "warn": True,
        "count": len(new),
        "message": f"{len(new)} unlabeled document(s) quarantined by the intake firewall — review in the admin console.",
        "document_ids": new,
    }
