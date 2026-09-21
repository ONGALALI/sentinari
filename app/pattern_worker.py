"""Sentinel Pattern Worker — extraction + synthesis pipeline.

Flow (mirrors the SENTINEL-v2 blueprint):

1. QUEUE       — every ingested document is queued (after-ingest hook or the
                 review panel's "Analyze for patterns" action).
2. EXTRACT     — the worker pulls the document's chunks from the knowledge
                 library and asks the LLM gateway for structured output:
                 entities, typed relations, and candidate patterns.
3. STORE       — entities/relations go into the pattern store; candidate
                 patterns land in the Approve/Reject/Test queue with evidence
                 (document + chunk provenance, per Constitution Article V).
4. SYNTHESIZE  — a cross-domain pass looks for entity pairs connected across
                 different scientific fields (the "superposition" middle zone)
                 and proposes bridge patterns for review.

Nothing here mutates knowledge automatically: everything lands as a
'candidate' until a human Approves it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .db import library_connection
from .llm_gateway import LLMGatewayError, get_gateway
from .pattern_store import (
    ensure_pattern_store,
    log_extraction,
    propose_pattern,
    register_template,
    upsert_entity,
    upsert_relation,
)

# Caps keep a runaway document from burning the whole API budget.
MAX_CHUNKS_PER_DOCUMENT = 24
MAX_CHARS_PER_CHUNK = 4000
MAX_ENTITIES_PER_BATCH = 40

EXTRACTION_SYSTEM_PROMPT = """You are Sentinel's pattern-extraction engine. You read scientific text and \
return STRICT JSON only — no prose, no markdown fences. You never invent facts \
that are not in the text; if the text contains little of value, return empty lists. \
Your purpose is discovering problems, solutions, cures, and cross-domain patterns \
for the benefit of society (society includes artificial intelligence)."""

EXTRACTION_USER_TEMPLATE = """Read the following scientific text (document: "{title}", field: {field}).

Extract:
1. "entities": things the text is about. Each has "name", "type", "description".
   Use type from: disease, treatment, drug, gene, protein, symptom, cause, effect,
   problem, solution, concept, method, technology, organization, material, other.
2. "relations": pairs of the above entities. Each has "source", "target",
   "relation" (e.g. treated_by, causes, inhibits, prevents, correlates_with,
   addressed_by, bridged_with, part_of), "confidence" (0.0-1.0).
3. "patterns": notable insights the text supports. Each has "title",
   "statement" (1-3 sentences, self-contained), "pattern_type"
   (problem_solution | disease_treatment | cause_effect | cross_domain_bridge | general),
   "fields_involved" (list of scientific field names), "confidence" (0.0-1.0),
   "supporting_text" (the exact quote from the text that supports it).

TEXT:
{text}
"""


def queue_document(document_id: int) -> int:
    """Add a document to the extraction queue."""
    ensure_pattern_store()
    from .pattern_store import _connect

    with _connect() as conn:
        conn.execute(
            "INSERT INTO pattern_extraction_log (document_id, status, started_at) VALUES (?, 'queued', ?)",
            (int(document_id), _now()),
        )
        conn.commit()
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def queued_documents(limit: int = 10) -> list[dict[str, Any]]:
    ensure_pattern_store()
    from .pattern_store import _connect

    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pattern_extraction_log WHERE status = 'queued' ORDER BY id LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    return [dict(r) for r in rows]


def _document_chunks(document_id: int, limit: int = MAX_CHUNKS_PER_DOCUMENT) -> list[dict[str, Any]]:
    with library_connection("gemma") as conn:
        doc = conn.execute(
            "SELECT id, title, scientific_field, source_path, source_url FROM documents WHERE id = ?",
            (int(document_id),),
        ).fetchone()
        if doc is None:
            return []
        chunks = conn.execute(
            "SELECT id, chunk_index, content FROM chunks WHERE document_id = ? ORDER BY chunk_index LIMIT ?",
            (int(document_id), int(limit)),
        ).fetchall()
    return [
        {
            "document_id": int(doc["id"]),
            "title": str(doc["title"] or "Untitled"),
            "field": str(doc["scientific_field"] or ""),
            "source_url": str(doc["source_url"] or ""),
            "chunk_id": int(c["id"]),
            "chunk_index": int(c["chunk_index"]),
            "text": str(c["content"] or "")[:MAX_CHARS_PER_CHUNK],
        }
        for c in chunks
    ]


def extract_document(document_id: int, *, max_chunks: int = MAX_CHUNKS_PER_DOCUMENT) -> dict[str, Any]:
    """Run LLM extraction over a document's chunks and store the results."""
    ensure_pattern_store()
    gateway = get_gateway()
    started = _now()

    chunks = _document_chunks(document_id, max_chunks)
    if not chunks:
        log_id = log_extraction(document_id, "skipped", error="document not found in library", started_at=started)
        return {"ok": False, "reason": "document-not-found", "log_id": log_id}

    entities_found = 0
    relations_found = 0
    patterns_proposed = 0
    batch_errors: list[str] = []

    # Accumulate evidence + pattern proposals across chunks.
    entity_cache: dict[tuple[str, str], int] = {}

    def entity_id(name: str, etype: str) -> int | None:
        key = (str(etype or "other").lower(), str(name or "").strip().lower())
        if not key[1]:
            return None
        if key not in entity_cache:
            try:
                entity_cache[key] = upsert_entity(key[0], key[1])
            except Exception:
                return None
        return entity_cache[key]

    evidence_by_quote: dict[str, dict[str, Any]] = {}
    pattern_drafts: list[dict[str, Any]] = []

    for chunk in chunks:
        try:
            reply = gateway.chat_json(
                [
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": EXTRACTION_USER_TEMPLATE.format(
                            title=chunk["title"],
                            field=chunk["field"] or "unknown",
                            text=chunk["text"],
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=1400,
            )
        except LLMGatewayError as ex:
            batch_errors.append(str(ex)[:200])
            continue

        if not isinstance(reply, dict):
            batch_errors.append("model reply was not a JSON object")
            continue

        entities = reply.get("entities") or []
        relations = reply.get("relations") or []
        patterns = reply.get("patterns") or []

        name_to_type: dict[str, str] = {}
        for item in entities[:MAX_ENTITIES_PER_BATCH]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            etype = str(item.get("type") or "other").strip().lower()
            if name:
                name_to_type[name.lower()] = etype
                if entity_id(name, etype) is not None:
                    entities_found += 1

        for item in relations[:60]:
            if not isinstance(item, dict):
                continue
            src = str(item.get("source") or "").strip()
            tgt = str(item.get("target") or "").strip()
            rel = str(item.get("relation") or "related_to").strip()
            if not src or not tgt:
                continue
            src_id = entity_id(src, name_to_type.get(src.lower(), "other"))
            tgt_id = entity_id(tgt, name_to_type.get(tgt.lower(), "other"))
            if src_id and tgt_id and src_id != tgt_id:
                try:
                    upsert_relation(src_id, tgt_id, rel, float(item.get("confidence") or 0.5))
                    relations_found += 1
                except Exception:
                    continue

        for item in patterns[:6]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "Pattern").strip()
            statement = str(item.get("statement") or "").strip()
            if not statement:
                continue
            quote = str(item.get("supporting_text") or "").strip()[:1000]
            pattern_drafts.append(
                {
                    "title": title,
                    "statement": statement,
                    "pattern_type": str(item.get("pattern_type") or "general"),
                    "fields_involved": item.get("fields_involved") or [chunk["field"]] if chunk["field"] else [],
                    "confidence": float(item.get("confidence") or 0.5),
                    "template_key": str(item.get("pattern_type") or "general"),
                    "evidence": [
                        {
                            "document_id": chunk["document_id"],
                            "chunk_id": chunk["chunk_id"],
                            "document_title": chunk["title"],
                            "field_slug": chunk["field"],
                            "chunk_text": quote or chunk["text"][:600],
                            "source_url": chunk["source_url"],
                        }
                    ],
                }
            )

    # Store proposed patterns (deduped by title+statement prefix).
    seen_titles: set[str] = set()
    for draft in pattern_drafts:
        key = (draft["title"].lower(), draft["statement"].lower()[:120])
        if key in seen_titles:
            # Merge evidence into the earlier proposal instead of duplicating.
            continue
        seen_titles.add(key)
        try:
            if draft["template_key"] and draft["template_key"] != "general":
                register_template(
                    draft["template_key"],
                    draft["template_key"].replace("_", " ").title(),
                    source_entity_type="",
                    target_entity_type="",
                    relation_type="",
                )
            propose_pattern(
                draft["title"],
                draft["statement"],
                pattern_type=draft["pattern_type"],
                fields_involved=draft["fields_involved"],
                confidence=draft["confidence"],
                template_key=draft["template_key"],
                evidence=draft["evidence"],
            )
            patterns_proposed += 1
        except Exception as ex:
            batch_errors.append(str(ex)[:150])

    status = "ok" if (entities_found or relations_found or patterns_proposed) else ("error" if batch_errors else "empty")
    log_id = log_extraction(
        document_id,
        status,
        entities_found=entities_found,
        relations_found=relations_found,
        patterns_proposed=patterns_proposed,
        error="; ".join(batch_errors)[:900],
        started_at=started,
    )
    return {
        "ok": status in {"ok", "empty"},
        "status": status,
        "log_id": log_id,
        "chunks_processed": len(chunks),
        "entities_found": entities_found,
        "relations_found": relations_found,
        "patterns_proposed": patterns_proposed,
        "errors": batch_errors[:5],
    }


def process_queue(limit: int = 5) -> dict[str, Any]:
    """Process queued documents (used by the after-ingest hook and the UI)."""
    jobs = queued_documents(limit)
    results = []
    for job in jobs:
        result = extract_document(int(job["document_id"]))
        results.append({"queue_id": int(job["id"]), **result})
    return {"ok": True, "processed": len(results), "results": results}


# ---------------------------------------------------------------------------
# Cross-domain synthesis: the "superposition" middle zone
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """You are Sentinel's cross-domain synthesis engine. You look at entity \
relationships that span different scientific fields and propose the hidden \
connection. Return STRICT JSON only. You never invent facts; if nothing \
compelling connects the items, return an empty list."""


def synthesize_cross_domain(*, max_pairs: int = 6) -> dict[str, Any]:
    """Find entity pairs bridging different fields and propose bridge patterns."""
    ensure_pattern_store()
    gateway = get_gateway()
    started = _now()

    # Entities seen in more than one field, or pairs whose relation type
    # matches a registered bridge template.
    with library_connection("gemma") as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.name, e.entity_type, e.mention_count,
                   GROUP_CONCAT(DISTINCT d.scientific_field) AS fields
            FROM pattern_entities e
            LEFT JOIN documents d
              ON d.title LIKE '%' || e.name || '%'
            GROUP BY e.id
            HAVING COUNT(DISTINCT d.scientific_field) >= 1 AND e.mention_count >= 2
            ORDER BY e.mention_count DESC
            LIMIT 60
            """,
            (),
        ).fetchall()

    if len(rows) < 2:
        return {"ok": True, "proposed": 0, "note": "Not enough extracted entities yet — analyze more documents first."}

    entity_lines = [
        f"- {r['name']} ({r['entity_type']}) fields: {r['fields'] or 'unknown'}" for r in rows
    ]
    try:
        reply = gateway.chat_json(
            [
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Below are entities extracted from a scientific knowledge library, with the "
                        "fields they appeared in. Identify at most "
                        f"{max_pairs} compelling CROSS-DOMAIN patterns: hidden connections between "
                        "entities from different fields that together suggest a problem, a solution, "
                        "a cure, or a novel insight. Base every pattern only on the listed entities "
                        "and general scientific knowledge; do not fabricate specific findings.\n\n"
                        "Return JSON: {\"patterns\": [{\"title\", \"statement\", "
                        "\"pattern_type\": \"cross_domain_bridge\", \"fields_involved\": [...], "
                        "\"confidence\": 0.0-1.0, \"entity_names\": [...]}]}\n\n"
                        "ENTITIES:\n" + "\n".join(entity_lines)
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=1200,
        )
    except LLMGatewayError as ex:
        return {"ok": False, "error": str(ex)[:300]}

    proposed = 0
    patterns = (reply or {}).get("patterns") if isinstance(reply, dict) else None
    for item in (patterns or [])[:max_pairs]:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or "").strip()
        if not statement:
            continue
        title = str(item.get("title") or "Cross-domain pattern").strip()
        fields = [str(f) for f in (item.get("fields_involved") or []) if str(f).strip()]
        entity_names = [str(n) for n in (item.get("entity_names") or []) if str(n).strip()]
        evidence = [
            {
                "document_title": f"Synthesis across entities: {', '.join(entity_names[:6])}",
                "field_slug": fields[0] if fields else "",
                "chunk_text": statement[:1000],
                "source_url": "",
            }
        ]
        try:
            register_template("cross_domain_bridge", "Cross-Domain Bridge", source_entity_type="concept", target_entity_type="concept", relation_type="bridged_with")
            propose_pattern(
                title,
                statement,
                pattern_type="cross_domain_bridge",
                fields_involved=fields,
                confidence=float(item.get("confidence") or 0.5),
                template_key="cross_domain_bridge",
                evidence=evidence,
            )
            proposed += 1
        except Exception:
            continue

    from .pattern_store import log_extraction as _log  # avoid circulars

    _log(None, "synthesis", patterns_proposed=proposed, started_at=started)
    return {"ok": True, "proposed": proposed, "entities_considered": len(rows)}
