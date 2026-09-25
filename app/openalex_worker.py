"""OpenAlex dataset-sourcing worker for the SMi Sentinel scientific fields.

Given a query and a Sentinel scientific field, this worker:

1. Searches the OpenAlex ``works`` REST API for the most relevant scientific
   papers (https://api.openalex.org/works?search=...).
2. Prefers works with a freely accessible full text (open access PDF or HTML
   landing page).
3. Downloads the best-available artifact for each work (PDF, HTML page, or the
   OpenAlex JSON record as a last resort) into the field's data room under
   ``data/knowledge_taxonomy/scientific_fields/<field_slug>/openalex/``.
4. The caller then ingests the downloaded files into the field's vector room
   with :func:`ingestion.ingest_files` (mirrors the GitHub/HF dataset lanes).

The API key lives in ``app/apis/open-alex-api.md`` (the file the user keeps
their key in); ``OPENALEX_API_KEY`` environment variable overrides it.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import requests

from .config import get_project_root
from . import load_progress
from .sentinel_domains import (
    SENTINEL_DOMAINS,
    _field_metadata,
    _note_last_ingest,
    _resolve_field,
    get_sentinel_status,
    slugify,
)

OPENALEX_API_BASE = "https://api.openalex.org"

# English-only intake: the owner's directive — for now Sentinel accepts English
# datasets only. Applied to the search filter (server-side) and as a safety
# net on each result (OpenAlex reports the detected language per work).
OA_ENGLISH_ONLY = True

# Resilient HTTP: scholarly endpoints (OpenAlex, publisher PDF hosts, NCBI)
# are slow and flaky, so every GET retries with backoff before giving up.
_RETRYABLE_STATUSES = {403, 408, 429, 500, 502, 503, 504}


def _retry_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    attempts: int = 3,
    stream: bool = False,
) -> requests.Response:
    """GET with retries and exponential backoff.

    Handles the "extremely slow / mostly server error" reality of scholarly
    hosts: transient 429/5xx responses and mid-flight connection drops are
    retried instead of failing the whole load.
    """
    last_exc: Exception | None = None
    last_resp: requests.Response | None = None
    for attempt in range(max(1, attempts)):
        try:
            resp = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout,
                stream=stream,
                allow_redirects=True,
            )
            if resp.status_code not in _RETRYABLE_STATUSES:
                return resp
            last_resp = resp
            status = resp.status_code
        except requests.RequestException as ex:  # timeouts, resets, DNS hiccups
            last_exc = ex
            status = str(ex)[:80]
        if attempt < max(1, attempts) - 1:
            wait = min(8.0, 1.5 * (2**attempt))  # 1.5s, 3s, 6s ...
            load_progress.emit("download", f"Request failed ({status}); retrying in {wait:.0f}s...")
            time.sleep(wait)
    if last_resp is not None:
        return last_resp
    raise last_exc if last_exc is not None else RuntimeError(f"Request failed: {url}")


def _is_english_work(work: dict[str, Any]) -> bool:
    """True when the work's detected language is English (or unknown/blank,
    which OpenAlex uses when language detection found nothing to judge)."""
    lang = str(work.get("language") or "").strip().lower()
    return lang in ("", "en", "en-us", "en-gb")


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------

_KEY_TOKEN_RE = re.compile(r"[A-Za-z0-9._-]{8,}")


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------

_KEY_TOKEN_RE = re.compile(r"[A-Za-z0-9._-]{8,}")


def _extract_key_from_line(line: str) -> list[str]:
    """Pull candidate API keys out of one config line, best guess first."""
    candidates: list[str] = []
    # Format: https://api.openalex.org/<key>
    if "openalex.org/" in line:
        tail = line.split("openalex.org/", 1)[1].strip().split()[0]
        tail = tail.rstrip(",;\"')]")
        if _KEY_TOKEN_RE.fullmatch(tail):
            candidates.append(tail)
    # Whole line is a bare key (possibly 'label KEY')
    tokens = [t for t in line.replace("api.openalex.org", " ").split() if _KEY_TOKEN_RE.fullmatch(t)]
    for token in tokens:
        if token not in candidates and not token.lower().startswith(("http", "api.")):
            candidates.append(token)
    return candidates


def _key_sources() -> list[str]:
    """Ordered key candidates: env var, URL-embedded keys, then bare tokens."""
    import os

    env_key = str(os.environ.get("OPENALEX_API_KEY") or "").strip()
    url_embedded: list[str] = []
    bare_tokens: list[str] = []

    key_file = get_project_root() / "app" / "apis" / "open-alex-api.md"
    candidate_lines: list[str] = []
    if key_file.exists():
        candidate_lines.extend(key_file.read_text(encoding="utf-8", errors="replace").splitlines())
    env_file = get_project_root().parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "openalex" in line.lower():
                candidate_lines.append(line.strip())

    for line in candidate_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "openalex.org/" in line:
            tail = line.split("openalex.org/", 1)[1].strip().split()[0].rstrip(",;\"')]")
            if _KEY_TOKEN_RE.fullmatch(tail) and tail not in url_embedded:
                url_embedded.append(tail)
            continue
        for token in _extract_key_from_line(line):
            if token not in bare_tokens:
                bare_tokens.append(token)

    ordered: list[str] = []
    for candidate in [env_key, *url_embedded, *bare_tokens]:
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def load_openalex_api_key() -> str:
    """Resolve the OpenAlex API key from env or the user's key files."""
    keys = _key_sources()
    return keys[0] if keys else ""


def _openalex_headers() -> dict[str, str]:
    return {"User-Agent": "SMi-Sentinel-Discovery/1.0 (mailto:smi@local)"}


def _params(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"mailto": "smi@local"}
    key = load_openalex_api_key()
    if key:
        params["api_key"] = key
    if extra:
        params.update(extra)
    return params


def _get_with_key_retry(url: str, params: dict[str, Any], timeout: int = 60) -> requests.Response:
    """GET the URL, retrying with each candidate API key on auth rejection."""
    keys = _key_sources()
    last_resp: requests.Response | None = None
    for key in keys or [""]:
        attempt = dict(params)
        if key:
            attempt["api_key"] = key
        else:
            attempt.pop("api_key", None)
        resp = _retry_get(url, params=attempt, headers=_openalex_headers(), timeout=timeout)
        if resp.status_code not in (401, 403):
            return resp
        last_resp = resp
    assert last_resp is not None
    return last_resp


# ---------------------------------------------------------------------------
# Field resolution helpers
# ---------------------------------------------------------------------------

def list_fields() -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for domain in SENTINEL_DOMAINS:
        for item in domain.get("fields", []):
            name = str(item.get("name") or "")
            field_slug = str(item.get("slug") or "").strip() or slugify(name)
            fields.append(
                {
                    "field_slug": field_slug,
                    "field_name": name,
                    "domain_slug": str(domain.get("slug") or ""),
                    "detail": str(item.get("detail") or ""),
                }
            )
    return fields


def _resolve_field_meta(field: str) -> dict[str, Any]:
    """Return the SENTINEL_DOMAINS registry entry for a field (no DB access)."""
    wanted = slugify(field)
    for item in list_fields():
        if item["field_slug"] == wanted or slugify(item["field_name"]) == wanted:
            return item
    raise ValueError(f"Unknown Sentinel scientific field: {field!r}")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _work_artifacts(work: dict[str, Any]) -> dict[str, Any]:
    """Extract the best downloadable artifacts from an OpenAlex work record."""
    best_oa = work.get("best_oa_location") or {}
    primary = work.get("primary_location") or {}
    oa_any = work.get("open_access") or {}

    pdf_url = (
        best_oa.get("pdf_url")
        or primary.get("pdf_url")
        or oa_any.get("oa_url")
        or ""
    )
    landing_url = best_oa.get("landing_page_url") or primary.get("landing_page_url") or ""
    if not landing_url and primary.get("source"):
        landing_url = primary["source"].get("landing_page_url") or ""
    landing_url = str(landing_url or "")

    doi = str(work.get("doi") or "").replace("https://doi.org/", "")
    title = str(work.get("title") or work.get("display_name") or "Untitled work")
    year = work.get("publication_year")
    cited_by = int(work.get("cited_by_count") or 0)
    is_oa = bool(work.get("open_access", {}).get("is_oa"))

    return {
        "openalex_id": str(work.get("id") or ""),
        "title": title,
        "year": year,
        "cited_by_count": cited_by,
        "doi": doi,
        "is_oa": is_oa,
        "pdf_url": str(pdf_url or ""),
        "landing_page_url": landing_url,
        "authors": ", ".join(
            str(a.get("author", {}).get("display_name") or "")
            for a in (work.get("authorships") or [])[:6]
            if isinstance(a, dict)
        ).strip(", "),
        "source_name": (
            (primary.get("source") or {}).get("display_name")
            or (best_oa.get("source") or {}).get("display_name")
            or ""
        ),
        "abstract": _work_abstract(work)[:1200],
    }


_ABSTRACT_INV_INDEX_RE = re.compile(r"\b(\d+)\b")


def _work_abstract(work: dict[str, Any]) -> str:
    """Rebuild an abstract from OpenAlex's inverted index when available."""
    if work.get("abstract"):
        return str(work["abstract"])
    idx = work.get("abstract_inverted_index")
    if not isinstance(idx, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, spots in idx.items():
        for spot in spots or []:
            positions.append((int(spot), word))
    positions.sort()
    return " ".join(word for _, word in positions)


def search_openalex_works(
    query: str,
    *,
    field: str = "",
    limit: int = 12,
    open_access_only: bool = True,
    min_citations: int = 0,
    from_year: int | None = None,
) -> dict[str, Any]:
    """Search OpenAlex works and return review-ready candidates."""
    query = str(query or "").strip()
    if len(query) < 2:
        raise ValueError("Provide a research topic query of at least 2 characters.")
    limit = max(1, min(25, int(limit or 12)))

    field_meta: dict[str, Any] | None = None
    if field:
        field_meta = _resolve_field_meta(field)

    # The query is used exactly as provided — the UI sends the field's own name
    # (e.g. "Physics") or whatever topic the operator typed. No extra
    # sub-science keywords are appended to the search string.
    search_text = query
    filters: list[str] = []
    if open_access_only:
        filters.append("is_oa:true")
    if OA_ENGLISH_ONLY:
        # Server-side English filter — non-English works never reach the lineup.
        filters.append("language:en")
    if from_year:
        filters.append(f"from_publication_date:{from_year}-01-01")
    else:
        # Owner directive (§22): recent scholarship leads the lineup — the
        # default window is 2020 to current. Pass from_year to widen it.
        filters.append("from_publication_date:2020-01-01")
    if min_citations and min_citations > 0:
        filters.append(f"cited_by_count:>{int(min_citations)}")

    params = _params(
        {
            "search": search_text,
            "per-page": limit,        "select": "id,doi,title,display_name,publication_year,cited_by_count,"
        "open_access,best_oa_location,primary_location,authorships,abstract_inverted_index,language",
    }
    )
    if filters:
        params["filter"] = ",".join(filters)

    resp = _get_with_key_retry(f"{OPENALEX_API_BASE}/works", params, timeout=60)
    if resp.status_code in (401, 403):
        raise ValueError(
            "OpenAlex rejected the API key (403). Check the key in app/apis/open-alex-api.md "
            "or set the OPENALEX_API_KEY environment variable."
        )
    resp.raise_for_status()
    payload = resp.json()

    candidates: list[dict[str, Any]] = []
    for work in payload.get("results") or []:
        if not isinstance(work, dict):
            continue
        if OA_ENGLISH_ONLY and not _is_english_work(work):
            continue  # safety net if the server-side filter ever misses
        artifact = _work_artifacts(work)
        # The full record is kept so "load" can re-fetch metadata reliably.
        artifact["search_query"] = query
        artifact["source_type"] = "openalex"
        artifact["scientific_field"] = (field_meta or {}).get("field_name", "")
        artifact["field_slug"] = (field_meta or {}).get("field_slug", "")
        candidates.append(artifact)

    # Owner directive (§22): prioritized lineup — the most-cited works lead.
    # The sort is stable, so within equal citation counts OpenAlex's own
    # relevance ranking (query fit) is preserved. Candidates are already
    # restricted to 2020-current by the server-side filter above.
    candidates.sort(key=lambda c: -int(c.get("cited_by_count") or 0))

    return {
        "ok": True,
        "query": query,
        "field": (field_meta or {}).get("field_name", field),
        "field_slug": (field_meta or {}).get("field_slug", ""),
        "count": len(candidates),
        "candidates": candidates,
        "api_key_found": bool(load_openalex_api_key()),
        "review_required": True,
    }


# ---------------------------------------------------------------------------
# Download + ingest into a field
# ---------------------------------------------------------------------------

_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # per file, matches the Sentinel PDF cap
_DOWNLOAD_TIMEOUT = 180
# Owner directive: the whole load (every attempt chain) must finish inside this
# wall-clock budget — no more 10-minute hangs on the small machine.
_LOAD_WALL_BUDGET_SECONDS = 150

_PDF_MAGIC = b"%PDF-"


def _looks_like_pdf(blob: bytes) -> bool:
    return blob[:8].lstrip()[:5] == _PDF_MAGIC[:5]


def _safe_filename(text: str, max_len: int = 80) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip("-.")
    return (cleaned or "openalex-work")[:max_len]


def _download(url: str, deadline: float | None = None) -> tuple[str, bytes, str]:
    """Download an artifact; return (content_type, bytes, final_url).

    Owner directive: no download may ever hold the app hostage. The wall-clock
    ``deadline`` (monotonic timestamp) is enforced across the streamed body —
    a slow trickle of bytes cannot stretch a download into a 10-minute hang.
    """
    headers = _openalex_headers()
    resp = _retry_get(url, headers=headers, timeout=_DOWNLOAD_TIMEOUT, stream=True, attempts=4)
    resp.raise_for_status()
    content_type = str(resp.headers.get("Content-Type") or "")
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError(f"Download exceeded the {int(_LOAD_WALL_BUDGET_SECONDS)}s wall-clock budget ({total} bytes so far).")
        if total > _MAX_DOWNLOAD_BYTES:
            break
    return content_type, b"".join(chunks), str(resp.url or url)


def _work_metadata_record(work: dict[str, Any]) -> str:
    """Serialize a work as a readable JSON+text hybrid document for ingestion."""
    artifact = _work_artifacts(work)
    header = "\n".join(
        [
            f"Title: {artifact['title']}",
            f"Authors: {artifact['authors'] or 'Unknown'}",
            f"Year: {artifact['year'] or 'Unknown'}",
            f"Source: {artifact['source_name'] or 'Unknown'}",
            f"DOI: {artifact['doi'] or 'n/a'}",
            f"OpenAlex ID: {artifact['openalex_id']}",
            f"Cited by: {artifact['cited_by_count']}",
            f"Open access: {'yes' if artifact['is_oa'] else 'no'}",
            f"Landing page: {artifact['landing_page_url'] or 'n/a'}",
            f"PDF: {artifact['pdf_url'] or 'n/a'}",
            "",
        ]
    )
    abstract = artifact.get("abstract") or "(no abstract available)"
    body = json.dumps(work, ensure_ascii=False, indent=1)
    return f"{header}Abstract:\n{abstract}\n\nOpenAlex record JSON:\n{body}"


def load_openalex_works_into_field(
    field: str,
    works: list[dict[str, Any]],
    *,
    max_works: int = 10,
) -> dict[str, Any]:
    """Download + digest OpenAlex works into a Sentinel scientific field."""
    from .ingestion import ingest_files

    resolved = _resolve_field(field)
    target_root = resolved["target_dir"] / "openalex"
    target_root.mkdir(parents=True, exist_ok=True)

    max_works = max(1, min(25, int(max_works or 10)))
    works = works[:max_works]

    stored_paths: list[str] = []
    items: list[dict[str, Any]] = []
    total_bytes = 0
    work_records: dict[str, dict[str, Any]] = {}

    for index, work in enumerate(works, start=1):
        openalex_id = str(work.get("openalex_id") or "")
        title = str(work.get("title") or "Untitled work")
        if load_progress.cancel_requested():
            raise load_progress.LoadCancelled("Load cancelled by owner before the next download.")
        load_progress.stage("download", f"Fetching work {index}/{len(works)}: {title[:60]}...")
        base = f"{slugify(title)[:60]}-{_safe_filename(openalex_id.split('/')[-1] or str(index))}"
        stored = False
        load_started = time.monotonic()
        # §39: per-attempt budget — previously all three attempts shared the
        # whole 150s wall, so one stalling PDF host consumed it and the work
        # died before the reliable fallbacks ever ran (the owner's 4–8
        # reloads). Now each attempt gets its own slice and the always-
        # reachable metadata record is almost never starved.
        per_attempt = max(30.0, _LOAD_WALL_BUDGET_SECONDS / 3.0)

        # Attempt 1: direct open-access PDF.
        pdf_url = str(work.get("pdf_url") or "")
        if pdf_url:
            try:
                _content_type, blob, _final = _download(pdf_url, deadline=time.monotonic() + per_attempt)
                if _looks_like_pdf(blob):
                    pdf_path = target_root / f"{base}.pdf"
                    pdf_path.write_bytes(blob)
                    stored_paths.append(str(pdf_path))
                    total_bytes += len(blob)
                    items.append({"ok": True, "title": title, "kind": "pdf", "bytes": len(blob), "path": str(pdf_path)})
                    stored = True
            except Exception as ex:
                items.append({"ok": False, "title": title, "note": f"PDF download failed ({str(ex)[:120]}); trying the landing page next."})

        # Attempt 2: the open-access landing page (HTML full text on the
        # publisher's site) — ingests like any saved web document.
        landing_url = str(work.get("landing_page_url") or "")
        if not stored and landing_url and not landing_url.lower().startswith("https://doi.org/"):
            try:
                content_type, blob, _final = _download(landing_url, deadline=time.monotonic() + per_attempt)
                lowered = (content_type or "").lower()
                is_html = (
                    "html" in lowered
                    or blob[:512].lstrip().lower().startswith((b"<!doctype", b"<html"))
                    or b"<html" in blob[:2048].lower()
                )
                # §39: HTML quality gate — publisher landing pages are often
                # JavaScript shells / cookie-walls that parse to menus and
                # boilerplate. They used to be stored as "success", then
                # digest to junk (or below minimum size -> failed load ->
                # owner retries). Measure the real text BEFORE accepting.
                html_text_len = 0
                if is_html:
                    try:
                        from .parsing import parse_document_from_html

                        html_text_len = len(str(parse_document_from_html(blob.decode("utf-8", errors="ignore"), default_title=title).get("text") or ""))
                    except Exception:
                        html_text_len = 0
                if is_html and len(blob) > 2000 and html_text_len >= 1200:
                    html_path = target_root / f"{base}.html"
                    html_path.write_bytes(blob)
                    stored_paths.append(str(html_path))
                    total_bytes += len(blob)
                    items.append({"ok": True, "title": title, "kind": "html", "bytes": len(blob), "path": str(html_path)})
                    stored = True
                elif is_html:
                    items.append({"ok": False, "title": title, "note": f"Landing page rejected (only {html_text_len} chars of real text — JS shell/menu wall); using the OpenAlex record instead."})
            except Exception as ex:
                items.append({"ok": False, "title": title, "note": f"Landing page fetch failed ({str(ex)[:120]}); using the OpenAlex record instead."})

        # Attempt 3: full OpenAlex record (abstract + metadata JSON) — always
        # reachable and enough for the knowledge library on its own.
        if not stored:
            try:
                work_record: dict[str, Any]
                work_id = openalex_id.split("/")[-1] if openalex_id else ""
                if work_id and work_id.upper().startswith("W"):
                    resp = _get_with_key_retry(f"{OPENALEX_API_BASE}/works/{work_id}", _params(), timeout=60)
                    if resp.status_code in (401, 403):
                        raise ValueError("OpenAlex rejected the API key while fetching the full work record.")
                    resp.raise_for_status()
                    work_record = resp.json()
                else:
                    work_record = dict(work)
                    work_record.setdefault("title", title)
                text_path = target_root / f"{base}.json.txt"
                text_path.write_text(_work_metadata_record(work_record), encoding="utf-8")
                stored_paths.append(str(text_path))
                work_records[str(text_path)] = work_record
                total_bytes += text_path.stat().st_size
                items.append({"ok": True, "title": title, "kind": "metadata", "bytes": text_path.stat().st_size, "path": str(text_path)})
                stored = True
            except Exception as ex:
                items.append({"ok": False, "title": title, "error": str(ex)})

    if not stored_paths:
        return {
            "ok": False,
            "field": resolved["field_name"],
            "field_slug": resolved["field_slug"],
            "downloaded": 0,
            "ingested": 0,
            "failed": len(works),
            "items": items,
            "status": get_sentinel_status(refresh_counts=False),
        }

    # Owner directive: non-English content is discarded immediately. When the
    # work was downloaded as a metadata record, re-check the detected language
    # of the authoritative record before it can reach the library.
    english_paths: list[str] = []
    for item in items:
        if item.get("ok") and item.get("kind") == "metadata":
            rec = work_records.get(str(item.get("path") or ""))
            if rec is not None and not _is_english_work(rec):
                try:
                    Path(str(item.get("path"))).unlink(missing_ok=True)
                except Exception:
                    pass
                stored_paths = [p for p in stored_paths if p != str(item.get("path"))]
                item["ok"] = False
                item["error"] = "Non-English work discarded (OpenAlex language gate)."
                continue
        if item.get("ok") and item.get("path"):
            english_paths.append(str(item.get("path")))
    if not english_paths:
        return {
            "ok": False,
            "field": resolved["field_name"],
            "field_slug": resolved["field_slug"],
            "downloaded": len(items),
            "ingested": 0,
            "failed": len(works),
            "items": items,
            "status": get_sentinel_status(refresh_counts=False),
        }

    load_progress.stage("digest", f"Stored {len(english_paths)} file(s) — digesting into the knowledge library...")
    result = ingest_files(
        english_paths,
        metadata={**_field_metadata(resolved), "enforce_english": True},
        allow_embeddings=True,
    )
    # Owner directive: a failed digest must leave nothing behind — the
    # artifact files are removed so no half-state lingers in the container.
    if int(result.get("ingested") or 0) == 0:
        for path in english_paths:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
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
