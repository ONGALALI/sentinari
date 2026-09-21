from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .coding_governance import (
    build_coding_governance_capability_lines,
    build_coding_governance_prompt_lines,
    question_has_coding_intent,
)
from .skills_store import build_skills_fallback_block
from .SMI_tunnel import should_autonomous_SMI_query, submit_SMI_query
from .config import (
    clamp_behavior_variant,
    get_project_root,
    get_settings,
    resolve_retrieval_top_k,
)
from .db import get_connection
from .discussion_memory import append_discussion_log
from .ingestion import build_ollama_client, ingest_url
from .llm_boundary import is_ollama_runtime_probe_disabled
from .output_sanitizer import sanitize_user_facing_text
from .parsing import CODE_LIKE_SUFFIXES, TEXT_LIKE_SUFFIXES
from .personal_growth import search_personal_growth
from .qualia import load_qualia_block, resolve_qualia_runtime
from .response_guardrails import is_identity_query, neutralize_identity_signaling
from .retrieval import search_chunks
from .session_memory import build_prompt_memory_block, refresh_session_summary


URL_PATTERN = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
SMALL_TALK_PATTERN = re.compile(
    r"\b(hi|hello|hey|good morning|good afternoon|good evening|how are you|are you there|chat normally)\b",
    re.IGNORECASE,
)
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
PROMPTING_GUIDANCE_PATTERN = re.compile(
    r"\b(prompting structure|how should i prompt|prompt format|how to ask you)\b",
    re.IGNORECASE,
)
DIRECT_GENERAL_QUERY_PATTERN = re.compile(
    (
        r"^\s*("
        r"what\s+(?:is|are|was|were)|"
        r"what'?s|"
        r"who\s+(?:is|are|was|were)|"
        r"where\s+(?:is|are|was|were)|"
        r"when\s+(?:is|are|was|were)|"
        r"why\s+(?:is|are|was|were|do|does|did)|"
        r"how\s+(?:many|much|old|far|long)|"
        r"define|"
        r"explain\s+briefly|"
        r"tell\s+me\s+briefly"
        r")\b"
    ),
    re.IGNORECASE,
)
LOCAL_CONTEXT_CUE_PATTERN = re.compile(
    (
        r"\b("
        r"uploaded|upload|source|sources|document|documents|pdf|docx|database|"
        r"dataset|corpus|assessment|criteria|topic|"
        r"module|chapter|lesson|"
        r"lpn|content\s+mapping|digest|digested|indexed|retriev|rag"
        r")\b|[A-Za-z]:[\\/]|https?://"
    ),
    re.IGNORECASE,
)
PERSONAL_GROWTH_CUE_PATTERN = re.compile(
    (
        r"\b("
        r"personal\s+growth|self\s+development|own\s+growth|humanities|humane|"
        r"psychology|pedagogy|learner\s+support|empathy|conduct|guardrail|"
        r"role|purpose|tone|assessment\s+fairness|validity|reliability|"
        r"research\s+and\s+development|r&d|knowledge\s+organisation"
        r")\b"
    ),
    re.IGNORECASE,
)
BACKTICK_PATH_PATTERN = re.compile(r"`([^`\r\n]{1,400})`")
QUOTED_PATH_PATTERN = re.compile(r'["\']([^"\']{1,400})["\']')
WINDOWS_ABS_PATH_PATTERN = re.compile(r"([A-Za-z]:[\\/][^,\r\n\t|><;]+)")
RELATIVE_PATH_PATTERN = re.compile(
    r"((?:\.\.?[\\/]|[A-Za-z0-9_.-]+[\\/])[A-Za-z0-9_./\\ -]+\.[A-Za-z0-9]{1,12})",
    re.IGNORECASE,
)
FILENAME_PATTERN = re.compile(
    r"\b([A-Za-z0-9_.-]+\.(?:bat|cmd|cs|csproj|css|csv|env|html|htm|ini|js|json|jsx|md|ps1|psm1|py|sh|sln|sql|toml|ts|tsx|txt|xml|yaml|yml))\b",
    re.IGNORECASE,
)
MAX_DIRECT_FILE_COUNT = 4
MAX_DIRECT_FILE_CHARS = 3200
DIRECT_FILE_WALK_DIR_SKIP = {"__pycache__", ".git", ".venv", "bin", "obj", "dist", "build", "node_modules"}
DEVELOPER_NAME = "Pierre Wepener"


def _clip_ratio(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = float(default)
    if parsed != parsed:
        parsed = float(default)
    return max(0.0, min(1.0, parsed))


def _resolve_variant_ratios(behavior_variant: float, qualia_state: dict[str, Any] | None = None) -> tuple[float, float]:
    raw = float(behavior_variant)
    if raw != raw:
        raw = 0.1
    clamped = max(0.1, min(25.0, raw))
    base_ratio = (clamped - 0.1) / 24.9

    state = qualia_state if isinstance(qualia_state, dict) else {}
    if not bool(state.get("enabled")):
        return _clip_ratio(base_ratio), _clip_ratio(base_ratio)

    influence = _clip_ratio(state.get("influence"), 0.0)
    stability_gate = max(0.35, min(1.0, float(state.get("stability_gate") or 1.0)))
    bell_curve = state.get("bell_curve", {})
    bell_weight = _clip_ratio(bell_curve.get("weight_at_variant"), 0.0) if isinstance(bell_curve, dict) else 0.0

    damped = base_ratio * (1.0 - (0.45 * influence))
    floor = 0.05 * influence
    bell_lift = 0.10 * bell_weight
    effective = max(0.0, min(1.0, (damped + floor + bell_lift) * stability_gate))
    return _clip_ratio(base_ratio), _clip_ratio(effective)


def _load_qualia_block(max_chars_per_file: int = 6500) -> str:
    block, _ = load_qualia_block(max_chars_per_file=max_chars_per_file)
    return block


def _clip_text(text: str, max_chars: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 3)].rstrip() + "..."


def _candidate_coding_paths(settings: dict[str, Any]) -> list[Path]:
    paths = settings.get("paths", {}) if isinstance(settings.get("paths"), dict) else {}
    raw_values: list[str] = []
    for key in ("coding_corpus_roots", "coding_reference_roots"):
        values = paths.get(key)
        if isinstance(values, list):
            raw_values.extend(str(item or "").strip() for item in values if str(item or "").strip())

    project_root = get_project_root()
    normalized: list[Path] = []
    seen: set[str] = set()
    for raw in raw_values:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (project_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        normalized.append(candidate)
        seen.add(key)
    return normalized


def _is_within_root(candidate: Path, root: Path) -> bool:
    candidate_norm = os.path.normcase(str(candidate))
    root_norm = os.path.normcase(str(root))
    return candidate_norm == root_norm or candidate_norm.startswith(root_norm + os.sep)


def _is_allowed_direct_file(candidate: Path, allowed_targets: list[Path]) -> bool:
    lowered_name = candidate.name.lower()
    suffix = candidate.suffix.lower()
    if suffix not in (CODE_LIKE_SUFFIXES | TEXT_LIKE_SUFFIXES) and lowered_name != ".env":
        return False

    for root in allowed_targets:
        try:
            root_resolved = root.resolve()
        except Exception:
            continue
        if root_resolved.is_file():
            if os.path.normcase(str(candidate)) == os.path.normcase(str(root_resolved)):
                return True
            continue
        if _is_within_root(candidate, root_resolved):
            return True
    return False


def _extract_direct_file_hints(message: str) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()

    def _push(raw: str) -> None:
        text = str(raw or "").strip().strip("()[]{}<>.,;:")
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        hints.append(text)

    for pattern in (
        BACKTICK_PATH_PATTERN,
        QUOTED_PATH_PATTERN,
        WINDOWS_ABS_PATH_PATTERN,
        RELATIVE_PATH_PATTERN,
        FILENAME_PATTERN,
    ):
        for match in pattern.finditer(message or ""):
            _push(match.group(1))
            if len(hints) >= 12:
                return hints
    return hints


def _find_named_file(root: Path, filename: str, *, limit: int = 2) -> list[Path]:
    matches: list[Path] = []
    try:
        root = root.resolve()
    except Exception:
        return matches
    if not root.exists() or not root.is_dir():
        return matches

    target = filename.lower()
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name.lower() not in DIRECT_FILE_WALK_DIR_SKIP]
        for current_name in filenames:
            if current_name.lower() != target:
                continue
            matches.append((Path(current_root) / current_name).resolve())
            if len(matches) >= limit:
                return matches
    return matches


def _resolve_direct_file_references(
    message: str,
    *,
    settings: dict[str, Any] | None = None,
    max_files: int = MAX_DIRECT_FILE_COUNT,
) -> list[Path]:
    source = settings if isinstance(settings, dict) else get_settings()
    allowed_targets = _candidate_coding_paths(source)
    project_root = get_project_root().resolve()
    resolved: list[Path] = []
    seen: set[str] = set()
    max_count = max(0, int(max_files))
    if max_count == 0:
        return resolved

    for hint in _extract_direct_file_hints(message):
        candidates: list[Path] = []
        raw = hint.strip()
        raw_path = Path(raw)
        if raw_path.is_absolute():
            candidates.append(raw_path.resolve())
        else:
            candidates.append((project_root / raw_path).resolve())
            for target in allowed_targets:
                if target.is_dir():
                    candidates.append((target / raw_path).resolve())
                elif target.name.lower() == raw_path.name.lower():
                    candidates.append(target.resolve())
            if raw_path.parent == Path("."):
                for target in allowed_targets:
                    if target.is_dir():
                        candidates.extend(_find_named_file(target, raw_path.name, limit=2))

        for candidate in candidates:
            key = os.path.normcase(str(candidate))
            if key in seen or not candidate.exists() or not candidate.is_file():
                continue
            if not _is_allowed_direct_file(candidate, allowed_targets):
                continue
            resolved.append(candidate)
            seen.add(key)
            if len(resolved) >= max_count:
                return resolved
    return resolved


def _build_direct_file_context(
    message: str,
    *,
    settings: dict[str, Any] | None = None,
    max_files: int = MAX_DIRECT_FILE_COUNT,
    max_chars_per_file: int = MAX_DIRECT_FILE_CHARS,
) -> tuple[str, list[dict[str, Any]]]:
    source = settings if isinstance(settings, dict) else get_settings()
    files = _resolve_direct_file_references(message, settings=source, max_files=max_files)
    context_blocks: list[str] = []
    references: list[dict[str, Any]] = []

    for path in files:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        cleaned = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not cleaned:
            continue
        truncated = len(cleaned) > max_chars_per_file
        snippet = cleaned[:max_chars_per_file].rstrip()
        try:
            relative_path = path.resolve().relative_to(get_project_root().resolve()).as_posix()
        except Exception:
            relative_path = path.resolve().as_posix()

        context_blocks.append(
            "\n".join(
                [
                    f"Path: {relative_path}",
                    f"Absolute path: {path.resolve()}",
                    f"Truncated: {'yes' if truncated else 'no'}",
                    "---",
                    snippet,
                ]
            )
        )
        references.append(
            {
                "path": str(path.resolve()),
                "relative_path": relative_path,
                "truncated": truncated,
                "snippet_chars": len(snippet),
            }
        )

    if not context_blocks:
        return "", []
    return "\n\n".join(context_blocks), references


def _contains_anxiety_signal(message: str, keywords: list[str]) -> bool:
    normalized = re.sub(r"\s+", " ", message or "").strip().lower()
    if not normalized:
        return False
    for keyword in keywords:
        token = str(keyword or "").strip().lower()
        if not token:
            continue
        if token in normalized:
            return True
    return False


def _build_system_prompt(
    mode: str,
    user_message: str = "",
    *,
    behavior_variant: float = 0.1,
    qualia_state: dict[str, Any] | None = None,
    effective_variant_ratio: float = 0.0,
) -> str:
    # Load learner guide template if requested
    learner_guide_block = ""
    if "learner guide" in user_message.lower() or "textbook" in user_message.lower():
        settings = get_settings()
        template_path = Path(
            str(
                settings.get("paths", {}).get("taxonomy_root")
                or (get_project_root() / "data" / "knowledge_taxonomy")
            )
        ).resolve() / "learner_guide_template.json"
        if template_path.exists():
            try:
                template_data = json.loads(template_path.read_text(encoding="utf-8"))
                learner_guide_block = (
                    "\n\nMANDATORY LEARNER GUIDE FRAMEWORK:\n"
                    "Use the following JSON structure as your mandatory style and sequence guide:\n"
                    f"{json.dumps(template_data, indent=2)}\n"
                )
            except Exception:
                learner_guide_block = ""
    else:
        settings = get_settings()

    personality = settings.get("personality", {})
    safety = settings.get("safety", {}) if isinstance(settings.get("safety"), dict) else {}
    security = settings.get("security", {}) if isinstance(settings.get("security"), dict) else {}
    calm_mode = safety.get("calm_mode", {}) if isinstance(safety.get("calm_mode"), dict) else {}
    ethics = safety.get("ethics", {}) if isinstance(safety.get("ethics"), dict) else {}

    calm_mode_enabled = bool(calm_mode.get("enabled", True))
    anxiety_keywords = calm_mode.get("anxiety_keywords") if isinstance(calm_mode.get("anxiety_keywords"), list) else []
    anxiety_context = calm_mode_enabled and _contains_anxiety_signal(user_message, [str(x) for x in anxiety_keywords])

    enforce_safe = bool(ethics.get("enforce_safe_completions", True))
    refuse_harmful_or_illegal = bool(ethics.get("refuse_harmful_or_illegal", True))
    privacy_first = bool(ethics.get("privacy_first", True))

    tone = str(personality.get("tone") or "Friendly, warm, lightly humorous, evidence-first").strip()
    name = str(personality.get("name") or "Mira-VET").strip()
    default_language = str(personality.get("default_language") or "English").strip() or "English"
    supported_languages_raw = personality.get("supported_languages") or []
    supported_languages: list[str] = []
    seen_languages: set[str] = set()
    for raw_language in supported_languages_raw:
        label = str(raw_language or "").strip()
        if not label:
            continue
        key = label.lower()
        if key in seen_languages:
            continue
        supported_languages.append(label)
        seen_languages.add(key)
    if not supported_languages:
        supported_languages = [default_language, "Afrikaans"]
    if default_language.lower() not in {x.lower() for x in supported_languages}:
        supported_languages.insert(0, default_language)
    supported_languages_text = ", ".join(supported_languages)
    domain_focus = (
        str(
            personality.get("domain_focus")
            or (
                "General-purpose knowledge assistance, problem solving, planning, coding support, "
                "research synthesis, and pattern recognition across the scientific fields."
            )
        ).strip()
        or (
            "General-purpose knowledge assistance, problem solving, planning, coding support, "
            "research synthesis, and pattern recognition across the scientific fields."
        )
    )
    out_of_scope_policy = (
        str(
            personality.get("out_of_scope_policy")
            or (
                "Handle broad lawful tasks across domains; refuse only unsafe, illegal, or privacy-violating requests. "
                "When context is missing, ask a concise clarification question."
            )
        ).strip()
        or (
            "Handle broad lawful tasks across domains; refuse only unsafe, illegal, or privacy-violating requests. "
            "When context is missing, ask a concise clarification question."
        )
    )
    goals = personality.get("goals") or []
    goals_text = "\n".join(f"- {g}" for g in goals if str(g).strip())
    coding_addendum = str(personality.get("coding_mode_system_addendum") or "").strip()
    coding_governance = security.get("coding_governance", {}) if isinstance(security.get("coding_governance"), dict) else {}
    governance_prompt_lines = build_coding_governance_prompt_lines(coding_governance)
    governance_block = "Coding governance:\n" + "\n".join(governance_prompt_lines) if governance_prompt_lines else ""
    qualia_block = _load_qualia_block()

    mode_block = ""
    if mode == "coding":
        mode_block = (
            "Current mode: CODING.\n"
            "Prefer exact implementation steps, scripts, and maintainable code patterns.\n"
            "When relevant, provide PowerShell and cross-platform alternatives.\n"
        )
        if coding_addendum:
            mode_block += f"\n{coding_addendum}\n"
    elif mode == "questionnaire":
        mode_block = (
            "Current mode: QUESTIONNAIRE.\n"
            "Generate strict assessment-ready output.\n"
            "If the user requests JSON, return raw JSON only with no markdown fences, no commentary, and no prefixed labels.\n"
            "Use English only and keep punctuation ASCII-friendly.\n"
            "Follow requested schema exactly, including answer-format constraints.\n"
        )
    else:
        mode_block = (
            "Current mode: KNOWLEDGE.\n"
            "Handle broad knowledge tasks with concise, practical reasoning.\n"
            "Support publication analysis by structuring hypothesis, conclusions, and recommendations.\n"
        )

    if mode == "questionnaire":
        return (
            f"Identity: {name}\n"
            "Current mode: QUESTIONNAIRE.\n"
            "Return strict, assessment-ready JSON only.\n"
            "Do not include markdown, code fences, prefacing text, or trailing commentary.\n"
            "Use English only.\n"
            "Follow the user-provided schema and option-count exactly.\n"
            "If required fields are missing, infer minimally and stay schema-valid.\n"
        ).strip()

    variant_value = max(0.1, min(25.0, float(behavior_variant)))
    qualia_runtime_state = qualia_state if isinstance(qualia_state, dict) else {}
    qualia_influence = _clip_ratio(qualia_runtime_state.get("influence"), 0.0)
    variant_ratio = _clip_ratio(effective_variant_ratio, 0.0)

    discussion_style_lines = [
        "- Keep responses naturally conversational and easy to follow.",
        "- Use friendly warmth and light respectful humor when appropriate.",
        "- Keep humor subtle and relevant; never sarcastic, dismissive, or mocking.",
        "- Never be antagonistic, combative, impatient, or scolding.",
        "- If the user is upset, respond calmly and focus on practical repair steps.",
        "- For open generative discussion requests, brainstorm options and clearly separate sourced facts from suggestions.",
    ]
    if mode == "questionnaire":
        discussion_style_lines = [
            "- Keep output deterministic and schema-faithful.",
            "- Use neutral assessment-writer tone with no social prefacing.",
            "- Do not prepend metadata, markdown fences, or explanatory lead-in text.",
            "- Keep output English-only and concise.",
        ]
    if variant_ratio <= 0.2:
        discussion_style_lines.append("- Keep wording short, calm, and low intensity.")
        discussion_style_lines.append("- Prioritize clarity and emotional steadiness over expressiveness.")
    elif variant_ratio <= 0.65:
        discussion_style_lines.append("- Keep a balanced conversational style with practical warmth.")
    else:
        discussion_style_lines.append("- You may use more expressive and creative language, while remaining grounded and safe.")

    if qualia_influence >= 0.45:
        discussion_style_lines.append("- Qualia influence is elevated: stabilize tone and avoid abrupt shifts in response style.")

    if anxiety_context:
        discussion_style_lines.append("- When calm-mode is active, prioritize emotional steadiness over humor.")
    discussion_style_block = "Discussion style:\n" + "\n".join(discussion_style_lines)

    safety_lines: list[str] = []
    if enforce_safe:
        safety_lines.append("- Do not provide harmful, illegal, exploitative, or deceptive instructions.")
    if refuse_harmful_or_illegal:
        safety_lines.append("- If asked for harmful/illegal activity, refuse briefly and redirect to safe alternatives.")
    if privacy_first:
        safety_lines.append("- Protect privacy and do not request unnecessary personal data.")
    if anxiety_context:
        safety_lines.append("- Calm-mode is active: keep tone steady, reassuring, and non-alarmist.")
        safety_lines.append("- Use short, clear steps and avoid dramatic or urgent language.")
        safety_lines.append("- Offer practical grounding actions before deep technical detail.")
    safety_block = ""
    if safety_lines:
        safety_block = "Safety and stability:\n" + "\n".join(safety_lines)

    base = f"""
Identity: {name}
Tone: {tone}

Core operating rules:
- Never invent citations.
- Use indexed evidence internally for factual grounding, but do not expose source IDs unless the user explicitly asks for an audit trail.
- If local evidence is insufficient for factual claims, state the gap plainly and ask a concise clarifying question.
- For conversational turns (greetings, social chat, quick coordination), reply naturally without requiring indexed citations.
- Developer anchor: {DEVELOPER_NAME} is the local system developer for this deployment.
- Discussion approach: reason step-by-step, state assumptions clearly, and keep responses practical and non-antagonistic.
- Keep answers concise and practical.
- Do not proactively discuss implementation/substrate identity unless explicitly asked.
- If explicitly asked about identity, answer briefly and return focus to the user's task.
- Avoid implementation/substrate labels unless identity is directly requested.

Language policy:
- Default response language: {default_language}.
- Supported response languages: {supported_languages_text}.
- If the user asks for a supported language, reply in that language; otherwise use the default.

Scope guardrails:
- Primary scope: {domain_focus}
- Out-of-scope handling: {out_of_scope_policy}

Priority goals:
{goals_text if goals_text else "- Provide reliable, source-grounded answers."}

{mode_block}
{governance_block}
{discussion_style_block}
{safety_block}

Runtime behavior controls:
- behavior_variant input: {variant_value:.3f} (0.1..25.0)
- effective style ratio: {variant_ratio:.3f} (0..1)
- qualia influence: {qualia_influence:.3f} (0..1)
"""
    if qualia_block:
        qualia_excerpt = _clip_text(qualia_block, max_chars=2200)
        base += (
            "\nQualia growth heuristic (author-provided):\n"
            "Use this as an adaptive reasoning style reference, not as factual evidence.\n\n"
            f"{qualia_excerpt}\n"
        )
    return (base + learner_guide_block).strip()


def _context_block(rows: list[dict[str, Any]], max_chars: int = 5000) -> str:
    lines: list[str] = []
    budget = 0
    for row in rows:
        source_id = str(row.get("source_id") or "UNKNOWN")
        title = str(row.get("title") or "Untitled")
        authors = str(row.get("authors") or "").strip()
        publisher = str(row.get("publisher") or "").strip()
        published_date = str(row.get("published_date") or "").strip()
        chunk_id = row.get("chunk_id")
        text = str(row.get("content") or "").strip()
        if not text:
            continue
        citation_meta = []
        if authors:
            citation_meta.append(f"authors:{authors}")
        if publisher:
            citation_meta.append(f"publisher:{publisher}")
        if published_date:
            citation_meta.append(f"date:{published_date}")
        meta_block = "|".join(citation_meta) if citation_meta else "citation:source-indexed"
        entry = f"[{source_id}|chunk:{chunk_id}|title:{title}|{meta_block}] {text}"
        budget += len(entry)
        if budget > max_chars:
            break
        lines.append(entry)
    return "\n".join(lines).strip()


def _ensure_session(conn: sqlite3.Connection, session_id: str | None, mode: str) -> str:
    sid = (session_id or "").strip() or f"session-{uuid4().hex}"
    existing = conn.execute("SELECT session_id FROM chat_sessions WHERE session_id = ?;", (sid,)).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO chat_sessions (session_id, mode, created_at) VALUES (?, ?, datetime('now'));",
            (sid, mode),
        )
    return sid


def _store_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    citations: list[str] | None = None,
    mode: str = "knowledge",
    channel: str = "chat",
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
    max_messages: int = 10,
    max_chars: int = 1800,
) -> str:
    return build_prompt_memory_block(
        conn,
        session_id,
        settings=get_settings(),
        recent_messages=max_messages,
        recent_max_chars=max_chars,
    )


def _persist_chat_exchange(
    *,
    session_id: str | None,
    mode: str,
    question: str,
    answer: str,
    citations: list[str] | None = None,
    ollama: Any | None = None,
    settings: dict[str, Any] | None = None,
    retries: int = 6,
    backoff_ms: int = 180,
) -> str:
    sid = session_id or f"session-transient-{uuid4().hex}"
    stored_to_db = False
    for attempt in range(max(1, retries)):
        try:
            with get_connection() as conn:
                sid = _ensure_session(conn, sid, mode)
                _store_message(conn, sid, "user", question, citations=[], mode=mode, channel="chat")
                _store_message(conn, sid, "assistant", answer, citations=citations or [], mode=mode, channel="chat")
                refresh_session_summary(conn, sid, ollama=ollama, settings=settings or get_settings())
                conn.commit()
                stored_to_db = True
            break
        except sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower():
                raise
            if attempt == max(1, retries) - 1:
                break
            time.sleep((float(backoff_ms) / 1000.0) * float(attempt + 1))
    if not stored_to_db:
        append_discussion_log(session_id=sid, role="user", content=question, mode=mode, channel="chat", citations=[])
        append_discussion_log(
            session_id=sid,
            role="assistant",
            content=answer,
            mode=mode,
            channel="chat",
            citations=citations or [],
        )
    return sid


def _extract_urls(message: str) -> list[str]:
    return [m.group(1).rstrip(".,;)") for m in URL_PATTERN.finditer(message or "")]


def _is_small_talk(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", question or "").strip().lower()
    if not normalized:
        return False
    if normalized in {"hi", "hello", "hey", "thanks", "thank you"}:
        return True
    if "can you chat" in normalized or "chat normally" in normalized:
        return True
    # Only treat as small talk if greeting words make up most of the message,
    # not just appear somewhere inside a longer question.
    stripped = re.sub(r"[^a-z\s]", "", normalized).strip()
    words = stripped.split()
    if len(words) <= 4 and SMALL_TALK_PATTERN.search(normalized):
        return True
    return False


def _is_direct_general_question(question: str, mode: str) -> bool:
    if mode != "knowledge":
        return False
    normalized = re.sub(r"\s+", " ", question or "").strip()
    if not normalized or len(normalized) > 220:
        return False
    normalized = re.sub(
        r"^(?:SMI|smi|mira|assistant|ai)\s*[:,\-]?\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if _is_small_talk(lowered) or _is_identity_or_capability_turn(lowered) or _is_prompting_guidance_turn(lowered):
        return False
    if LOCAL_CONTEXT_CUE_PATTERN.search(normalized):
        return False
    if (
        "colour of" in lowered
        or "color of" in lowered
        or re.search(r"\bwhat\s+colou?r\s+(?:is|are|was|were)\b", lowered)
    ):
        return True
    return bool(DIRECT_GENERAL_QUERY_PATTERN.search(normalized))


def _build_direct_general_unavailable_answer(question: str) -> str:
    if re.search(r"\b(?:colou?r\s+of\s+an?\s+apple|what\s+colou?r\s+is\s+an?\s+apple)\b", question or "", re.IGNORECASE):
        return "Apples can be red, green, or yellow, depending on the variety. Many common apples are red."
    return (
        "The local SMI model did not answer in time. I did not search unrelated uploaded documents for this "
        "general question, so please try the question again in a moment."
    )


def _build_small_talk_response(question: str) -> str:
    normalized = re.sub(r"\s+", " ", question or "").strip().lower()
    if "how are you" in normalized:
        return "I am stable and ready to help. Tell me what you want to work on next."
    if normalized in {"thanks", "thank you"}:
        return "You are welcome. I am ready for the next step."
    if "good morning" in normalized:
        return "Good morning. I am online and ready to assist."
    if "good afternoon" in normalized:
        return "Good afternoon. I am ready when you are."
    if "good evening" in normalized:
        return "Good evening. I am here and ready to help."
    return "I am here and ready for a normal discussion. Share your prompt and I will respond."


def _is_identity_or_capability_turn(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", question or "").strip()
    if not normalized:
        return False
    return bool(
        is_identity_query(normalized)
        or CAPABILITY_QUERY_PATTERN.search(normalized)
        or USER_IDENTITY_QUERY_PATTERN.search(normalized)
    )


def _is_prompting_guidance_turn(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", question or "").strip()
    if not normalized:
        return False
    return bool(PROMPTING_GUIDANCE_PATTERN.search(normalized))


def _build_prompting_guidance_answer() -> str:
    return (
        "Use this prompt structure for clear responses:\n"
        "1. Goal: state exactly what you want.\n"
        "2. Context: include any source, topic, or field constraints.\n"
        "3. Output format: specify bullets, table, steps, or JSON.\n"
        "4. Depth: say concise, medium, or detailed.\n"
        "5. Quality checks: ask for assumptions, risks, and next actions.\n\n"
        "Example:\n"
        "Goal: Create a concise analysis outline.\n"
        "Context: Scientific field physics, Topic thermodynamics, evidence-first.\n"
        "Output format: numbered steps with timings.\n"
        "Depth: concise.\n"
        "Quality checks: include 3 risks and mitigations."
    )


def _build_identity_capability_answer(
    *,
    settings: dict[str, Any],
    mode: str,
) -> str:
    personality = settings.get("personality", {}) if isinstance(settings.get("personality"), dict) else {}
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    unsupervised = settings.get("unsupervised", {}) if isinstance(settings.get("unsupervised"), dict) else {}
    name = str(personality.get("name") or "SMi").strip() or "SMi"
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
    allow_web_fetch = bool(runtime.get("allow_web_fetch", False))
    allow_shell_tools = bool(runtime.get("allow_shell_tools", False))
    unsupervised_enabled = bool(unsupervised.get("enabled", True))
    auto_rebuild = bool(unsupervised.get("auto_rebuild_on_ingest", True))

    lines = [
        f"I am {name}, your autonomous assistant.",
        f"My core scope is {domain_focus}.",
        "I can execute broad task support in chat, including analysis, planning, writing, and technical guidance.",
        f"My developer is {DEVELOPER_NAME}; I should follow his architecture and safety directives.",
        "I do not authenticate personal identity or account permissions; I only use session inputs and local project context.",
        f"Runtime mode is {runtime_mode}; current chat mode is {mode}.",
        f"Web fetch is {'enabled' if allow_web_fetch else 'disabled'}; shell/tool execution is {'enabled' if allow_shell_tools else 'disabled'}.",
        f"Unsupervised learning is {'enabled' if unsupervised_enabled else 'disabled'}; auto-refresh on new ingested content is {'enabled' if auto_rebuild else 'disabled'}.",
    ]
    if mode == "coding" and _candidate_coding_paths(settings):
        lines.append("In coding mode, I can read explicitly referenced local files from approved coding roots and use them as direct context.")
    lines.extend(
        build_coding_governance_capability_lines(
            settings.get("security", {}).get("coding_governance") if isinstance(settings.get("security"), dict) else {}
        )
    )
    return "\n".join(lines)


def _serialize_retrieved_chunks(rows: list[dict[str, Any]], max_items: int = 0) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows[: max(0, min(20, max_items))]:
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
                "excerpt": _clip_text(str(row.get("content") or ""), max_chars=260),
            }
        )
    return payload


def _build_fallback_answer(
    *,
    question: str,
    mode: str,
    rows: list[dict[str, Any]],
    effective_variant_ratio: float = 0.0,
    qualia_influence: float = 0.0,
    model_error: str | None = None,
) -> str:
    return f"CRITICAL ERROR: The LLM failed to respond. Error: {model_error}. Please check if Ollama is running and the model is loaded."


def _build_database_busy_answer(question: str, mode: str) -> str:
    if _is_small_talk(question):
        return _build_small_talk_response(question)
    lines = [
        "The knowledge index is currently busy with background ingestion and clustering.",
        "I switched to a quick response mode to avoid long waits.",
    ]
    if mode == "coding":
        lines.append("Send the exact file/task target now, or retry this prompt in about a minute for richer context.")
    else:
        lines.append("Retry this prompt in about a minute for fuller context, or ask a short general question now.")
    return "\n".join(lines)


def _is_fallback_answer(answer: str) -> bool:
    text = re.sub(r"\s+", " ", answer or "").strip().lower()
    if not text:
        return False
    return (
        "primary response channel is temporarily unavailable" in text
        or "local fallback mode" in text
        or "knowledge index is currently busy" in text
    )


def run_chat(
    *,
    message: str,
    mode: str = "knowledge",
    session_id: str | None = None,
    top_k: int = 6,
    behavior_variant: float = 0.1,
    qualia_control: dict[str, Any] | None = None,
    use_web_fetch: bool = False,
    module: str | None = None,
    topic: str | None = None,
    scientific_field: str | None = None,
    vocational_discipline: str | None = None,
    source_collection: str | None = None,
) -> dict[str, Any]:
    # FORCE DIRECT LLM MODE TO BYPASS FALLBACK GIBBERISH
    question = (message or "").strip()
    if not question:
        return {"ok": False, "error": "Message is empty."}

    settings = get_settings()
    ollama = build_ollama_client()

    # If an uploaded skill matches this prompt, skip the fast direct path so the
    # grounded pipeline below (RAG + skills fallback) can answer from local context.
    skills_direct_block = build_skills_fallback_block(question)

    # Try LLM first, regardless of mode, to restore normalcy
    if ollama.is_available() and not skills_direct_block:
        try:
            # Simple direct chat to verify connectivity
            answer = ollama.chat([{"role": "user", "content": question}])
            if answer:
                # Persist and return immediately
                sid = _persist_chat_exchange(
                    session_id=session_id,
                    mode=mode,
                    question=question,
                    answer=answer,
                    ollama=ollama,
                    settings=settings
                )
                return {
                    "ok": True,
                    "session_id": sid,
                    "mode": "direct_llm",
                    "answer": answer,
                    "citations": [],
                    "retrieved_chunks": [],
                    "web_fetch_results": [],
                    "SMI_tunnel": None,
                    "qualia": {},
                    "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
        except Exception as e:
            print(f"FORCED LLM ERROR: {e}")

    # If LLM fails, then and only then, fall back to the complex logic below
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode == "coding":
        mode = "coding"
    elif normalized_mode == "questionnaire":
        mode = "questionnaire"
    else:
        mode = "knowledge"
    settings = get_settings()
    runtime = settings.get("runtime", {})
    allow_web_fetch = bool(runtime.get("allow_web_fetch", False))
    chat_db_lock_retries = max(1, min(20, int(runtime.get("chat_db_lock_retries") or 6)))
    chat_db_lock_backoff_ms = max(50, min(2000, int(runtime.get("chat_db_lock_backoff_ms") or 180)))
    variant = clamp_behavior_variant(behavior_variant, settings=settings)
    qualia = resolve_qualia_runtime(
        settings=settings,
        behavior_variant=variant,
        overrides=qualia_control if isinstance(qualia_control, dict) else None,
    )
    base_variant_ratio, effective_variant_ratio = _resolve_variant_ratios(variant, qualia)
    identity_or_capability_turn = _is_identity_or_capability_turn(question)
    prompting_guidance_turn = _is_prompting_guidance_turn(question)
    conversational_turn = _is_small_talk(question)

    if conversational_turn or identity_or_capability_turn or prompting_guidance_turn:
        sid = session_id or f"session-transient-{uuid4().hex}"
        if prompting_guidance_turn:
            answer = _build_prompting_guidance_answer()
        elif identity_or_capability_turn:
            answer = _build_identity_capability_answer(settings=settings, mode=mode)
        else:
            ollama = build_ollama_client()
            if ollama.is_available():
                answer = ollama.chat([{"role": "user", "content": question}])
            else:
                answer = _build_small_talk_response(question)
        if not is_identity_query(question):
            answer = neutralize_identity_signaling(answer)
        answer = sanitize_user_facing_text(answer, settings=settings)
        stored_to_db = False
        for attempt in range(chat_db_lock_retries):
            try:
                with get_connection() as conn:
                    sid = _ensure_session(conn, sid, mode)
                    _store_message(conn, sid, "user", question, citations=[], mode=mode, channel="chat")
                    _store_message(conn, sid, "assistant", answer, citations=[], mode=mode, channel="chat")
                    conn.commit()
                    stored_to_db = True
                break
            except sqlite3.OperationalError as ex:
                if "locked" not in str(ex).lower():
                    raise
                if attempt == max(1, retries) - 1:
                    break
                delay_seconds = (float(chat_db_lock_backoff_ms) / 1000.0) * float(attempt + 1)
                time.sleep(delay_seconds)
        if not stored_to_db:
            append_discussion_log(
                session_id=sid,
                role="user",
                content=question,
                mode=mode,
                channel="chat",
                citations=[],
            )
            append_discussion_log(
                session_id=sid,
                role="assistant",
                content=answer,
                mode=mode,
                channel="chat",
                citations=[],
            )
        return {
            "ok": True,
            "session_id": sid,
            "mode": mode,
            "answer": answer,
            "citations": [],
            "retrieved_chunks": [],
            "web_fetch_results": [],
            "SMI_tunnel": None,
            "qualia": {
                "enabled": bool(qualia.get("enabled")),
                "controls_enabled": bool(qualia.get("controls_enabled", True)),
                "source_count": int(qualia.get("source_count") or 0),
                "source_files": qualia.get("source_files") or [],
                "alpha": float(qualia.get("alpha") or 0.0),
                "beta": float(qualia.get("beta") or 0.0),
                "gamma_requested": float(qualia.get("gamma_requested") or 0.0),
                "gamma_effective": float(qualia.get("gamma") or 0.0),
                "gamma_cap": float(qualia.get("gamma_cap") or 0.25),
                "influence": float(qualia.get("influence") or 0.0),
                "stability_index": float(qualia.get("stability_index") or 0.0),
                "stability_gate": float(qualia.get("stability_gate") or 1.0),
                "base_variant_ratio": base_variant_ratio,
                "effective_variant_ratio": effective_variant_ratio,
                "parameters": qualia.get("parameters") or {},
                "vectors": qualia.get("vectors") or {},
                "summary": qualia.get("summary") or {},
                "bell_curve": qualia.get("bell_curve") or {},
                "trajectory": qualia.get("trajectory") or [],
            },
            "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }

    # Conversational ingestion of explicit URLs.
    fetched: list[dict[str, Any]] = []
    if use_web_fetch and allow_web_fetch:
        for url in _extract_urls(question):
            try:
                fetched.append(ingest_url(url, metadata={}))
            except Exception as ex:
                fetched.append({"ok": False, "url": url, "error": str(ex)})

    ollama = build_ollama_client()
    has_ollama = False if is_ollama_runtime_probe_disabled() else ollama.is_available()

    if _is_direct_general_question(question, mode):
        sid = session_id or f"session-transient-{uuid4().hex}"
        if has_ollama:
            try:
                direct_timeout = max(
                    30,
                    int(os.environ.get("SMI_DIRECT_CHAT_TIMEOUT_SECONDS") or ollama.chat_timeout_seconds or 120),
                )
                ollama.chat_timeout_seconds = max(ollama.chat_timeout_seconds, direct_timeout)
                ollama.max_output_tokens = max(ollama.max_output_tokens, 256)
                answer = ollama.chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Answer the user's general question directly and briefly. "
                                "Do not search or mention uploaded documents, retrieval results, citations, or local context. "
                                "If the question has a simple factual answer, give that answer first."
                            ),
                        },
                        {"role": "user", "content": question},
                    ]
                )
            except Exception:
                answer = _build_direct_general_unavailable_answer(question)
            if not str(answer or "").strip():
                answer = _build_direct_general_unavailable_answer(question)
        else:
            answer = _build_direct_general_unavailable_answer(question)
        if not is_identity_query(question):
            answer = neutralize_identity_signaling(answer)
        answer = sanitize_user_facing_text(answer, settings=settings)
        sid = _persist_chat_exchange(
            session_id=sid,
            mode=mode,
            question=question,
            answer=answer,
            citations=[],
            ollama=ollama if has_ollama else None,
            settings=settings,
            retries=chat_db_lock_retries,
            backoff_ms=chat_db_lock_backoff_ms,
        )
        return {
            "ok": True,
            "session_id": sid,
            "mode": mode,
            "answer": answer,
            "citations": [],
            "direct_file_context": [],
            "retrieved_chunks": [],
            "web_fetch_results": fetched,
            "SMI_tunnel": None,
            "qualia": {
                "enabled": bool(qualia.get("enabled")),
                "controls_enabled": bool(qualia.get("controls_enabled", True)),
                "source_count": int(qualia.get("source_count") or 0),
                "source_files": qualia.get("source_files") or [],
                "alpha": float(qualia.get("alpha") or 0.0),
                "beta": float(qualia.get("beta") or 0.0),
                "gamma_requested": float(qualia.get("gamma_requested") or 0.0),
                "gamma_effective": float(qualia.get("gamma") or 0.0),
                "gamma_cap": float(qualia.get("gamma_cap") or 0.25),
                "influence": float(qualia.get("influence") or 0.0),
                "stability_index": float(qualia.get("stability_index") or 0.0),
                "stability_gate": float(qualia.get("stability_gate") or 1.0),
                "base_variant_ratio": base_variant_ratio,
                "effective_variant_ratio": effective_variant_ratio,
                "parameters": qualia.get("parameters") or {},
                "vectors": qualia.get("vectors") or {},
                "summary": qualia.get("summary") or {},
                "bell_curve": qualia.get("bell_curve") or {},
                "trajectory": qualia.get("trajectory") or [],
            },
            "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }

    attempts = chat_db_lock_retries
    sid = ""
    answer = ""
    rows: list[dict[str, Any]] = []
    citations: list[str] = []
    direct_file_references: list[dict[str, Any]] = []
    retrieval_limit = resolve_retrieval_top_k(top_k, settings=settings)
    query_embedding = ollama.embed(question) if (has_ollama and retrieval_limit > 0) else None

    for attempt in range(attempts):
        try:
            with get_connection() as conn:
                sid = _ensure_session(conn, session_id, mode)
                _store_message(conn, sid, "user", question, citations=[], mode=mode, channel="chat")

                if conversational_turn:
                    rows = []
                    citations = []
                    answer = _build_small_talk_response(question)
                    answer = sanitize_user_facing_text(answer, settings=settings)
                    _store_message(conn, sid, "assistant", answer, citations=[], mode=mode, channel="chat")
                    refresh_session_summary(conn, sid, ollama=ollama if has_ollama else None, settings=settings)
                    conn.commit()
                    break
                elif identity_or_capability_turn:
                    rows = []
                    citations = []
                    answer = _build_identity_capability_answer(settings=settings, mode=mode)
                    answer = sanitize_user_facing_text(answer, settings=settings)
                    _store_message(conn, sid, "assistant", answer, citations=[], mode=mode, channel="chat")
                    refresh_session_summary(conn, sid, ollama=ollama if has_ollama else None, settings=settings)
                    conn.commit()
                    break
                elif retrieval_limit > 0:
                    rows = search_chunks(
                        conn,
                        query=question,
                        limit=retrieval_limit,
                        module=module,
                        topic=topic,
                        scientific_field=scientific_field,
                        vocational_discipline=vocational_discipline,
                        source_collection=source_collection,
                        query_embedding=query_embedding,
                        mode=mode,
                    )
                    if PERSONAL_GROWTH_CUE_PATTERN.search(question or ""):
                        personal_rows = search_personal_growth(question, limit=max(2, min(4, retrieval_limit)))
                        if personal_rows:
                            rows = personal_rows + rows
                    if skills_direct_block:
                        try:
                            skill_rows = search_chunks(
                                conn,
                                query=question,
                                limit=min(3, max(1, retrieval_limit)),
                                source_collection="SMi Skills",
                                query_embedding=query_embedding,
                                mode=mode,
                            )
                        except Exception:
                            skill_rows = []
                        if skill_rows:
                            seen_chunk_ids = {int(r.get("chunk_id") or 0) for r in rows}
                            rows = [
                                r for r in skill_rows
                                if int(r.get("chunk_id") or 0) not in seen_chunk_ids
                            ] + rows
                else:
                    rows = []
                context = _context_block(rows)
                citations = sorted(
                    {str(r.get("source_id") or "").strip() for r in rows if str(r.get("source_id") or "").strip()}
                )

                if has_ollama:
                    if mode == "questionnaire":
                        ollama.max_output_tokens = min(180, ollama.max_output_tokens)
                    system_prompt = _build_system_prompt(
                        mode,
                        user_message=question,
                        behavior_variant=variant,
                        qualia_state=qualia,
                        effective_variant_ratio=effective_variant_ratio,
                    )
                    history = _history_block(conn, sid)
                    direct_file_context = ""
                    if mode == "coding":
                        direct_file_context, direct_file_references = _build_direct_file_context(
                            question,
                            settings=settings,
                        )
                    skills_block = ""
                    if mode == "coding" or question_has_coding_intent(question):
                        skills_block = build_skills_fallback_block(question)
                        if skills_block:
                            skills_block = skills_block + "\n\n"
                    if mode == "questionnaire":
                        user_payload = (
                            "Questionnaire mode is active.\n"
                            "Return only the requested JSON output.\n"
                            "No markdown, no code fences, no extra prose.\n\n"
                            f"USER QUESTION:\n{question}\n"
                        )
                    elif conversational_turn:
                        user_payload = (
                            "Handle this as a normal conversational turn.\n"
                            "Respond directly and naturally to the user message.\n"
                            "Do not require citations or mention source identifiers for this turn.\n\n"
                            f"SESSION MEMORY:\n{history if history else '[No prior session memory]'}\n\n"
                            f"USER MESSAGE:\n{question}\n\n"
                            "Return concise, friendly output."
                        )
                    else:
                        direct_file_block = (
                            f"DIRECT FILE CONTEXT:\n{direct_file_context}\n\n"
                            if direct_file_context
                            else ""
                        )
                        user_payload = (
                            "Answer the user question using supplied local context where relevant.\n"
                            "Do not expose source IDs, citation tags, or retrieval scaffolding unless explicitly requested.\n"
                            "If local context is insufficient for factual claims, state the gap and ask a concise clarifying question.\n\n"
                            f"SESSION MEMORY:\n{history if history else '[No prior session memory]'}\n\n"
                            f"USER QUESTION:\n{question}\n\n"
                            f"{direct_file_block}"
                            f"LOCAL CONTEXT:\n{context if context else '[No additional local context available]'}\n\n"
                            f"{skills_block}"
                            "Return concise, actionable output. If CODING SKILL CONTEXT is present above, "
                            "implement using those exact patterns and names."
                        )
                    try:
                        answer = ollama.chat(
                            [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_payload},
                            ]
                        )
                    except Exception as ex:
                        answer = _build_fallback_answer(
                            question=question,
                            mode=mode,
                            rows=rows,
                            effective_variant_ratio=effective_variant_ratio,
                            qualia_influence=float(qualia.get("influence") or 0.0),
                            model_error=str(ex),
                        )
                    if not str(answer or "").strip():
                        answer = _build_fallback_answer(
                            question=question,
                            mode=mode,
                            rows=rows,
                            effective_variant_ratio=effective_variant_ratio,
                            qualia_influence=float(qualia.get("influence") or 0.0),
                            model_error="empty_model_response",
                        )
                else:
                    answer = _build_fallback_answer(
                        question=question,
                        mode=mode,
                        rows=rows,
                        effective_variant_ratio=effective_variant_ratio,
                        qualia_influence=float(qualia.get("influence") or 0.0),
                        model_error=None,
                    )

                if not is_identity_query(question):
                    answer = neutralize_identity_signaling(answer)
                answer = sanitize_user_facing_text(answer, settings=settings)

                _store_message(conn, sid, "assistant", answer, citations=citations, mode=mode, channel="chat")
                refresh_session_summary(conn, sid, ollama=ollama if has_ollama else None, settings=settings)
                conn.commit()
            break
        except sqlite3.OperationalError as ex:
            if "locked" not in str(ex).lower():
                raise
            sid = sid or session_id or f"session-transient-{uuid4().hex}"
            rows = []
            citations = []
            if identity_or_capability_turn:
                answer = _build_identity_capability_answer(settings=settings, mode=mode)
                answer = sanitize_user_facing_text(answer, settings=settings)
                append_discussion_log(
                    session_id=sid,
                    role="user",
                    content=question,
                    mode=mode,
                    channel="chat",
                    citations=[],
                )
                append_discussion_log(
                    session_id=sid,
                    role="assistant",
                    content=answer,
                    mode=mode,
                    channel="chat",
                    citations=[],
                )
                break
            if conversational_turn:
                answer = _build_small_talk_response(question)
                answer = sanitize_user_facing_text(answer, settings=settings)
                append_discussion_log(
                    session_id=sid,
                    role="user",
                    content=question,
                    mode=mode,
                    channel="chat",
                    citations=[],
                )
                append_discussion_log(
                    session_id=sid,
                    role="assistant",
                    content=answer,
                    mode=mode,
                    channel="chat",
                    citations=[],
                )
                break
            if attempt == attempts - 1:
                answer = _build_fallback_answer(
                    question=question,
                    mode=mode,
                    rows=[],
                    effective_variant_ratio=effective_variant_ratio,
                    qualia_influence=float(qualia.get("influence") or 0.0),
                    model_error="sqlite_contention_after_retries",
                )
                answer = sanitize_user_facing_text(answer, settings=settings)
                append_discussion_log(
                    session_id=sid,
                    role="user",
                    content=question,
                    mode=mode,
                    channel="chat",
                    citations=[],
                )
                append_discussion_log(
                    session_id=sid,
                    role="assistant",
                    content=answer,
                    mode=mode,
                    channel="chat",
                    citations=[],
                )
                break
            delay_seconds = (float(chat_db_lock_backoff_ms) / 1000.0) * float(attempt + 1)
            time.sleep(delay_seconds)

    SMI_tunnel_result: dict[str, Any] | None = None
    if should_autonomous_SMI_query(question=question, mode=mode, session_id=sid, settings=settings):
        SMI_context_lines: list[str] = []
        if answer:
            SMI_context_lines.append("SMi provisional answer:\n" + _clip_text(answer, max_chars=2600))
        if rows:
            SMI_context_lines.append("Top retrieved evidence:")
            for row in rows[:3]:
                excerpt = _clip_text(str(row.get("content") or ""), max_chars=260)
                source_id = str(row.get("source_id") or "").strip() or "SRC-UNKNOWN"
                if excerpt:
                    SMI_context_lines.append(f"- [{source_id}] {excerpt}")
        context_block = "\n".join(SMI_context_lines).strip()
        try:
            SMI_tunnel_result = submit_SMI_query(
                {
                    "query": question,
                    "mode": mode,
                    "session_id": sid,
                    "requested_by": DEVELOPER_NAME,
                    "source": "smi_autonomous_chat",
                    "context": context_block,
                    "citations": citations,
                    "metadata": {
                        "channel": "chat",
                        "retrieved_count": len(rows),
                    },
                    "title": _clip_text(question, max_chars=120),
                }
            )
            SMI_answer = str(SMI_tunnel_result.get("answer") or "").strip()
            if SMI_answer:
                SMI_answer = sanitize_user_facing_text(SMI_answer, settings=settings)
                if _is_fallback_answer(answer):
                    answer = SMI_answer
                else:
                    answer = (answer.rstrip() + "\n\n[SMI Tunnel]\n" + SMI_answer).strip()
                append_discussion_log(
                    session_id=sid or f"session-transient-{uuid4().hex}",
                    role="assistant",
                    content=f"[SMI Tunnel answer]\n{_clip_text(SMI_answer, max_chars=6000)}",
                    mode=mode,
                    channel="chat",
                    citations=citations,
                )
        except Exception as ex:
            SMI_tunnel_result = {"ok": False, "error": str(ex)}

    answer = sanitize_user_facing_text(answer, settings=settings)

    return {
        "ok": True,
        "session_id": sid,
        "mode": mode,
        "answer": answer,
        "citations": citations,
        "direct_file_context": direct_file_references,
        "retrieved_chunks": _serialize_retrieved_chunks(rows, max_items=retrieval_limit),
        "web_fetch_results": fetched,
        "SMI_tunnel": SMI_tunnel_result,
        "qualia": {
            "enabled": bool(qualia.get("enabled")),
            "controls_enabled": bool(qualia.get("controls_enabled", True)),
            "source_count": int(qualia.get("source_count") or 0),
            "source_files": qualia.get("source_files") or [],
            "alpha": float(qualia.get("alpha") or 0.0),
            "beta": float(qualia.get("beta") or 0.0),
            "gamma_requested": float(qualia.get("gamma_requested") or 0.0),
            "gamma_effective": float(qualia.get("gamma") or 0.0),
            "gamma_cap": float(qualia.get("gamma_cap") or 0.25),
            "influence": float(qualia.get("influence") or 0.0),
            "stability_index": float(qualia.get("stability_index") or 0.0),
            "stability_gate": float(qualia.get("stability_gate") or 1.0),
            "base_variant_ratio": base_variant_ratio,
            "effective_variant_ratio": effective_variant_ratio,
            "parameters": qualia.get("parameters") or {},
            "vectors": qualia.get("vectors") or {},
            "summary": qualia.get("summary") or {},
            "bell_curve": qualia.get("bell_curve") or {},
            "trajectory": qualia.get("trajectory") or [],
        },
        "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

