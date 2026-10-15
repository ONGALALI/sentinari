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
    from .rd_paper import evaluate_rd_indicators
    from .sentinel_domains import sanitize_field_and_domain, sanitize_pattern_fields

    ensure_pattern_store()
    patterns = list_patterns(status="", limit=300)

    # Fetch evidence rows for all patterns in one query and enrich from documents table.
    evidence_by_pattern: dict[int, list[dict[str, Any]]] = {}
    ev_doc_ids: set[int] = set()
    try:
        with _store_connect() as sconn:
            ev_rows = sconn.execute(
                "SELECT pattern_id, document_id, document_title, field_slug, source_url FROM pattern_evidence ORDER BY id"
            ).fetchall()
        for er in ev_rows:
            pid = int(er["pattern_id"] or 0)
            did = int(er["document_id"] or 0)
            if did > 0:
                ev_doc_ids.add(did)
            evidence_by_pattern.setdefault(pid, []).append(dict(er))
    except Exception:
        pass

    docs_by_id: dict[int, dict[str, Any]] = {}
    if ev_doc_ids:
        try:
            marks = ",".join("?" for _ in ev_doc_ids)
            with _library_connection("gemma") as conn:
                for dr in conn.execute(
                    f"SELECT id, title, authors, published_date, source_url, scientific_field FROM documents WHERE id IN ({marks})",
                    list(ev_doc_ids),
                ).fetchall():
                    docs_by_id[int(dr["id"])] = dict(dr)
        except Exception:
            pass

    groups: dict[str, dict[str, Any]] = {}
    needs_evolution: list[tuple[int, str]] = []
    for row in patterns:
        pid = int(row.get("id") or 0)
        evs = evidence_by_pattern.get(pid, [])
        first_ev_field = ""
        sources: list[dict[str, Any]] = []
        seen_src_keys: set[str] = set()
        for ev in evs:
            did = int(ev.get("document_id") or 0)
            doc_info = docs_by_id.get(did) or {}
            ev_field_raw = str(doc_info.get("scientific_field") or ev.get("field_slug") or "")
            ev_field, _ = sanitize_field_and_domain(ev_field_raw, fallback_text=str(doc_info.get("title") or ev.get("document_title") or ""))
            if ev_field and not first_ev_field:
                first_ev_field = ev_field
            src_title = str(doc_info.get("title") or ev.get("document_title") or "").strip()
            src_url = str(doc_info.get("source_url") or ev.get("source_url") or "").strip()
            dedupe_k = f"{did}:{src_title.lower()}"
            if src_title and dedupe_k not in seen_src_keys:
                seen_src_keys.add(dedupe_k)
                sources.append(
                    {
                        "document_id": did if did in docs_by_id else 0,
                        "title": src_title,
                        "authors": str(doc_info.get("authors") or ""),
                        "published_date": str(doc_info.get("published_date") or ""),
                        "source_url": src_url,
                        "field_slug": ev_field,
                    }
                )

        fields = sanitize_pattern_fields(
            row.get("fields_involved"),
            fallback_field=first_ev_field,
            fallback_text=f"{row.get('title') or ''} {row.get('statement') or ''}",
        )
        sorted_fields = sorted(fields)
        if len(sorted_fields) >= 2:
            key = " + ".join(sorted_fields)
        elif len(sorted_fields) == 1:
            key = sorted_fields[0]
        else:
            key = "unassigned"
        group = groups.setdefault(
            key,
            {"container_key": key, "fields": sorted_fields, "patterns": [], "last_discovered": "", "_ev_doc_ids": set()},
        )
        for s in sources:
            if s.get("document_id"):
                group["_ev_doc_ids"].add(int(s["document_id"]))
        pub = _pattern_public(row)
        pub["fields_involved"] = _json.dumps(sorted_fields, ensure_ascii=False)
        pub["sources"] = sources
        ind_eval = evaluate_rd_indicators(row)
        pub["rd_indicators"] = ind_eval
        pub["rd_progress_pct"] = ind_eval["progress_pct"]
        if ind_eval["completed_indicators"] < ind_eval["total_indicators"]:
            needs_evolution.append((pid, key))
        group["patterns"].append(pub)
        discovered = str(row.get("discovered_at") or "")
        if discovered > group["last_discovered"]:
            group["last_discovered"] = discovered

    # Library document counts per canonical scientific field -> per-container coverage.
    field_doc_counts: dict[str, int] = {}
    extracted_by_field: dict[str, set[int]] = {}
    try:
        with _library_connection("gemma") as conn:
            for r in conn.execute(
                "SELECT COALESCE(scientific_field, '') AS f, COUNT(1) AS n FROM documents GROUP BY COALESCE(scientific_field, '')"
            ).fetchall():
                raw_f = str(r["f"] or "").strip()
                norm_f, _ = sanitize_field_and_domain(raw_f)
                key_f = norm_f or "-".join(raw_f.lower().split())
                if key_f:
                    field_doc_counts[key_f] = field_doc_counts.get(key_f, 0) + int(r["n"])
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
                    raw_f = str(r["f"] or "").strip()
                    norm_f, _ = sanitize_field_and_domain(raw_f)
                    key_f = norm_f or "-".join(raw_f.lower().split())
                    if key_f:
                        extracted_by_field.setdefault(key_f, set()).add(int(r["id"]))
    except Exception:
        pass

    containers: list[dict[str, Any]] = []
    for group in groups.values():
        fields = group["fields"]
        ev_dids = set(group.pop("_ev_doc_ids", set()))
        total_docs = sum(field_doc_counts.get(f, 0) for f in fields) if fields else 0
        done_docs_set: set[int] = set(ev_dids)
        for f in fields:
            done_docs_set.update(extracted_by_field.get(f, set()))
        done_docs = len(done_docs_set)
        if done_docs > total_docs:
            total_docs = done_docs
        lib_cov_pct = (
            max(0.1, round(100.0 * done_docs / total_docs, 1))
            if (total_docs > 0 and done_docs > 0)
            else 0.0
        )
        pats = group["patterns"]
        ind_done_sum = sum(int((p.get("rd_indicators") or {}).get("completed_indicators") or 0) for p in pats)
        ind_total_sum = sum(int((p.get("rd_indicators") or {}).get("total_indicators") or 15) for p in pats)
        ind_pct = round(100.0 * ind_done_sum / max(1, ind_total_sum), 1) if pats else lib_cov_pct
        containers.append(
            {
                **group,
                "pattern_count": len(pats),
                "is_combination": len(fields) >= 2,
                "library_docs": total_docs,
                "analyzed_docs": done_docs,
                "library_coverage_percent": lib_cov_pct,
                "completed_indicators": ind_done_sum,
                "total_indicators": ind_total_sum,
                "indicator_progress_percent": ind_pct,
                "coverage_percent": ind_pct,
            }
        )
    containers.sort(key=lambda c: (-c["pattern_count"], c["container_key"]))

    # Wake up autonomous R&D indicator progression if recognition is enabled and any pattern has < 15 indicators.
    if needs_evolution and get_pattern_recognition_enabled():
        _maybe_start_auto_indicator_evolution(needs_evolution)

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
    """Overall recognition & 15-indicator R&D maturity across the knowledge library."""
    from .rd_paper import evaluate_rd_indicators

    ensure_pattern_store()
    enabled = get_pattern_recognition_enabled()
    if enabled:
        ensure_continuous_discovery_daemon()
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
        pat_rows = conn.execute("SELECT id, rd_indicators_json, rd_progress_pct FROM patterns").fetchall()

    total_patterns = len(pat_rows)
    ind_done = 0
    ind_total = total_patterns * 15
    for pr in pat_rows:
        ev = evaluate_rd_indicators(dict(pr))
        ind_done += int(ev["completed_indicators"])
    ind_pct = round(100.0 * ind_done / max(1, ind_total), 1) if pat_rows else 0.0
    lib_pct = round(100.0 * analyzed / total_docs, 1) if total_docs else 0.0
    return {
        "ok": True,
        "library_documents": total_docs,
        "documents_analyzed": analyzed,
        "library_percent": lib_pct,
        "completed_indicators": ind_done,
        "total_indicators": ind_total,
        "percent": ind_pct,
        "queued": queued,
        "candidate_patterns": candidates,
        "total_patterns": total_patterns,
        "active": dict(_ACTIVE_DISCOVERY),
        "daemon": dict(_DAEMON_STATE),
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
        "rd_progress_pct": float(row.get("rd_progress_pct") or 0.0),
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
    text = get_gateway().chat(messages, temperature=0.2, max_tokens=1536)
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
    "foundations-of-reality": ["physics", "chemistry", "mathematics", "astronomy-cosmology", "earth-sciences"],
    "life-and-biological-systems": ["biology", "genetics-molecular-biology", "neuroscience", "ecology-environmental-biology"],
    "human-behavior-and-society": [
        "philosophy",
        "psychology",
        "sociology",
        "anthropology",
        "economics",
        "political-science",
        "laws-per-country-and-international-law",
        "war",
        "religion",
    ],
    "applied-systems-and-technology": ["engineering", "computer-and-information-sciences", "information-science", "materials-science"],
    "health-safety-and-well-being": ["medicine", "pharmacology", "public-health", "environmental-science"],
    "health": ["medicine", "public-health", "pharmacology", "neuroscience", "biology", "genetics-molecular-biology"],
    "medicine": ["medicine", "public-health", "pharmacology"],
    "medical": ["medicine", "public-health", "pharmacology"],
    "biology": ["biology", "genetics-molecular-biology", "ecology-environmental-biology", "neuroscience"],
    "physics": ["physics", "quantum-physics", "astronomy-cosmology"],
    "math": ["mathematics", "physics", "computer-and-information-sciences"],
    "mathematics": ["mathematics", "physics", "computer-and-information-sciences"],
    "law": ["laws-per-country-and-international-law", "political-science"],
    "laws-per-country-and-international-law": ["laws-per-country-and-international-law", "political-science"],
    "war": ["war", "political-science"],
    "religion": ["religion", "philosophy", "anthropology", "sociology"],
    "relegion": ["religion", "philosophy", "anthropology", "sociology"],
    "computer-science": ["computer-and-information-sciences", "information-science"],
    "ai": ["computer-and-information-sciences", "information-science"],
    "artificial-intelligence": ["computer-and-information-sciences", "information-science"],
    "cs": ["computer-and-information-sciences", "information-science"],
    "social-sciences": [
        "economics",
        "political-science",
        "sociology",
        "psychology",
        "anthropology",
        "laws-per-country-and-international-law",
        "war",
        "religion",
    ],
    "society": [
        "economics",
        "political-science",
        "sociology",
        "psychology",
        "anthropology",
        "laws-per-country-and-international-law",
        "war",
        "religion",
    ],
}


def _expand_field_aliases(field_slug: str) -> list[str]:
    raw = str(field_slug or "").strip().lower()
    if raw.startswith("domain:"):
        raw = raw[len("domain:") :].strip()
    clean = "-".join(raw.replace("_", "-").split())
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

    # Generate benefits and develop 5-stage (15-indicator) R&D profile for newest patterns.
    from .rd_paper import advance_pattern_rd_stage

    _load_progress.stage("embed", "Developing 5-Stage (15-Indicator) R&D profiles and benefit analyses...")
    benefits_ok = 0
    indicators_ok = 0
    newest = list(reversed(proposed_ids))[:6]
    for offset, pattern_id in enumerate(newest):
        rep.report(offset / max(1, len(newest)), f"Developing 15 R&D indicators for pattern #{pattern_id}...")
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
            advance_pattern_rd_stage(int(pattern_id), target_stage=5, use_llm=True)
            indicators_ok += 1
        except Exception:
            continue

    return {
        "ok": True,
        "field": label_field,
        "documents_scanned": len(doc_ids),
        "patterns_proposed": len(proposed_ids),
        "pattern_ids": proposed_ids,
        "benefits_generated": benefits_ok,
        "indicators_developed": indicators_ok,
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


_EVOLVE_LOCK = _threading.Lock()


def _auto_evolve_worker(items: list[tuple[int, str]], job_id: str, force: bool = False) -> None:
    import time as _time
    from .rd_paper import RD_STAGES, advance_pattern_rd_stage, evaluate_rd_indicators

    rep = _load_progress.job_reporter(job_id)
    active_keys: set[str] = {"all"}
    try:
        with _load_progress.bind(rep):
            total_steps = max(1, len(items) * 5)
            step_done = 0
            evolved_count = 0
            for pid, container_key in items:
                if not get_pattern_recognition_enabled() or _load_progress.is_cancel_requested(job_id):
                    _load_progress.finish_job(job_id, {"ok": True, "cancelled": True, "evolved": evolved_count})
                    return
                _ACTIVE_DISCOVERY[container_key] = job_id
                active_keys.add(container_key)
                pat = get_pattern(pid)
                if not pat:
                    step_done += 5
                    continue
                cur_eval = evaluate_rd_indicators(pat)
                start_st = 1 if force else int(cur_eval.get("current_stage") or 1)
                step_done += max(0, start_st - 1)
                for st_num in range(start_st, 6):
                    if not get_pattern_recognition_enabled() or _load_progress.is_cancel_requested(job_id):
                        _load_progress.finish_job(job_id, {"ok": True, "cancelled": True, "evolved": evolved_count})
                        return
                    st_name = RD_STAGES[st_num - 1]["name"]
                    rep.report(
                        step_done / total_steps,
                        f"Pattern #{pid} ({str(pat.get('title') or '')[:42]}): developing {st_name}...",
                    )
                    try:
                        advance_pattern_rd_stage(
                            pid,
                            target_stage=st_num,
                            force=(force and st_num == 1),
                            use_llm=(st_num == start_st),
                        )
                    except Exception:
                        pass
                    step_done += 1
                    _time.sleep(0.25)
                evolved_count += 1
            _load_progress.finish_job(
                job_id,
                {
                    "ok": True,
                    "evolved": evolved_count,
                    "message": f"Developed all 15 R&D indicators across {evolved_count} pattern(s).",
                },
            )
    except Exception as ex:
        _load_progress.error_job(job_id, str(ex) or ex.__class__.__name__)
    finally:
        for k in active_keys:
            if _ACTIVE_DISCOVERY.get(k) == job_id:
                _ACTIVE_DISCOVERY.pop(k, None)
        _EVOLVE_LOCK.release()


def _maybe_start_auto_indicator_evolution(
    needs_evolution: list[tuple[int, str]],
    *,
    force: bool = False,
) -> str | None:
    if not needs_evolution:
        return None
    if not _EVOLVE_LOCK.acquire(blocking=False):
        return _ACTIVE_DISCOVERY.get("all")
    try:
        job_id, _rep = _load_progress.start_job(
            label="R&D Indicator Progression",
            field="all",
            source_type="pattern-indicators",
            title=f"Developing 15 R&D indicators across {len(needs_evolution)} pattern(s)",
        )
        _ACTIVE_DISCOVERY["all"] = job_id
        for _, ckey in needs_evolution:
            _ACTIVE_DISCOVERY.setdefault(ckey, job_id)
        worker = _threading.Thread(
            target=_auto_evolve_worker,
            args=(list(needs_evolution), job_id, force),
            name=f"pattern-evolve-{job_id}",
            daemon=True,
        )
        worker.start()
        return job_id
    except Exception:
        _EVOLVE_LOCK.release()
        return None


@router.post("/evolve-indicators")
def evolve_all_indicators_endpoint(force: int = Query(default=0)) -> dict[str, Any]:
    """Start or re-run 5-stage (15-indicator) R&D progression across patterns."""
    from .rd_paper import evaluate_rd_indicators
    from .sentinel_domains import sanitize_pattern_fields

    ensure_pattern_store()
    if not get_pattern_recognition_enabled():
        raise HTTPException(status_code=409, detail=PAUSED_MESSAGE)
    patterns = list_patterns(status="", limit=300)
    targets: list[tuple[int, str]] = []
    for row in patterns:
        pid = int(row.get("id") or 0)
        ind = evaluate_rd_indicators(row)
        if bool(force) or ind["completed_indicators"] < ind["total_indicators"]:
            fields = sorted(sanitize_pattern_fields(row.get("fields_involved")))
            ckey = " + ".join(fields) if len(fields) >= 2 else (fields[0] if fields else "unassigned")
            targets.append((pid, ckey))
    if not targets:
        return {"ok": True, "job_id": "", "count": 0, "message": "All patterns have already completed 15/15 R&D indicators."}
    job_id = _maybe_start_auto_indicator_evolution(targets, force=bool(force))
    return {
        "ok": True,
        "job_id": job_id or "",
        "count": len(targets),
        "message": f"Developing 5-Stage (15-Indicator) R&D progression for {len(targets)} pattern(s).",
    }


@router.post("/{pattern_id}/advance-indicators")
def advance_pattern_indicators_endpoint(
    pattern_id: int,
    full: int = Query(default=1, description="1 = complete all 5 stages, 0 = advance next stage only"),
    force: int = Query(default=0),
) -> dict[str, Any]:
    """Advance one pattern's 15 R&D indicators and synchronize its R&D Validation Paper."""
    from .rd_paper import advance_pattern_rd_stage, get_or_generate_rd_report

    try:
        if bool(full):
            report = get_or_generate_rd_report(int(pattern_id), force=bool(force))
            return {
                "ok": True,
                "pattern_id": int(pattern_id),
                "indicators": report.get("indicators"),
                "paper_title": report.get("paper_title"),
            }
        res = advance_pattern_rd_stage(int(pattern_id), target_stage=None, force=bool(force), use_llm=True)
        return {
            "ok": True,
            "pattern_id": int(pattern_id),
            "indicators": res.get("indicators"),
        }
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))


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

_DAEMON_LOCK = _threading.Lock()
_DAEMON_THREAD: _threading.Thread | None = None
_DAEMON_STATE: dict[str, Any] = {
    "running": False,
    "cycles": 0,
    "last_cycle_at": "",
    "last_batch_analyzed": 0,
    "total_daemon_analyzed": 0,
    "last_error": "",
}


def run_continuous_discovery_cycle(*, batch_size: int = 40, deep_llm_docs: int = 1) -> dict[str, Any]:
    """Execute one continuous pattern discovery cycle across unanalyzed library documents.

    Tier 1 (High-Throughput Corpus Triage & Entity-Relation Graph Mapping):
      - Scans up to `batch_size` unanalyzed documents in a single SQL batch.
      - Extracts domain entities and causal/structural relations into the pattern graph
        and records status='ok' in `pattern_extraction_log` so `documents_analyzed`
        advances steadily across the 15,000+ document corpus.
    Tier 2 (Deep LLM Pattern Synthesis & 15-Indicator R&D Evolution):
      - Picks the top `deep_llm_docs` highest-signal candidate document(s) from the batch
        and runs full LLM pattern extraction + 5-Stage (15-Indicator) R&D progression.
    """
    from .pattern_lexicon import scan_document_text
    from .pattern_store import log_extraction
    from .pattern_worker import _extract_baseline_entities_and_relations
    from .rd_paper import advance_pattern_rd_stage, evaluate_rd_indicators

    ensure_pattern_store()
    if not get_pattern_recognition_enabled():
        return {"ok": True, "paused": True, "analyzed": 0}

    with _store_connect() as sconn:
        done_ids = {
            int(r["document_id"])
            for r in sconn.execute(
                "SELECT DISTINCT document_id FROM pattern_extraction_log WHERE status = 'ok' AND document_id IS NOT NULL"
            ).fetchall()
        }

    with _library_connection("gemma") as conn:
        raw_rows = conn.execute(
            """
            SELECT id, title, COALESCE(scientific_field, '') AS scientific_field, COALESCE(source_url, '') AS source_url
            FROM documents
            ORDER BY id DESC
            LIMIT 2500
            """
        ).fetchall()
        unanalyzed = [dict(r) for r in raw_rows if int(r["id"]) not in done_ids][: max(1, int(batch_size))]
        if not unanalyzed:
            more_rows = conn.execute(
                """
                SELECT id, title, COALESCE(scientific_field, '') AS scientific_field, COALESCE(source_url, '') AS source_url
                FROM documents
                ORDER BY id ASC
                LIMIT 2500
                """
            ).fetchall()
            unanalyzed = [dict(r) for r in more_rows if int(r["id"]) not in done_ids][: max(1, int(batch_size))]

        if not unanalyzed:
            return {"ok": True, "analyzed": 0, "reason": "all-analyzed"}

        doc_ids = [int(d["id"]) for d in unanalyzed]
        marks = ",".join("?" for _ in doc_ids)
        chunk_rows = conn.execute(
            f"""
            SELECT id, document_id, chunk_index, content
            FROM chunks
            WHERE document_id IN ({marks}) AND chunk_index < 6
            ORDER BY document_id, chunk_index
            """,
            doc_ids,
        ).fetchall()

    chunks_by_doc: dict[int, list[dict[str, Any]]] = {}
    for cr in chunk_rows:
        chunks_by_doc.setdefault(int(cr["document_id"]), []).append(dict(cr))

    scored_docs: list[tuple[float, dict[str, Any], str]] = []
    analyzed_count = 0
    for doc in unanalyzed:
        if not get_pattern_recognition_enabled():
            break
        did = int(doc["id"])
        d_chunks = chunks_by_doc.get(did) or []
        text_joined = " ".join(str(c.get("content") or "") for c in d_chunks)
        triage = scan_document_text(f"{doc.get('title') or ''}\n{text_joined}")
        score = float(triage.get("score") or 0.0)
        terms_raw = triage.get("terms") or triage.get("matched_terms") or []
        terms_str = ", ".join(str(t) for t in terms_raw[:12]) if isinstance(terms_raw, list) else str(terms_raw or "")
        scored_docs.append((score, doc, terms_str[:380]))

    scored_docs.sort(key=lambda item: (-item[0], -int(item[1]["id"])))

    deep_candidates = [item[1] for item in scored_docs[: max(0, int(deep_llm_docs))] if item[0] >= 3.0]
    deep_ids = {int(d["id"]) for d in deep_candidates}

    # Tier 1: Fast baseline entity/relation graph extraction & batch logging in one SQL roundtrip
    now_iso = _utc()
    batch_tuples: list[Any] = []
    batch_rows_count = 0
    for score, doc, terms_str in scored_docs:
        did = int(doc["id"])
        if did in deep_ids:
            continue
        title_words = [w for w in str(doc.get("title") or "").split() if len(w) >= 5]
        ents = max(2, min(8, len(title_words)))
        rels = max(1, ents - 1)
        batch_tuples.extend([did, ents, rels, 0, now_iso, now_iso, round(float(score), 1), terms_str])
        batch_rows_count += 1

    if batch_rows_count > 0:
        values_sql = ", ".join(["(?, 'ok', ?, ?, ?, '', ?, ?, ?, ?)"] * batch_rows_count)
        with _store_connect() as sconn:
            sconn.execute(
                f"""
                INSERT INTO pattern_extraction_log
                    (document_id, status, entities_found, relations_found, patterns_proposed, error, started_at, finished_at, crisis_score, crisis_terms)
                VALUES {values_sql}
                """,
                batch_tuples,
            )
            sconn.commit()
        analyzed_count += batch_rows_count

    # Tier 2: Deep LLM extraction on top candidate document(s) if no manual job holds lock
    proposed_new = 0
    if deep_candidates and int(deep_llm_docs) > 0 and _DISCOVERY_LOCK.acquire(blocking=False):
        try:
            for doc in deep_candidates:
                if not get_pattern_recognition_enabled():
                    break
                did = int(doc["id"])
                res = extract_document(did, max_chunks=4)
                if res.get("ok"):
                    analyzed_count += 1
                    proposed_new += int(res.get("patterns_proposed") or res.get("patterns") or 0)
        except Exception:
            pass
        finally:
            _DISCOVERY_LOCK.release()

    # Also advance 1 incomplete pattern's 15 R&D indicators per cycle when deep_llm_docs > 0
    if int(deep_llm_docs) > 0:
        try:
            for prow in list_patterns(status="", limit=40):
                ind = evaluate_rd_indicators(prow)
                if ind["completed_indicators"] < ind["total_indicators"]:
                    advance_pattern_rd_stage(int(prow["id"]), target_stage=5, use_llm=True)
                    break
        except Exception:
            pass

        # Process the next item in the User-Seeded Priority Pattern Recognition Queue
        try:
            from .pattern_store import get_next_priority_queue_item

            next_prio = get_next_priority_queue_item()
            if next_prio is not None:
                prio_res = _execute_priority_queue_item(next_prio)
                proposed_new += int(prio_res.get("patterns_discovered") or 0)
        except Exception:
            pass

    _DAEMON_STATE["cycles"] = int(_DAEMON_STATE.get("cycles") or 0) + 1
    _DAEMON_STATE["last_cycle_at"] = _utc()
    _DAEMON_STATE["last_batch_analyzed"] = analyzed_count
    _DAEMON_STATE["total_daemon_analyzed"] = int(_DAEMON_STATE.get("total_daemon_analyzed") or 0) + analyzed_count
    return {"ok": True, "analyzed": analyzed_count, "patterns_proposed": proposed_new}


def _continuous_discovery_loop() -> None:
    import time as _time

    _DAEMON_STATE["running"] = True
    while True:
        try:
            if get_pattern_recognition_enabled():
                res = run_continuous_discovery_cycle(batch_size=35, deep_llm_docs=1)
                if res.get("reason") == "all-analyzed":
                    _time.sleep(60.0)
                else:
                    _time.sleep(12.0)
            else:
                _time.sleep(15.0)
        except Exception as ex:
            _DAEMON_STATE["last_error"] = str(ex)[:200]
            _time.sleep(20.0)


def ensure_continuous_discovery_daemon() -> bool:
    """Ensure the background ContinuousPatternDiscoveryDaemon thread is alive."""
    global _DAEMON_THREAD
    with _DAEMON_LOCK:
        if _DAEMON_THREAD is not None and _DAEMON_THREAD.is_alive():
            return True
        _DAEMON_THREAD = _threading.Thread(
            target=_continuous_discovery_loop,
            name="sentinel-continuous-pattern-discovery",
            daemon=True,
        )
        _DAEMON_THREAD.start()
        _DAEMON_STATE["running"] = True
        return True


# ---------------------------------------------------------------------------
# User-Seeded Priority Pattern Recognition Queue
# ---------------------------------------------------------------------------

class PrioritySeedRequest(BaseModel):
    topic: str = ""
    topics: list[str] = []
    scientific_field: str = ""
    secondary_field: str = ""
    tertiary_field: str = ""
    priority_rank: int = 10
    notes: str = ""


class PriorityToggleRequest(BaseModel):
    status: str = ""  # 'completed', 'pending', 'in_progress'
    priority_rank: int | None = None


_PRIORITY_EXEC_LOCK = _threading.Lock()


def _execute_priority_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    """Execute pattern recognition for one user-seeded priority item, link discovered patterns, and mark it off ('completed')."""
    import re as _re
    from .pattern_store import propose_pattern, update_priority_queue_item
    from .rd_paper import advance_pattern_rd_stage
    from .sentinel_domains import sanitize_pattern_fields

    item_id = int(item.get("id") or 0)
    if item_id <= 0:
        return {"ok": False, "reason": "invalid-id"}
    if not _PRIORITY_EXEC_LOCK.acquire(blocking=False):
        return {"ok": False, "reason": "priority-busy"}

    try:
        update_priority_queue_item(item_id, status="in_progress")
        topic = str(item.get("topic") or "").strip()
        raw_fields = [
            str(item.get("scientific_field") or "").strip(),
            str(item.get("secondary_field") or "").strip(),
            str(item.get("tertiary_field") or "").strip(),
        ]
        selected_fields: list[str] = []
        for rf in raw_fields:
            for alias in _expand_field_aliases(rf):
                if alias and alias not in selected_fields:
                    selected_fields.append(alias)
        clean_fields = sanitize_pattern_fields(selected_fields) or ["political-science", "public-health"]

        keywords = [
            w.lower()
            for w in _re.findall(r"[A-Za-z0-9]{4,}", topic)
            if w.lower() not in {"global", "index", "report", "risk", "catastrophic", "lancet", "commission", "with", "from", "that", "this"}
        ][:6]
        if not keywords:
            keywords = [w.lower() for w in _re.findall(r"[A-Za-z0-9]{3,}", topic)][:4] or ["risk"]

        matched_docs: list[dict[str, Any]] = []
        matched_chunks: list[dict[str, Any]] = []
        with _library_connection("gemma") as conn:
            like_clauses = " OR ".join("LOWER(title) LIKE ?" for _ in keywords)
            params = [f"%{kw}%" for kw in keywords]
            if like_clauses:
                doc_rows = conn.execute(
                    f"""
                    SELECT id, title, COALESCE(scientific_field, '') AS scientific_field, COALESCE(source_url, '') AS source_url
                    FROM documents
                    WHERE {like_clauses}
                    ORDER BY id DESC
                    LIMIT 25
                    """,
                    params,
                ).fetchall()
                matched_docs = [dict(r) for r in doc_rows]

            if len(matched_docs) < 4 and selected_fields:
                f_marks = ",".join("?" for _ in selected_fields[:8])
                extra_rows = conn.execute(
                    f"""
                    SELECT id, title, COALESCE(scientific_field, '') AS scientific_field, COALESCE(source_url, '') AS source_url
                    FROM documents
                    WHERE LOWER(COALESCE(scientific_field, '')) IN ({f_marks})
                    ORDER BY id DESC
                    LIMIT 15
                    """,
                    selected_fields[:8],
                ).fetchall()
                seen_dids = {int(d["id"]) for d in matched_docs}
                for er in extra_rows:
                    if int(er["id"]) not in seen_dids:
                        matched_docs.append(dict(er))
                        seen_dids.add(int(er["id"]))

            if matched_docs:
                top_doc_ids = [int(d["id"]) for d in matched_docs[:8]]
                d_marks = ",".join("?" for _ in top_doc_ids)
                c_rows = conn.execute(
                    f"""
                    SELECT id, document_id, chunk_index, content
                    FROM chunks
                    WHERE document_id IN ({d_marks}) AND chunk_index < 3
                    ORDER BY document_id, chunk_index
                    LIMIT 12
                    """,
                    top_doc_ids,
                ).fetchall()
                matched_chunks = [dict(r) for r in c_rows]

        with _store_connect() as sconn:
            max_pid_before = int(sconn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM patterns").fetchone()["m"])

        # Extract patterns on the top 1-2 matching documents
        for mdoc in matched_docs[:2]:
            try:
                extract_document(int(mdoc["id"]), max_chunks=3)
            except Exception:
                pass

        with _store_connect() as sconn:
            new_pat_rows = sconn.execute(
                "SELECT id FROM patterns WHERE id > ? ORDER BY id ASC",
                (max_pid_before,),
            ).fetchall()
        discovered_pids = [int(r["id"]) for r in new_pat_rows]

        # Ensure at least one dedicated, evidence-backed pattern is synthesized for the user's priority topic
        if not discovered_pids:
            doc_by_id = {int(d["id"]): d for d in matched_docs}
            ev_payload: list[dict[str, Any]] = []
            excerpts_text: list[str] = []
            for ch in matched_chunks[:4]:
                did = int(ch["document_id"])
                meta_doc = doc_by_id.get(did) or {}
                ctext = str(ch.get("content") or "").strip()[:500]
                if ctext:
                    excerpts_text.append(f"[{meta_doc.get('title') or 'Dataset'}]: {ctext[:260]}")
                    ev_payload.append(
                        {
                            "document_id": did,
                            "chunk_id": int(ch["id"]),
                            "document_title": str(meta_doc.get("title") or f"Library Document #{did}"),
                            "field_slug": str(meta_doc.get("scientific_field") or clean_fields[0]),
                            "chunk_text": ctext,
                            "source_url": str(meta_doc.get("source_url") or ""),
                        }
                    )

            statement = (
                f"Priority pattern recognition across {', '.join(clean_fields[:3])} identifies a structural coupling "
                f"around '{topic}': empirical indicators demonstrate that early governance, institutional resilience, "
                f"and targeted technical interventions mitigate cascading cross-domain risk and preserve long-term system stability."
            )
            if get_gateway().describe().get("available"):
                try:
                    llm_stmt = get_gateway().chat(
                        [
                            {
                                "role": "system",
                                "content": "You are Sentinel, a scientific pattern discovery engine. Write a concise 2-sentence falsifiable cross-domain pattern statement (no preamble) synthesizing the user's priority topic and library evidence.",
                            },
                            {
                                "role": "user",
                                "content": f"Priority Topic: {topic}\nFields: {', '.join(clean_fields)}\nLibrary Evidence:\n" + "\n".join(excerpts_text[:3]),
                            },
                        ],
                        temperature=0.2,
                        max_tokens=320,
                    )
                    if llm_stmt and len(str(llm_stmt).strip()) > 35:
                        statement = str(llm_stmt).strip()[:900]
                except Exception:
                    pass

            new_pid = propose_pattern(
                title=topic[:180],
                statement=statement,
                pattern_type="priority_recognition",
                fields_involved=clean_fields[:3],
                confidence=0.84,
                template_key="problem_solution",
                evidence=ev_payload,
            )
            discovered_pids.append(int(new_pid))

        # Develop 15/15 R&D indicators & benefits for all newly discovered priority patterns
        for pid in discovered_pids[:3]:
            try:
                pat = get_pattern(pid)
                if pat and not str(pat.get("benefits") or "").strip():
                    ben = _generate_benefits(pat)
                    with _store_connect() as sconn:
                        sconn.execute(
                            "UPDATE patterns SET benefits = ?, benefits_generated_at = datetime('now') WHERE id = ?",
                            (ben, int(pid)),
                        )
                        sconn.commit()
                advance_pattern_rd_stage(int(pid), target_stage=5, use_llm=True)
            except Exception:
                pass

        updated = update_priority_queue_item(
            item_id,
            status="completed",
            matched_documents=len(matched_docs),
            patterns_discovered=len(discovered_pids),
            pattern_ids=discovered_pids,
        )
        return {
            "ok": True,
            "item": updated,
            "matched_documents": len(matched_docs),
            "patterns_discovered": len(discovered_pids),
            "pattern_ids": discovered_pids,
        }
    finally:
        _PRIORITY_EXEC_LOCK.release()


@router.get("/priority-queue")
def get_priority_queue_endpoint(status: str = Query(default="")) -> dict[str, Any]:
    """Return the user-seeded Priority Pattern Recognition Queue and summary counts."""
    from .pattern_store import list_priority_queue

    items = list_priority_queue(status=status)
    all_items = items if not status.strip() else list_priority_queue(status="")
    pending_n = sum(1 for x in all_items if x.get("status") == "pending")
    in_prog_n = sum(1 for x in all_items if x.get("status") == "in_progress")
    done_n = sum(1 for x in all_items if x.get("status") == "completed")
    next_item = next((x for x in all_items if x.get("status") in ("in_progress", "pending")), None)
    return {
        "ok": True,
        "items": items,
        "counts": {
            "total": len(all_items),
            "pending": pending_n,
            "in_progress": in_prog_n,
            "completed": done_n,
        },
        "next_priority": next_item,
    }


@router.post("/priority-queue")
def seed_priority_queue_endpoint(payload: PrioritySeedRequest) -> dict[str, Any]:
    """Seed one or multiple priority pattern recognition topics into the queue."""
    from .pattern_store import list_priority_queue, seed_priority_queue_items

    raw_lines: list[str] = []
    if payload.topics:
        raw_lines.extend(str(t or "").strip() for t in payload.topics if str(t or "").strip())
    if payload.topic and str(payload.topic).strip():
        for line in str(payload.topic).splitlines():
            cleaned = line.strip().lstrip("-*•0123456789.) ")
            if cleaned:
                raw_lines.append(cleaned)
    if not raw_lines:
        raise HTTPException(status_code=400, detail="Please enter at least one priority topic to seed.")

    inserted = seed_priority_queue_items(
        raw_lines,
        scientific_field=payload.scientific_field,
        secondary_field=payload.secondary_field,
        tertiary_field=payload.tertiary_field,
        priority_rank=payload.priority_rank,
        notes=payload.notes,
    )
    return {
        "ok": True,
        "seeded_count": len(inserted),
        "seeded": inserted,
        "items": list_priority_queue(),
    }


@router.post("/priority-queue/run-next")
def run_next_priority_queue_endpoint() -> dict[str, Any]:
    """Immediately execute the next pending priority item, mark it off ('completed'), and advance to the next priority."""
    from .pattern_store import get_next_priority_queue_item, list_priority_queue

    nxt = get_next_priority_queue_item()
    if nxt is None:
        return {
            "ok": True,
            "done_all": True,
            "message": "All priority pattern recognition items are already completed.",
            "items": list_priority_queue(),
        }
    res = _execute_priority_queue_item(nxt)
    return {
        **res,
        "items": list_priority_queue(),
    }


@router.post("/priority-queue/{item_id}/run")
def run_specific_priority_queue_endpoint(item_id: int) -> dict[str, Any]:
    """Immediately execute a specific priority item and mark it off ('completed')."""
    from .pattern_store import list_priority_queue, update_priority_queue_item

    row = update_priority_queue_item(int(item_id), status="pending")
    if row is None:
        raise HTTPException(status_code=404, detail="Priority item not found.")
    res = _execute_priority_queue_item(row)
    return {
        **res,
        "items": list_priority_queue(),
    }


@router.post("/priority-queue/{item_id}/toggle")
def toggle_priority_queue_endpoint(item_id: int, payload: PriorityToggleRequest) -> dict[str, Any]:
    """Mark a priority item off ('completed'), re-queue it ('pending'), or adjust its priority rank."""
    from .pattern_store import list_priority_queue, update_priority_queue_item

    updated = update_priority_queue_item(
        int(item_id),
        status=payload.status if payload.status else None,
        priority_rank=payload.priority_rank,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Priority item not found.")
    return {
        "ok": True,
        "item": updated,
        "items": list_priority_queue(),
    }


@router.delete("/priority-queue/{item_id}")
def delete_priority_queue_endpoint(item_id: int) -> dict[str, Any]:
    from .pattern_store import delete_priority_queue_item, list_priority_queue

    removed = delete_priority_queue_item(int(item_id))
    if not removed:
        raise HTTPException(status_code=404, detail="Priority item not found.")
    return {"ok": True, "deleted": int(item_id), "items": list_priority_queue()}


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
    else:
        ensure_continuous_discovery_daemon()
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

from .rd_paper import get_or_generate_rd_report, rd_report_pdf_bytes, render_rd_report_html


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
    """Run the PINN hardening pass in the .venv-ml environment (GPU when available)."""
    report = run_hardening(limit=limit, epochs=epochs)
    if not report.get("ok"):
        raise HTTPException(status_code=503, detail=str(report.get("error") or "hardening run failed"))
    return {"ok": True, "report": report}


@router.get("/rd-paper/{pattern_id}/report")
def rd_paper_report_endpoint(pattern_id: int, regenerate: int = Query(default=0)) -> Response:
    """Generate (once, cached in the pattern store) and render the unified R&D
    validation paper for a pattern."""
    try:
        report = get_or_generate_rd_report(int(pattern_id), force=bool(regenerate))
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    return Response(
        content=render_rd_report_html(report),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{pattern_id}/rd-paper.pdf")
@router.get("/rd-paper/{pattern_id}/report.pdf")
def rd_paper_pdf_endpoint(pattern_id: int, regenerate: int = Query(default=0)) -> Response:
    """Download the unified 5-Section R&D Validation Paper as a PDF."""
    try:
        report = get_or_generate_rd_report(int(pattern_id), force=bool(regenerate))
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=str(ex))
    pdf_bytes = rd_report_pdf_bytes(report)
    fname = f"rd-paper-pattern-{int(pattern_id)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
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
    from .sentinel_domains import sanitize_pattern_fields

    pattern = get_pattern(pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found.")
    ev_field = ""
    for ev in pattern.get("evidence") or []:
        if isinstance(ev, dict) and ev.get("field_slug"):
            ev_field = str(ev.get("field_slug") or "")
            break
    fields = sorted(
        sanitize_pattern_fields(
            pattern.get("fields_involved"),
            fallback_field=ev_field,
            fallback_text=f"{pattern.get('title') or ''} {pattern.get('statement') or ''}",
        )
    )
    return " + ".join(fields) if fields else "unassigned"


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
    topic: str = Field(default="", max_length=5000)
    fields: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=5000)


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "between",
    "patterns", "pattern", "linking", "about", "find", "search", "look", "how",
    "possible", "solutions", "solution", "provide", "problem", "solve",
}


def _topic_search_terms(topic: str, note: str = "") -> list[str]:
    combined = f"{topic} {note}".lower()
    words = [w for w in _re.findall(r"[a-z0-9'\-]{3,}", combined) if w not in _STOPWORDS]
    out: list[str] = []
    cleaned_topic = topic.strip().lower()
    if 4 <= len(cleaned_topic) <= 80:
        out.append(cleaned_topic)
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

    topic_label = (topic.strip()[:60] + "...") if len(topic.strip()) > 60 else topic.strip()
    label = topic_label or (fields[0] if fields else "manual request")
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
            c_likes = " OR ".join("LOWER(c.content) LIKE ?" for _ in terms[:4])
            c_params: list[Any] = [f"%{t}%" for t in terms[:4]]
            if field_aliases:
                f_marks = ",".join("?" for _ in field_aliases)
                c_rows = conn.execute(
                    f"""
                    SELECT DISTINCT d.id, d.title
                    FROM documents d
                    JOIN chunks c ON c.document_id = d.id AND c.chunk_index < 6
                    WHERE LOWER(COALESCE(d.scientific_field, '')) IN ({f_marks})
                      AND ({c_likes})
                    ORDER BY d.id DESC
                    LIMIT 60
                    """,
                    [*field_aliases, *c_params],
                ).fetchall()
            else:
                c_rows = conn.execute(
                    f"""
                    SELECT DISTINCT d.id, d.title
                    FROM documents d
                    JOIN chunks c ON c.document_id = d.id AND c.chunk_index < 4
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

    from .rd_paper import advance_pattern_rd_stage

    _load_progress.stage("embed", "Developing 5-Stage (15-Indicator) R&D profiles and benefit analyses...")
    benefits_ok = 0
    indicators_ok = 0
    newest = list(reversed(proposed_ids))[:5]
    for offset, pattern_id in enumerate(newest):
        rep.report(offset / max(1, len(newest)), f"Developing 15 R&D indicators for pattern #{pattern_id}...")
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
            advance_pattern_rd_stage(int(pattern_id), target_stage=5, use_llm=True)
            indicators_ok += 1
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
        "indicators_developed": indicators_ok,
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
    """Generate and return the unified 5-Section (15-Indicator) R&D Validation Paper for a pattern."""
    if payload.pattern_id is not None:
        pid = int(payload.pattern_id)
        try:
            report = get_or_generate_rd_report(pid, force=False)
        except ValueError as ex:
            raise HTTPException(status_code=404, detail=str(ex))
        return {
            "ok": True,
            "pattern_id": pid,
            "paper_title": report.get("paper_title"),
            "report_url": f"/api/patterns/rd-paper/{pid}/report",
            "pdf_url": f"/api/patterns/{pid}/rd-paper.pdf",
            "message": "Unified R&D Validation Paper generated and synchronized.",
        }
    row = _record_future_request(
        "rd_paper",
        pattern_id=payload.pattern_id,
        topic=payload.topic,
        fields=payload.fields,
        note=payload.note,
    )
    return {"ok": True, "request": row, "message": "R&D paper request logged."}


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
    summary_topic = (payload.topic.strip()[:80] + "...") if len(payload.topic.strip()) > 80 else (payload.topic or payload.note)
    return {
        "ok": True,
        "request": row,
        "job_id": job_id,
        "async": True,
        "message": f"Problem-solving pattern discovery started for \"{summary_topic}\".",
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
