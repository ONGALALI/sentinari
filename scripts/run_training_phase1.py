"""Run Sentinari ML ladder stages outside the API server (§57).

Usage (from Sentinari/):
  .venv-ml/Scripts/python.exe scripts/run_training_phase1.py --audit   # stage 1 only
  .venv-ml/Scripts/python.exe scripts/run_training_phase1.py           # stage 2 (CUDA)
  .venv/Scripts/python.exe    scripts/run_training_phase1.py --audit   # app venv works for audit

Stage 2 needs .venv-ml (torch 2.11.0+cu128) — under the app venv it
returns ok:false with torch_unavailable rather than faking a run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sentinari ML ladder runner")
    parser.add_argument("--audit", action="store_true", help="run stage 1 (data parsing audit) only")
    args = parser.parse_args()

    from app import ml_pipeline

    if args.audit:
        print("[stage 1] Data Parsing audit ...")
        r = ml_pipeline.run_data_parsing()
        if not r.get("ok"):
            print(f"  BLOCKED: {r}")
            return 1
        print(f"  library={r['library']} docs={r['documents']} chunks={r['chunks']}")
        print(f"  embedded={r['chunks_embedded']} coverage={r['embed_coverage']:.1%} "
              f"unembedded={r['chunks_unembedded']}")
        print(f"  scientific_fields={r['scientific_fields']} fts={'alive' if r['fulltext_index_alive'] else 'BROKEN'}")
        for d in r["domains"]:
            print(f"    {d['domain']}: {d['chunks']} chunks ({d['embedded']} embedded)")
        print(f"  verdict: {r['verdict']} ({r['duration_seconds']}s)")
        return 0

    print("[stage 2] Training Phase 1 — Sentinari Domain Probe ...")
    r = ml_pipeline.run_training_phase1()
    if not r.get("ok"):
        print(f"  BLOCKED: {r}")
        return 1
    print(f"  backend: {r['backend']}")
    print(f"  rows scanned: {r['rows_scanned']} | train={r['train_size']} val={r['val_size']}")
    for h in r["history"]:
        print(f"  epoch {h['epoch']:2d}: loss={h['train_loss']:.4f} "
              f"train_acc={h['train_acc']:.4f} val_acc={h['val_acc']:.4f}")
    print(f"  best val_acc={r['best_val_acc']:.4f} | artifact={r['artifact']} | {r['duration_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
