"""Sentinari Forensic Governance & Courtroom Deception Engine.

Authored under the direction of Dr. Pierre C. Wepener.
Integrates criminal psychology courtroom deception detection, linguistic
statement analysis (SCAN/CBCA), and discourse noise decoupling with the
Sentinari Qualia Lab pseudodynamic vector model.

Features:
1. Forensic Psychological Marker Taxonomy:
   - Agency Dissociation & Passive Deflection
   - Epistemic Equivocation & Perjury Avoidance
   - Cognitive Load Leakage & Unsolicited Over-Justification
   - Deflection, Whataboutism & Topic Pivoting
   - Temporal Instability & Narrative Fracturing
   - Euphemistic Minimization & Semantic Sanitization
2. Discourse Noise Decoupling Flow:
   - Strips rhetorical spin, manipulative framing, and qualification bloat
   - Isolates residual naked factual assertions
3. Merciless 1-Page A4 Forensic Cross-Examination Audit:
   - Strict APA 7th Edition paragraph-by-paragraph referencing
   - Time-stamped with ISO 8601 UTC and localized stamps
   - Multi-dimensional Societal & Governance Impact Matrix
   - Dynamic Projected Value on Conducting Further Research (%)
4. Stamped Database Auditing & Qualia Vector Bridge
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_settings


# ---------------------------------------------------------------------------
# Courtroom Criminal Psychology Lexicons & Forensic Regex Compilers
# ---------------------------------------------------------------------------

_AGENCY_DISSOCIATION_TERMS = (
    "mistakes were made",
    "errors occurred",
    "decisions were taken",
    "it was determined",
    "events transpired",
    "circumstances dictated",
    "out of our hands",
    "out of our control",
    "the committee decided",
    "leadership concluded",
    "industry standards dictate",
    "was subjected to",
    "occurred inadvertently",
    "regrettable outcome",
    "unforeseen consequence",
    "unintended consequence",
    "external factors",
    "the administration determined",
    "systemic failure",
    "procedural anomaly",
)

_EPISTEMIC_EQUIVOCATION_TERMS = (
    "to the best of my recollection",
    "to the best of my knowledge",
    "as far as i recall",
    "i cannot recall",
    "i have no recollection",
    "i have no specific memory",
    "not to my knowledge",
    "not that i am aware of",
    "it would be premature",
    "that depends on how one defines",
    "in some sense",
    "purportedly",
    "allegedly",
    "it could be argued",
    "one might interpret",
    "to a certain degree",
    "without prejudice",
    "subject to interpretation",
    "cannot confirm or deny",
)

_COGNITIVE_LOAD_TERMS = (
    "to be completely honest",
    "to tell you the truth",
    "in all candor",
    "truthfully speaking",
    "as god is my witness",
    "i swear on",
    "in all sincerity",
    "categorically deny without reservation",
    "let me be abundantly clear",
    "let me be crystal clear",
    "with utmost sincerity",
    "i would never",
    "believe me when i say",
    "hand on heart",
    "frankly speaking",
)

_DEFLECTION_PIVOT_TERMS = (
    "that is the wrong question",
    "the real issue here is",
    "what we should really be looking at",
    "what the public really cares about",
    "that is a distraction",
    "politicized witch hunt",
    "bad faith inquiry",
    "what about",
    "if you look at the other side",
    "rather than looking backwards",
    "we need to look forward",
    "it is easy to criticize in hindsight",
    "media sensation",
    "partisan agenda",
)

_TEMPORAL_FRACTURE_TERMS = (
    "all of a sudden",
    "out of nowhere",
    "the next thing i knew",
    "suddenly",
    "at that exact instant",
    "without any warning",
    "before i knew it",
)

_EUPHEMISTIC_MINIMIZATION_TERMS = (
    "special military operation",
    "kinetic action",
    "kinetic engagement",
    "collateral damage",
    "neutralize",
    "pacification",
    "non-standard accounting",
    "accounting irregularity",
    "technical adjustment",
    "revenue recalibration",
    "balance sheet optimization",
    "workforce rightsizing",
    "resource realignment",
    "operational friction",
    "communication breakdown",
    "suboptimal outcome",
    "temporary anomaly",
)


def _compile_phrase_matcher(phrases: tuple[str, ...]) -> re.Pattern[str]:
    escaped = [re.escape(p.strip()) for p in phrases if p.strip()]
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(escaped) + r")(?![A-Za-z0-9])", re.IGNORECASE)


_AGENCY_RE = _compile_phrase_matcher(_AGENCY_DISSOCIATION_TERMS)
_EQUIVOCATION_RE = _compile_phrase_matcher(_EPISTEMIC_EQUIVOCATION_TERMS)
_COGNITIVE_LOAD_RE = _compile_phrase_matcher(_COGNITIVE_LOAD_TERMS)
_DEFLECTION_RE = _compile_phrase_matcher(_DEFLECTION_PIVOT_TERMS)
_TEMPORAL_RE = _compile_phrase_matcher(_TEMPORAL_FRACTURE_TERMS)
_EUPHEMISM_RE = _compile_phrase_matcher(_EUPHEMISTIC_MINIMIZATION_TERMS)

_FIRST_PERSON_SINGULAR_RE = re.compile(r"\b(i|me|my|mine|myself)\b", re.IGNORECASE)
_COLLECTIVE_PRONOUN_RE = re.compile(r"\b(we|us|our|ours|ourselves|the team|the committee|the board)\b", re.IGNORECASE)
_PASSIVE_VERB_RE = re.compile(r"\b(was|were|is|are|been|being)\s+([a-z]{3,}ed|[a-z]{3,}en)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Noise Decoupling & Core Fact Extraction
# ---------------------------------------------------------------------------

def decouple_discourse_noise(text: str) -> dict[str, Any]:
    """Isolate and strip rhetorical padding, evasive qualification, and spin.

    Returns the residual core assertions and metrics on noise volume.
    """
    raw = str(text or "").strip()
    if not raw:
        return {
            "clean_core_text": "",
            "noise_ratio": 0.0,
            "raw_char_count": 0,
            "core_char_count": 0,
            "stripped_noise_segments": [],
        }

    stripped_segments: list[str] = []

    def _collect_and_sub(pattern: re.Pattern[str], target: str) -> str:
        for match in pattern.finditer(target):
            stripped_segments.append(match.group(0))
        return pattern.sub(" ", target)

    # 1. Strip overt evasion phrases
    scrubbed = _collect_and_sub(_DEFLECTION_RE, raw)
    scrubbed = _collect_and_sub(_COGNITIVE_LOAD_RE, scrubbed)
    scrubbed = _collect_and_sub(_EQUIVOCATION_RE, scrubbed)
    scrubbed = _collect_and_sub(_TEMPORAL_RE, scrubbed)

    # 2. Strip rhetorical throat-clearing sentences
    sentences = re.split(r"(?<=[.!?])\s+", scrubbed)
    core_sentences: list[str] = []

    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        # Drop sentences that are pure meta-rhetoric
        words = s_clean.split()
        if len(words) < 4:
            continue
        # Look for substantive predicates (numbers, actors, entities, dates)
        has_substance = bool(
            re.search(r"\b\d+\b", s_clean)
            or re.search(r"\b(confirmed|signed|transferred|deployed|authorized|ordered|failed|paid|lost|denied)\b", s_clean, re.I)
            or re.search(r"\b(percent|\$|euro|ruble|million|billion|tonnes|troops|weapons|dollars)\b", s_clean, re.I)
            or len(words) >= 6
        )
        if has_substance:
            # Clean up internal whitespace
            core_sentences.append(re.sub(r"\s+", " ", s_clean))

    clean_core = " ".join(core_sentences)
    raw_len = max(1, len(raw))
    core_len = len(clean_core)
    noise_ratio = max(0.0, min(1.0, 1.0 - (core_len / raw_len)))

    return {
        "clean_core_text": clean_core if clean_core else "No verifiable empirical assertion remained after noise decoupling.",
        "noise_ratio": round(noise_ratio, 3),
        "raw_char_count": len(raw),
        "core_char_count": core_len,
        "stripped_noise_count": len(stripped_segments),
        "stripped_noise_samples": list(set(stripped_segments))[:8],
    }


# ---------------------------------------------------------------------------
# Forensic Criminal Psychology Analysis
# ---------------------------------------------------------------------------

def analyze_forensic_deception(text: str) -> dict[str, Any]:
    """Execute rigorous courtroom criminal psychology statement analysis.

    Evaluates linguistic distancing, agency loss, perjury-proofing hedges,
    cognitive load leakage, and euphemistic minimization.
    """
    raw = str(text or "").strip()
    words = re.findall(r"\b[A-Za-z0-9'-]+\b", raw)
    word_count = max(1, len(words))

    # Match markers
    agency_matches = _AGENCY_RE.findall(raw)
    equiv_matches = _EQUIVOCATION_RE.findall(raw)
    cog_matches = _COGNITIVE_LOAD_RE.findall(raw)
    deflect_matches = _DEFLECTION_RE.findall(raw)
    temporal_matches = _TEMPORAL_RE.findall(raw)
    euphemism_matches = _EUPHEMISM_RE.findall(raw)

    first_person_hits = len(_FIRST_PERSON_SINGULAR_RE.findall(raw))
    collective_hits = len(_COLLECTIVE_PRONOUN_RE.findall(raw))
    passive_hits = len(_PASSIVE_VERB_RE.findall(raw))

    # Calculate densities per 100 words
    factor = 100.0 / word_count
    agency_density = (len(agency_matches) * 2.5 + passive_hits * 0.8) * factor
    equiv_density = len(equiv_matches) * 3.0 * factor
    cog_density = len(cog_matches) * 4.0 * factor
    deflect_density = len(deflect_matches) * 3.5 * factor
    temporal_density = len(temporal_matches) * 2.0 * factor
    euphemism_density = len(euphemism_matches) * 3.0 * factor

    # Pronoun agency ratio: if collective vastly outnumbers first person in a culpability context
    pronoun_ratio = (collective_hits / max(1, first_person_hits)) if collective_hits > 3 else 1.0
    agency_dissociation_score = min(1.0, (agency_density * 0.08) + (0.15 if pronoun_ratio > 2.5 else 0.0))

    # Composite Deception / Evasion Index (0.0 to 100.0%)
    raw_score = (
        (agency_dissociation_score * 25.0)
        + min(25.0, equiv_density * 3.5)
        + min(20.0, cog_density * 4.0)
        + min(20.0, deflect_density * 4.0)
        + min(15.0, euphemism_density * 3.0)
        + min(10.0, temporal_density * 2.5)
    )

    deception_index = max(4.0, min(98.5, raw_score))
    truth_gradient = max(0.02, min(0.96, 1.0 - (deception_index / 100.0)))

    # Risk Tiering
    if deception_index < 25.0:
        tier = "Low Evasion / Committed Directness"
        verdict = "Discourse shows direct agency, consistent tense alignment, and minimal rhetorical deflection."
    elif deception_index < 50.0:
        tier = "Moderate Evasion / Strategic Hedging"
        verdict = "Notable presence of epistemic softeners and collective pronoun displacement; guarded institutional posture."
    elif deception_index < 75.0:
        tier = "High Deceptive Indicators / Systematic Deflection"
        verdict = "High concentration of courtroom evasion markers: passive agency evasion, topic pivots, and euphemistic minimization."
    else:
        tier = "Severe Deceptive Pathology / Perjury Risk Profile"
        verdict = "Critical saturation of courtroom deception cues: severe agency dissociation, unsolicited honesty oaths, and semantic whitewashing."

    # Qualia Vector Adjustments
    q0_shift = -round(deception_index * 0.003, 3)
    a0_shift = round((deflect_density - agency_density) * 0.02, 3)
    s_shift = -round((cog_density + temporal_density) * 0.025, 3)
    gamma_shift = round(min(0.25, (deception_index / 100.0) * 0.22), 3)

    return {
        "word_count": word_count,
        "deception_index": round(deception_index, 1),
        "truth_gradient": round(truth_gradient, 3),
        "risk_tier": tier,
        "clinical_verdict": verdict,
        "markers": {
            "agency_dissociation": {
                "count": len(agency_matches),
                "passive_verbs": passive_hits,
                "first_person_pronouns": first_person_hits,
                "collective_pronouns": collective_hits,
                "samples": list(set(agency_matches))[:5],
                "score": round(agency_dissociation_score, 3),
            },
            "epistemic_equivocation": {
                "count": len(equiv_matches),
                "samples": list(set(equiv_matches))[:5],
                "density": round(equiv_density, 2),
            },
            "cognitive_load_leakage": {
                "count": len(cog_matches),
                "samples": list(set(cog_matches))[:5],
                "density": round(cog_density, 2),
            },
            "deflection_and_pivot": {
                "count": len(deflect_matches),
                "samples": list(set(deflect_matches))[:5],
                "density": round(deflect_density, 2),
            },
            "euphemistic_minimization": {
                "count": len(euphemism_matches),
                "samples": list(set(euphemism_matches))[:5],
                "density": round(euphemism_density, 2),
            },
            "temporal_instability": {
                "count": len(temporal_matches),
                "samples": list(set(temporal_matches))[:5],
                "density": round(temporal_density, 2),
            },
        },
        "qualia_vector_deltas": {
            "q0_delta": q0_shift,
            "a0_delta": a0_shift,
            "s_delta": s_shift,
            "gamma_delta": gamma_shift,
        },
    }


# ---------------------------------------------------------------------------
# Merciless 1-Page A4 Audit Report Generator (APA 7 Referenced)
# ---------------------------------------------------------------------------

def generate_merciless_audit_report(
    source_text: str,
    *,
    source_title: str = "High-Priority Governance Subject Statement",
    domain: str = "Governance & Forensic Cross-Examination",
    audit_ref: str | None = None,
) -> dict[str, Any]:
    """Compile an uncompromising 1-page A4 forensic assessment report.

    Conforms rigorously to APA 7th Edition paragraph referencing,
    evaluates societal impact dimensions, and projects further research ROI.
    """
    raw = str(source_text or "").strip()
    if not audit_ref:
        audit_ref = f"SMI-GOV-{uuid.uuid4().hex[:8].upper()}"

    now_utc = datetime.now(timezone.utc)
    date_stamp = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    iso_stamp = now_utc.isoformat()

    # 1. Noise Decoupling
    noise_res = decouple_discourse_noise(raw)

    # 2. Forensic Marker Analysis
    deception_res = analyze_forensic_deception(raw)

    dec_idx = deception_res["deception_index"]
    truth_grad = deception_res["truth_gradient"]
    noise_ratio = noise_res["noise_ratio"]

    # 3. Societal Impact Dimensions Matrix
    # Dynamically scale societal impact severity based on deception intensity
    societal_impacts = {
        "Democratic & Institutional Accountability": {
            "severity": "CRITICAL" if dec_idx > 60 else "ELEVATED" if dec_idx > 35 else "STABLE",
            "impact_vector": (
                "Erosion of constitutional oversight; suppression of direct administrative responsibility "
                "through linguistic distancing and evasive collective attribution."
            ),
        },
        "Economic & Fiscal Integrity": {
            "severity": "CRITICAL" if dec_idx > 70 else "HIGH" if dec_idx > 40 else "MODERATE",
            "impact_vector": (
                "Distortion of public asset allocation, undisclosed contingent liabilities, and "
                "sub-rosa institutional subsidization obscured by semantic sanitization."
            ),
        },
        "Public Trust & Psychological Cohesion": {
            "severity": "SEVERE" if dec_idx > 50 else "MODERATE",
            "impact_vector": (
                "Induction of collective cynicism and cognitive fatigue; destruction of the epistemic "
                "baseline necessary for citizen engagement in democratic deliberation."
            ),
        },
        "Rule of Law & Juridical Integrity": {
            "severity": "CRITICAL" if dec_idx > 65 else "ELEVATED",
            "impact_vector": (
                "Impairment of evidentiary standards; intentional deployment of perjury-proofing "
                "equivocation designed to withstand subpoena cross-examination without substantive disclosure."
            ),
        },
        "Geopolitical & Human Security": {
            "severity": "HIGH" if ("war" in raw.lower() or "military" in raw.lower() or dec_idx > 60) else "MODERATE",
            "impact_vector": (
                "Escalation dynamics masked by diplomatic euphemisms; deferred crisis resolution leading "
                "to compounded humanitarian and regional instability."
            ),
        },
    }

    # 4. Projected Value on Conducting Further Research (%)
    # Formula: Baseline empirical necessity + Evasion Premium + Noise Penalty
    base_research_val = 55.0
    evasion_premium = (dec_idx * 0.35)
    noise_premium = (noise_ratio * 15.0)
    research_projection = min(99.4, round(base_research_val + evasion_premium + noise_premium, 1))

    # 5. Merciless APA 7 Report Text (Crafted specifically to fit 1 standard A4 page)
    # References: Vrij (2008), DePaulo et al. (2003), Pennebaker et al. (2003), Ekman (2001), Adams (1996)
    markers = deception_res["markers"]
    agency_samples = ", ".join(f'"{s}"' for s in markers["agency_dissociation"]["samples"]) or "implicit passive constructions"
    equiv_samples = ", ".join(f'"{s}"' for s in markers["epistemic_equivocation"]["samples"]) or "qualified conditionals"
    cog_samples = ", ".join(f'"{s}"' for s in markers["cognitive_load_leakage"]["samples"]) or "unsolicited oaths of candor"

    apa7_report = f"""====================================================================================================
SENTINARI FORENSIC GOVERNANCE AUDIT: MERCILESS CROSS-EXAMINATION REPORT
====================================================================================================
AUDIT REFERENCE: {audit_ref} | DATE OF ASSESSMENT: {date_stamp}
SUBJECT / SOURCE: {source_title}
INVESTIGATOR: Dr. Pierre C. Wepener & Sentinari Qualia Intelligence Architecture
DOMAIN: {domain}
DECEPTION & EVASION INDEX: {dec_idx}% [{deception_res['risk_tier'].upper()}]
TRUTH-GRADIENT SCORE: {truth_grad} / 1.000 | DISCOURSE NOISE RATIO: {noise_ratio * 100:.1f}%
PROJECTED VALUE OF CONDUCTING FURTHER RESEARCH: {research_projection}%
====================================================================================================

1. FORENSIC DISCOURSE DECONSTRUCTION & AGENCY DISPLACEMENT
Statement analysis reveals severe linguistic distancing engineered to decouple institutional actors from executive accountability. In forensic psycholinguistics, the systematic suppression of first-person singular pronouns ('I', 'my') in favor of collective or passive constructions ({agency_samples}) serves as an empirical indicator of culpability displacement and psychological distancing (Adams, 1996; Pennebaker et al., 2003). The subject exhibits an agency dissociation score of {markers['agency_dissociation']['score']}, demonstrating a deliberate avoidance of causative agency. Rather than detailing direct executive conduct, the discourse constructs an abstract narrative wherein events transpired autonomously, insulating decision-makers from legal and civic exposure (Pennebaker et al., 2003).

2. COGNITIVE LOAD ANOMALIES & COURTROOM DECEPTION PROFILING
The analyzed testimony displays acute markers of cognitive friction and spontaneous over-justification. Under courtroom cross-examination criteria, truthful communicators typically provide direct, unadorned narrative reconstructions, whereas deceptive individuals exhibit heightened cognitive load manifested through unprompted protestations of honesty ({cog_samples}) and dense epistemic equivocation ({equiv_samples}) designed to preempt perjury sanctions (DePaulo et al., 2003; Vrij, 2008). The linguistic density of perjury-proofing hedges ({markers['epistemic_equivocation']['density']} per 100 words) reflects an evasive defensive perimeter. These semantic fortifications serve not to clarify material reality, but to construct plausible deniability under potential juridical scrutiny (Porter & Yuille, 1996; Vrij, 2008).

3. DECOUPLED MATERIAL REALITY & SUBSTANTIVE FACTUAL CORE
Following algorithmic extraction of rhetorical obfuscation, procedural euphemisms, and emotional posturing (noise reduction: {noise_ratio * 100:.1f}%), the residual verifiable core assertions are identified as follows:
\"{noise_res['clean_core_text']}\"
As established by behavioral baseline analysis, the stripped assertions represent a fraction of the total narrative volume, demonstrating that over {(noise_ratio * 100):.0f}% of the communicative output functions solely as deceptive noise to obscure material non-compliance and policy failure (Ekman, 2001).

4. MULTI-DIMENSIONAL SOCIETAL IMPACT EVALUATION
The institutional fallout of this evasive discourse manifests across five vital societal dimensions:
- Democratic Accountability [{societal_impacts['Democratic & Institutional Accountability']['severity']}]: {societal_impacts['Democratic & Institutional Accountability']['impact_vector']}
- Economic & Fiscal Integrity [{societal_impacts['Economic & Fiscal Integrity']['severity']}]: {societal_impacts['Economic & Fiscal Integrity']['impact_vector']}
- Public Trust & Cohesion [{societal_impacts['Public Trust & Psychological Cohesion']['severity']}]: {societal_impacts['Public Trust & Psychological Cohesion']['impact_vector']}
- Rule of Law [{societal_impacts['Rule of Law & Juridical Integrity']['severity']}]: {societal_impacts['Rule of Law & Juridical Integrity']['impact_vector']}
- Human Security [{societal_impacts['Geopolitical & Human Security']['severity']}]: {societal_impacts['Geopolitical & Human Security']['impact_vector']}

5. FORENSIC CONCLUSION & RESEARCH VALUE PROJECTION ({research_projection}%)
With a Deception & Evasion Index of {dec_idx}%, this audited testimony warrants a merciless evidentiary finding: the discourse is fundamentally evasive and institutionally compromised. The Projected Value of Conducting Further Research is calculated at {research_projection}%, denoting an imperative return for forensic subpoena, independent financial discovery, and non-sanitized witness cross-examination. To pierce this deceptive veil, oversight authorities must bypass the subject's curated rhetoric and enforce subpoena power targeting operational logs, contemporaneous digital records, and direct personal testimony (Vrij, 2008).

----------------------------------------------------------------------------------------------------
REFERENCES (APA 7TH EDITION)
Adams, S. H. (1996). Statement analysis: What do suspects' words really reveal? FBI Law Enforcement Bulletin, 65(10), 12–20.
DePaulo, B. M., Lindsay, J. J., Malone, B. E., Muhlenbruck, L., Charlton, K., & Cooper, H. (2003). Cues to deception. Psychological Bulletin, 129(1), 74–118. https://doi.org/10.1037/0033-2909.129.1.74
Ekman, P. (2001). Telling lies: Clues to deceit in the marketplace, politics, and marriage (3rd ed.). W. W. Norton & Company.
Pennebaker, J. W., Mehl, M. R., & Niederhoffer, K. G. (2003). Psychological aspects of natural language use: Our words, our selves. Annual Review of Psychology, 54(1), 547–577. https://doi.org/10.1146/annurev.psych.54.101601.145041
Porter, S., & Yuille, J. C. (1996). The language of deceit: An investigation of the verbal cues to deception in the interrogation room. Law and Human Behavior, 20(4), 443–458. https://doi.org/10.1007/BF01499024
Vrij, A. (2008). Detecting lies and deceit: Pitfalls and opportunities (2nd ed.). John Wiley & Sons.
===================================================================================================="""

    return {
        "audit_ref": audit_ref,
        "date_stamp": date_stamp,
        "iso_stamp": iso_stamp,
        "source_title": source_title,
        "domain": domain,
        "deception_index": dec_idx,
        "truth_gradient": truth_grad,
        "risk_tier": deception_res["risk_tier"],
        "clinical_verdict": deception_res["clinical_verdict"],
        "discourse_noise_ratio": noise_ratio,
        "noise_analysis": noise_res,
        "forensic_markers": markers,
        "qualia_vector_deltas": deception_res["qualia_vector_deltas"],
        "societal_impacts": societal_impacts,
        "research_value_projection": research_projection,
        "merciless_report_apa7": apa7_report,
    }


# ---------------------------------------------------------------------------
# Database Persistence for Immutable Stamped Audits
# ---------------------------------------------------------------------------

def ensure_forensic_audits_table(conn: sqlite3.Connection) -> None:
    """Ensure immutable forensic audit log table exists."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS forensic_governance_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_ref TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            source_title TEXT NOT NULL,
            domain TEXT NOT NULL,
            deception_index REAL NOT NULL,
            truth_gradient REAL NOT NULL,
            noise_ratio REAL NOT NULL,
            research_value_projection REAL NOT NULL,
            risk_tier TEXT NOT NULL,
            source_text TEXT NOT NULL,
            core_facts TEXT NOT NULL,
            markers_json TEXT NOT NULL,
            societal_impacts_json TEXT NOT NULL,
            qualia_deltas_json TEXT NOT NULL,
            report_apa7 TEXT NOT NULL
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fga_created_at ON forensic_governance_audits(created_at);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fga_ref ON forensic_governance_audits(audit_ref);")


def persist_forensic_audit(conn: sqlite3.Connection, audit: dict[str, Any], raw_source: str) -> int:
    """Save stamped audit report to database."""
    ensure_forensic_audits_table(conn)
    cursor = conn.execute(
        """
        INSERT INTO forensic_governance_audits (
            audit_ref, created_at, source_title, domain, deception_index,
            truth_gradient, noise_ratio, research_value_projection, risk_tier,
            source_text, core_facts, markers_json, societal_impacts_json,
            qualia_deltas_json, report_apa7
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            audit["audit_ref"],
            audit["iso_stamp"],
            audit["source_title"],
            audit["domain"],
            float(audit["deception_index"]),
            float(audit["truth_gradient"]),
            float(audit["discourse_noise_ratio"]),
            float(audit["research_value_projection"]),
            audit["risk_tier"],
            raw_source[:5000],
            audit["noise_analysis"]["clean_core_text"][:5000],
            json.dumps(audit["forensic_markers"]),
            json.dumps(audit["societal_impacts"]),
            json.dumps(audit["qualia_vector_deltas"]),
            audit["merciless_report_apa7"],
        ),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def list_forensic_audits(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    """Retrieve recent stamped audits."""
    ensure_forensic_audits_table(conn)
    rows = conn.execute(
        """
        SELECT id, audit_ref, created_at, source_title, domain, deception_index,
               truth_gradient, noise_ratio, research_value_projection, risk_tier
        FROM forensic_governance_audits
        ORDER BY id DESC
        LIMIT ?;
        """,
        (max(1, int(limit)),),
    ).fetchall()
    return [dict(r) for r in rows]


def get_forensic_audit_by_ref(conn: sqlite3.Connection, audit_ref: str) -> dict[str, Any] | None:
    """Retrieve a single complete stamped audit."""
    ensure_forensic_audits_table(conn)
    row = conn.execute(
        """
        SELECT * FROM forensic_governance_audits WHERE audit_ref = ? LIMIT 1;
        """,
        (str(audit_ref).strip(),),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["markers"] = json.loads(d.get("markers_json") or "{}")
        d["societal_impacts"] = json.loads(d.get("societal_impacts_json") or "{}")
        d["qualia_vector_deltas"] = json.loads(d.get("qualia_deltas_json") or "{}")
    except Exception:
        pass
    return d


# ---------------------------------------------------------------------------
# Pre-loaded 5,000-character Forensic Exemplars
# ---------------------------------------------------------------------------

EXEMPLARS: dict[str, dict[str, Any]] = {
    "russia_ukraine_evasion": {
        "title": "Diplomatic Evasion & Geopolitical Minimization (Russia-Ukraine Conflict)",
        "domain": "Geopolitics & Military Escalation",
        "description": "Cross-examination of institutional press releases deploying euphemisms ('special military operation', 'pacification', 'unforeseen civilian friction') and shifting culpability.",
        "text": (
            "To be completely honest, let me be abundantly clear about the historical circumstances surrounding "
            "our special military operation and kinetic engagement. It must be stated that mistakes were made in the "
            "early diplomatic exchanges, but events transpired in a manner that was entirely out of our hands. What we "
            "should really be looking at is not the temporary tactical friction on the ground, but rather the thirty years "
            "of relentless eastward provocation orchestrated by external geopolitical actors. The decision was taken by our "
            "collective leadership to execute a pre-emptive pacification following non-standard security violations along "
            "our sovereign frontier. As far as I recall, no civilian targets were ever designated; any collateral impact that "
            "occurred was an unforeseen consequence of hostile weapon placements within municipal perimeters. Believe me when "
            "I say that our administration has acted with utmost sincerity and restraint. Why are international commentators "
            "fixated on procedural discrepancies rather than looking at the undeniable economic warfare being waged against "
            "our peaceful population? In all candor, to the best of my knowledge, every operational directive complied with "
            "the broadest interpretations of self-defense. Suddenly, out of nowhere, hostile coalitions mobilized thousands of "
            "sanctions, yet we categorically deny without reservation that any international conventions were breached. Rather "
            "than looking backwards at historical grievances, it is easy to criticize in hindsight, but our resolve remains "
            "unshakable as we achieve the ultimate neutralization of hostile infrastructure."
        ),
    },
    "corporate_governance_fraud": {
        "title": "Legislative Subpoena Defense (Executive Balance-Sheet Obfuscation)",
        "domain": "Corporate Governance & Financial Integrity",
        "description": "Executive testimony responding to parliamentary inquiry into concealed debt, structured offshore vehicles, and auditor misdirection.",
        "text": (
            "With utmost sincerity, I welcome this committee's review, although that is the wrong question to be asking "
            "if we are genuinely concerned with corporate sustainability. In all candor, to the best of my recollection, "
            "the structured off-balance-sheet adjustments were determined by our independent auditing committee in full alignment "
            "with prevailing industry standards. It was concluded that revenue recalibrations and workforce rightsizing were "
            "unfortunate operational anomalies driven by unprecedented macroeconomic headwinds entirely beyond our control. "
            "I cannot recall the exact date when the advisory memorandum was circulated; not to my direct knowledge was there "
            "any attempt to conceal liabilities from the board. Frankly speaking, let me be crystal clear: our executive team "
            "categorically denies without reservation that any intentional misstatement occurred. Certain non-standard accounting "
            "procedures were adopted as a temporary measure to optimize capital allocation during market contractions. Suddenly, "
            "the financial press created a sensationalized narrative, but what the public really cares about is that thousands of "
            "jobs were safeguarded through our proactive resource realignment."
        ),
    },
    "public_health_crisis": {
        "title": "Crisis Management Evasion (Institutional Health Response Failure)",
        "domain": "Public Health & Administrative Accountability",
        "description": "Official institutional defense regarding delayed quarantine orders, stockpiling lapses, and epidemiological data suppression.",
        "text": (
            "Let me be abundantly clear: our agency acted at all times in accordance with the best available scientific data "
            "present at that exact instant. To tell you the truth, mistakes were made across the entire international ecosystem, "
            "and decisions were taken under conditions of radical uncertainty. As far as I am aware, the delay in issuing the "
            "containment protocols was not a bureaucratic failure, but a prudent pause dictated by emerging immunological models. "
            "That is a distraction being weaponized by partisan critics rather than examining our record-setting deployment of "
            "diagnostic supplies. The next thing we knew, supply chain disruptions were subjected to external logistical failures "
            "that were completely out of our control. To a certain degree, communication breakdowns occurred, but we categorically "
            "deny that risk assessments were withheld from public record."
        ),
    },
}


def render_standalone_audit_html(audit: dict[str, Any]) -> str:
    """Render a standalone, print-optimized 1-page A4 Merciless Forensic Audit document."""
    audit_ref = audit.get("audit_ref") or "SMI-GOV-00000000"
    date_stamp = audit.get("created_at") or audit.get("date_stamp") or "2026-10-19"
    source_title = audit.get("source_title") or "High-Priority Governance Subject Statement"
    domain = audit.get("domain") or "Governance & Forensic Cross-Examination"
    deception_idx = float(audit.get("deception_index") or 0.0)
    truth_grad = float(audit.get("truth_gradient") or 0.0)
    noise_ratio = float(audit.get("noise_ratio") or audit.get("discourse_noise_ratio") or 0.0)
    research_proj = float(audit.get("research_value_projection") or 0.0)
    risk_tier = audit.get("risk_tier") or "Forensic Assessment"
    report_text = audit.get("merciless_report_apa7") or audit.get("report_apa7") or ""

    # Status color
    tier_color = "#dc2626" if deception_idx > 60 else "#f59e0b" if deception_idx > 35 else "#10b981"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Forensic Governance Audit — {audit_ref}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    @page {{
      size: A4 portrait;
      margin: 12mm 15mm;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0b0f19;
      color: #f3f4f6;
      line-height: 1.5;
      padding: 24px;
    }}
    .sheet {{
      max-width: 860px;
      margin: 0 auto;
      background: #111827;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 8px;
      padding: 32px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
    }}
    .actions-bar {{
      max-width: 860px;
      margin: 0 auto 16px auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 16px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 0.85rem;
      text-decoration: none;
      cursor: pointer;
      border: 1px solid rgba(255, 255, 255, 0.15);
      background: #1f2937;
      color: #f9fafb;
      transition: all 0.15s ease;
    }}
    .btn:hover {{
      background: #374151;
      border-color: #6366f1;
    }}
    .btn-primary {{
      background: #4f46e5;
      border-color: #6366f1;
    }}
    .btn-primary:hover {{
      background: #4338ca;
    }}
    .header-rule {{
      border-bottom: 2px solid #4f46e5;
      padding-bottom: 16px;
      margin-bottom: 20px;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
    }}
    .doc-title {{
      font-size: 1.4rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #ffffff;
    }}
    .doc-sub {{
      font-size: 0.82rem;
      color: #9ca3af;
      margin-top: 4px;
    }}
    .badge-ref {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
      padding: 4px 10px;
      border-radius: 4px;
      background: rgba(99, 102, 241, 0.15);
      border: 1px solid rgba(99, 102, 241, 0.4);
      color: #a5b4fc;
      font-weight: 700;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 24px;
    }}
    .kpi-card {{
      background: rgba(17, 24, 39, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 6px;
      padding: 12px;
      text-align: center;
    }}
    .kpi-label {{
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #9ca3af;
      margin-bottom: 4px;
    }}
    .kpi-val {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 1.3rem;
      font-weight: 800;
    }}
    .report-content {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.78rem;
      line-height: 1.45;
      color: #e5e7eb;
      background: #0b0f19;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 6px;
      padding: 20px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .footer-stamp {{
      margin-top: 20px;
      padding-top: 12px;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      display: flex;
      justify-content: space-between;
      font-size: 0.72rem;
      color: #6b7280;
    }}
    @media print {{
      body {{
        background: #ffffff !important;
        color: #111827 !important;
        padding: 0 !important;
      }}
      .actions-bar {{ display: none !important; }}
      .sheet {{
        box-shadow: none !important;
        border: none !important;
        background: #ffffff !important;
        padding: 0 !important;
        max-width: 100% !important;
      }}
      .header-rule {{ border-color: #111827 !important; }}
      .doc-title {{ color: #111827 !important; }}
      .doc-sub {{ color: #4b5563 !important; }}
      .badge-ref {{
        background: #f3f4f6 !important;
        color: #111827 !important;
        border-color: #d1d5db !important;
      }}
      .kpi-card {{
        background: #f9fafb !important;
        border-color: #e5e7eb !important;
      }}
      .kpi-label {{ color: #6b7280 !important; }}
      .report-content {{
        background: #ffffff !important;
        color: #111827 !important;
        border-color: #d1d5db !important;
        font-size: 0.72rem !important;
        line-height: 1.35 !important;
        padding: 12px !important;
      }}
      .footer-stamp {{ color: #9ca3af !important; border-color: #e5e7eb !important; }}
    }}
  </style>
</head>
<body>
  <div class="actions-bar">
    <a href="/ui/qualia" class="btn">&larr; Return to Qualia Lab</a>
    <div style="display:flex;gap:8px;">
      <button onclick="window.print()" class="btn btn-primary">&#x1F5B6; Print / Save PDF (1 A4 Page)</button>
    </div>
  </div>

  <div class="sheet">
    <div class="header-rule">
      <div>
        <div class="doc-title">SENTINARI FORENSIC GOVERNANCE AUDIT</div>
        <div class="doc-sub">Courtroom Criminal Psychology & Deception Cross-Examination Sheet</div>
      </div>
      <div style="text-align:right;">
        <span class="badge-ref">{audit_ref}</span>
        <div style="font-size:0.75rem;color:#9ca3af;margin-top:6px;">{date_stamp}</div>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Deception Index</div>
        <div class="kpi-val" style="color:{tier_color};">{deception_idx:.1f}%</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Truth-Gradient</div>
        <div class="kpi-val" style="color:#10b981;">{truth_grad:.3f}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Discourse Noise</div>
        <div class="kpi-val" style="color:#06b6d4;">{noise_ratio * 100:.1f}%</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Research Value ROI</div>
        <div class="kpi-val" style="color:#818cf8;">{research_proj:.1f}%</div>
      </div>
    </div>

    <div class="report-content">{report_text}</div>

    <div class="footer-stamp">
      <span>Investigator: Dr. Pierre C. Wepener | Sentinari Qualia Intelligence Engine</span>
      <span>Strict 1-Page A4 Juridical Standard · APA 7th Edition</span>
    </div>
  </div>
</body>
</html>
"""
