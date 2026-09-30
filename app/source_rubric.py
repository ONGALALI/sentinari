"""Sentinari source rubric — §65.

The owner's doctoral-level (NQF 10-style) benchmark for candidate dataset
sources, applied as a MANUAL assessment rubric. Ten dimensions, each scored
on a Likert 1-5 scale; composite = mean (1.0-5.0).

Doctrine (owner, §65): the JUDGMENT stays with the owner — "I doubt it can
be automated". This module automates only the evidence-gathering structure,
the scoring arithmetic, and the memory: assessments are stored in the MAIN
app database (same store as the §60 intake firewall and §64 blocklist) and
surface in the discovery card next to each assessed source.

The canonical rubric text (owner's descriptors + Likert anchors) lives in
docs/source_assessment_benchmark.md.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# §65 — the ten doctoral dimensions, in the owner's order. Keys are stable
# identifiers (never renamed — assessments persist against them); labels are
# the short forms of the owner's descriptors.
RUBRIC_DIMENSIONS: tuple[dict[str, str], ...] = (
    {"key": "scope_of_knowledge", "label": "Scope of knowledge"},
    {"key": "knowledge_literacy", "label": "Knowledge literacy"},
    {"key": "method_and_procedure", "label": "Method and procedure"},
    {"key": "problem_solving", "label": "Problem solving"},
    {"key": "ethics_and_professional_practice", "label": "Ethics and professional practice"},
    {"key": "accessing_processing_managing_information", "label": "Accessing, processing and managing information"},
    {"key": "producing_and_communicating_information", "label": "Producing and communicating information"},
    {"key": "context_and_systems", "label": "Context and systems"},
    {"key": "management_of_learning", "label": "Management of learning"},
    {"key": "accountability", "label": "Accountability"},
)

LIKERT_ANCHORS: tuple[str, ...] = (
    "1 - Not evidenced",
    "2 - Weak",
    "3 - Partial",
    "4 - Strong",
    "5 - Exemplary",
)

# Guidance bands (draft, owner-adjustable) — advisory only; the owner decides.
BAND_EXEMPLARY_MIN = 4.0
BAND_BORDERLINE_MIN = 3.0


def band_for(composite: float) -> str:
    if composite >= BAND_EXEMPLARY_MIN:
        return "exemplary - approve for the fine-tuning chain"
    if composite >= BAND_BORDERLINE_MIN:
        return "borderline - owner review"
    return "below standard - block candidate (once blocked, always blocked)"


def _app_db_path() -> Path:
    from .intake_firewall import _app_db_path as _fw_db_path  # single source of truth (§60)

    return _fw_db_path()


def _connect() -> sqlite3.Connection:
    path = _app_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            label TEXT NOT NULL DEFAULT '',
            scores TEXT NOT NULL DEFAULT '{}',
            composite REAL NOT NULL DEFAULT 0,
            band TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            assessed_at TEXT NOT NULL,
            assessed_by TEXT NOT NULL DEFAULT 'owner',
            UNIQUE(origin)
        )
        """
    )
    conn.commit()
    return conn


def get_rubric() -> dict[str, Any]:
    """The rubric definition for the UI: dimensions, anchors, bands."""
    return {
        "ok": True,
        "dimensions": [dict(d) for d in RUBRIC_DIMENSIONS],
        "likert_anchors": list(LIKERT_ANCHORS),
        "bands": {
            "exemplary_min": BAND_EXEMPLARY_MIN,
            "borderline_min": BAND_BORDERLINE_MIN,
            "note": ">=4.0 exemplary - approve; 3.0-3.9 borderline - owner review; <3.0 below standard - block candidate",
        },
        "canonical_doc": "docs/source_assessment_benchmark.md",
    }


def save_assessment(
    origin: str,
    scores: dict[str, Any],
    source: str = "",
    label: str = "",
    note: str = "",
    assessed_by: str = "owner",
) -> dict[str, Any]:
    """Store one owner assessment. Rejects invalid dimensions/scores."""
    o = str(origin or "").strip().lower()  # §64 convention: origins are case-insensitive keys
    if not o:
        return {"ok": False, "error": "origin is required"}
    valid = {d["key"] for d in RUBRIC_DIMENSIONS}
    clean: dict[str, int] = {}
    for k, v in (scores or {}).items():
        if k not in valid:
            return {"ok": False, "error": f"unknown dimension: {k}"}
        try:
            n = int(v)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"score for {k} must be an integer 1-5"}
        if not 1 <= n <= 5:
            return {"ok": False, "error": f"score for {k} must be 1-5 (Likert)"}
        clean[k] = n
    missing = valid - set(clean)
    if missing:
        return {"ok": False, "error": f"missing dimension(s): {', '.join(sorted(missing))}"}

    composite = round(sum(clean.values()) / len(RUBRIC_DIMENSIONS), 2)
    band = band_for(composite)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO source_assessments (origin, source, label, scores, composite, band, note, assessed_at, assessed_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(origin) DO UPDATE SET source=excluded.source, label=excluded.label, "
            "scores=excluded.scores, composite=excluded.composite, band=excluded.band, "
            "note=excluded.note, assessed_at=excluded.assessed_at, assessed_by=excluded.assessed_by",
            (
                o,
                str(source or "").strip().lower(),
                str(label or "").strip(),
                json.dumps(clean, sort_keys=True),
                composite,
                band,
                str(note or "").strip(),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                str(assessed_by or "owner"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "origin": o, "composite": composite, "band": band, "dimensions_scored": len(clean)}


def get_assessments(origins: list[str] | None = None) -> dict[str, Any]:
    """All (or selected) assessments, newest composite first."""
    conn = _connect()
    try:
        if origins:
            rows = conn.execute(
                f"SELECT origin, source, label, scores, composite, band, note, assessed_at, assessed_by "
                f"FROM source_assessments WHERE origin IN ({','.join('?' for _ in origins)}) "
                f"ORDER BY composite DESC, assessed_at DESC",
                [str(o).strip().lower() for o in origins],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT origin, source, label, scores, composite, band, note, assessed_at, assessed_by "
                "FROM source_assessments ORDER BY composite DESC, assessed_at DESC"
            ).fetchall()
    finally:
        conn.close()
    return {
        "ok": True,
        "count": len(rows),
        "assessments": [
            {
                "origin": r["origin"],
                "source": r["source"],
                "label": r["label"],
                "scores": json.loads(r["scores"] or "{}"),
                "composite": r["composite"],
                "band": r["band"],
                "note": r["note"],
                "assessed_at": r["assessed_at"],
                "assessed_by": r["assessed_by"],
            }
            for r in rows
        ],
    }


def delete_assessment(origin: str) -> dict[str, Any]:
    """API-only correction valve — re-assessment also overwrites (upsert)."""
    o = str(origin or "").strip().lower()
    if not o:
        return {"ok": False, "error": "origin is required"}
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM source_assessments WHERE origin = ?", (o,))
        conn.commit()
        removed = cur.rowcount or 0
    finally:
        conn.close()
    return {"ok": True, "origin": o, "removed": removed}
