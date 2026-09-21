from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from .config import get_settings


CATEGORY_TO_COLUMN = {
    "scientific_fields": "scientific_field",
    "vocational_disciplines": "vocational_discipline",
    "curricula": "source_collection",
}


def slugify(name: str) -> str:
    raw = (name or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = raw.strip("-")
    return raw or "unnamed"


def taxonomy_root() -> Path:
    settings = get_settings()
    return Path(settings["paths"]["taxonomy_root"]).resolve()


def category_root(category: str) -> Path:
    return taxonomy_root() / category


def ensure_taxonomy_roots() -> None:
    root = taxonomy_root()
    root.mkdir(parents=True, exist_ok=True)
    for category in CATEGORY_TO_COLUMN:
        (root / category).mkdir(parents=True, exist_ok=True)


def ensure_configured_taxonomy_dirs(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_taxonomy_roots()
    settings = get_settings()
    taxonomy_cfg = settings.get("taxonomy", {})
    if not bool(taxonomy_cfg.get("auto_create_missing", True)):
        return {"created": 0, "categories": {}}
    result = {"created": 0, "categories": {}}

    for category in CATEGORY_TO_COLUMN:
        names = taxonomy_cfg.get(category) or []
        created = 0
        category_path = category_root(category)
        for name in names:
            item_name = str(name or "").strip()
            if not item_name:
                continue
            slug = slugify(item_name)
            target = category_path / slug
            target.mkdir(parents=True, exist_ok=True)
            _upsert_taxonomy_node(conn, category, item_name, slug, target)
            created += 1
        result["categories"][category] = created
        result["created"] += created
    return result


def configure_taxonomy(
    conn: sqlite3.Connection,
    scientific_fields: list[str] | None = None,
    vocational_disciplines: list[str] | None = None,
    curricula: list[str] | None = None,
) -> dict[str, Any]:
    ensure_taxonomy_roots()
    payload = {
        "scientific_fields": scientific_fields or [],
        "vocational_disciplines": vocational_disciplines or [],
        "curricula": curricula or [],
    }

    created = 0
    for category, names in payload.items():
        category_dir = category_root(category)
        for raw_name in names:
            name = str(raw_name or "").strip()
            if not name:
                continue
            slug = slugify(name)
            target = category_dir / slug
            target.mkdir(parents=True, exist_ok=True)
            _upsert_taxonomy_node(conn, category, name, slug, target)
            created += 1

    rows = list_taxonomy(conn)
    return {"ok": True, "created": created, "items": rows}


def list_taxonomy(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, category, name, slug, path, created_at
        FROM taxonomy_nodes
        ORDER BY category, name;
        """
    ).fetchall()
    return [dict(r) for r in rows]


def infer_metadata_from_taxonomy_path(conn: sqlite3.Connection, path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    p = path.resolve()
    root = taxonomy_root()
    try:
        rel = p.relative_to(root)
    except ValueError:
        return result

    parts = rel.parts
    if len(parts) < 2:
        return result
    category = parts[0]
    slug = parts[1]
    if category not in CATEGORY_TO_COLUMN:
        return result

    row = None
    try:
        row = conn.execute(
            """
            SELECT name
            FROM taxonomy_nodes
            WHERE category = ? AND slug = ?
            LIMIT 1;
            """,
            (category, slug),
        ).fetchone()
    except sqlite3.OperationalError:
        # The caller passed a library-scoped connection (library_gemma.db /
        # (the single Gemma library has no taxonomy_nodes table; fall back to a
        # read connection on the main database so taxonomy enrichment keeps
        # working without crashing the ingest.
        try:
            from .db import get_connection

            with get_connection() as main_conn:
                row = main_conn.execute(
                    """
                    SELECT name
                    FROM taxonomy_nodes
                    WHERE category = ? AND slug = ?
                    LIMIT 1;
                    """,
                    (category, slug),
                ).fetchone()
        except Exception:
            row = None
    label = str(row["name"]) if row else slug.replace("-", " ").title()
    result[CATEGORY_TO_COLUMN[category]] = label
    return result


def _upsert_taxonomy_node(
    conn: sqlite3.Connection,
    category: str,
    name: str,
    slug: str,
    path: Path,
) -> None:
    existing = conn.execute(
        "SELECT id FROM taxonomy_nodes WHERE category = ? AND slug = ?;",
        (category, slug),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE taxonomy_nodes SET name = ?, path = ? WHERE id = ?;",
            (name, str(path.resolve()), int(existing["id"])),
        )
        return
    conn.execute(
        """
        INSERT INTO taxonomy_nodes (category, name, slug, path)
        VALUES (?, ?, ?, ?);
        """,
        (category, name, slug, str(path.resolve())),
    )
