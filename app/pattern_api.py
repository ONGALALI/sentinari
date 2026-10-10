"""Pattern Recognition API — endpoints for the pattern workflow."""

from __future__ import annotations

import json as _json
import threading as _threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from . import load_progress as _load_progress
from .db import library_connection as _library_connection
from .llm_gateway import LLMGatewayError, get_gateway
from .pattern_store import (
    _connect as _store_connect,
    ensure_pattern_store,
    get_pattern,
    get_pattern_recognition_enabled,
    list_patterns,
    review_pattern,
    set_pattern_recognition_enabled,
    store_stats,
)
from .pattern_store import PAUSED_MESSAGE
from .pattern_worker import extract_document, process_queue, queue_document, synthesize_cross_domain

router = APIRouter(prefix="/api/patterns", tags=["Pattern Recognition"])


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject|test|activate)$")
    note: str = Field(default="", max_length=500)


@router.get("/status")
def pattern_status() -> dict[str, Any]:
    """Store stats + LLM gateway/provider diagnostics in one call."""
    ensure_pattern_store()
    stats = store_stats()
    try:
        gateway_info = get_gateway().describe()
    except Exception as ex:
        gateway_info = {"provider": "unknown", "available": False, "error": str(ex)[:200]}
    return {"ok": True, "stats": stats, "gateway": gateway_info}


@router.get("")
@router.get("/")
def list_pattern_candidates(
    status: str = Query(default="candidate", max_length=40),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    try:
        items = list_patterns(status=status, limit=limit)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return {"ok": True, "patterns": items, "count": len(items)}


@router.get("/workspace")
def pattern_workspace() -> dict[str, Any]:
    """Patterns grouped into per-field and cross-field combination containers."""
    ensure_pattern_store()
    patterns = list_patterns(status="", limit=300)
    groups: dict[str, dict[str, Any]] = {}
    for row in patterns:
        try:
            fields = _json.loads(str(row.get("fields_involved") or "[]"))
        except Exception:
            fields = []
        fields = [str(f or "").strip() for f in fields if str(f or "").strip()]
        if len(fields) >= 2:
            key = " + ".join(sorted(f.lower() for f in fields))
        elif len(fields) == 1:
            key = fields[0].lower()
        else:
            key = "unassigned"
        group = groups.setdefault(
            key,
            {"container_key": key, "fields": fields, "patterns": [], "last_discovered": ""},
        )
        group["patterns"].append(_pattern_public(row))
        discovered = str(row.get("discovered_at") or "")
        if discovered > group["last_discovered"]:
            group["last_discovered"] = discovered

    # Library document counts per scientific field -> per-container coverage.
    field_doc_counts: dict[str, int] = {}
    extracted_by_field: dict[str, set[int]] = {}
    try:
        with _library_connection("gemma") as conn:
            for r in conn.execute(
                "SELECT COALESCE(scientific_field, '') AS f, COUNT(1) AS n FROM documents GROUP BY COALESCE(scientific_field, '')"
            ).fetchall():
                norm_f = "-".join(str(r["f"] or "").strip().lower().split())
                field_doc_counts[norm_f] = field_doc_counts.get(norm_f, 0) + int(r["n"])
        with _store_connect() as sconn:
            ok_doc_ids = [
                int(r["document_id"])
                for r in sconn.execute(
                    "SELECT DISTINCT document_id FROM pattern_extraction_log WHERE status = 'ok' AND document_id IS NOT NULL"
                ).fetchall()
            ]
        if ok_doc_ids:
            marks = ",".join("?" for _ in ok_doc_ids)
            with _library_connection("gemma") as conn:
                for r in conn.execute(
                    f"SELECT id, COALESCE(scientific_field, '') AS f FROM documents WHERE id IN ({marks})",
                    ok_doc_ids,
                ).fetchall():
                    norm_f = "-".join(str(r["f"] or "").strip().lower().split())
                    extracted_by_field.setdefault(norm_f, set()).add(int(r["id"]))
    except Exception:
        pass

    containers: list[dict[str, Any]] = []
    for group in groups.values():
        fields = group["fields"]
        primary = "-".join((fields[0] if fields else "unassigned").lower().split())
        total_docs = field_doc_counts.get(primary, 0)
        done_docs = len(extracted_by_field.get(primary, set()))
        containers.append(
            {
                **group,
                "pattern_count": len(group["patterns"]),
                "is_combination": len(fields) >= 2,
                "library_docs": total_docs,
                "analyzed_docs": done_docs,
                "coverage_percent": round(100.0 * done_docs / total_docs, 1) if total_docs else 0.0,
            }
        )
    containers.sort(key=lambda c: (-c["pattern_count"], c["container_key"]))
    return {
        "ok": True,
        "containers": containers,
        "stats": store_stats(),
        "active_discovery": {
            field: _load_progress.job_snapshot(job_id)
            for field, job_id in list(_ACTIVE_DISCOVERY.items())
        },
        "recognition_enabled": get_pattern_recognition_enabled(),
        "paused_message": "" if get_pattern_recognition_enabled() else PAUSED_MESSAGE,
    }


@router.get("/assessment-matrix")
def assessment_matrix_endpoint() -> Response:
    """§78: the Assessment Matrix document (corrections/Assessment_Matrix.docx)
    rendered as a standalone HTML page — headings, prose, all tables, the
    embedded figure and the code samples. This is the scoring law behind the
    New Patterns workspace; the owner asked to containerise it here rather
    than leave it as a raw docx.

    Registered BEFORE the /{pattern_id} catch-all: FastAPI matches routes in
    registration order, so a later literal path would be shadowed by it."""
    from .config import get_project_root
    from .assessment_matrix import get_assessment_matrix_html

    try:
        rendered = get_assessment_matrix_html(get_project_root())
    except FileNotFoundError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Assessment Matrix render failed: {ex}")
    return Response(
        content=rendered,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/discovery-status")
def pattern_discovery_status() -> dict[str, Any]:
    """Overall recognition coverage across the whole knowledge library."""
    ensure_pattern_store()
    enabled = get_pattern_recognition_enabled()
    total_docs = 0
    try:
        with _library_connection("gemma") as conn:
            total_docs = int(conn.execute("SELECT COUNT(1) AS n FROM documents").fetchone()["n"])
    except Exception:
        pass
    with _store_connect() as conn:
        analyzed = int(
            conn.execute(
                "SELECT COUNT(DISTINCT document_id) AS n FROM pattern_extraction_log WHERE status = 'ok' AND document_id IS NOT NULL"
            ).fetchone()["n"]
        )
        queued = int(conn.execute("SELECT COUNT(1) AS n FROM pattern_extraction_log WHERE status = 'queued'").fetchone()["n"])
        candidates = int(conn.execute("SELECT COUNT(1) AS n FROM patterns WHERE status = 'candidate'").fetchone()["n"])
    percent = round(100.0 * analyzed / total_docs, 1) if total_docs else 0.0
    return {
        "ok": True,
        "library_documents": total_docs,
        "documents_analyzed": analyzed,
        "queued": queued,
        "candidate_patterns": candidates,
        "percent": percent,
        "active": dict(_ACTIVE_DISCOVERY),
        "recognition_enabled": enabled,
    }


def _pattern_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row.get("id") or 0),
        "title": str(row.get("title") or ""),
        "statement": str(row.get("statement") or ""),
        "pattern_type": str(row.get("pattern_type") or "general"),
        "fields_involved": row.get("fields_involved") or "[]",
        "confidence": float(row.get("confidence") or 0.0),
        "status": str(row.get("status") or "candidate"),
        "discovered_at": str(row.get("discovered_at") or ""),
        "benefits": str(row.get("benefits") or ""),
        "has_benefits": bool(str(row.get("benefits") or "").strip()),
    }


def _generate_benefits(pattern: dict[str, Any]) -> str:
    """LLM-generated potential-benefit notes for one pattern."""
    evidence_rows = pattern.get("evidence") or []
    evidence_text = " ".join(
        str((e or {}).get("chunk_text") or "")[:300] for e in evidence_rows[:3]
    )[:900]
    messages = [
        {
            "role": "system",
            "content": (
                "You are Sentinel, a scientific pattern analyst. Answer with exactly three "
                "short numbered lines, one sentence each, concrete and specific. No preamble."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Pattern: {pattern.get('title')}\n"
                f"Type: {pattern.get('pattern_type')}\n"
                f"Fields: {pattern.get('fields_involved')}\n"
                f"Statement: {pattern.get('statement')}\n"
                f"Evidence excerpts: {evidence_text}\n\n"
                "List the three most significant potential benefits of recognizing this "
                "pattern - for science, for society (including AI), or for solving real problems."
            ),
        },
    ]
    text = get_gateway().chat(messages, temperature=0.2, max_tokens=320)
    return str(text or "").strip()[:2000]


@router.get("/{pattern_id}/benefits")
def pattern_benefits(pattern_id: int) -> dict[str, Any]:
    """Potential benefits of a pattern; LLM-generated once, then cached."""
    pattern = get_pattern(pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found.")
    if str(pattern.get("benefits") or "").strip():
        return {"ok": True, "pattern_id": pattern_id, "benefits": pattern["benefits"], "cached": True}
    try:
        benefits = _generate_benefits(pattern)
    except LLMGatewayError as ex:
        raise HTTPException(status_code=503, detail=f"Benefit analysis unavailable: {ex}")
    with _store_connect() as conn:
        conn.execute(
            "UPDATE patterns SET benefits = ?, benefits_generated_at = datetime('now') WHERE id = ?",
            (benefits, int(pattern_id)),
        )
        conn.commit()
    return {"ok": True, "pattern_id": pattern_id, "benefits": benefits, "cached": False}


def _utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_FIELD_ALIASES: dict[str, list[str]] = {
    "health": ["medicine", "public-health", "pharmacology", "neuroscience", "biology", "genetics-molecular-biology"],
    "medicine": ["medicine", "public-health", "pharmacology"],
    "medical": ["medicine", "public-health", "pharmacology"],
    "biology": ["biology", "genetics-molecular-biology", "ecology-environmental-biology", "neuroscience"],
    "physics": ["physics", "quantum-physics", "astronomy-cosmology"],
    "computer-science": ["computer-and-information-sciences", "information-science"],
    "ai": ["computer-and-information-sciences", "information-science"],
    "artificial-intelligence": ["computer-and-information-sciences", "information-science"],
    "cs": ["computer-and-information-sciences", "information-science"],
    "social-sciences": ["economics", "political-science", "sociology", "psychology", "anthropology"],
    "society": ["economics", "political-science", "sociology", "psychology", "anthropology"],
}


def _expand_field_aliases(field_slug: str) -> list[str]:
    clean = "-".join(str(field_slug or "").strip().lower().replace("_", "-").split())
    if not clean or clean in {"all", "*", "every", "all-fields"}:
        return []
    aliases = list(_FIELD_ALIASES.get(clean, []))
    for variant in (clean, clean.replace("-", " ")):
        if variant and variant not in aliases:
            aliases.append(variant)
    return aliases


def _batch_triage_documents(
    conn: Any,
    pool_rows: list[Any],
    rep: Any,
    *,
    topic_terms: list[str] | None = None,
) -> list[tuple[float, int, str, dict[str, Any], list[int]]]:
    """Fetch first 8 chunks for up to 60 documents in ONE query and rank via §74l crisis lexicon (+ optional topic terms)."""
    from .pattern_lexicon import scan_document_text

    if not pool_rows:
        return []
    pool_ids = [int(r["id"]) for r in pool_rows]
    marks = ",".join("?" for _ in pool_ids)
    chunk_rows = conn.execute(
        f"""
        SELECT id, document_id, chunk_index, content
        FROM chunks
        WHERE document_id IN ({marks}) AND chunk_index < 8
        ORDER BY document_id, chunk_index
        """,
        pool_ids,
    ).fetchall()
    chunks_by_doc: dict[int, list[tuple[int, str]]] = {}
    for cr in chunk_rows:
        chunks_by_doc.setdefault(int(cr["document_id"]), []).append(
            (int(cr["id"]), str(cr["content"] or ""))
        )

    clean_terms = [t.strip().lower() for t in (topic_terms or []) if len(t.strip()) >= 3]
    triaged: list[tuple[float, int, str, dict[str, Any], list[int]]] = []
    for row in pool_rows:
        if _load_progress.is_cancel_requested(getattr(rep, "job_id", "")):
            return []
        doc_id = int(row["id"])
        title = str(row["title"] or "")
        doc_chunks = chunks_by_doc.get(doc_id) or []
        text = " ".join(c_text for _, c_text in doc_chunks)
        triage = scan_document_text(f"{title}\n{text}")
        score = float(triage.get("score") or 0.0)
        matched_chunk_ids: list[int] = []
        if clean_terms:
            title_low = title.lower()
            for term in clean_terms:
                if term in title_low:
                    score += 20.0
            for cid, c_text in doc_chunks:
                c_low = c_text.lower()
                hits = sum(1 for term in clean_terms if term in c_low)
                if hits > 0:
                    score += 10.0 * hits
                    matched_chunk_ids.append(cid)
        triaged.append((round(score, 1), doc_id, title, triage, matched_chunk_ids))
    triaged.sort(key=lambda item: (-item[0], -item[1]))
    return triaged


def _discover_field_impl(field_slug: str, rep: Any, max_documents: int, max_chunks: int) -> dict[str, Any]:
    started = _utc()
    is_all = not field_slug or field_slug in {"all", "*", "all-fields"}
    label_field = "all fields" if is_all else field_slug
    aliases = _expand_field_aliases(field_slug)

    _load_progress.stage("download", f"Ranking {label_field} documents by crisis & threat signal (§74l lexicon)...")
    with _store_connect() as sconn:
        done_ids = {
            int(r["document_id"])
            for r in sconn.execute(
                "SELECT DISTINCT document_id FROM pattern_extraction_log WHERE status = 'ok' AND document_id IS NOT NULL"
            ).fetchall()
        }

    with _library_connection("gemma") as conn:
        if is_all or not aliases:
            raw_rows = conn.execute(
                "SELECT id, title FROM documents ORDER BY id DESC LIMIT 180"
            ).fetchall()
        else:
            marks = ",".join("?" for _ in aliases)
            like_clauses = " OR ".join("LOWER(COALESCE(scientific_field, '')) LIKE ?" for _ in aliases)
            params = [*aliases, *[f"%{a}%" for a in aliases]]
            raw_rows = conn.execute(
                f"""
                SELECT id, title FROM documents
                WHERE LOWER(COALESCE(scientific_field, '')) IN ({marks})
                   OR ({like_clauses})
                ORDER BY id DESC LIMIT 180
                """,
                params,
            ).fetchall()
        unanalyzed = [r for r in raw_rows if int(r["id"]) not in done_ids]
        pool_rows = (unanalyzed if len(unanalyzed) >= max_documents else raw_rows)[:60]
        triaged = _batch_triage_documents(conn, pool_rows, rep)
        if _load_progress.is_cancel_requested(getattr(rep, "job_id", "")):
            return {"ok": True, "cancelled": True, "field": label_field, "analyzed": 0}

    picked = triaged[: max(1, min(12, int(max_documents)))]
    doc_ids = [item[1] for item in picked]
    titles = {item[1]: item[2] for item in picked}
    if not doc_ids:
        return {"ok": False, "reason": "no-documents", "field": label_field}
    crisis_picked = sum(1 for item in picked if item[0] >= 5.0)
    top_scores = [
        {"document_id": item[1], "title": item[2][:80], "score": item[0], "matched_terms": int((item[3] or {}).get("matched_terms") or 0)}
        for item in picked[:5]
    ]

    gateway_desc = get_gateway().describe()
    if not gateway_desc.get("available"):
        return {
            "ok": True,
            "field": label_field,
            "engine_dark": True,
            "reason": "engine-unavailable",
            "message": "No LLM engine is configured, so extraction is held. The crisis lexicon still ranked the field's documents (§74l).",
            "documents_scanned": 0,
            "patterns_proposed": 0,
            "pattern_ids": [],
            "benefits_generated": 0,
            "crisis_lexicon": {
                "high_priority_documents": crisis_picked,
                "pool_triaged": len(triaged),
                "top_scores": top_scores,
            },
            "started_at": started,
        }

    _load_progress.stage("download", f"Scanning {len(doc_ids)} document(s) in {label_field}...")
    proposed_ids: list[int] = []
    errors: list[str] = []
    with _store_connect() as conn:
        max_known_id = int(conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM patterns").fetchone()["m"])
    for index, doc_id in enumerate(doc_ids, start=1):
        title = str(titles.get(doc_id) or doc_id)
        rep.report((index - 1) / len(doc_ids), f"Extracting patterns from \"{title[:60]}\" ({index}/{len(doc_ids)})...")
        if _load_progress.is_cancel_requested(getattr(rep, "job_id", "")):
            return {"ok": True, "cancelled": True, "field": label_field, "analyzed": index - 1}
        try:
            result = extract_document(doc_id, max_chunks=max_chunks)
            if str(result.get("reason") or "") == "paused":
                return {"ok": True, "cancelled": True, "field": label_field, "analyzed": index - 1}
            if not result.get("ok") and result.get("reason"):
                errors.append(f"doc {doc_id}: {result.get('reason')}")
        except Exception as ex:
            errors.append(f"doc id={doc_id}: {str(ex)[:120]}")
    with _store_connect() as conn:
        new_rows = conn.execute(
            "SELECT id FROM patterns WHERE id > ? ORDER BY id", (max_known_id,)
        ).fetchall()
    proposed_ids = [int(r["id"]) for r in new_rows]

    # Generate benefits for this field's newest patterns.
    _load_progress.stage("embed", "Analyzing potential benefits of new patterns...")
    benefits_ok = 0
    newest = list(reversed(proposed_ids))[:5]
    for offset, pattern_id in enumerate(newest):
        rep.report(offset / max(1, len(newest)), f"Analyzing benefits of pattern {pattern_id}...")
        try:
            pattern = get_pattern(pattern_id)
            if pattern and not str(pattern.get("benefits") or "").strip():
                benefits = _generate_benefits(pattern)
                with _store_connect() as conn:
                    conn.execute(
                        "UPDATE patterns SET benefits = ?, benefits_generated_at = datetime('now') WHERE id = ?",
                        (benefits, int(pattern_id)),
                    )
                    conn.commit()
                benefits_ok += 1
        except Exception:
            continue

    return {
        "ok": True,
        "field": label_field,
        "documents_scanned": len(doc_ids),
        "patterns_proposed": len(proposed_ids),
        "pattern_ids": proposed_ids,
        "benefits_generated": benefits_ok,
        "crisis_lexicon": {
            "high_priority_documents": crisis_picked,
            "pool_triaged": len(triaged),
            "top_scores": top_scores,
        },
        "errors": errors[:6],
        "started_at": started,
    }


def _discover_field_worker(field_slug: str, job_id: str, max_documents: int, max_chunks: int) -> None:
    rep = _load_progress.job_reporter(job_id)
    try:
        with _load_progress.bind(rep):
            result = _discover_field_impl(field_slug, rep, max_documents, max_chunks)
        if result.get("cancelled"):
            _load_progress.finish_job(job_id, {**result, "message": "Pattern discovery paused by owner."})
        else:
            _load_progress.finish_job(job_id, result)
    except Exception as ex:
        _load_progress.error_job(job_id, str(ex) or ex.__class__.__name__)
    finally:
        _ACTIVE_DISCOVERY.pop(field_slug, None)


@router.post("/discover/all")
def discover_all_field_patterns(
    max_documents: int = Query(default=6, ge=1, le=12),
    max_chunks: int = Query(default=4, ge=1, le=10),
) -> dict[str, Any]:
    """Start live pattern discovery across all scientific fields."""
    return discover_field_patterns("all", max_documents=max_documents, max_chunks=max_chunks)


@router.post("/discover/field/{field_slug}")
def discover_field_patterns(
    field_slug: str,
    max_documents: int = Query(default=6, ge=1, le=12),
    max_chunks: int = Query(default=4, ge=1, le=10),
) -> dict[str, Any]:
    """Start live pattern discovery for one scientific field or 'all' (background job)."""
    ensure_pattern_store()
    if not get_pattern_recognition_enabled():
        raise HTTPException(status_code=409, detail=PAUSED_MESSAGE)
    field = str(field_slug or "all").strip().lower()
    if field == "unassigned":
        field = "all"
    if not _DISCOVERY_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A pattern discovery is already running - wait for it to finish.")
    try:
        label_field = "all fields" if field in {"all", "*"} else field
        job_id, _rep = _load_progress.start_job(
            label=f"Pattern discovery: {label_field}",
            field=field,
            source_type="pattern-discovery",
            title=f"New pattern recognition in {label_field}",
        )
        worker = _threading.Thread(
            target=_discover_field_worker,
            args=(field, job_id, max_documents, max_chunks),
            name=f"pattern-discovery-{job_id}",
            daemon=True,
        )
        _ACTIVE_DISCOVERY[field] = job_id
        worker.start()
        return {"ok": True, "job_id": job_id, "async": True, "field": field}
    finally:
        _DISCOVERY_LOCK.release()


_DISCOVERY_LOCK = _threading.Lock()
_ACTIVE_DISCOVERY: dict[str, str] = {}  # field_slug -> job_id


@router.get("/future-requests")
def list_future_requests_endpoint(kind: str = Query(default="")) -> dict[str, Any]:
    return {"ok": True, "requests": _list_future_requests(kind)}


# ---------------------------------------------------------------------------
# Pattern recognition master switch (owner pause control)
# ---------------------------------------------------------------------------

class RecognitionSwitch(BaseModel):
    enabled: bool


@router.get("/recognition-switch")
def recognition_switch_status() -> dict[str, Any]:
    return {"ok": True, "recognition_enabled": get_pattern_recognition_enabled()}


@router.post("/recognition-switch")
def recognition_switch_set(payload: RecognitionSwitch) -> dict[str, Any]:
    """Persist the owner's ON/OFF switch. When pausing, any running discovery
    job is cancelled at its next document/chunk boundary."""
    set_pattern_recognition_enabled(bool(payload.enabled))
    cancelled: list[str] = []
    if not payload.enabled:
        with _DISCOVERY_LOCK:
            for field, job_id in list(_ACTIVE_DISCOVERY.items()):
                _load_progress.cancel_job(job_id)
                cancelled.append(f"{field}:{job_id}")
    return {
        "ok": True,
        "recognition_enabled": bool(payload.enabled),
        "cancelled_jobs": cancelled,
        "message": "Pattern recognition resumed." if payload.enabled else PAUSED_MESSAGE,
    }


@router.get("/{pattern_id}")
def get_pattern_detail(pattern_id: int) -> dict[str, Any]:
    pattern = get_pattern(pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found.")
    return {"ok": True, "pattern": pattern}


@router.post("/{pattern_id}/review")
def review_pattern_endpoint(pattern_id: int, payload: ReviewRequest) -> dict[str, Any]:
    try:
        updated = review_pattern(pattern_id, payload.decision, payload.note)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    return {"ok": True, "pattern": updated}


@router.post("/analyze/{document_id}")
def analyze_document(document_id: int) -> dict[str, Any]:
    """Queue + immediately extract patterns from one library document."""
    if not get_pattern_recognition_enabled():
        raise HTTPException(status_code=409, detail=PAUSED_MESSAGE)
    queue_document(document_id)
    result = extract_document(document_id)
    return {"ok": result.get("ok", False), "result": result}


@router.post("/process-queue")
def run_queue(limit: int = Query(default=5, ge=1, le=25)) -> dict[str, Any]:
    if not get_pattern_recognition_enabled():
        raise HTTPException(status_code=409, detail=PAUSED_MESSAGE)
    return process_queue(limit=limit)


@router.post("/synthesize")
def run_synthesis(max_pairs: int = Query(default=6, ge=1, le=20)) -> dict[str, Any]:
    if not get_pattern_recognition_enabled():
        raise HTTPException(status_code=409, detail=PAUSED_MESSAGE)
    try:
        return synthesize_cross_domain(max_pairs=max_pairs)
    except LLMGatewayError as ex:
        raise HTTPException(status_code=503, detail=str(ex))


# ---------------------------------------------------------------------------
# §79: R&D Validation Papers — generate + view (math computed by
# app/assessment_math.py from the pattern's real extraction record)
# ---------------------------------------------------------------------------

from .rd_paper import get_or_generate_rd_report, render_rd_report_html


# ---------------------------------------------------------------------------
# §80: ML hardening — PINN verification of discovered patterns (ml/ stack)
# ---------------------------------------------------------------------------

from .ml_hardening import get_cached_report, run_hardening


@router.get("/ml-hardening/report")
def ml_hardening_report() -> dict[str, Any]:
    """Cached hardening report (verdicts for every pattern)."""
    report = get_cached_report()
    if report is None:
        return {"ok": True, "cached": False, "message": "No hardening run yet — POST /api/patterns/ml-hardening/run to execute the PINN pass."}
    return {"ok": True, "cached": True, "report": report}


@router.post("/ml-hardening/run")
def ml_hardening_run(
    epochs: int = Query(default=600, ge=100, le=4000),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """Run the PINN hardening pass in the .venv-ml environment (GPU when available).

    Encodes every pattern's real extraction record into features, trains the
    SiLU network to fit analysis outcomes, and enforces the Assessment
    Matrix's volatility-anchor law (d(sustainability)/d(risk) <= 0) as a
    differentiable constraint. Verdicts: stable / weak / volatile /
    insufficient-data."""
    report = run_hardening(limit=limit, epochs=epochs)
    if not report.get("ok"):
        raise HTTPException(status_code=503, detail=str(report.get("error") or "hardening run failed"))
    return {"ok": True, "report": report}


@router.get("/rd-paper/{pattern_id}/report")
def rd_paper_report_endpoint(pattern_id: int, regenerate: int = Query(default=0)) -> Response:
    """Generate (once, cached in the pattern store) and render the R&D
    validation paper for a pattern. Matrix scores, SD_i(%) and the coupled
    bell curves are computed from the pattern's actual extraction record."""
    try:
        report = get_or_generate_rd_report(int(pattern_id), force=bool(regenerate))
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    return Response(
        content=render_rd_report_html(report),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/rd-paper/{pattern_id}/data")
def rd_paper_data_endpoint(pattern_id: int, regenerate: int = Query(default=0)) -> dict[str, Any]:
    """The raw reportData object (the schema from corrections/R&DPaper.md)."""
    try:
        report = get_or_generate_rd_report(int(pattern_id), force=bool(regenerate))
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    return {"ok": True, "report": report}


# ---------------------------------------------------------------------------
# Reports: HTML preview + PDF download, APA 7th works cited
# ---------------------------------------------------------------------------

from .pattern_report import (
    build_report,
    render_report_html,
    render_report_text,
    report_pdf_bytes,
    safe_filename,
)


def _report_response(report: dict, want_pdf: bool) -> Response:
    if want_pdf:
        data = report_pdf_bytes(report)
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename(report["title"])}.pdf"'},
        )
    return Response(
        content=render_report_html(report),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/reports/container/{container_key:path}/report")
def container_report_endpoint(container_key: str, format: str = Query(default="html")):  # noqa: A002
    try:
        report = build_report(container_key=container_key)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    return _report_response(report, want_pdf=(format.lower() == "pdf"))


@router.get("/reports/pattern/{pattern_id}/report")
def pattern_report_endpoint(pattern_id: int, format: str = Query(default="html")):  # Patterns PDFs are container-scoped anyway.
    report = build_report(container_key=_container_key_for_pattern(int(pattern_id)))
    return _report_response(report, want_pdf=(format.lower() == "pdf"))


def _container_key_for_pattern(pattern_id: int) -> str:
    pattern = get_pattern(pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found.")
    fields = []
    try:
        fields = [str(f) for f in _json.loads(str(pattern.get("fields_involved") or "[]"))]
    except Exception:
        fields = []
    return "+".join(fields) if fields else "unassigned"


# ---------------------------------------------------------------------------
# Future requests: R&D paper launcher + manual (user-requested) discovery
# ---------------------------------------------------------------------------

import re as _re
from .pattern_store import (
    get_future_request as _get_future_request,
    list_future_requests as _list_future_requests,
    record_future_request as _record_future_request,
    update_future_request as _update_future_request,
)


class FutureRequestPayload(BaseModel):
    pattern_id: int | None = None
    topic: str = Field(default="", max_length=300)
    fields: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=2000)


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "between",
    "patterns", "pattern", "linking", "about", "find", "search", "look", "how",
}


def _topic_search_terms(topic: str, note: str = "") -> list[str]:
    combined = f"{topic} {note}".lower()
    words = [w for w in _re.findall(r"[a-z0-9'\-]{3,}", combined) if w not in _STOPWORDS]
    out: list[str] = []
    if len(topic.strip()) >= 4:
        out.append(topic.strip().lower())
    for w in words:
        if w not in out:
            out.append(w)
    return out[:10]


def _discover_manual_impl(
    request_id: int,
    topic: str,
    fields: list[str],
    note: str,
    rep: Any,
    max_documents: int = 6,
    max_chunks: int = 4,
) -> dict[str, Any]:
    started = _utc()
    _update_future_request(request_id, status="running")
    terms = _topic_search_terms(topic, note)
    field_aliases: list[str] = []
    for f in fields:
        for alias in _expand_field_aliases(f):
            if alias not in field_aliases:
                field_aliases.append(alias)

    label = topic.strip() or (fields[0] if fields else "manual request")
    _load_progress.stage("download", f"Searching knowledge library for \"{label}\" + crisis lexicon (§74l)...")

    with _library_connection("gemma") as conn:
        candidate_docs: dict[int, Any] = {}
        # 1. Search documents by title / topic / module / scientific_field + optional field filter
        if terms:
            term_likes = " OR ".join(
                "(LOWER(COALESCE(title, '')) LIKE ? OR LOWER(COALESCE(topic, '')) LIKE ? OR LOWER(COALESCE(scientific_field, '')) LIKE ?)"
                for _ in terms[:6]
            )
            t_params: list[Any] = []
            for t in terms[:6]:
                like_val = f"%{t}%"
                t_params.extend([like_val, like_val, like_val])
            if field_aliases:
                f_marks = ",".join("?" for _ in field_aliases)
                f_likes = " OR ".join("LOWER(COALESCE(scientific_field, '')) LIKE ?" for _ in field_aliases)
                sql = (
                    f"SELECT id, title FROM documents WHERE ({term_likes}) "
                    f"AND (LOWER(COALESCE(scientific_field, '')) IN ({f_marks}) OR ({f_likes})) "
                    f"ORDER BY id DESC LIMIT 60"
                )
                rows = conn.execute(sql, [*t_params, *field_aliases, *[f"%{a}%" for a in field_aliases]]).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT id, title FROM documents WHERE ({term_likes}) ORDER BY id DESC LIMIT 60",
                    t_params,
                ).fetchall()
            for r in rows:
                candidate_docs[int(r["id"])] = r

        # 2. Search chunks for the requested topic terms if we need more candidates
        if len(candidate_docs) < 30 and terms:
            c_likes = " OR ".join("LOWER(content) LIKE ?" for _ in terms[:4])
            c_params = [f"%{t}%" for t in terms[:4]]
            c_rows = conn.execute(
                f"""
                SELECT DISTINCT d.id, d.title
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE ({c_likes})
                ORDER BY d.id DESC
                LIMIT 60
                """,
                c_params,
            ).fetchall()
            for r in c_rows:
                candidate_docs.setdefault(int(r["id"]), r)

        # 3. Fallback to field documents if topic was broad (e.g. "medicine" in field "health")
        if len(candidate_docs) < max_documents and field_aliases:
            f_marks = ",".join("?" for _ in field_aliases)
            f_likes = " OR ".join("LOWER(COALESCE(scientific_field, '')) LIKE ?" for _ in field_aliases)
            f_rows = conn.execute(
                f"""
                SELECT id, title FROM documents
                WHERE LOWER(COALESCE(scientific_field, '')) IN ({f_marks}) OR ({f_likes})
                ORDER BY id DESC LIMIT 60
                """,
                [*field_aliases, *[f"%{a}%" for a in field_aliases]],
            ).fetchall()
            for r in f_rows:
                candidate_docs.setdefault(int(r["id"]), r)

        # 4. Final fallback to newest library documents
        if not candidate_docs:
            for r in conn.execute("SELECT id, title FROM documents ORDER BY id DESC LIMIT 60").fetchall():
                candidate_docs[int(r["id"])] = r

        pool_rows = list(candidate_docs.values())[:60]
        triaged = _batch_triage_documents(conn, pool_rows, rep, topic_terms=terms)
        if _load_progress.is_cancel_requested(getattr(rep, "job_id", "")):
            _update_future_request(request_id, status="cancelled")
            return {"ok": True, "cancelled": True, "topic": topic, "analyzed": 0}

    picked = triaged[: max(1, min(12, int(max_documents)))]
    doc_ids = [item[1] for item in picked]
    titles = {item[1]: item[2] for item in picked}
    pref_chunks = {item[1]: item[4] for item in picked}
    if not doc_ids:
        _update_future_request(request_id, status="no matching documents")
        return {"ok": False, "reason": "no-documents", "topic": topic}

    crisis_picked = sum(1 for item in picked if item[0] >= 5.0)
    top_scores = [
        {"document_id": item[1], "title": item[2][:80], "score": item[0], "matched_terms": int((item[3] or {}).get("matched_terms") or 0)}
        for item in picked[:5]
    ]

    gateway_desc = get_gateway().describe()
    if not gateway_desc.get("available"):
        _update_future_request(request_id, status="held (engine dark)")
        return {
            "ok": True,
            "topic": topic,
            "engine_dark": True,
            "reason": "engine-unavailable",
            "message": "No LLM engine is configured, so extraction is held. Topic & crisis ranking completed.",
            "documents_scanned": 0,
            "patterns_proposed": 0,
            "pattern_ids": [],
            "benefits_generated": 0,
            "crisis_lexicon": {
                "high_priority_documents": crisis_picked,
                "pool_triaged": len(triaged),
                "top_scores": top_scores,
            },
            "started_at": started,
        }

    _load_progress.stage("download", f"Extracting patterns for \"{label}\" across {len(doc_ids)} document(s)...")
    errors: list[str] = []
    with _store_connect() as conn:
        max_known_id = int(conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM patterns").fetchone()["m"])

    for index, doc_id in enumerate(doc_ids, start=1):
        title = str(titles.get(doc_id) or doc_id)
        rep.report((index - 1) / len(doc_ids), f"Targeted extraction on \"{title[:55]}\" ({index}/{len(doc_ids)})...")
        if _load_progress.is_cancel_requested(getattr(rep, "job_id", "")):
            _update_future_request(request_id, status="cancelled")
            return {"ok": True, "cancelled": True, "topic": topic, "analyzed": index - 1}
        try:
            result = extract_document(
                doc_id,
                max_chunks=max_chunks,
                focus_topic=topic,
                focus_note=note,
                preferred_chunk_ids=pref_chunks.get(doc_id) or None,
            )
            if str(result.get("reason") or "") == "paused":
                _update_future_request(request_id, status="paused")
                return {"ok": True, "cancelled": True, "topic": topic, "analyzed": index - 1}
            if not result.get("ok") and result.get("reason"):
                errors.append(f"doc {doc_id}: {result.get('reason')}")
        except Exception as ex:
            errors.append(f"doc id={doc_id}: {str(ex)[:120]}")

    # Also run a targeted cross-domain synthesis pass for this topic
    try:
        rep.report(0.85, f"Synthesizing cross-domain patterns for \"{label[:50]}\"...")
        synthesize_cross_domain(max_pairs=3, focus_topic=topic)
    except Exception:
        pass

    with _store_connect() as conn:
        new_rows = conn.execute(
            "SELECT id FROM patterns WHERE id > ? ORDER BY id", (max_known_id,)
        ).fetchall()
    proposed_ids = [int(r["id"]) for r in new_rows]

    _load_progress.stage("embed", "Analyzing potential benefits of newly discovered patterns...")
    benefits_ok = 0
    newest = list(reversed(proposed_ids))[:5]
    for offset, pattern_id in enumerate(newest):
        rep.report(offset / max(1, len(newest)), f"Analyzing benefits of pattern {pattern_id}...")
        try:
            pattern = get_pattern(pattern_id)
            if pattern and not str(pattern.get("benefits") or "").strip():
                benefits = _generate_benefits(pattern)
                with _store_connect() as conn:
                    conn.execute(
                        "UPDATE patterns SET benefits = ?, benefits_generated_at = datetime('now') WHERE id = ?",
                        (benefits, int(pattern_id)),
                    )
                    conn.commit()
                benefits_ok += 1
        except Exception:
            continue

    status_str = f"completed ({len(proposed_ids)} pattern{'s' if len(proposed_ids) != 1 else ''})"
    _update_future_request(
        request_id,
        status=status_str,
        pattern_id=proposed_ids[0] if proposed_ids else None,
    )
    return {
        "ok": True,
        "request_id": request_id,
        "topic": topic,
        "fields": fields,
        "documents_scanned": len(doc_ids),
        "patterns_proposed": len(proposed_ids),
        "pattern_ids": proposed_ids,
        "benefits_generated": benefits_ok,
        "crisis_lexicon": {
            "high_priority_documents": crisis_picked,
            "pool_triaged": len(triaged),
            "top_scores": top_scores,
        },
        "errors": errors[:6],
        "started_at": started,
    }


def _discover_manual_worker(
    request_id: int,
    topic: str,
    fields: list[str],
    note: str,
    key: str,
    job_id: str,
    max_documents: int,
    max_chunks: int,
) -> None:
    rep = _load_progress.job_reporter(job_id)
    try:
        with _load_progress.bind(rep):
            result = _discover_manual_impl(
                request_id, topic, fields, note, rep, max_documents=max_documents, max_chunks=max_chunks
            )
        if result.get("cancelled"):
            _load_progress.finish_job(job_id, {**result, "message": "Manual pattern discovery paused by owner."})
        else:
            _load_progress.finish_job(job_id, result)
    except Exception as ex:
        _update_future_request(request_id, status="error")
        _load_progress.error_job(job_id, str(ex) or ex.__class__.__name__)
    finally:
        _ACTIVE_DISCOVERY.pop(key, None)


def _launch_manual_discovery_job(
    request_row: dict[str, Any],
    *,
    max_documents: int = 5,
    max_chunks: int = 3,
) -> str:
    req_id = int(request_row["id"])
    topic = str(request_row.get("topic") or "").strip()
    note = str(request_row.get("note") or "").strip()
    try:
        raw_fields = request_row.get("fields")
        fields = list(raw_fields) if isinstance(raw_fields, list) else _json.loads(str(raw_fields or "[]"))
    except Exception:
        fields = []
    fields = [str(f).strip() for f in fields if str(f).strip()]
    key = fields[0].lower() if fields else f"manual-{req_id}"
    label = topic or (fields[0] if fields else f"request #{req_id}")
    job_id, _rep = _load_progress.start_job(
        label=f"Manual pattern discovery: {label[:50]}",
        field=key,
        source_type="manual-pattern-discovery",
        title=f"User-requested pattern discovery: {label[:60]}",
    )
    worker = _threading.Thread(
        target=_discover_manual_worker,
        args=(req_id, topic, fields, note, key, job_id, max_documents, max_chunks),
        name=f"manual-pattern-discovery-{job_id}",
        daemon=True,
    )
    _ACTIVE_DISCOVERY[key] = job_id
    worker.start()
    return job_id


@router.post("/future-requests/rd-paper")
def request_rd_paper_endpoint(payload: FutureRequestPayload) -> dict[str, Any]:
    """Launch a future R&D paper request on a discovered pattern."""
    if payload.pattern_id is not None:
        pattern = get_pattern(int(payload.pattern_id))
        if pattern is None:
            raise HTTPException(status_code=404, detail=f"Pattern {payload.pattern_id} not found.")
        if not payload.topic:
            payload.topic = str(pattern.get("title") or "")
        if not payload.fields:
            try:
                payload.fields = [str(f) for f in _json.loads(str(pattern.get("fields_involved") or "[]"))]
            except Exception:
                payload.fields = []
    row = _record_future_request(
        "rd_paper",
        pattern_id=payload.pattern_id,
        topic=payload.topic,
        fields=payload.fields,
        note=payload.note,
    )
    return {"ok": True, "request": row, "message": "R&D paper request logged as future work."}


@router.post("/future-requests/manual-discovery")
def request_manual_discovery_endpoint(payload: FutureRequestPayload) -> dict[str, Any]:
    """Record AND actively execute a user-requested pattern discovery job."""
    if not payload.topic and not payload.note:
        raise HTTPException(status_code=422, detail="Describe the pattern you want Sentinel to look for.")
    ensure_pattern_store()
    if not get_pattern_recognition_enabled():
        row = _record_future_request(
            "manual_discovery",
            topic=payload.topic,
            fields=payload.fields,
            note=payload.note,
            status="queued (paused)",
        )
        return {"ok": True, "request": row, "job_id": "", "message": PAUSED_MESSAGE}
    row = _record_future_request(
        "manual_discovery",
        topic=payload.topic,
        fields=payload.fields,
        note=payload.note,
        status="running",
    )
    job_id = _launch_manual_discovery_job(row)
    return {
        "ok": True,
        "request": row,
        "job_id": job_id,
        "async": True,
        "message": f"Manual pattern discovery started for \"{payload.topic or payload.note}\".",
    }


@router.post("/future-requests/{request_id}/run")
def run_manual_discovery_request_endpoint(request_id: int) -> dict[str, Any]:
    """Execute or re-run a logged manual discovery request."""
    ensure_pattern_store()
    if not get_pattern_recognition_enabled():
        raise HTTPException(status_code=409, detail=PAUSED_MESSAGE)
    row = _get_future_request(int(request_id))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found.")
    job_id = _launch_manual_discovery_job(row)
    return {
        "ok": True,
        "request": row,
        "job_id": job_id,
        "async": True,
        "message": f"Running manual pattern discovery for \"{row.get('topic') or row.get('note')}\".",
    }
