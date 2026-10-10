from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import get_project_root
from . import load_progress
from .db import get_connection, library_connection

router = APIRouter(prefix="/api/skill-review", tags=["Skill Review"])


class FindRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    scientific_field: str = Field(default="", max_length=200)
    limit: int = Field(default=12, ge=1, le=25)
    min_citations: int = Field(default=0, ge=0, le=100000)
    from_year: int | None = Field(default=None, ge=1500, le=2100)
    pubmed_full_text_only: bool = Field(default=False)
    fresh_only: bool = Field(default=False)


def _root() -> Path:
    root = Path(
        str(
            __import__("os").environ.get("SENTINARI_SHARED_SKILLS_ROOT")
            or __import__("os").environ.get("SMI_SHARED_SKILLS_ROOT")
            or get_project_root() / "data" / "skills"
        )
    ).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _document_chunk_total(document_id: int) -> int:
    try:
        with library_connection("gemma") as conn:
            row = conn.execute("SELECT COUNT(1) AS n FROM chunks WHERE document_id = ?", (document_id,)).fetchone()
        return int(row["n"]) if row is not None else 0
    except Exception:
        return 0


def slugify_text(value: str) -> str:
    """Lightweight slug used only to build a stable placeholder URL."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:80] or "untitled"


def _pmid_from_url(url: str) -> str:
    m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", str(url or ""), re.I)
    return m.group(1) if m else ""


def _source_identity(source_type: str, source_url: str, metadata: dict[str, Any] | None, title: str = "") -> str:
    """Stable identity key for a candidate, so the same dataset arriving
    under different URLs (DOI link vs landing page vs PMC mirror; repo URL
    with/without trailing path; case differences) maps to ONE row.

    Identity choices:
      openalex    -> doi:<doi> when known, else openalex:<W-id>, else URL
      github      -> https://github.com/<owner>/<repo> (lowercased, trimmed)
      huggingface -> hf:<dataset id>
      other       -> normalized URL (scheme+host lowercased, trailing / and
                     common tracking fragments removed)
    """
    metadata = metadata if isinstance(metadata, dict) else {}
    stype = str(source_type or "").strip().lower()
    url = str(source_url or "").strip()

    def _norm_url(u: str) -> str:
        u = str(u or "").strip().lower()
        u = re.sub(r"^[a-z]+://", "", u)
        u = u.split("#", 1)[0].split("?", 1)[0]
        u = u.rstrip("/")
        return u

    if stype == "openalex":
        doi = str(metadata.get("doi") or "").strip().lower()
        if not doi:
            m = re.search(r"doi\.org/(10\.[^/?#]+(?:/[^/?#]+)*)", url, re.I)
            if m:
                doi = m.group(1).strip().lower().rstrip(".")
        if doi:
            return f"doi:{doi}"
        oa_id = str(metadata.get("openalex_id") or "").strip()
        if not oa_id:
            m = re.search(r"openalex\.org/(W\d+)", url, re.I)
            if m:
                oa_id = m.group(1).upper()
        if oa_id:
            return f"openalex:{oa_id.split('/')[-1].upper()}"
        return f"url:{_norm_url(url)}"

    if stype == "pubmed":
        # PubMed identity: PMID (canon), DOI (shared with OpenAlex), or PMC id.
        doi = str((metadata or {}).get("doi") or "").strip().lower()
        if not doi:
            m = re.search(r"doi\.org/(10\.[^/?#]+(?:/[^/?#]+)*)", url, re.I)
            if m:
                doi = m.group(1).strip().lower().rstrip(".")
        if doi:
            return f"doi:{doi}"  # Same DOI as an OpenAlex candidate = SAME paper, one row.
        m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url, re.I)
        if m:
            return f"pmid:{m.group(1)}"
        pmcid = str((metadata or {}).get("pmcid") or "").strip().upper()
        if pmcid:
            return f"pmc:{pmcid}"
        return f"url:{_norm_url(url)}"

    if stype == "github":
        m = re.search(r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", url, re.I)
        if m:
            owner, repo = m.group(1).lower(), re.sub(r"\.git$", "", m.group(2), flags=re.I).lower()
            return f"github:{owner}/{repo}"
        return f"url:{_norm_url(url)}"

    if stype == "huggingface":
        dataset = url.split("/datasets/")[1] if "/datasets/" in url else str(metadata.get("dataset") or "")
        dataset = dataset.strip("/").lower()
        if dataset:
            return f"hf:{dataset}"
        return f"url:{_norm_url(url)}"

    if stype == "oecd":
        agency = str(metadata.get("agency") or "oecd").lower()
        dataset = str(metadata.get("dataset") or "").lower()
        if dataset:
            return f"oecd:{agency}:{dataset}"
        return f"url:{_norm_url(url)}"

    key = _norm_url(url)
    return f"url:{key}" if key else f"title:{str(title or '').strip().lower()}"


def _ensure_schema() -> None:
    # Long write window + retries: this runs at first endpoint hit, possibly
    # during a startup digestion storm on the same database.
    for _attempt in range(6):
        try:
            _ensure_schema_once()
            return
        except sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower() or _attempt == 5:
                raise
            time.sleep(1.5)


def _ensure_schema_once() -> None:
    with get_connection() as conn:
        conn.execute("PRAGMA busy_timeout = 30000;")
        _ensure_schema_body(conn)


def _ensure_schema_body(conn: Any) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS skill_review_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                scientific_field TEXT NOT NULL DEFAULT '',
                target_persona TEXT NOT NULL DEFAULT 'gemma',
                license TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
                reviewed_at TEXT NOT NULL DEFAULT '',
                loaded_document_id INTEGER,
                loaded_title TEXT NOT NULL DEFAULT '',
                loaded_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_skill_review_status
                ON skill_review_candidates(status, discovered_at DESC);
            """
        )
        existing_cols = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(skill_review_candidates)").fetchall()
        }
        for column in ("loaded_document_id INTEGER", "loaded_title TEXT NOT NULL DEFAULT ''", "loaded_at TEXT NOT NULL DEFAULT ''"):
            name = column.split()[0]
            if name not in existing_cols:
                conn.execute(f"ALTER TABLE skill_review_candidates ADD COLUMN {column};")
        if "identity_key" not in existing_cols:
            conn.execute("ALTER TABLE skill_review_candidates ADD COLUMN identity_key TEXT NOT NULL DEFAULT '';")
        conn.commit()

        # One-time backfill: give legacy rows their identity key.
        needs_backfill = conn.execute(
            "SELECT COUNT(1) AS n FROM skill_review_candidates WHERE IFNULL(identity_key, '') = ''"
        ).fetchone()[0]
        if int(needs_backfill) > 0:
            rows = conn.execute(
                "SELECT id, source_type, source_url, title, metadata_json FROM skill_review_candidates"
                " WHERE IFNULL(identity_key, '') = ''"
            ).fetchall()
            for row in rows:
                try:
                    meta = json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else dict(row["metadata_json"] or {})
                except Exception:
                    meta = {}
                key = _source_identity(
                    str(row["source_type"] or ""),
                    str(row["source_url"] or ""),
                    meta if isinstance(meta, dict) else {},
                    str(row["title"] or ""),
                )
                conn.execute(
                    "UPDATE skill_review_candidates SET identity_key = ? WHERE id = ?",
                    (key, int(row["id"])),
                )
            conn.commit()

        # Collapse legacy duplicates among reviewable rows. Loaded and
        # rejected rows are never touched; within each identity keep the
        # most-advanced review status (approve > test > pending), oldest id
        # as tiebreak.
        conn.execute(
            """
            DELETE FROM skill_review_candidates
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY identity_key
                        ORDER BY CASE status WHEN 'approve' THEN 0 WHEN 'test' THEN 1 ELSE 2 END, id
                    ) AS rn
                    FROM skill_review_candidates
                    WHERE IFNULL(identity_key, '') != '' AND status IN ('pending','approve','test')
                ) WHERE rn > 1
            );
            """
        )
        conn.commit()
        # The safety net: one reviewable row per dataset identity, ever.
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_review_identity
                ON skill_review_candidates(identity_key)
                WHERE IFNULL(identity_key, '') != '' AND status IN ('pending','approve','test');
            """
        )
        conn.commit()

        # One-time upgrade: PubMed rows whose identity fell back to pmid:*
        # get their DOI identity (shared with OpenAlex) once top-level
        # metadata is available.
        pm_rows = conn.execute(
            "SELECT id, source_type, source_url, metadata_json FROM skill_review_candidates"
            " WHERE source_type = 'pubmed' AND identity_key LIKE 'pmid:%'"
        ).fetchall()
        for pm_row in pm_rows:
            try:
                pm_meta = json.loads(str(pm_row["metadata_json"] or "{}"))
            except Exception:
                pm_meta = {}
            # Legacy rows may carry the ids nested under _metadata (pre-flatten
            # storage); new rows have them at the top level.
            nested = pm_meta.get("_metadata") if isinstance(pm_meta.get("_metadata"), dict) else {}
            doi = str(pm_meta.get("doi") or nested.get("doi") or "").strip().lower()
            upgraded = f"doi:{doi}" if doi else ""
            if upgraded:
                conn.execute(
                    "UPDATE skill_review_candidates SET identity_key = ? WHERE id = ? AND identity_key LIKE 'pmid:%'",
                    (upgraded, int(pm_row["id"])),
                )
        if pm_rows:
            conn.commit()


class DiscoveryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    scientific_field: str = Field(default="", max_length=200)
    target_persona: str = Field(default="gemma", pattern="^(gemma)$")
    limit: int = Field(default=10, ge=1, le=25)


@router.get("/candidates")
def list_candidates(
    status: str = Query(default="pending"),
    scientific_field: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    """Stored candidates for the review panel, paginated (§76).

    OpenAlex rows sort first (owner directive), then newest discovery.
    ``total``/``pages`` let the UI draw page numbers covering ALL datasets
    found — not just the rows on this page.
    """
    _ensure_schema()
    field = scientific_field.strip().lower().replace(" ", "-")
    where = "status = ?"
    args: list[Any] = [status.strip() or "pending"]
    if field:
        where += " AND REPLACE(LOWER(scientific_field), ' ', '-') = ?"
        args.append(field)
    with get_connection() as conn:
        total = int(conn.execute(f"SELECT COUNT(1) AS n FROM skill_review_candidates WHERE {where}", args).fetchone()["n"])
        pages = max(1, (total + page_size - 1) // page_size)
        current = min(max(1, page), pages)
        rows = conn.execute(
            f"""
            SELECT * FROM skill_review_candidates
            WHERE {where}
            ORDER BY CASE LOWER(source_type) WHEN 'openalex' THEN 0 ELSE 1 END,
                     discovered_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*args, page_size, (current - 1) * page_size),
        ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if str(item.get("source_type") or "") == "pubmed":
            # Surface PubMed ids at the top level for the PMC availability pill.
            try:
                meta = json.loads(str(item.get("metadata_json") or "{}"))
            except Exception:
                meta = {}
            nested = meta.get("_metadata") if isinstance(meta.get("_metadata"), dict) else {}
            for k in ("pmid", "pmcid", "doi"):
                if not item.get(k):
                    item[k] = str(meta.get(k) or nested.get(k) or "")
            item["has_full_text"] = bool(item.get("pmcid"))
        candidates.append(item)
    return {
        "ok": True,
        "candidates": candidates,
        "total": total,
        "page": current,
        "page_size": page_size,
        "pages": pages,
    }


@router.get("/loaded-identities")
def loaded_identities() -> dict[str, Any]:
    """Identity keys of already-loaded datasets — powers the Already-loaded badge."""
    _ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT IFNULL(identity_key, '') AS k FROM skill_review_candidates WHERE status = 'loaded'"
        ).fetchall()
    keys = sorted({str(row["k"]) for row in rows if str(row["k"])})
    return {"ok": True, "identities": keys, "count": len(keys)}


@router.post("/candidates/clear")
def clear_candidates(
    scientific_field: str = Query(default=""),
) -> dict[str, Any]:
    """Remove review-lane candidates so a new science can be searched cleanly.

    Deletes pending / approved / rejected / tested candidates — optionally only
    those of one scientific field. LOADED datasets are never touched: they are
    permanently listed in their field's container.
    """
    _ensure_schema()
    field = scientific_field.strip().lower().replace(" ", "-")
    with get_connection() as conn:
        if field:
            counts = conn.execute(
                """
                SELECT status, COUNT(1) AS n FROM skill_review_candidates
                WHERE REPLACE(LOWER(scientific_field), ' ', '-') = ?
                  AND status IN ('pending', 'approve', 'reject', 'test')
                GROUP BY status
                """,
                (field,),
            ).fetchall()
            cur = conn.execute(
                """
                DELETE FROM skill_review_candidates
                WHERE REPLACE(LOWER(scientific_field), ' ', '-') = ?
                  AND status IN ('pending', 'approve', 'reject', 'test')
                """,
                (field,),
            )
        else:
            counts = conn.execute(
                """
                SELECT status, COUNT(1) AS n FROM skill_review_candidates
                WHERE status IN ('pending', 'approve', 'reject', 'test')
                GROUP BY status
                """,
            ).fetchall()
            cur = conn.execute(
                """
                DELETE FROM skill_review_candidates
                WHERE status IN ('pending', 'approve', 'reject', 'test')
                """
            )
        conn.commit()
        remaining = conn.execute("SELECT COUNT(1) AS n FROM skill_review_candidates").fetchone()["n"]
    deleted = int(cur.rowcount or 0)
    return {
        "ok": True,
        "deleted": deleted,
        "by_status": {str(row["status"]): int(row["n"]) for row in counts},
        "scientific_field": field,
        "remaining": int(remaining),
    }


@router.get("/loaded")
def list_loaded() -> dict[str, Any]:
    """Permanently listing datasets that were loaded + ingested, per field."""
    _ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, source_type, source_url, title, description,
                   scientific_field, license, loaded_at,
                   loaded_document_id, loaded_title, status
            FROM skill_review_candidates
            WHERE status = 'loaded'
            ORDER BY COALESCE(loaded_at, reviewed_at, discovered_at) DESC
            LIMIT 500
            """
        ).fetchall()
    loaded: list[dict[str, Any]] = []
    chunk_totals: dict[int, int] = {}
    doc_ids = [int(r["loaded_document_id"] or 0) for r in rows if r.get("loaded_document_id")]
    valid_ids = [d for d in doc_ids if d > 0]
    if valid_ids:
        try:
            with library_connection("gemma") as conn:
                id_list = ",".join(str(d) for d in set(valid_ids))
                counts = conn.execute(
                    f"SELECT document_id, COUNT(1) AS n FROM chunks WHERE document_id IN ({id_list}) GROUP BY document_id"
                ).fetchall()
                for c in counts:
                    chunk_totals[int(c["document_id"])] = int(c["n"])
        except Exception:
            pass
    for row in rows:
        item = dict(row)
        item["chunk_count"] = chunk_totals.get(int(row["loaded_document_id"] or 0), 0)
        loaded.append(item)
    return {"ok": True, "loaded": loaded}


def _candidate_document(candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the knowledge-library document a loaded candidate produced."""
    document_id = int(candidate.get("loaded_document_id") or 0)
    with library_connection("gemma") as conn:
        if document_id > 0:
            row = conn.execute(
                "SELECT id, title, source_type, source_path, source_url, scientific_field, authors, published_date FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if row is not None:
                return dict(row)
        # Fall back to matching on the stored title within the candidate's field.
        title = str(candidate.get("loaded_title") or candidate.get("title") or "").strip()
        field_slug = str(candidate.get("scientific_field") or "").strip()
        if title:
            row = conn.execute(
                "SELECT id, title, source_type, source_path, source_url, scientific_field, authors, published_date FROM documents WHERE title = ? ORDER BY id DESC LIMIT 1",
                (title,),
            ).fetchone()
            if row is not None:
                return dict(row)
    return None


@router.get("/candidates/{candidate_id}/preview")
def preview_candidate(candidate_id: int) -> dict[str, Any]:
    """HTML-ready preview of a candidate (loaded documents show real text)."""
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate = dict(row)
    doc = _candidate_document(candidate)
    if doc is not None:
        document_id = int(doc["id"])
        with library_connection("gemma") as conn:
            chunk_rows = conn.execute(
                "SELECT chunk_index, content FROM chunks WHERE document_id = ? ORDER BY chunk_index LIMIT 12",
                (document_id,),
            ).fetchall()
        chunks = [{"index": int(r["chunk_index"]), "text": str(r["content"] or "")[:2400]} for r in chunk_rows]
        total = _document_chunk_total(document_id)
        return {
            "ok": True,
            "ingested": True,
            "document": doc,
            "chunk_total": total,
            "preview_chunks": chunks,
            "truncated": total > len(chunks),
        }
    # Not ingested yet: preview the stored description so review still works.
    return {
        "ok": True,
        "ingested": False,
        "document": {
            "title": candidate.get("title"),
            "source_type": candidate.get("source_type"),
            "source_url": candidate.get("source_url"),
            "scientific_field": candidate.get("scientific_field"),
        },
        "preview_chunks": [{"index": 0, "text": str(candidate.get("description") or "No description stored.")[:2400]}],
        "chunk_total": 0,
        "truncated": False,
        "note": "Not ingested yet — this is the discovery description. Load the dataset to preview its full text.",
    }


@router.get("/candidates/{candidate_id}/download")
def download_candidate(candidate_id: int):
    """Download a candidate's stored artifact as .pdf (real PDF when we have one)."""
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate = dict(row)
    doc = _candidate_document(candidate)
    if doc is None:
        raise HTTPException(status_code=409, detail="This dataset has not been loaded yet. Load it first — download works after ingestion.")
    document_id = int(doc["id"])
    source_path = Path(str(doc.get("source_path") or ""))
    if source_path.suffix.lower() == ".pdf" and source_path.exists():
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(doc.get("title") or source_path.name))[:80] or "dataset"
        return FileResponse(path=str(source_path), media_type="application/pdf", filename=f"{safe_name}.pdf")
    with library_connection("gemma") as conn:
        rows = conn.execute(
            "SELECT content FROM chunks WHERE document_id = ? ORDER BY chunk_index",
            (document_id,),
        ).fetchall()
    text = "\n\n".join(str(r["content"] or "") for r in rows).strip()
    if not text:
        raise HTTPException(status_code=404, detail="No ingested text available to build a PDF.")
    from .text_pdf import text_to_pdf_response

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(doc.get("title") or "dataset"))[:80] or "dataset"
    return text_to_pdf_response(text, filename=f"{safe_name}.pdf", title=str(doc.get("title") or "SMi Sentinel Dataset"))


@router.get("/documents/{document_id}/preview")
def preview_document(document_id: int) -> dict[str, Any]:
    """HTML preview of a loaded dataset: text chunks rendered as HTML."""
    from html import escape

    with library_connection("gemma") as conn:
        doc = conn.execute(
            "SELECT id, title, source_type, source_path, source_url, scientific_field, authors, published_date FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found in the knowledge library.")
        chunk_rows = conn.execute(
            "SELECT chunk_index, content FROM chunks WHERE document_id = ? ORDER BY chunk_index LIMIT 12",
            (document_id,),
        ).fetchall()
    chunks = [
        {
            "index": int(row["chunk_index"]),
            "text": str(row["content"] or "")[:2400],
        }
        for row in chunk_rows
    ]
    return {
        "ok": True,
        "document": {
            "id": int(doc["id"]),
            "title": str(doc["title"] or "Untitled"),
            "source_type": str(doc["source_type"] or ""),
            "source_path": str(doc["source_path"] or ""),
            "source_url": str(doc["source_url"] or ""),
            "scientific_field": str(doc["scientific_field"] or ""),
            "authors": str(doc["authors"] or ""),
            "published_date": str(doc["published_date"] or ""),
        },
        "chunk_total": _document_chunk_total(document_id),
        "preview_chunks": chunks,
        "truncated": _document_chunk_total(document_id) > len(chunks),
    }


@router.get("/documents/{document_id}/download")
def download_document(document_id: int):
    """Download the stored dataset artifact as a real .pdf when available."""
    with library_connection("gemma") as conn:
        doc = conn.execute(
            "SELECT title, source_path, source_type FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found in the knowledge library.")
    source_path = Path(str(doc["source_path"] or ""))
    if source_path.suffix.lower() == ".pdf" and source_path.exists():
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(doc["title"] or source_path.name))[:80] or "dataset"
        return FileResponse(
            path=str(source_path),
            media_type="application/pdf",
            filename=f"{safe_name}.pdf",
        )
    # Non-PDF artifacts: convert the ingested text to a generated PDF.
    from .text_pdf import text_to_pdf_response

    with library_connection("gemma") as conn:
        rows = conn.execute(
            "SELECT content FROM chunks WHERE document_id = ? ORDER BY chunk_index",
            (document_id,),
        ).fetchall()
    text = "\n\n".join(str(row["content"] or "") for row in rows).strip()
    if not text:
        raise HTTPException(status_code=404, detail="No ingested text available to build a PDF.")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(doc["title"] or "dataset"))[:80] or "dataset"
    return text_to_pdf_response(text, filename=f"{safe_name}.pdf")


@router.post("/discover")
def discover_candidates(payload: DiscoveryRequest) -> dict[str, Any]:
    _ensure_schema()
    headers = {"User-Agent": "SMI-Skill-Review/1.0"}
    candidates: list[dict[str, Any]] = []

    hf = requests.get(
        "https://huggingface.co/api/datasets",
        params={"search": payload.query, "limit": payload.limit},
        headers=headers,
        timeout=30,
    )
    hf.raise_for_status()
    hf_items = hf.json()
    for item in hf_items if isinstance(hf_items, list) else []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        candidates.append(
            {
                "source_type": "huggingface",
                "source_url": f"https://huggingface.co/datasets/{item['id']}",
                "title": str(item["id"]),
                "description": str(item.get("description") or "")[:1000],
                "scientific_field": payload.scientific_field.strip(),
                "target_persona": payload.target_persona,
                "license": "",
            }
        )

    github = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": f"{payload.query} in:name,description", "per_page": payload.limit},
        headers=headers,
        timeout=30,
    )
    github.raise_for_status()
    github_items = github.json().get("items", []) if isinstance(github.json(), dict) else []
    for item in github_items:
        if not isinstance(item, dict) or not item.get("html_url"):
            continue
        license_data = item.get("license")
        candidates.append(
            {
                "source_type": "github",
                "source_url": str(item["html_url"]),
                "title": str(item.get("full_name") or item.get("name") or "Repository"),
                "description": str(item.get("description") or "")[:1000],
                "scientific_field": payload.scientific_field.strip(),
                "target_persona": payload.target_persona,
                "license": str(license_data.get("spdx_id") or "") if isinstance(license_data, dict) else "",
            }
        )

    with get_connection() as conn:
        duplicates = 0
        for item in candidates:
            identity = _source_identity(
                str(item.get("source_type") or ""),
                str(item.get("source_url") or ""),
                item,
                str(item.get("title") or ""),
            )
            already = conn.execute(
                "SELECT status FROM skill_review_candidates WHERE identity_key = ?",
                (identity,),
            ).fetchone() if identity else None
            if already is not None and str(already["status"]) in ("loaded", "reject"):
                # Owner directive (§34): loaded datasets must never re-enter
                # the review lineup through any write lane.
                duplicates += 1
                continue
            try:
                conn.execute(
                    """
                    INSERT INTO skill_review_candidates
                        (source_type, source_url, title, description, scientific_field,
                         target_persona, license, metadata_json, identity_key, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    ON CONFLICT(identity_key) WHERE IFNULL(identity_key, '') != ''
                         AND status IN ('pending','approve','test')
                    DO UPDATE SET
                        description = excluded.description,
                        scientific_field = excluded.scientific_field,
                        target_persona = excluded.target_persona,
                        license = excluded.license
                    """,
                    (
                        item["source_type"],
                        item["source_url"],
                        item["title"],
                        item["description"],
                        item["scientific_field"],
                        item["target_persona"],
                        item["license"],
                        json.dumps({"query": payload.query}, ensure_ascii=True),
                        identity,
                    ),
                )
            except sqlite3.IntegrityError:
                duplicates += 1
        conn.commit()
    return {"ok": True, "discovered": len(candidates), "duplicates_skipped": duplicates, "review_required": True}


def _novelty_rank(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Owner directive (§35): rank candidates by novelty against the whole
    library — most-cited first, recency breaking ties, open access / PMC
    full text as a light bonus. Candidates arriving here are already free
    of loaded / rejected / duplicate identities (the §34 sweep), so what
    remains IS the fresh set; this orders it for discovery value."""
    from datetime import datetime, timezone

    try:
        current_year = datetime.now(timezone.utc).year
    except Exception:
        current_year = 2026

    def _score(c: dict[str, Any]) -> float:
        try:
            citations = int(c.get("cited_by_count") or 0)
        except Exception:
            citations = 0
        year = 0
        for key in ("year", "publication_year"):
            try:
                if c.get(key):
                    year = int(c[key])
                    break
            except Exception:
                pass
        # The §22 window (last ~7 years) earns a full recency bonus ordered
        # newest-first; older works decay to a floor of zero.
        recency = max(0, (year - (current_year - 7)) * 5) if year else 0
        oa_bonus = 2.0 if (c.get("is_oa") or c.get("has_full_text")) else 0.0
        return float(citations) + float(recency) + oa_bonus

    return sorted(candidates, key=_score, reverse=True)


# ---------------------------------------------------------------------------
# §74n — Whole-string precision law (owner directive).
#
# A sourcing search must honor the ENTIRE search string. Before this law the
# lanes broadened freely: "Linux Ubuntu LTS for Beginners" came back drowned
# in field-wide noise ("everything from the Ubuntu Culture and whatever")
# because providers do token-OR matching and the OpenAlex lane re-sorted by
# citation count, floating field heavyweights above topical matches.
#
# Every source lane flows through the single chokepoint in ``find_candidates``
# below, where candidates that do not carry the whole string are dropped —
# narrowed, never broadened.
# ---------------------------------------------------------------------------
_PHRASE_STOPWORDS = frozenset(
    {"for", "the", "and", "of", "a", "an", "to", "in", "with", "on", "by", "at", "from"}
)


def _precision_terms(query: str) -> list[str]:
    """Content words of the search string (stopwords dropped for matching)."""
    tokens = re.findall(r"[a-z0-9]+", str(query or "").lower())
    content = [t for t in tokens if t not in _PHRASE_STOPWORDS]
    return content or tokens


def _normalize_for_match(text: str) -> str:
    """Lowercase, drop punctuation/stopwords, collapse whitespace — so
    'linux-ubuntu-LTS for beginners' and 'Linux Ubuntu LTS for Beginners'
    compare equal."""
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return " ".join(t for t in tokens if t not in _PHRASE_STOPWORDS)


def _precision_score(candidate: dict[str, Any], terms: list[str], phrase: str) -> tuple[int, int]:
    """Return (tier, hits) against title + description + abstract.

    Tier 0 = the entire phrase present in order (slug forms count — dashes
    normalize away). Tier 1 = every content word present. Tier 2 = all but
    one. Anything weaker is field-level dilution and gets dropped.
    """
    haystack = _normalize_for_match(
        f"{candidate.get('title') or ''} {candidate.get('description') or ''} {candidate.get('abstract') or ''}"
    )
    hits = sum(1 for t in terms if t in haystack)
    if phrase and phrase in haystack:
        return 0, hits
    if terms and hits >= len(terms):
        return 1, hits
    if terms and hits >= max(1, len(terms) - 1):
        return 2, hits
    return 3, hits


@router.post("/find")
def find_candidates(payload: FindRequest) -> dict[str, Any]:
    """Search GitHub, Hugging Face, and OpenAlex at the same time.

    Every candidate found is stored server-side (status='pending') so the
    lineup survives page refreshes, and the stored rows (with their DB ids)
    are returned for Approve / Reject / Test / Load / Preview / Download.
    """
    _ensure_schema()
    headers = {"User-Agent": "SMI-Skill-Review/1.0"}
    query = payload.query.strip()
    field_text = payload.scientific_field.strip()
   
    def _github_search() -> list[dict[str, Any]]:
        try:
            resp = requests.get(
                "https://api.github.com/search/repositories",
                params={"q": f"{query} in:name,description", "per_page": payload.limit, "sort": "best-match"},
                headers=headers,
                timeout=25,
            )
            if resp.status_code != 200:
                return []
            items = resp.json().get("items", []) if isinstance(resp.json(), dict) else []
            out: list[dict[str, Any]] = []
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict) or not item.get("html_url"):
                    continue
                license_data = item.get("license")
                out.append(
                    {
                        "source_type": "github",
                        "source_url": str(item["html_url"]),
                        "title": str(item.get("full_name") or item.get("name") or "Repository"),
                        "description": str(item.get("description") or "")[:1000],
                        "scientific_field": field_text,
                        "target_persona": "gemma",
                        "license": str(license_data.get("spdx_id") or "") if isinstance(license_data, dict) else "",
                        "stars": int(item.get("stargazers_count") or 0),
                    }
                )
            return out
        except Exception:
            return []

    def _huggingface_search() -> list[dict[str, Any]]:
        try:
            resp = requests.get(
                "https://huggingface.co/api/datasets",
                params={"search": query, "limit": payload.limit, "full": "false"},
                headers=headers,
                timeout=25,
            )
            if resp.status_code != 200:
                return []
            items = resp.json()
            out = []
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                out.append(
                    {
                        "source_type": "huggingface",
                        "source_url": f"https://huggingface.co/datasets/{item['id']}",
                        "title": str(item["id"]),
                        "description": str(item.get("description") or item.get("cardData", {}).get("pretty_name") or "")[:1000],
                        "scientific_field": field_text,
                        "target_persona": "gemma",
                        "license": "",
                        "downloads": int(item.get("downloads") or 0),
                    }
                )
            return out
        except Exception:
            return []

    def _openalex_search() -> list[dict[str, Any]]:
        try:
            from .openalex_worker import search_openalex_works

            result = search_openalex_works(
                query,
                field=field_text,
                limit=payload.limit,
                min_citations=payload.min_citations,
                from_year=payload.from_year,
            )
            return list(result.get("candidates") or [])
        except Exception:
            return []

    def _pubmed_search() -> list[dict[str, Any]]:
        # Medical-fields gate runs first — no point opening a lane that must
        # return nothing.
        try:
            from .pubmed_worker import pubmed_field_allowed, search_pubmed_papers

            if not pubmed_field_allowed(field_text):
                return []
            result = search_pubmed_papers(
                query,
                field=field_text,
                limit=payload.limit,
                from_year=payload.from_year,
                full_text_only=bool(payload.pubmed_full_text_only),
            )
            if not result.get("ok"):
                return []
            return list(result.get("candidates") or [])
        except Exception:
            return []

    def _worldbank_search() -> list[dict[str, Any]]:
        # §74k — the Finance Industry challenge: World Bank / IMF / OECD
        # official time-series datasets via the public DBnomics REST API.
        # One candidate = one whole dataset; the load slices it by query.
        try:
            from .worldbank_worker import search_dbnomics_datasets

            result = search_dbnomics_datasets(query, field=field_text, limit=max(2, min(10, payload.limit)))
            return list(result.get("candidates") or [])
        except Exception:
            return []

    def _oecd_search() -> list[dict[str, Any]]:
        # Official OECD SDMX REST API statistical dataflows.
        try:
            from .oecd_worker import search_oecd_datasets

            result = search_oecd_datasets(query, field=field_text, limit=max(2, min(10, payload.limit)))
            return list(result.get("candidates") or [])
        except Exception:
            return []

    # All sources at the same time. A shared deadline keeps one slow lane
    # (OpenAlex and NCBI can crawl) from holding the whole search hostage —
    # whichever lanes have answered when the deadline passes are what's shown.
    # The pool is shut down WITHOUT waiting: a lane still running past the
    # deadline keeps its thread but must not block the response.
    import time as _search_time

    _search_deadline = _search_time.monotonic() + 75.0

    def _lane_result(future: Any) -> list[dict[str, Any]]:
        remaining = _search_deadline - _search_time.monotonic()
        try:
            return list(future.result(timeout=max(1.0, remaining)) or [])
        except Exception:
            return []

    pool = ThreadPoolExecutor(max_workers=6)
    try:
        github_future = pool.submit(_github_search)
        hf_future = pool.submit(_huggingface_search)
        openalex_future = pool.submit(_openalex_search)
        pubmed_future = pool.submit(_pubmed_search)
        worldbank_future = pool.submit(_worldbank_search)
        oecd_future = pool.submit(_oecd_search)
        candidates = [
            *_lane_result(github_future),
            *_lane_result(hf_future),
            *_lane_result(openalex_future),
            *_lane_result(pubmed_future),
            *_lane_result(worldbank_future),
            *_lane_result(oecd_future),
        ]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # Owner directive: rejected datasets must never reappear in later searches.
    # The persisted identity cache is loaded here and applied after the
    # normalization loop below (identities don't exist until then).
    try:
        from .pattern_store import rejected_identities as _rejected_identities

        _rejected = set(_rejected_identities())
    except Exception:
        _rejected = set()

    # Normalize the unique key every source needs before storage.
    for item in candidates:
        # Flatten PubMed's nested metadata (pmid/pmcid/doi) to the top level so
        # identity resolution and the load lane see them directly.
        extra = item.get("_metadata") if isinstance(item.get("_metadata"), dict) else {}
        for k in ("pmid", "pmcid", "doi"):
            if extra.get(k) and not item.get(k):
                item[k] = str(extra[k])
        item.pop("_metadata", None)
        source_url = str(item.get("source_url") or "").strip()
        if not source_url and str(item.get("source_type") or "") == "openalex":
            source_url = str(
                item.get("landing_page_url")
                or (f"https://doi.org/{item['doi']}" if item.get("doi") else "")
                or item.get("openalex_id")
                or f"openalex:{slugify_text(item.get('title') or 'work')}"
            ).strip()
            item["source_url"] = source_url
        item.setdefault("source_url", source_url)
        item["_identity"] = _source_identity(
            str(item.get("source_type") or ""),
            str(item.get("source_url") or ""),
            item if isinstance(item, dict) else {},
            str(item.get("title") or ""),
        )

    # In-batch dedupe: the same work can appear twice in one search response
    # (e.g. DOI and landing-page variants); keep the first occurrence. This
    # is also where the rejected-identity cache is enforced — identities
    # exist by now, so a rejected work is dropped before it can be stored.
    unique_candidates: list[dict[str, Any]] = []
    seen_identities: set[str] = set()
    duplicate_count = 0
    for item in candidates:
        identity = str(item.get("_identity") or "")
        if identity and identity in seen_identities:
            duplicate_count += 1
            continue
        if identity and identity in _rejected:
            duplicate_count += 1
            continue
        if identity:
            seen_identities.add(identity)
        unique_candidates.append(item)

    stored_ids: dict[str, int] = {}
    loaded_skipped = 0
    with get_connection() as conn:
        # The DB is the second layer of the rejected-never-returns guarantee:
        # any legacy rows still carrying status='reject' are skipped too.
        _known_rejected = _rejected | {
            str(r["identity_key"])
            for r in conn.execute(
                "SELECT identity_key FROM skill_review_candidates WHERE status = 'reject' AND identity_key IS NOT NULL AND identity_key != ''"
            ).fetchall()
        }
        for item in unique_candidates:
            identity = str(item.get("_identity") or "")
            if identity and identity in _known_rejected:
                duplicate_count += 1
                continue
            existing = conn.execute(
                "SELECT id, status FROM skill_review_candidates WHERE identity_key = ?",
                (identity,),
            ).fetchone() if identity else None
            if existing is not None:
                item["id"] = int(existing["id"])
                item["already_loaded"] = str(existing["status"]) == "loaded"
                item["previously_rejected"] = str(existing["status"]) == "reject"
                if str(existing["status"]) in ("pending", "approve", "test"):
                    conn.execute(
                        "UPDATE skill_review_candidates SET description = ?, scientific_field = ?, license = ?, metadata_json = ? WHERE id = ?",
                        (
                            str(item.get("description") or item.get("abstract") or "")[:1000],
                            field_text,
                            str(item.get("license") or ""),
                            json.dumps(item, ensure_ascii=True)[:6000],
                            int(existing["id"]),
                        ),
                    )
                else:
                    # Loaded or rejected: never resurrect. (Owner directive,
                    # §34: loaded datasets are additionally dropped from the
                    # visible lineup by the final sweep below, so fresh
                    # searches surface only genuinely new material.)
                    duplicate_count += 1
                continue
            try:
                cur = conn.execute(
                    """
                    INSERT INTO skill_review_candidates
                        (source_type, source_url, title, description, scientific_field,
                         target_persona, license, metadata_json, identity_key, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        str(item.get("source_type") or "github"),
                        str(item.get("source_url") or ""),
                        str(item.get("title") or "Untitled candidate"),
                        str(item.get("description") or item.get("abstract") or "")[:1000],
                        field_text,
                        "gemma",
                        str(item.get("license") or ""),
                        json.dumps(item, ensure_ascii=True)[:6000],
                        identity,
                    ),
                )
                # Attach the new row id so the response's cards carry working
                # Approve / Reject / Load buttons without a page refresh.
                item["id"] = int(cur.lastrowid or 0)
                item["already_loaded"] = False
                item["previously_rejected"] = False
            except sqlite3.IntegrityError:
                duplicate_count += 1
                row = conn.execute(
                    "SELECT id, status FROM skill_review_candidates WHERE identity_key = ?",
                    (identity,),
                ).fetchone()
                if row is not None:
                    item["id"] = int(row["id"])
                    item["already_loaded"] = str(row["status"]) == "loaded"
        conn.commit()
    candidates = unique_candidates

    # Owner directive (§34): datasets already loaded + parsed into the
    # library must not reappear in fresh searches — they crowd out new
    # discoveries. The storage loop above already refuses to resurrect
    # them; this final sweep drops any that slip through, so the lineup
    # contains only genuinely new material.
    visible: list[dict[str, Any]] = []
    for item in candidates:
        if item.get("already_loaded") is True:
            loaded_skipped += 1
            continue
        visible.append(item)
    candidates = visible

    # §74n — whole-string precision gate. Candidates must carry the ENTIRE
    # search string: every content word (the exact phrase ranks first). A
    # single missing word is tolerated only on wide searches (3+ terms);
    # anything looser is the field-broadening the owner outlawed. Narrowed
    # here, at the one chokepoint every lane flows through.
    terms = _precision_terms(query)
    phrase = _normalize_for_match(query)
    scored: list[dict[str, Any]] = []
    precision_dropped = 0
    for item in candidates:
        if str(item.get("source_type") or "").lower() in {"worldbank", "oecd"}:
            # §76 World Bank / OECD exemption (official statistics catalogue entries)
            # must be listed): DBnomics rows are official-statistics catalogue
            # entries — their identifiers and descriptions ("OECD/DSD_…") can
            # never carry a scientific free-text query, so the whole-string
            # law structurally dropped 100% of that lane. The lane's own
            # DBnomics search already scoped them to the query; keep them.
            item["_precision_tier"] = 0
            item["_precision_hits"] = len(terms)
            scored.append(item)
            continue
        tier, hits = _precision_score(item, terms, phrase)
        item["_precision_tier"] = tier
        item["_precision_hits"] = hits
        if hits >= len(terms) - (0 if len(terms) <= 2 else 1):
            scored.append(item)
        else:
            precision_dropped += 1
    candidates = scored

    if payload.fresh_only:
        # Owner directive (§35): Fresh-discoveries mode — novelty (citations,
        # recency) now orders candidates INSIDE each precision tier, so a
        # field heavyweight can never float above a whole-string match.
        ranked: list[dict[str, Any]] = []
        for tier in sorted({int(c.get("_precision_tier") or 0) for c in candidates}):
            ranked.extend(_novelty_rank([c for c in candidates if int(c.get("_precision_tier") or 0) == tier]))
        candidates = ranked
    else:
        # Default mode: precision tier leads; the stable sort preserves each
        # lane's own relevance order within a tier.
        candidates.sort(key=lambda c: int(c.get("_precision_tier") or 0))
    # Owner directive (§76): OpenAlex is the primary R&D source — its
    # datasets are listed FIRST, ahead of every other lane. Stable sort, so
    # precision/novelty order inside each group is preserved.
    candidates.sort(key=lambda c: 0 if str(c.get("source_type") or "").lower() == "openalex" else 1)
    for item in candidates:
        item.pop("_precision_tier", None)
        item.pop("_precision_hits", None)

    return {
        "ok": True,
        "query": query,
        "field": field_text,
        "fresh_only": bool(payload.fresh_only),
        "count": len(candidates),
        "duplicates_skipped": duplicate_count,
        "loaded_skipped": loaded_skipped,
        "precision": {
            "mode": "whole-string",
            "terms": terms,
            "kept": len(candidates),
            "dropped_imprecise": precision_dropped,
            "note": (
                ""
                if candidates
                else "No candidate carried the entire search string — precision kept nothing rather than diluting into the field."
            ),
        },
        "github_count": sum(1 for c in candidates if c["source_type"] == "github"),
        "huggingface_count": sum(1 for c in candidates if c["source_type"] == "huggingface"),
        "openalex_count": sum(1 for c in candidates if c["source_type"] == "openalex"),
        "pubmed_count": sum(1 for c in candidates if c["source_type"] == "pubmed"),
        "worldbank_count": sum(1 for c in candidates if c["source_type"] == "worldbank"),
        "oecd_count": sum(1 for c in candidates if c["source_type"] == "oecd"),
        "pubmed_fulltext_count": sum(
            1 for c in candidates
            if c.get("source_type") == "pubmed" and (c.get("has_full_text") or str(c.get("pmcid") or ""))
        ),
        "candidates": candidates,
        "review_required": True,
    }


@router.post("/candidates/save")
def save_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    """Store review-picked OpenAlex works (or HF/GitHub datasets) as candidates."""
    _ensure_schema()
    items = payload.get("candidates")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Provide a candidates list to store.")
    scientific_field = str(payload.get("scientific_field") or "").strip()
    saved = 0
    duplicates = 0
    with get_connection() as conn:
        for item in items:
            if not isinstance(item, dict):
                continue
            source_url = str(item.get("source_url") or item.get("openalex_id") or item.get("landing_page_url") or "").strip()
            if not source_url:
                continue
            title = str(item.get("title") or "Untitled candidate")
            identity = _source_identity(
                str(item.get("source_type") or "openalex"),
                source_url,
                item if isinstance(item, dict) else {},
                title,
            )
            already = conn.execute(
                "SELECT status FROM skill_review_candidates WHERE identity_key = ?",
                (identity,),
            ).fetchone() if identity else None
            if already is not None and str(already["status"]) in ("loaded", "reject"):
                # Owner directive (§34): loaded datasets must never re-enter
                # the review lineup through any write lane.
                duplicates += 1
                continue
            try:
                conn.execute(
                    """
                    INSERT INTO skill_review_candidates
                        (source_type, source_url, title, description, scientific_field,
                         target_persona, license, metadata_json, identity_key, status)
                    VALUES (?, ?, ?, ?, ?, 'gemma', ?, ?, ?, 'pending')
                    ON CONFLICT(identity_key) WHERE IFNULL(identity_key, '') != ''
                         AND status IN ('pending','approve','test')
                    DO UPDATE SET
                        description = excluded.description,
                        scientific_field = excluded.scientific_field
                    """,
                    (
                        str(item.get("source_type") or "openalex"),
                        source_url,
                        title,
                        str(item.get("abstract") or item.get("description") or "")[:1000],
                        scientific_field,
                        str(item.get("license") or ""),
                        json.dumps(item, ensure_ascii=True)[:4000],
                        identity,
                    ),
                )
            except sqlite3.IntegrityError:
                duplicates += 1
                continue
            saved += 1
        conn.commit()
    return {"ok": True, "saved": saved, "duplicates_skipped": duplicates, "review_required": True}


@router.post("/candidates/{candidate_id}/ingest")
def ingest_candidate(candidate_id: int, wait: int = Query(default=0, ge=0, le=1)) -> dict[str, Any]:
    """Download + digest a stored candidate into its scientific field.

    Works for any source_type: OpenAlex works (PDF/landing-page/record),
    GitHub repos, and Hugging Face datasets. Works straight from the stored
    candidate row — no client-side save/re-lookup dance is needed.
    """
    from .openalex_worker import load_openalex_works_into_field
    from .sentinel_domains import ingest_github_dataset_to_field, ingest_huggingface_dataset_to_field

    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate = dict(row)

    if not wait:
        # Owner directive: loads run through the sequential background queue —
        # one at a time, never overlapping, each with live per-job progress.
        from .load_queue import get_load_queue

        try:
            entry = get_load_queue().enqueue(candidate)
        except ValueError as ex:
            raise HTTPException(status_code=409, detail=str(ex))
        return {
            "ok": True,
            "queued": True,
            "async": True,
            "entry_id": entry.get("entry_id"),
            "position": entry.get("position"),
            "already_queued": bool(entry.get("already_queued")),
        }
    return _ingest_candidate_impl(candidate_id, None)


def _ingest_with_lock_armor(candidate_id: int, rep: Any) -> dict[str, Any]:
    """Run one candidate load, riding out transient 'database is locked'
    storms (§74j owner complaint): calm progress message, backoff, retry —
    the load completes without the owner ever re-clicking Load.

    Shared by the legacy worker AND the sequential load queue, so every
    load path is armored identically. Must be called inside an active
    load_progress.bind(rep) context so the calm message reaches the UI.
    """
    import sqlite3 as _sqlite3
    import time as _time

    result: dict[str, Any] | None = None
    for attempt in range(3):
        try:
            result = _ingest_candidate_impl(candidate_id, rep)
            break
        except _sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower() or attempt >= 2:
                raise
            wait_s = 8 * (attempt + 1)
            load_progress.stage(
                "finalize",
                f"Library busy — waiting {wait_s}s for the lock to clear "
                f"and retrying (attempt {attempt + 2} of 3). "
                "Your download is queued and safe; no action needed.",
            )
            _time.sleep(wait_s)
    return result or {"ok": False, "error": "load produced no result"}


def _ingest_candidate_worker(candidate_id: int, job_id: str) -> None:
    """Run the load in this background thread with progress bound."""
    _rep = load_progress.job_reporter(job_id)
    try:
        with load_progress.bind(_rep):
            result = _ingest_with_lock_armor(candidate_id, _rep)
        load_progress.finish_job(job_id, result)
    except load_progress.LoadCancelled as ex:
        load_progress.error_job(job_id, str(ex) or "Cancelled by owner.")
    except HTTPException as ex:
        load_progress.error_job(job_id, str(ex.detail or ex))
    except Exception as ex:
        load_progress.error_job(job_id, str(ex) or ex.__class__.__name__)


def _resolve_target_field(candidate_id: int, candidate: dict[str, Any], metadata: dict[str, Any]) -> tuple[str, str]:
    """Resolve the target field, healing old rows that stored the field's
    detail string (e.g. "quantum, relativity, thermodynamics, particle
    physics") instead of the slug — that mismatch caused the historic
    "Unknown Sentinel scientific field" error."""
    from .sentinel_domains import resolve_field_loose, slugify

    field_text = str(candidate.get("scientific_field") or "").strip()
    try:
        field_slug = str(metadata.get("field_slug") or "").strip() or resolve_field_loose(field_text)
    except ValueError:
        field_slug = slugify(field_text)
    field = field_slug or field_text
    if not field:
        raise HTTPException(status_code=400, detail="Candidate has no scientific field set.")
    if field_slug and field_text and field_slug != field_text:
        try:
            with get_connection() as heal_conn:
                heal_conn.execute(
                    "UPDATE skill_review_candidates SET scientific_field = ? WHERE id = ?",
                    (field_slug, candidate_id),
                )
                heal_conn.commit()
        except Exception:
            pass
    return field, field_slug


def _ingest_candidate_impl(candidate_id: int, rep: Any) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    candidate = dict(row)
    from .openalex_worker import load_openalex_works_into_field
    from .sentinel_domains import (
        ingest_github_dataset_to_field,
        ingest_huggingface_dataset_to_field,
        slugify,
    )

    metadata_raw = candidate.get("metadata_json") or "{}"
    try:
        metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else dict(metadata_raw or {})
    except Exception:
        metadata = {}
    # Legacy PubMed rows carry the ids nested under _metadata; accept both
    # shapes so the load lane always sees pmid/pmcid/doi.
    nested_meta = metadata.get("_metadata") if isinstance(metadata.get("_metadata"), dict) else {}
    for _k in ("pmid", "pmcid", "doi"):
        if not metadata.get(_k) and nested_meta.get(_k):
            metadata[_k] = str(nested_meta[_k])
    source_type = str(candidate.get("source_type") or "").strip().lower()

    field, field_slug = _resolve_target_field(candidate_id, candidate, metadata)
    _SOURCE_LABELS = {
        "github": "GitHub",
        "huggingface": "Hugging Face",
        "openalex": "OpenAlex",
        "pubmed": "PubMed",
        "worldbank": "World Bank (DBnomics)",
        "oecd": "OECD (Official Statistics)",
    }
    _source_label = _SOURCE_LABELS.get(source_type, source_type or "the source")
    load_progress.emit_meta(
        field=field_slug,
        source_type=source_type,
        title=str(candidate.get("title") or ""),
        label=f"Load {_source_label} candidate {candidate_id}",
    )
    load_progress.stage(
        "download",
        f'Downloading "{str(candidate.get("title") or "candidate")[:60]}" from {_source_label}...',
    )

    result: dict[str, Any]
    if source_type == "github":
        load_progress.stage("download", f"Fetching repository files from GitHub for {field_slug}...")
        result = ingest_github_dataset_to_field(field, [str(candidate.get("source_url") or "")], max_files_per_repo=200, max_total_mb=300)
        result["source_type"] = "github"
    elif source_type == "huggingface":
        source_url = str(candidate.get("source_url") or "")
        dataset = source_url.split("/datasets/")[1] if "/datasets/" in source_url else str(metadata.get("dataset") or candidate.get("title") or "")
        result = ingest_huggingface_dataset_to_field(field, dataset.strip("/"), config_name="default", split="train", rows=50)
        result["source_type"] = "huggingface"
    elif source_type == "pubmed":
        load_progress.stage("download", "Fetching the paper from PubMed Central (open access) or PubMed...")
        from .pubmed_worker import load_pubmed_papers_into_field

        result = load_pubmed_papers_into_field(
            field,
            [
                {
                    "pmid": str(metadata.get("pmid") or _pmid_from_url(str(candidate.get("source_url") or ""))),
                    "pmcid": str(metadata.get("pmcid") or ""),
                    "title": str(candidate.get("title") or ""),
                }
            ],
            max_papers=1,
        )
        result["source_type"] = "pubmed"
    elif source_type == "worldbank":
        # §74k — DBnomics/World Bank time-series lane: slice the dataset by
        # the owner's discovery query and digest one readable factbook.
        load_progress.stage("download", "Fetching the dataset slice from DBnomics (World Bank, IMF, OECD, ECB)...")
        from .worldbank_worker import load_dbnomics_dataset_into_field

        result = load_dbnomics_dataset_into_field(
            field,
            {
                "provider": str(metadata.get("provider") or "WB"),
                "dataset": str(metadata.get("dataset") or ""),
                "query": str(metadata.get("query") or ""),
            },
        )
        result["source_type"] = "worldbank"
    elif source_type == "oecd":
        load_progress.stage("download", "Fetching OECD SDMX observations and structure...")
        from .oecd_worker import load_oecd_dataset_into_field

        result = load_oecd_dataset_into_field(
            field,
            {
                "agency": str(metadata.get("agency") or "OECD"),
                "dataset": str(metadata.get("dataset") or ""),
                "version": str(metadata.get("version") or "1.0"),
                "query": str(metadata.get("query") or ""),
            },
        )
        result["source_type"] = "oecd"
    else:
        load_progress.stage("download", "Fetching the work from OpenAlex (PDF, landing page, or record)...")
        work = {
            "openalex_id": str(metadata.get("openalex_id") or ""),
            "title": candidate.get("title"),
            "pdf_url": str(metadata.get("pdf_url") or ""),
            "landing_page_url": str(metadata.get("landing_page_url") or ""),
        }
        result = load_openalex_works_into_field(field, [work], max_works=1)
        result["source_type"] = "openalex"

    # Persist the outcome on the candidate and link the stored document(s).
    load_progress.stage("finalize", "Recording the loaded dataset in the field...")
    ingested = int(result.get("ingested") or 0)
    document_ids: list[int] = []
    document_titles: list[str] = []
    for item in result.get("items") or []:
        if isinstance(item, dict) and item.get("ok") and int(item.get("document_id") or 0) > 0:
            document_ids.append(int(item["document_id"]))
            if item.get("title"):
                document_titles.append(str(item["title"]))
    loaded_ok = ingested > 0
    if loaded_ok and not document_ids:
        # GitHub/HF lanes report repo-level summaries without per-file ids;
        # link one document from this batch by its stored path pattern.
        like_patterns: list[str] = []
        if source_type == "github":
            match = re.search(r"github\.com[/:]([^/]+)/([^/#?]+)", str(candidate.get("source_url") or ""))
            if match:
                folder = slugify(f"{match.group(1)}-{match.group(2)}")
                like_patterns = [f"%github/{folder}%", f"%github\\{folder}%"]
        elif source_type == "huggingface":
            source_url = str(candidate.get("source_url") or "")
            dataset = source_url.split("/datasets/")[1] if "/datasets/" in source_url else str(candidate.get("title") or "")
            like_patterns = [f"%hf-{slugify(dataset.strip('/'))}%"]
        elif source_type == "pubmed":
            pmid = str(metadata.get("pmid") or _pmid_from_url(str(candidate.get("source_url") or "")))
            if pmid:
                like_patterns = [f"%pm{slugify(pmid)}%"]
        elif source_type == "oecd":
            dataset = str(metadata.get("dataset") or "")
            if dataset:
                like_patterns = [f"%oecd-{slugify(dataset)}%"]
        try:
            if like_patterns:
                with library_connection("gemma") as conn:
                    for pattern in like_patterns:
                        row = conn.execute(
                            "SELECT id, title FROM documents WHERE scientific_field = ? AND source_path LIKE ? ORDER BY id DESC LIMIT 1",
                            (field_slug, pattern),
                        ).fetchone()
                        if row is not None:
                            document_ids = [int(row["id"])]
                            document_titles = [str(row["title"] or "")]
                            break
        except Exception:
            pass
    update_error: Exception | None = None
    import sqlite3 as _sqlite3
    import time as _time

    from .config import get_settings
    from .db import _db_path

    for _attempt in range(20):
        try:
            # A direct connection with a generous busy timeout: the live app
            # writes in bursts, so the plain 1 s timeout is often not enough.
            with _sqlite3.connect(str(_db_path()), timeout=15.0) as conn:
                conn.row_factory = _sqlite3.Row
                conn.execute(
                    """
                    UPDATE skill_review_candidates
                    SET status = ?, reviewed_at = datetime('now'),
                        loaded_document_id = ?, loaded_title = ?, loaded_at = CASE WHEN ? > 0 THEN datetime('now') ELSE loaded_at END
                    WHERE id = ?
                    """,
                    (
                        "loaded" if loaded_ok else "failed",
                        document_ids[0] if document_ids else None,
                        (document_titles[0] if document_titles else (str(candidate.get("title") or "") or result.get("field") or "")),
                        1 if loaded_ok else 0,
                        candidate_id,
                    ),
                )
                conn.commit()
            update_error = None
            break
        except _sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower():
                raise
            update_error = ex
            _time.sleep(0.5)
    if update_error is not None:
        raise update_error
    if not loaded_ok:
        # Owner directive: a failed load must leave NOTHING behind — partial
        # documents/chunks are purged from the field's library, and the
        # dataset is recorded as rejected so it can never reappear in a
        # future search or be re-loaded in this broken state.
        try:
            from .sentinel_domains import purge_field_documents

            attempt_doc_ids = [
                int(item.get("document_id"))
                for item in (result.get("items") or [])
                if isinstance(item, dict) and int(item.get("document_id") or 0) > 0
            ]
            purge_field_documents(field_slug, attempt_doc_ids)
        except Exception:
            pass
        try:
            from .pattern_store import remember_rejected_identity

            _failed_identity = str(candidate.get("identity_key") or "")
            if _failed_identity:
                remember_rejected_identity(_failed_identity)
        except Exception:
            pass
    result["candidate_id"] = candidate_id
    result["candidate_status"] = "loaded" if loaded_ok else "failed"
    result["document_id"] = document_ids[0] if document_ids else None
    result["loaded_title"] = document_titles[0] if document_titles else ""
    return result


@router.get("/load-queue")
def load_queue_status() -> dict[str, Any]:
    """Live status of the sequential background load queue (owner directive)."""
    from .load_queue import get_load_queue

    return get_load_queue().snapshot()


@router.post("/load-queue/{entry_id}/cancel")
def load_queue_cancel(entry_id: str) -> dict[str, Any]:
    """Cancel a queued entry instantly or request a running load to stop."""
    from .load_queue import get_load_queue

    outcome = get_load_queue().cancel(entry_id)
    if not outcome.get("ok"):
        raise HTTPException(status_code=404, detail=str(outcome.get("error") or "Unknown queue entry."))
    return outcome


@router.get("/progress/{job_id}")
def load_job_progress(job_id: str) -> dict[str, Any]:
    """Live progress for a background Load job (download / digest / embed)."""
    snapshot = load_progress.job_snapshot(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Unknown load job.")
    return snapshot


@router.post("/candidates/{candidate_id}/review")
def review_candidate(
    candidate_id: int,
    decision: str = Query(..., pattern="^(approve|reject)$"),
) -> dict[str, Any]:
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Skill candidate not found.")
        if decision == "reject":
            # Rejected datasets are removed from the review lineup immediately
            # (owner directive). The identity_key is preserved in the worker's
            # rejected-identity cache, so it will never reappear in future
            # searches either — only a fresh Load via GitHub/HF direct pull
            # can reintroduce the same dataset.
            identity = str(row["identity_key"] or "")
            conn.execute("DELETE FROM skill_review_candidates WHERE id = ?", (candidate_id,))
            conn.commit()
            if identity:
                try:
                    from .pattern_store import remember_rejected_identity

                    remember_rejected_identity(identity)
                    # Also block same-title variants: the same work often
                    # resurfaces under a different URL (mirrors, DOI vs landing
                    # page) — identical titles must not dodge the cache.
                    title_key = _source_identity(str(row["source_type"] or ""), "", {}, str(row["title"] or ""))
                    if title_key and title_key != identity:
                        remember_rejected_identity(title_key)
                except Exception:
                    pass
            return {
                "ok": True,
                "candidate_id": candidate_id,
                "status": "reject",
                "removed": True,
                "activated": False,
                "shared_skills_root": str(_root()),
            }
        conn.execute(
            "UPDATE skill_review_candidates SET status = ?, reviewed_at = datetime('now') WHERE id = ?",
            (decision, candidate_id),
        )
        conn.commit()

    if decision == "approve":
        manifest_dir = _root() / "approved"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest = manifest_dir / f"candidate-{candidate_id}.json"
        manifest.write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "source_url": row["source_url"],
                    "source_type": row["source_type"],
                    "title": row["title"],
                    "scientific_field": row["scientific_field"],
                    "target_persona": row["target_persona"],
                    "license": row["license"],
                    "approved_for_review": True,
                    "activated": False,
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "status": decision,
        "activated": False,
        "shared_skills_root": str(_root()),
    }


@router.post("/candidates/{candidate_id}/test")
def test_candidate(candidate_id: int) -> dict[str, Any]:
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM skill_review_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Skill candidate not found.")
    result = {
        "ok": True,
        "candidate": dict(row),
        "test_status": "queued_for_manual_test",
        "activated": False,
    }
    # OpenAlex works can be dry-run tested: fetch metadata + report what would load.
    candidate = dict(row)
    if str(candidate.get("source_type") or "") == "openalex":
        metadata_raw = candidate.get("metadata_json") or "{}"
        try:
            metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else dict(metadata_raw or {})
        except Exception:
            metadata = {}
        result["test_report"] = {
            "would_download_pdf": bool(metadata.get("pdf_url")),
            "pdf_url": str(metadata.get("pdf_url") or ""),
            "landing_page_url": str(metadata.get("landing_page_url") or ""),
            "open_access": bool(metadata.get("is_oa")),
            "note": "Dry run only: nothing was downloaded or ingested.",
        }
    return result
