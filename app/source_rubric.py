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

# §66 — NQF levels 1-10. The owner's CUMULATIVE RULE: a candidate claiming
# Level N reach must also carry Levels 1..N-1 (understand, apply, reflect at
# every rung below); the ladder is internationally benchmarked — valid,
# reliable, fair, defensible by case studies. Canonical text:
# docs/nqf_level_descriptors.md
NQF_LEVELS: tuple[dict[str, Any], ...] = (
    {"level": 1, "name": "Level One"},
    {"level": 2, "name": "Level Two"},
    {"level": 3, "name": "Level Three"},
    {"level": 4, "name": "Level Four"},
    {"level": 5, "name": "Level Five"},
    {"level": 6, "name": "Level Six"},
    {"level": 7, "name": "Level Seven"},
    {"level": 8, "name": "Level Eight"},
    {"level": 9, "name": "Level Nine — masters"},
    {"level": 10, "name": "Level Ten — doctoral"},
)

CUMULATIVE_RULE = (
    "NQF cumulative rule (§66): a candidate at Level N must also include all levels "
    "before it — understand, apply and reflect on levels 1..N-1. A Level 10 source "
    "is Level 10 only if the whole staircase is present."
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
    _ensure_columns(conn)
    conn.commit()
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """§66 migration: add the level columns to ledgers created before §66."""
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(source_assessments)").fetchall()}
    if "nqf_level_reach" not in cols:
        conn.execute("ALTER TABLE source_assessments ADD COLUMN nqf_level_reach INTEGER")
    if "builds_through" not in cols:
        conn.execute("ALTER TABLE source_assessments ADD COLUMN builds_through INTEGER")


def get_rubric() -> dict[str, Any]:
    """The rubric definition for the UI: dimensions, anchors, bands."""
    return {
        "ok": True,
        "dimensions": [dict(d) for d in RUBRIC_DIMENSIONS],
        "likert_anchors": list(LIKERT_ANCHORS),
        "nqf_levels": [dict(l) for l in NQF_LEVELS],
        "cumulative_rule": CUMULATIVE_RULE,
        "bands": {
            "exemplary_min": BAND_EXEMPLARY_MIN,
            "borderline_min": BAND_BORDERLINE_MIN,
            "note": ">=4.0 exemplary - approve; 3.0-3.9 borderline - owner review; <3.0 below standard - block candidate",
        },
        "canonical_doc": "docs/source_assessment_benchmark.md",
        "nqf_doc": "docs/nqf_level_descriptors.md",
    }


def save_assessment(
    origin: str,
    scores: dict[str, Any],
    source: str = "",
    label: str = "",
    note: str = "",
    assessed_by: str = "owner",
    nqf_level_reach: int | None = None,
    builds_through: bool | None = None,
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

    # §66 level claim: optional, but validated when present.
    reach: int | None
    if nqf_level_reach is None or nqf_level_reach == "":
        reach = None
    else:
        try:
            reach = int(nqf_level_reach)
        except (TypeError, ValueError):
            return {"ok": False, "error": "nqf_level_reach must be an integer 1-10"}
        if not 1 <= reach <= 10:
            return {"ok": False, "error": "nqf_level_reach must be 1-10"}
        if reach < 10 and not builds_through:
            pass  # lower claims are the owner's call too; the flag simply records the staircase
    builds: int | None
    builds = None if builds_through is None else int(bool(builds_through))
    if reach == 10 and builds is None:
        # a doctoral claim without the staircase recorded is stored, but flagged unverified
        level_claim = f"L{reach} unverified (builds_through not confirmed)"
    elif reach is not None:
        level_claim = f"L{reach}{' verified through lower levels' if builds else ''}"
    else:
        level_claim = ""

    composite = round(sum(clean.values()) / len(RUBRIC_DIMENSIONS), 2)
    band = band_for(composite)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO source_assessments (origin, source, label, scores, composite, band, note, assessed_at, assessed_by, nqf_level_reach, builds_through) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(origin) DO UPDATE SET source=excluded.source, label=excluded.label, "
            "scores=excluded.scores, composite=excluded.composite, band=excluded.band, "
            "note=excluded.note, assessed_at=excluded.assessed_at, assessed_by=excluded.assessed_by, "
            "nqf_level_reach=excluded.nqf_level_reach, builds_through=excluded.builds_through",
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
                reach,
                builds,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    result: dict[str, Any] = {
        "ok": True,
        "origin": o,
        "composite": composite,
        "band": band,
        "dimensions_scored": len(clean),
    }
    if level_claim:
        result["level_claim"] = level_claim
    return result


def get_assessments(origins: list[str] | None = None) -> dict[str, Any]:
    """All (or selected) assessments, newest composite first."""
    conn = _connect()
    try:
        if origins:
            rows = conn.execute(
                f"SELECT origin, source, label, scores, composite, band, note, assessed_at, assessed_by, nqf_level_reach, builds_through "
                f"FROM source_assessments WHERE origin IN ({','.join('?' for _ in origins)}) "
                f"ORDER BY composite DESC, assessed_at DESC",
                [str(o).strip().lower() for o in origins],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT origin, source, label, scores, composite, band, note, assessed_at, assessed_by, nqf_level_reach, builds_through "
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
                "nqf_level_reach": r["nqf_level_reach"],
                "builds_through": (None if r["builds_through"] is None else bool(r["builds_through"])),
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
