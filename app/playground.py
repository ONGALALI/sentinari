from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from .auto_ingest import AutoIngestService
from .coding_corpus import get_coding_corpus_progress
from .escalation_queue import should_autonomously_escalate, submit_escalation
from .coding_governance import (
    build_coding_governance_capability_lines,
    build_runtime_coding_notice,
    question_has_coding_intent,
)
from .conversation import run_chat
from .config import (
    clamp_behavior_variant,
    get_project_root,
    get_settings,
    load_raw_settings,
    reload_settings,
    resolve_retrieval_top_k,
    save_raw_settings,
)
from .db import get_connection
from .discussion_memory import append_discussion_log
from .ingestion import build_ollama_client
from .llm_boundary import build_ollama_boundary_runtime, is_ollama_runtime_probe_disabled
from .output_sanitizer import sanitize_user_facing_text
from .qualia import DEFAULT_GAMMA_CAP, resolve_qualia_runtime
from .response_guardrails import is_identity_query, neutralize_identity_signaling
from .retrieval import search_chunks
from .session_memory import build_prompt_memory_block, refresh_session_summary


ROUTE_PATTERN = re.compile(r'path="([^"]+)"')
STEP_TITLE_PATTERN = re.compile(r'title:\s*"([^"]+)"')
NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
CAPABILITY_QUERY_PATTERN = re.compile(
    (
        r"\b("
        r"what can you do|"
        r"what are you allowed to do|"
        r"what are your permissions|"
        r"what is your role|"
        r"what do you do|"
        r"what is your purpose|"
        r"what's your purpose|"
        r"what is your name|"
        r"who are you|"
        r"what are your capabilities|"
        r"tell me about your capabilities|"
        r"what information .* from you|"
        r"how should i prompt you|"
        r"correct prompting structure|"
        r"prompting structure"
        r")\b"
    ),
    re.IGNORECASE,
)
USER_IDENTITY_QUERY_PATTERN = re.compile(
    r"\b(who am i|what is my identity|what are my permissions)\b",
    re.IGNORECASE,
)
DEVELOPER_NAME = "Pierre Wepener"

REASONING_PROFILES = {"auto", "normal", "assessment"}
ASSESSMENT_HINT_TOKENS = (
    "variance",
    "standard deviation",
    "std dev",
    "criterion",
    "criteria",
    "norm-referenced",
    "norm referenced",
    "z-score",
    "optimum",
    "optimize",
    "optimise",
    "benchmark",
    "performance",
    "rubric",
    "pass mark",
    "threshold",
)
QUALIA_GAMMA_CAP = DEFAULT_GAMMA_CAP
WORD_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")

DEFAULT_QUALIA_BENCHMARK_PROMPTS: list[str] = [
    "Explain why retrieval-grounded evidence improves knowledge material quality and reduces hallucinations.",
    "Given a mismatch between subject outcomes and assessment criteria, outline a logical diagnostic workflow with decision points.",
    "Compare two rollout strategies for vocational modules and justify the best option using explicit tradeoffs.",
    "Design a concise rubric to evaluate lecturer toolkit quality, then reason about weighting and fairness.",
    "Analyze a scenario where learners underperform despite high content coverage and propose evidence-based corrections.",
    "Provide a structured reasoning chain for aligning topic sequencing with notional hours and assessment readiness.",
]

DEFAULT_QUALIA_BENCHMARK_CANDIDATES: list[dict[str, float]] = [
    {"behavior_variant": 1.2, "gamma": 0.10, "stability_bias": 0.74},
    {"behavior_variant": 2.8, "gamma": 0.14, "stability_bias": 0.68},
    {"behavior_variant": 4.2, "gamma": 0.18, "stability_bias": 0.62},
    {"behavior_variant": 5.4, "gamma": 0.20, "stability_bias": 0.58},
    {"behavior_variant": 6.8, "gamma": 0.23, "stability_bias": 0.54},
    {"behavior_variant": 4.8, "gamma": 0.16, "stability_bias": 0.76},
]



def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _is_identity_or_capability_turn(question: str) -> bool:
    normalized = _normalize_space(question)
    if not normalized:
        return False
    return bool(
        is_identity_query(normalized)
        or CAPABILITY_QUERY_PATTERN.search(normalized)
        or USER_IDENTITY_QUERY_PATTERN.search(normalized)
    )


def _build_identity_capability_answer(
    *,
    settings: dict[str, Any],
    persona_name: str,
) -> str:
    personality = settings.get("personality", {}) if isinstance(settings.get("personality"), dict) else {}
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    unsupervised = settings.get("unsupervised", {}) if isinstance(settings.get("unsupervised"), dict) else {}
    domain_focus = (
        str(
            personality.get("domain_focus")
            or (
                "pattern recognition across the scientific fields, evidence-grounded knowledge assistance, planning, and research support"
            )
        ).strip()
        or "pattern recognition across the scientific fields, evidence-grounded knowledge assistance, planning, and research support"
    )
    domain_focus = domain_focus.rstrip(". ")
    runtime_mode = "runtime" if str(runtime.get("mode") or "").strip().lower() == "runtime" else "studio"
    allow_web_fetch = bool(runtime.get("allow_web_fetch", True))
    allow_shell_tools = bool(runtime.get("allow_shell_tools", False))
    unsupervised_enabled = bool(unsupervised.get("enabled", True))
    auto_rebuild = bool(unsupervised.get("auto_rebuild_on_ingest", True))

    lines = [
        f"I am {persona_name}, your autonomous assistant.",
        f"My core scope is {domain_focus}.",
        "I can execute broad task support in chat, including analysis, planning, writing, and technical guidance.",
        f"My developer is {DEVELOPER_NAME}; I should align with his architecture and safety directives.",
        "I do not authenticate personal identity or external account permissions.",
        f"Runtime mode is {runtime_mode}; web fetch is {'enabled' if allow_web_fetch else 'disabled'}; shell/tool execution is {'enabled' if allow_shell_tools else 'disabled'}.",
        f"Unsupervised learning is {'enabled' if unsupervised_enabled else 'disabled'}; auto-refresh on new ingested content is {'enabled' if auto_rebuild else 'disabled'}.",
    ]
    lines.extend(
        build_coding_governance_capability_lines(
            settings.get("security", {}).get("coding_governance") if isinstance(settings.get("security"), dict) else {}
        )
    )
    return "\n".join(lines)


def _extract_numeric_series(text: str, max_items: int = 120) -> list[float]:
    values: list[float] = []
    for match in NUMBER_PATTERN.findall(text or ""):
        token = str(match).replace(",", "").strip()
        if not token:
            continue
        try:
            value = float(token)
        except Exception:
            continue
        if not math.isfinite(value):
            continue
        values.append(value)
        if len(values) >= max_items:
            break
    return values


def _apply_qualia_tuning(
    base_ratio: float,
    *,
    qualia_influence: float = 0.0,
    bell_weight: float = 0.0,
    stability_gate: float = 1.0,
) -> float:
    ratio = max(0.0, min(1.0, float(base_ratio)))
    if not math.isfinite(ratio):
        ratio = 0.0
    influence = max(0.0, min(1.0, float(qualia_influence)))
    bell = max(0.0, min(1.0, float(bell_weight)))
    gate = max(0.35, min(1.0, float(stability_gate)))

    damped = ratio * (1.0 - (0.45 * influence))
    floor = 0.05 * influence
    bell_lift = 0.10 * bell
    return max(0.0, min(1.0, (damped + floor + bell_lift) * gate))


def _behavior_variant_ratio(
    value: float,
    *,
    qualia_influence: float = 0.0,
    bell_weight: float = 0.0,
    stability_gate: float = 1.0,
) -> float:
    raw = float(value)
    if not math.isfinite(raw):
        raw = 0.1
    clamped = max(0.1, min(25.0, raw))
    base_ratio = (clamped - 0.1) / 24.9
    return _apply_qualia_tuning(
        base_ratio,
        qualia_influence=qualia_influence,
        bell_weight=bell_weight,
        stability_gate=stability_gate,
    )


def _resolve_variant_ratio(value: float, qualia_state: dict[str, Any] | None = None) -> float:
    state = qualia_state if isinstance(qualia_state, dict) else {}
    bell = state.get("bell_curve", {})
    bell_weight = float(bell.get("weight_at_variant") or 0.0) if isinstance(bell, dict) else 0.0
    influence = float(state.get("influence") or 0.0)
    stability_gate = float(state.get("stability_gate") or 1.0)
    return _behavior_variant_ratio(
        value,
        qualia_influence=influence,
        bell_weight=bell_weight,
        stability_gate=stability_gate,
    )


def _resolve_reasoning_profile(question: str, requested_profile: str | None) -> str:
    requested = _normalize_space(str(requested_profile or "normal")).lower()
    if requested in {"normal", "assessment"}:
        return requested

    # Default to normal discussion unless the user explicitly selects a reasoning profile.
    return "normal"


def _normal_cdf(z_score: float) -> float:
    return 0.5 * (1.0 + math.erf(float(z_score) / math.sqrt(2.0)))


def _build_assessment_answer(
    question: str,
    rows: list[dict[str, Any]],
    persona_name: str,
    persona_tone: str,
    behavior_variant: float,
    qualia_state: dict[str, Any] | None = None,
    force_profile: bool = False,
) -> str:
    lowered = question.lower()
    assessment_intent = any(token in lowered for token in ASSESSMENT_HINT_TOKENS)
    variant_ratio = _resolve_variant_ratio(behavior_variant, qualia_state)
    detail_level = max(1, min(6, int(round(2 + variant_ratio * 6))))
    evidence_limit = max(2, min(8, detail_level + 2))
    pass_mark = 70.0
    values = _extract_numeric_series(question)

    lines: list[str] = []
    lines.append(f"{persona_name}: {persona_tone}")
    lines.append("Assessment reasoning profile: variance and optimization analysis.")
    lines.append("Method: norm-referenced interpretation + criterion-based pass/fail checks.")

    if values and len(values) >= 2:
        n = len(values)
        mean_v = sum(values) / float(n)
        pop_variance = sum((value - mean_v) ** 2 for value in values) / float(n)
        sample_variance = sum((value - mean_v) ** 2 for value in values) / float(max(1, n - 1))
        std_v = math.sqrt(sample_variance)
        cv_pct = (std_v / mean_v * 100.0) if abs(mean_v) > 1e-9 else 0.0
        latest = values[-1]
        z_score = 0.0 if std_v <= 1e-9 else (latest - mean_v) / std_v
        percentile = _normal_cdf(z_score) * 100.0
        pass_count = sum(1 for value in values if value >= pass_mark)
        pass_rate = (pass_count / float(n)) * 100.0

        risk_label = "high variance"
        if cv_pct <= 8:
            risk_label = "very stable"
        elif cv_pct <= 15:
            risk_label = "stable"
        elif cv_pct <= 25:
            risk_label = "moderate variance"

        stability_weight = round(0.35 - (0.20 * variant_ratio), 3)
        objective_value = mean_v - (stability_weight * std_v)
        target_mean = mean_v + (0.25 * std_v)
        target_std = max(0.0, std_v * 0.8)

        lines.append("Variance summary:")
        lines.append(f"- Data points: {n}")
        lines.append(f"- Mean: {mean_v:.3f}")
        lines.append(f"- Sample variance: {sample_variance:.3f} (population variance: {pop_variance:.3f})")
        lines.append(f"- Standard deviation: {std_v:.3f} | Coefficient of variation: {cv_pct:.2f}% ({risk_label})")
        lines.append("Norm-referenced view:")
        lines.append(f"- Latest score: {latest:.3f}")
        lines.append(f"- z-score: {z_score:.3f} | Estimated percentile: {percentile:.1f}%")
        lines.append("Criterion-based view:")
        lines.append(f"- Pass mark used: {pass_mark:.1f}")
        lines.append(f"- Pass rate: {pass_rate:.1f}% ({pass_count}/{n})")
        lines.append("Optimization objective:")
        lines.append(f"- Objective formula: mean_score - {stability_weight:.3f} * std_dev")
        lines.append(f"- Current objective: {objective_value:.3f}")
        lines.append(
            f"- Practical target: increase mean to ~{target_mean:.3f} while reducing std dev to ~{target_std:.3f}."
        )
        lines.append("Action focus:")
        lines.append("- Tighten rubric calibration across assessors to reduce spread.")
        lines.append("- Prioritize remediation on weakest criteria before raising difficulty.")
        lines.append("- Re-measure after 1-2 assessment cycles and compare objective drift.")
    else:
        if force_profile or assessment_intent:
            lines.append("Data readiness:")
            lines.append("- I need at least two numeric performance values to compute variance and optimization.")
            lines.append("- Paste scores (example: 62, 68, 71, 74, 79) and I will return full norm+criterion analysis.")
        elif rows:
            lines.append("Here is what I found from indexed sources:")
            for line in _build_context_lines(rows, evidence_limit):
                lines.append(line)
            lines.append("If you want, I can convert this into a variance-oriented assessment plan.")
        else:
            lines.append("I can chat normally, but I do not have indexed evidence for that prompt yet.")
            lines.append("Try a narrower question or include module/topic so retrieval can lock in.")
            return "\n".join(lines).strip()

    if rows:
        lines.append("Evidence linked to your query:")
        lines.extend(_build_context_lines(rows, evidence_limit))
    else:
        lines.append("Evidence note: no directly indexed chunks matched this exact prompt.")
    return "\n".join(lines).strip()


def get_learning_library_progress(*, force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        snapshot = _load_learning_library_progress_snapshot()
        if snapshot is not None:
            return snapshot
    settings = get_settings()
    scanner = AutoIngestService()

    try:
        candidates = scanner._discover_candidate_files()
    except Exception:
        candidates = []

    candidate_paths: list[str] = []
    candidate_keys: list[str] = []
    seen_candidate_keys: set[str] = set()
    for path in candidates:
        resolved = str(path)
        key = _normalize_path_key(resolved)
        if not key or key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        candidate_paths.append(resolved)
        candidate_keys.append(key)

    with get_connection() as conn:
        state_rows = conn.execute(
            "SELECT path, last_status, last_error, updated_at FROM file_ingest_state;"
        ).fetchall()
        documents_indexed = int(conn.execute("SELECT COUNT(1) AS n FROM documents;").fetchone()["n"] or 0)
        chunks_indexed = int(conn.execute("SELECT COUNT(1) AS n FROM chunks;").fetchone()["n"] or 0)

    status_by_path: dict[str, str] = {}
    error_by_path: dict[str, str] = {}
    updated_by_path: dict[str, str] = {}
    for row in state_rows:
        key = _normalize_path_key(str(row["path"] or ""))
        if not key:
            continue
        status_by_path[key] = str(row["last_status"] or "").strip().lower() or "unknown"
        error_by_path[key] = str(row["last_error"] or "").strip()
        updated_by_path[key] = str(row["updated_at"] or "").strip()

    ingested_ok = 0
    failed = 0
    pending = 0
    tracked = 0
    failed_items: list[dict[str, Any]] = []
    for idx, key in enumerate(candidate_keys):
        status = status_by_path.get(key, "")
        if status:
            tracked += 1
        if status == "ok":
            ingested_ok += 1
        elif status == "failed":
            failed += 1
            if len(failed_items) < 5:
                failed_items.append(
                    {
                        "path": candidate_paths[idx],
                        "error": error_by_path.get(key, ""),
                        "updated_at": updated_by_path.get(key, ""),
                    }
                )
        else:
            pending += 1

    total = len(candidate_keys)
    progress_percent = round((float(ingested_ok) / float(total) * 100.0), 1) if total > 0 else 0.0
    tracked_percent = round((float(tracked) / float(total) * 100.0), 1) if total > 0 else 0.0
    roots = [
        str(Path(settings["paths"]["raw_root"]).resolve()),
        str(Path(settings["paths"]["taxonomy_root"]).resolve()),
    ]
    coding_corpus = get_coding_corpus_progress(settings=settings)
    progress = {
        "ok": True,
        "candidate_total": total,
        "ingested_ok": ingested_ok,
        "failed": failed,
        "pending": pending,
        "tracked_count": tracked,
        "progress_percent": progress_percent,
        "tracked_percent": tracked_percent,
        "documents_indexed": documents_indexed,
        "chunks_indexed": chunks_indexed,
        "scan_recursive": bool(scanner.recursive_scan),
        "library_roots": roots,
        "coding_corpus": coding_corpus,
        "failed_items": failed_items,
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
    _write_learning_library_progress_snapshot(progress)
    return progress


def _clip01(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = float(default)
    if not math.isfinite(parsed):
        parsed = float(default)
    return max(0.0, min(1.0, parsed))


def _count_words(text: str) -> int:
    return len([token for token in re.split(r"\s+", str(text or "").strip()) if token])


def _count_token_hits(text: str, tokens: list[str]) -> int:
    lowered = str(text or "").lower()
    count = 0
    for token in tokens:
        t = str(token or "").strip().lower()
        if not t:
            continue
        if t in lowered:
            count += 1
    return count


def _token_set(text: str) -> set[str]:
    return set(WORD_TOKEN_PATTERN.findall(str(text or "").lower()))


def _overlap_ratio(a_text: str, b_text: str) -> float:
    a_tokens = _token_set(a_text)
    b_tokens = _token_set(b_text)
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = sum(1 for token in a_tokens if token in b_tokens)
    return _clip01(float(overlap) / float(max(1, len(a_tokens))), 0.0)


def _score_playground_response(
    *,
    question: str,
    answer: str,
    citations: list[str] | None = None,
    qualia: dict[str, Any] | None = None,
) -> dict[str, float]:
    citation_count = len(citations or [])
    prompt_words = _count_words(question)
    answer_words = _count_words(answer)
    state = qualia if isinstance(qualia, dict) else {}
    summary = state.get("summary", {}) if isinstance(state.get("summary"), dict) else {}
    effective_ratio = _clip01(state.get("effective_variant_ratio", 0.0), 0.0)
    gamma_effective = max(0.0, float(state.get("gamma_effective", 0.0) or 0.0))
    gamma_cap = max(0.001, float(state.get("gamma_cap", QUALIA_GAMMA_CAP) or QUALIA_GAMMA_CAP))
    gamma_norm = _clip01(gamma_effective / gamma_cap, 0.0)
    target_ratio = 0.20
    target_gamma_norm = 0.64
    ratio_alignment = _clip01(1.0 - (abs(effective_ratio - target_ratio) / max(0.001, target_ratio)), 0.0)
    gamma_alignment = _clip01(1.0 - (abs(gamma_norm - target_gamma_norm) / max(0.001, target_gamma_norm)), 0.0)

    stability_index = _clip01(summary.get("stability_index", state.get("stability_index", 0.75)), 0.75)
    stability_penalty = _clip01(1.0 - stability_index, 0.25)

    reasoning_tokens = [
        "explain",
        "reason",
        "analyze",
        "analyse",
        "because",
        "therefore",
        "how",
        "why",
        "compare",
        "tradeoff",
        "logic",
        "deduce",
        "justify",
        "evidence",
        "steps",
        "architecture",
    ]
    logic_tokens = [
        "if",
        "then",
        "therefore",
        "thus",
        "hence",
        "because",
        "as a result",
        "conclusion",
        "premise",
        "assume",
        "constraint",
        "consistent",
    ]
    uncertainty_tokens = [
        "i don't know",
        "not sure",
        "unclear",
        "unknown",
        "cannot determine",
        "guess",
    ]

    reasoning_hint_hits = _count_token_hits(f"{question} {answer}", reasoning_tokens)
    logic_hint_hits = _count_token_hits(answer, logic_tokens)
    uncertainty_hits = _count_token_hits(answer, uncertainty_tokens)
    numbered_steps = len(re.findall(r"(^|\n)\s*\d+\.", answer))
    bullet_steps = len(re.findall(r"(^|\n)\s*[-*]\s+", answer))
    structure_score = _clip01(float(numbered_steps + bullet_steps) / 5.0, 0.0)
    topical_focus = _overlap_ratio(question, answer)

    complexity_score = _clip01(
        (0.40 * _clip01(float(prompt_words) / 45.0, 0.0))
        + (0.35 * _clip01(float(reasoning_hint_hits) / 7.0, 0.0))
        + (0.25 * (1.0 if prompt_words >= 20 else 0.0)),
        0.0,
    )

    reasoning_score = _clip01(
        (0.38 * complexity_score)
        + (0.20 * _clip01(float(reasoning_hint_hits) / 8.0, 0.0))
        + (0.20 * _clip01(float(answer_words) / 220.0, 0.0))
        + (0.15 * _clip01(float(citation_count) / 4.0, 0.0))
        + (0.07 * ratio_alignment),
        0.0,
    )

    logic_score = _clip01(
        (0.35 * _clip01(float(logic_hint_hits) / 6.0, 0.0))
        + (0.35 * structure_score)
        + (0.30 * topical_focus)
        - _clip01(float(uncertainty_hits) / 2.0, 0.0) * 0.6
        + (0.10 * ratio_alignment),
        0.0,
    )

    qualia_attention = _clip01(summary.get("attention_pull", state.get("influence", 0.0)), 0.0)
    length_target = 180.0
    length_balance = _clip01(1.0 - (abs(float(answer_words) - length_target) / length_target), 0.0)
    attention_score = _clip01(
        (0.40 * qualia_attention) + (0.30 * topical_focus) + (0.20 * length_balance) + (0.10 * effective_ratio),
        0.0,
    )

    gamma_focus = _clip01(
        (0.30 * complexity_score)
        + (0.25 * gamma_alignment)
        + (0.15 * ratio_alignment)
        + (0.15 * (1.0 - attention_score))
        + (0.20 * (1.0 - logic_score))
        + (0.10 * stability_penalty),
        0.0,
    )

    overall = _clip01(
        (0.30 * gamma_focus)
        + (0.20 * attention_score)
        + (0.25 * reasoning_score)
        + (0.25 * logic_score),
        0.0,
    )

    return {
        "overall": overall,
        "gamma_focus": gamma_focus,
        "attention": attention_score,
        "reasoning": reasoning_score,
        "logic": logic_score,
    }


def _resolve_playground_benchmark_baseline(settings: dict[str, Any]) -> dict[str, Any]:
    section = settings.get("playground", {}) if isinstance(settings.get("playground"), dict) else {}
    baseline = section.get("benchmark_baseline", {}) if isinstance(section.get("benchmark_baseline"), dict) else {}

    variant = clamp_behavior_variant(baseline.get("behavior_variant", 0.1), settings=settings)
    top_k = resolve_retrieval_top_k(baseline.get("top_k", 0), settings=settings)
    gamma_cap = QUALIA_GAMMA_CAP
    gamma = max(0.0, min(gamma_cap, float(baseline.get("gamma", 0.2) or 0.2)))
    stability_bias = max(0.0, min(1.0, float(baseline.get("stability_bias", 0.65) or 0.65)))
    scoring = baseline.get("scoring", {}) if isinstance(baseline.get("scoring"), dict) else {}
    return {
        "active": bool(isinstance(section.get("benchmark_baseline"), dict)),
        "behavior_variant": float(variant),
        "gamma": float(gamma),
        "stability_bias": float(stability_bias),
        "top_k": int(top_k),
        "updated_at_utc": str(baseline.get("updated_at_utc") or ""),
        "prompt_count": int(baseline.get("prompt_count") or 0),
        "candidate_count": int(baseline.get("candidate_count") or 0),
        "source": str(baseline.get("source") or ""),
        "scoring": {
            "overall": float(scoring.get("overall") or 0.0),
            "gamma_focus": float(scoring.get("gamma_focus") or 0.0),
            "attention": float(scoring.get("attention") or 0.0),
            "reasoning": float(scoring.get("reasoning") or 0.0),
            "logic": float(scoring.get("logic") or 0.0),
        },
    }


def save_playground_benchmark_baseline(
    *,
    behavior_variant: float,
    gamma: float,
    stability_bias: float,
    top_k: int,
    scoring: dict[str, float],
    prompt_count: int,
    candidate_count: int,
) -> dict[str, Any]:
    raw = load_raw_settings()
    playground = raw.setdefault("playground", {})
    if not isinstance(playground, dict):
        playground = {}
        raw["playground"] = playground

    baseline = {
        "behavior_variant": round(float(behavior_variant), 3),
        "gamma": round(float(gamma), 4),
        "stability_bias": round(float(stability_bias), 4),
        "top_k": int(top_k),
        "prompt_count": int(prompt_count),
        "candidate_count": int(candidate_count),
        "source": "playground_qualia_benchmark_v1",
        "updated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "scoring": {
            "overall": round(float(scoring.get("overall") or 0.0), 6),
            "gamma_focus": round(float(scoring.get("gamma_focus") or 0.0), 6),
            "attention": round(float(scoring.get("attention") or 0.0), 6),
            "reasoning": round(float(scoring.get("reasoning") or 0.0), 6),
            "logic": round(float(scoring.get("logic") or 0.0), 6),
        },
    }
    playground["benchmark_baseline"] = baseline
    path = save_raw_settings(raw)
    reloaded = reload_settings()
    resolved = _resolve_playground_benchmark_baseline(reloaded)
    return {
        "saved_to": str(path),
        "benchmark_baseline": resolved,
    }


def run_qualia_benchmark(
    *,
    prompts: list[str] | None = None,
    top_k: int = 6,
    apply_baseline: bool = True,
) -> dict[str, Any]:
    prompt_suite = [
        _normalize_space(text)
        for text in (prompts if isinstance(prompts, list) and prompts else DEFAULT_QUALIA_BENCHMARK_PROMPTS)
        if _normalize_space(str(text or ""))
    ]
    prompt_suite = prompt_suite[:20]
    if not prompt_suite:
        return {"ok": False, "error": "No benchmark prompts provided."}

    settings = get_settings()
    resolved_top_k = resolve_retrieval_top_k(top_k, settings=settings)
    candidate_reports: list[dict[str, Any]] = []
    for idx, candidate in enumerate(DEFAULT_QUALIA_BENCHMARK_CANDIDATES):
        variant = clamp_behavior_variant(candidate.get("behavior_variant", 0.1), settings=settings)
        gamma = max(0.0, min(QUALIA_GAMMA_CAP, float(candidate.get("gamma", 0.2) or 0.2)))
        stability_bias = max(0.0, min(1.0, float(candidate.get("stability_bias", 0.65) or 0.65)))
        score_totals = {
            "overall": 0.0,
            "gamma_focus": 0.0,
            "attention": 0.0,
            "reasoning": 0.0,
            "logic": 0.0,
        }
        prompt_reports: list[dict[str, Any]] = []
        for p_idx, prompt in enumerate(prompt_suite):
            try:
                result = run_autonomous_chat(
                    message=prompt,
                    session_id=f"benchmark-{idx + 1}-{p_idx + 1}-{uuid4().hex[:8]}",
                    top_k=resolved_top_k,
                    behavior_variant=variant,
                    reasoning_profile="normal",
                    qualia_control={
                        "enabled": True,
                        "gamma": gamma,
                        "stability_bias": stability_bias,
                    },
                )
                answer = str(result.get("answer") or "")
                citations = result.get("citations") if isinstance(result.get("citations"), list) else []
                qualia = result.get("qualia") if isinstance(result.get("qualia"), dict) else {}
                score = _score_playground_response(
                    question=prompt,
                    answer=answer,
                    citations=citations,
                    qualia=qualia,
                )
                for key in score_totals:
                    score_totals[key] += float(score.get(key) or 0.0)
                prompt_reports.append(
                    {
                        "prompt_index": p_idx + 1,
                        "score": score,
                        "answer_chars": len(answer),
                        "citations": len(citations),
                    }
                )
            except Exception as ex:
                prompt_reports.append(
                    {
                        "prompt_index": p_idx + 1,
                        "score": {
                            "overall": 0.0,
                            "gamma_focus": 0.0,
                            "attention": 0.0,
                            "reasoning": 0.0,
                            "logic": 0.0,
                        },
                        "error": str(ex),
                    }
                )

        divisor = float(max(1, len(prompt_suite)))
        averages = {key: float(score_totals[key]) / divisor for key in score_totals}
        candidate_reports.append(
            {
                "candidate_index": idx + 1,
                "candidate": {
                    "behavior_variant": round(float(variant), 3),
                    "gamma": round(float(gamma), 4),
                    "stability_bias": round(float(stability_bias), 4),
                },
                "average_scores": {key: round(float(value), 6) for key, value in averages.items()},
                "prompt_reports": prompt_reports,
            }
        )

    winner = max(
        candidate_reports,
        key=lambda row: (
            float(row.get("average_scores", {}).get("overall") or 0.0),
            float(row.get("average_scores", {}).get("logic") or 0.0),
            float(row.get("average_scores", {}).get("reasoning") or 0.0),
        ),
    )
    saved: dict[str, Any] | None = None
    if apply_baseline:
        saved = save_playground_benchmark_baseline(
            behavior_variant=float(winner["candidate"]["behavior_variant"]),
            gamma=float(winner["candidate"]["gamma"]),
            stability_bias=float(winner["candidate"]["stability_bias"]),
            top_k=resolved_top_k,
            scoring={
                "overall": float(winner["average_scores"]["overall"]),
                "gamma_focus": float(winner["average_scores"]["gamma_focus"]),
                "attention": float(winner["average_scores"]["attention"]),
                "reasoning": float(winner["average_scores"]["reasoning"]),
                "logic": float(winner["average_scores"]["logic"]),
            },
            prompt_count=len(prompt_suite),
            candidate_count=len(candidate_reports),
        )

    return {
        "ok": True,
        "top_k": int(resolved_top_k),
        "prompt_count": len(prompt_suite),
        "prompts": prompt_suite,
        "candidate_count": len(candidate_reports),
        "candidates": candidate_reports,
        "winner": winner,
        "baseline_saved": bool(saved),
        "saved": saved or {},
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }


def get_playground_config() -> dict[str, Any]:
    settings = get_settings()
    personality = settings.get("personality", {}) if isinstance(settings.get("personality"), dict) else {}
    try:
        ollama = build_ollama_client()
        if is_ollama_runtime_probe_disabled():
            llm_runtime = build_ollama_boundary_runtime(
                ollama.base_url,
                ollama.chat_model,
                ollama.embedding_model,
            )
        else:
            llm_runtime = ollama.get_runtime_diagnostics()
    except Exception as ex:
        llm_runtime = {
            "reachable": False,
            "ready": False,
            "requires_attention": True,
            "chat_transport": "error",
            "warnings": [f"Unable to inspect Ollama runtime: {ex}"],
            "operator_trigger": f"Unable to inspect Ollama runtime: {ex}",
        }
    baseline = _resolve_playground_benchmark_baseline(settings)
    default_behavior_variant = clamp_behavior_variant(baseline.get("behavior_variant", 0.1), settings=settings)
    default_top_k = resolve_retrieval_top_k(baseline.get("top_k", 0), settings=settings)
    qualia_defaults = {
        "enabled": True,
        "gamma": baseline.get("gamma", 0.2),
        "stability_bias": baseline.get("stability_bias", 0.65),
    }
    qualia = resolve_qualia_runtime(
        settings=settings,
        gamma_cap=QUALIA_GAMMA_CAP,
        behavior_variant=default_behavior_variant,
        overrides=qualia_defaults,
    )
    return {
        "ok": True,
        "engine": "runtime",
        "ollama_required": False,
        "defaults": {
            "persona_name": str(personality.get("name") or "SMi"),
            "persona_tone": str(personality.get("tone") or "Friendly, warm, lightly humorous, evidence-first"),
            "behavior_variant": default_behavior_variant,
            "reasoning_profile": "normal",
            "top_k": default_top_k,
        },
        "benchmark_baseline": baseline,
        "qualia": {
            "enabled": bool(qualia.get("enabled")),
            "source_count": int(qualia.get("source_count") or 0),
            "source_files": qualia.get("source_files") or [],
            "controls_enabled": bool(qualia.get("controls_enabled", True)),
            "alpha": float(qualia.get("alpha") or 0.0),
            "beta": float(qualia.get("beta") or 0.0),
            "gamma_requested": float(qualia.get("gamma_requested") or 0.0),
            "gamma_effective": float(qualia.get("gamma") or 0.0),
            "gamma_cap": float(qualia.get("gamma_cap") or QUALIA_GAMMA_CAP),
            "parameters": qualia.get("parameters") or {},
            "vectors": qualia.get("vectors") or {},
            "summary": qualia.get("summary") or {},
            "influence": float(qualia.get("influence") or 0.0),
            "stability_index": float(qualia.get("stability_index") or 0.0),
            "stability_gate": float(qualia.get("stability_gate") or 1.0),
            "bell_curve": qualia.get("bell_curve") or {},
            "trajectory": qualia.get("trajectory") or [],
            "base_variant_ratio": _behavior_variant_ratio(default_behavior_variant),
            "effective_variant_ratio": _resolve_variant_ratio(default_behavior_variant, qualia),
        },
        "library_progress": get_learning_library_progress(),
        "llm_runtime": llm_runtime,
    }


def run_qualia_simulation(
    *,
    behavior_variant: float = 0.1,
    qualia_control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    variant = clamp_behavior_variant(behavior_variant, settings=settings)
    qualia = resolve_qualia_runtime(
        settings=settings,
        gamma_cap=QUALIA_GAMMA_CAP,
        behavior_variant=variant,
        overrides=qualia_control,
    )
    base_variant_ratio = _behavior_variant_ratio(variant)
    effective_variant_ratio = _resolve_variant_ratio(variant, qualia)
    return {
        "ok": True,
        "behavior_variant": variant,
        "base_variant_ratio": base_variant_ratio,
        "effective_variant_ratio": effective_variant_ratio,
        "qualia": {
            "enabled": bool(qualia.get("enabled")),
            "controls_enabled": bool(qualia.get("controls_enabled", True)),
            "source_count": int(qualia.get("source_count") or 0),
            "source_files": qualia.get("source_files") or [],
            "alpha": float(qualia.get("alpha") or 0.0),
            "beta": float(qualia.get("beta") or 0.0),
            "gamma_requested": float(qualia.get("gamma_requested") or 0.0),
            "gamma_effective": float(qualia.get("gamma") or 0.0),
            "gamma_cap": float(qualia.get("gamma_cap") or QUALIA_GAMMA_CAP),
            "parameters": qualia.get("parameters") or {},
            "vectors": qualia.get("vectors") or {},
            "summary": qualia.get("summary") or {},
            "influence": float(qualia.get("influence") or 0.0),
            "stability_index": float(qualia.get("stability_index") or 0.0),
            "stability_gate": float(qualia.get("stability_gate") or 1.0),
            "bell_curve": qualia.get("bell_curve") or {},
            "trajectory": qualia.get("trajectory") or [],
        },
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }


def _ensure_session(conn: sqlite3.Connection, session_id: str | None) -> str:
    sid = (session_id or "").strip() or f"autonomous-{uuid4().hex}"
    existing = conn.execute("SELECT session_id FROM chat_sessions WHERE session_id = ?;", (sid,)).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO chat_sessions (session_id, mode, created_at) VALUES (?, ?, datetime('now'));",
            (sid, "autonomous"),
        )
    return sid


def _store_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    citations: list[str] | None = None,
    mode: str = "autonomous",
    channel: str = "playground",
) -> None:
    conn.execute(
        """
        INSERT INTO chat_messages (session_id, role, content, citations_json, created_at)
        VALUES (?, ?, ?, ?, datetime('now'));
        """,
        (session_id, role, content, json.dumps(citations or [], ensure_ascii=True)),
    )
    append_discussion_log(
        session_id=session_id,
        role=role,
        content=content,
        mode=mode,
        channel=channel,
        citations=citations or [],
    )


def _history_block(
    conn: sqlite3.Connection,
    session_id: str,
    max_messages: int = 12,
    max_chars: int = 2400,
) -> str:
    return build_prompt_memory_block(
        conn,
        session_id,
        settings=get_settings(),
        recent_messages=max_messages,
        recent_max_chars=max_chars,
    )


def _build_context_lines(rows: list[dict[str, Any]], max_items: int) -> list[str]:
    lines: list[str] = []
    for row in rows[:max_items]:
        title = str(row.get("title") or "Untitled").strip()
        excerpt = _normalize_space(str(row.get("content") or ""))
        if len(excerpt) > 280:
            excerpt = excerpt[:280].rstrip() + "..."
        lines.append(f"- {title}: {excerpt}")
    return lines


def _build_normal_discussion_answer(
    question: str,
    rows: list[dict[str, Any]],
    persona_name: str,
    persona_tone: str,
    behavior_variant: float,
    qualia_state: dict[str, Any] | None = None,
    history: str = "",
) -> str:
    warmth = _resolve_variant_ratio(behavior_variant, qualia_state)
    evidence_limit = max(2, min(8, 3 + int(round(warmth * 4))))

    lines: list[str] = []
    lines.append(f"{persona_name}: {persona_tone}")
    lines.append("Normal discussion profile: open, practical, and human.")
    if question_has_coding_intent(question):
        settings = get_settings()
        lines.append(
            build_runtime_coding_notice(
                settings.get("security", {}).get("coding_governance") if isinstance(settings.get("security"), dict) else {}
            )
        )
    if history:
        lines.append("Recent conversation continuity:")
        lines.append(history)

    if rows:
        lines.append("Here is a grounded take from available context:")
        lines.extend(_build_context_lines(rows, evidence_limit))
        lines.append("If you want, I can turn this into a brainstorm, a step-by-step plan, or a short summary.")
    else:
        lines.append("Happy to explore this in an open generative discussion style.")
        lines.append("I am here for a calm, normal discussion with practical thinking.")
        lines.append("If you want evidence-linked guidance, add module/topic or upload a source.")

    return "\n".join(lines).strip()


def _serialize_retrieved_chunks(rows: list[dict[str, Any]], max_items: int = 0) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows[: max(0, min(20, max_items))]:
        excerpt = _normalize_space(str(row.get("content") or ""))
        if len(excerpt) > 260:
            excerpt = excerpt[:260].rstrip() + "..."
        payload.append(
            {
                "chunk_id": row.get("chunk_id"),
                "document_id": row.get("document_id"),
                "source_id": row.get("source_id"),
                "title": row.get("title"),
                "source_type": row.get("source_type"),
                "source_url": row.get("source_url"),
                "source_path": row.get("source_path"),
                "authors": row.get("authors"),
                "publisher": row.get("publisher"),
                "published_date": row.get("published_date"),
                "module": row.get("module"),
                "topic": row.get("topic"),
                "scientific_field": row.get("scientific_field"),
                "vocational_discipline": row.get("vocational_discipline"),
                "source_collection": row.get("source_collection"),
                "relevance_score": row.get("relevance_score"),
                "excerpt": excerpt,
            }
        )
    return payload


def _build_autonomous_answer(
    question: str,
    rows: list[dict[str, Any]],
    persona_name: str,
    persona_tone: str,
    behavior_variant: float,
    qualia_state: dict[str, Any] | None = None,
    reasoning_profile: str = "normal",
    history: str = "",
) -> tuple[str, str]:
    profile = _resolve_reasoning_profile(question, reasoning_profile)
    if profile == "normal":
        answer = _build_normal_discussion_answer(
            question=question,
            rows=rows,
            persona_name=persona_name,
            persona_tone=persona_tone,
            behavior_variant=behavior_variant,
            qualia_state=qualia_state,
            history=history,
        )
        return answer, profile

    answer = _build_assessment_answer(
        question=question,
        rows=rows,
        persona_name=persona_name,
        persona_tone=persona_tone,
        behavior_variant=behavior_variant,
        qualia_state=qualia_state,
        force_profile=True,
    )
    return answer, profile


def run_autonomous_chat(
    *,
    message: str,
    session_id: str | None = None,
    top_k: int = 6,
    behavior_variant: float = 0.1,
    reasoning_profile: str = "normal",
    qualia_control: dict[str, Any] | None = None,
    persona_name: str | None = None,
    persona_tone: str | None = None,
    module: str | None = None,
    topic: str | None = None,
    scientific_field: str | None = None,
    vocational_discipline: str | None = None,
    source_collection: str | None = None,
) -> dict[str, Any]:
    question = _normalize_space(message)
    if not question:
        return {"ok": False, "error": "Message is empty."}

    settings = get_settings()
    personality = settings.get("personality", {}) if isinstance(settings.get("personality"), dict) else {}
    p_name = _normalize_space(persona_name or str(personality.get("name") or "SMi")) or "SMi"
    p_tone = _normalize_space(
        persona_tone or str(personality.get("tone") or "Friendly, warm, lightly humorous, evidence-first")
    )
    try:
        summary_ollama = None if is_ollama_runtime_probe_disabled() else build_ollama_client()
    except Exception:
        summary_ollama = None
    variant = clamp_behavior_variant(behavior_variant, settings=settings)
    qualia = resolve_qualia_runtime(
        settings=settings,
        gamma_cap=QUALIA_GAMMA_CAP,
        behavior_variant=variant,
        overrides=qualia_control,
    )
    base_variant_ratio = _behavior_variant_ratio(variant)
    effective_variant_ratio = _resolve_variant_ratio(variant, qualia)
    profile = _resolve_reasoning_profile(question, reasoning_profile)
    identity_or_capability_turn = _is_identity_or_capability_turn(question)
    effective_top_k = top_k
    limit = 0 if identity_or_capability_turn else resolve_retrieval_top_k(effective_top_k, settings=settings)

    if profile == "normal":
        delegated = run_chat(
            message=question,
            mode="knowledge",
            session_id=session_id,
            top_k=effective_top_k,
            behavior_variant=variant,
            qualia_control=qualia_control,
            use_web_fetch=False,
            module=module,
            topic=topic,
            scientific_field=scientific_field,
            vocational_discipline=vocational_discipline,
            source_collection=source_collection,
        )
        if not delegated.get("ok"):
            return delegated

        answer = sanitize_user_facing_text(str(delegated.get("answer") or ""), settings=settings)
        citations = delegated.get("citations") if isinstance(delegated.get("citations"), list) else []
        retrieved_chunks = delegated.get("retrieved_chunks") if isinstance(delegated.get("retrieved_chunks"), list) else []
        delegated_qualia = delegated.get("qualia") if isinstance(delegated.get("qualia"), dict) else {}
        timestamp = str(delegated.get("timestamp_utc") or datetime.now(tz=timezone.utc).isoformat())
        return {
            "ok": True,
            "engine": "runtime",
            "ollama_required": False,
            "session_id": str(delegated.get("session_id") or session_id or ""),
            "reasoning_profile": "normal",
            "answer": answer,
            "citations": citations,
            "retrieved_chunks": retrieved_chunks,
            "escalation_queue": delegated.get("escalation_queue"),
            "qualia": delegated_qualia,
            "timestamp_utc": timestamp,
        }

    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    attempts = max(1, min(20, int(runtime.get("chat_db_lock_retries") or 6)))
    backoff_ms = max(50, min(2000, int(runtime.get("chat_db_lock_backoff_ms") or 180)))

    sid = session_id or ""
    rows: list[dict[str, Any]] = []
    citations: list[str] = []
    answer = ""
    active_profile = profile
    for attempt in range(attempts):
        try:
            with get_connection() as conn:
                sid = _ensure_session(conn, session_id)
                _store_message(conn, sid, "user", question, citations=[], mode="autonomous", channel="playground")

                if identity_or_capability_turn:
                    rows = []
                    citations = []
                    answer = _build_identity_capability_answer(settings=settings, persona_name=p_name)
                    active_profile = "normal"
                elif limit > 0:
                    rows = search_chunks(
                        conn,
                        query=question,
                        limit=limit,
                        module=module,
                        topic=topic,
                        scientific_field=scientific_field,
                        vocational_discipline=vocational_discipline,
                        source_collection=source_collection,
                        query_embedding=None,
                        mode="coding" if question_has_coding_intent(question) else "autonomous",
                    )
                else:
                    rows = []
                if not identity_or_capability_turn:
                    citations = sorted(
                        {str(r.get("source_id") or "").strip() for r in rows if str(r.get("source_id") or "").strip()}
                    )
                    history = _history_block(conn, sid)
                    answer, active_profile = _build_autonomous_answer(
                        question=question,
                        rows=rows,
                        persona_name=p_name,
                        persona_tone=p_tone,
                        behavior_variant=variant,
                        qualia_state=qualia,
                        reasoning_profile=profile,
                        history=history,
                    )

                if not identity_or_capability_turn and not is_identity_query(question):
                    answer = neutralize_identity_signaling(answer)
                answer = sanitize_user_facing_text(answer, settings=settings)

                _store_message(conn, sid, "assistant", answer, citations=citations, mode="autonomous", channel="playground")
                refresh_session_summary(conn, sid, ollama=summary_ollama, settings=settings)
                conn.commit()
            break
        except sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower():
                raise
            sid = sid or session_id or f"playground-transient-{uuid4().hex}"
            rows = []
            citations = []
            if attempt == attempts - 1:
                if identity_or_capability_turn:
                    answer = _build_identity_capability_answer(settings=settings, persona_name=p_name)
                    active_profile = "normal"
                else:
                    answer, active_profile = _build_autonomous_answer(
                        question=question,
                        rows=[],
                        persona_name=p_name,
                        persona_tone=p_tone,
                        behavior_variant=variant,
                        qualia_state=qualia,
                        reasoning_profile=profile,
                        history="",
                    )
                answer = sanitize_user_facing_text(answer, settings=settings)
                append_discussion_log(
                    session_id=sid,
                    role="user",
                    content=question,
                    mode="autonomous",
                    channel="playground",
                    citations=[],
                )
                append_discussion_log(
                    session_id=sid,
                    role="assistant",
                    content=answer,
                    mode="autonomous",
                    channel="playground",
                    citations=[],
                )
                break
            delay_seconds = (float(backoff_ms) / 1000.0) * float(attempt + 1)
            time.sleep(delay_seconds)

    escalation_result: dict[str, Any] | None = None
    if should_autonomously_escalate(question=question, mode="autonomous", session_id=sid, settings=settings):
        escalation_context_lines: list[str] = []
        if answer:
            escalation_context_lines.append("Provisional local answer:\n" + _normalize_space(answer)[:2600])
        if rows:
            escalation_context_lines.append("Top retrieved evidence:")
            for row in rows[:3]:
                source_id = str(row.get("source_id") or "").strip() or "SRC-UNKNOWN"
                excerpt = _normalize_space(str(row.get("content") or ""))[:260]
                if excerpt:
                    escalation_context_lines.append(f"- [{source_id}] {excerpt}")
        try:
            escalation_result = submit_escalation(
                {
                    "query": question,
                    "mode": "autonomous",
                    "session_id": sid,
                    "requested_by": DEVELOPER_NAME,
                    "source": "sentinari_autonomous_playground",
                    "context": "\n".join(escalation_context_lines).strip(),
                    "citations": citations,
                    "metadata": {
                        "channel": "playground",
                        "reasoning_profile": active_profile,
                        "retrieved_count": len(rows),
                    },
                    "title": _normalize_space(question)[:120],
                }
            )
            append_discussion_log(
                session_id=sid or f"playground-transient-{uuid4().hex}",
                role="assistant",
                content=f"[Escalation ticket filed: {escalation_result.get('ticket_id', '')}]",
                mode="autonomous",
                channel="playground",
                citations=citations,
            )
        except Exception as ex:
            escalation_result = {"ok": False, "error": str(ex)}

    answer = sanitize_user_facing_text(answer, settings=settings)

    return {
        "ok": True,
        "engine": "runtime",
        "ollama_required": False,
        "session_id": sid,
        "reasoning_profile": active_profile,
        "answer": answer,
        "citations": citations,
        "retrieved_chunks": _serialize_retrieved_chunks(rows, max_items=limit),
        "escalation_queue": escalation_result,
        "qualia": {
            "enabled": bool(qualia.get("enabled")),
            "controls_enabled": bool(qualia.get("controls_enabled", True)),
            "source_count": int(qualia.get("source_count") or 0),
            "source_files": qualia.get("source_files") or [],
            "alpha": float(qualia.get("alpha") or 0.0),
            "beta": float(qualia.get("beta") or 0.0),
            "gamma_requested": float(qualia.get("gamma_requested") or 0.0),
            "gamma_effective": float(qualia.get("gamma") or 0.0),
            "gamma_cap": float(qualia.get("gamma_cap") or QUALIA_GAMMA_CAP),
            "base_variant_ratio": base_variant_ratio,
            "effective_variant_ratio": effective_variant_ratio,
            "parameters": qualia.get("parameters") or {},
            "vectors": qualia.get("vectors") or {},
            "summary": qualia.get("summary") or {},
            "influence": float(qualia.get("influence") or 0.0),
            "stability_index": float(qualia.get("stability_index") or 0.0),
            "stability_gate": float(qualia.get("stability_gate") or 1.0),
            "bell_curve": qualia.get("bell_curve") or {},
            "trajectory": qualia.get("trajectory") or [],
        },
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
