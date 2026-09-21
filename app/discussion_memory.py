from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import get_settings
from .output_sanitizer import sanitize_user_facing_text


def _safe_token(value: str, fallback: str) -> str:
    raw = str(value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")
    return cleaned or fallback


def _resolve_log_root(settings: dict[str, Any]) -> Path:
    memory = settings.get("memory", {}) if isinstance(settings.get("memory"), dict) else {}
    configured = str(memory.get("discussion_log_dir") or "").strip()
    if configured:
        return Path(configured).resolve()
    taxonomy_root = Path(settings.get("paths", {}).get("taxonomy_root") or ".").resolve()
    return (taxonomy_root / "SMI_Log").resolve()


def append_discussion_log(
    *,
    session_id: str,
    role: str,
    content: str,
    mode: str = "knowledge",
    channel: str = "chat",
    citations: list[str] | None = None,
) -> str | None:
    try:
        settings = get_settings()
        memory = settings.get("memory", {}) if isinstance(settings.get("memory"), dict) else {}
        if not bool(memory.get("discussion_logging_enabled", True)):
            return None

        max_chars = max(200, min(12000, int(memory.get("discussion_log_max_chars") or 6000)))
        timestamp = datetime.now(timezone.utc)
        timestamp_utc = timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")

        log_root = _resolve_log_root(settings)
        day_dir = log_root / "discussion_memory" / timestamp.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        sid = _safe_token(session_id, "session")
        role_key = _safe_token(role, "message")
        prefix = _safe_token(str(memory.get("discussion_log_prefix") or "discussion_memory"), "discussion_memory")
        unique = uuid4().hex[:8]
        file_name = f"{prefix}_{timestamp.strftime('%Y%m%dT%H%M%SZ')}_{sid}_{role_key}_{unique}.md"
        target = day_dir / file_name

        cleaned_content = str(content or "")
        if role_key == "assistant":
            cleaned_content = sanitize_user_facing_text(cleaned_content, settings=settings)
        cleaned_content = re.sub(r"\s+", " ", cleaned_content).strip()
        if len(cleaned_content) > max_chars:
            cleaned_content = cleaned_content[: max_chars - 3].rstrip() + "..."

        payload = [
            "# SMi Discussion Memory",
            f"- timestamp_utc: {timestamp_utc}",
            f"- session_id: {session_id}",
            f"- role: {role}",
            f"- mode: {mode}",
            f"- channel: {channel}",
            f"- citations: {json.dumps(citations or [], ensure_ascii=True)}",
            "",
            "## Content",
            cleaned_content or "[empty]",
            "",
        ]
        target.write_text("\n".join(payload), encoding="utf-8")

        # Self-updating per-session archive artifacts.
        session_root = log_root / "discussion_memory" / "sessions"
        session_root.mkdir(parents=True, exist_ok=True)
        session_jsonl = session_root / f"{sid}.jsonl"
        session_md = session_root / f"{sid}.md"
        event = {
            "timestamp_utc": timestamp_utc,
            "session_id": session_id,
            "role": role,
            "mode": mode,
            "channel": channel,
            "citations": citations or [],
            "content": cleaned_content or "[empty]",
        }
        with session_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

        if not session_md.exists():
            session_md.write_text(
                "\n".join(
                    [
                        "# SMi Session Archive",
                        f"- session_id: {session_id}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        with session_md.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n".join(
                    [
                        f"## {timestamp_utc} | {role}",
                        f"- mode: {mode}",
                        f"- channel: {channel}",
                        f"- citations: {json.dumps(citations or [], ensure_ascii=True)}",
                        "",
                        cleaned_content or "[empty]",
                        "",
                    ]
                )
            )

        # Promote user prompts into instruction memory for autonomous learning.
        if role_key == "user" and cleaned_content:
            instruction_root = log_root / "instruction_memory"
            instruction_root.mkdir(parents=True, exist_ok=True)
            day_file = instruction_root / f"instructions_{timestamp.strftime('%Y-%m-%d')}.md"
            with day_file.open("a", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            f"- [{timestamp_utc}] session={session_id} mode={mode} channel={channel}",
                            f"  instruction: {cleaned_content}",
                        ]
                    )
                    + "\n"
                )

        return str(target)
    except Exception:
        return None
