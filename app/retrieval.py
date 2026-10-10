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


def _pg_query_tokens(query: str) -> tuple[list[str], list[str]]:
    stop = {
        "the", "and", "for", "with", "that", "this", "what", "does", "how", "why",
        "when", "where", "from", "into", "are", "was", "were", "which", "whose",
        "whom", "have", "has", "had", "will", "would", "could", "should", "can",
    }
    generic = {
        "point", "group", "value", "values", "number", "system", "state", "first",
        "order", "table", "level", "model", "index", "total", "using", "given",
        "under", "between", "within", "about", "after", "before",
    }
    tokens: list[str] = []
    for raw in str(query or "").replace('"', " ").split():
        token = "".join(ch for ch in raw if ch.isalnum()).strip().lower()
        if len(token) < 2 or token in stop:
            continue
        if token not in tokens:
            tokens.append(token)
    specific = [
        t for t in tokens
        if t not in generic and (len(t) >= 5 or any(ch.isdigit() for ch in t))
    ]
    return tokens[:12], specific[:10]


def _pg_tsquery_from_text(query: str) -> str:
    tokens, specific = _pg_query_tokens(query)
    chosen = specific if specific else tokens
    if not chosen:
        return ""
    return " | ".join(chosen[:10])


def search_chunks(
    conn: Any = None,
    query: str = "",
    limit: int = 8,
    module: str | None = None,
    topic: str | None = None,
    scientific_field: str | None = None,
    vocational_discipline: str | None = None,
    source_collection: str | None = None,
    query_embedding: list[float] | None = None,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    from .db import _get_pg_url, library_connection

    coding_focus = _is_coding_focus(query, mode)
    if _get_pg_url():
        tsq = _pg_tsquery_from_text(query)
        if query_embedding is None and str(query or "").strip():
            try:
                from .llm_gateway import get_gateway

                query_embedding = get_gateway().embed(str(query).strip()[:2000])
            except Exception:
                query_embedding = None
        if not tsq and not query_embedding:
            return []
        with library_connection("gemma") as pg_conn:
            return _search_library_chunks_pg(
                pg_conn,
                tsq,
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

    fts_query = _fts_query_from_text(query)
    if not fts_query:
        return []

    from .library_router import library_path_for

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


def _run_pg_fts_query(
    conn: Any,
    tsq: str,
    *,
    module: str | None,
    topic: str | None,
    scientific_field: str | None,
    vocational_discipline: str | None,
    source_collection: str | None,
    candidate_cap: int,
) -> list[dict[str, Any]]:
    if not tsq:
        return []
    sql = """
    SELECT
        c.id AS chunk_id,
        c.document_id AS document_id,
        c.chunk_index AS chunk_index,
        c.content AS content,
        c.embedding_json AS embedding_json,
        ts_rank_cd(to_tsvector('english'::regconfig, substring(c.content, 1, 100000)), to_tsquery('english'::regconfig, ?)) AS pg_rank,
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
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE to_tsvector('english'::regconfig, substring(c.content, 1, 100000)) @@ to_tsquery('english'::regconfig, ?)
    """
    args: list[Any] = [tsq, tsq]

    if module:
        sql += " AND COALESCE(d.module, '') = ?"
        args.append(module.strip())
    if topic:
        sql += " AND COALESCE(d.topic, '') = ?"
        args.append(topic.strip())
    if scientific_field:
        from .sentinel_domains import resolve_domain_or_field_filter

        d_slug, f_slugs = resolve_domain_or_field_filter(scientific_field)
        if d_slug and f_slugs:
            marks = ",".join("?" for _ in f_slugs)
            sql += f" AND (REPLACE(LOWER(COALESCE(d.scientific_field, '')), ' ', '-') IN ({marks}) OR LOWER(COALESCE(d.domain, '')) = ?)"
            args.extend([*f_slugs, d_slug])
        elif f_slugs:
            marks = ",".join("?" for _ in f_slugs)
            sql += f" AND REPLACE(LOWER(COALESCE(d.scientific_field, '')), ' ', '-') IN ({marks})"
            args.extend(f_slugs)
        else:
            sql += " AND LOWER(COALESCE(d.scientific_field, '')) = LOWER(?)"
            args.append(scientific_field.strip())
    if vocational_discipline:
        sql += " AND COALESCE(d.vocational_discipline, '') = ?"
        args.append(vocational_discipline.strip())
    if source_collection:
        sql += " AND COALESCE(d.source_collection, '') = ?"
        args.append(source_collection.strip())

    sql += " ORDER BY pg_rank DESC LIMIT ?"
    args.append(candidate_cap)
    return [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]


def _run_pg_vector_query(
    conn: Any,
    query_embedding: list[float],
    *,
    module: str | None,
    topic: str | None,
    scientific_field: str | None,
    vocational_discipline: str | None,
    source_collection: str | None,
    candidate_cap: int,
) -> list[dict[str, Any]]:
    if not query_embedding or len(query_embedding) != 768:
        return []
    vec_literal = "[" + ",".join(f"{float(v):.6f}" for v in query_embedding) + "]"
    sql = """
    SELECT
        c.id AS chunk_id,
        c.document_id AS document_id,
        c.chunk_index AS chunk_index,
        c.content AS content,
        0.0 AS pg_rank,
        (c.embedding <-> ?::vector) AS l2_distance,
        (1.0 - (c.embedding <=> ?::vector)) AS vector_similarity,
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
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE c.embedding IS NOT NULL
    """
    args: list[Any] = [vec_literal, vec_literal]

    if module:
        sql += " AND COALESCE(d.module, '') = ?"
        args.append(module.strip())
    if topic:
        sql += " AND COALESCE(d.topic, '') = ?"
        args.append(topic.strip())
    if scientific_field:
        from .sentinel_domains import resolve_domain_or_field_filter

        d_slug, f_slugs = resolve_domain_or_field_filter(scientific_field)
        if d_slug and f_slugs:
            marks = ",".join("?" for _ in f_slugs)
            sql += f" AND (REPLACE(LOWER(COALESCE(d.scientific_field, '')), ' ', '-') IN ({marks}) OR LOWER(COALESCE(d.domain, '')) = ?)"
            args.extend([*f_slugs, d_slug])
        elif f_slugs:
            marks = ",".join("?" for _ in f_slugs)
            sql += f" AND REPLACE(LOWER(COALESCE(d.scientific_field, '')), ' ', '-') IN ({marks})"
            args.extend(f_slugs)
        else:
            sql += " AND LOWER(COALESCE(d.scientific_field, '')) = LOWER(?)"
            args.append(scientific_field.strip())
    if vocational_discipline:
        sql += " AND COALESCE(d.vocational_discipline, '') = ?"
        args.append(vocational_discipline.strip())
    if source_collection:
        sql += " AND COALESCE(d.source_collection, '') = ?"
        args.append(source_collection.strip())

    sql += " ORDER BY c.embedding <=> ?::vector LIMIT ?"
    args.extend([vec_literal, candidate_cap])
    try:
        return [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]
    except Exception:
        return []


def _search_library_chunks_pg(
    conn: Any,
    tsq: str,
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

    tokens, specific = _pg_query_tokens(query)
    candidate_cap = max(1, min(160, limit * (12 if coding_focus else 8)))
    fts_rows = _run_pg_fts_query(
        conn,
        tsq,
        module=module,
        topic=topic,
        scientific_field=scientific_field,
        vocational_discipline=vocational_discipline,
        source_collection=source_collection,
        candidate_cap=candidate_cap,
    )
    if not fts_rows and specific and len(tokens) > len(specific):
        fallback_tsq = " | ".join(tokens[:10])
        fts_rows = _run_pg_fts_query(
            conn,
            fallback_tsq,
            module=module,
            topic=topic,
            scientific_field=scientific_field,
            vocational_discipline=vocational_discipline,
            source_collection=source_collection,
            candidate_cap=candidate_cap,
        )

    vec_rows: list[dict[str, Any]] = []
    if query_embedding:
        vec_rows = _run_pg_vector_query(
            conn,
            query_embedding,
            module=module,
            topic=topic,
            scientific_field=scientific_field,
            vocational_discipline=vocational_discipline,
            source_collection=source_collection,
            candidate_cap=max(16, min(80, limit * 6)),
        )

    merged_by_id: dict[int, dict[str, Any]] = {}
    for row in fts_rows:
        cid = int(row.get("chunk_id") or 0)
        row["_from_fts"] = True
        merged_by_id[cid] = row

    for vrow in vec_rows:
        cid = int(vrow.get("chunk_id") or 0)
        if cid in merged_by_id:
            merged_by_id[cid]["l2_distance"] = float(vrow.get("l2_distance") or 0.0)
            merged_by_id[cid]["vector_similarity"] = float(vrow.get("vector_similarity") or 0.0)
            merged_by_id[cid]["_from_vec"] = True
        else:
            vrow["_from_vec"] = True
            merged_by_id[cid] = vrow

    rows = list(merged_by_id.values())
    if not rows:
        return rows

    specific_set = set(specific)
    for row in rows:
        rank = float(row.get("pg_rank") or 0.0)
        title_lc = str(row.get("title") or "").lower()
        content_lc = str(row.get("content") or "")[:6000].lower()
        coverage_bonus = 0.0
        for tok in tokens:
            is_spec = tok in specific_set
            if tok in title_lc:
                coverage_bonus += 2.5 if is_spec else 0.6
            if tok in content_lc:
                coverage_bonus += 1.5 if is_spec else 0.3
        lexical_score = (max(0.05, rank) if row.get("_from_fts") else 0.0) + coverage_bonus

        vector_sim = float(row.get("vector_similarity") or 0.0)
        l2_dist = row.get("l2_distance")
        if query_embedding and not row.get("_from_vec"):
            emb_raw = row.get("embedding_json")
            if emb_raw:
                try:
                    emb = json.loads(str(emb_raw))
                    if isinstance(emb, list) and len(emb) == len(query_embedding):
                        vector_sim = _cosine_similarity(query_embedding, [float(v) for v in emb])
                        l2_dist = math.sqrt(max(0.0, 2.0 * (1.0 - vector_sim)))
                except Exception:
                    pass

        l2_score = (1.0 / (1.0 + float(l2_dist))) if l2_dist is not None else max(0.0, vector_sim)
        hybrid_bonus = 2.0 if (row.get("_from_fts") and row.get("_from_vec")) else 0.0
        total_score = lexical_score + (l2_score * 5.0 if (l2_dist is not None or vector_sim > 0) else 0.0) + hybrid_bonus

        row["lexical_score"] = round(lexical_score, 4)
        if l2_dist is not None:
            row["l2_distance"] = round(float(l2_dist), 4)
        row["vector_score"] = round(float(l2_score), 4)
        row["relevance_score"] = total_score
        if coding_focus:
            row["relevance_score"] *= _coding_source_boost(row)
        row["relevance_score"] *= field_boost_for(row.get("scientific_field"))
        row.pop("embedding_json", None)
        row.pop("_from_fts", None)
        row.pop("_from_vec", None)
        if not coding_focus and _is_noise_source(row.get("source_path")):
            row["relevance_score"] *= 0.75

    rows.sort(key=lambda r: r.get("relevance_score", 0.0), reverse=True)
    return rows[: max(1, min(100, limit))]


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

    for row in rows:
        lexical = float(row.get("lexical_score") or 0.0)
        row["relevance_score"] = 1.0 / (1.0 + max(0.0, lexical))
        if coding_focus:
            row["relevance_score"] *= _coding_source_boost(row)
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
            row["relevance_score"] = (0.65 * row["relevance_score"]) + (0.35 * max(-1.0, min(1.0, vector_score)))

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
