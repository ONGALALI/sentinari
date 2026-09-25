"""Sentinel Learning Index — proof that ingested knowledge is *applied*, not just held.

Owner directive (§36): a background worker that determines, per ingested
document, whether Sentinel can actually apply the knowledge, and reports a
% Learned progress per scientific field and for the whole library.

Honest method — every assessment is one evidence-graded exam:
1. EXAM     — pull a few chunks of one not-yet-assessed document and ask the
              LLM gateway to write ONE exam question grounded ONLY in that
              text, then answer it from the model's own knowledge WITHOUT
              quoting the passage back.
2. GRADE    — grading is local (no extra API cost): the answer is scored
              against the source text by token-overlap GROUNDING (did she use
              the knowledge?), with a VERBATIM penalty so reciting the
              passage is not mistaken for mastery.
3. RECORD   — the graded result is persisted per document; the index
              aggregates to per-field and whole-library percentages.

Nothing here mutates knowledge: this is measurement, not modification —
the Qualia Lab's verification discipline, run continuously and gently.
Verdict thresholds are deliberately conservative and should be calibrated
against Qualia Lab results as data accumulates.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import get_connection, library_connection
from .llm_gateway import LLMGatewayError, get_gateway

router = APIRouter(prefix="/api/learning", tags=["learning"])

# Gentle-by-design pacing: one document per tick, tick every 10s (~6 exams/min).
POLL_INTERVAL_SECONDS = 10.0
CHUNKS_PROBED = 3
MAX_CHARS_PER_CHUNK = 3500
MAX_CHARS_SOURCE = 9000
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 600
# Documents are scanned newest-first; this window keeps each tick cheap while
# the index sweeps the whole library over time.
RECENT_WINDOW = 400

EXAM_SYSTEM_PROMPT = """You are Sentinel. You are being examined on knowledge you have ingested. \
Write ONE exam question grounded ONLY in the provided text, then answer it from your own understanding. \
Answer in your own words — do NOT copy phrases from the text. \
Return STRICT JSON only: {"question": "...", "answer": "..."}"""

EXAM_USER_TEMPLATE = """Text (document: "{title}", field: {field}):

{source}

Produce the JSON exam now."""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _ensure_schema() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS learning_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                scientific_field TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                question TEXT NOT NULL DEFAULT '',
                answer TEXT NOT NULL DEFAULT '',
                grounding_score REAL NOT NULL DEFAULT 0,
                verbatim_score REAL NOT NULL DEFAULT 0,
                mastery REAL NOT NULL DEFAULT 0,
                verdict TEXT NOT NULL DEFAULT '',
                assessed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_learning_field
                ON learning_assessments(scientific_field);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_learning_doc
                ON learning_assessments(document_id);
            CREATE TABLE IF NOT EXISTS learning_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.commit()


def _get_setting(key: str, default: str) -> str:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM learning_settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row is not None else default
    except Exception:
        return default


def _set_setting(key: str, value: str) -> None:
    _ensure_schema()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO learning_settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value),
        )
        conn.commit()


def learning_enabled() -> bool:
    """True unless the owner paused the Learning Index (persisted)."""
    return _get_setting("learning_enabled", "on").lower() != "off"


# ---------------------------------------------------------------------------
# Local grading — grounding with a verbatim penalty
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    """the and for are but not you all any can had her was one our out day get has
    him his how man new now old see two way who boy did its let put say she too
    use that this with from they have will been were when what your said each
    which their there these those about into over under between because while
    where after before above below both few more most other some such only own
    same than them then once here does done doing having""".split()
)


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
    return {t for t in tokens if t not in _STOPWORDS}


def _grade(answer: str, source_text: str) -> tuple[float, float, float, str]:
    """Return (grounding, verbatim, mastery, verdict).

    grounding = share of the answer's tokens that appear in the source text
                (did the answer actually draw on the material?).
    verbatim  = share of the source text's tokens parroted back (recitation).
    mastery   = grounding, penalized when the answer is mostly copied text —
                reciting a passage is not the same as applying it.
    """
    a_tokens = _tokenize(answer)
    s_tokens = _tokenize(source_text)
    if not a_tokens:
        return 0.0, 0.0, 0.0, "no-answer"
    grounding = len(a_tokens & s_tokens) / len(a_tokens)
    verbatim = (len(a_tokens & s_tokens) / len(s_tokens)) if s_tokens else 0.0
    if verbatim > 0.6:
        mastery = grounding * max(0.3, 1.0 - (verbatim - 0.6))
    else:
        mastery = grounding
    if mastery >= 0.28:
        verdict = "applied"
    elif verbatim > 0.6:
        verdict = "recited"
    elif grounding > 0.08:
        verdict = "partial"
    else:
        verdict = "not-learned"
    return round(grounding, 4), round(verbatim, 4), round(mastery, 4), verdict


# ---------------------------------------------------------------------------
# The exam itself
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any] | None:
    t = re.sub(r"^```(?:json)?|```\s*$", "", str(text or "").strip(), flags=re.M).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(t[start : end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _load_probe_material(document_id: int) -> tuple[str, str, str] | None:
    """(title, scientific_field, source_text) from the knowledge library."""
    with library_connection("gemma") as conn:
        doc = conn.execute(
            "SELECT title, IFNULL(scientific_field, '') AS field FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if doc is None:
            return None
        rows = conn.execute(
            "SELECT content FROM chunks WHERE document_id = ? ORDER BY chunk_index LIMIT ?",
            (document_id, CHUNKS_PROBED),
        ).fetchall()
    source = "\n\n".join(
        str(r["content"] or "")[:MAX_CHARS_PER_CHUNK] for r in rows
    ).strip()[:MAX_CHARS_SOURCE]
    if not source:
        return None
    return str(doc["title"] or "Untitled"), str(doc["field"] or "unclassified"), source


def probe_document(document_id: int) -> dict[str, Any] | None:
    """Run one exam against a specific document. None = could not assess."""
    material = _load_probe_material(document_id)
    if material is None:
        return None
    title, field, source = material
    try:
        raw = get_gateway().chat(
            [
                {"role": "system", "content": EXAM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": EXAM_USER_TEMPLATE.format(
                        title=title, field=field or "general", source=source
                    ),
                },
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
    except (LLMGatewayError, Exception):
        return None
    exam = _extract_json(raw)
    if not exam:
        return None
    question = str(exam.get("question") or "")[:1000]
    answer = str(exam.get("answer") or "")[:4000]
    if not question or not answer:
        return None
    grounding, verbatim, mastery, verdict = _grade(answer, source)
    record: dict[str, Any] = {
        "document_id": document_id,
        "scientific_field": _norm_field(field),
        "title": title,
        "question": question,
        "answer": answer,
        "grounding_score": grounding,
        "verbatim_score": verbatim,
        "mastery": mastery,
        "verdict": verdict,
        "assessed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _persist(record)
    return record


def _persist(record: dict[str, Any]) -> None:
    _ensure_schema()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO learning_assessments
                (document_id, scientific_field, title, question, answer,
                 grounding_score, verbatim_score, mastery, verdict, assessed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                scientific_field = excluded.scientific_field,
                title = excluded.title,
                question = excluded.question,
                answer = excluded.answer,
                grounding_score = excluded.grounding_score,
                verbatim_score = excluded.verbatim_score,
                mastery = excluded.mastery,
                verdict = excluded.verdict,
                assessed_at = excluded.assessed_at
            """,
            (
                int(record["document_id"]),
                record["scientific_field"],
                record["title"],
                record["question"],
                record["answer"],
                float(record["grounding_score"]),
                float(record["verbatim_score"]),
                float(record["mastery"]),
                record["verdict"],
                record["assessed_at"],
            ),
        )
        conn.commit()


def _candidate_documents() -> list[int]:
    """Unassessed library documents, newest first. The recent window is
    checked first (cheap); when it is exhausted, the sweep continues into
    the rest of the library — the 10s exam pacing is the real throttle."""
    with library_connection("gemma") as conn:
        rows = conn.execute(
            "SELECT id FROM documents ORDER BY id DESC LIMIT ?", (RECENT_WINDOW,)
        ).fetchall()
    library_ids = [int(r["id"]) for r in rows]
    if not library_ids:
        return []
    placeholders = ",".join("?" for _ in library_ids)
    with get_connection() as conn:
        assessed = {
            int(r["document_id"])
            for r in conn.execute(
                f"SELECT document_id FROM learning_assessments WHERE document_id IN ({placeholders})",
                library_ids,
            ).fetchall()
        }
    pending = [i for i in library_ids if i not in assessed]
    if pending:
        return pending
    # Recent window fully assessed — continue the sweep deeper, newest first,
    # so the whole library is eventually examined (gently, one per tick).
    with library_connection("gemma") as conn:
        all_rows = conn.execute(
            "SELECT id FROM documents ORDER BY id DESC"
        ).fetchall()
    all_ids = [int(r["id"]) for r in all_rows]
    if not all_ids:
        return []
    placeholders = ",".join("?" for _ in all_ids)
    with get_connection() as conn:
        assessed_all = {
            int(r["document_id"])
            for r in conn.execute(
                f"SELECT document_id FROM learning_assessments WHERE document_id IN ({placeholders})",
                all_ids,
            ).fetchall()
        }
    return [i for i in all_ids if i not in assessed_all]


def probe_next() -> dict[str, Any] | None:
    """Assess the next unassessed recent document. None = nothing pending / failed."""
    for _ in range(5):  # skip over a handful of unloadable docs before giving up
        candidates = _candidate_documents()
        if not candidates:
            return None
        document_id = candidates[0]
        record = probe_document(document_id)
        if record is not None:
            return record
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO learning_assessments (document_id, verdict, assessed_at)"
                " VALUES (?, 'skipped', ?)",
                (document_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            conn.commit()
    return None


# ---------------------------------------------------------------------------
# The index — per-field and whole-library % learned
# ---------------------------------------------------------------------------

def _norm_field(raw: Any) -> str:
    """Merge legacy Title-case field labels ('Chemistry', 'Physics') into the
    canonical slug form so per-field percentages are not split by casing."""
    value = str(raw or "").strip().lower().replace(" ", "-")
    return value or "unclassified"


def _field_totals() -> dict[str, int]:
    try:
        with library_connection("gemma") as conn:
            rows = conn.execute(
                "SELECT IFNULL(NULLIF(TRIM(scientific_field), ''), 'unclassified') AS f, COUNT(1) AS n"
                " FROM documents GROUP BY f"
            ).fetchall()
        totals: dict[str, int] = {}
        for r in rows:
            key = _norm_field(r["f"])
            totals[key] = totals.get(key, 0) + int(r["n"])
        return totals
    except Exception:
        return {}


def learning_status() -> dict[str, Any]:
    _ensure_schema()
    totals = _field_totals()
    with get_connection() as conn:
        assessed_rows = conn.execute(
            "SELECT scientific_field, COUNT(1) AS n,"
            " SUM(CASE WHEN verdict = 'applied' THEN 1 ELSE 0 END) AS applied"
            " FROM learning_assessments WHERE verdict != 'skipped' GROUP BY scientific_field"
        ).fetchall()
        latest = conn.execute(
            "SELECT document_id, title, verdict, mastery, assessed_at"
            " FROM learning_assessments WHERE verdict != 'skipped'"
            " ORDER BY id DESC LIMIT 5"
        ).fetchall()
    assessed_by_field: dict[str, int] = {}
    for r in assessed_rows:
        key = _norm_field(r["scientific_field"])
        assessed_by_field[key] = assessed_by_field.get(key, 0) + int(r["n"])
    total_assessed = sum(assessed_by_field.values())
    total_docs = sum(totals.values())
    fields = []
    for field, total in sorted(totals.items(), key=lambda kv: -kv[1]):
        assessed = assessed_by_field.get(field, 0)
        fields.append(
            {
                "field": field,
                "total": total,
                "assessed": assessed,
                "percent": round(100.0 * assessed / total, 1) if total else 0.0,
            }
        )
    return {
        "ok": True,
        "enabled": learning_enabled(),
        "total": total_docs,
        "assessed": total_assessed,
        "percent": round(100.0 * total_assessed / total_docs, 1) if total_docs else 0.0,
        "fields": fields,
        "latest": [dict(r) for r in latest],
    }


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class LearningWorker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="learning-index", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(POLL_INTERVAL_SECONDS):
            try:
                if learning_enabled():
                    probe_next()
            except Exception:
                # A background index must never take the app down.
                time.sleep(POLL_INTERVAL_SECONDS)


_worker = LearningWorker()


def start_learning_worker() -> None:
    _ensure_schema()
    _worker.start()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class ToggleRequest(BaseModel):
    enabled: bool


class ProbeRequest(BaseModel):
    document_id: int | None = Field(default=None, ge=1)


@router.get("/status")
def api_learning_status() -> dict[str, Any]:
    return learning_status()


@router.post("/toggle")
def api_learning_toggle(payload: ToggleRequest) -> dict[str, Any]:
    _set_setting("learning_enabled", "on" if payload.enabled else "off")
    if payload.enabled:
        start_learning_worker()
    return {"ok": True, "enabled": payload.enabled}


@router.post("/probe")
def api_learning_probe(payload: ProbeRequest) -> dict[str, Any]:
    """Examine one document now — the owner's 'watch her learn' button."""
    document_id = payload.document_id
    if document_id is None:
        record = probe_next()
        if record is None:
            raise HTTPException(status_code=404, detail="No unexamined documents in the recent window — every loaded document has been assessed.")
        return {"ok": True, "result": record}
    record = probe_document(int(document_id))
    if record is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} could not be examined (missing or no readable text).")
    return {"ok": True, "result": record}
