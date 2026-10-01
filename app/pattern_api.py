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
                "SELECT IFNULL(scientific_field, '') AS f, COUNT(1) AS n FROM documents GROUP BY f"
            ):
                field_doc_counts[str(r["f"] or "").strip().lower()] = int(r["n"])
        ok_doc_ids = [
            int(r["document_id"])
            for r in _store_connect().execute(
                "SELECT DISTINCT document_id FROM pattern_extraction_log WHERE status = 'ok' AND document_id IS NOT NULL"
            )
        ]
        if ok_doc_ids:
            marks = ",".join("?" for _ in ok_doc_ids)
            with _library_connection("gemma") as conn:
                for r in conn.execute(
                    f"SELECT id, IFNULL(scientific_field, '') AS f FROM documents WHERE id IN ({marks})",
                    ok_doc_ids,
                ):
                    extracted_by_field.setdefault(str(r["f"] or "").strip().lower(), set()).add(int(r["id"]))
    except Exception:
        pass

    containers: list[dict[str, Any]] = []
    for group in groups.values():
        fields = group["fields"]
        primary = (fields[0] if fields else "unassigned").lower()
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


def _discover_field_impl(field_slug: str, rep: Any, max_documents: int, max_chunks: int) -> dict[str, Any]:
    started = _utc()

    # §74l — owner's crisis & threat lexicon ranks which documents the
    # scanner sees. Newest-first was blind; now up to 60 of the field's
    # documents are triaged against pattern_discovery/key_words_tags.md
    # (crises, threats, unsolved science) and the highest-scoring ones are
    # scanned first — the hunt starts where the danger words live.
    from .pattern_lexicon import scan_document_text

    _load_progress.stage("download", f"Ranking {field_slug}'s documents by crisis & threat signal (§74l lexicon)...")
    with _library_connection("gemma") as conn:
        pool_rows = conn.execute(
            "SELECT id, title FROM documents WHERE IFNULL(scientific_field, '') = ? ORDER BY id DESC LIMIT 60",
            (field_slug,),
        ).fetchall()
    triaged: list[tuple[float, int, str, dict[str, Any]]] = []
    for row in pool_rows:
        if _load_progress.is_cancel_requested(getattr(rep, "job_id", "")):
            return {"ok": True, "cancelled": True, "field": field_slug, "analyzed": 0}
        with _library_connection("gemma") as conn:
            chunk_rows = conn.execute(
                "SELECT content FROM chunks WHERE document_id = ? ORDER BY chunk_index LIMIT 8",
                (int(row["id"]),),
            ).fetchall()
        text = " ".join(str(r["content"] or "") for r in chunk_rows)
        triage = scan_document_text(text)
        triaged.append((float(triage.get("score") or 0.0), int(row["id"]), str(row["title"] or ""), triage))
    triaged.sort(key=lambda item: -item[0])
    picked = triaged[: max(1, min(12, int(max_documents)))]
    doc_ids = [item[1] for item in picked]
    titles = {item[1]: item[2] for item in picked}
    if not doc_ids:
        return {"ok": False, "reason": "no-documents", "field": field_slug}
    crisis_picked = sum(1 for item in picked if item[0] >= 5.0)
    top_scores = [
        {"document_id": item[1], "title": item[2][:80], "score": item[0], "matched_terms": int((item[3] or {}).get("matched_terms") or 0)}
        for item in picked[:5]
    ]

    # §74l pre-flight: ranking always runs — it is pure local signal work.
    # Extraction is engine work; when the engine is dark (strict Enigma
    # doctrine) we refuse here, dignified, instead of failing document by
    # document. The lexicon ranking report still stands for the owner.
    gateway_desc = get_gateway().describe()
    if not gateway_desc.get("available"):
        return {
            "ok": True,
            "field": field_slug,
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

    _load_progress.stage("download", f"Scanning {len(doc_ids)} document(s) in {field_slug}...")
    proposed_ids: list[int] = []
    errors: list[str] = []
    with _store_connect() as conn:
        max_known_id = int(conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM patterns").fetchone()["m"])
    for index, doc_id in enumerate(doc_ids, start=1):
        title = str(titles.get(doc_id) or doc_id)
        rep.report((index - 1) / len(doc_ids), f"Extracting patterns from \"{title[:60]}\" ({index}/{len(doc_ids)})...")
        if _load_progress.is_cancel_requested(getattr(rep, "job_id", "")):
            return {"ok": True, "cancelled": True, "field": field_slug, "analyzed": index - 1}
        try:
            result = extract_document(doc_id, max_chunks=max_chunks)
            if str(result.get("reason") or "") == "paused":
                return {"ok": True, "cancelled": True, "field": field_slug, "analyzed": index - 1}
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
        "field": field_slug,
        "documents_scanned": len(doc_ids),
        "patterns_proposed": len(proposed_ids),
        "pattern_ids": proposed_ids,
        "benefits_generated": benefits_ok,
        # §74l: how the crisis lexicon steered this scan.
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


@router.post("/discover/field/{field_slug}")
def discover_field_patterns(
    field_slug: str,
    max_documents: int = Query(default=6, ge=1, le=12),
    max_chunks: int = Query(default=4, ge=1, le=10),
) -> dict[str, Any]:
    """Start live pattern discovery for one scientific field (background job)."""
    ensure_pattern_store()
    if not get_pattern_recognition_enabled():
        raise HTTPException(status_code=409, detail=PAUSED_MESSAGE)
    field = str(field_slug or "").strip().lower()
    if not field or field == "unassigned":
        raise HTTPException(status_code=400, detail="Provide a valid scientific field.")
    if not _DISCOVERY_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A pattern discovery is already running - wait for it to finish.")
    try:
        job_id, _rep = _load_progress.start_job(
            label=f"Pattern discovery: {field}",
            field=field,
            source_type="pattern-discovery",
            title=f"New pattern recognition in {field}",
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

from .pattern_store import list_future_requests as _list_future_requests
from .pattern_store import record_future_request as _record_future_request


class FutureRequestPayload(BaseModel):
    pattern_id: int | None = None
    topic: str = Field(default="", max_length=300)
    fields: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=2000)


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
    """Log a manual (user-requested) pattern discovery request as future work."""
    if not payload.topic and not payload.note:
        raise HTTPException(status_code=422, detail="Describe the pattern you want Sentinel to look for.")
    row = _record_future_request(
        "manual_discovery",
        topic=payload.topic,
        fields=payload.fields,
        note=payload.note,
    )
    return {"ok": True, "request": row, "message": "Manual discovery request logged as future work."}
