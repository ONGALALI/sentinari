from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


_SAFE_UPLOAD_FALLBACK = "upload.bin"
_SAFE_SESSION_FALLBACK = "session-transient"


def sanitize_chat_upload_filename(filename: str | None) -> str:
    raw = Path(str(filename or "")).name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", raw)
    sanitized = re.sub(r"-+\.", ".", sanitized)
    sanitized = sanitized.strip(".-")
    return sanitized[:120] or _SAFE_UPLOAD_FALLBACK


def sanitize_chat_upload_session_id(session_id: str | None) -> str:
    raw = str(session_id or "").strip()
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")
    return sanitized[:80] or _SAFE_SESSION_FALLBACK


def allocate_chat_upload_path(raw_root: str | Path, session_id: str | None, filename: str | None) -> Path:
    root = Path(raw_root).resolve() / "chat_uploads" / sanitize_chat_upload_session_id(session_id)
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_name = sanitize_chat_upload_filename(filename)
    return root / f"{timestamp}_{safe_name}"
