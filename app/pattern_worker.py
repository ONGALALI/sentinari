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
from .pattern_lexicon import scan_document_text
from .pattern_store import (
    ensure_pattern_store,
    get_pattern_recognition_enabled as pattern_recognition_enabled,
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
   "fields_involved" (list of 1-3 canonical Sentinel field slugs from: physics, chemistry,
   astronomy-cosmology, earth-sciences, mathematics, biology, genetics-molecular-biology,
   ecology-environmental-biology, neuroscience, psychology, sociology, anthropology,
   economics, political-science, philosophy, laws-per-country-and-international-law,
   war, religion, computer-and-information-sciences, engineering, materials-science,
   information-science, medicine, pharmacology, public-health, environmental-science),
   "confidence" (0.0-1.0),
   "supporting_text" (the exact quote from the text that supports it).

{crisis_line}

TEXT:
{text}
"""


def queue_document(document_id: int) -> int:
    """Add a document to the extraction queue."""
    ensure_pattern_store()
    from .pattern_store import _connect

    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO pattern_extraction_log (document_id, status, started_at) VALUES (?, 'queued', ?)",
            (int(document_id), _now()),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


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
    from .sentinel_domains import sanitize_field_and_domain

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
    doc_title = str(doc["title"] or "Untitled")
    canon_field, _ = sanitize_field_and_domain(str(doc["scientific_field"] or ""), fallback_text=doc_title)
    out: list[dict[str, Any]] = []
    for c in chunks:
        raw_text = str(c["content"] or "")
        if "OpenAlex record JSON:" in raw_text:
            raw_text = raw_text.split("OpenAlex record JSON:", 1)[0].strip()
        if not raw_text or "(no abstract available)" in raw_text:
            continue
        # Skip pure JSON metadata fragments from legacy OpenAlex stubs
        if raw_text.lstrip().startswith(('{"', '{ "', '"institution_ids"', '"author_position"')) or '"institution_ids":' in raw_text:
            continue
        out.append(
            {
                "document_id": int(doc["id"]),
                "title": doc_title,
                "field": canon_field or str(doc["scientific_field"] or ""),
                "source_url": str(doc["source_url"] or ""),
                "chunk_id": int(c["id"]),
                "chunk_index": int(c["chunk_index"]),
                "text": raw_text[:MAX_CHARS_PER_CHUNK],
            }
        )
    return out


def _extract_baseline_entities_and_relations(
    chunks: list[dict[str, Any]],
    crisis_family_terms: dict[str, set[str]],
    entity_id_fn: Any,
) -> tuple[int, int]:
    """Deterministic baseline entity/relation extraction so every scanned document maps its scientific nodes."""
    import re as _re

    ent_count = 0
    rel_count = 0
    if not chunks:
        return 0, 0
    first = chunks[0]
    field_name = str(first.get("field") or "general-science").replace("-", " ").strip()
    title = str(first.get("title") or "").strip()
    field_eid = entity_id_fn(field_name, "concept") if field_name else None
    if field_eid:
        ent_count += 1

    # Extract key noun/technical phrases from title
    clean_title = _re.sub(r"[^A-Za-z0-9\s\-]", " ", title)
    words = [w for w in clean_title.split() if len(w) >= 5 and w.lower() not in {"study", "paper", "using", "based", "model", "models", "analysis", "review", "system"}]
    prev_eid = field_eid
    for w in words[:4]:
        eid = entity_id_fn(w.lower(), "concept")
        if eid:
            ent_count += 1
            if prev_eid and prev_eid != eid:
                try:
                    upsert_relation(prev_eid, eid, "correlates_with", 0.65)
                    rel_count += 1
                except Exception:
                    pass
            prev_eid = eid

    for fam, terms in list(crisis_family_terms.items())[:3]:
        for t in sorted(terms)[:4]:
            teid = entity_id_fn(t, "problem" if "risk" in fam or "crisis" in fam else "concept")
            if teid:
                ent_count += 1
                if field_eid and field_eid != teid:
                    try:
                        upsert_relation(field_eid, teid, "addressed_by", 0.7)
                        rel_count += 1
                    except Exception:
                        pass
    return ent_count, rel_count


def extract_document(
    document_id: int,
    *,
    max_chunks: int = MAX_CHUNKS_PER_DOCUMENT,
    focus_topic: str = "",
    focus_note: str = "",
    preferred_chunk_ids: list[int] | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Run extraction over a document's chunks (batched up to 4 chunks per LLM call for cost efficiency)."""
    ensure_pattern_store()
    gateway = get_gateway()
    started = _now()

    chunks = _document_chunks(document_id, max(max_chunks, 24) if preferred_chunk_ids else max_chunks)
    if not chunks:
        log_id = log_extraction(document_id, "skipped", error="document not found in library", started_at=started)
        return {"ok": False, "reason": "document-not-found", "log_id": log_id}
    if preferred_chunk_ids:
        pref_set = set(int(cid) for cid in preferred_chunk_ids)
        chunks.sort(key=lambda c: (0 if int(c["chunk_id"]) in pref_set else 1, int(c["chunk_index"])))
        chunks = chunks[:max_chunks]

    entities_found = 0
    relations_found = 0
    patterns_proposed = 0
    batch_errors: list[str] = []

    crisis_score_total = 0.0
    crisis_terms_total = 0
    crisis_family_terms: dict[str, set[str]] = {}

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

    pattern_drafts: list[dict[str, Any]] = []

    # First pass: triage all selected chunks via §74l crisis lexicon
    for chunk in chunks:
        triage = scan_document_text(chunk["text"])
        crisis_score_total += float(triage.get("score") or 0.0)
        crisis_terms_total += int(triage.get("matched_terms") or 0)
        for fam, info in (triage.get("families") or {}).items():
            crisis_family_terms.setdefault(fam, set()).update(info.get("terms") or [])

    # Group chunks into batches of up to 4 chunks (~7,500 chars) so 1 document = 1 LLM call instead of 4-24 calls
    chunk_groups: list[list[dict[str, Any]]] = []
    if use_llm:
        cur_group: list[dict[str, Any]] = []
        cur_chars = 0
        for ch in chunks[: max(1, min(8, max_chunks))]:
            ch_len = len(ch["text"])
            if cur_group and (len(cur_group) >= 4 or cur_chars + ch_len > 7500):
                chunk_groups.append(cur_group)
                cur_group = []
                cur_chars = 0
            cur_group.append(ch)
            cur_chars += ch_len
        if cur_group:
            chunk_groups.append(cur_group)

    for group in chunk_groups[:2]:
        if not pattern_recognition_enabled():
            log_id = log_extraction(document_id, "skipped", error="pattern recognition paused", started_at=started)
            return {"ok": False, "reason": "paused", "log_id": log_id}
        primary_chunk = group[0]
        combined_text = "\n\n---\n\n".join(c["text"][:2200] for c in group)
        crisis_line = ""
        if crisis_family_terms:
            ranked = sorted(crisis_family_terms.items(), key=lambda kv: -len(kv[1]))[:3]
            tops = " | ".join(f"{fam.replace('_', ' ')}: {', '.join(sorted(ts)[:8])}" for fam, ts in ranked)
            crisis_line = (
                f"\n\nCRISIS & THREAT SIGNALS PRESENT (§74l): {tops}\n"
                "Treat these as priority entities and prioritize patterns that "
                "explain, predict, or resolve them."
            )
        if focus_topic or focus_note:
            focus_line = f"\n\nUSER-REQUESTED DISCOVERY FOCUS: {focus_topic}"
            if focus_note:
                focus_line += f" — {focus_note}"
            focus_line += (
                "\nPrioritize extracting entities, relations, and actionable scientific patterns "
                "directly addressing or illuminating this requested focus."
            )
            crisis_line = f"{crisis_line}{focus_line}"
        try:
            reply = gateway.chat_json(
                [
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": EXTRACTION_USER_TEMPLATE.format(
                            title=primary_chunk["title"],
                            field=primary_chunk["field"] or "unknown",
                            text=combined_text,
                            crisis_line=crisis_line,
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=4096,
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
            # Match quote to the specific chunk in group if possible
            matched_chunk = primary_chunk
            if quote:
                q_short = quote[:60].lower()
                for ch in group:
                    if q_short in ch["text"].lower():
                        matched_chunk = ch
                        break
            pattern_drafts.append(
                {
                    "title": title,
                    "statement": statement,
                    "pattern_type": str(item.get("pattern_type") or "general"),
                    "fields_involved": item.get("fields_involved") or ([matched_chunk["field"]] if matched_chunk["field"] else []),
                    "confidence": float(item.get("confidence") or 0.5),
                    "template_key": str(item.get("pattern_type") or "general"),
                    "evidence": [
                        {
                            "document_id": matched_chunk["document_id"],
                            "chunk_id": matched_chunk["chunk_id"],
                            "document_title": matched_chunk["title"],
                            "field_slug": matched_chunk["field"],
                            "chunk_text": quote or matched_chunk["text"][:600],
                            "source_url": matched_chunk["source_url"],
                        }
                    ],
                }
            )

    # Always ensure baseline domain entities & relations are mapped when scanning a document
    if entities_found == 0 and relations_found == 0:
        b_ent, b_rel = _extract_baseline_entities_and_relations(chunks, crisis_family_terms, entity_id)
        entities_found += b_ent
        relations_found += b_rel

    # Store proposed patterns (deduped by title+statement prefix).
    seen_titles: set[str] = set()
    for draft in pattern_drafts:
        key = (draft["title"].lower(), draft["statement"].lower()[:120])
        if key in seen_titles:
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

    status = "ok" if (entities_found or relations_found or patterns_proposed or not batch_errors) else "error"
    crisis_summary = "; ".join(
        f"{fam}: {', '.join(sorted(ts)[:6])}"
        for fam, ts in sorted(crisis_family_terms.items(), key=lambda kv: -len(kv[1]))[:3]
    )
    log_id = log_extraction(
        document_id,
        status,
        entities_found=entities_found,
        relations_found=relations_found,
        patterns_proposed=patterns_proposed,
        error="; ".join(batch_errors)[:900],
        started_at=started,
        crisis_score=round(crisis_score_total, 1),
        crisis_terms=crisis_summary,
    )
    return {
        "ok": status in {"ok", "empty"},
        "status": status,
        "log_id": log_id,
        "chunks_processed": len(chunks),
        "entities_found": entities_found,
        "relations_found": relations_found,
        "patterns_proposed": patterns_proposed,
        "crisis_score": round(crisis_score_total, 1),
        "crisis_terms_matched": crisis_terms_total,
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


def synthesize_cross_domain(*, max_pairs: int = 6, focus_topic: str = "") -> dict[str, Any]:
    """Find entity pairs bridging different fields and propose bridge patterns."""
    ensure_pattern_store()
    gateway = get_gateway()
    started = _now()
    from .pattern_store import _connect

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.name, e.entity_type, e.description, e.mention_count
            FROM pattern_entities e
            ORDER BY e.mention_count DESC, e.id DESC
            LIMIT 60
            """,
            (),
        ).fetchall()
        rel_rows = conn.execute(
            """
            SELECT se.name AS src_name, r.relation_type, te.name AS tgt_name, r.confidence
            FROM pattern_relations r
            JOIN pattern_entities se ON se.id = r.source_entity_id
            JOIN pattern_entities te ON te.id = r.target_entity_id
            ORDER BY r.mention_count DESC, r.confidence DESC
            LIMIT 40
            """,
            (),
        ).fetchall()

    if len(rows) < 2:
        return {"ok": True, "proposed": 0, "note": "Not enough extracted entities yet — analyze more documents first."}

    entity_lines = [
        f"- {r['name']} ({r['entity_type']}, mentions={r['mention_count']}): {str(r['description'] or '')[:120]}"
        for r in rows
    ]
    rel_lines = [
        f"- {r['src_name']} --[{r['relation_type']}]--> {r['tgt_name']} (conf={float(r['confidence'] or 0.5):.2f})"
        for r in rel_rows
    ]
    focus_clause = (
        f"\nPrioritize cross-domain patterns relevant to the user-requested focus: \"{focus_topic}\".\n"
        if focus_topic.strip()
        else ""
    )
    try:
        reply = gateway.chat_json(
            [
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Below are entities and relations extracted from a scientific knowledge library. "
                        f"Identify at most {max_pairs} compelling CROSS-DOMAIN patterns: hidden connections "
                        "between entities across scientific fields that together suggest a problem, a solution, "
                        "a cure, or a novel insight. Base every pattern only on the listed entities/relations "
                        "and general scientific knowledge; do not fabricate specific findings.\n"
                        f"{focus_clause}\n"
                        "Return JSON: {\"patterns\": [{\"title\", \"statement\", "
                        "\"pattern_type\": \"cross_domain_bridge\", \"fields_involved\": [...], "
                        "\"confidence\": 0.0-1.0, \"entity_names\": [...]}]}\n\n"
                        "ENTITIES:\n" + "\n".join(entity_lines) +
                        ("\n\nRELATIONS:\n" + "\n".join(rel_lines) if rel_lines else "")
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=3072,
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
