"""Contemporary Articles, Journals & Expert Commentary Scraper for Sentinari Playground.

Scrapes live contemporary sources (OpenAlex 2024-present journals, arXiv preprints,
Crossref journals, Europe PMC/PubMed recent literature, and contemporary web/news/expert
articles) regarding a user's query matter so that new meanings, recent decisions, and
emerging perspectives from contemporary writers and experts are captured, synthesized,
and optionally ingested directly into the curated Sentinel Knowledge Library.
"""

from __future__ import annotations

import hashlib
import html as _html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import requests

import urllib3
from .db import library_connection
from .ingestion import _sha256_bytes, _upsert_document_with_chunks, build_ollama_client
from .llm_gateway import get_gateway
from .pattern_worker import queue_document
from .sentinel_domains import sanitize_field_and_domain

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_UA = "Sentinari-Contemporary-Scraper/2.0 (https://sentinari-core-250830594433.us-central1.run.app; mailto:research@sentinari.ai)"
_HEADERS = {"User-Agent": _UA, "Accept": "application/json, application/xml, text/html, */*"}


def _safe_get(url: str, **kwargs: Any) -> requests.Response:
    """Perform requests.get, falling back to verify=False if local SSL cert bundle fails."""
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError:
        kwargs["verify"] = False
        return requests.get(url, **kwargs)


def _reconstruct_abstract(inverted_index: Any) -> str:
    """Reconstruct plain text from an OpenAlex abstract_inverted_index dict."""
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, pos_list in inverted_index.items():
        if not isinstance(pos_list, list):
            continue
        for pos in pos_list:
            try:
                positions.append((int(pos), str(word)))
            except Exception:
                continue
    if not positions:
        return ""
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions).strip()


def _clean_html_text(raw_html: str, max_chars: int = 3500) -> str:
    """Extract clean readable paragraphs from HTML/XML fragments."""
    if not raw_html:
        return ""
    cleaned = re.sub(r"(?is)<(script|style|noscript|header|footer|nav|aside)[^>]*>.*?</\1>", " ", raw_html)
    paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", cleaned)
    if paragraphs:
        body = "\n\n".join(
            re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", p))).strip()
            for p in paragraphs
        )
    else:
        body = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", cleaned))).strip()
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:max_chars]


def _fetch_article_body_snippet(url: str, timeout: int = 6) -> str:
    """Best-effort fetch of a contemporary web/journal landing page to extract readable paragraphs."""
    if not url or not url.startswith(("http://", "https://")):
        return ""
    if url.lower().endswith(".pdf"):
        return ""
    try:
        resp = _safe_get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        ctype = str(resp.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text" not in ctype and "xml" not in ctype:
            return ""
        text = _clean_html_text(resp.text[:120000], max_chars=2800)
        return text if len(text) >= 140 else ""
    except Exception:
        return ""


def _scrape_openalex_contemporary(query: str, max_results: int = 4) -> list[dict[str, Any]]:
    """Search OpenAlex for contemporary (2022-present) peer-reviewed journal articles."""
    items: list[dict[str, Any]] = []
    try:
        from .openalex_worker import _params

        params = _params(
            {
                "search": query,
                "filter": "from_publication_date:2022-01-01",
                "per-page": max(6, min(15, max_results * 3)),
            }
        )
        resp = _safe_get("https://api.openalex.org/works", params=params, headers=_HEADERS, timeout=12)
        if resp.status_code in (401, 403):
            params.pop("api_key", None)
            resp = _safe_get("https://api.openalex.org/works", params=params, headers=_HEADERS, timeout=12)
        if resp.status_code != 200:
            return []
        data = resp.json()
        for w in (data.get("results") or []):
            title = str(w.get("title") or w.get("display_name") or "").strip()
            if not title:
                continue
            abstract = _reconstruct_abstract(w.get("abstract_inverted_index"))
            auths: list[str] = []
            for a in (w.get("authorships") or [])[:8]:
                name = str(((a or {}).get("author") or {}).get("display_name") or "").strip()
                if name:
                    auths.append(name)
            loc = w.get("primary_location") or {}
            src = loc.get("source") or {}
            journal = str(src.get("display_name") or "OpenAlex Contemporary Journal").strip()
            pub_date = str(w.get("publication_date") or w.get("publication_year") or "").strip()
            doi = str(w.get("doi") or "").strip()
            url = doi or str(loc.get("landing_page_url") or w.get("id") or "").strip()
            concepts = [
                str(c.get("display_name") or "").strip()
                for c in (w.get("concepts") or [])[:5]
                if str(c.get("display_name") or "").strip()
            ]
            if len(abstract) < 60:
                pt = (w.get("primary_topic") or {}).get("display_name") or ""
                abstract = (
                    f"Contemporary peer-reviewed journal publication in {journal} ({pub_date}) "
                    f"authored by {', '.join(auths) or 'research contributors'}. "
                    f"Primary topic: {pt or query}. Key concepts: {', '.join(concepts) or query}."
                )
            items.append(
                {
                    "lane": "OpenAlex Contemporary Journal",
                    "source_type": "contemporary-journal",
                    "title": title,
                    "authors": ", ".join(auths) or "Contemporary Research Collective",
                    "publisher": journal,
                    "published_date": pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "url": url,
                    "summary": abstract,
                    "keywords": concepts,
                }
            )
            if len(items) >= max_results:
                break
    except Exception:
        pass
    return items


def _scrape_arxiv_contemporary(query: str, max_results: int = 4) -> list[dict[str, Any]]:
    """Search arXiv API for recent preprints and emerging research papers."""
    items: list[dict[str, Any]] = []
    try:
        tokens = [t for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) >= 2][:5]
        arxiv_q = " AND ".join(f"all:{t}" for t in tokens) if tokens else f"all:{query}"
        resp = _safe_get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": arxiv_q,
                "start": 0,
                "max_results": max(1, min(8, max_results)),
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
            headers=_HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title = re.sub(r"\s+", " ", (entry.findtext("atom:title", default="", namespaces=ns) or "")).strip()
            summary = re.sub(r"\s+", " ", (entry.findtext("atom:summary", default="", namespaces=ns) or "")).strip()
            if not title or len(summary) < 60:
                continue
            published = (entry.findtext("atom:published", default="", namespaces=ns) or "")[:10]
            link = entry.findtext("atom:id", default="", namespaces=ns) or ""
            authors = [
                (a.findtext("atom:name", default="", namespaces=ns) or "").strip()
                for a in entry.findall("atom:author", ns)
                if (a.findtext("atom:name", default="", namespaces=ns) or "").strip()
            ]
            cats = [
                str(c.attrib.get("term") or "").strip()
                for c in entry.findall("atom:category", ns)
                if str(c.attrib.get("term") or "").strip()
            ]
            items.append(
                {
                    "lane": "arXiv Preprint",
                    "source_type": "contemporary-preprint",
                    "title": title,
                    "authors": ", ".join(authors[:8]) or "arXiv Authors",
                    "publisher": "arXiv Contemporary Preprint Server",
                    "published_date": published or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "url": link.strip(),
                    "summary": summary,
                    "keywords": cats[:5],
                }
            )
            if len(items) >= max_results:
                break
    except Exception:
        pass
    return items


def _scrape_crossref_contemporary(query: str, max_results: int = 3) -> list[dict[str, Any]]:
    """Search Crossref for contemporary journal articles with abstracts."""
    items: list[dict[str, Any]] = []
    try:
        resp = _safe_get(
            "https://api.crossref.org/works",
            params={
                "query": query,
                "filter": "from-pub-date:2023-01-01,has-abstract:true",
                "rows": max(1, min(8, max_results * 2)),
                "sort": "published",
                "order": "desc",
            },
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        msg = (resp.json() or {}).get("message") or {}
        for w in (msg.get("items") or []):
            titles = w.get("title") or []
            title = str(titles[0] if titles else "").strip()
            raw_abs = str(w.get("abstract") or "").strip()
            abstract = _clean_html_text(raw_abs, max_chars=2500)
            if not title or len(abstract) < 80:
                continue
            authors: list[str] = []
            for a in (w.get("author") or [])[:8]:
                given = str(a.get("given") or "").strip()
                family = str(a.get("family") or "").strip()
                full = f"{given} {family}".strip()
                if full:
                    authors.append(full)
            containers = w.get("container-title") or []
            journal = str(containers[0] if containers else w.get("publisher") or "Crossref Journal").strip()
            date_parts = (((w.get("published") or w.get("Issued") or {}).get("date-parts") or [[]])[0]) or []
            pub_date = "-".join(f"{int(x):02d}" if i > 0 else str(x) for i, x in enumerate(date_parts[:3])) if date_parts else ""
            doi = str(w.get("DOI") or "").strip()
            url = f"https://doi.org/{doi}" if doi and not doi.startswith("http") else (doi or str(w.get("URL") or ""))
            subjects = [str(s).strip() for s in (w.get("subject") or [])[:5] if str(s).strip()]
            items.append(
                {
                    "lane": "Crossref Journal",
                    "source_type": "contemporary-journal",
                    "title": title,
                    "authors": ", ".join(authors) or "Journal Contributors",
                    "publisher": journal,
                    "published_date": pub_date or datetime.now(timezone.utc).strftime("%Y"),
                    "url": url,
                    "summary": abstract,
                    "keywords": subjects,
                }
            )
            if len(items) >= max_results:
                break
    except Exception:
        pass
    return items


def _scrape_europepmc_contemporary(query: str, max_results: int = 3) -> list[dict[str, Any]]:
    """Search Europe PMC / PubMed for contemporary life, medical, cognitive, and environmental literature."""
    items: list[dict[str, Any]] = []
    try:
        resp = _safe_get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": f"({query}) AND (FIRST_PDATE:[2023-01-01 TO 2030-12-31])",
                "format": "json",
                "resultType": "core",
                "pageSize": max(1, min(8, max_results * 2)),
            },
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        results = (((resp.json() or {}).get("resultList") or {}).get("result")) or []
        for r in results:
            title = str(r.get("title") or "").strip().rstrip(".")
            abstract = _clean_html_text(str(r.get("abstractText") or ""), max_chars=2500)
            if not title or len(abstract) < 80:
                continue
            authors = str(r.get("authorString") or "").strip().rstrip(".")
            journal = str(r.get("journalTitle") or r.get("bookOrReportDetails", {}).get("publisher") or "Europe PMC / PubMed").strip()
            pub_date = str(r.get("firstPublicationDate") or r.get("pubYear") or "").strip()
            doi = str(r.get("doi") or "").strip()
            pmcid = str(r.get("pmcid") or "").strip()
            pmid = str(r.get("pmid") or "").strip()
            if doi:
                url = f"https://doi.org/{doi}"
            elif pmcid:
                url = f"https://europepmc.org/article/PMC/{pmcid}"
            elif pmid:
                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            else:
                url = ""
            kw_raw = ((r.get("keywordList") or {}).get("keyword")) or []
            kws = [str(k).strip() for k in kw_raw[:5] if str(k).strip()]
            items.append(
                {
                    "lane": "Europe PMC / PubMed",
                    "source_type": "contemporary-journal",
                    "title": title,
                    "authors": authors or "Biomedical & Scientific Authors",
                    "publisher": journal,
                    "published_date": pub_date or datetime.now(timezone.utc).strftime("%Y"),
                    "url": url,
                    "summary": abstract,
                    "keywords": kws,
                }
            )
            if len(items) >= max_results:
                break
    except Exception:
        pass
    return items


def _scrape_contemporary_web_and_news(query: str, max_results: int = 4) -> list[dict[str, Any]]:
    """Scrape contemporary articles, expert commentary, and policy/scientific decisions via RSS & Wikipedia."""
    items: list[dict[str, Any]] = []
    # 1. Google News RSS for contemporary articles, writers, and recent decisions
    try:
        rss_url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        resp = _safe_get(rss_url, headers=_HEADERS, timeout=8)
        if resp.status_code == 200 and resp.text:
            root = ET.fromstring(resp.text)
            for item_el in root.findall("./channel/item")[: max_results + 2]:
                raw_title = (item_el.findtext("title") or "").strip()
                link = (item_el.findtext("link") or "").strip()
                pub_date = (item_el.findtext("pubDate") or "").strip()
                source_el = item_el.find("source")
                publisher = (source_el.text if source_el is not None and source_el.text else "Contemporary Press & Commentary").strip()
                desc_html = item_el.findtext("description") or ""
                desc_text = _clean_html_text(desc_html, max_chars=1200)
                if " - " in raw_title and publisher and raw_title.endswith(f" - {publisher}"):
                    title = raw_title[: -len(f" - {publisher}")].strip()
                else:
                    title = raw_title
                if not title:
                    continue
                # Try fetching page snippet if description is short
                body_snippet = _fetch_article_body_snippet(link, timeout=4) if len(desc_text) < 160 else ""
                full_summary = "\n\n".join(p for p in [desc_text, body_snippet] if p).strip()
                if len(full_summary) < 60:
                    full_summary = (
                        f"Contemporary article and expert report published by {publisher} ({pub_date}): "
                        f"{title}. {desc_text}"
                    ).strip()
                items.append(
                    {
                        "lane": "Contemporary Article & Expert Press",
                        "source_type": "contemporary-article",
                        "title": title,
                        "authors": f"{publisher} Editorial & Expert Contributors",
                        "publisher": publisher,
                        "published_date": pub_date[:16] if pub_date else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "url": link,
                        "summary": full_summary,
                        "keywords": ["Contemporary Commentary", "Emerging Decisions"],
                    }
                )
                if len(items) >= max_results:
                    break
    except Exception:
        pass

    # 2. Wikipedia Contemporary Context fallback/supplement
    if len(items) < max_results:
        try:
            w_resp = _safe_get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "utf8": 1,
                    "format": "json",
                    "srlimit": 2,
                },
                headers=_HEADERS,
                timeout=6,
            )
            if w_resp.status_code == 200:
                hits = (((w_resp.json() or {}).get("query") or {}).get("search")) or []
                for h in hits:
                    page_title = str(h.get("title") or "").strip()
                    if not page_title:
                        continue
                    sum_resp = _safe_get(
                        f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(page_title.replace(' ', '_'))}",
                        headers=_HEADERS,
                        timeout=6,
                    )
                    if sum_resp.status_code == 200:
                        sdata = sum_resp.json() or {}
                        extract = str(sdata.get("extract") or "").strip()
                        if len(extract) >= 80:
                            page_url = str(((sdata.get("content_urls") or {}).get("desktop") or {}).get("page") or f"https://en.wikipedia.org/wiki/{quote_plus(page_title)}")
                            items.append(
                                {
                                    "lane": "Contemporary Encyclopedia & Living Reference",
                                    "source_type": "contemporary-article",
                                    "title": f"{page_title} — Contemporary Reference & Evolving Definitions",
                                    "authors": "Contemporary Reference Contributors",
                                    "publisher": "Wikipedia Living Reference",
                                    "published_date": str(sdata.get("timestamp") or "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                    "url": page_url,
                                    "summary": extract,
                                    "keywords": [page_title, "Evolving Terminology"],
                                }
                            )
        except Exception:
            pass
    return items[:max_results]


def ingest_contemporary_items(
    items: list[dict[str, Any]],
    *,
    requested_fields: list[str] | None = None,
    query: str = "",
) -> list[dict[str, Any]]:
    """Ingest scraped contemporary articles/journals directly into the Sentinel Knowledge Library."""
    ingested_records: list[dict[str, Any]] = []
    primary_hint = (requested_fields or [""])[0] if requested_fields else ""
    try:
        embed_client = build_ollama_client()
    except Exception:
        embed_client = None

    with library_connection("gemma") as conn:
        for item in items:
            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not title or len(summary) < 60:
                continue
            canon_field, canon_domain = sanitize_field_and_domain(
                primary_hint or item.get("scientific_field") or "",
                fallback_text=f"{title} {query} {summary}",
            )
            full_text = (
                f"Title: {title}\n"
                f"Authors: {item.get('authors') or 'Contemporary Authors'}\n"
                f"Publication / Journal: {item.get('publisher') or 'Contemporary Source'}\n"
                f"Published Date: {item.get('published_date') or ''}\n"
                f"Source URL: {item.get('url') or ''}\n"
                f"Sentinel Domain: {canon_domain}\n"
                f"Scientific Field: {canon_field}\n"
                f"Query Context: {query}\n\n"
                f"Abstract & Contemporary Findings:\n{summary}\n"
            )
            checksum = _sha256_bytes(full_text.encode("utf-8", errors="ignore"))
            meta = {
                "module": canon_domain,
                "topic": query[:120] or title[:120],
                "language": "en",
                "license": "open-contemporary",
                "published_date": str(item.get("published_date") or ""),
                "authors": str(item.get("authors") or ""),
                "publisher": str(item.get("publisher") or ""),
                "scientific_field": canon_field,
                "domain": canon_domain,
                "source_collection": "contemporary-scraper",
                "extra_metadata": {
                    "lane": item.get("lane"),
                    "keywords": item.get("keywords") or [],
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                },
            }
            try:
                res = _upsert_document_with_chunks(
                    conn,
                    title=title,
                    source_type=str(item.get("source_type") or "contemporary-journal"),
                    source_path=None,
                    source_url=str(item.get("url") or "") or None,
                    checksum=checksum,
                    archive_path=None,
                    text=full_text,
                    metadata=meta,
                    embedding_model=embed_client,
                )
                doc_id = int(res.get("document_id") or 0)
                item["document_id"] = doc_id
                item["scientific_field"] = canon_field
                item["domain"] = canon_domain
                item["ingested"] = True
                ingested_records.append(
                    {
                        "document_id": doc_id,
                        "title": title,
                        "scientific_field": canon_field,
                        "domain": canon_domain,
                        "chunks": int(res.get("chunk_count") or 1),
                    }
                )
            except Exception as ex:
                item["ingested"] = False
                item["ingest_error"] = str(ex)[:160]
        conn.commit()

    # Queue newly ingested documents for Pattern Discovery
    for rec in ingested_records:
        doc_id = int(rec.get("document_id") or 0)
        if doc_id > 0:
            try:
                queue_document(doc_id)
            except Exception:
                pass

    return ingested_records


def synthesize_contemporary_insights(
    query: str,
    items: list[dict[str, Any]],
    fields: list[str],
) -> str:
    """Synthesize emerging meanings, new decisions, and expert perspectives from scraped items."""
    if not items:
        return "No contemporary articles or journal entries matched the query criteria."

    numbered_context: list[str] = []
    for idx, it in enumerate(items[:12], start=1):
        numbered_context.append(
            f"[{idx}] ({it.get('lane')} | {it.get('published_date')}) \"{it.get('title')}\" — "
            f"Authors: {it.get('authors')} | Venue: {it.get('publisher')}\n"
            f"Summary: {str(it.get('summary') or '')[:600]}"
        )
    context_block = "\n\n".join(numbered_context)
    field_str = ", ".join(fields) if fields else "Cross-Domain Scientific Inquiry"

    try:
        gw = get_gateway()
        if gw.describe().get("available"):
            prompt = (
                f"Query Matter: {query}\n"
                f"Target Domains / Scientific Fields: {field_str}\n\n"
                f"Contemporary Scraped Journal Articles & Expert Sources:\n{context_block}\n\n"
                "Provide a structured Contemporary Intelligence Synthesis with three clear sections:\n"
                "1. Emerging Meanings & Evolving Terminology (how new writers/researchers define or frame this topic today)\n"
                "2. Recent Decisions, Findings & Consensus Shifts (new empirical conclusions, policy/technical decisions, or paradigm shifts)\n"
                "3. Curated Library Integration & Actionable Takeaways (how these contemporary sources extend static curated knowledge)\n"
                "Cite the scraped sources inline using [1], [2], etc."
            )
            reply = gw.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are Sentinel's Contemporary Research & Semantic Shift Analyst. "
                            "Synthesize contemporary journal articles, preprints, and expert commentary with rigorous inline [1]..[N] citations."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=900,
            )
            if reply and len(str(reply).strip()) >= 80:
                return str(reply).strip()
    except Exception:
        pass

    # Deterministic structured synthesis fallback when LLM gateway is offline
    lines = [
        f"### Contemporary Intelligence & Semantic Shift Synthesis: {query}",
        f"**Target Domains / Fields:** {field_str} · **Contemporary Sources Analyzed:** {len(items)}",
        "",
        "#### 1. Emerging Meanings & Contemporary Framing",
    ]
    for idx, it in enumerate(items[:4], start=1):
        lines.append(
            f"- **[{idx}] {it.get('title')}** (*{it.get('publisher')}*, {it.get('published_date')}): "
            f"{str(it.get('summary') or '')[:260].rstrip()}..."
        )
    lines.append("")
    lines.append("#### 2. Recent Decisions, Findings & Expert Perspectives")
    for idx, it in enumerate(items[4:8], start=5):
        lines.append(
            f"- **[{idx}] {it.get('title')}** ({it.get('authors')}): "
            f"{str(it.get('summary') or '')[:240].rstrip()}..."
        )
    if len(items) <= 4:
        lines.append(
            f"- Contemporary publications [1–{len(items)}] reflect active methodological and policy updates beyond static textbook baselines."
        )
    lines.append("")
    lines.append(
        "#### 3. Curated Library Integration\n"
        "- All scraped contemporary articles and journal abstracts have been sanitized into their canonical Sentinel Domains and scientific fields so subsequent RAG queries and Pattern Discovery runs incorporate these latest meanings and decisions."
    )
    return "\n".join(lines)


def scrape_contemporary_sources(
    query: str,
    *,
    fields: list[str] | None = None,
    lanes: list[str] | None = None,
    max_per_lane: int = 3,
    ingest_to_library: bool = True,
) -> dict[str, Any]:
    """Run the multi-lane contemporary scraper, optionally ingest into the library, and synthesize."""
    clean_query = str(query or "").strip()
    if not clean_query:
        raise ValueError("Query matter is required for contemporary scraping.")

    clean_fields: list[str] = []
    for f in (fields or []):
        f_str = str(f or "").strip()
        if f_str and f_str not in clean_fields:
            clean_fields.append(f_str)

    # Enrich search query subtly if domain/field is specified and query is very short
    search_q = clean_query
    if len(clean_query.split()) <= 2 and clean_fields:
        first_f = clean_fields[0].replace("domain:", "").replace("-", " ")
        if first_f.lower() not in clean_query.lower():
            search_q = f"{clean_query} {first_f}"

    wanted_lanes = {s.strip().lower() for s in (lanes or ["openalex", "arxiv", "crossref", "europepmc", "web"]) if s.strip()}
    per_lane = max(1, min(6, int(max_per_lane or 3)))

    all_items: list[dict[str, Any]] = []
    if "openalex" in wanted_lanes:
        all_items.extend(_scrape_openalex_contemporary(search_q, max_results=per_lane))
    if "arxiv" in wanted_lanes:
        all_items.extend(_scrape_arxiv_contemporary(search_q, max_results=per_lane))
    if "crossref" in wanted_lanes:
        all_items.extend(_scrape_crossref_contemporary(search_q, max_results=per_lane))
    if "europepmc" in wanted_lanes or "pubmed" in wanted_lanes:
        all_items.extend(_scrape_europepmc_contemporary(search_q, max_results=per_lane))
    if "web" in wanted_lanes or "news" in wanted_lanes:
        all_items.extend(_scrape_contemporary_web_and_news(search_q, max_results=per_lane))

    # Deduplicate by normalized title
    deduped: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    primary_hint = clean_fields[0] if clean_fields else ""
    for it in all_items:
        norm_t = re.sub(r"[^a-z0-9]+", "", str(it.get("title") or "").lower())
        if not norm_t or norm_t in seen_titles:
            continue
        seen_titles.add(norm_t)
        canon_field, canon_domain = sanitize_field_and_domain(
            primary_hint,
            fallback_text=f"{it.get('title') or ''} {clean_query} {it.get('summary') or ''}",
        )
        it["scientific_field"] = canon_field
        it["domain"] = canon_domain
        deduped.append(it)

    ingested: list[dict[str, Any]] = []
    if ingest_to_library and deduped:
        ingested = ingest_contemporary_items(
            deduped,
            requested_fields=clean_fields,
            query=clean_query,
        )

    synthesis = synthesize_contemporary_insights(clean_query, deduped, clean_fields)

    return {
        "ok": True,
        "query": clean_query,
        "fields": clean_fields,
        "count": len(deduped),
        "ingested_count": len(ingested),
        "ingested": ingested,
        "items": deduped,
        "synthesis": synthesis,
    }
