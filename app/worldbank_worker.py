"""World Bank / DBnomics time-series worker for the SMi Sentinel fields.

Owner directive (§74k, the Finance Industry challenge): World Bank economic
data as a new source inside Sentinari. The data actually flows through
DBnomics (https://api.db.nomics.world/v22) — a public REST API that
redistributes official providers (WB, IMF, OECD, ECB, ...) as normalized
time series: no API key, no client library, no cloud inference. §41/§45
zero-cloud stays intact, and the intake law is the same as every other
source: discovery proposes, nothing enters the library without the owner's
one-click approval.

Discovery:
    search_dbnomics_datasets(query, field, limit) -> dataset candidates
    (one candidate = one whole dataset, e.g. WB/WDI or IMF/GFSCOFOG)

Ingestion:
    load_dbnomics_dataset_into_field(field, spec) -> fetches a bounded,
    query-matched slice of the dataset's series and writes ONE readable
    Markdown factbook (period/value tables, values verbatim, NA where the
    provider reports no value), then digests it like every other lane.
    Time series read like documents, so the examiner can question her own
    macroeconomics library once an engine serves the gateway.

House principles adopted from DBnomics itself: values are NEVER modified,
NA stays NA, provider codes preserved as-is.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from . import load_progress
from .sentinel_domains import (
    _field_metadata,
    _note_last_ingest,
    _resolve_field,
    get_sentinel_status,
    slugify,
)

DBNOMICS_API_BASE = "https://api.db.nomics.world/v22"

# Owner-safety cap: one load ingests a bounded slice (the sequential queue
# keeps loads one at a time; the small machine stays comfortable). The rest
# of the dataset remains available — another load with a sharper query, or a
# bigger cap on the rig.
MAX_SERIES_PER_LOAD = 60
MAX_ROWS_PER_SERIES = 240
_QUERY_TOKEN_STOP = {
    "world", "development", "indicators", "database", "dataset", "data",
    "with", "from", "that", "this", "official", "statistics", "series",
}

# Providers label indicators with acronyms (WDI's GDP series is literally
# "GDP (current US$)"), so spelled-out queries need the acronym bridge to
# find them (live proof: 'gross domestic product' matched Gross domestic
# SAVINGS until this map landed).
_ACRONYM_EXPANSIONS = {
    "gdp": "gross domestic product",
    "gni": "gross national income",
    "cpi": "consumer price index",
    "fdi": "foreign direct investment",
    "hdi": "human development index",
    "vat": "value added tax",
}


def _get(url: str, params: dict[str, Any] | None = None, timeout: int = 45) -> dict[str, Any]:
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": "SMI-Sentinel/1.0 (local knowledge platform)"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


# ----------------------------------------------------------------------
# Discovery — one candidate per dataset
# ----------------------------------------------------------------------
def search_dbnomics_datasets(query: str, field: str = "", limit: int = 10) -> dict[str, Any]:
    """Full-text search over World Bank Official API v2 + DBnomics providers."""
    out: list[dict[str, Any]] = []
    try:
        from .intl_stats_worker import search_worldbank_direct

        out.extend(search_worldbank_direct(query, field=field, limit=max(3, min(6, int(limit or 10)))))
    except Exception:
        pass
    try:
        payload = _get(
            f"{DBNOMICS_API_BASE}/search",
            {"q": query, "limit": max(1, min(25, int(limit or 10)))},
            timeout=15,
        )
        docs = ((payload.get("results") or {}).get("docs")) or []
        seen_urls = {str(x.get("source_url") or "") for x in out}
        for d in docs:
            if not isinstance(d, dict):
                continue
            code = str(d.get("code") or "").strip()
            provider = str(d.get("provider_code") or "").strip()
            if not code or not provider:
                continue
            url = f"https://db.nomics.world/{provider}/{code}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            name = str(d.get("name") or code)
            nb_series = int(d.get("nb_series") or 0)
            desc = re.sub(r"<[^>]+>", " ", str(d.get("description") or "")).strip()
            out.append(
                {
                    "source_type": "worldbank",
                    "source_url": url,
                    "title": f"{provider}/{code} — {name}",
                    "description": (
                        f"Official time-series dataset ({nb_series:,} series) redistributed by "
                        f"DBnomics from provider {provider}. {desc}"
                    )[:1000],
                    "scientific_field": field,
                    "target_persona": "gemma",
                    "license": "Official statistics (provider terms via DBnomics)",
                    "provider": provider,
                    "dataset": code,
                    "nb_series": nb_series,
                    "query": str(query or ""),
                }
            )
    except Exception:
        pass
    return {"ok": True, "candidates": out[: max(4, min(25, int(limit or 10)))]}


# ----------------------------------------------------------------------
# Dataset dimensions — where the query is matched against real value labels
# ----------------------------------------------------------------------
def _dataset_dimensions(provider: str, dataset: str) -> dict[str, Any]:
    """Return {order: [dim codes], labels: {dim: {value_code: label}}, name, nb_series}."""
    payload = _get(f"{DBNOMICS_API_BASE}/datasets/{provider}/{dataset}", timeout=45)
    docs = payload.get("datasets")
    doc = (docs.get("docs") or [{}])[0] if isinstance(docs, dict) else (docs or [{}])[0]
    order = [str(c) for c in (doc.get("dimensions_codes_order") or [])]
    labels = {
        str(dim): {str(k): str(v) for k, v in (vals or {}).items()}
        for dim, vals in (doc.get("dimensions_values_labels") or {}).items()
    }
    return {
        "order": order,
        "labels": labels,
        "name": str(doc.get("name") or dataset),
        "nb_series": int(doc.get("nb_series") or 0),
    }


def _primary_dimension(meta: dict[str, Any]) -> str:
    """The dimension with the most distinct values (WDI: 'indicator') — the
    axis a query naturally speaks to."""
    best, best_n = "", -1
    for dim in meta["order"]:
        n = len(meta["labels"].get(dim, {}))
        if n > best_n:
            best, best_n = dim, n
    return best


def _match_axis_values(query: str, meta: dict[str, Any], axis: str, cap: int = 6) -> list[str]:
    """Pick axis value codes whose labels share words with the owner's query.

    Acronym law (earned in live proof): providers title series with acronyms
    ("GDP (current US$)") while owners type the words ("gross domestic
    product") — and hundreds of unrelated labels mention the acronym in
    passing ("% of GDP"). So: engage an acronym when the query carries it OR
    its full phrase, add the alias as a token, and boost +2 for a whole-word
    acronym in the label and +4 when it appears in the series CODE (codes are
    family-unique: NY.GDP.* is the GDP family). Phrase-substring hits alone
    can no longer outrank the true series.
    """
    q = str(query or "").lower()
    words = set(re.findall(r"[a-z]{4,}", q))
    active: list[str] = []
    for acronym, phrase in _ACRONYM_EXPANSIONS.items():
        phrase_words = set(phrase.split())
        if re.search(rf"\b{re.escape(acronym)}\b", q) or (phrase_words & words) == phrase_words:
            active.append(acronym)
            words.add(acronym)
    tokens = sorted(words - _QUERY_TOKEN_STOP)
    if not tokens:
        return []
    scored: list[tuple[float, int, str]] = []
    for code, label in meta["labels"].get(axis, {}).items():
        lowered = label.lower()
        token_hits = sum(1 for t in tokens if t in lowered)
        acronym_boost = 0
        for acronym in active:
            if lowered.startswith(acronym):
                acronym_boost += 5
            elif re.search(rf"\b{re.escape(acronym)}\b", lowered):
                acronym_boost += 2
            if acronym.upper() in code.upper():
                acronym_boost += 4
        if token_hits:
            score = 10.0 * token_hits + acronym_boost
        elif active and acronym_boost:
            # Acronym-only candidate: rank by how canonical the title is —
            # a series TITLED by the acronym ("GDP (current US$)") outranks
            # one that merely mentions it ("% of GDP"), short titles first.
            score = acronym_boost / 100.0
        else:
            continue
        scored.append((-score, len(label), code))
    scored.sort()
    return [code for _s, _l, code in scored[:cap]]


# ----------------------------------------------------------------------
# Ingestion — bounded slice -> one Markdown factbook -> the library
# ----------------------------------------------------------------------
def load_dbnomics_dataset_into_field(field: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Download a bounded, query-matched slice of one DBnomics dataset and
    digest it into the Sentinel field as a readable factbook."""
    from .ingestion import ingest_files

    resolved = _resolve_field(field)
    target_root = resolved["target_dir"] / "worldbank"
    target_root.mkdir(parents=True, exist_ok=True)

    provider = str(spec.get("provider") or "WB").strip() or "WB"
    dataset = str(spec.get("dataset") or "").strip()
    if not dataset:
        return {"ok": False, "field": resolved["field_name"], "field_slug": resolved["field_slug"],
                "downloaded": 0, "ingested": 0, "failed": 1,
                "items": [{"ok": False, "note": "No dataset code on the candidate; cannot load."}]}
    query = str(spec.get("query") or "")
    forced = [str(x).strip() for x in (spec.get("indicators") or []) if str(x).strip()]

    if spec.get("indicator") or "api.worldbank.org" in str(spec.get("source_url") or ""):
        from .intl_stats_worker import load_intl_stat_dataset_into_field

        return load_intl_stat_dataset_into_field(field, "worldbank", spec)

    load_progress.stage("download", f"Reading {provider}/{dataset} dimensions from DBnomics...")
    try:
        meta = _dataset_dimensions(provider, dataset)
    except Exception:
        from .intl_stats_worker import load_intl_stat_dataset_into_field

        return load_intl_stat_dataset_into_field(field, "worldbank", spec)

    axis = _primary_dimension(meta)
    axis_filter: dict[str, list[str]] = {}
    slice_note = "first series in dataset order"
    axis_codes: list[str] = forced or (_match_axis_values(query, meta, axis) if axis else [])
    if axis and axis_codes:
        axis_filter[axis] = axis_codes
        chosen = ", ".join(meta["labels"].get(axis, {}).get(c, c) for c in axis_codes[:3])
        more = "" if len(axis_codes) <= 3 else f" (+{len(axis_codes) - 3} more)"
        slice_note = f"{axis}: {chosen}{more}"

    # Page through the series until the load cap — cancellation checked
    # between pages so the owner's Cancel lands at the next boundary.
    series: list[dict[str, Any]] = []
    offset = 0
    page = 60
    while len(series) < MAX_SERIES_PER_LOAD:
        if load_progress.cancel_requested():
            raise load_progress.LoadCancelled("Load cancelled by owner during the series fetch.")
        params: dict[str, Any] = {"observations": "true", "limit": page, "offset": offset}
        if axis_filter:
            params["dimensions"] = json.dumps(axis_filter)
        try:
            payload = _get(f"{DBNOMICS_API_BASE}/series/{provider}/{dataset}", params, timeout=60)
        except Exception as ex:
            if series:
                break  # keep the slice we already have rather than failing whole
            return {"ok": False, "field": resolved["field_name"], "field_slug": resolved["field_slug"],
                    "downloaded": 0, "ingested": 0, "failed": 1,
                    "items": [{"ok": False, "error": f"Series fetch failed: {str(ex)[:160]}"}]}
        docs = ((payload.get("series") or {}).get("docs")) or []
        if not docs:
            break
        for sd in docs:
            series.append(sd)
            if len(series) >= MAX_SERIES_PER_LOAD:
                break
        offset += page
        if offset >= int(((payload.get("series") or {}).get("num_found") or 0)):
            break
        load_progress.stage("download", f"Fetched {len(series)} series from {provider}/{dataset}...")

    if not series:
        return {"ok": False, "field": resolved["field_name"], "field_slug": resolved["field_slug"],
                "downloaded": 0, "ingested": 0, "failed": 1,
                "items": [{"ok": False, "note": "The slice matched zero series."}]}

    load_progress.stage("digest", f"Writing the factbook for {len(series)} series and digesting it...")

    axis_label = axis.replace("_", " ").title() if axis else "Series"
    lines: list[str] = [
        f"# {provider}/{dataset} — {meta['name']}",
        "",
        f"Source: DBnomics ({DBNOMICS_API_BASE}) — official statistics redistributed as-is.",
        f"Browse: https://db.nomics.world/{provider}/{dataset}",
        f"Dataset size: {meta['nb_series']:,} series. Slice ingested here: {len(series)} series ({slice_note}).",
        "Values are verbatim from the provider; NA marks periods with no reported value.",
        "",
    ]
    for sd in series:
        if load_progress.cancel_requested():
            raise load_progress.LoadCancelled("Load cancelled by owner while writing the factbook.")
        dims = sd.get("dimensions") or {}
        axis_value = str(dims.get(axis, "")) if axis else ""
        axis_text = f" ({axis_label}: {meta['labels'].get(axis, {}).get(axis_value, axis_value)})" if axis else ""
        lines.append(f"## {sd.get('series_name') or sd.get('series_code')}{axis_text}")
        lines.append("")
        lines.append(f"Series code: `{sd.get('series_code')}` · Frequency: {sd.get('@frequency') or 'n/a'}")
        lines.append("")
        lines.append("| Period | Value |")
        lines.append("|---|---|")
        periods = sd.get("period") or []
        values = sd.get("value") or []
        truncated = False
        for idx, (period, value) in enumerate(zip(periods, values)):
            if idx >= MAX_ROWS_PER_SERIES:
                truncated = True
                break
            shown = "NA" if value is None else (str(int(value)) if isinstance(value, float) and value.is_integer() else str(value))
            lines.append(f"| {period} | {shown} |")
        if truncated or len(periods) > len(values):
            lines.append(f"| … | ({len(periods)} periods total; first {MAX_ROWS_PER_SERIES} shown) |")
        lines.append("")

    slice_slug = slugify(slice_note)[:40] or "slice"
    # Windows trap found in the first live proof: dataset codes carry colons
    # (WEO:2022-04) and a raw colon in the filename is an NTFS alternate-
    # data-stream separator — the write vanishes into a stream and a 0-byte
    # husk stays behind, failing the digest. Slugify every path component.
    factbook = target_root / f"dbnomics-{slugify(provider)}-{slugify(dataset)}-{slice_slug}.md"
    factbook.write_text("\n".join(lines), encoding="utf-8")

    result = ingest_files(
        [str(factbook)],
        metadata={**_field_metadata(resolved), "enforce_english": True},
        allow_embeddings=True,
    )
    ingested = int(result.get("ingested") or 0)
    if ingested == 0:
        # Owner directive: a failed digest leaves nothing behind.
        try:
            factbook.unlink(missing_ok=True)
        except Exception:
            pass
    else:
        _note_last_ingest(resolved["field_slug"])
    return {
        "ok": ingested > 0,
        "field": resolved["field_name"],
        "field_slug": resolved["field_slug"],
        "downloaded": 1,
        "ingested": ingested,
        "failed": int(result.get("failed") or 0),
        "items": [{"ok": True, "kind": "timeseries-factbook", "title": factbook.name,
                   "series": len(series), "path": str(factbook)}] + (result.get("items") or []),
        "status": get_sentinel_status(refresh_counts=False),
    }
