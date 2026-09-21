"""Text-feature recommendation model for the exploratory sandbox.

Design notes (qr-v2)
--------------------
This module converts a question/answer exchange into bounded feature indices and
proposes damped sandbox parameter changes. It is a *constructed text-feature
model*: every score is a deterministic function of the observable text and the
supplied qualia state. It is not a psychological assessment and nothing here is
psychometrically validated; the output carries explicit status fields so that
downstream consumers cannot mistake it for measurement.

Reliability properties (deliberate design decisions):
1. Lexicon matches are whole-word/phrase regex matches, so "how" no longer
   counts inside "however" and short tokens cannot inflate scores.
2. Each observable feeds exactly one composite. Reusing a signal in several
   composites (as earlier versions did) creates correlated indices that only
   *appear* more reliable; qr-v2 removes that double-counting.
3. Count features saturate smoothly (1 - exp(-hits/k)) instead of hard clamp
   ratios, so a single extra hit near the ceiling cannot swing a composite.
4. The proposal step is damped *and* confidence-gated: low-information
   exchanges move the sandbox less, and ``should_apply`` requires a meaningful
   shift together with adequate confidence.
5. Confidence has a hard ceiling (CONFIDENCE_CEILING) below 1.0 until the
   indices are validated against independent external ratings.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .config import get_settings


FEATURE_VERSION = "qr-v2"
UNCERTAINTY_PENALTY_WEIGHT = 0.20
RECOMMENDATION_UPDATE_RATE = 0.25
CONFIDENCE_CEILING = 0.85
SHOULD_APPLY_MIN_CONFIDENCE = 0.40


# ---------------------------------------------------------------------------
# Lexicons. Question-side terms express *demand*; answer-side terms express
# *structure*. They are disjoint by design so no token is counted twice.
# ---------------------------------------------------------------------------

_REASONING_DEMAND_TOKENS = (
    "explain", "reason", "analyze", "analyse", "why", "how", "compare",
    "tradeoff", "deduce", "justify", "evaluate", "derive", "architecture",
)
_DISCOURSE_TOKENS = (
    "therefore", "thus", "hence", "because", "conclusion", "premise",
    "constraint", "consistent", "implies", "follows", "as a result",
)
_EVIDENCE_TOKENS = (
    "evidence", "study", "studies", "research", "citation", "source",
    "according", "data", "measured", "observed",
)
_UNCERTAINTY_PHRASES = (
    "i don't know", "not sure", "unclear", "unknown", "cannot determine",
    "cannot say", "no evidence", "guess",
)
_ANXIETY_TOKENS = (
    "anxiety", "panic", "overwhelmed", "unsafe", "afraid", "stressed",
    "distressed",
)


def _compile_alternation(tokens: tuple[str, ...]) -> re.Pattern[str]:
    escaped = [re.escape(str(token or "").strip()) for token in tokens if str(token or "").strip()]
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(escaped) + r")(?![A-Za-z0-9])", re.IGNORECASE)


_REASONING_DEMAND_RE = _compile_alternation(_REASONING_DEMAND_TOKENS)
_DISCOURSE_RE = _compile_alternation(_DISCOURSE_TOKENS)
_EVIDENCE_RE = _compile_alternation(_EVIDENCE_TOKENS)
_UNCERTAINTY_RE = _compile_alternation(_UNCERTAINTY_PHRASES)
_ANXIETY_RE = _compile_alternation(_ANXIETY_TOKENS)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float(default)
    if parsed != parsed:  # NaN
        return float(default)
    return float(parsed)


def _clip(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _saturate(hits: float, half_way: float) -> float:
    """Smoothly map a hit count to [0, 1]; ``half_way`` hits -> ~0.5."""
    if hits <= 0:
        return 0.0
    return _clip(1.0 - math.exp(-float(hits) / float(half_way)), 0.0, 1.0)


def _count_words(text: str) -> int:
    return len([token for token in re.split(r"\s+", str(text or "").strip()) if token])


def _count_matches(pattern: re.Pattern[str], text: str) -> int:
    if not text:
        return 0
    return len(pattern.findall(str(text)))


def _extract_token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", str(text or "").lower()))


def _overlap_ratio(a_text: str, b_text: str) -> float:
    a_tokens = _extract_token_set(a_text)
    b_tokens = _extract_token_set(b_text)
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = len(a_tokens.intersection(b_tokens))
    union = len(a_tokens.union(b_tokens))
    return _clip(float(intersection) / float(max(1, union)), 0.0, 1.0)


def build_qualia_recommendation(
    *,
    question: str,
    answer: str,
    citations: list[str] | None,
    qualia: dict[str, Any] | None,
    current_variant: float,
    current_gamma: float,
    current_stability_bias: float,
    gamma_cap: float,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_settings = settings if isinstance(settings, dict) else get_settings()
    safety = source_settings.get("safety", {}) if isinstance(source_settings.get("safety"), dict) else {}
    calm_mode = safety.get("calm_mode", {}) if isinstance(safety.get("calm_mode"), dict) else {}
    anxiety_keywords = [
        str(item or "").strip().lower()
        for item in (calm_mode.get("anxiety_keywords") or [])
        if str(item or "").strip()
    ]

    question_text = str(question or "")
    answer_text = str(answer or "")
    citation_count = len(citations or [])
    current_variant = _clip(_as_float(current_variant, 0.1), 0.1, 25.0)
    current_gamma = _clip(_as_float(current_gamma, 0.2), 0.0, 1.0)
    current_bias = _clip(_as_float(current_stability_bias, 0.65), 0.0, 1.0)
    gamma_cap = _clip(_as_float(gamma_cap, 0.25), 0.0, 0.25)
    qualia_state = qualia if isinstance(qualia, dict) else {}

    current_ratio = _clip((current_variant - 0.1) / 24.9, 0.0, 1.0)
    effective_ratio = _clip(_as_float(qualia_state.get("effective_variant_ratio"), current_ratio), 0.0, 1.0)
    summary = qualia_state.get("summary", {}) if isinstance(qualia_state.get("summary"), dict) else {}
    stability_index = _clip(
        _as_float(qualia_state.get("stability_index"), _as_float(summary.get("stability_index"), 0.75)),
        0.0,
        1.0,
    )
    qualia_attention = _clip(
        _as_float(summary.get("attention_pull"), _as_float(qualia_state.get("influence"), 0.0)),
        0.0,
        1.0,
    )

    # ---- Observable features (each used exactly once below) ----------------
    q_words = _count_words(question_text)
    a_words = _count_words(answer_text)
    reasoning_demand = _saturate(_count_matches(_REASONING_DEMAND_RE, question_text), 5.0)
    discourse = _saturate(_count_matches(_DISCOURSE_RE, answer_text), 6.0)
    evidence_lex = _saturate(_count_matches(_EVIDENCE_RE, answer_text), 4.0)
    uncertainty_hits = _count_matches(_UNCERTAINTY_RE, answer_text)
    anxiety_hits = _count_matches(_ANXIETY_RE, f"{question_text} {answer_text}")
    if anxiety_keywords:
        anxiety_hits += _count_matches(_compile_alternation(tuple(anxiety_keywords)), f"{question_text} {answer_text}")
    numbered_steps = len(re.findall(r"(?m)^\s*\d+\.", answer_text))
    bullet_steps = len(re.findall(r"(?m)^\s*[-*]\s+", answer_text))
    structure = _saturate(float(numbered_steps + bullet_steps), 4.0)
    alignment = _overlap_ratio(question_text, answer_text)

    depth = _saturate(float(a_words), 180.0)
    adequacy = _saturate(float(q_words + a_words), 150.0)
    length_balance = math.exp(-abs(float(a_words) - 180.0) / 180.0)
    uncertainty_penalty = _clip(UNCERTAINTY_PENALTY_WEIGHT * _saturate(float(uncertainty_hits), 2.0), 0.0, UNCERTAINTY_PENALTY_WEIGHT)
    stability_penalty = _clip(1.0 - stability_index, 0.0, 1.0)

    # ---- Composite indices (disjoint observables, documented weights) ------
    reasoning_score = _clip(
        (0.50 * reasoning_demand) + (0.30 * depth) + (0.20 * structure),
        0.0,
        1.0,
    )
    logic_score = _clip(
        (0.35 * discourse) + (0.35 * structure) + (0.30 * alignment) - uncertainty_penalty,
        0.0,
        1.0,
    )
    grounding_score = _clip(
        (0.60 * _saturate(float(citation_count), 3.0)) + (0.40 * evidence_lex),
        0.0,
        1.0,
    )
    attention_score = _clip(
        (0.50 * alignment) + (0.30 * qualia_attention) + (0.20 * length_balance),
        0.0,
        1.0,
    )
    anxiety_signal = _clip(
        (0.60 * _saturate(float(anxiety_hits), 3.0)) + (0.40 * stability_penalty),
        0.0,
        1.0,
    )
    gamma_focus = _clip(
        (0.50 * reasoning_demand) + (0.25 * (1.0 - attention_score)) + (0.25 * (1.0 - logic_score)),
        0.0,
        1.0,
    )

    # ---- Confidence: information adequacy, never text volume alone --------
    confidence = _clip(
        0.25
        + (0.30 * adequacy)
        + (0.20 * grounding_score)
        + (0.15 * alignment)
        + (0.10 * stability_index)
        - (0.15 * _saturate(float(uncertainty_hits), 2.0))
        - (0.10 * _saturate(float(anxiety_hits), 3.0)),
        0.20,
        CONFIDENCE_CEILING,
    )

    # ---- Damped, confidence-gated proposal --------------------------------
    raw_target_ratio = _clip(
        (0.35 * effective_ratio)
        + (0.25 * reasoning_score)
        + (0.20 * logic_score)
        + (0.10 * grounding_score)
        + (0.10 * attention_score)
        - (0.15 * anxiety_signal),
        0.0,
        1.0,
    )
    # Recommendations are damped proposals, not recursive measurements. The
    # effective step shrinks with low confidence so weak evidence moves the
    # sandbox less. This limits compounding error across accepted proposals.
    effective_rate = RECOMMENDATION_UPDATE_RATE * (0.5 + 0.5 * confidence)
    target_ratio = _clip(
        current_ratio + (effective_rate * (raw_target_ratio - current_ratio)),
        0.0,
        1.0,
    )

    recommended_gamma = _clip(
        current_gamma
        + (0.08 * gamma_focus)
        + (0.03 * reasoning_score)
        - (0.04 * stability_penalty)
        - (0.03 * anxiety_signal),
        0.0,
        gamma_cap,
    )

    recommended_bias = _clip(
        0.45
        + (0.30 * anxiety_signal)
        + (0.15 * (1.0 - attention_score))
        - (0.10 * logic_score),
        0.30,
        0.95,
    )

    recommended_variant = round(0.1 + (target_ratio * 24.9), 2)
    variant_delta = round(recommended_variant - current_variant, 2)

    meaningful_shift = (
        abs(variant_delta) >= 0.25
        or abs(recommended_gamma - current_gamma) >= 0.02
        or abs(recommended_bias - current_bias) >= 0.04
    )
    concern_flag = (
        anxiety_signal >= 0.40
        or reasoning_score < 0.45
        or logic_score < 0.45
        or gamma_focus >= 0.70
    )
    should_apply = bool(meaningful_shift and confidence >= SHOULD_APPLY_MIN_CONFIDENCE and concern_flag)

    reason_parts = [
        f"Reasoning demand index {round(reasoning_score * 100)}% from question complexity and response depth.",
        f"Logic-feature index {round(logic_score * 100)}% from discourse structure and topical alignment, with a capped {round(uncertainty_penalty * 100)}% uncertainty penalty.",
        f"Grounding index {round(grounding_score * 100)}% from citations and evidence markers.",
        f"Attention index {round(attention_score * 100)}% from topical alignment and simulated qualia pull.",
    ]
    if anxiety_signal >= 0.35:
        reason_parts.append(
            "The instability/uncertainty composite was elevated, so the proposal shifts toward lower variance and higher stability bias."
        )
    if stability_penalty > 0.45:
        reason_parts.append("Low stability detected, so coherence safeguards were increased.")
    if citation_count >= 4:
        reason_parts.append("Strong citation grounding supported the proposal.")

    return {
        "model_scope": "exploratory_sandbox_proposal",
        "feature_version": FEATURE_VERSION,
        "measurement_status": "constructed_text_feature_index",
        "psychometric_status": "not_psychometrically_validated",
        "external_validation_required": True,
        "validation_status": "not_validated",
        "auto_apply_allowed": False,
        "variant": recommended_variant,
        "gamma": round(recommended_gamma, 2),
        "stability_bias": round(recommended_bias, 2),
        "delta": variant_delta,
        "confidence": round(confidence, 4),
        "focus_scores": {
            "gamma": round(gamma_focus, 4),
            "attention": round(attention_score, 4),
            "reasoning": round(reasoning_score, 4),
            "logic": round(logic_score, 4),
            "anxiety": round(anxiety_signal, 4),
            "uncertainty_penalty": round(uncertainty_penalty, 4),
            "grounding": round(grounding_score, 4),
            "alignment": round(alignment, 4),
            "structure": round(structure, 4),
            "discourse": round(discourse, 4),
            "depth": round(depth, 4),
            "reasoning_demand": round(reasoning_demand, 4),
            "adequacy": round(adequacy, 4),
        },
        "reason": " ".join(reason_parts),
        "should_apply": should_apply,
    }
