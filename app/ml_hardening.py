"""§80 — ML hardening bridge: sentinel/ml PINN stack verifies discovered patterns.

Owner directive: harden the approach with the two scientific-ML files in ml/
(scientific_ml.py — data+physics hybrid PINN with Tanh MLP; sci_ml_core.py —
multi-output Jacobian-residual PINN with SiLU MLP). The app runtime stays
torch-free by design (§48): training runs in the separate .venv-ml
environment via subprocess, exactly like the ml/ README prescribes.

What this module does:

1. FEATURE EXTRACTION (this process, stdlib): every discovered pattern in
   the store is encoded into a normalised scientific feature vector from its
   real extraction record — evidence depth, source breadth, graph mass,
   confidence, cross-field span, Assessment Matrix S-scores, NSIS, and the
   Risk speculation gap. Same quantities the Assessment Matrix engine uses,
   so the physics check and the matrix agree on the inputs.

2. PHYSICS CONSTRAINT (the PINN part): a pattern is "hardened" when a small
   feed-forward net, trained on the library's pattern feature vectors, both
   fits the observed activation outcomes (data loss) AND respects a
   conservation-style residual: the net's sensitivity to the Risk dimension
   must be monotone-decreasing in sustainability (dS/dRisk <= 0 within
   tolerance) — the docx's volatility-anchor law, enforced by autograd
   exactly like sci_ml_core.py's Jacobian residual.

3. INVOCATION: run_hardening(limit) writes the feature matrix to a temp
   JSON, invokes .venv-ml/Scripts/python.exe ml/harden_patterns.py, reads
   back per-pattern verdicts (stable / volatile / insufficient-data with
   physics residual + data error), and caches them in patterns.db
   (pattern_settings key 'ml_hardening'). Never raises; honest errors.

4. INTEGRATION: verdicts surface in the chat tool-gateway
   (dataset_tools.tool_ml_hardening_report) and via the API
   /api/patterns/ml-hardening (POST run, GET report).
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assessment_math import DIMENSIONS, evaluate_pattern_matrix
from .pattern_store import (
    _connect as _store_connect,
    ensure_pattern_store,
    get_pattern,
    get_pattern_graph,
)

HARDENING_KEY = "ml_hardening"
HARDENING_SCRIPT = Path("ml") / "harden_patterns.py"

FEATURE_ORDER = [
    "evidence_depth",
    "source_breadth",
    "graph_mass",
    "confidence",
    "field_span",
    "benefits_recorded",
    "nsis",
    "sd_risk",
    "sd_societal",
    "speculation_gap",
]


# ---------------------------------------------------------------------------
# Feature extraction (stdlib; mirrors the Assessment Matrix inputs)
# ---------------------------------------------------------------------------


def extract_pattern_features(pattern: dict[str, Any]) -> dict[str, float] | None:
    """Normalised 0-1 feature vector for one pattern from its stored record."""
    evidence = pattern.get("evidence") or []
    n_evidence = len(evidence)
    docs = len({int((e or {}).get("document_id") or 0) for e in evidence if (e or {}).get("document_id")})
    confidence = float(pattern.get("confidence") or 0.0)
    try:
        fields = [str(f) for f in json.loads(str(pattern.get("fields_involved") or "[]"))]
    except Exception:
        fields = []
    benefits = bool(str(pattern.get("benefits") or "").strip())

    graph = get_pattern_graph(int(pattern.get("id") or 0))
    n_relations = len(graph.get("relations") or [])
    evaluation = evaluate_pattern_matrix(pattern, graph={"entities": 0, "relations": n_relations})
    s = evaluation["s_scores"]

    features = {
        "evidence_depth": min(1.0, n_evidence / 5.0),
        "source_breadth": min(1.0, docs / 4.0),
        "graph_mass": min(1.0, n_relations / 10.0),
        "confidence": confidence,
        "field_span": min(1.0, len(fields) / 4.0),
        "benefits_recorded": 1.0 if benefits else 0.0,
        "nsis": min(1.0, float(evaluation["nsis"]) / 0.9),
        "sd_risk": min(1.0, float(evaluation["sd_percent"].get("Risk", 0)) / 40.0),
        "sd_societal": min(1.0, float(evaluation["sd_percent"].get("Societal", 0)) / 40.0),
        # Speculation gap: 1 - confidence minus evidence cushion (the Risk driver).
        "speculation_gap": max(0.0, min(1.0, (1.0 - confidence) - min(0.5, 0.1 * n_evidence))),
    }
    return {k: round(float(v), 4) for k, v in features.items()}


def build_feature_matrix(limit: int = 200) -> dict[str, Any]:
    """Features + labels for every pattern in the store.

    Label: 1.0 when the pattern has evidence AND a recorded benefit analysis
    (i.e. it survived contact with analysis), else 0.0. With few patterns the
    PINN still trains — it reports honest confidence instead of pretending.
    """
    ensure_pattern_store()
    with _store_connect() as conn:
        rows = conn.execute(
            "SELECT id FROM patterns ORDER BY confidence DESC LIMIT ?", (max(1, int(limit)),)
        ).fetchall()
    items: list[dict[str, Any]] = []
    for r in rows:
        pattern = get_pattern(int(r["id"]))
        if pattern is None:
            continue
        features = extract_pattern_features(pattern)
        if features is None:
            continue
        has_evidence = bool(pattern.get("evidence"))
        items.append(
            {
                "pattern_id": int(r["id"]),
                "title": str(pattern.get("title") or ""),
                "status": str(pattern.get("status") or "candidate"),
                "features": features,
                "label": 1.0 if (has_evidence and bool(str(pattern.get("benefits") or "").strip())) else 0.0,
            }
        )
    return {
        "feature_order": FEATURE_ORDER,
        "dimensions": DIMENSIONS,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "patterns": items,
    }


# ---------------------------------------------------------------------------
# venv-ml invocation
# ---------------------------------------------------------------------------


def _venv_ml_python() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    for candidate in (root / ".venv-ml" / "Scripts" / "python.exe", root / ".venv-ml" / "bin" / "python"):
        if candidate.exists():
            return candidate
    return None


def run_hardening(limit: int = 200, epochs: int = 600) -> dict[str, Any]:
    """Run the PINN hardening pass in the ml venv. Never raises."""
    started = time.time()
    python = _venv_ml_python()
    if python is None:
        return {"ok": False, "error": ".venv-ml not found — install per ml/README.md (day-1: pip install -r ml/requirements-ml.txt)"}
    script = Path(__file__).resolve().parents[1] / HARDENING_SCRIPT
    if not script.exists():
        return {"ok": False, "error": f"{HARDENING_SCRIPT} missing"}

    matrix = build_feature_matrix(limit=limit)
    if not matrix["patterns"]:
        return {"ok": False, "error": "no patterns in the store to harden yet"}

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(matrix, handle, ensure_ascii=False)
        payload_path = Path(handle.name)
    out_path = payload_path.with_suffix(".result.json")
    try:
        proc = subprocess.run(
            [
                str(python),
                str(script),
                "--input", str(payload_path),
                "--output", str(out_path),
                "--epochs", str(max(100, min(4000, int(epochs)))),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": (proc.stderr or proc.stdout or "ml venv run failed")[-600:],
            }
        result = json.loads(out_path.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ml hardening run timed out (600s cap)"}
    except Exception as ex:
        return {"ok": False, "error": f"hardening run failed: {ex}"}
    finally:
        try:
            payload_path.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)
        except Exception:
            pass

    elapsed = round(time.time() - started, 2)
    report = {
        "ok": bool(result.get("ok")),
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds": elapsed,
        "device": result.get("device", "unknown"),
        "epochs": result.get("epochs"),
        "final_data_loss": result.get("final_data_loss"),
        "final_physics_residual": result.get("final_physics_residual"),
        "verdicts": result.get("verdicts", []),
        "notes": result.get("notes", ""),
    }
    _cache_report(report)
    return report


def _cache_report(report: dict[str, Any]) -> None:
    try:
        with _store_connect() as conn:
            conn.execute(
                """
                INSERT INTO pattern_settings (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
                """,
                (HARDENING_KEY, json.dumps(report, ensure_ascii=False)),
            )
            conn.commit()
    except Exception:
        pass


def get_cached_report() -> dict[str, Any] | None:
    try:
        with _store_connect() as conn:
            row = conn.execute(
                "SELECT value, updated_at FROM pattern_settings WHERE key = ?", (HARDENING_KEY,)
            ).fetchone()
        if row is None:
            return None
        report = json.loads(str(row["value"] or ""))
        if isinstance(report, dict):
            report["cached_updated_at"] = str(row["updated_at"] or "")
        return report
    except Exception:
        return None


def verdict_for_pattern(pattern_id: int) -> dict[str, Any] | None:
    report = get_cached_report()
    if not report:
        return None
    for v in report.get("verdicts") or []:
        if int(v.get("pattern_id") or 0) == int(pattern_id):
            return v
    return None
