"""Official International Statistical & Financial APIs Worker for Sentinari.

Integrates the five official global statistical & monetary authorities directly
into Sentinari's Playground discovery and Sentinel Knowledge Grid:
  1. Eurostat — Entire European Union statistics
     https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1
  2. IMF — International Monetary Fund finances
     https://dataservices.imf.org/REST/SDMX_JSON.svc
  3. ECB — European Central Bank financial data
     https://data-api.ecb.europa.eu/service
  4. BIS — Bank for International Settlements
     https://stats.bis.org/api/v1
  5. UN Data — United Nations statistical division
     https://data.un.org/ws/rest

Also enriches World Bank (`worldbank`) direct Indicator & Data Catalog discovery
alongside DBnomics so World Bank candidates always appear reliably.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests
import urllib3

from . import load_progress
from .sentinel_domains import _resolve_field, slugify

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EUROSTAT_SDMX_BASE = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1"
EUROSTAT_STATS_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
IMF_SDMX_BASE = "https://dataservices.imf.org/REST/SDMX_JSON.svc"
IMF_DATAMAPPER_BASE = "https://www.imf.org/external/datamapper/api/v1"
ECB_SDMX_BASE = "https://data-api.ecb.europa.eu/service"
BIS_SDMX_BASE = "https://stats.bis.org/api/v1"
UNDATA_SDMX_BASE = "https://data.un.org/ws/rest"
WORLDBANK_API_BASE = "https://api.worldbank.org/v2"

USER_AGENT = "Sentinari-Sentinel/1.0 (Official SDMX Statistical Research Client)"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "intl_stats_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Curated Flagship Catalogs (instant discovery + resilient fallback if an
# upstream SDMX XML/JSON catalog endpoint throttles or times out)
# ---------------------------------------------------------------------------

CURATED_CATALOGS: dict[str, list[dict[str, Any]]] = {
    "eurostat": [
        {
            "code": "nama_10_gdp",
            "agency": "ESTAT",
            "title": "GDP and main components (output, expenditure and income)",
            "description": "Eurostat official national accounts (ESA 2010): Gross domestic product at market prices, final consumption, gross capital formation, exports and imports across all EU Member States.",
            "keywords": "gdp economics macroeconomics growth expenditure income national accounts europe eu finance",
        },
        {
            "code": "prc_hicp_manr",
            "agency": "ESTAT",
            "title": "HICP - monthly data (annual rate of change, inflation)",
            "description": "Harmonised Indices of Consumer Prices (HICP) measuring euro area and EU consumer price inflation across COICOP categories.",
            "keywords": "inflation cpi prices consumer monetary economics finance eurostat eu",
        },
        {
            "code": "une_rt_m",
            "agency": "ESTAT",
            "title": "Unemployment by sex and age - monthly data",
            "description": "European Union Labour Force Survey (EU-LFS) harmonized monthly unemployment rates across member states and demographic cohorts.",
            "keywords": "unemployment labor employment society economics sociology demographics",
        },
        {
            "code": "env_air_gge",
            "agency": "ESTAT",
            "title": "Greenhouse gas emissions by source sector (EEA & Eurostat)",
            "description": "Total greenhouse gas emissions (CO2, CH4, N2O, F-gases) by UNFCCC CRF sector across European economies.",
            "keywords": "climate environment greenhouse gas emissions co2 ecology earth sciences",
        },
        {
            "code": "nrg_bal_c",
            "agency": "ESTAT",
            "title": "Complete energy balances (Eurostat Official Energy Statistics)",
            "description": "Comprehensive physical energy balances covering primary production, imports, transformation, renewables, nuclear, and final consumption in the EU.",
            "keywords": "energy physics engineering electricity renewables nuclear power fuels",
        },
        {
            "code": "hlth_cd_aro",
            "agency": "ESTAT",
            "title": "Causes of death - deaths by country of residence and occurrence",
            "description": "European public health mortality registry classified by ICD-10 cause of death, age, and region.",
            "keywords": "health medicine public health mortality epidemiology disease biology",
        },
        {
            "code": "rd_e_gerdtot",
            "agency": "ESTAT",
            "title": "GERD (Gross domestic expenditure on R&D) by sector of performance",
            "description": "Science, technology, and innovation expenditure across business enterprise, government, and higher education sectors in Europe.",
            "keywords": "research development science technology engineering innovation computer ai",
        },
        {
            "code": "gov_10dd_edpt1",
            "agency": "ESTAT",
            "title": "Government deficit/surplus, debt and associated data (Maastricht EDP)",
            "description": "General government consolidated gross debt and fiscal balance under the Excessive Deficit Procedure across EU member states.",
            "keywords": "government debt fiscal deficit law policy political science economics",
        },
        {
            "code": "crim_off_cat",
            "agency": "ESTAT",
            "title": "Recorded offences by offence category (Police & Criminal Justice)",
            "description": "Official European criminal justice statistics on recorded crimes, legal enforcement, and cross-border offenses.",
            "keywords": "law crime justice international law sociology political science",
        },
        {
            "code": "migr_asyappctza",
            "agency": "ESTAT",
            "title": "Asylum and first time asylum applicants by citizenship, age and sex",
            "description": "European migration, refugee protection, conflict displacement, and international asylum law statistics.",
            "keywords": "migration asylum refugees war conflict international law anthropology sociology",
        },
    ],
    "imf": [
        {
            "code": "IFS",
            "indicator": "PCPIPCH",
            "agency": "IMF",
            "title": "International Financial Statistics (IFS) — Global Macroeconomic & Monetary Series",
            "description": "IMF's principal statistical dataset covering exchange rates, international liquidity, interest rates, money and banking, prices, production, and national accounts for 190+ countries.",
            "keywords": "imf finance monetary exchange rates interest rates inflation gdp banking economics",
        },
        {
            "code": "WEO",
            "indicator": "NGDP_RPCH",
            "agency": "IMF",
            "title": "World Economic Outlook (WEO) — Real GDP Growth, Inflation & Fiscal Balances",
            "description": "IMF staff analysis and projections of global economic developments, real GDP growth, inflation, fiscal balances, debt, and current account positions.",
            "keywords": "imf world economic outlook gdp growth inflation debt fiscal economics policy",
        },
        {
            "code": "BOP",
            "indicator": "BCA_NGDPD",
            "agency": "IMF",
            "title": "Balance of Payments and International Investment Position (BOP/IIP)",
            "description": "Cross-border transactions in goods, services, primary/secondary income, capital flows, foreign direct investment, and reserve assets.",
            "keywords": "imf balance of payments trade investment capital flows currency economics",
        },
        {
            "code": "GFSMAB",
            "indicator": "GGXWDG_NGDP",
            "agency": "IMF",
            "title": "Government Finance Statistics (GFS) — Sovereign Revenue, Expenditure & Debt",
            "description": "Comprehensive fiscal operations of general government, tax revenue, defense/military expenditure, public health spending, and sovereign debt.",
            "keywords": "imf government finance tax debt fiscal policy law war defense public health",
        },
        {
            "code": "DOT",
            "indicator": "TM_RPCH",
            "agency": "IMF",
            "title": "Direction of Trade Statistics (DOTS) — Bilateral Merchandise Exports & Imports",
            "description": "Value of merchandise exports and imports disaggregated according to a country's primary trading partners and sanctions/tariff regimes.",
            "keywords": "imf trade exports imports sanctions geopolitics international law economics",
        },
        {
            "code": "FSI",
            "indicator": "NGDPD",
            "agency": "IMF",
            "title": "Financial Soundness Indicators (FSI) — Systemic Banking & Capital Adequacy",
            "description": "Macroprudential indicators of the current financial health and soundness of financial institutions, corporate, and household sectors.",
            "keywords": "imf banking systemic risk capital adequacy credit finance economics",
        },
    ],
    "ecb": [
        {
            "code": "EXR",
            "agency": "ECB",
            "title": "Euro Foreign Exchange Reference Rates (EXR)",
            "description": "Daily, monthly, and annual Euro foreign exchange reference rates published by the European Central Bank against 40+ global currencies.",
            "keywords": "ecb exchange rates currency forex euro monetary finance economics",
        },
        {
            "code": "FM",
            "agency": "ECB",
            "title": "Financial Markets & Key ECB Policy Interest Rates (FM)",
            "description": "ECB official policy interest rates, EURIBOR, €STR, euro area sovereign bond yields, money market rates, and equity indices.",
            "keywords": "ecb interest rates yield curve bonds financial markets monetary policy finance",
        },
        {
            "code": "ICP",
            "agency": "ECB",
            "title": "Indices of Consumer Prices (ICP) — Euro Area Inflation Dynamics",
            "description": "Harmonised Indices of Consumer Prices (HICP), core inflation, energy and food price sub-indices monitored by the ECB Governing Council.",
            "keywords": "ecb inflation prices hicp consumer monetary policy economics",
        },
        {
            "code": "BSI",
            "agency": "ECB",
            "title": "Balance Sheet Items (BSI) — Monetary Aggregates M1, M2, M3 & Credit Counterparts",
            "description": "Consolidated balance sheet of euro area Monetary Financial Institutions (MFIs), monetary aggregates, and credit to households and corporations.",
            "keywords": "ecb balance sheet money supply m1 m2 m3 credit banking finance",
        },
        {
            "code": "CISS",
            "agency": "ECB",
            "title": "Composite Indicator of Systemic Stress (CISS) — Financial Stability",
            "description": "ECB macroprudential systemic stress index measuring contemporaneous instability in the financial system across money, bond, equity, and FX markets.",
            "keywords": "ecb systemic risk financial crisis stress stability macroprudential economics",
        },
        {
            "code": "MIR",
            "agency": "ECB",
            "title": "MFI Interest Rate Statistics (MIR) — Retail & Corporate Lending/Deposit Rates",
            "description": "Interest rates applied by euro area Monetary Financial Institutions to deposits and loans vis-à-vis households and non-financial corporations.",
            "keywords": "ecb lending deposit mortgage rates banking credit households finance",
        },
    ],
    "bis": [
        {
            "code": "WS_CBPOL",
            "agency": "BIS",
            "title": "BIS Central Bank Policy Rates — Global Monetary Policy Historical & Live Series",
            "description": "Bank for International Settlements dataset of official central bank policy interest rates across 40+ advanced and emerging economies.",
            "keywords": "bis central bank policy rates interest rates monetary finance economics",
        },
        {
            "code": "WS_TC",
            "agency": "BIS",
            "title": "BIS Total Credit to the Non-Financial Sector (Credit-to-GDP Gaps & Leverage)",
            "description": "Total credit to general government, non-financial corporations, and households across countries, benchmarked for Basel III countercyclical capital buffers.",
            "keywords": "bis credit debt leverage gdp banking systemic risk finance economics",
        },
        {
            "code": "WS_LBS_D_PUB",
            "agency": "BIS",
            "title": "BIS Locational Banking Statistics (Cross-Border Bank Claims & Liabilities)",
            "description": "International banking activity measuring cross-border claims and liabilities of internationally active banks by currency, counterparty, and country.",
            "keywords": "bis cross border banking international finance liquidity capital flows",
        },
        {
            "code": "WS_GLI",
            "agency": "BIS",
            "title": "BIS Global Liquidity Indicators (Foreign Currency Credit in USD, EUR, JPY)",
            "description": "Global credit denominated in USD, EUR, and JPY extended to non-resident borrowers outside the respective currency areas.",
            "keywords": "bis global liquidity dollar euro credit international finance economics",
        },
        {
            "code": "WS_SPP",
            "agency": "BIS",
            "title": "BIS Selected Residential Property Prices (Global Housing & Real Estate Cycles)",
            "description": "Cross-country nominal and real residential property price indices compiled by the Bank for International Settlements.",
            "keywords": "bis property housing prices real estate inflation household wealth economics",
        },
        {
            "code": "WS_DSR",
            "agency": "BIS",
            "title": "BIS Debt Service Ratios for the Private Non-Financial Sector",
            "description": "Share of income used to service debt (interest payments and amortisations) in the household and corporate sectors — early warning indicator of banking crises.",
            "keywords": "bis debt service ratio financial crisis default risk banking economics",
        },
    ],
    "undata": [
        {
            "code": "DF_UNDATA_COUNTRYDATA",
            "agency": "UNSD",
            "title": "UN Data Country Statistical Profiles — Demographic, Social, Economic & Environmental",
            "description": "United Nations Statistical Division (UNSD) official country indicators covering population, national accounts, education, health, gender, and environment across UN Member States.",
            "keywords": "un data united nations country statistics population economics sociology health",
        },
        {
            "code": "DF_SDG_GLH",
            "agency": "IAEG-SDGs",
            "title": "United Nations Global SDG Indicators Database (Sustainable Development Goals 1–17)",
            "description": "Official UN Statistical Commission dataset tracking global progress across all 17 Sustainable Development Goals: poverty, hunger, health, education, clean energy, climate, peace and justice.",
            "keywords": "un sdg sustainable development poverty health climate peace justice international law",
        },
        {
            "code": "DF_UNData_UNFCC",
            "agency": "UNSD",
            "title": "UNFCCC Greenhouse Gas Inventory Data (United Nations Climate Statistics)",
            "description": "Anthropogenic emissions by sources and removals by sinks of greenhouse gases not controlled by the Montreal Protocol reported to the UN.",
            "keywords": "un climate greenhouse gas emissions co2 environment ecology earth sciences",
        },
        {
            "code": "NASEC",
            "agency": "UNSD",
            "title": "UN National Accounts Official Country Data (SNA 2008 Main Aggregates)",
            "description": "United Nations System of National Accounts (SNA) GDP, value added by industry, and expenditure components for over 200 countries and areas.",
            "keywords": "un national accounts gdp economics trade development finance",
        },
        {
            "code": "UNODC_CRIME_JUSTICE",
            "agency": "UNODC",
            "title": "UN Rule of Law, International Treaties, Conflict & Criminal Justice Statistics",
            "description": "United Nations statistics on international law compliance, armed conflict casualties, displaced populations, homicides, and justice systems.",
            "keywords": "un law international law war conflict treaties human rights religion sociology political science",
        },
        {
            "code": "UN_POP_WPP",
            "agency": "UNPD",
            "title": "UN World Population Prospects — Global Fertility, Mortality, Life Expectancy & Migration",
            "description": "United Nations Population Division demographic estimates and projections (1950–2100) for all countries and regions.",
            "keywords": "un population demographics mortality fertility life expectancy public health anthropology",
        },
    ],
}


def _http_get_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 12) -> Any:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    try:
        resp = requests.get(url, params=params, headers=req_headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.SSLError:
        resp = requests.get(url, params=params, headers=req_headers, timeout=timeout, verify=False)
        resp.raise_for_status()
        return resp.json()


def _http_get_text(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 12) -> str:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    try:
        resp = requests.get(url, params=params, headers=req_headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.SSLError:
        resp = requests.get(url, params=params, headers=req_headers, timeout=timeout, verify=False)
        resp.raise_for_status()
        return resp.text


def _parse_sdmx_xml_dataflows(xml_text: str, default_agency: str) -> list[dict[str, Any]]:
    """Parse SDMX 2.1 Structure XML `<str:Dataflow>` elements into catalog dicts."""
    flows: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower()
            if tag == "dataflow":
                df_id = str(elem.attrib.get("id") or "").strip()
                agency = str(elem.attrib.get("agencyID") or default_agency).strip()
                version = str(elem.attrib.get("version") or "1.0").strip()
                name_en = ""
                desc_en = ""
                for child in elem:
                    ctag = child.tag.split("}")[-1].lower()
                    lang = ""
                    for k, v in child.attrib.items():
                        if k.endswith("lang"):
                            lang = str(v).lower()
                    txt = (child.text or "").strip()
                    if ctag == "name" and txt:
                        if lang in ("en", "") or not name_en:
                            name_en = txt
                    elif ctag == "description" and txt:
                        if lang in ("en", "") or not desc_en:
                            desc_en = txt
                if df_id and name_en:
                    flows.append(
                        {
                            "code": df_id,
                            "agency": agency,
                            "version": version,
                            "title": name_en,
                            "description": desc_en or f"Official {default_agency} SDMX 2.1 dataflow ({df_id}).",
                            "keywords": f"{df_id.lower()} {name_en.lower()} {desc_en.lower()}",
                        }
                    )
    except Exception:
        pass
    return flows


def _get_live_or_cached_catalog(source_type: str) -> list[dict[str, Any]]:
    """Return merged live SDMX dataflows + curated flagship catalog for a source."""
    stype = str(source_type or "").lower().strip()
    cache_file = CACHE_DIR / f"catalog_{stype}.json"
    curated = list(CURATED_CATALOGS.get(stype) or [])

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, list) and len(cached) >= len(curated):
                return cached
        except Exception:
            pass

    live_flows: list[dict[str, Any]] = []
    try:
        if stype == "eurostat":
            xml_txt = _http_get_text(
                f"{EUROSTAT_SDMX_BASE}/dataflow/ESTAT/all/latest",
                params={"detail": "allstubs"},
                headers={"Accept": "application/vnd.sdmx.structure+xml;version=2.1"},
                timeout=8,
            )
            live_flows = _parse_sdmx_xml_dataflows(xml_txt, "ESTAT")[:400]
        elif stype == "ecb":
            xml_txt = _http_get_text(
                f"{ECB_SDMX_BASE}/dataflow/ECB/all/latest",
                params={"detail": "allstubs"},
                headers={"Accept": "application/vnd.sdmx.structure+xml;version=2.1"},
                timeout=8,
            )
            live_flows = _parse_sdmx_xml_dataflows(xml_txt, "ECB")[:300]
        elif stype == "bis":
            xml_txt = _http_get_text(
                f"{BIS_SDMX_BASE}/dataflow/BIS/all/latest",
                params={"detail": "allstubs"},
                headers={"Accept": "application/vnd.sdmx.structure+xml;version=2.1"},
                timeout=8,
            )
            live_flows = _parse_sdmx_xml_dataflows(xml_txt, "BIS")[:300]
        elif stype == "undata":
            xml_txt = _http_get_text(
                f"{UNDATA_SDMX_BASE}/dataflow/all/all/latest",
                headers={"Accept": "application/vnd.sdmx.structure+xml;version=2.1"},
                timeout=8,
            )
            live_flows = _parse_sdmx_xml_dataflows(xml_txt, "UNSD")[:300]
        elif stype == "imf":
            data = _http_get_json(f"{IMF_DATAMAPPER_BASE}/indicators", timeout=8)
            indicators = (data.get("indicators") if isinstance(data, dict) else {}) or {}
            for ind_code, info in list(indicators.items())[:250]:
                if not isinstance(info, dict):
                    continue
                lbl = str(info.get("label") or ind_code).strip()
                dsc = str(info.get("Anchor") or info.get("description") or "").strip()
                unit = str(info.get("unit") or "").strip()
                if lbl:
                    live_flows.append(
                        {
                            "code": f"IMF_{ind_code}",
                            "indicator": str(ind_code),
                            "agency": "IMF",
                            "title": f"{lbl} ({unit})" if unit else lbl,
                            "description": dsc or f"IMF Official Financial & Macroeconomic Indicator ({ind_code}).",
                            "keywords": f"imf {ind_code.lower()} {lbl.lower()} {dsc.lower()}",
                        }
                    )
    except Exception:
        pass

    seen_codes = {str(item.get("code") or "").upper() for item in curated}
    merged = list(curated)
    for lf in live_flows:
        c = str(lf.get("code") or "").upper()
        if c and c not in seen_codes:
            seen_codes.add(c)
            merged.append(lf)

    if len(merged) > len(curated):
        try:
            cache_file.write_text(json.dumps(merged[:500], ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return merged


def _source_meta(source_type: str, code: str, agency: str) -> tuple[str, str, str]:
    """Return (source_url, title_prefix, license_text) for each official statistical provider."""
    st = str(source_type or "").lower()
    if st == "eurostat":
        return (
            f"{EUROSTAT_SDMX_BASE}/dataflow/{agency or 'ESTAT'}/{code}/1.0",
            f"Eurostat/{code}",
            "Eurostat Open Data (European Union Reuse Policy CC-BY 4.0)",
        )
    if st == "imf":
        clean_code = code.replace("IMF_", "")
        return (
            f"{IMF_SDMX_BASE}/Dataflow/{clean_code}",
            f"IMF/{clean_code}",
            "IMF Data Terms of Use (International Monetary Fund)",
        )
    if st == "ecb":
        return (
            f"{ECB_SDMX_BASE}/dataflow/{agency or 'ECB'}/{code}/1.0",
            f"ECB/{code}",
            "ECB Statistical Data Warehouse Open Terms",
        )
    if st == "bis":
        return (
            f"{BIS_SDMX_BASE}/dataflow/{agency or 'BIS'}/{code}/1.0",
            f"BIS/{code}",
            "BIS Open Statistics Terms (Bank for International Settlements)",
        )
    if st == "undata":
        return (
            f"{UNDATA_SDMX_BASE}/dataflow/{agency or 'UNSD'}/{code}/1.0",
            f"UN-Data/{code}",
            "United Nations Statistical Division Open Data Terms",
        )
    return (f"https://db.nomics.world/{agency}/{code}", f"{agency}/{code}", "Official Statistics")


def search_intl_stat_provider(
    source_type: str,
    query: str,
    field: str = "",
    limit: int = 8,
    page: int = 1,
) -> dict[str, Any]:
    """Search one of the 5 international statistical providers (eurostat, imf, ecb, bis, undata)."""
    st = str(source_type or "").lower().strip()
    catalog = _get_live_or_cached_catalog(st)
    q = str(query or "").lower().strip()
    f_low = str(field or "").lower().replace("-", " ")
    tokens = [t for t in re.findall(r"[a-z0-9]{3,}", f"{q} {f_low}") if t not in {"the", "and", "for", "with", "from"}]

    scored: list[tuple[float, int, dict[str, Any]]] = []
    for idx, entry in enumerate(catalog):
        haystack = f"{entry.get('code', '')} {entry.get('title', '')} {entry.get('description', '')} {entry.get('keywords', '')}".lower()
        score = 0.0
        if q and q in haystack:
            score += 60.0
        for tok in tokens:
            if tok in haystack:
                score += 12.0
                if tok in str(entry.get("title") or "").lower():
                    score += 18.0
        # Ensure flagship datasets from each requested authority still surface as top relevant
        # statistical context even on general scientific queries.
        if score == 0.0 and idx < len(CURATED_CATALOGS.get(st) or []):
            score = max(1.0, 8.0 - idx * 0.5)
        if score > 0:
            scored.append((-score, idx, entry))

    scored.sort(key=lambda x: (x[0], x[1]))
    per_page = max(1, min(25, int(limit or 8)))
    start = max(0, (max(1, int(page or 1)) - 1) * per_page)
    selected = scored[start : start + per_page]
    if not selected and page > 1:
        # Wrap or slice remaining if catalog is smaller than page offset
        selected = scored[:per_page]

    candidates: list[dict[str, Any]] = []
    for _neg_score, _idx, item in selected:
        code = str(item.get("code") or "").strip()
        agency = str(item.get("agency") or st.upper()).strip()
        source_url, prefix, lic = _source_meta(st, code, agency)
        candidates.append(
            {
                "source_type": st,
                "source_url": source_url,
                "title": f"{prefix} — {item.get('title') or code}",
                "description": str(item.get("description") or "")[:1000],
                "scientific_field": field,
                "target_persona": "gemma",
                "license": lic,
                "agency": agency,
                "dataset": code,
                "indicator": str(item.get("indicator") or ""),
                "version": str(item.get("version") or "1.0"),
                "query": str(query or ""),
            }
        )
    return {"ok": True, "source_type": st, "candidates": candidates, "count": len(candidates)}


def search_worldbank_direct(query: str, field: str = "", limit: int = 8, page: int = 1) -> list[dict[str, Any]]:
    """Query the official World Bank Indicators API v2 + curated flagship WB datasets so World Bank always returns results."""
    q = str(query or "").strip()
    f_low = str(field or "").lower().replace("-", " ")
    tokens = [t for t in re.findall(r"[a-z0-9]{3,}", f"{q.lower()} {f_low}") if t not in {"the", "and", "for", "with"}]

    wb_curated = [
        {
            "provider": "WB",
            "dataset": "WDI",
            "indicator": "NY.GDP.MKTP.CD",
            "title": "WB/WDI — World Bank World Development Indicators (Global Macroeconomic & Development Series)",
            "description": "World Bank's premier compilation of cross-country comparable data on global development, GDP, poverty, health, education, infrastructure, climate, and governance across 217 economies.",
            "keywords": "world bank wdi gdp economics development poverty health education climate energy",
        },
        {
            "provider": "WB",
            "dataset": "WGI",
            "indicator": "RL.EST",
            "title": "WB/WGI — World Bank Worldwide Governance Indicators (Rule of Law, Voice & Accountability, Stability)",
            "description": "Aggregate and individual governance indicators for over 200 countries measuring Rule of Law, Regulatory Quality, Political Stability and Absence of Violence/Terrorism, and Control of Corruption.",
            "keywords": "world bank governance rule of law international law war conflict political science corruption",
        },
        {
            "provider": "WB",
            "dataset": "HNP",
            "indicator": "SH.XPD.CHEX.GD.ZS",
            "title": "WB/HNP — World Bank Health, Nutrition and Population Statistics",
            "description": "Global biomedical, epidemiological, immunization, health expenditure, life expectancy, and demographic series compiled by the World Bank.",
            "keywords": "world bank health medicine nutrition population mortality epidemiology biology public health",
        },
        {
            "provider": "WB",
            "dataset": "CCKP",
            "indicator": "EN.ATM.CO2E.KT",
            "title": "WB/CCKP — World Bank Climate Change, Energy & Environmental Sustainability Indicators",
            "description": "Greenhouse gas emissions, renewable energy transition, biodiversity protection, agricultural land, and climate vulnerability metrics.",
            "keywords": "world bank climate environment ecology earth sciences physics chemistry energy",
        },
        {
            "provider": "WB",
            "dataset": "IDS",
            "indicator": "DT.DOD.DECT.CD",
            "title": "WB/IDS — World Bank International Debt Statistics & Sovereign External Finance",
            "description": "External debt stocks, debt service payments, bilateral/multilateral creditor flows, and sovereign risk indicators.",
            "keywords": "world bank debt finance economics sovereign bonds imf international",
        },
        {
            "provider": "WB",
            "dataset": "STI",
            "indicator": "GB.XPD.RSDV.GD.ZS",
            "title": "WB/STI — World Bank Science, Technology, R&D Expenditure & Patent Applications",
            "description": "Research and development expenditure (% of GDP), researchers in R&D, high-technology exports, and scientific and technical journal articles.",
            "keywords": "world bank science technology engineering mathematics computer ai physics research",
        },
    ]

    scored: list[tuple[float, int, dict[str, Any]]] = []
    for idx, item in enumerate(wb_curated):
        hay = f"{item['title']} {item['description']} {item['keywords']}".lower()
        score = 5.0 - idx * 0.3
        if q.lower() in hay:
            score += 40.0
        for tok in tokens:
            if tok in hay:
                score += 12.0
        scored.append((-score, idx, item))

    scored.sort(key=lambda x: (x[0], x[1]))
    out: list[dict[str, Any]] = []
    for _neg, _idx, item in scored[: max(2, min(limit, 6))]:
        ind = item["indicator"]
        ds = item["dataset"]
        out.append(
            {
                "source_type": "worldbank",
                "source_url": f"https://api.worldbank.org/v2/country/all/indicator/{ind}?format=json",
                "title": item["title"],
                "description": item["description"],
                "scientific_field": field,
                "target_persona": "gemma",
                "license": "World Bank Open Data (CC-BY 4.0)",
                "provider": "WB",
                "dataset": ds,
                "indicator": ind,
                "query": q,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Ingestion: Fetch live observations & synthesize a Markdown statistical
# factbook into the Sentinel Knowledge Library
# ---------------------------------------------------------------------------

def _fetch_live_observations_markdown(source_type: str, spec: dict[str, Any]) -> str:
    """Fetch live statistical series/observations from the official endpoint and format as Markdown."""
    st = str(source_type or "").lower().strip()
    dataset = str(spec.get("dataset") or "").strip()
    agency = str(spec.get("agency") or st.upper()).strip()
    indicator = str(spec.get("indicator") or "").strip()
    query = str(spec.get("query") or "").strip()
    title = str(spec.get("title") or f"{st.upper()} Dataset {dataset}").strip()
    desc = str(spec.get("description") or "").strip()

    lines: list[str] = [
        f"# {title}",
        "",
        f"- **Official Statistical Authority**: {st.upper()} ({agency})",
        f"- **Dataset / Flow Identifier**: `{dataset}`",
        f"- **Discovery Query Context**: `{query or 'General Scientific & Economic Inquiry'}`",
        "",
        "## 1. Dataset Scope & Methodological Description",
        desc or f"Official statistical time-series dataflow `{dataset}` published by {agency}.",
        "",
    ]

    obs_lines: list[str] = []
    try:
        if st == "eurostat":
            # Try Eurostat JSON-stat 2.0 API or SDMX structure summary
            url = f"{EUROSTAT_STATS_BASE}/{dataset}?format=JSON&lang=EN"
            data = _http_get_json(url, timeout=15)
            if isinstance(data, dict):
                label = str(data.get("label") or title)
                updated = str(data.get("updated") or "")
                vals = data.get("value") or {}
                dims = data.get("dimension") or {}
                obs_lines.append(f"### Live Eurostat JSON-Stat 2.0 Extract (`{label}`, Updated: {updated})")
                obs_lines.append(f"- Total observation cells returned: **{len(vals):,}**")
                for dname, dinfo in list(dims.items())[:6]:
                    if isinstance(dinfo, dict):
                        cat = ((dinfo.get("category") or {}).get("label")) or {}
                        sample_labels = ", ".join(f"`{k}` ({v})" for k, v in list(cat.items())[:8])
                        obs_lines.append(f"- Dimension **{dname}**: {sample_labels}")
                if isinstance(vals, dict) and vals:
                    obs_lines.append("")
                    obs_lines.append("| Observation Cell Index | Reported Value |")
                    obs_lines.append("|---|---|")
                    for k, v in list(vals.items())[:60]:
                        obs_lines.append(f"| `{k}` | {v} |")
        elif st == "imf":
            ind = indicator or dataset.replace("IMF_", "")
            if ind in ("IFS", "WEO", "BOP", "GFSMAB", "DOT", "FSI"):
                ind = "PCPIPCH" if ind == "IFS" else ("NGDP_RPCH" if ind == "WEO" else "GGXWDG_NGDP")
            data = _http_get_json(f"{IMF_DATAMAPPER_BASE}/{ind}", timeout=15)
            values = (((data or {}).get("values") or {}).get(ind)) or {}
            if isinstance(values, dict) and values:
                obs_lines.append(f"### Live IMF DataMapper & SDMX Time-Series (`{ind}`)")
                obs_lines.append("| Country / Group ISO | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |")
                obs_lines.append("|---|---|---|---|---|---|---|")
                for iso, years_map in list(values.items())[:50]:
                    if isinstance(years_map, dict):
                        row_vals = [str(years_map.get(yr, "NA")) for yr in ("2020", "2021", "2022", "2023", "2024", "2025")]
                        obs_lines.append(f"| **{iso}** | " + " | ".join(row_vals) + " |")
        elif st == "ecb":
            csv_txt = _http_get_text(
                f"{ECB_SDMX_BASE}/data/{dataset}",
                params={"format": "csvdata", "lastNObservations": "5"},
                timeout=15,
            )
            csv_rows = [r for r in csv_txt.splitlines() if r.strip()][:60]
            if csv_rows:
                obs_lines.append(f"### Live ECB SDMX 2.1 Observation Extract (`{dataset}`)")
                obs_lines.append("```csv")
                obs_lines.extend(csv_rows[:45])
                obs_lines.append("```")
        elif st == "bis":
            csv_txt = _http_get_text(
                f"{BIS_SDMX_BASE}/data/{dataset}/all",
                params={"lastNObservations": "5", "detail": "dataonly"},
                headers={"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"},
                timeout=15,
            )
            csv_rows = [r for r in csv_txt.splitlines() if r.strip()][:60]
            if csv_rows:
                obs_lines.append(f"### Live BIS SDMX v1 Observation Extract (`{dataset}`)")
                obs_lines.append("```csv")
                obs_lines.extend(csv_rows[:45])
                obs_lines.append("```")
        elif st == "undata":
            xml_txt = _http_get_text(
                f"{UNDATA_SDMX_BASE}/dataflow/all/{dataset}/latest",
                params={"references": "none"},
                timeout=15,
            )
            parsed = _parse_sdmx_xml_dataflows(xml_txt, agency)
            if parsed:
                obs_lines.append(f"### Live UN Data SDMX Structure Metadata (`{dataset}`)")
                for p in parsed[:10]:
                    obs_lines.append(f"- **{p.get('code')}** ({p.get('agency')}): {p.get('title')} — {p.get('description')}")
        elif st == "worldbank":
            ind = indicator or "NY.GDP.MKTP.CD"
            data = _http_get_json(
                f"{WORLDBANK_API_BASE}/country/all/indicator/{ind}",
                params={"format": "json", "per_page": "60", "date": "2019:2024"},
                timeout=15,
            )
            if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
                obs_lines.append(f"### Live World Bank API v2 Observations (`{ind}`)")
                obs_lines.append("| Economy / Country | ISO3 | Year | Indicator Value |")
                obs_lines.append("|---|---|---|---|")
                for row in data[1][:55]:
                    if isinstance(row, dict) and row.get("value") is not None:
                        cname = str((row.get("country") or {}).get("value") or "")
                        ciso = str(row.get("countryiso3code") or "")
                        dt = str(row.get("date") or "")
                        val = row.get("value")
                        obs_lines.append(f"| {cname} | `{ciso}` | {dt} | {val:,} |" if isinstance(val, (int, float)) else f"| {cname} | `{ciso}` | {dt} | {val} |")
    except Exception as ex:
        obs_lines.append(f"_Note: Direct SDMX observation stream summarized via catalog metadata ({str(ex)[:120]})._")

    lines.append("## 2. Empirical Series & Structural Observations")
    if obs_lines:
        lines.extend(obs_lines)
    else:
        lines.append(
            f"This official dataset (`{agency}/{dataset}`) provides standardized cross-national time-series "
            f"indicators for quantitative validation, comparative policy evaluation, and cross-domain pattern discovery."
        )
    return "\n".join(lines) + "\n"


def load_intl_stat_dataset_into_field(field: str, source_type: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Download and ingest an official Eurostat, IMF, ECB, BIS, UN Data, or World Bank dataset into a Sentinel field."""
    from .ingestion import ingest_files

    st = str(source_type or "").lower().strip()
    resolved = _resolve_field(field)
    target_root = resolved["target_dir"] / st
    target_root.mkdir(parents=True, exist_ok=True)

    dataset = str(spec.get("dataset") or spec.get("indicator") or "dataset").strip()
    agency = str(spec.get("agency") or spec.get("provider") or st.upper()).strip()
    title = str(spec.get("title") or f"{agency}/{dataset}").strip()

    load_progress.stage("download", f"Fetching {agency}/{dataset} from official {st.upper()} API...")
    md_content = _fetch_live_observations_markdown(st, spec)

    safe_slug = slugify(f"{st}-{agency}-{dataset}")[:80] or f"{st}-dataset"
    file_path = target_root / f"{safe_slug}.md"
    file_path.write_text(md_content, encoding="utf-8")

    load_progress.stage("digest", f"Digesting {title[:60]} into {resolved['field_name']}...")
    ingest_res = ingest_files(
        [file_path],
        persona="gemma",
        source_type=st,
        scientific_field=resolved["field_slug"],
        title_override=title,
        source_url_override=str(spec.get("source_url") or ""),
    )
    ingested_count = int(ingest_res.get("ingested") or 0)
    doc_ids = [int(x["document_id"]) for x in (ingest_res.get("items") or []) if isinstance(x, dict) and x.get("document_id")]
    return {
        "ok": ingested_count > 0,
        "source_type": st,
        "field": resolved["field_name"],
        "field_slug": resolved["field_slug"],
        "downloaded": 1,
        "ingested": ingested_count,
        "failed": 0 if ingested_count > 0 else 1,
        "document_id": doc_ids[0] if doc_ids else 0,
        "items": ingest_res.get("items") or [],
    }
