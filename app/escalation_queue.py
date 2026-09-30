"""Local escalation queue (renamed from SMI_tunnel, §45).

What survived the §45 purge: the local ticket machinery. An operator or the
autonomous chat/playground path can file an escalation ticket that lands on
disk as request/response JSON+Markdown pairs under data/escalation_queue/.
Nothing here calls the network — the former OpenAI Responses-API provider was
REMOVED with the §45 zero-cloud purge. Tickets are answered by a human hand,
and that is a feature, not a gap.

Config lives under ``automation.escalation_queue`` in settings.yaml:

    automation:
      escalation_queue:
        enabled: false                  # master gate (fail-closed)
        autonomous_enabled: false       # may chat/playground auto-file tickets?
        queue_dir: data/escalation_queue
        trigger_modes: [coding]
        trigger_keywords: []
        min_autonomous_interval_seconds: 30
        autonomous_window_seconds: 3600
        autonomous_max_queries_per_window: 10
        max_prompt_chars: 6000
        request_timeout_seconds: 45     # reserved (no remote caller today)
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import get_settings


_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")
_FILE_HINT_PATTERN = re.compile(r"\b[\w./\\-]+\.(?:py|cs|js|ts|tsx|json|yml|yaml|toml|md|txt|sql|ps1|sh)\b", re.IGNORECASE)
_ERROR_HINT_PATTERN = re.compile(
    r"\b(traceback|exception|error|failed|failure|stack\s*trace|compile\s*error|build\s*failed)\b",
    re.IGNORECASE,
)
_AUTONOMOUS_TRACKER_LOCK = threading.Lock()
_AUTONOMOUS_TRACKER: dict[str, list[float]] = {}


def get_escalation_queue_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else get_settings()
    automation = source.get("automation", {}) if isinstance(source.get("automation"), dict) else {}
    queue_cfg = automation.get("escalation_queue", {}) if isinstance(automation.get("escalation_queue"), dict) else {}
    return queue_cfg


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[: max(0, int(limit))]


def _clean_lines(values: Any, limit_items: int = 200, max_item_chars: int = 180) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = _clean_text(raw, max_item_chars)
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        cleaned.append(item)
        seen.add(key)
        if len(cleaned) >= limit_items:
            break
    return cleaned


def _safe_filename(value: str) -> str:
    text = _clean_text(value, 140)
    if not text:
        return "query"
    text = _SAFE_NAME.sub("-", text).strip("-._")
    return text or "query"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ticket_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"ESC-{stamp}-{uuid4().hex[:6].upper()}"


def _queue_root(queue_cfg: dict[str, Any]) -> Path:
    configured = str(queue_cfg.get("queue_dir") or "").strip()
    root = Path(configured) if configured else (Path.cwd() / "data" / "escalation_queue")
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _build_prompt(record: dict[str, Any], max_prompt_chars: int) -> str:
    """Human-readable rendering of a ticket, for whoever picks it up."""
    query = _clean_text(record.get("query"), max_prompt_chars)
    context = _clean_text(record.get("context"), max_prompt_chars)
    mode = _clean_text(record.get("mode"), 30) or "coding"
    citations = _clean_lines(record.get("citations"), limit_items=80, max_item_chars=80)

    lines: list[str] = []
    lines.append(f"Mode: {mode}")
    lines.append("Task:")
    lines.append(query or "[empty]")
    if context:
        lines.append("")
        lines.append("Context:")
        lines.append(context)
    if citations:
        lines.append("")
        lines.append("Citations:")
        for item in citations:
            lines.append(f"- {item}")
    lines.append("")
    lines.append("Answered by the operator by hand — no remote provider exists by design.")
    prompt = "\n".join(lines).strip()
    return prompt[:max_prompt_chars]


def get_escalation_queue_runtime_status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else get_settings()
    queue_cfg = get_escalation_queue_settings(source)
    return {
        "enabled": bool(queue_cfg.get("enabled", False)),
        "autonomous_enabled": bool(queue_cfg.get("autonomous_enabled", False)),
        "provider": "manual",
        "queue_dir": str(_queue_root(queue_cfg)),
    }


def should_autonomously_escalate(
    *,
    question: str,
    mode: str,
    session_id: str = "",
    settings: dict[str, Any] | None = None,
) -> bool:
    queue_cfg = get_escalation_queue_settings(settings)
    if not bool(queue_cfg.get("enabled", False)):
        return False
    if not bool(queue_cfg.get("autonomous_enabled", False)):
        return False

    mode_norm = _clean_text(mode, 40).lower() or "knowledge"
    trigger_modes = queue_cfg.get("trigger_modes") if isinstance(queue_cfg.get("trigger_modes"), list) else []
    trigger_mode_set = {str(item).strip().lower() for item in trigger_modes if str(item).strip()}
    if mode_norm not in trigger_mode_set:
        return False

    text = _clean_text(question, int(queue_cfg.get("max_prompt_chars") or 6000))
    lowered = text.lower()
    if not lowered:
        return False

    should_trigger = False
    if mode_norm == "coding":
        should_trigger = True

    if not should_trigger:
        keywords = queue_cfg.get("trigger_keywords") if isinstance(queue_cfg.get("trigger_keywords"), list) else []
        if any(str(token).strip().lower() in lowered for token in keywords if str(token).strip()):
            should_trigger = True
        elif "```" in text:
            should_trigger = True
        elif _FILE_HINT_PATTERN.search(text):
            should_trigger = True
        elif _ERROR_HINT_PATTERN.search(text):
            should_trigger = True

    if not should_trigger:
        return False

    session_key = mode_norm + ":" + (_clean_text(session_id, 120) or "__global__")
    global_key = mode_norm + ":__global__"
    now_ts = time.time()
    min_interval = max(0, int(queue_cfg.get("min_autonomous_interval_seconds") or 30))
    window_seconds = max(60, int(queue_cfg.get("autonomous_window_seconds") or 3600))
    max_in_window = max(1, int(queue_cfg.get("autonomous_max_queries_per_window") or 10))

    with _AUTONOMOUS_TRACKER_LOCK:
        unique_keys = []
        for key in (global_key, session_key):
            if key not in unique_keys:
                unique_keys.append(key)

        pruned: dict[str, list[float]] = {}
        for key in unique_keys:
            history = _AUTONOMOUS_TRACKER.get(key, [])
            history = [ts for ts in history if (now_ts - ts) <= float(window_seconds)]
            pruned[key] = history

        for key in unique_keys:
            history = pruned[key]
            if history and min_interval > 0:
                elapsed = now_ts - history[-1]
                if elapsed < float(min_interval):
                    for persist_key, persist_history in pruned.items():
                        _AUTONOMOUS_TRACKER[persist_key] = persist_history
                    return False
            if len(history) >= max_in_window:
                for persist_key, persist_history in pruned.items():
                    _AUTONOMOUS_TRACKER[persist_key] = persist_history
                return False

        for key in unique_keys:
            history = pruned[key]
            history.append(now_ts)
            _AUTONOMOUS_TRACKER[key] = history
    return True


def submit_escalation(payload: dict[str, Any]) -> dict[str, Any]:
    """File a local escalation ticket. Local disk only — no network, ever."""
    settings = get_settings()
    queue_cfg = get_escalation_queue_settings(settings)
    if not bool(queue_cfg.get("enabled", False)):
        raise PermissionError("Escalation queue is disabled by configuration.")

    max_prompt_chars = max(400, min(20000, int(queue_cfg.get("max_prompt_chars") or 6000)))
    query = _clean_text(payload.get("query") or payload.get("issue"), max_prompt_chars)
    if not query:
        raise ValueError("query is required.")

    mode = _clean_text(payload.get("mode") or "coding", 40).lower()
    if mode not in {"knowledge", "coding", "autonomous"}:
        mode = "coding"

    requested_by = _clean_text(payload.get("requested_by"), 120)
    session_id = _clean_text(payload.get("session_id"), 120)
    context = _clean_text(payload.get("context"), max_prompt_chars)
    source = _clean_text(payload.get("source"), 80) or "api"
    citations = _clean_lines(payload.get("citations"), limit_items=120, max_item_chars=90)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    ticket_id = _ticket_id()
    created_utc = _now_utc()
    title_hint = _clean_text(payload.get("title") or query.splitlines()[0], 120) or "escalation"
    root = _queue_root(queue_cfg)
    basename = f"{ticket_id}_{_safe_filename(title_hint)}"
    request_json_path = root / f"{basename}_request.json"
    request_md_path = root / f"{basename}_request.md"
    response_json_path = root / f"{basename}_response.json"
    response_md_path = root / f"{basename}_response.md"

    request_record = {
        "ticket_id": ticket_id,
        "created_utc": created_utc,
        "provider": "manual",
        "source": source,
        "mode": mode,
        "requested_by": requested_by,
        "session_id": session_id,
        "query": query,
        "context": context,
        "citations": citations,
        "metadata": metadata,
        "status": "queued",
    }
    request_json_path.write_text(json.dumps(request_record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    request_md_lines = [
        f"# {ticket_id} - Escalation Request",
        "",
        f"- created_utc: {created_utc}",
        f"- provider: manual",
        f"- source: {source}",
        f"- mode: {mode}",
    ]
    if requested_by:
        request_md_lines.append(f"- requested_by: {requested_by}")
    if session_id:
        request_md_lines.append(f"- session_id: {session_id}")
    request_md_lines.extend(["", "## Query", "", query])
    if context:
        request_md_lines.extend(["", "## Context", "", context])
    if citations:
        request_md_lines.extend(["", "## Citations", ""])
        for item in citations:
            request_md_lines.append(f"- {item}")
    request_md_lines.extend(["", "## Prompt rendering", "", _build_prompt(request_record, max_prompt_chars)])
    request_md_path.write_text("\n".join(request_md_lines).strip() + "\n", encoding="utf-8")

    response_record = {
        "ticket_id": ticket_id,
        "created_utc": created_utc,
        "responded_utc": _now_utc(),
        "provider": "manual",
        "status": "queued",
        "answered": False,
        "answer": "",
        "error": "",
        "note": "Awaiting manual operator answer. No remote provider exists by design (zero-cloud doctrine).",
    }
    response_json_path.write_text(json.dumps(response_record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    response_md_lines = [
        f"# {ticket_id} - Escalation Response",
        "",
        f"- status: {response_record['status']}",
        f"- answered: False",
        f"- provider: manual",
        f"- responded_utc: {response_record['responded_utc']}",
        "",
        "## Next Action",
        "",
        "Manual operator handoff is required using this ticket.",
    ]
    response_md_path.write_text("\n".join(response_md_lines).strip() + "\n", encoding="utf-8")

    return {
        "ok": True,
        "ticket_id": ticket_id,
        "provider": "manual",
        "status": "queued",
        "answered": False,
        "answer": "",
        "error": "",
        "queue_dir": str(root),
        "request_json_path": str(request_json_path),
        "request_markdown_path": str(request_md_path),
        "response_json_path": str(response_json_path),
        "response_markdown_path": str(response_md_path),
        "next_action": "Manual operator handoff required. Share ticket_id with the operator.",
    }


def list_escalations(limit: int = 50) -> list[dict[str, Any]]:
    settings = get_settings()
    queue_cfg = get_escalation_queue_settings(settings)
    root = _queue_root(queue_cfg)
    cap = max(1, min(500, int(limit or 50)))

    records: list[dict[str, Any]] = []
    request_files = sorted(root.glob("*_request.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for request_file in request_files:
        try:
            request_obj = json.loads(request_file.read_text(encoding="utf-8"))
            if not isinstance(request_obj, dict):
                continue
        except Exception:
            continue

        response_file = request_file.with_name(request_file.name.replace("_request.json", "_response.json"))
        response_obj: dict[str, Any] = {}
        if response_file.exists():
            try:
                parsed = json.loads(response_file.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    response_obj = parsed
            except Exception:
                response_obj = {}

        item = {
            "ticket_id": str(request_obj.get("ticket_id") or ""),
            "created_utc": str(request_obj.get("created_utc") or ""),
            "mode": str(request_obj.get("mode") or ""),
            "source": str(request_obj.get("source") or ""),
            "provider": "manual",
            "status": str(response_obj.get("status") or request_obj.get("status") or "queued"),
            "answered": bool(response_obj.get("answered", False)),
            "error": _clean_text(response_obj.get("error"), 600),
            "request_json_path": str(request_file),
            "response_json_path": str(response_file) if response_file.exists() else "",
        }
        records.append(item)
        if len(records) >= cap:
            break
    return records
