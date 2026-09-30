"""Sentinari dataset scout — §61.

Owner-set source priority for discovering NEW candidate datasets:

    1) OpenAlex            (scholarly works, keyed, in-tree)
    2) Medical web sources (Europe PMC — free, no key, biomedical)
    3) GitHub              (code+data repos, unauthenticated search)
    4) HuggingFace         (datasets hub, unauthenticated search)

Candidates are returned IN PRIORITY ORDER and are PROPOSALS ONLY — the
owner manually approves every dataset before any ingestion (the intake
firewall, §60, still guards the door). No candidate is auto-ingested by
this module. Each source is independently error-isolated: one failing
source never hides the others, and the response reports what happened.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

SOURCE_PRIORITY = (
    {"rank": 1, "id": "openalex", "label": "OpenAlex (scholarly works)"},
    {"rank": 2, "id": "medical", "label": "Medical web sources (Europe PMC)"},
    {"rank": 3, "id": "github", "label": "GitHub (repos & data)"},
    {"rank": 4, "id": "huggingface", "label": "HuggingFace (datasets hub)"},
)

_HTTP_TIMEOUT = 20
_UA = {"User-Agent": "Sentinari-DatasetScout/1.0 (research discovery)"}


def _clean(text: str, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _openalex_candidates(query: str, limit: int) -> dict[str, Any]:
    try:
        from .openalex_worker import search_openalex_works

        result = search_openalex_works(query=query, limit=min(25, limit))
        items = []
        for w in (result.get("candidates") or [])[:limit]:
            items.append({
                "source": "openalex",
                "title": _clean(w.get("title")),
                "year": w.get("year") or w.get("publication_year"),
                "authors": [_clean(a, 60) for a in (w.get("authors") or [])[:3]],
                "detail": _clean(str(w.get("landing_page") or w.get("doi") or "")),
                "url": str(w.get("landing_page") or w.get("doi") or ""),
                "citations": w.get("cited_by_count"),
            })
        return {"ok": bool(result.get("ok")), "items": items, "error": result.get("error")}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200], "items": []}


def _medical_candidates(query: str, limit: int) -> dict[str, Any]:
    """Europe PMC REST search — free, no key, the biomedical wing."""
    try:
        resp = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": query,
                "format": "json",
                "pageSize": min(25, limit),
                "resultType": "core",
            },
            headers=_UA,
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("resultList", {}).get("result", []) or []
        items = []
        for r in results[:limit]:
            items.append({
                "source": "medical",
                "title": _clean(r.get("title")),
                "year": r.get("pubYear"),
                "authors": [_clean(a, 60) for a in str(r.get("authorString") or "").split(",")[:3]],
                "detail": _clean(r.get("abstractText") or r.get("journalTitle") or "", 200),
                "url": (f"https://europepmc.org/article/{r.get('source','')}/{r.get('id','')}" if r.get("id") else ""),
            })
        return {"ok": True, "items": items}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200], "items": []}


def _github_candidates(query: str, limit: int) -> dict[str, Any]:
    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": f"{query} dataset", "per_page": min(20, limit), "sort": "stars"},
            headers=_UA,
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        items = []
        for r in (resp.json() or {}).get("items", [])[:limit]:
            items.append({
                "source": "github",
                "title": _clean(r.get("full_name")),
                "year": (str(r.get("created_at") or "")[:4] or None),
                "authors": [str(r.get("owner", {}).get("login") or "")] if r.get("owner") else [],
                "detail": f"★{r.get('stargazers_count', 0)} — {_clean(r.get('description'), 160)}",
                "url": str(r.get("html_url") or ""),
            })
        return {"ok": True, "items": items}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200], "items": []}


def _huggingface_candidates(query: str, limit: int) -> dict[str, Any]:
    try:
        resp = requests.get(
            "https://huggingface.co/api/datasets",
            params={"search": query, "limit": min(20, limit), "sort": "downloads", "direction": -1},
            headers=_UA,
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        items = []
        for r in (resp.json() or [])[:limit]:
            repo = str(r.get("id") or "")
            items.append({
                "source": "huggingface",
                "title": repo,
                "year": None,
                "authors": [repo.split("/")[0]] if "/" in repo else [],
                "detail": f"downloads:{r.get('downloads', 0)} likes:{r.get('likes', 0)}",
                "url": f"https://huggingface.co/datasets/{repo}",
            })
        return {"ok": True, "items": items}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200], "items": []}


_SOURCES = {
    "openalex": _openalex_candidates,
    "medical": _medical_candidates,
    "github": _github_candidates,
    "huggingface": _huggingface_candidates,
}


def discover(
    query: str,
    limit_per_source: int = 8,
    sources: list[str] | None = None,
    bypass_blocks: bool = False,
) -> dict[str, Any]:
    """Search candidate sources in owner priority order; proposals only.

    §64: sources on the owner blocklist are filtered out BEFORE the response
    is built — blocked items never reach the review surface. bypass_blocks
    (owner-only audit) skips the filter but reports that it was bypassed.
    """
    q = str(query or "").strip()
    if not q:
        return {"ok": False, "error": "query is required"}
    wanted = [s.strip().lower() for s in (sources or [s["id"] for s in SOURCE_PRIORITY])]
    ordered = [s for s in SOURCE_PRIORITY if s["id"] in wanted]

    blocked_origins, hf_exact = _load_blocks()

    results: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    total = 0
    blocked_total = 0
    for source in ordered:
        fn = _SOURCES.get(source["id"])
        outcome = fn(q, max(1, min(25, int(limit_per_source)))) if fn else {"ok": False, "error": "unknown source", "items": []}
        kept: list[dict[str, Any]] = []
        dropped = 0
        for item in outcome.get("items", []):
            blocked_hit = _is_blocked(item, source["id"], blocked_origins, hf_exact)
            if blocked_hit:
                dropped += 1
                if not bypass_blocks:
                    continue  # §64: hidden from the review surface unless owner audits
            kept.append(item)
        results.append({
            "rank": source["rank"],
            "source": source["id"],
            "label": source["label"],
            "ok": outcome.get("ok", False),
            "error": outcome.get("error"),
            "returned": len(kept),
            "blocked": dropped,  # §64: hidden by the owner blocklist, not lost.
        })
        for item in kept:
            item["priority_rank"] = source["rank"]
            candidates.append(item)
        total += len(kept)
        blocked_total += dropped

    return {
        "ok": total > 0,
        "query": q,
        "priority_note": " → ".join(s["label"] for s in ordered),
        "owner_rule": "proposals only — the owner approves every dataset before ingestion (intake firewall §60 still guards the door)",
        "quality_rule": "§64: comprehensive, whole-field datasets at masters/PhD standard only — block sub-standard sources the moment they appear",
        "sources": results,
        "candidates": candidates,
        "total": total,
        "blocked_count": blocked_total,
        "blocks_active": len(blocked_origins) + len(hf_exact),
        "blocks_bypassed": bool(bypass_blocks),
    }


# ---------------------------------------------------------------------------
# §64 — owner source blocklist ("once blocked, always blocked")
#
# Owner doctrine: discovery must surface only comprehensive, whole-field
# datasets at masters/PhD standard. Repeated low-grade publishers (e.g. a
# HuggingFace user mass-uploading sub-standard datasets) are BLOCKED at the
# source, so review effort shrinks instead of re-judging the same noise on
# every search. Blocks live in the MAIN app database (scout_blocklist table,
# same store as the §60 intake firewall) and are enforced in discover().
#
# Scope:
#   "user"  — blocks the ORIGIN everywhere it appears (HF user, GitHub
#             org/user, journal/domain). Covers everything they publish,
#             past and future.
#   "exact" — HuggingFace only: blocks one repo (user/dataset-name) while
#             keeping the rest of that user's work visible.
# Unblock exists as an API-only safety valve for owner mistakes; the UI
# never offers it — on the review surface, once blocked, always blocked.
# ---------------------------------------------------------------------------


def _app_db_path() -> Path:
    from .intake_firewall import _app_db_path as _fw_db_path  # single source of truth (§60)

    return _fw_db_path()


def _blocks_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_app_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scout_blocklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'user',
            note TEXT NOT NULL DEFAULT '',
            blocked_at TEXT NOT NULL,
            blocked_by TEXT NOT NULL DEFAULT 'owner'
        )
        """
    )
    conn.commit()
    return conn


def _load_blocks() -> tuple[frozenset[str], frozenset[str]]:
    """(user-scope origins, exact HF repo names) currently blocked."""
    try:
        conn = _blocks_connect()
    except Exception:
        return frozenset(), frozenset()
    try:
        rows = conn.execute("SELECT origin, label, source, scope FROM scout_blocklist").fetchall()
    except Exception:
        return frozenset(), frozenset()
    finally:
        conn.close()
    origins = frozenset(
        str(r["origin"]).strip().lower() for r in rows if str(r["scope"]) == "user" and str(r["origin"]).strip()
    )
    hf_exact = frozenset(
        str(r["label"]).strip().lower()
        for r in rows
        if str(r["scope"]) == "exact" and str(r["source"]) == "huggingface" and str(r["label"]).strip()
    )
    return origins, hf_exact


def _hf_repo(item: dict[str, Any]) -> str:
    repo = str(item.get("title") or "").strip()
    return repo.lower() if "/" in repo else ""


def _candidate_origin(item: dict[str, Any], source_id: str) -> str:
    """The person/organisation behind a candidate — the blockable unit (§64)."""
    authors = item.get("authors") or []
    origin = str(authors[0]).strip() if authors else ""
    if not origin:
        url = str(item.get("url") or "")
        m = re.match(r"https?://([^/]+)/", url)
        origin = m.group(1) if m else ""
    return origin.strip().lower()


def _is_blocked(item: dict[str, Any], source_id: str, blocked_origins: frozenset[str], hf_exact: frozenset[str]) -> bool:
    origin = _candidate_origin(item, source_id)
    if origin and origin in blocked_origins:
        return True
    if source_id == "huggingface":
        repo = _hf_repo(item)
        if repo and repo in hf_exact:
            return True
    return False


def list_blocks() -> dict[str, Any]:
    conn = _blocks_connect()
    try:
        rows = conn.execute(
            "SELECT id, origin, label, source, scope, note, blocked_at, blocked_by "
            "FROM scout_blocklist ORDER BY blocked_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return {
        "ok": True,
        "count": len(rows),
        "blocks": [
            {
                "id": r["id"],
                "origin": r["origin"],
                "label": r["label"],
                "source": r["source"],
                "scope": r["scope"],
                "note": r["note"],
                "blocked_at": r["blocked_at"],
                "blocked_by": r["blocked_by"],
            }
            for r in rows
        ],
    }


def block_source(
    origin: str,
    label: str = "",
    source: str = "",
    scope: str = "user",
    note: str = "",
    blocked_by: str = "owner",
) -> dict[str, Any]:
    """Block a source origin. Idempotent: re-blocking updates label/note."""
    o = str(origin or "").strip().lower()
    if not o:
        return {"ok": False, "error": "origin is required"}
    scope = "exact" if str(scope or "").strip().lower() == "exact" else "user"
    if scope == "exact" and str(source or "").strip().lower() != "huggingface":
        return {"ok": False, "error": "exact scope is HuggingFace-only (user scope covers every source)"}
    conn = _blocks_connect()
    try:
        conn.execute(
            "INSERT INTO scout_blocklist (origin, label, source, scope, note, blocked_at, blocked_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(origin) DO UPDATE SET label=excluded.label, source=excluded.source, "
            "scope=excluded.scope, note=excluded.note, blocked_at=excluded.blocked_at, blocked_by=excluded.blocked_by",
            (
                o,
                str(label or "").strip(),
                str(source or "").strip().lower(),
                scope,
                str(note or "").strip(),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                str(blocked_by or "owner"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "origin": o, "scope": scope, "rule": "once blocked, always blocked"}


def unblock_source(origin: str) -> dict[str, Any]:
    """API-only safety valve for owner mistakes — the UI never offers it."""
    o = str(origin or "").strip().lower()
    if not o:
        return {"ok": False, "error": "origin is required"}
    conn = _blocks_connect()
    try:
        cur = conn.execute("DELETE FROM scout_blocklist WHERE origin = ?", (o,))
        conn.commit()
        removed = cur.rowcount or 0
    finally:
        conn.close()
    return {"ok": True, "origin": o, "removed": removed}
