"""Purge UI-code documents from the gemma library (§31, owner-directed).

Sentinel's own UI templates and app code were auto-digested into the knowledge
base before the code-exclusion guard existed. They are engineering artifacts,
not knowledge — this script removes them (documents + chunks + FTS rows), with
a gzip backup written first.

Dry-run by default. Apply with:  --apply
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import library_connection  # noqa: E402

PROJECT_ROOT = str(ROOT).replace("\\", "/").rstrip("/").lower()
CODE_TOP_DIRS = {"templates", "app", "scripts", "config"}


def _is_code_path(source: str) -> bool:
    """True only for files INSIDE Sentinel's own code dirs, i.e. paths under
    <project root>/templates|app|scripts|config. Dataset files that merely
    contain a 'scripts' or 'app' folder somewhere (e.g. github repos inside
    scientific-field containers) are NOT code paths and must be kept."""
    path = str(source or "").replace("\\", "/").rstrip("/").lower()
    if not path.startswith(PROJECT_ROOT + "/"):
        return False
    relative = path[len(PROJECT_ROOT) + 1 :]
    top_dir = relative.split("/", 1)[0]
    return top_dir in CODE_TOP_DIRS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually delete")
    args = parser.parse_args()

    with library_connection("gemma") as conn:
        rows = conn.execute(
            "SELECT id, title, source_path FROM documents"
        ).fetchall()
        doomed = [dict(row) for row in rows if _is_code_path(row["source_path"])]

        print(f"documents to purge: {len(doomed)}")
        for row in doomed:
            print(f"  [{row['id']}] {row['title']}")

        if not doomed:
            print("nothing to purge.")
            return 0

        doc_ids = [int(row["id"]) for row in doomed]
        placeholders = ",".join("?" for _ in doc_ids)
        chunk_count = int(
            conn.execute(
                f"SELECT COUNT(1) AS n FROM chunks WHERE document_id IN ({placeholders});",
                doc_ids,
            ).fetchone()["n"]
        )
        print(f"chunks covered: {chunk_count}")

        if not args.apply:
            print("dry-run only (no changes). Re-run with --apply to execute.")
            return 0

        backup_path = ROOT / "data" / "exports" / "purge-backup-ui-code.json.gz"
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        doc_rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM documents WHERE id IN ({placeholders});", doc_ids
            ).fetchall()
        ]
        chunk_rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM chunks WHERE document_id IN ({placeholders});",
                doc_ids,
            ).fetchall()
        ]
        manifest = {
            "purged": "ui-code documents (auto-ingest pollution, pre-guard)",
            "documents": doc_rows,
            "chunks": chunk_rows,
            "count_documents": len(doc_rows),
            "count_chunks": len(chunk_rows),
        }
        with gzip.open(backup_path, "wt", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, default=str)
        print(f"backup written: {backup_path}")

        conn.execute(
            f"DELETE FROM chunks WHERE document_id IN ({placeholders});", doc_ids
        )
        conn.execute(
            f"DELETE FROM chunk_fts WHERE document_id IN ({placeholders});", doc_ids
        )
        conn.execute(
            f"DELETE FROM documents WHERE id IN ({placeholders});", doc_ids
        )
        conn.commit()

        remnants_docs = int(
            conn.execute(
                f"SELECT COUNT(1) AS n FROM documents WHERE id IN ({placeholders});",
                doc_ids,
            ).fetchone()["n"]
        )
        remnants_chunks = int(
            conn.execute(
                f"SELECT COUNT(1) AS n FROM chunks WHERE document_id IN ({placeholders});",
                doc_ids,
            ).fetchone()["n"]
        )
        print(f"purged documents: {len(doc_ids)}, chunks: {chunk_count}")
        print(f"remnants: docs={remnants_docs}, chunks={remnants_chunks}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
