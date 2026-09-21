"""PubMed/PMC dataset-sourcing worker for the SMi Sentinel medical fields.

Fourth sourcing lane (alongside GitHub, Hugging Face, OpenAlex), available ONLY
for the medical / life-mind sciences: Health, Medicine, Psychology,
Neuroscience (plus their compound variants such as "Medicine & Health",
"Public Health", "Pharmacology", "Neuroscience & Psychology").

Two-step E-utilities flow (see pubmedprocess.md):
  1. esearch  -> PMIDs matching the query
  2. esummary -> structured metadata (title, journal, authors, DOI, PMCID)
  3. efetch   -> full text from PubMed Central when the paper is in the
                 PMC Open Access Subset (XML -> plain text), otherwise the
                 PubMed abstract (always available, still valuable for RAG).

Full-text papers are stored under
``data/knowledge_taxonomy/scientific_fields/<field_slug>/pubmed/`` and ingested
by :func:`ingestion.ingest_files` exactly like the other lanes.

The NCBI API key is read from (first match wins):
  1. ``NCBI_API_KEY`` environment variable
  2. ``pubmedapi.md`` in the project root (the file the owner keeps the key in)
With a key: 10 requests/second. Without: 3 requests/second (rate limited here).
"""

from __future__ import annotations

import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests

from . import load_progress
from .config import get_project_root
from .sentinel_domains import (
    _field_metadata,
    _note_last_ingest,
    _resolve_field,
    get_sentinel_status,
    slugify,
)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Fields allowed to use the PubMed lane (normalized: lowercase, hyphens -> spaces).
PUBMED_ALLOWED_FIELD_PREFIXES = (
    "health",
    "medicine",
    "psychology",
    "neuroscience",
    "public health",
    "pharmacology",
    "genetics & molecular biology",
)

_last_request_at = 0.0
_rate_lock = threading.Lock()


def pubmed_field_allowed(field: str) -> bool:
    """True when the scientific field may use the PubMed lane."""
    normalized = str(field or "").strip().lower().replace("-", " ").replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip(" &")
    if not normalized:
        return False
    return any(
        normalized == prefix or normalized.startswith(prefix)
        for prefix in PUBMED_ALLOWED_FIELD_PREFIXES
    )


def _api_key() -> str:
    env = str(__import__("os").environ.get("NCBI_API_KEY") or "").strip()
    if env:
        return env
    try:
        raw = (get_project_root() / "pubmedapi.md").read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""
    # The key file may hold just the key (NCBI keys are 36 hex chars), or notes
    # around it; accept only something that looks like a bare key.
    candidate = raw.split()[0].strip() if raw else ""
    if re.fullmatch(r"[0-9a-fA-F]{36}", candidate):
        return candidate
    return ""


def _throttle() -> None:
    """NCBI politeness: <=3 req/s keyless, <=10 req/s with a key."""
    global _last_request_at
    interval = 0.11 if _api_key() else 0.35
    with _rate_lock:
        wait = _last_request_at + interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()


def _eget(url: str, params: dict[str, Any], timeout: int = 40) -> requests.Response:
    _throttle()
    key = _api_key()
    if key:
        params = {**params, "api_key": key}
    # NCBI endpoints are slow and occasionally drop connections; retry with
    # backoff instead of failing the search/load on the first hiccup.
    from .openalex_worker import _retry_get

    return _retry_get(
        url,
        params=params,
        headers={"User-Agent": "SMi-Sentinel/1.0 (dataset sourcing)"},
        timeout=timeout,
        attempts=3,
    )


def _clean_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\r", "", str(text or ""))).strip()


# ---------------------------------------------------------------------------
# Search (candidates for review)
# ---------------------------------------------------------------------------

def _esummary_to_candidate(uid: str, doc: dict[str, Any], field_text: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    title = _clean_text(doc.get("title") or "")
    if not title:
        return None
    doi = ""
    pmcid = ""
    for art in doc.get("articleids") or []:
        idtype = str(art.get("idtype") or "")
        if idtype == "doi" and not doi:
            doi = str(art.get("value") or "").strip()
        elif idtype == "pmc" and not pmcid:
            pmcid = str(art.get("value") or "").strip()
    pmcid = pmcid or str(doc.get("pmc") or "")
    journal = _clean_text(doc.get("fulljournalname") or doc.get("source") or "")
    pubdate = _clean_text(doc.get("pubdate") or "")
    last_author = _clean_text(doc.get("lastauthor") or "")
    authors = doc.get("authors") or []
    author_line = f"{last_author} et al." if last_author else (f"{len(authors)} authors" if authors else "")
    description = " ".join(part for part in [journal, f"({pubdate})" if pubdate else "", author_line] if part)
    source_url = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"
    return {
        "source_type": "pubmed",
        "source_url": source_url,
        "title": title,
        "description": description[:1000],
        "scientific_field": field_text,
        "target_persona": "gemma",
        "license": "PMC Open Access Subset (full text)" if pmcid else "PubMed abstract",
        "journal": journal,
        "pubdate": pubdate,
        "authors": author_line,
        # Top-level ids: identity resolution and the load lane read them here.
        "pmid": uid,
        "pmcid": pmcid,
        "doi": doi,
        "has_full_text": bool(pmcid),
    }


PM_ENGLISH_ONLY = True  # owner directive: English datasets only, for now


def search_pubmed_papers(
    query: str,
    field: str = "",
    limit: int = 12,
    from_year: int | None = None,
    full_text_only: bool = False,
) -> dict[str, Any]:
    """Search PubMed and return candidate papers for the review lineup.

    ``full_text_only=True`` restricts the search to the PMC Open Access
    Subset (query-level filter) AND drops any straggler without a PMCID,
    so every returned paper downloads as complete full text.
    """
    field_text = str(field or "").strip()
    if not pubmed_field_allowed(field_text):
        return {"ok": False, "candidates": [], "count": 0, "note": "PubMed is enabled for Health, Medicine, Psychology and Neuroscience fields only."}

    term = str(query or "").strip()
    if from_year:
        term = f"{term} AND {int(from_year)}:3000[dp]"
    if full_text_only:
        term = f"{term} AND free full text[sb]"
    if PM_ENGLISH_ONLY:
        term = f"{term} AND english[lang]"

    try:
        # Fetch a wider pool so open-access (PMC full-text) papers can be
        # promoted to the top of the lineup before trimming to the limit.
        pool_size = max(int(limit or 12) * 3, 15)
        search_resp = _eget(
            f"{EUTILS_BASE}/esearch.fcgi",
            {"db": "pubmed", "term": term, "retmode": "json", "retmax": min(75, pool_size)},
        )
        search_resp.raise_for_status()
        esearch = (search_resp.json() or {}).get("esearchresult") or {}
        pmids = [str(p) for p in (esearch.get("idlist") or []) if str(p).strip()]
        if not pmids:
            return {"ok": True, "candidates": [], "count": 0, "total_available": int(esearch.get("count") or 0), "full_text_count": 0}

        # Esummary in batches of 40 (URL length + NCBI batch limits) so wide
        # pools (up to 75 pmids) never exceed a single request's budget.
        candidates: list[dict[str, Any]] = []
        for batch_start in range(0, len(pmids), 40):
            batch = pmids[batch_start : batch_start + 40]
            summary_resp = _eget(
                f"{EUTILS_BASE}/esummary.fcgi",
                {"db": "pubmed", "id": ",".join(batch), "retmode": "json"},
            )
            summary_resp.raise_for_status()
            result = (summary_resp.json() or {}).get("result") or {}
            for uid in batch:
                doc = result.get(uid)
                if not isinstance(doc, dict):
                    continue
                candidate = _esummary_to_candidate(uid, doc, field_text)
                if candidate is not None:
                    candidates.append(candidate)

        if PM_ENGLISH_ONLY:
            # Owner directive: English-language papers only. PubMed indexes
            # mostly English titles, but translated records carry a [lang]
            # tag; the lightweight heuristic below drops the obvious ones
            # without extra API round-trips.
            _NON_EN_TAGS = (
                "[french]", "[german]", "[spanish]", "[italian]", "[portuguese]",
                "[russian]", "[japanese]", "[chinese]", "[dutch]", "[polish]",
                "[swedish]", "[danish]", "[norwegian]", "[czech]", "[hungarian]",
                "[turkish]", "[greek]", "[hebrew]", "[arabic]", "[korean]",
            )
            candidates = [c for c in candidates if not str(c.get("title") or "").lower().endswith(_NON_EN_TAGS)]

        # Prefer open-access papers: stable sort keeps NCBI relevance/date order
        # within each group, but papers with PMC full text lead the lineup.
        candidates.sort(key=lambda c: 0 if c.get("has_full_text") else 1)

        if full_text_only:
            # Defense in depth: the OA filter can occasionally match records
            # without a PMCID (e.g. free full text on the publisher site only).
            candidates = [c for c in candidates if c.get("has_full_text")]

        full_text_count = sum(1 for c in candidates if c.get("has_full_text"))
        candidates = candidates[: max(1, min(25, int(limit or 12)))]
        return {
            "ok": True,
            "candidates": candidates,
            "count": len(candidates),
            "total_available": int(esearch.get("count") or 0),
            "full_text_count": sum(1 for c in candidates if c.get("has_full_text")),
            "full_text_available": full_text_count,
            "full_text_only": bool(full_text_only),
        }
    except Exception as ex:
        return {"ok": False, "candidates": [], "count": 0, "note": f"PubMed search failed: {str(ex)[:140]}", "full_text_count": 0}


def fetch_pubmed_abstract(pmid: str) -> str:
    """Fetch the abstract (or title fallback) for one PMID as plain text."""
    try:
        resp = _eget(
            f"{EUTILS_BASE}/efetch.fcgi",
            {"db": "pubmed", "id": str(pmid).strip(), "rettype": "abstract", "retmode": "text"},
            timeout=45,
        )
        resp.raise_for_status()
        return _clean_text(resp.text)[:40000]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Load (download full text + ingest into the field)
# ---------------------------------------------------------------------------

def _pmc_full_text(pmcid: str) -> str:
    """Full text of a PMC Open Access paper (XML -> plain text)."""
    numeric = str(pmcid).upper().replace("PMC", "").strip()
    resp = _eget(
        f"{EUTILS_BASE}/efetch.fcgi",
        {"db": "pmc", "id": numeric, "retmode": "xml"},
        timeout=60,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    parts: list[str] = []
    for element in root.iter():
        tag = element.tag.split("}")[-1]
        if tag in ("title", "p", "td", "th", "li", "sec", "abstract"):
            text = _clean_text("".join(element.itertext()))
            if text:
                parts.append(text)
    # Dedupe nested section repeats while keeping reading order.
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        key = part[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(part)
    return "\n\n".join(out)


def load_pubmed_papers_into_field(
    field: str,
    papers: list[dict[str, Any]],
    *,
    max_papers: int = 10,
) -> dict[str, Any]:
    """Download + digest PubMed/PMC papers into a Sentinel scientific field."""
    from .ingestion import ingest_files

    if not pubmed_field_allowed(field):
        return {
            "ok": False,
            "field": field,
            "downloaded": 0,
            "ingested": 0,
            "failed": len(papers or []),
            "items": [{"ok": False, "error": "PubMed lane is enabled for Health, Medicine, Psychology and Neuroscience fields only."}],
            "status": get_sentinel_status(refresh_counts=False),
        }

    resolved = _resolve_field(field)
    target_root = resolved["target_dir"] / "pubmed"
    target_root.mkdir(parents=True, exist_ok=True)

    max_papers = max(1, min(25, int(max_papers or 10)))
    papers = papers[:max_papers]

    stored_paths: list[str] = []
    items: list[dict[str, Any]] = []

    for index, paper in enumerate(papers, start=1):
        pmid = str(paper.get("pmid") or "").strip()
        title = str(paper.get("title") or f"PubMed paper {pmid or index}")
        load_progress.stage("download", f"Fetching paper {index}/{len(papers)}: {title[:60]}...")
        base = f"{slugify(title)[:60]}-pm{slugify(pmid or str(index))}"
        stored = False

        # Attempt 1: PMC Open Access full text.
        pmcid = str(paper.get("pmcid") or "").strip()
        if pmcid and pmcid.upper().startswith("PMC"):
            try:
                full_text = _pmc_full_text(pmcid)
                if len(full_text) > 500:
                    text_path = target_root / f"{base}.txt"
                    header = f"{title}\nPubMed https://pubmed.ncbi.nlm.nih.gov/{pmid}/  PMC{pmcid.replace('PMC', '')}\n\n"
                    text_path.write_text(header + full_text, encoding="utf-8")
                    stored_paths.append(str(text_path))
                    items.append({"ok": True, "title": title, "kind": "pmc-full-text", "bytes": text_path.stat().st_size, "path": str(text_path), "pmid": pmid})
                    stored = True
            except Exception as ex:
                items.append({"ok": False, "title": title, "note": f"PMC full text failed ({str(ex)[:120]}); falling back to the abstract."})

        # Attempt 2: PubMed abstract (always available for the record).
        if not stored and pmid:
            try:
                abstract = fetch_pubmed_abstract(pmid)
                if len(abstract) > 80:
                    text_path = target_root / f"{base}-abstract.txt"
                    text_path.write_text(abstract, encoding="utf-8")
                    stored_paths.append(str(text_path))
                    items.append({"ok": True, "title": title, "kind": "abstract", "bytes": text_path.stat().st_size, "path": str(text_path), "pmid": pmid})
                    stored = True
            except Exception as ex:
                items.append({"ok": False, "title": title, "error": str(ex)[:160]})

        if not stored:
            items.append({"ok": False, "title": title, "error": "No PMC full text and no abstract retrievable."})

    if not stored_paths:
        return {
            "ok": False,
            "field": resolved["field_name"],
            "field_slug": resolved["field_slug"],
            "downloaded": 0,
            "ingested": 0,
            "failed": len(papers),
            "items": items,
            "status": get_sentinel_status(refresh_counts=False),
        }

    load_progress.stage("digest", f"Stored {len(stored_paths)} paper file(s) — digesting into the knowledge library...")
    result = ingest_files(stored_paths, metadata=_field_metadata(resolved), allow_embeddings=True)
    ingested = int(result.get("ingested") or 0)
    _note_last_ingest(resolved["field_slug"])
    return {
        "ok": ingested > 0,
        "field": resolved["field_name"],
        "field_slug": resolved["field_slug"],
        "downloaded": len(stored_paths),
        "ingested": ingested,
        "failed": int(result.get("failed") or 0) + sum(1 for item in items if not item.get("ok")),
        "items": items + (result.get("items") or []),
        "status": get_sentinel_status(refresh_counts=False),
    }
