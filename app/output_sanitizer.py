from __future__ import annotations

import re
from typing import Any

from .config import get_settings


_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\u202A-\u202E\u2060-\u206F\ufeff]")
_CJK_RE = re.compile(
    r"[\u3000-\u303F\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uf900-\ufaff\uac00-\ud7af]"
)
_SOURCE_TAG_RE = re.compile(
    r"\[(?:SRC-[^\]]+|source[_ -]?id:[^\]]+|source:[^\]]+|citation:[^\]]+)\]",
    re.IGNORECASE,
)

_SCAFFOLD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bBased on the provided sources[,:\s]*", re.IGNORECASE), ""),
    (re.compile(r"\bBased on provided sources[,:\s]*", re.IGNORECASE), ""),
    (re.compile(r"\bBased on the provided context[,:\s]*", re.IGNORECASE), ""),
    (re.compile(r"\bprovided context\b", re.IGNORECASE), "local context"),
    (re.compile(r"\bindexed context\b", re.IGNORECASE), "local context"),
    (re.compile(r"\bindexed sources\b", re.IGNORECASE), "local knowledge"),
    (re.compile(r"\bindexed evidence\b", re.IGNORECASE), "local context"),
    (re.compile(r"\bsource uploads\b", re.IGNORECASE), "additional local material"),
    (re.compile(r"\bsource-based fallback mode\b", re.IGNORECASE), "local fallback mode"),
    (re.compile(r"\bThere is no indexed context available\b", re.IGNORECASE), "I do not have enough local context yet"),
    (re.compile(r"\bNo indexed context available\b", re.IGNORECASE), "No additional local context available"),
]


def _filter_settings(settings: dict[str, Any] | None = None) -> dict[str, bool]:
    source = settings if isinstance(settings, dict) else get_settings()
    safety = source.get("safety", {}) if isinstance(source.get("safety"), dict) else {}
    raw = safety.get("output_filters", {}) if isinstance(safety.get("output_filters"), dict) else {}
    return {
        "strip_zero_width": bool(raw.get("strip_zero_width", True)),
        "strip_cjk_characters": bool(raw.get("strip_cjk_characters", True)),
        "hide_source_scaffolding": bool(raw.get("hide_source_scaffolding", True)),
        "remove_source_id_tags": bool(raw.get("remove_source_id_tags", True)),
    }


def sanitize_user_facing_text(text: str, settings: dict[str, Any] | None = None) -> str:
    cleaned = str(text or "")
    if not cleaned:
        return ""

    filters = _filter_settings(settings)

    if filters["strip_zero_width"]:
        cleaned = _ZERO_WIDTH_RE.sub("", cleaned)

    if filters["hide_source_scaffolding"]:
        for pattern, replacement in _SCAFFOLD_PATTERNS:
            cleaned = pattern.sub(replacement, cleaned)

    if filters["remove_source_id_tags"]:
        cleaned = _SOURCE_TAG_RE.sub("", cleaned)

    if filters["strip_cjk_characters"]:
        cleaned = _CJK_RE.sub("", cleaned)

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return "I am ready to help. Please send your task."
    return cleaned
