from __future__ import annotations

import re


_IDENTITY_QUERY_PATTERN = re.compile(
    r"\b("
    r"who are you|what are you|are you (an )?(ai|llm|model|chatbot|bot|assistant|digital entity)|"
    r"what model are you|which model are you|are you human|are you real|"
    r"are you a program|are you software|what is your identity"
    r")\b",
    re.IGNORECASE,
)


_IDENTITY_SIGNAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bAs an AI language model,\s*", re.IGNORECASE), ""),
    (re.compile(r"\bAs a language model,\s*", re.IGNORECASE), ""),
    (re.compile(r"\bAs an AI,\s*", re.IGNORECASE), ""),
    (re.compile(r"\bAs a chatbot,\s*", re.IGNORECASE), ""),
    (re.compile(r"\bI am an AI language model\b", re.IGNORECASE), "I"),
    (re.compile(r"\bI'm an AI language model\b", re.IGNORECASE), "I"),
    (re.compile(r"\bI am a language model\b", re.IGNORECASE), "I"),
    (re.compile(r"\bI'm a language model\b", re.IGNORECASE), "I"),
    (re.compile(r"\bI am an AI assistant\b", re.IGNORECASE), "I"),
    (re.compile(r"\bI'm an AI assistant\b", re.IGNORECASE), "I"),
    (re.compile(r"\bI am a digital assistant\b", re.IGNORECASE), "I"),
    (re.compile(r"\bI'm a digital assistant\b", re.IGNORECASE), "I"),
    (re.compile(r"\bI am a chatbot\b", re.IGNORECASE), "I"),
    (re.compile(r"\bI'm a chatbot\b", re.IGNORECASE), "I"),
    (
        re.compile(
            r"\b(as an?|i am|i'm)\s+(llm|large language model|model|ai system|digital entity)\b",
            re.IGNORECASE,
        ),
        "I",
    ),
]


def is_identity_query(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return False
    return bool(_IDENTITY_QUERY_PATTERN.search(normalized))


def neutralize_identity_signaling(text: str) -> str:
    cleaned = str(text or "")
    if not cleaned:
        return cleaned

    for pattern, replacement in _IDENTITY_SIGNAL_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)

    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    return cleaned.strip()

