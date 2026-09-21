"""Re-embed the gemma library onto the gateway's embedding space (§23 cord-cut).

Run AFTER flipping ``runtime_llm.client_backend: gateway`` + ``llm.provider:
gemini``. Uses the exact same client path as the running app
(``build_ollama_client()``), so the vectors written here are byte-compatible
with what ingestion writes at runtime.

Scopes:
  old     — chunks that already carry an embedding (33,905 on 2026-09-21):
            these MUST be migrated; mixed vector spaces poison retrieval.
  missing — chunks never embedded (152,839 on 2026-09-21, a CPU-era gap).
            Filling them restores full semantic retrieval over the library.
  all     — old + missing (the complete job for the new rig).

Resumable: completed ids are recorded in the ``reembed_done`` table; re-run
any time and it continues where it stopped. Dry-run is the default — add
``--apply`` to actually write.

Usage (new rig, after the flip):
    python scripts/reembed_gemini.py                # dry-run report
    python scripts/reembed_gemini.py --scope old --apply --limit 100
    python scripts/reembed_gemini.py --scope all --apply
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.ingestion import build_ollama_client  # noqa: E402  (project import after path setup)


def _embed_dims(client: Any, sample_text: str) -> int:
    vec = client.embed(sample_text)
    if not vec:
        raise SystemExit("FATAL: gateway produced no embedding — check llm.provider/gemini settings.")
    return len(vec)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "library_gemma.db"))
    parser.add_argument("--scope", choices=["old", "missing", "all"], default="old")
    parser.add_argument("--apply", action="store_true", help="Actually write (default: dry-run).")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N chunks (testing).")
    parser.add_argument("--commit-every", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=0.05, help="Pause between requests (rate politeness).")
    args = parser.parse_args()

    client = build_ollama_client()
    print(f"backend: {type(client).__name__} | embed model: {client.embedding_model}")

    conn = sqlite3.connect(args.db, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reembed_done (
            chunk_id INTEGER PRIMARY KEY,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            done_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()

    scope_sql = {
        "old": "content IS NOT NULL AND length(content) > 0 AND embedding_json IS NOT NULL AND length(embedding_json) > 10",
        "missing": "content IS NOT NULL AND length(content) > 0 AND (embedding_json IS NULL OR length(embedding_json) < 10)",
        "all": "content IS NOT NULL AND length(content) > 0",
    }[args.scope]
    rows = conn.execute(
        f"SELECT id, content FROM chunks WHERE {scope_sql} ORDER BY id"
    ).fetchall()
    already = {
        int(r["chunk_id"])
        for r in conn.execute("SELECT chunk_id FROM reembed_done WHERE model = ?", (client.embedding_model,)).fetchall()
    }
    todo = [(int(r["id"]), str(r["content"])) for r in rows if int(r["id"]) not in already]
    if args.limit:
        todo = todo[: args.limit]
    print(f"scope={args.scope}: {len(rows)} candidate(s), {len(todo)} to embed (resuming past {len(already)} done)")

    if not args.apply:
        print("DRY-RUN — add --apply to execute. No changes written.")
        return 0
    if not todo:
        print("Nothing to do — scope already complete.")
        return 0

    # Probe once: the vector space must match the runtime schema (768) before
    # a single row is written.
    probe_dims = _embed_dims(client, todo[0][1][:1000])
    print(f"probe embedding dims: {probe_dims}")
    if probe_dims != 768:
        raise SystemExit(
            f"FATAL: embedding dims = {probe_dims}, library schema = 768. "
            "Fix llm.gemini.embedding_dimensions before migrating."
        )

    started = time.time()
    done = 0
    batch = 0
    for chunk_id, content in todo:
        vec = client.embed(content[:8000])
        if vec and len(vec) == probe_dims:
            conn.execute(
                "UPDATE chunks SET embedding_json = ? WHERE id = ?",
                (json.dumps(vec, ensure_ascii=True), chunk_id),
            )
            conn.execute(
                "INSERT OR REPLACE INTO reembed_done (chunk_id, model, dims) VALUES (?, ?, ?)",
                (chunk_id, client.embedding_model, len(vec)),
            )
            batch += 1
        else:
            print(f"  WARN: chunk {chunk_id} embed failed/mismatched — skipped (re-run resumes)")
        done += 1
        if batch >= args.commit_every:
            conn.commit()
            batch = 0
            rate = done / max(1e-9, time.time() - started)
            eta_min = (len(todo) - done) / max(1e-9, rate) / 60
            print(f"  {done}/{len(todo)} ({100 * done / len(todo):.1f}%) | {rate:.1f}/s | ETA {eta_min:.0f} min")
        if args.sleep:
            time.sleep(args.sleep)
    conn.commit()
    print(f"DONE: {done} processed in {(time.time() - started) / 60:.1f} min — library fully on {client.embedding_model} @ {probe_dims} dims.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
