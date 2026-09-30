from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import get_project_root

FALLBACK_OFF_FLAG = "skills_fallback_off.flag"
_SKILL_NAME_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")
_SKILL_TOKENS = re.compile(r"[a-z0-9]{3,}")


def get_skills_root() -> Path:
    import os
    configured = os.environ.get("SENTINARI_SHARED_SKILLS_ROOT", "").strip() or os.environ.get("SMI_SHARED_SKILLS_ROOT", "").strip()
    return Path(configured).resolve() if configured else (get_project_root() / "data" / "skills").resolve()


def get_index_path() -> Path:
    return get_skills_root() / "skills_index.json"


def sanitize_skill_name(name: str | None) -> str:
    raw = str(name or "").strip()
    sanitized = _SKILL_NAME_SANITIZE.sub("-", raw).strip(".-")
    return sanitized[:60].lower() or "unnamed-skill"


def is_fallback_disabled() -> bool:
    try:
        return (get_skills_root() / FALLBACK_OFF_FLAG).exists()
    except Exception:
        return False


def set_fallback_enabled(enabled: bool) -> dict[str, Any]:
    root = get_skills_root()
    root.mkdir(parents=True, exist_ok=True)
    flag = root / FALLBACK_OFF_FLAG
    try:
        if enabled:
            if flag.exists():
                flag.unlink()
        else:
            flag.write_text("skills auto-fallback disabled by operator", encoding="utf-8")
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "skills_fallback_enabled": bool(enabled)}


def load_skill_index() -> list[dict[str, Any]]:
    try:
        data = json.loads(get_index_path().read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def save_skill_index(skills: list[dict[str, Any]]) -> None:
    root = get_skills_root()
    root.mkdir(parents=True, exist_ok=True)
    get_index_path().write_text(
        json.dumps(skills, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def register_skill(
    *,
    name: str,
    files: list[dict[str, Any]],
    chunk_count: int,
    description: str = "",
) -> dict[str, Any]:
    """Insert or update a skill entry in the index (keyed by skill name)."""
    skills = load_skill_index()
    from datetime import datetime, timezone

    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entry = {
        "name": name,
        "description": str(description or "").strip()[:300],
        "files": files,
        "file_count": len(files),
        "chunk_count": int(chunk_count or 0),
        "updated_at": updated_at,
    }
    for idx, existing in enumerate(skills):
        if str(existing.get("name") or "").strip().lower() == name:
            skills[idx] = entry
            break
    else:
        skills.append(entry)
    save_skill_index(skills)
    return entry


def build_skills_fallback_block(question: str, *, max_skills: int = 2, max_chars_per_file: int = 3200) -> str:
    """Return a prompt block with matching uploaded skill excerpts for coding fallback.

    Matching is intentionally lightweight: word-overlap between the question and
    the skill name/description/file names. Returns "" when disabled or no match.
    """
    if is_fallback_disabled():
        return ""
    skills = load_skill_index()
    if not skills:
        return ""

    question_tokens = set(_SKILL_TOKENS.findall(str(question or "").lower()))
    if not question_tokens:
        return ""

    scored: list[tuple[int, dict[str, Any]]] = []
    for skill in skills:
        name_tokens = set(_SKILL_TOKENS.findall(str(skill.get("name") or "").lower()))
        name_tokens |= set(_SKILL_TOKENS.findall(str(skill.get("description") or "").lower()))
        for item in skill.get("files") or []:
            if isinstance(item, dict):
                name_tokens |= set(_SKILL_TOKENS.findall(str(item.get("name") or "").lower()))
        score = len(question_tokens & name_tokens)
        if score > 0:
            scored.append((score, skill))
    if not scored:
        return ""
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("name") or "")))

    blocks: list[str] = []
    for _, skill in scored[: max(1, max_skills)]:
        for item in (skill.get("files") or [])[:2]:
            path_text = str((item or {}).get("path") or "")
            if not path_text:
                continue
            try:
                text = Path(path_text).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            snippet = text[: max(200, max_chars_per_file)].strip()
            if not snippet:
                continue
            blocks.append(f"[skill: {skill.get('name')} | file: {Path(path_text).name}]\n{snippet}")
    if not blocks:
        return ""
    header = (
        "CODING SKILL CONTEXT (operator-uploaded skills). When relevant, implement the task "
        "using these exact patterns, APIs, and names - they take priority over generic examples:"
    )
    return header + "\n\n" + "\n\n".join(blocks)
