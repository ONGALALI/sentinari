"""Sentinari ML pipeline executors — §57.

Makes the first two ladder stages EXECUTE real work on this laptop, at
five-miles-per-hour scale, honestly:

  Stage 1  run_data_parsing()    — audit sentinari.db: docs, chunks,
               embedded ratio, per-domain coverage, FTS integrity.
               Persists a report into the ladder state.
  Stage 2  run_training_phase1() — train the Sentinari Domain Probe on
               REAL stored embeddings (768-d -> 5 domains) with CUDA
               torch (ML venv). Memory-safe batched loading; reports
               train/val accuracy; persists model + metadata.

Honesty rules (house style):
- No fabricated numbers. A stage that cannot run returns ok:false and
  does NOT advance the ladder.
- The probe is a *progress instrument* (like the local HLE grader): it
  proves the training loop, data plumbing, and GPU path end-to-end, and
  gives a real accuracy baseline that improves as embedding coverage
  grows. It is not the qualification benchmark.
- Stage 2 runs OUTSIDE the API server via scripts/run_training_phase1.py
  so heavy torch work never blocks 8099.
"""

from __future__ import annotations

import json
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .config import get_settings  # noqa: E402  (settings path bootstrap)

ML_DIR = ROOT / "data" / "ml"
PROBE_PATH = ML_DIR / "domain_probe.pt"
PROBE_META_PATH = ML_DIR / "domain_probe_meta.json"

EMBED_DIM = 768
DOMAINS = (
    "foundations-of-reality",
    "life-and-biological-systems",
    "human-behavior-and-society",
    "applied-systems-and-technology",
    "health-safety-and-well-being",
)

TRAIN_CAP = 30_000   # five-mph cap — grows later, never shrinks honesty
VAL_CAP = 6_000
EPOCHS = 12
BATCH = 1024
LR = 1e-3
SEED = 47  # §47 lineage


def _library_db() -> Path:
    from .library_router import sentinari_library_path

    return sentinari_library_path()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _persist_stage_report(stage: str, report: dict[str, Any]) -> None:
    from . import assessment_pipeline as ladder

    with ladder._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stage TEXT NOT NULL,
                created_at TEXT NOT NULL,
                report_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO stage_reports (stage, created_at, report_json) VALUES (?, ?, ?)",
            (stage, _now(), json.dumps(report)[:20000]),
        )
        conn.commit()


def last_stage_report(stage: str) -> dict[str, Any] | None:
    from . import assessment_pipeline as ladder

    with ladder._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stage TEXT NOT NULL,
                created_at TEXT NOT NULL,
                report_json TEXT NOT NULL
            )
            """
        )
        row = conn.execute(
            "SELECT report_json FROM stage_reports WHERE stage = ? ORDER BY id DESC LIMIT 1",
            (stage,),
        ).fetchone()
    return json.loads(row[0]) if row else None


# ---------------------------------------------------------------------------
# Stage 1 — Data Parsing
# ---------------------------------------------------------------------------

def run_data_parsing() -> dict[str, Any]:
    """Audit the knowledge library; persist an honest parsing report."""
    from . import assessment_pipeline as ladder

    db_path = _library_db()
    if not db_path.exists():
        ladder.advance("data_parsing", status="blocked", notes="library db missing")
        return {"ok": False, "reason": "library_missing", "detail": f"Library DB not found at {db_path}"}

    t0 = time.time()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    try:
        docs_total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks_total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embedded = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding_json IS NOT NULL AND embedding_json != ''"
        ).fetchone()[0]
        per_domain = conn.execute(
            """
            SELECT d.domain, COUNT(c.id),
                   SUM(CASE WHEN c.embedding_json IS NOT NULL AND c.embedding_json != '' THEN 1 ELSE 0 END)
            FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.domain ORDER BY 2 DESC
            """
        ).fetchall()
        fields = conn.execute(
            "SELECT COUNT(DISTINCT scientific_field) FROM documents WHERE scientific_field IS NOT NULL AND scientific_field != ''"
        ).fetchone()[0]
        fts_ok = conn.execute("SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH 'energy'").fetchone()[0] > 0
    finally:
        conn.close()

    report = {
        "ok": True,
        "library": db_path.name,
        "documents": docs_total,
        "chunks": chunks_total,
        "chunks_embedded": embedded,
        "embed_coverage": round(embedded / chunks_total, 4) if chunks_total else 0.0,
        "chunks_unembedded": chunks_total - embedded,
        "scientific_fields": fields,
        "domains": [
            {"domain": d or "unassigned", "chunks": int(n), "embedded": int(e or 0)}
            for d, n, e in per_domain
        ],
        "fulltext_index_alive": bool(fts_ok),
        "duration_seconds": round(time.time() - t0, 2),
        "verdict": "pass" if (chunks_total > 0 and embedded > 0 and fts_ok) else "fail",
    }

    ladder.advance(
        "data_parsing",
        status="parsed" if report["verdict"] == "pass" else "failed",
        notes=(
            f"docs={docs_total} chunks={chunks_total} embedded={embedded} "
            f"coverage={report['embed_coverage']} fts={'ok' if fts_ok else 'broken'}"
        ),
    )
    _persist_stage_report("data_parsing", report)
    return report


# ---------------------------------------------------------------------------
# Stage 2 — Training Phase 1 (the Domain Probe)
# ---------------------------------------------------------------------------

def _iter_labelled_chunks(batch: int = 2000):
    """Yield (vec, domain_index) pairs lazily so memory stays flat."""
    conn = sqlite3.connect(f"file:{_library_db()}?mode=ro", uri=True, timeout=60)
    try:
        rows = conn.execute(
            """
            SELECT c.embedding_json, d.domain
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.embedding_json IS NOT NULL AND c.embedding_json != ''
              AND d.domain IS NOT NULL AND d.domain != ''
            ORDER BY c.id
            """
        )
        emitted = 0
        for emb_json, domain in rows:
            if emitted >= TRAIN_CAP + VAL_CAP:
                break
            if domain not in DOMAINS:
                continue
            try:
                vec = json.loads(emb_json)
            except Exception:
                continue
            if not isinstance(vec, list) or len(vec) != EMBED_DIM:
                continue
            yield vec, DOMAINS.index(domain)
            emitted += 1
    finally:
        conn.close()


def run_training_phase1() -> dict[str, Any]:
    """Train the Sentinari Domain Probe on real stored embeddings.

    Requires the ML venv (torch 2.11.0+cu128). Memory stays flat by
    building tensors in batches instead of a giant list-of-lists.
    """
    from . import assessment_pipeline as ladder

    t0 = time.time()
    try:
        import torch
        from torch import nn
    except ImportError as ex:
        ladder.advance("training_phase_1", status="blocked", notes="torch unavailable in this venv")
        return {
            "ok": False,
            "reason": "torch_unavailable",
            "detail": f"Stage 2 runs under .venv-ml (scripts/run_training_phase1.py). Import error: {ex}",
        }

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    backend = f"cuda:{torch.cuda.get_device_name(0)}" if device.type == "cuda" else "cpu"

    # --- load in batches, shuffle paired, split ---
    gen = _iter_labelled_chunks()
    batch_vecs: list[list[float]] = []
    batch_labels: list[int] = []
    chunks: list[torch.Tensor] = []
    labels: list[torch.Tensor] = []
    scanned = 0
    for vec, label in gen:
        scanned += 1
        batch_vecs.append(vec)
        batch_labels.append(label)
        if len(batch_vecs) >= 2000:
            chunks.append(torch.tensor(batch_vecs, dtype=torch.float32))
            labels.append(torch.tensor(batch_labels, dtype=torch.long))
            batch_vecs, batch_labels = [], []
    if batch_vecs:
        chunks.append(torch.tensor(batch_vecs, dtype=torch.float32))
        labels.append(torch.tensor(batch_labels, dtype=torch.long))
    if not chunks:
        ladder.advance("training_phase_1", status="blocked", notes="no usable embedded labelled chunks")
        return {"ok": False, "reason": "insufficient_data", "detail": "No usable embedded labelled chunks."}

    X = torch.cat(chunks)
    y = torch.cat(labels)
    del chunks, labels

    g = torch.Generator().manual_seed(SEED)
    perm = torch.randperm(X.shape[0], generator=g)
    X, y = X[perm], y[perm]

    n_val = min(VAL_CAP, max(500, X.shape[0] // 10))
    Xva, yva = X[:n_val].to(device), y[:n_val].to(device)
    Xtr, ytr = X[n_val:].to(device), y[n_val:].to(device)
    if Xtr.shape[0] < 1000:
        ladder.advance("training_phase_1", status="blocked", notes="insufficient training rows")
        return {"ok": False, "reason": "insufficient_data", "detail": f"Only {Xtr.shape[0]} training rows."}

    torch.manual_seed(SEED)
    model = nn.Sequential(
        nn.Linear(EMBED_DIM, 256), nn.ReLU(), nn.Dropout(0.15),
        nn.Linear(256, 64), nn.ReLU(),
        nn.Linear(64, len(DOMAINS)),
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss()

    history = []
    best_val = 0.0
    for epoch in range(1, EPOCHS + 1):
        model.train()
        order = torch.randperm(Xtr.shape[0], device=device)
        total_loss = 0.0
        correct = 0
        for i in range(0, Xtr.shape[0], BATCH):
            idx = order[i:i + BATCH]
            opt.zero_grad()
            logits = model(Xtr[idx])
            loss = loss_fn(logits, ytr[idx])
            loss.backward()
            opt.step()
            total_loss += float(loss.item()) * idx.shape[0]
            correct += int((logits.argmax(dim=1) == ytr[idx]).sum().item())
        train_loss = total_loss / Xtr.shape[0]
        train_acc = correct / Xtr.shape[0]
        model.eval()
        with torch.no_grad():
            val_acc = float((model(Xva).argmax(dim=1) == yva).float().mean().item())
        best_val = max(best_val, val_acc)
        history.append({
            "epoch": epoch,
            "train_loss": round(train_loss, 4),
            "train_acc": round(train_acc, 4),
            "val_acc": round(val_acc, 4),
        })

    ML_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), PROBE_PATH)
    meta = {
        "run_at": _now(),
        "seed": SEED,
        "backend": backend,
        "torch": torch.__version__,
        "train_size": int(Xtr.shape[0]),
        "val_size": int(Xva.shape[0]),
        "rows_scanned": scanned,
        "domains": list(DOMAINS),
        "epochs": EPOCHS,
        "batch": BATCH,
        "lr": LR,
        "best_val_acc": round(best_val, 4),
        "final_val_acc": history[-1]["val_acc"],
        "history": history,
        "model_path": str(PROBE_PATH.relative_to(ROOT)),
        "duration_seconds": round(time.time() - t0, 1),
    }
    PROBE_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    ladder.advance(
        "training_phase_1",
        status="trained",
        notes=(
            f"domain probe: train={meta['train_size']} val={meta['val_size']} "
            f"val_acc={meta['best_val_acc']} device={device.type} (§57)"
        ),
    )
    _persist_stage_report("training_phase_1", meta)

    return {
        "ok": True,
        "backend": backend,
        "train_size": meta["train_size"],
        "val_size": meta["val_size"],
        "rows_scanned": scanned,
        "best_val_acc": meta["best_val_acc"],
        "final_val_acc": meta["final_val_acc"],
        "history": history,
        "artifact": meta["model_path"],
        "duration_seconds": meta["duration_seconds"],
    }
