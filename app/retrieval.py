from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from .coding_corpus import classify_coding_source_path
from .coding_governance import question_has_coding_intent


def _fts_query_from_text(query: str) -> str:
    stop = {"the", "and", "for", "with", "that", "this", "what", "does", "how", "why", "when", "where"}
    tokens = []
    for raw in query.replace('"', " ").split():
        token = "".join(ch for ch in raw if ch.isalnum()).strip().lower()
        if len(token) < 3:
            continue
        if token in stop:
            continue
        tokens.append(token)
    if not tokens:
        return ""
    tokens = tokens[:8]
    return " OR ".join(f'"{t}"' for t in tokens)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _allow_discussion_memory(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    if not normalized:
        return False
    tokens = (
        "discussion memory",
        "conversation memory",
        "previous discussion",
        "previous chat",
        "session memory",
        "chat history",
        "what did we discuss",
        "recap our chat",
    )
    return any(token in normalized for token in tokens)


def _normalize_query_mode(mode: str | None) -> str:
    value = str(mode or "").strip().lower()
    if value not in {"knowledge", "coding", "questionnaire", "autonomous"}:
        return ""
    return value


def _is_noise_source(path: str | None, *, settings: dict[str, Any] | None = None) -> bool:
    return classify_coding_source_path(path, settings=settings) == "noise"


def _is_coding_focus(query: str, mode: str | None = None) -> bool:
    mode_norm = _normalize_query_mode(mode)
    return mode_norm == "coding" or question_has_coding_intent(query)


def _coding_source_boost(row: dict[str, Any], *, settings: dict[str, Any] | None = None) -> float:
    boost = 1.0
    classification = classify_coding_source_path(row.get("source_path"), settings=settings)
    source_type = str(row.get("source_type") or "").strip().lower()
    source_collection = str(row.get("source_collection") or "").strip().lower()

    if classification == "repo":
        boost *= 3.0 if source_type == "code" else 2.1
    elif classification == "reference":
        boost *= 1.45
    elif classification == "noise":
        boost *= 0.25

    if source_type == "code":
        boost *= 1.15
    if "smi coding corpus" in source_collection:
        boost *= 1.2
    if "coding reference library" in source_collection:
        boost *= 1.1
    return boost


def search_chunks(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    module: str | None = None,
    topic: str | None = None,
    scientific_field: str | None = None,
    vocational_discipline: str | None = None,
    source_collection: str | None = None,
    query_embedding: list[float] | None = None,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    fts_query = _fts_query_from_text(query)
    if not fts_query:
        return []
    coding_focus = _is_coding_focus(query, mode)

    # Single-library retrieval: the Sentinel library holds every field
    # (the former separate coding library was folded in).
    from .library_router import library_path_for, field_boost_for

    lib_conn = sqlite3.connect(str(library_path_for()), timeout=15)
    lib_conn.row_factory = sqlite3.Row
    try:
        return _search_library_chunks(
            lib_conn,
            fts_query,
            query=query,
            limit=limit,
            module=module,
            topic=topic,
            scientific_field=scientific_field,
            vocational_discipline=vocational_discipline,
            source_collection=source_collection,
            query_embedding=query_embedding,
            coding_focus=coding_focus,
        )
    finally:
        lib_conn.close()


def _search_library_chunks(
    conn: sqlite3.Connection,
    fts_query: str,
    *,
    query: str,
    limit: int,
    module: str | None,
    topic: str | None,
    scientific_field: str | None,
    vocational_discipline: str | None,
    source_collection: str | None,
    query_embedding: list[float] | None,
    coding_focus: bool,
) -> list[dict[str, Any]]:
    from .library_router import field_boost_for

    sql = """
    SELECT
        c.id AS chunk_id,
        c.document_id AS document_id,
        c.chunk_index AS chunk_index,
        c.content AS content,
        c.embedding_json AS embedding_json,
        bm25(chunk_fts) AS lexical_score,
        d.source_id AS source_id,
        d.title AS title,
        d.source_type AS source_type,
        d.source_url AS source_url,
        d.source_path AS source_path,
        d.authors AS authors,
        d.publisher AS publisher,
        d.published_date AS published_date,
        d.module AS module,
        d.topic AS topic,
        d.scientific_field AS scientific_field,
        d.vocational_discipline AS vocational_discipline,
        d.source_collection AS source_collection,
        d.priority AS priority
    FROM chunk_fts
    JOIN chunks c ON c.id = chunk_fts.rowid
    JOIN documents d ON d.id = c.document_id
    WHERE chunk_fts MATCH ?
    """
    args: list[Any] = [fts_query]

    if not _allow_discussion_memory(query):
        sql += " AND IFNULL(d.source_path, '') NOT LIKE ?"
        args.append("%\\SMI_Log\\discussion_memory\\%")
    if coding_focus:
        noise_patterns = [
            "%\\SMI_Log\\%",
            "%\\data\\logs\\%",
            "%\\data\\raw\\%",
            "%\\data\\archive\\%",
        ]
        for pattern in noise_patterns:
            sql += " AND IFNULL(d.source_path, '') NOT LIKE ?"
            args.append(pattern)

    if module:
        sql += " AND IFNULL(d.module, '') = ?"
        args.append(module.strip())
    if topic:
        sql += " AND IFNULL(d.topic, '') = ?"
        args.append(topic.strip())
    if scientific_field:
        sql += " AND IFNULL(d.scientific_field, '') = ?"
        args.append(scientific_field.strip())
    if vocational_discipline:
        sql += " AND IFNULL(d.vocational_discipline, '') = ?"
        args.append(vocational_discipline.strip())
    if source_collection:
        sql += " AND IFNULL(d.source_collection, '') = ?"
        args.append(source_collection.strip())

    candidate_cap = limit * (12 if coding_focus else 6)
    sql += " ORDER BY lexical_score ASC LIMIT ?"
    args.append(max(1, min(160, candidate_cap)))

    rows = [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]
    if not rows:
        return rows

    # Lexical baseline score: lower bm25 is better. Convert to monotonic relevance.
    for row in rows:
        lexical = float(row.get("lexical_score") or 0.0)
        row["relevance_score"] = 1.0 / (1.0 + max(0.0, lexical))
        if coding_focus:
            row["relevance_score"] *= _coding_source_boost(row)
        # Sentinel focus profile: boost the fields the operator prioritized.
        row["relevance_score"] *= field_boost_for(row.get("scientific_field"))

    if query_embedding:
        for row in rows:
            emb_raw = row.get("embedding_json")
            vector_score = 0.0
            if emb_raw:
                try:
                    emb = json.loads(str(emb_raw))
                    if isinstance(emb, list):
                        vector_score = _cosine_similarity(query_embedding, [float(v) for v in emb])
                except Exception:
                    vector_score = 0.0
            # Weighted blend with lexical baseline.
            row["relevance_score"] = (0.65 * row["relevance_score"]) + (0.35 * max(-1.0, min(1.0, vector_score)))

    # Hide large internal vectors from API-facing payloads.
    for row in rows:
        row.pop("embedding_json", None)
        if not coding_focus and _is_noise_source(row.get("source_path")):
            row["relevance_score"] *= 0.75

    rows.sort(key=lambda r: r.get("relevance_score", 0.0), reverse=True)
    return rows[: max(1, min(100, limit))]


# ---------------------------------------------------------------------------
# §77 (corrections 1): Cross-functional pattern matching.
# Spotting structural anomalies across disparate fields (a public-health
# signal mirroring a chemistry dataset) requires querying OUTSIDE the field
# the question names. search_chunks_cross_sector runs the same query against
# a different Sentinel domain and merges only novel hits, so cross-domain
# structure can surface without drowning the primary answer.
# ---------------------------------------------------------------------------

_CROSS_SECTOR_ROTATION = {
    "life-and-biological-systems": "foundations-of-reality",
    "foundations-of-reality": "computer-and-information-sciences",
    "human-behavior-and-society": "life-and-biological-systems",
    "applied-systems-and-technology": "foundations-of-reality",
    "health-safety-and-well-being": "human-behavior-and-society",
}
_DEFAULT_CROSS_SECTOR_ROTATION = "foundations-of-reality"

# Library documents carry fine-grained fields ("biology", "physics", ...);
# map them into the five Sentinel domains so the rotation works regardless
# of taxonomy granularity.
_FIELD_DOMAIN_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("bio", "gene", "zoo", "botan", "ecolog", "neuro", "microb", "protein"), "life-and-biological-systems"),
    (("phys", "chem", "astron", "geolog", "quantum", "material"), "foundations-of-reality"),
    (("psych", "socio", "econom", "polit", "educat", "law", "anthrop"), "human-behavior-and-society"),
    (("comput", "informat", "engineer", "software", "ai", "math"), "computer-and-information-sciences"),
    (("medic", "health", "nurs", "clinic", "epidem", "public-health", "safety", "well-?being"), "health-safety-and-well-being"),
)


def _domain_for_field(field: str) -> str:
    """Map any stored scientific_field (slug or free text) to a Sentinel domain."""
    f = (field or "").strip().lower()
    if not f:
        return ""
    for domain in _CROSS_SECTOR_ROTATION:
        if f == domain or f.startswith(domain):
            return domain
    for keywords, domain in _FIELD_DOMAIN_KEYWORDS:
        if any(k in f for k in keywords):
            return domain
    return ""


def cross_sector_target(scientific_field: str | None) -> str | None:
    """The domain to probe for structural analogs of the given field."""
    if not scientific_field:
        return None
    return _CROSS_SECTOR_ROTATION.get(scientific_field.strip(), _DEFAULT_CROSS_SECTOR_ROTATION)


def search_chunks_cross_sector(
    conn: sqlite3.Connection,
    query: str,
    *,
    scientific_field: str | None = None,
    limit: int = 3,
    exclude_chunk_ids: set[int] | None = None,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """Probe a rotationally-different Sentinel domain for structural analogs.

    Returns at most ``limit`` rows whose chunk ids are not in
    ``exclude_chunk_ids`` and whose scientific_field differs from the caller's
    field. Never raises: a cross-sector miss must not break the primary
    retrieval path.
    """
    try:
        target_domain = cross_sector_target(scientific_field)
        if not target_domain:
            return []
        caller_domain = _domain_for_field(scientific_field or "")
        probe_rows = search_chunks(
            conn,
            query=query,
            limit=max(8, int(limit) * 4),
            mode=mode,
        )
        excluded = exclude_chunk_ids or set()
        merged: list[dict[str, Any]] = []
        for row in probe_rows:
            row_domain = _domain_for_field(str(row.get("scientific_field") or ""))
            if not row_domain or row_domain == caller_domain:
                continue
            if row_domain != target_domain:
                continue
            if int(row.get("chunk_id") or 0) in excluded:
                continue
            row["cross_sector"] = True
            row["relevance_score"] = float(row.get("relevance_score") or 0.0) * 0.6
            merged.append(row)
            if len(merged) >= max(1, int(limit)):
                break
        return merged
    except Exception:
        return []
