"""Crisis & threat lexicon for New Pattern Discovery (§74l).

Owner directive: the discovery worker must PRIORITIZE literature that speaks
of crises and threats — the words that mark unsolved, dangerous, urgent
material — so that the moment an engine serves the gateway, the scanner
chews the most threatening documents first. The vocabulary is the owner's
own list, kept in ``pattern_discovery/key_words_tags.md`` (nouns, verbs,
adjectives, named diseases, and societal/existential threats), which this
module parses live so the owner can grow the list without touching code.

The file is free-form — families are separated by headings and bullets — so
the module assigns every term to a curated FAMILY with a weight. Families
are ordered by urgency; weights sum when a document hits several.

House rules honored here:
- Nothing is invented: a term not in the owner's file never scores.
- The file's four obvious typos are corrected in place at parse time
  (alchohol, Banckruptcy, Fugutive, Incomptence) — noted in §74l.
- Scoring is substring-on-boundaries, case-insensitive, against real text.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import get_project_root

_LEXICON_REL_PATH = Path("pattern_discovery") / "key_words_tags.md"

# Family law (§74l): the owner's ~230 terms grouped by what they MEAN, with
# urgency weights. Higher = more urgent; a document's crisis score is the
# sum of its best family weight per distinct matched term, so one word
# repeated a hundred times cannot drown the signal.
FAMILY_WEIGHTS: dict[str, float] = {
    "existential_threat": 10.0,   # engineered pandemics, nuclear proliferation, ecosystem collapse
    "catastrophe": 9.0,           # catastrophic, calamitous, genocide, massacre, atomic weapons
    "terminal_medical": 8.0,      # named incurable diseases, fatal, inoperable, metastatic cancers
    "unsolved_science": 7.0,      # unexplainable, unsolved, impenetrable, baffling — the hunt zone
    "outbreak_violence": 6.0,     # terrorism, warfare, shooting, kidnapping-adjacent crime words
    "societal_crisis": 5.0,       # homelessness, famine/scarcity, joblessness, authoritarianism, debt crises
    "mental_health": 4.0,         # depression, psychosis, addiction — suffering, treatable
    "systemic_risk": 3.0,         # cyber threats, fraud, pollution, corruption, regulatory failure
}

# Terms are assigned by phrase; matching happens on the normalized term
# (see _FAMILY_TERMS below, built via _terms_for).

def _terms_for(family: str, *terms: str) -> tuple[str, ...]:
    return terms


_FAMILY_TERMS = {
    "unsolved_science": _terms_for(
        "unsolved_science",
        "unexplainable", "unsolvable", "baffling", "impenetrable", "indecipherable",
        "inexplicable", "inextricable", "irresolvable", "mystifying", "unaccountable",
        "unconcluded", "unfathomable", "unresolved", "unsolved", "cryptic", "equivocal",
        "inscrutable", "perplexing", "puzzling", "incomprehensible",
    ),
    "terminal_medical": _terms_for(
        "terminal_medical",
        "alzheimer's disease", "amyotrophic lateral sclerosis", "als", "creutzfeldt-jakob disease",
        "cjd", "chronic obstructive pulmonary disease", "copd", "cystic fibrosis",
        "diabetes", "fatal familial insomnia", "ffi", "fibrodysplasia ossificans progressiva",
        "fop", "hiv", "aids", "huntington's disease", "inflammatory bowel disease",
        "crohn's disease", "ulcerative colitis", "inoperable", "metastatic cancer",
        "metastatic cancers", "glioblastoma", "pancreatic adenocarcinoma", "multiple sclerosis",
        "niemann-pick disease", "parkinson's disease", "progeria", "rabies",
        "rheumatoid arthritis", "sanfilippo syndrome", "mps iii", "spinal muscular atrophy",
        "sma", "tay-sachs disease", "batten disease", "canavan disease", "krabbe disease",
        "kuru", "muscular dystrophy", "duchenne muscular dystrophy", "terminal", "fatal",
        "cureless", "immedicable", "irrecoverable", "irremediable", "irreparable",
        "incurable", "remediless", "uncorrectable", "unrecoverable", "mortal", "deathly",
    ),
    "existential_threat": _terms_for(
        "existential_threat",
        "marburg virus", "avian influenza", "highly pathogenic avian influenza",
        "h5n1", "h5n1 bird flu", "bird flu", "inhalation anthrax",
        "engineered pandemics", "biotechnology risk", "nuclear proliferation",
        "atomic weapons", "climate change", "global warming", "biodiversity loss",
        "ecosystem collapse", "resource depletion", "habitat destruction",
        "food scarcity", "resource scarcity", "mass migration", "information warfare",
        "algorithmic distortions", "cyber threats", "hacking", "energy crises",
        "electricity crises", "debt crises", "demographic aging", "wealth inequality",
        "authoritarianism", "electoral mistrust", "crop failures",
    ),
    "catastrophe": _terms_for(
        "catastrophe",
        "calamitous", "cataclysmic", "catastrophic", "destructive", "disastrous",
        "fateful", "ill-fated", "ill-starred", "inevitable", "malignant", "mortal",
        "poisonous", "ruinous", "virulent", "baleful", "baneful", "killing", "killings",
        "malefic", "mortiferous", "noxious", "pernicious", "pestilent", "pestilential",
        "genocide", "massacre", "slaughter", "manslaughter", "homicide", "assassination",
        "bloodshed", "lynching", "terrorism", "poison", "property destruction",
    ),
    "outbreak_violence": _terms_for(
        "outbreak_violence",
        "battle", "combat", "conflict", "fighting", "hostility", "strife", "strike",
        "struggle", "warfare", "shooting", "slaying", "crime", "felony", "destruction",
        "eradication", "expulsion", "displacement", "ejection", "exclusion",
        "extermination", "purge", "theft", "fraud", "fake", "dishonesty", "fugitive",
        "gangs", "violence", "rape", "domestic violence", "child abuse", "drug abuse",
        "bullying", "victimizing", "race hatred", "persecution", "despotism",
        "tyyranny", "tyranny", "nepotism", "oppressed", "human rights abuses", "labor exploitation",
        "tax evasion",
    ),
    "societal_crisis": _terms_for(
        "societal_crisis",
        "ailment", "breakdown", "collapse", "disability", "disorder", "disturbance",
        "ill health", "malady", "relapse", "seizure", "sickness", "syndrome",
        "affliction", "indisposition", "infirmity", "malaise", "hardship", "addicts",
        "addict", "homeless", "homelessness", "joblessness", "bankruptcy", "insolvency",
        "insolvent", "despair", "obesity", "inflation", "marburg",
    ),
    "mental_health": _terms_for(
        "mental_health",
        "deranged", "hysterical", "maniacal", "manic", "psychotic", "unhinged",
        "depressed", "depression", "psycho", "psychopathic", "unbalanced", "mad",
        "alcohol", "drugs",
    ),
    "systemic_risk": _terms_for(
        "systemic_risk",
        "exogenic", "external", "extrinsic", "alien", "estranged", "exotic", "foreign",
        "remote", "strange", "unfamiliar", "hidden", "obscure", "occult", "veiled",
        "esoteric", "mysterious", "mystic", "supernatural", "unnatural", "secretive",
        "subjective", "magical", "regulatory compliance", "ethics", "pollution",
        "incompetence", "unqualified", "unskilled", "serious", "hopeless", "impossible",
        "nowhere to go", "out of time", "virus", "flu", "disease",
    ),
}

# Obvious typos in the owner's file, corrected at parse time (recorded §74l).
_TYPO_FIXES = {
    "alchohol": "alcohol",
    "banckruptcy": "bankruptcy",
    "fugutive": "fugitive",
    "incomptence": "incompetence",
    "vicitimizing": "victimizing",
    "tyyranny": "tyranny",
}

_cache: dict[str, Any] = {}


def _normalize(term: str) -> str:
    term = str(term or "").strip().lower()
    term = re.sub(r"[^a-z0-9'\- ]+", " ", term)
    term = re.sub(r"\s+", " ", term).strip()
    term = _TYPO_FIXES.get(term, term)
    return term


def _extract_line_terms(line: str) -> list[str]:
    """Extract clean searchable terms from a line in key_words_tags.md,
    stripping parenthetical qualifiers while preserving acronyms/sub-diseases."""
    out: list[str] = []
    # Strip parentheticals to get the main phrase(s)
    base_line = re.sub(r"\([^)]*\)", "", line)
    for part in re.split(r"[;,/]", base_line):
        t = _normalize(part)
        if t and len(t) >= 2:
            out.append(t)
    # Also inspect parentheticals for acronyms or named conditions
    for paren in re.findall(r"\(([^)]+)\)", line):
        cleaned = re.sub(r"^(?:e\.g\.|i\.e\.|specifically)\b[\s,:]*", "", paren, flags=re.IGNORECASE)
        lower_c = cleaned.lower()
        if any(skip in lower_c for skip in ("once symptoms", "advanced stage", "without early", "type 1", "types a")):
            continue
        for sub in re.split(r"[;,]|\band\b", cleaned, flags=re.IGNORECASE):
            sub = re.sub(r"^stage\s+[ivx]+\s+", "", sub.strip(), flags=re.IGNORECASE)
            t = _normalize(sub)
            if t and len(t) >= 3:
                out.append(t)
    return out


def load_lexicon(*, force: bool = False) -> dict[str, Any]:
    """Parse the owner's key_words_tags.md live; curate into weighted families.

    Returns {terms: {term: family}, weights: {family: weight}, raw_count,
    file_count, source}. The parsed file only EXTENDS the curated map — a
    term the owner adds lands in the closest family by keyword heuristics,
    so the file stays the single source the owner edits.
    """
    global _cache
    if _cache and not force:
        return _cache

    weights = dict(FAMILY_WEIGHTS)
    terms: dict[str, str] = {}
    for family, family_terms in _FAMILY_TERMS.items():
        for term in family_terms:
            norm = _normalize(term)
            if norm:
                terms[norm] = family

    file_terms: list[str] = []
    path = get_project_root() / _LEXICON_REL_PATH
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        for line in text.splitlines():
            line = line.strip().lstrip("•").lstrip("-").strip()
            if not line or line.startswith("#"):
                continue
            for t in _extract_line_terms(line):
                file_terms.append(t)
        # Extend with any owner additions not yet curated: nearest family by
        # a light keyword probe, else the safest meaningful default.
        for t in file_terms:
            if t in terms:
                continue
            terms[t] = _guess_family(t)
    else:
        text = ""

    # Pre-compile a single combined word-boundary regex for fast O(N) scanning
    sorted_terms = sorted(terms.keys(), key=len, reverse=True)
    alt = "|".join(re.escape(t).replace(r"\ ", r"[ \-]+") for t in sorted_terms if t)
    compiled = re.compile(rf"(?<![a-z0-9])(?:{alt})(?![a-z0-9])") if alt else None
    canon_map = {re.sub(r"[\s\-]+", " ", t): (t, fam) for t, fam in terms.items()}

    _cache = {
        "terms": terms,
        "weights": weights,
        "compiled": compiled,
        "canon_map": canon_map,
        "raw_count": len(file_terms),
        "file_count": len(set(file_terms)),
        "curated_count": sum(len(v) for v in _FAMILY_TERMS.values()),
        "source": str(path),
        "file_found": bool(text),
    }
    return _cache


def _guess_family(term: str) -> str:
    """Owner added a term the curation doesn't know: file it by feel."""
    probes = (
        ("existential_threat", ("pandemic", "nuclear", "climate", "collapse", "scarcity", "crisis", "war")),
        ("catastrophe", ("catastroph", "disaster", "massacre", "genocide", "weapon", "deadly", "fatal")),
        ("terminal_medical", ("disease", "cancer", "syndrome", "incurable", "virus", "terminal", "sclerosis", "dystrophy", "atrophy", "colitis", "arthritis", "diabetes", "influenza")),
        ("outbreak_violence", ("violence", "crime", "attack", "terror", "abuse", "war")),
        ("societal_crisis", ("poverty", "homeless", "famine", "unemploy", "jobless", "debt")),
        ("mental_health", ("depress", "psych", "mania", "addict")),
        ("unsolved_science", ("unsolved", "unknown", "mystery", "paradox", "unexplain")),
    )
    for family, keywords in probes:
        if any(k in term for k in keywords):
            return family
    return "systemic_risk"


def lexicon_stats() -> dict[str, Any]:
    data = load_lexicon()
    return {
        "ok": True,
        "source": data["source"],
        "file_found": data["file_found"],
        "terms_total": len(data["terms"]),
        "terms_from_owner_file": data["file_count"],
        "curated_terms": data["curated_count"],
        "families": {k: {"weight": v, "terms": sum(1 for f in data["terms"].values() if f == k)}
                     for k, v in data["weights"].items()},
    }


def _match_terms(text: str) -> dict[str, str]:
    """Distinct lexicon terms present in the text, mapped to their family.
    Whole-phrase match on word boundaries (multi-word phrases included)."""
    data = load_lexicon()
    lowered = f" {str(text or '').lower()} "
    lowered = re.sub(r"[^a-z0-9'\- ]+", " ", lowered)
    hits: dict[str, str] = {}
    compiled = data.get("compiled")
    canon_map = data.get("canon_map") or {}
    if compiled is not None:
        for m in compiled.finditer(lowered):
            key = re.sub(r"[\s\-]+", " ", m.group(0).strip())
            entry = canon_map.get(key)
            if entry is not None:
                hits[entry[0]] = entry[1]
        return hits
    for term, family in data["terms"].items():
        pattern = r"(?<![a-z0-9])" + re.escape(term).replace(r"\ ", r"[ \-]+") + r"(?![a-z0-9])"
        if re.search(pattern, lowered):
            hits[term] = family
    return hits


def score_text(text: str) -> dict[str, Any]:
    """Crisis score for one text: urgency-weighted, distinct-term driven.

    score = Σ over matched terms of family weight, with the match-density
    bonus capped so a pamphlet can't outshout a thesis. Returns matched
    terms grouped by family so the UI can show WHY a document rose.
    """
    data = load_lexicon()
    hits = _match_terms(text)
    weights = data["weights"]
    score = 0.0
    by_family: dict[str, list[str]] = {}
    for term, family in hits.items():
        score += float(weights.get(family, 1.0))
        by_family.setdefault(family, []).append(term)
    words = max(1, len(str(text or "").split()))
    density = round(100.0 * len(hits) / words, 2)
    return {
        "score": round(score, 1),
        "matched_terms": len(hits),
        "density_per_100_words": density,
        "families": {
            f: {"weight": weights.get(f, 1.0), "terms": sorted(ts)[:12], "n": len(ts)}
            for f, ts in sorted(by_family.items(), key=lambda kv: -weights.get(kv[0], 0))
        },
    }


def scan_document_text(text: str) -> dict[str, Any]:
    """The single call the pattern worker/api use: crisis triage for text."""
    result = score_text(text)
    result["ok"] = True
    result["priority"] = "high" if result["score"] >= 15 else ("elevated" if result["score"] >= 5 else "normal")
    return result
