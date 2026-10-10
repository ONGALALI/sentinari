"""Search workspace API — the ingested library as a searchable database.

Owner directive: instead of listing raw uploaded documents in the Playground,
the knowledge library is exposed as a searchable database grouped under the
five main scientific areas (the Sentinel domains). Opening a domain container
reveals its scientific-field containers, and opening a field container lists
the datasets available to preview (HTML) and download.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from .db import library_connection
from .sentinel_domains import (
    SENTINEL_DOMAINS,
    resolve_domain_or_field_filter,
    resolve_field_loose,
    sanitize_field_and_domain,
    slugify,
)

router = APIRouter(prefix="/api/search-library", tags=["search-library"])


def _resolve_field_slug(field: str) -> str:
    text = str(field or "").strip()
    if not text:
        return ""
    f_slug, _ = sanitize_field_and_domain(field=text)
    if f_slug:
        return f_slug
    try:
        return resolve_field_loose(text)
    except Exception:
        return slugify(text)


def _all_field_stats(conn: Any) -> dict[str, dict[str, int]]:
    """Aggregate dataset, chunk, and embedded chunk counts grouped by canonical field slug."""
    stats_by_slug: dict[str, dict[str, int]] = {}
    doc_rows = conn.execute(
        """
        SELECT COALESCE(scientific_field, '') AS sf,
               COALESCE(domain, '') AS dom,
               COUNT(1) AS docs
        FROM documents
        GROUP BY COALESCE(scientific_field, ''), COALESCE(domain, '')
        """
    ).fetchall()

    chunk_rows = []
    try:
        chunk_rows = conn.execute(
            """
            SELECT COALESCE(d.scientific_field, '') AS sf,
                   COALESCE(d.domain, '') AS dom,
                   COUNT(c.id) AS chunks,
                   COALESCE(SUM(CASE WHEN c.embedding IS NOT NULL OR c.embedding_json IS NOT NULL THEN 1 ELSE 0 END), 0) AS embedded
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY COALESCE(d.scientific_field, ''), COALESCE(d.domain, '')
            """
        ).fetchall()
    except Exception:
        try:
            chunk_rows = conn.execute(
                """
                SELECT COALESCE(d.scientific_field, '') AS sf,
                       COALESCE(d.domain, '') AS dom,
                       COUNT(c.id) AS chunks,
                       COALESCE(SUM(CASE WHEN c.embedding_json IS NOT NULL THEN 1 ELSE 0 END), 0) AS embedded
                FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.id
                GROUP BY COALESCE(d.scientific_field, ''), COALESCE(d.domain, '')
                """
            ).fetchall()
        except Exception:
            pass

    chunk_map: dict[tuple[str, str], tuple[int, int]] = {}
    for crow in chunk_rows:
        key = (str(crow["sf"] or ""), str(crow["dom"] or ""))
        chunk_map[key] = (int(crow["chunks"] or 0), int(crow["embedded"] or 0))

    for drow in doc_rows:
        raw_sf = str(drow["sf"] or "")
        raw_dom = str(drow["dom"] or "")
        docs = int(drow["docs"] or 0)
        chunks, embedded = chunk_map.get((raw_sf, raw_dom), (0, 0))
        f_slug, _ = sanitize_field_and_domain(field=raw_sf, domain=raw_dom)
        target_slug = (f_slug or slugify(raw_sf) or "unassigned").lower()
        bucket = stats_by_slug.setdefault(
            target_slug,
            {"dataset_count": 0, "chunk_count": 0, "embedded_chunks": 0},
        )
        bucket["dataset_count"] += docs
        bucket["chunk_count"] += chunks
        bucket["embedded_chunks"] += embedded

    return stats_by_slug


@router.get("/overview")
def overview() -> dict[str, Any]:
    """The five main scientific areas with their field containers and counts."""
    domains: list[dict[str, Any]] = []
    known_slugs: set[str] = set()
    with library_connection("gemma") as conn:
        stats_by_slug = _all_field_stats(conn)

    for domain in SENTINEL_DOMAINS:
        fields: list[dict[str, Any]] = []
        for field in domain.get("fields", []) or []:
            field_name = str(field.get("name") or "")
            field_slug = str(field.get("slug") or slugify(field_name))
            try:
                resolved_slug = resolve_field_loose(field_slug)
                if resolved_slug:
                    field_slug = resolved_slug
            except Exception:
                pass
            known_slugs.add(field_slug.lower())
            stats = stats_by_slug.get(
                field_slug.lower(),
                {"dataset_count": 0, "chunk_count": 0, "embedded_chunks": 0},
            )
            fields.append(
                {
                    "slug": field_slug,
                    "name": field_name,
                    "detail": str(field.get("detail") or ""),
                    **stats,
                }
            )
        domains.append(
            {
                "slug": str(domain.get("slug") or ""),
                "name": str(domain.get("name") or ""),
                "description": str(domain.get("description") or ""),
                "dataset_count": sum(f["dataset_count"] for f in fields),
                "chunk_count": sum(f["chunk_count"] for f in fields),
                "fields": fields,
            }
        )

    other_fields: list[dict[str, Any]] = []
    for sf_slug, stats in sorted(
        stats_by_slug.items(),
        key=lambda kv: kv[1]["dataset_count"],
        reverse=True,
    ):
        if not sf_slug or sf_slug in known_slugs or stats["dataset_count"] <= 0:
            continue
        known_slugs.add(sf_slug)
        other_fields.append(
            {
                "slug": sf_slug,
                "name": sf_slug.replace("-", " ").title(),
                "detail": "(field recorded in the library outside the five Sentinel domains)",
                **stats,
            }
        )
    if other_fields:
        domains.append(
            {
                "slug": "other-fields",
                "name": "Other Recorded Fields",
                "description": "Fields that hold library data outside the five Sentinel domains.",
                "dataset_count": sum(f["dataset_count"] for f in other_fields),
                "chunk_count": sum(f["chunk_count"] for f in other_fields),
                "fields": other_fields,
            }
        )
    return {
        "ok": True,
        "domains": domains,
        "total_datasets": sum(d["dataset_count"] for d in domains),
        "total_chunks": sum(d["chunk_count"] for d in domains),
    }


@router.get("/documents")
def documents(
    field: str = Query(default="", description="Field or domain slug (empty = all fields)"),
    domain: str = Query(default="", description="Optional Sentinel domain slug or name"),
    q: str = Query(default="", description="Search phrase over titles/authors/source"),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """Datasets in a field or domain container — searchable across the whole library."""
    where = ["1=1"]
    params: list[Any] = []
    filter_val = (field or domain or "").strip()
    if filter_val:
        d_slug, field_slugs = resolve_domain_or_field_filter(filter_val)
        if d_slug and field_slugs:
            placeholders = ", ".join(["LOWER(?)"] * len(field_slugs))
            where.append(
                f"(LOWER(COALESCE(domain, '')) = LOWER(?) OR LOWER(COALESCE(scientific_field, '')) IN ({placeholders}))"
            )
            params.append(d_slug)
            params.extend(field_slugs)
        elif field_slugs:
            if len(field_slugs) == 1:
                where.append("LOWER(COALESCE(scientific_field, '')) = LOWER(?)")
                params.append(field_slugs[0])
            else:
                placeholders = ", ".join(["LOWER(?)"] * len(field_slugs))
                where.append(f"LOWER(COALESCE(scientific_field, '')) IN ({placeholders})")
                params.extend(field_slugs)
        else:
            f_slug = _resolve_field_slug(filter_val)
            if f_slug:
                where.append("LOWER(COALESCE(scientific_field, '')) = LOWER(?)")
                params.append(f_slug)
    phrase = q.strip()
    if phrase:
        like = f"%{phrase.lower()}%"
        where.append(
            "(LOWER(title) LIKE ? OR LOWER(IFNULL(authors, '')) LIKE ? "
            "OR LOWER(IFNULL(source_type, '')) LIKE ? OR LOWER(IFNULL(scientific_field, '')) LIKE ? "
            "OR LOWER(IFNULL(domain, '')) LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    items: list[dict[str, Any]] = []
    with library_connection("gemma") as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, source_type, source_path, source_url, domain, scientific_field,
                   authors, publisher, published_date, raw_char_count, created_at
            FROM documents
            WHERE {" AND ".join(where)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        doc_ids = [int(r["id"]) for r in rows]
        chunk_stats: dict[int, tuple[int, int]] = {}
        if doc_ids:
            placeholders = ", ".join(["?"] * len(doc_ids))
            try:
                crows = conn.execute(
                    f"""
                    SELECT document_id,
                           COUNT(1) AS chunks,
                           COALESCE(SUM(CASE WHEN embedding IS NOT NULL OR embedding_json IS NOT NULL THEN 1 ELSE 0 END), 0) AS embedded
                    FROM chunks
                    WHERE document_id IN ({placeholders})
                    GROUP BY document_id
                    """,
                    tuple(doc_ids),
                ).fetchall()
                for cr in crows:
                    chunk_stats[int(cr["document_id"])] = (int(cr["chunks"] or 0), int(cr["embedded"] or 0))
            except Exception:
                try:
                    crows = conn.execute(
                        f"""
                        SELECT document_id,
                               COUNT(1) AS chunks,
                               COALESCE(SUM(CASE WHEN embedding_json IS NOT NULL THEN 1 ELSE 0 END), 0) AS embedded
                        FROM chunks
                        WHERE document_id IN ({placeholders})
                        GROUP BY document_id
                        """,
                        tuple(doc_ids),
                    ).fetchall()
                    for cr in crows:
                        chunk_stats[int(cr["document_id"])] = (int(cr["chunks"] or 0), int(cr["embedded"] or 0))
                except Exception:
                    pass
        for row in rows:
            d = dict(row)
            f_slug, d_slug = sanitize_field_and_domain(
                field=d.get("scientific_field"),
                domain=d.get("domain"),
                title=d.get("title"),
            )
            if f_slug:
                d["scientific_field"] = f_slug
            if d_slug:
                d["domain"] = d_slug
            chunks_n, emb_n = chunk_stats.get(int(row["id"]), (0, 0))
            d["chunk_count"] = chunks_n
            d["embedded_chunks"] = emb_n
            items.append(d)
    return {"ok": True, "count": len(items), "documents": items}

