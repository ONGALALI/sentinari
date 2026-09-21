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
from .sentinel_domains import SENTINEL_DOMAINS, resolve_field_loose, slugify

router = APIRouter(prefix="/api/search-library", tags=["search-library"])


def _resolve_field_slug(field: str) -> str:
    text = str(field or "").strip()
    if not text:
        return ""
    try:
        return resolve_field_loose(text)
    except Exception:
        return slugify(text)


def _field_stats(conn: Any, field_slug: str) -> dict[str, int]:
    doc_row = conn.execute(
        "SELECT COUNT(1) AS docs FROM documents WHERE LOWER(scientific_field) = LOWER(?)",
        (field_slug,),
    ).fetchone()
    chunk_row = conn.execute(
        """
        SELECT COUNT(1) AS chunks,
               COALESCE(SUM(CASE WHEN embedding_json IS NULL THEN 0 ELSE 1 END), 0) AS embedded
        FROM chunks WHERE document_id IN (
            SELECT id FROM documents WHERE LOWER(scientific_field) = LOWER(?)
        )
        """,
        (field_slug,),
    ).fetchone()
    return {
        "dataset_count": int(doc_row["docs"]) if doc_row is not None else 0,
        "chunk_count": int(chunk_row["chunks"]) if chunk_row is not None else 0,
        "embedded_chunks": int(chunk_row["embedded"]) if chunk_row is not None else 0,
    }


@router.get("/overview")
def overview() -> dict[str, Any]:
    """The five main scientific areas with their field containers and counts."""
    domains: list[dict[str, Any]] = []
    known_slugs: set[str] = set()
    with library_connection("gemma") as conn:
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
                stats = _field_stats(conn, field_slug)
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
        # Fields that exist in the library but outside the current domain map
        # still deserve a container — nothing the owner loaded may be hidden.
        other_rows = conn.execute(
            """
            SELECT LOWER(scientific_field) AS lsf, MAX(scientific_field) AS sf, COUNT(1) AS docs
            FROM documents
            WHERE IFNULL(scientific_field, '') != ''
            GROUP BY LOWER(scientific_field)
            ORDER BY docs DESC
            """
        ).fetchall()
    other_fields: list[dict[str, Any]] = []
    with library_connection("gemma") as conn2:
        for row in other_rows:
            sf = str(row["sf"] or "")
            lsf = str(row["lsf"] or "")
            if not sf or lsf in known_slugs:
                continue
            known_slugs.add(lsf)
            other_fields.append(
                {
                    "slug": sf,
                    "name": sf.replace("-", " ").title(),
                    "detail": "(field recorded in the library but not part of the current domain map)",
                    **_field_stats(conn2, sf),
                }
            )
    if other_fields:
        domains.append(
            {
                "slug": "other-fields",
                "name": "Other Recorded Fields (outside the current domain map)",
                "description": "Fields that hold library data but are not part of the five Sentinel domains.",
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
    field: str = Query(default="", description="Field slug (empty = all fields)"),
    q: str = Query(default="", description="Search phrase over titles/authors/source"),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """Datasets in a field container — searchable across the whole library."""
    where = ["1=1"]
    params: list[Any] = []
    field_slug = _resolve_field_slug(field)
    if field_slug:
        where.append("LOWER(scientific_field) = LOWER(?)")
        params.append(field_slug)
    phrase = q.strip()
    if phrase:
        like = f"%{phrase.lower()}%"
        where.append(
            "(LOWER(title) LIKE ? OR LOWER(IFNULL(authors, '')) LIKE ? "
            "OR LOWER(IFNULL(source_type, '')) LIKE ? OR LOWER(IFNULL(scientific_field, '')) LIKE ?)"
        )
        params.extend([like, like, like, like])
    items: list[dict[str, Any]] = []
    with library_connection("gemma") as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, source_type, source_path, source_url, scientific_field,
                   authors, publisher, published_date, raw_char_count, created_at
            FROM documents
            WHERE {" AND ".join(where)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        for row in rows:
            d = dict(row)
            n = conn.execute(
                """
                SELECT COUNT(1) AS chunks,
                       COALESCE(SUM(CASE WHEN embedding_json IS NULL THEN 0 ELSE 1 END), 0) AS embedded
                FROM chunks WHERE document_id = ?
                """,
                (int(row["id"]),),
            ).fetchone()
            d["chunk_count"] = int(n["chunks"]) if n is not None else 0
            d["embedded_chunks"] = int(n["embedded"]) if n is not None else 0
            items.append(d)
    return {"ok": True, "count": len(items), "documents": items}
