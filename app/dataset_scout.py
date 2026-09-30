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


def discover(query: str, limit_per_source: int = 8, sources: list[str] | None = None) -> dict[str, Any]:
    """Search candidate sources in owner priority order; proposals only."""
    q = str(query or "").strip()
    if not q:
        return {"ok": False, "error": "query is required"}
    wanted = [s.strip().lower() for s in (sources or [s["id"] for s in SOURCE_PRIORITY])]
    ordered = [s for s in SOURCE_PRIORITY if s["id"] in wanted]

    results: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    total = 0
    for source in ordered:
        fn = _SOURCES.get(source["id"])
        outcome = fn(q, max(1, min(25, int(limit_per_source)))) if fn else {"ok": False, "error": "unknown source", "items": []}
        results.append({
            "rank": source["rank"],
            "source": source["id"],
            "label": source["label"],
            "ok": outcome.get("ok", False),
            "error": outcome.get("error"),
            "returned": len(outcome.get("items", [])),
        })
        for item in outcome.get("items", []):
            item["priority_rank"] = source["rank"]
            candidates.append(item)
        total += len(outcome.get("items", []))  # §63: outcome has no 'returned' key — count items directly.

    return {
        "ok": total > 0,
        "query": q,
        "priority_note": " → ".join(s["label"] for s in ordered),
        "owner_rule": "proposals only — the owner approves every dataset before ingestion (intake firewall §60 still guards the door)",
        "sources": results,
        "candidates": candidates,
        "total": total,
    }
