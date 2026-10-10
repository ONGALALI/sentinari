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
    """Pull candidate API keys out of one config line, best guess first.

    Handles bare keys, URL-embedded keys, and ``KEY=value`` lines — the
    in-tree ``.env`` stores the live key as ``OPENALEX_API_KEY=...`` (§76:
    the old extractor only matched bare tokens, so the valid .env key was
    never seen and a stale doc key got the lane 401-killed every search).
    """
    candidates: list[str] = []

    def _add(token: str) -> None:
        token = token.strip().strip("\"'").rstrip(",;)]}")
        if token and _KEY_TOKEN_RE.fullmatch(token) and token not in candidates:
            if not token.lower().startswith(("http", "api.")):
                candidates.append(token)

    # Format: https://api.openalex.org/<key>
    if "openalex.org/" in line:
        _add(line.split("openalex.org/", 1)[1].strip().split()[0])
    # Format: KEY=value (e.g. OPENALEX_API_KEY=abc123 in .env)
    if "=" in line and "http" not in line.lower():
        value = line.split("=", 1)[1]
        _add(value.split()[0] if value.split() else value)
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
    # Live secrets first: the in-tree .env is the operator's current key
    # store (§76) — the doc file below is only a fallback, and its key can
    # rot without the owner noticing while .env stays valid.
    for env_file in (
        get_project_root() / ".env",          # in-tree first — folder is self-contained
        get_project_root().parent / ".env",   # legacy parent-folder fallback
    ):
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if "openalex" in line.lower():
                    candidate_lines.append(line.strip())
    if key_file.exists():
        candidate_lines.extend(key_file.read_text(encoding="utf-8", errors="replace").splitlines())

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
    return {"User-Agent": "Sentinari-Sentinel-Discovery/1.0 (mailto:operator@local)"}


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
    # Every stored key was rejected (§76): fall back to a keyless request
    # instead of failing the whole lane — OpenAlex still serves anonymous
    # traffic, and a rotting doc key must never zero out the OpenAlex lane.
    keyless = dict(params)
    keyless.pop("api_key", None)
    resp = _retry_get(url, params=keyless, headers=_openalex_headers(), timeout=timeout)
    if resp.status_code not in (401, 403):
        return resp
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


def _resolve_field_meta(field: str, fallback_text: str = "") -> dict[str, Any]:
    """Return the SENTINEL_DOMAINS registry entry for a field (no DB access)."""
    from .sentinel_domains import sanitize_field_and_domain

    f_slug, _ = sanitize_field_and_domain(field, fallback_text=fallback_text)
    wanted = f_slug or slugify(field)
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
    primary_topic = work.get("primary_topic") if isinstance(work.get("primary_topic"), dict) else {}
    oa_field = str((primary_topic.get("field") or {}).get("display_name") or "").strip()
    oa_subfield = str((primary_topic.get("subfield") or {}).get("display_name") or "").strip()
    oa_topic = str(primary_topic.get("display_name") or "").strip()

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
        "oa_field": oa_field,
        "oa_subfield": oa_subfield,
        "oa_topic": oa_topic,
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
    from .sentinel_domains import sanitize_field_and_domain

    query = str(query or "").strip()
    if len(query) < 2:
        raise ValueError("Provide a research topic query of at least 2 characters.")
    limit = max(1, min(25, int(limit or 12)))

    field_meta: dict[str, Any] | None = None
    try:
        field_meta = _resolve_field_meta(field, fallback_text=query)
    except Exception:
        field_meta = None

    search_text = query
    filters: list[str] = []
    if open_access_only:
        filters.append("is_oa:true")
    if OA_ENGLISH_ONLY:
        filters.append("language:en")
    if from_year:
        filters.append(f"from_publication_date:{from_year}-01-01")
    else:
        filters.append("from_publication_date:2020-01-01")
    if min_citations and min_citations > 0:
        filters.append(f"cited_by_count:>{int(min_citations)}")

    params = _params(
        {
            "search": search_text,
            "per-page": min(25, max(limit, int(limit * 1.5))),
            "select": "id,doi,title,display_name,publication_year,cited_by_count,"
            "open_access,best_oa_location,primary_location,authorships,abstract_inverted_index,language,primary_topic",
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

    target_slug = (field_meta or {}).get("field_slug", "")
    target_domain = (field_meta or {}).get("domain_slug", "")
    target_terms = set(
        re.findall(
            r"[a-z]{4,}",
            f"{(field_meta or {}).get('field_name', '')} {(field_meta or {}).get('detail', '')}".lower(),
        )
    )

    query_slug, query_domain = sanitize_field_and_domain("", fallback_text=query)

    candidates: list[dict[str, Any]] = []
    for work in payload.get("results") or []:
        if not isinstance(work, dict):
            continue
        if OA_ENGLISH_ONLY and not _is_english_work(work):
            continue
        artifact = _work_artifacts(work)
        # Skip title-only stubs that have neither a downloadable PDF nor a real abstract.
        if not artifact.get("pdf_url") and len(str(artifact.get("abstract") or "").strip()) < 80:
            continue
        oa_topic_hint = f"{artifact.get('oa_field') or ''} {artifact.get('oa_subfield') or ''} {artifact.get('oa_topic') or ''}".strip()
        work_text = f"{artifact.get('title') or ''} {artifact.get('abstract') or ''}"
        inferred_slug, inferred_domain = sanitize_field_and_domain(oa_topic_hint, fallback_text=work_text)

        # If the user's search query clearly targets a specific field (e.g. "Human Nervous System" -> neuroscience)
        # and OpenAlex's own topic agrees, prefer that canonical field over a stale UI dropdown.
        effective_target_slug = query_slug if (query_slug and query_slug == inferred_slug) else target_slug
        effective_target_domain = query_domain if (query_slug and query_slug == inferred_slug) else target_domain

        # Domain gate: if user requested a specific scientific field (e.g. physics),
        # reject works that OpenAlex classifies into an unrelated domain (e.g. medicine
        # or insurance) unless the title/abstract explicitly carries the target field's terms.
        if effective_target_slug and inferred_domain and effective_target_domain and inferred_domain != effective_target_domain:
            hay_lc = work_text.lower()
            if not any(t in hay_lc for t in target_terms):
                continue

        resolved_slug = effective_target_slug or inferred_slug or target_slug or "physics"
        resolved_domain = effective_target_domain or inferred_domain or target_domain or ""
        artifact["search_query"] = query
        artifact["source_type"] = "openalex"
        artifact["scientific_field"] = resolved_slug
        artifact["field_slug"] = resolved_slug
        artifact["domain_slug"] = resolved_domain
        candidates.append(artifact)
        if len(candidates) >= limit:
            break

    candidates.sort(key=lambda c: -int(c.get("cited_by_count") or 0))

    return {
        "ok": True,
        "query": query,
        "field": (field_meta or {}).get("field_name", field),
        "field_slug": target_slug,
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


def _work_metadata_record(work: dict[str, Any], fallback_abstract: str = "") -> str:
    """Serialize a work as clean scientific prose (never raw JSON metadata)."""
    artifact = _work_artifacts(work)
    concepts = [
        str(c.get("display_name") or "").strip()
        for c in (work.get("concepts") or work.get("topics") or [])
        if isinstance(c, dict) and str(c.get("display_name") or "").strip()
    ][:12]
    header_lines = [
        f"Title: {artifact['title'] or work.get('title') or 'Untitled'}",
        f"Authors: {artifact['authors'] or work.get('authors') or 'Unknown'}",
        f"Year: {artifact['year'] or work.get('year') or 'Unknown'}",
        f"Source: {artifact['source_name'] or work.get('source_name') or 'Unknown'}",
        f"DOI: {artifact['doi'] or work.get('doi') or 'n/a'}",
        f"OpenAlex ID: {artifact['openalex_id'] or work.get('openalex_id') or ''}",
        f"Cited by: {artifact['cited_by_count']}",
        f"Open access: {'yes' if artifact['is_oa'] else 'no'}",
        f"Landing page: {artifact['landing_page_url'] or work.get('landing_page_url') or 'n/a'}",
        f"PDF: {artifact['pdf_url'] or work.get('pdf_url') or 'n/a'}",
    ]
    if concepts:
        header_lines.append(f"Key Topics: {', '.join(concepts)}")
    header = "\n".join(header_lines) + "\n\n"
    abstract = str(artifact.get("abstract") or fallback_abstract or "").strip()
    return f"{header}Abstract:\n{abstract}\n"


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
    per_file_metadata: dict[str, dict[str, Any]] = {}

    for index, work in enumerate(works, start=1):
        openalex_id = str(work.get("openalex_id") or "")
        title = str(work.get("title") or "Untitled work")
        if load_progress.cancel_requested():
            raise load_progress.LoadCancelled("Load cancelled by owner before the next download.")
        load_progress.stage("download", f"Fetching work {index}/{len(works)}: {title[:60]}...")
        base = f"{slugify(title)[:60]}-{_safe_filename(openalex_id.split('/')[-1] or str(index))}"
        stored = False
        stored_path_for_work = ""
        per_attempt = max(30.0, _LOAD_WALL_BUDGET_SECONDS / 3.0)

        # Attempt 1: direct open-access PDF.
        pdf_url = str(work.get("pdf_url") or "")
        if pdf_url:
            try:
                _content_type, blob, _final = _download(pdf_url, deadline=time.monotonic() + per_attempt)
                if _looks_like_pdf(blob):
                    pdf_path = target_root / f"{base}.pdf"
                    pdf_path.write_bytes(blob)
                    stored_path_for_work = str(pdf_path)
                    stored_paths.append(stored_path_for_work)
                    total_bytes += len(blob)
                    items.append({"ok": True, "title": title, "kind": "pdf", "bytes": len(blob), "path": stored_path_for_work})
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
                    stored_path_for_work = str(html_path)
                    stored_paths.append(stored_path_for_work)
                    total_bytes += len(blob)
                    items.append({"ok": True, "title": title, "kind": "html", "bytes": len(blob), "path": stored_path_for_work})
                    stored = True
                elif is_html:
                    items.append({"ok": False, "title": title, "note": f"Landing page rejected (only {html_text_len} chars of real text — JS shell/menu wall); using the OpenAlex record instead."})
            except Exception as ex:
                items.append({"ok": False, "title": title, "note": f"Landing page fetch failed ({str(ex)[:120]}); using the OpenAlex record instead."})

        # Attempt 3: OpenAlex abstract record — ONLY if a real abstract exists!
        # Never store a title-only stub with '(no abstract available)'.
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
                rec_art = _work_artifacts(work_record)
                fallback_abs = str(work.get("abstract") or work.get("description") or "").strip()
                real_abs = str(rec_art.get("abstract") or fallback_abs).strip()
                if len(real_abs) < 80:
                    items.append(
                        {
                            "ok": False,
                            "title": title,
                            "error": "Publisher blocked PDF/HTML full text and OpenAlex has no abstract for this work — skipped so title-only stubs never enter the library.",
                        }
                    )
                else:
                    text_path = target_root / f"{base}.json.txt"
                    text_path.write_text(_work_metadata_record(work_record, fallback_abstract=fallback_abs), encoding="utf-8")
                    stored_path_for_work = str(text_path)
                    stored_paths.append(stored_path_for_work)
                    work_records[stored_path_for_work] = work_record
                    total_bytes += text_path.stat().st_size
                    items.append({"ok": True, "title": title, "kind": "metadata", "bytes": text_path.stat().st_size, "path": stored_path_for_work})
                    stored = True
            except Exception as ex:
                items.append({"ok": False, "title": title, "error": str(ex)})

        if stored and stored_path_for_work:
            rec_obj = work_records.get(stored_path_for_work) or work
            art_meta = _work_artifacts(rec_obj) if "id" in rec_obj or "authorships" in rec_obj else {}
            w_title = str(work.get("title") or art_meta.get("title") or title).strip()
            w_authors = str(work.get("authors") or art_meta.get("authors") or "").strip()
            w_year = str(work.get("year") or art_meta.get("year") or "").strip()
            w_source = str(work.get("source_name") or art_meta.get("source_name") or "").strip()
            w_doi = str(work.get("doi") or art_meta.get("doi") or "").strip()
            w_url = str(
                work.get("landing_page_url")
                or (f"https://doi.org/{w_doi}" if w_doi else "")
                or work.get("source_url")
                or openalex_id
            ).strip()
            file_meta = {
                "title": w_title,
                "authors": w_authors or None,
                "published_date": w_year or None,
                "publisher": w_source or "OpenAlex",
                "source_url": w_url or None,
            }
            per_file_metadata[stored_path_for_work] = file_meta
            per_file_metadata[Path(stored_path_for_work).name] = file_meta

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
        metadata={
            **_field_metadata(resolved),
            "enforce_english": True,
            "per_file_metadata": per_file_metadata,
        },
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
        "failed": int(result.get("failed") or 0) + max(0, len(works) - len(english_paths)),
        "items": items + (result.get("items") or []),
        "status": get_sentinel_status(refresh_counts=False),
    }
