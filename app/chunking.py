from __future__ import annotations

import re


MULTISPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    cleaned = (text or "").replace("\r", "\n")
    cleaned = cleaned.replace("\u0000", " ").replace("\ufeff", " ")
    return MULTISPACE.sub(" ", cleaned).strip()


def split_into_chunks(
    text: str,
    max_chunk_chars: int = 1100,
    overlap_chars: int = 180,
    min_chunk_chars: int = 220,
) -> list[str]:
    body = normalize_text(text)
    if not body:
        return []
    if len(body) <= max_chunk_chars:
        return [body]

    sentences = re.split(r"(?<=[\.\!\?])\s+", body)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        candidate = f"{current} {s}".strip() if current else s
        if len(candidate) <= max_chunk_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = current[-overlap_chars:] if overlap_chars > 0 else ""
            current = f"{current} {s}".strip()
        else:
            # Hard split for very long sentence.
            start = 0
            while start < len(s):
                end = min(len(s), start + max_chunk_chars)
                piece = s[start:end].strip()
                if piece:
                    chunks.append(piece)
                start = max(start + max_chunk_chars - overlap_chars, start + 1)

    if current:
        chunks.append(current)

    merged: list[str] = []
    for chunk in chunks:
        if not merged:
            merged.append(chunk)
            continue
        if len(chunk) < min_chunk_chars:
            merged[-1] = f"{merged[-1]} {chunk}".strip()
        else:
            merged.append(chunk)
    return [c.strip() for c in merged if c.strip()]

