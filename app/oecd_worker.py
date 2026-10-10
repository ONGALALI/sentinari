"""OECD SDMX REST API worker for Sentinari Sentinel research fields.

Integrates the official OECD SDMX REST web services (https://sdmx.oecd.org/public/rest)
directly into Sentinari's discovery and Sentinel knowledge library.

Discovery:
    search_oecd_datasets(query, field, limit) -> dataset candidates
    (Matches across OECD's ~1,500+ official statistical dataflows)

Ingestion:
    load_oecd_dataset_into_field(field, spec) -> fetches the dataset structure,
    queries observations via SDMX-REST, formats a readable Markdown factbook
    (metadata, dimensions, observation tables), and ingests it into the Sentinel
    knowledge library with full Article V provenance.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.parse
from pathlib import Path
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

OECD_BASE_URL = "https://sdmx.oecd.org/public/rest"
USER_AGENT = "Sentinari-Sentinel/1.0 (OECD SDMX Research Client)"

# Local disk cache directory to respect OECD's 60 req/hour limit
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "oecd_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MAX_ROWS_PER_FACTBOOK = 200

# Acronym bridge for economic / statistical terms
_ACRONYM_EXPANSIONS = {
    "gdp": "gross domestic product",
    "cpi": "consumer price index",
    "fdi": "foreign direct investment",
    "pop": "population",
    "lfs": "labour force",
    "unemp": "unemployment",
    "ghg": "greenhouse gas",
    "co2": "carbon dioxide",
    "rd": "research and development",
}


import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _get(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 45) -> requests.Response:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    try:
        resp = requests.get(url, params=params, headers=req_headers, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.exceptions.SSLError:
        # Fallback for environments with custom root certificates
        resp = requests.get(url, params=params, headers=req_headers, timeout=timeout, verify=False)
        resp.raise_for_status()
        return resp


# ----------------------------------------------------------------------
# Catalog & Discovery
# ----------------------------------------------------------------------
def get_oecd_catalog(use_cache: bool = True) -> list[dict[str, Any]]:
    """Retrieve the full catalog of ~1,500+ OECD dataflows, cached locally."""
    cache_file = CACHE_DIR / "catalog.json"
    if use_cache and cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    try:
        url = f"{OECD_BASE_URL}/dataflow/all"
        resp = _get(url, headers={"Accept": "application/json"}, timeout=30)
        data = resp.json().get("data", {})
        flows = data.get("dataflows", [])
        results: list[dict[str, Any]] = []
        for flow in flows:
            agency = str(flow.get("agencyID") or "OECD").strip()
            df_id = str(flow.get("id") or "").strip()
            version = str(flow.get("version") or "1.0").strip()
            name = str(flow.get("name") or df_id).strip()
            desc = str(flow.get("description") or "").strip()
            if agency and df_id:
                results.append({
                    "agency": agency,
                    "id": df_id,
                    "version": version,
                    "name": name,
                    "description": desc,
                })
        if results:
            cache_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        return results
    except Exception as ex:
        # Fallback to empty list or stale cache if fetch fails
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        return []


def search_oecd_datasets(query: str, field: str = "", limit: int = 10) -> dict[str, Any]:
    """Search OECD official statistical datasets for discovery candidates."""
    try:
        catalog = get_oecd_catalog(use_cache=True)
        q = str(query or "").lower().strip()
        words = set(re.findall(r"[a-z0-9]{3,}", q))

        # Check acronyms
        for acr, phrase in _ACRONYM_EXPANSIONS.items():
            if acr in words or any(p in words for p in phrase.split()):
                words.add(acr)
                words.update(phrase.split())

        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in catalog:
            haystack = f"{entry['id']} {entry['name']} {entry['description']} {entry['agency']}".lower()
            score = 0.0
            if q and q in haystack:
                score += 50.0  # Full phrase match
            for w in words:
                if w in haystack:
                    score += 10.0
                    if w in entry['name'].lower():
                        score += 15.0

            if score > 0:
                scored.append((-score, entry))

        scored.sort(key=lambda x: x[0])
        candidates: list[dict[str, Any]] = []
        for _score, item in scored[:max(1, min(25, int(limit or 10)))]:
            agency = item["agency"]
            df_id = item["id"]
            ver = item["version"]
            name = item["name"]
            desc = item["description"] or f"Official SDMX statistical dataflow {agency}:{df_id}"
            
            candidates.append({
                "source_type": "oecd",
                "source_url": f"{OECD_BASE_URL}/dataflow/{agency}/{df_id}/{ver}?references=all",
                "title": f"OECD/{agency}:{df_id} — {name}",
                "description": f"Official OECD SDMX dataset: {desc}"[:1000],
                "scientific_field": field,
                "target_persona": "gemma",
                "license": "OECD Open Data Terms of Service",
                "agency": agency,
                "dataset": df_id,
                "version": ver,
                "query": str(query or ""),
            })

        return {"ok": True, "candidates": candidates}
    except Exception as ex:
        return {"ok": False, "error": str(ex), "candidates": []}


# ----------------------------------------------------------------------
# Structure & Dimensions
# ----------------------------------------------------------------------
def get_oecd_structure(agency: str, df_id: str, version: str = "1.0", use_cache: bool = True) -> dict[str, Any]:
    """Fetch and parse dataflow dimensions & codelists using SDMX-JSON Structure 2.0."""
    safe_name = re.sub(r"[^\w@.-]", "_", f"{agency}_{df_id}_{version}")
    cache_file = CACHE_DIR / f"struct_{safe_name}.json"
    if use_cache and cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    url = f"{OECD_BASE_URL}/dataflow/{agency}/{df_id}/{version}?references=all"
    resp = _get(
        url,
        headers={"Accept": "application/vnd.sdmx.structure+json;version=2.0.0"},
        timeout=45,
    )
    raw = resp.json()
    data = raw.get("data", {})

    # 1. Codelists map
    codelists_map: dict[str, Any] = {}
    for cl in data.get("codelists", []):
        c_id = cl.get("id")
        codes = []
        for c in cl.get("codes", []):
            codes.append({"id": c.get("id"), "name": c.get("name", c.get("id"))})
        codelists_map[c_id] = {
            "id": c_id,
            "name": cl.get("name", c_id),
            "codes": codes,
        }

    # 2. Dimensions in positional order
    structures = data.get("dataStructures", [])
    dimensions_list: list[dict[str, Any]] = []
    if structures:
        ds = structures[0]
        dims = ds.get("dataStructureComponents", {}).get("dimensionList", {}).get("dimensions", [])
        dims_sorted = sorted(dims, key=lambda x: x.get("position", 0))
        for d in dims_sorted:
            dim_id = d.get("id")
            pos = d.get("position", 0)
            enum_urn = d.get("localRepresentation", {}).get("enumeration", "")
            cl_id = None
            if enum_urn:
                m = re.search(r"[:=]([A-Za-z0-9_@]+)\(", enum_urn)
                if m:
                    cl_id = m.group(1)

            matched_cl = codelists_map.get(cl_id) if cl_id else None
            codes = matched_cl["codes"] if matched_cl else []
            dim_name = matched_cl.get("name", dim_id) if matched_cl else dim_id

            dimensions_list.append({
                "id": dim_id,
                "position": pos,
                "name": dim_name,
                "codelist_id": cl_id or "",
                "codes": codes,
            })

    df_info = data.get("dataflows", [{}])[0] if data.get("dataflows") else {}
    result = {
        "agency": agency,
        "id": df_id,
        "version": version,
        "title": df_info.get("name", df_id),
        "description": df_info.get("description", ""),
        "dimensions": dimensions_list,
    }

    cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


# ----------------------------------------------------------------------
# Ingestion — SDMX-REST -> Markdown Factbook -> Sentinel Library
# ----------------------------------------------------------------------
def load_oecd_dataset_into_field(field: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Query OECD SDMX dataflow, compile an empirical factbook, and ingest into Sentinel."""
    from .ingestion import ingest_files

    resolved = _resolve_field(field)
    target_root = resolved["target_dir"] / "oecd"
    target_root.mkdir(parents=True, exist_ok=True)

    agency = str(spec.get("agency") or "OECD").strip() or "OECD"
    dataset = str(spec.get("dataset") or "").strip()
    version = str(spec.get("version") or "1.0").strip()
    query = str(spec.get("query") or "").strip()

    if not dataset:
        return {
            "ok": False,
            "field": resolved["field_name"],
            "field_slug": resolved["field_slug"],
            "downloaded": 0,
            "ingested": 0,
            "failed": 1,
            "items": [{"ok": False, "note": "No OECD dataset code provided; cannot load."}],
        }

    load_progress.stage("download", f"Fetching OECD structure for {agency}:{dataset}...")
    try:
        struct = get_oecd_structure(agency, dataset, version, use_cache=True)
    except Exception as ex:
        return {
            "ok": False,
            "field": resolved["field_name"],
            "field_slug": resolved["field_slug"],
            "downloaded": 0,
            "ingested": 0,
            "failed": 1,
            "items": [{"ok": False, "error": f"OECD structure fetch failed: {str(ex)[:160]}"}],
        }

    dims = struct.get("dimensions", [])
    dim_count = len(dims)

    # Build key: wildcards for each dimension
    # Example: 6 dimensions -> "....." (5 dots)
    key_wildcard = ".".join([""] * dim_count)

    # Construct OECD REST URL
    data_url = (
        f"{OECD_BASE_URL}/data/{agency},{dataset},{version}/{key_wildcard}"
        f"?format=csvfilewithlabels"
    )

    load_progress.stage("download", f"Querying observations from OECD SDMX REST API...")
    try:
        resp = _get(data_url, timeout=60)
        csv_text = resp.text
    except Exception as ex:
        # Fallback to standard csvfile if labels format is too large
        try:
            fallback_url = f"{OECD_BASE_URL}/data/{agency},{dataset},{version}/{key_wildcard}?format=csvfile"
            resp = _get(fallback_url, timeout=60)
            csv_text = resp.text
        except Exception as ex2:
            return {
                "ok": False,
                "field": resolved["field_name"],
                "field_slug": resolved["field_slug"],
                "downloaded": 0,
                "ingested": 0,
                "failed": 1,
                "items": [{"ok": False, "error": f"OECD observation fetch failed: {str(ex2)[:160]}"}],
            }

    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows or len(rows) <= 1:
        return {
            "ok": False,
            "field": resolved["field_name"],
            "field_slug": resolved["field_slug"],
            "downloaded": 0,
            "ingested": 0,
            "failed": 1,
            "items": [{"ok": False, "note": "OECD returned zero observations for this slice."}],
        }

    load_progress.stage("digest", f"Writing Markdown factbook for OECD {agency}:{dataset}...")
    headers = rows[0]
    data_rows = rows[1:MAX_ROWS_PER_FACTBOOK + 1]

    # Select key display columns (Time, Area/Country, Measure, Observation Value)
    lines: list[str] = [
        f"# OECD/{agency}:{dataset} — {struct.get('title')}",
        "",
        f"**Source:** OECD Official Statistics (SDMX-REST 2.1)",
        f"**Dataflow Endpoint:** `{data_url}`",
        f"**License:** OECD Open Data (Terms of Use)",
        f"**Observations Received:** {len(rows) - 1:,} total observations (first {len(data_rows)} presented below).",
        "",
        "## Empirical Dimensions",
        "",
    ]

    for d in dims:
        lines.append(f"- **{d['id']}** ({d['name']}): {len(d.get('codes', []))} allowable categories.")

    lines.append("")
    lines.append("## Statistical Observations Table")
    lines.append("")

    # Construct Markdown table
    col_limit = min(8, len(headers))
    lines.append("| " + " | ".join(headers[:col_limit]) + " |")
    lines.append("|" + "|".join(["---"] * col_limit) + "|")

    for r in data_rows:
        row_vals = [str(val).replace("|", "/") for val in r[:col_limit]]
        # Pad if short
        while len(row_vals) < col_limit:
            row_vals.append("")
        lines.append("| " + " | ".join(row_vals) + " |")

    if len(rows) - 1 > len(data_rows):
        lines.append(f"\n*(Truncated: {len(rows) - 1 - len(data_rows):,} additional observations omitted for library economy)*\n")

    safe_slug = slugify(f"{agency}_{dataset}")[:50]
    factbook_path = target_root / f"oecd-{safe_slug}.md"
    factbook_path.write_text("\n".join(lines), encoding="utf-8")

    result = ingest_files(
        [str(factbook_path)],
        metadata={**_field_metadata(resolved), "enforce_english": True},
        allow_embeddings=True,
    )

    ingested = int(result.get("ingested") or 0)
    if ingested == 0:
        try:
            factbook_path.unlink(missing_ok=True)
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
        "items": [{
            "ok": True,
            "kind": "timeseries-factbook",
            "title": factbook_path.name,
            "observations": len(rows) - 1,
            "path": str(factbook_path),
        }] + (result.get("items") or []),
        "status": get_sentinel_status(refresh_counts=False),
    }
