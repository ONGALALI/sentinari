from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from .config import get_settings


_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")
_FILE_HINT_PATTERN = re.compile(r"\b[\w./\\-]+\.(?:py|cs|js|ts|tsx|json|yml|yaml|toml|md|txt|sql|ps1|sh)\b", re.IGNORECASE)
_ERROR_HINT_PATTERN = re.compile(
    r"\b(traceback|exception|error|failed|failure|stack\s*trace|compile\s*error|build\s*failed)\b",
    re.IGNORECASE,
)
_AUTONOMOUS_TRACKER_LOCK = threading.Lock()
_AUTONOMOUS_TRACKER: dict[str, list[float]] = {}


def get_SMI_tunnel_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else get_settings()
    automation = source.get("automation", {}) if isinstance(source.get("automation"), dict) else {}
    SMI = automation.get("SMI_tunnel", {}) if isinstance(automation.get("SMI_tunnel"), dict) else {}
    return SMI


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
    return f"CDX-{stamp}-{uuid4().hex[:6].upper()}"


def _queue_root(SMI_cfg: dict[str, Any]) -> Path:
    configured = str(SMI_cfg.get("queue_dir") or "").strip()
    root = Path(configured) if configured else (Path.cwd() / "data" / "SMI_tunnel")
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_path_candidate(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    return candidate


def _read_env_value_from_file(file_path: Path, key_name: str) -> str:
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except Exception:
        return ""

    target_key = str(key_name or "").strip()
    if not target_key:
        return ""

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if line.startswith("\ufeff"):
            line = line.lstrip("\ufeff").strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != target_key:
            continue
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] in {"'", '"'} and cleaned[-1] == cleaned[0]:
            cleaned = cleaned[1:-1]
        return cleaned.strip()
    return ""


def _resolve_openai_credential(openai_cfg: dict[str, Any]) -> dict[str, Any]:
    primary_env = str(openai_cfg.get("api_key_env") or "OPENAI_API_KEY").strip() or "OPENAI_API_KEY"

    env_candidates_raw = openai_cfg.get("api_key_envs") if isinstance(openai_cfg.get("api_key_envs"), list) else []
    env_seed: list[str] = [primary_env]
    for item in env_candidates_raw:
        text = str(item or "").strip()
        if text:
            env_seed.append(text)
    for fallback in ("OPENAI_API_KEY", "OPENAI_AUTH_TOKEN", "OPENAI_ACCESS_TOKEN"):
        env_seed.append(fallback)

    env_candidates: list[str] = []
    seen_envs: set[str] = set()
    for item in env_seed:
        key = item.lower()
        if key in seen_envs:
            continue
        env_candidates.append(item)
        seen_envs.add(key)

    checked_envs: list[str] = []
    checked_files: list[str] = []
    for env_name in env_candidates:
        checked_envs.append(env_name)
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return {
                "token": value,
                "source": f"env:{env_name}",
                "checked_envs": checked_envs,
                "checked_files": checked_files,
            }

    file_key = str(openai_cfg.get("api_key_file_key") or primary_env).strip() or primary_env
    file_paths = openai_cfg.get("api_key_file_paths") if isinstance(openai_cfg.get("api_key_file_paths"), list) else []
    for raw in file_paths:
        raw_path = str(raw or "").strip()
        if not raw_path:
            continue
        file_path = _resolve_path_candidate(raw_path)
        checked_files.append(str(file_path))
        value = _read_env_value_from_file(file_path, file_key)
        if value:
            return {
                "token": value,
                "source": f"file:{file_path}:{file_key}",
                "checked_envs": checked_envs,
                "checked_files": checked_files,
            }

    return {
        "token": "",
        "source": "",
        "checked_envs": checked_envs,
        "checked_files": checked_files,
    }


def _extract_response_text(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""

    text = str(payload.get("output_text") or "").strip()
    if text:
        return text

    output = payload.get("output")
    if not isinstance(output, list):
        return ""

    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            value = str(block.get("text") or "").strip()
            if value:
                parts.append(value)
    return "\n\n".join(parts).strip()


def _build_remote_prompt(record: dict[str, Any], max_prompt_chars: int) -> str:
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
    lines.append("Respond with practical, implementation-ready guidance and concise verification steps.")
    prompt = "\n".join(lines).strip()
    return prompt[:max_prompt_chars]


def _call_openai_responses(SMI_cfg: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    openai_cfg = SMI_cfg.get("openai", {}) if isinstance(SMI_cfg.get("openai"), dict) else {}
    credential = _resolve_openai_credential(openai_cfg)
    api_key = str(credential.get("token") or "").strip()
    if not api_key:
        checked_envs = ", ".join(credential.get("checked_envs") or []) or "(none)"
        checked_files = ", ".join(credential.get("checked_files") or []) or "(none)"
        return {
            "ok": False,
            "error": (
                "Missing OpenAI credential. "
                f"Checked env vars: {checked_envs}. "
                f"Checked key files: {checked_files}."
            ),
        }

    base_url = str(openai_cfg.get("base_url") or "https://api.openai.com/v1").strip().rstrip("/")
    model = str(openai_cfg.get("model") or "gpt-5-SMI").strip() or "gpt-5-SMI"
    system_prompt = _clean_text(
        openai_cfg.get("system_prompt")
        or (
            "You are SMI, an expert software engineering assistant. "
            "Return practical steps, patches, and test guidance. Keep it concise and safe. "
            "The user remains the coding authority and approval owner."
        ),
        4000,
    )
    timeout = max(5, min(240, int(SMI_cfg.get("request_timeout_seconds") or 45)))
    max_prompt_chars = max(400, min(20000, int(SMI_cfg.get("max_prompt_chars") or 6000)))

    request_payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _build_remote_prompt(record, max_prompt_chars=max_prompt_chars)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    organization_env = str(openai_cfg.get("organization_env") or "OPENAI_ORG_ID").strip() or "OPENAI_ORG_ID"
    project_env = str(openai_cfg.get("project_env") or "OPENAI_PROJECT_ID").strip() or "OPENAI_PROJECT_ID"
    organization = (os.environ.get(organization_env) or "").strip()
    project = (os.environ.get(project_env) or "").strip()
    if organization:
        headers["OpenAI-Organization"] = organization
    if project:
        headers["OpenAI-Project"] = project

    try:
        resp = requests.post(
            f"{base_url}/responses",
            headers=headers,
            json=request_payload,
            timeout=timeout,
        )
    except Exception as ex:
        return {
            "ok": False,
            "error": str(ex),
            "auth_source": str(credential.get("source") or ""),
        }

    if not resp.ok:
        body = _clean_text(resp.text, 1200)
        return {
            "ok": False,
            "error": f"OpenAI HTTP {resp.status_code}: {body}",
            "auth_source": str(credential.get("source") or ""),
        }

    try:
        data = resp.json()
    except Exception:
        return {
            "ok": False,
            "error": "OpenAI response was not valid JSON.",
            "auth_source": str(credential.get("source") or ""),
        }

    answer = _extract_response_text(data)
    if not answer:
        return {
            "ok": False,
            "error": "OpenAI response contained no text output.",
            "auth_source": str(credential.get("source") or ""),
        }

    return {
        "ok": True,
        "answer": answer,
        "response_id": str(data.get("id") or ""),
        "model": model,
        "auth_source": str(credential.get("source") or ""),
    }


def get_SMI_tunnel_runtime_status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else get_settings()
    SMI_cfg = get_SMI_tunnel_settings(source)
    provider = str(SMI_cfg.get("provider") or "queue_only").strip().lower()
    queue_dir = str(_queue_root(SMI_cfg))

    credential: dict[str, Any] = {"token": "", "source": "", "checked_envs": [], "checked_files": []}
    if provider == "openai_responses":
        openai_cfg = SMI_cfg.get("openai", {}) if isinstance(SMI_cfg.get("openai"), dict) else {}
        credential = _resolve_openai_credential(openai_cfg)

    ready = provider != "openai_responses" or bool(credential.get("token"))
    return {
        "enabled": bool(SMI_cfg.get("enabled", False)),
        "autonomous_enabled": bool(SMI_cfg.get("autonomous_enabled", False)),
        "provider": provider,
        "queue_dir": queue_dir,
        "openai_ready": ready,
        "credential_source": str(credential.get("source") or ""),
        "credential_checked_envs": list(credential.get("checked_envs") or []),
        "credential_checked_files": list(credential.get("checked_files") or []),
    }


def should_autonomous_SMI_query(
    *,
    question: str,
    mode: str,
    session_id: str = "",
    settings: dict[str, Any] | None = None,
) -> bool:
    SMI_cfg = get_SMI_tunnel_settings(settings)
    if not bool(SMI_cfg.get("enabled", False)):
        return False
    if not bool(SMI_cfg.get("autonomous_enabled", False)):
        return False

    mode_norm = _clean_text(mode, 40).lower() or "knowledge"
    trigger_modes = SMI_cfg.get("trigger_modes") if isinstance(SMI_cfg.get("trigger_modes"), list) else []
    trigger_mode_set = {str(item).strip().lower() for item in trigger_modes if str(item).strip()}
    if mode_norm not in trigger_mode_set:
        return False

    text = _clean_text(question, int(SMI_cfg.get("max_prompt_chars") or 6000))
    lowered = text.lower()
    if not lowered:
        return False

    should_trigger = False
    if mode_norm == "coding":
        should_trigger = True

    if not should_trigger:
        keywords = SMI_cfg.get("trigger_keywords") if isinstance(SMI_cfg.get("trigger_keywords"), list) else []
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
    min_interval = max(0, int(SMI_cfg.get("min_autonomous_interval_seconds") or 30))
    window_seconds = max(60, int(SMI_cfg.get("autonomous_window_seconds") or 3600))
    max_in_window = max(1, int(SMI_cfg.get("autonomous_max_queries_per_window") or 10))

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


def submit_SMI_query(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    SMI_cfg = get_SMI_tunnel_settings(settings)
    if not bool(SMI_cfg.get("enabled", False)):
        raise PermissionError("SMI tunnel is disabled by configuration.")

    max_prompt_chars = max(400, min(20000, int(SMI_cfg.get("max_prompt_chars") or 6000)))
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
    title_hint = _clean_text(payload.get("title") or query.splitlines()[0], 120) or "SMI-query"
    root = _queue_root(SMI_cfg)
    basename = f"{ticket_id}_{_safe_filename(title_hint)}"
    request_json_path = root / f"{basename}_request.json"
    request_md_path = root / f"{basename}_request.md"
    response_json_path = root / f"{basename}_response.json"
    response_md_path = root / f"{basename}_response.md"

    request_record = {
        "ticket_id": ticket_id,
        "created_utc": created_utc,
        "provider": str(SMI_cfg.get("provider") or "queue_only"),
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
        f"# {ticket_id} - SMI Query Request",
        "",
        f"- created_utc: {created_utc}",
        f"- provider: {request_record['provider']}",
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
    request_md_path.write_text("\n".join(request_md_lines).strip() + "\n", encoding="utf-8")

    answered = False
    answer = ""
    error = ""
    response_status = "queued"
    remote_response_id = ""
    credential_source = ""

    provider = str(SMI_cfg.get("provider") or "queue_only").strip().lower()
    if provider == "openai_responses":
        remote = _call_openai_responses(SMI_cfg, request_record)
        credential_source = _clean_text(remote.get("auth_source"), 280)
        if bool(remote.get("ok")):
            answered = True
            answer = _clean_text(remote.get("answer"), 24000)
            response_status = "completed"
            remote_response_id = _clean_text(remote.get("response_id"), 120)
        else:
            error = _clean_text(remote.get("error"), 1800)
            response_status = "queued"

    response_record = {
        "ticket_id": ticket_id,
        "created_utc": created_utc,
        "responded_utc": _now_utc(),
        "provider": provider,
        "status": response_status,
        "answered": answered,
        "answer": answer,
        "error": error,
        "remote_response_id": remote_response_id,
        "credential_source": credential_source,
    }
    response_json_path.write_text(json.dumps(response_record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    response_md_lines = [
        f"# {ticket_id} - SMI Query Response",
        "",
        f"- status: {response_status}",
        f"- answered: {answered}",
        f"- provider: {provider}",
        f"- responded_utc: {response_record['responded_utc']}",
    ]
    if remote_response_id:
        response_md_lines.append(f"- remote_response_id: {remote_response_id}")
    if credential_source:
        response_md_lines.append(f"- credential_source: {credential_source}")
    if error:
        response_md_lines.extend(["", "## Error", "", error])
    if answer:
        response_md_lines.extend(["", "## Answer", "", answer])
    if not answer and not error:
        response_md_lines.extend(["", "## Next Action", "", "Manual SMI handoff is required using this ticket."])
    response_md_path.write_text("\n".join(response_md_lines).strip() + "\n", encoding="utf-8")

    return {
        "ok": True,
        "ticket_id": ticket_id,
        "provider": provider,
        "status": response_status,
        "answered": answered,
        "answer": answer,
        "error": error,
        "credential_source": credential_source,
        "queue_dir": str(root),
        "request_json_path": str(request_json_path),
        "request_markdown_path": str(request_md_path),
        "response_json_path": str(response_json_path),
        "response_markdown_path": str(response_md_path),
        "next_action": (
            "SMI answered remotely."
            if answered
            else "Manual SMI handoff required. Share ticket_id with SMI if remote mode is unavailable."
        ),
    }


def list_SMI_queries(limit: int = 50) -> list[dict[str, Any]]:
    settings = get_settings()
    SMI_cfg = get_SMI_tunnel_settings(settings)
    root = _queue_root(SMI_cfg)
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
            "provider": str(request_obj.get("provider") or ""),
            "status": str(response_obj.get("status") or request_obj.get("status") or "queued"),
            "answered": bool(response_obj.get("answered", False)),
            "error": _clean_text(response_obj.get("error"), 600),
            "credential_source": str(response_obj.get("credential_source") or ""),
            "request_json_path": str(request_file),
            "response_json_path": str(response_file) if response_file.exists() else "",
        }
        records.append(item)
        if len(records) >= cap:
            break
    return records

