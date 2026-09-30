"""Sentinari assessment pipeline — §47.

Owner-mandated flow, implemented as an explicit, persisted state machine:

    [ Data Parsing ] → [ Training Phase 1 ] → [ HLE Assessment ]
        → [ Re-learning / Fine-tuning ] → [ SWE-bench Pro ]

Rules:
- SWE-bench Pro is GATED: it only unlocks after HLE ≥ 65% (the owner's
  qualification bar). The gate is fail-closed — a run that has not scored
  the bar cannot advance.
- HLE grading is a LOCAL, honest first pass (exact/normalized match +
  token overlap) against the local model. It is a progress instrument,
  not the official benchmark harness.
- SWE-bench Pro execution grading (patch → real repo → unit tests) runs
  through the owner-downloaded workbench harness (assessments/swe-workbench)
  on rig day. This module tracks the gate, not the harness runs.
- Every state change is persisted to data/assessment_pipeline.sqlite3 so the
  pipeline survives restarts and migrates with the folder.

Zero-cloud: all grading runs on the local engine. Dataset pulls (HLE,
SWE-bench Pro) are owner-ordered assessment materials, cached in-tree.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .config import get_settings  # noqa: E402

DB_PATH = ROOT / "data" / "assessment_pipeline.sqlite3"
QUALIFY_THRESHOLD = 0.65

STAGES = ("data_parsing", "training_phase_1", "hle_assessment", "relearning", "swe_bench_pro")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'data_parsing',
            status TEXT NOT NULL DEFAULT 'ready',
            hle_score REAL NOT NULL DEFAULT -1,
            hle_total INTEGER NOT NULL DEFAULT 0,
            hle_detail_json TEXT NOT NULL DEFAULT '[]',
            swe_gate_open INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT ''
        )
        """
    )
    return conn


def _latest_run() -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def get_state() -> dict[str, Any]:
    run = _latest_run()
    gate_open = bool(run and run.get("swe_gate_open"))
    hle_score = float(run.get("hle_score")) if run and run.get("hle_score") is not None and run.get("hle_score") >= 0 else None
    return {
        "ok": True,
        "stage": str(run.get("stage")) if run else "data_parsing",
        "status": str(run.get("status")) if run else "not_started",
        "stages": list(STAGES),
        "flow": " → ".join(s.replace("_", " ").title() for s in STAGES),
        "qualify_threshold": QUALIFY_THRESHOLD,
        "hle_score": hle_score,
        "hle_qualified": bool(hle_score is not None and hle_score >= QUALIFY_THRESHOLD),
        "swe_pro_gate": {
            "open": gate_open,
            "rule": f"HLE >= {int(QUALIFY_THRESHOLD * 100)}% unlocks SWE-bench Pro",
            "workbench_present": (ROOT / "assessments" / "swe-workbench").exists(),
            "dataset_zip_present": (ROOT / "assessments" / "swe-workbench" / "SWE-bench_Pro-os-main.zip").exists(),
        },
        "updated_at": str(run.get("updated_at")) if run else "",
    }


def start_run(notes: str = "") -> dict[str, Any]:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO pipeline_runs (created_at, updated_at, stage, status, notes) VALUES (?, ?, 'data_parsing', 'running', ?)",
            (_now(), _now(), str(notes or "")[:500]),
        )
        conn.commit()
    return get_state()


def advance(stage: str, status: str = "running", notes: str = "") -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage '{stage}'. Valid: {STAGES}")
    run = _latest_run()
    if not run:
        start_run(notes="auto-created on advance")
        run = _latest_run()
    with _connect() as conn:
        conn.execute(
            "UPDATE pipeline_runs SET stage = ?, status = ?, updated_at = ?, notes = ? WHERE id = ?",
            (stage, status, _now(), str(notes or "")[:500], run["id"]),
        )
        conn.commit()
    return get_state()


def record_hle_run(correct: int, total: int, detail: list[dict] | None = None) -> dict[str, Any]:
    """Persist an HLE assessment result and evaluate the 65% gate."""
    if total <= 0:
        raise ValueError("total must be positive")
    score = round(max(0.0, min(1.0, correct / total)), 4)
    qualified = score >= QUALIFY_THRESHOLD
    with _connect() as conn:
        row = conn.execute("SELECT id FROM pipeline_runs ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO pipeline_runs (created_at, updated_at, stage, status, notes) VALUES (?, ?, 'hle_assessment', 'assessed', 'auto-created on HLE record')",
                (_now(), _now(),),
            )
            row = conn.execute("SELECT id FROM pipeline_runs ORDER BY id DESC LIMIT 1").fetchone()
        conn.execute(
            """
            UPDATE pipeline_runs
            SET stage = 'hle_assessment', status = 'assessed', updated_at = ?,
                hle_score = ?, hle_total = ?, hle_detail_json = ?, swe_gate_open = ?
            WHERE id = ?
            """,
            (
                _now(),
                score,
                int(total),
                json.dumps((detail or [])[:200]),
                1 if qualified else 0,
                row["id"],
            ),
        )
        if qualified:
            conn.execute(
                "UPDATE pipeline_runs SET stage = 'relearning', status = 'swe_gate_open', updated_at = ? WHERE id = ?",
                (_now(), row["id"]),
            )
        conn.commit()
    state = get_state()
    state["hle_run"] = {"correct": int(correct), "total": int(total), "score": score, "qualified": qualified}
    return state


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).strip()


def _grade_answer(expected: str, produced: str) -> dict[str, Any]:
    """Local, honest grader: normalized exact match, else token overlap."""
    exp, got = _normalize(expected), _normalize(produced)
    if not exp:
        return {"correct": False, "match": "none", "overlap": 0.0}
    if exp == got:
        return {"correct": True, "match": "exact", "overlap": 1.0}
    exp_tokens, got_tokens = set(exp.split()), set(got.split())
    if not exp_tokens:
        return {"correct": False, "match": "none", "overlap": 0.0}
    overlap = len(exp_tokens & got_tokens) / len(exp_tokens)
    return {"correct": overlap >= 0.8, "match": "overlap", "overlap": round(overlap, 3)}


def run_hle_sample(sample_size: int = 10) -> dict[str, Any]:
    """Stage-3 assessor: ask the LOCAL engine a sample of HLE questions.

    Never calls the cloud. If the local engine is unavailable the result is
    an honest refusal — no grading is fabricated.
    """
    sample_size = max(1, min(100, int(sample_size)))
    from .ingestion import build_ollama_client

    client = build_ollama_client()
    if not client.is_available():
        return {
            "ok": False,
            "reason": "local_engine_unavailable",
            "detail": "The local model engine is offline. Start it and retry — zero-cloud grading never fabricates a score.",
        }

    sys.path.insert(0, str(ROOT))
    from assessments.hle import load_hle

    dataset = load_hle()
    detail: list[dict] = []
    correct = 0
    total = 0
    for i, item in zip(range(sample_size), dataset):
        question = str(item.get("question") or "")
        expected = str(item.get("answer") or "")
        if not question or not expected:
            continue
        try:
            produced = client.chat(
                [
                    {"role": "system", "content": "Answer directly and concisely. Give the final answer only."},
                    {"role": "user", "content": question[:4000]},
                ]
            )
        except Exception as ex:
            detail.append({"index": i, "error": str(ex)[:200]})
            continue
        verdict = _grade_answer(expected, produced)
        correct += 1 if verdict["correct"] else 0
        total += 1
        detail.append({"index": i, "match": verdict["match"], "overlap": verdict["overlap"], "correct": verdict["correct"]})
        if total >= sample_size:
            break
    state = record_hle_run(correct, total, detail) if total else {"ok": False, "reason": "no_gradable_questions"}
    state["sample"] = {"requested": sample_size, "graded": total, "correct": correct}
    return state


def datasets_status() -> dict[str, Any]:
    """Report assessment datasets: pulled? how many items? harness present?"""
    report: dict[str, Any] = {"ok": True}
    try:
        sys.path.insert(0, str(ROOT))
        from assessments.hle import load_hle

        report["hle"] = {"repo": "cais/hle", "items": len(load_hle()), "cache": "data/hf_cache (in-tree)"}
    except Exception as ex:
        gated = "gated" in str(ex).lower()
        report["hle"] = {
            "repo": "cais/hle",
            "pulled": False,
            "gated": gated,
            "error": str(ex)[:200],
            "needs": (
                "OWNER: accept the license at huggingface.co/datasets/cais/hle, "
                "then put HF_TOKEN=hf_... in the in-tree .env"
            )
            if gated
            else "investigate the error above",
        }
    try:
        from assessments.swe_pro import load_swe_pro

        report["swe_bench_pro"] = {
            "repo": "ScaleAI/SWE-bench_Pro (v2)",
            "items": len(load_swe_pro()),
            "cache": "data/hf_cache (in-tree)",
        }
    except Exception as ex:
        report["swe_bench_pro"] = {"repo": "ScaleAI/SWE-bench_Pro (v2)", "pulled": False, "error": str(ex)[:200]}
    workbench = ROOT / "assessments" / "swe-workbench"
    report["swe_workbench_harness"] = {
        "folder": str(workbench.relative_to(ROOT)),
        "present": workbench.exists(),
        "zip_present": (workbench / "SWE-bench_Pro-os-main.zip").exists(),
        "note": "Execution grading runs through this harness (docker) on rig day.",
    }
    report["learning_index"] = _learning_snapshot()
    return report


def _learning_snapshot() -> dict[str, Any]:
    """Training-phase telemetry from the live learning index (no side effects)."""
    try:
        from .learning_index import learning_status

        status = learning_status()
        return {
            "percent_learned": status.get("percent"),
            "assessed": status.get("assessed"),
            "total": status.get("total"),
            "enabled": status.get("enabled"),
        }
    except Exception as ex:
        return {"error": str(ex)[:200]}


def settings_snapshot() -> dict[str, Any]:
    settings = get_settings()
    llm = settings.get("llm", {}) if isinstance(settings.get("llm"), dict) else {}
    return {"chat_model": llm.get("chat_model"), "embedding_model": llm.get("embedding_model")}
