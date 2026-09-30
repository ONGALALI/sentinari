"""Sentinari cognitive taxonomy — 67.

Bloom's Revised Taxonomy (cognitive domain) as TAG FAMILIES for seeking out
source material. Six levels — remember, understand, apply, analyze, evaluate,
create — each carrying its learning-outcome verbs.

Owner doctrine (67): the verbs "provide numerous tags that can be used to
seek out source material"; Evaluate and Create are the FOCUS POINTS (NQF
Level 10 corresponds to Create — write a thesis, develop an alternative
hypothesis, invent a product). Two uses in Sentinari:

1. LENS — a Scout query is enriched with focus-level verbs so discovery
   reaches for material that demands evaluation and creation, not recall.
2. TAGS — every Scout candidate is auto-tagged with the Bloom levels its
   title/detail actually demonstrate (verb stems), with focus hits shown
   first on the review surface.

Canonical taxonomy text (owner-supplied): docs/blooms_cognitive_domain.md —
the verb lists below are PARSED from that file at import so the document
stays the single source of truth (owner edits flow through on restart).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOOM_DOC = ROOT / "docs" / "blooms_cognitive_domain.md"

# Ordered lowest → highest cognitive demand.
BLOOM_ORDER: tuple[str, ...] = ("remember", "understand", "apply", "analyze", "evaluate", "create")

# The owner's focus points (67): Evaluate and Create.
FOCUS_LEVELS: tuple[str, ...] = ("evaluate", "create")

# Curated discovery seeds per focus level — the highest-signal verbs for
# query enrichment (a search stuffed with all ~35 verbs drowns the query;
# these are the ones that locate doctoral-grade material).
FOCUS_QUERY_SEEDS: dict[str, tuple[str, ...]] = {
    "evaluate": ("critique", "evaluate", "assess", "justify", "validate"),
    "create": ("design", "synthesize", "construct", "develop", "formulate"),
}

_FALLBACK_VERBS: dict[str, tuple[str, ...]] = {
    "remember": ("cite", "define", "describe", "identify", "label", "list", "match", "name", "outline", "quote", "recall", "report", "reproduce", "retrieve", "show", "state", "tabulate", "tell"),
    "understand": ("abstract", "arrange", "articulate", "associate", "categorize", "clarify", "classify", "compare", "compute", "conclude", "contrast", "defend", "diagram", "differentiate", "discuss", "distinguish", "estimate", "exemplify", "explain", "extend", "extrapolate", "generalize", "illustrate", "infer", "interpret", "paraphrase", "predict", "reorder", "rephrase", "represent", "restate", "summarize", "transform", "translate"),
    "apply": ("apply", "calculate", "carry out", "classify", "complete", "compute", "demonstrate", "dramatize", "employ", "examine", "execute", "experiment", "generalize", "illustrate", "implement", "infer", "interpret", "manipulate", "modify", "operate", "organize", "predict", "solve", "transfer", "translate", "use"),
    "analyze": ("analyze", "break down", "categorize", "classify", "compare", "connect", "contrast", "deconstruct", "detect", "diagram", "differentiate", "discriminate", "distinguish", "divide", "explain", "identify", "integrate", "inventory", "order", "organize", "relate", "separate", "structure"),
    "evaluate": ("appraise", "argue", "assess", "compare", "conclude", "consider", "contrast", "criticize", "critique", "decide", "determine", "discriminate", "evaluate", "grade", "judge", "justify", "measure", "rank", "rate", "recommend", "review", "score", "select", "standardize", "support", "test", "validate"),
    "create": ("arrange", "assemble", "build", "collect", "combine", "compile", "compose", "constitute", "construct", "create", "design", "develop", "devise", "formulate", "generate", "hypothesize", "integrate", "invent", "make", "manage", "modify", "organize", "perform", "plan", "prepare", "produce", "propose", "rearrange", "reconstruct", "reorganize", "revise", "rewrite", "specify", "synthesize", "write"),
}

# "Definitions:" / "Definition:" heading lines in the doc mark each level.
_LEVEL_HEADINGS: dict[str, str] = {
    "remember": "Remember",
    "understand": "Understand",
    "apply": "Apply",
    "analyze": "Analyze",
    "evaluate": "Evaluate",
    "create": "Create",
}


def _parse_verbs_from_doc() -> dict[str, tuple[str, ...]]:
    """Parse each level's verb list out of the canonical doc (source of truth)."""
    verbs: dict[str, tuple[str, ...]] = dict(_FALLBACK_VERBS)
    try:
        text = BLOOM_DOC.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return verbs
    for key, heading in _LEVEL_HEADINGS.items():
        m = re.search(
            rf"^{re.escape(heading)}\s*\n+Definitions?:.*?(?=^[A-Z][a-z]+\s*\n|\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not m:
            continue
        block = m.group(0)
        vm = re.search(r"verbs for this level include:\s*(.+?)\.\s*$", block, flags=re.DOTALL)
        if not vm:
            continue
        raw = vm.group(1).replace(" and ", ", ")
        parsed = tuple(sorted({v.strip().lower() for v in raw.split(",") if v.strip()}))
        if len(parsed) >= 5:
            verbs[key] = parsed
    return verbs


BLOOM_VERBS: dict[str, tuple[str, ...]] = _parse_verbs_from_doc()

_ALL_VERB_STEMS: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((verb, level) for level, vs in BLOOM_VERBS.items() for verb in vs),
        key=lambda t: (-len(t[0]), t[0]),
    )
)


def get_taxonomy() -> dict[str, object]:
    """The taxonomy for the UI: levels, verbs, focus, doc pointer."""
    return {
        "ok": True,
        "order": list(BLOOM_ORDER),
        "focus_levels": list(FOCUS_LEVELS),
        "levels": [
            {"level": lvl, "verbs": list(BLOOM_VERBS.get(lvl, ())), "focus": lvl in FOCUS_LEVELS}
            for lvl in BLOOM_ORDER
        ],
        "canonical_doc": "docs/blooms_cognitive_domain.md",
        "owner_note": "Evaluate and Create are the focus points; NQF Level 10 corresponds to Create.",
    }


def enrich_query(query: str, lens: str | None = None, max_verbs: int = 2) -> str:
    """Append focus-level verb seeds to a Scout query (the cognitive lens).

    lens is a Bloom level name (default: 'create' — the owner's focus).
    Unknown/empty lens returns the query untouched. The enrichment is a
    hint to the sources, never a replacement of the owner's words.
    """
    q = str(query or "").strip()
    if not q:
        return q
    chosen = str(lens or "create").strip().lower()
    if chosen not in BLOOM_ORDER:
        return q
    seeds = FOCUS_QUERY_SEEDS.get(chosen) or tuple(BLOOM_VERBS.get(chosen, ())[:max_verbs])
    add = " ".join(seeds[: max(1, int(max_verbs))])
    if not add:
        return q
    return f"{q} ({add})"


def detect_levels(text: str) -> dict[str, object]:
    """Which Bloom levels does this text demonstrably reach for?

    Matches verb stems on word boundaries (stem-aware: 'evaluating' hits
    'evaluate', 'designed' hits 'design'). Returns focus hits first.
    """
    hay = str(text or "").lower()
    if not hay.strip():
        return {"ok": True, "levels": [], "focus_hits": [], "verbs": {}}
    found: dict[str, list[str]] = {}
    for verb, level in _ALL_VERB_STEMS:
        if re.search(rf"\b{re.escape(verb)}\w*", hay):
            found.setdefault(level, [])
            if verb not in found[level]:
                found[level].append(verb)
    ordered = [lvl for lvl in reversed(BLOOM_ORDER) if lvl in found]  # highest demand first
    focus_hits = [lvl for lvl in FOCUS_LEVELS if lvl in found]
    return {"ok": True, "levels": ordered, "focus_hits": focus_hits, "verbs": {k: found[k][:6] for k in ordered}}
