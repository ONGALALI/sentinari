from __future__ import annotations

import hmac
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coding_governance import build_mutation_block_reason, normalize_coding_governance


DEFAULT_WORKFLOW_STEPS = [
    "assess",
    "plan",
    "approve",
    "execute",
    "verify",
    "close",
]

DEFAULT_ALLOWED_COMMAND_PREFIXES = [
    "Get-ChildItem",
    "Get-Content",
    "Select-String",
    "rg",
    "Get-Process",
    "Get-Service",
    "Get-Location",
    "Test-Path",
    "Resolve-Path",
    "git status",
    "git diff",
    "git show",
    "dotnet --info",
    "dotnet build",
    "dotnet test",
    "npm --version",
    "python --version",
]

DEFAULT_BLOCKED_TOKENS = [
    "remove-item",
    "del ",
    "erase ",
    "rmdir",
    "rd ",
    "format ",
    "shutdown",
    "restart-computer",
    "stop-computer",
    "invoke-expression",
    "iex ",
    "start-process",
    "stop-process",
    "taskkill",
    "sc stop",
    "git reset --hard",
    "git checkout --",
    "git clean -fd",
]

DEFAULT_BLOCKED_PATH_TOKENS = [
    "config/settings.yaml",
    "config/settings.example.yaml",
    "start_smi.ps1",
    "stop_smi.ps1",
    "status_smi.ps1",
    "launch_smi_only.ps1",
]

MUTATION_HINT_TOKENS = [
    "set-content",
    "add-content",
    "out-file",
    "copy-item",
    "move-item",
    "rename-item",
    "new-item",
    "clear-content",
    "git commit",
    "git push",
    "git merge",
    "git rebase",
]

DESTRUCTIVE_HINT_TOKENS = [
    "remove-item",
    "del ",
    "erase ",
    "rmdir",
    "rd ",
    "format ",
    "shutdown",
    "restart-computer",
    "stop-computer",
    "taskkill",
    "stop-process",
    "git reset --hard",
    "git checkout --",
    "git clean -fd",
]

ABS_PATH_PATTERN = re.compile(r'([A-Za-z]:[\\/][^"\r\n\t|><;&]+)')
REL_PATH_PATTERN = re.compile(r'((?:\.\.?)[\\/][^"\r\n\t|><;&]+)')
MULTI_STATEMENT_PATTERN = re.compile(r"(?:[\r\n;]|&&|\|\|)")
REDIRECT_PATTERN = re.compile(r"(?<![<>=])>>(?!>)|(?<![<>=])>(?!>)")

WORKFLOW_STATE: dict[str, dict[str, Any]] = {}
WORKFLOW_LOCK = threading.Lock()


def _env_flag(name: str, fallback: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return fallback
    return raw in {"1", "true", "yes", "on"}


def _normalize_text_list(raw: Any, defaults: list[str], *, lower: bool = False) -> list[str]:
    values = raw if isinstance(raw, list) else defaults
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key if lower else value)
    return normalized


def _resolve_path(text: str, project_root: Path) -> Path:
    path = Path(text)
    if not path.is_absolute():
        path = (project_root / path).resolve()
    else:
        path = path.resolve()
    return path


def _normalize_path_list(raw: Any, defaults: list[str], project_root: Path) -> list[Path]:
    values = raw if isinstance(raw, list) else defaults
    normalized: list[Path] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        if not value:
            continue
        try:
            path = _resolve_path(value, project_root)
        except Exception:
            continue
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(path)
    return normalized


def _is_under_root(candidate: Path, root: Path) -> bool:
    candidate_norm = os.path.normcase(str(candidate))
    root_norm = os.path.normcase(str(root))
    if candidate_norm == root_norm:
        return True
    return candidate_norm.startswith(root_norm + os.sep)


def _extract_candidate_paths(command: str, project_root: Path) -> list[Path]:
    values: list[str] = []
    values.extend(match.group(1) for match in ABS_PATH_PATTERN.finditer(command))
    values.extend(match.group(1) for match in REL_PATH_PATTERN.finditer(command))

    normalized: list[Path] = []
    seen: set[str] = set()
    for raw in values:
        try:
            path = _resolve_path(raw, project_root)
        except Exception:
            continue
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(path)
    return normalized


def _normalize_command(command: str) -> str:
    return re.sub(r"\s+", " ", command or "").strip()


def _contains_token(text: str, token: str) -> bool:
    value = str(token or "").strip().lower()
    if not value:
        return False
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])"
    return re.search(pattern, text.lower()) is not None


def _matches_allowed_prefix(command: str, allowed_prefixes: list[str]) -> bool:
    normalized = _normalize_command(command).lower()
    if not normalized:
        return False
    for prefix in allowed_prefixes:
        token = str(prefix or "").strip().lower()
        if not token:
            continue
        if normalized == token or normalized.startswith(token + " "):
            return True
    return False


def _detect_operation(command: str) -> str:
    lowered = command.lower()
    if REDIRECT_PATTERN.search(command):
        return "mutation"
    if any(_contains_token(lowered, token) for token in DESTRUCTIVE_HINT_TOKENS):
        return "destructive"
    if any(_contains_token(lowered, token) for token in MUTATION_HINT_TOKENS):
        return "mutation"
    return "read"


def get_shell_policy(settings: dict[str, Any], project_root: Path) -> dict[str, Any]:
    security = settings.get("security", {})
    if not isinstance(security, dict):
        security = {}
    raw = security.get("shell_policy", {})
    if not isinstance(raw, dict):
        raw = {}
    coding_governance = normalize_coding_governance(security.get("coding_governance"))

    operation_mode = str(raw.get("operation_mode") or "propose_only").strip().lower()
    if operation_mode not in {"propose_only", "read_only", "guarded_execute"}:
        operation_mode = "propose_only"

    workflow_steps = _normalize_text_list(raw.get("workflow_steps"), DEFAULT_WORKFLOW_STEPS, lower=True)
    if not workflow_steps:
        workflow_steps = list(DEFAULT_WORKFLOW_STEPS)

    allowed_prefixes = _normalize_text_list(
        raw.get("allowed_command_prefixes"),
        DEFAULT_ALLOWED_COMMAND_PREFIXES,
        lower=False,
    )
    blocked_tokens = _normalize_text_list(raw.get("blocked_tokens"), DEFAULT_BLOCKED_TOKENS, lower=True)
    blocked_path_tokens = _normalize_text_list(raw.get("blocked_path_tokens"), DEFAULT_BLOCKED_PATH_TOKENS, lower=True)

    settings_paths = settings.get("paths", {}) if isinstance(settings.get("paths"), dict) else {}
    configured_protected = settings_paths.get("protected_dirs") if isinstance(settings_paths.get("protected_dirs"), list) else []
    default_protected = [
        "./app",
        "./config",
        "./scripts",
        "./templates",
    ]
    protected_roots = _normalize_path_list(
        list(configured_protected) + list(default_protected) + list(raw.get("extra_protected_roots") or []),
        [],
        project_root,
    )
    allowed_write_roots = _normalize_path_list(
        raw.get("allowed_write_roots"),
        ["./data/shell_sandbox"],
        project_root,
    )

    approval_env = str(raw.get("approval_env") or "SMI_SHELL_APPROVAL_TOKEN").strip() or "SMI_SHELL_APPROVAL_TOKEN"
    kill_switch_env = str(raw.get("kill_switch_env") or "SMI_SHELL_KILL_SWITCH").strip() or "SMI_SHELL_KILL_SWITCH"

    max_timeout = int(raw.get("max_timeout_seconds") or 90)
    max_timeout = max(5, min(300, max_timeout))
    max_command_length = int(raw.get("max_command_length") or 1200)
    max_command_length = max(120, min(8000, max_command_length))

    audit_log_path = _resolve_path(str(raw.get("audit_log_path") or "./data/logs/shell_tool_audit.jsonl"), project_root)

    return {
        "enabled": bool(raw.get("enabled", True)),
        "operation_mode": operation_mode,
        "require_admin_auth": bool(raw.get("require_admin_auth", True)),
        "enforce_workflow_sequence": bool(raw.get("enforce_workflow_sequence", True)),
        "allow_multi_statement": bool(raw.get("allow_multi_statement", False)),
        "allow_read_on_protected_paths": bool(raw.get("allow_read_on_protected_paths", True)),
        "require_approval_for_mutation": bool(raw.get("require_approval_for_mutation", True)),
        "approval_env": approval_env,
        "kill_switch_env": kill_switch_env,
        "kill_switch_active": _env_flag(kill_switch_env, bool(raw.get("kill_switch", False))),
        "max_timeout_seconds": max_timeout,
        "max_command_length": max_command_length,
        "workflow_steps": workflow_steps,
        "allowed_command_prefixes": allowed_prefixes,
        "blocked_tokens": blocked_tokens,
        "blocked_path_tokens": blocked_path_tokens,
        "protected_roots": protected_roots,
        "allowed_write_roots": allowed_write_roots,
        "audit_log_path": audit_log_path,
        "coding_governance": coding_governance,
    }


def get_public_shell_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(policy.get("enabled", True)),
        "operation_mode": str(policy.get("operation_mode") or "propose_only"),
        "require_admin_auth": bool(policy.get("require_admin_auth", True)),
        "enforce_workflow_sequence": bool(policy.get("enforce_workflow_sequence", True)),
        "allow_multi_statement": bool(policy.get("allow_multi_statement", False)),
        "allow_read_on_protected_paths": bool(policy.get("allow_read_on_protected_paths", True)),
        "require_approval_for_mutation": bool(policy.get("require_approval_for_mutation", True)),
        "approval_env": str(policy.get("approval_env") or ""),
        "kill_switch_env": str(policy.get("kill_switch_env") or ""),
        "kill_switch_active": bool(policy.get("kill_switch_active", False)),
        "max_timeout_seconds": int(policy.get("max_timeout_seconds") or 90),
        "max_command_length": int(policy.get("max_command_length") or 1200),
        "workflow_steps": list(policy.get("workflow_steps") or []),
        "allowed_command_prefixes": list(policy.get("allowed_command_prefixes") or []),
        "blocked_tokens": list(policy.get("blocked_tokens") or []),
        "blocked_path_tokens": list(policy.get("blocked_path_tokens") or []),
        "protected_roots": [str(path) for path in (policy.get("protected_roots") or [])],
        "allowed_write_roots": [str(path) for path in (policy.get("allowed_write_roots") or [])],
        "audit_log_path": str(policy.get("audit_log_path") or ""),
        "coding_governance": normalize_coding_governance(policy.get("coding_governance")),
    }


def reset_workflow_state(session_id: str) -> bool:
    key = (session_id or "").strip()
    if not key:
        return False
    with WORKFLOW_LOCK:
        existed = key in WORKFLOW_STATE
        WORKFLOW_STATE.pop(key, None)
    return existed


def _validate_workflow_transition(
    policy: dict[str, Any],
    session_id: str,
    workflow_step: str,
) -> tuple[bool, str, dict[str, Any]]:
    key = (session_id or "").strip()
    if not key:
        return False, "session_id is required for workflow-sequenced mutation commands.", {}

    step = (workflow_step or "").strip().lower()
    steps = [str(item).strip().lower() for item in (policy.get("workflow_steps") or []) if str(item).strip()]
    if not step:
        return False, "workflow_step is required for workflow-sequenced mutation commands.", {}
    if step not in steps:
        return (
            False,
            "workflow_step is not in policy workflow sequence.",
            {"workflow_step": step, "allowed_workflow_steps": steps},
        )

    requested_idx = steps.index(step)
    with WORKFLOW_LOCK:
        state = WORKFLOW_STATE.get(key, {"index": -1, "step": ""})
        current_idx = int(state.get("index", -1))
        current_step = str(state.get("step") or "")

        if requested_idx > current_idx + 1:
            expected_step = steps[current_idx + 1] if current_idx + 1 < len(steps) else steps[-1]
            return (
                False,
                "workflow_step skipped sequence order.",
                {
                    "session_id": key,
                    "current_step": current_step,
                    "requested_step": step,
                    "expected_next_step": expected_step,
                    "allowed_workflow_steps": steps,
                },
            )

        if requested_idx < current_idx:
            return (
                False,
                "workflow_step attempted to rewind sequence order.",
                {
                    "session_id": key,
                    "current_step": current_step,
                    "requested_step": step,
                    "allowed_workflow_steps": steps,
                },
            )

        if requested_idx > current_idx:
            WORKFLOW_STATE[key] = {
                "index": requested_idx,
                "step": step,
                "updated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
            }
        snapshot = dict(WORKFLOW_STATE.get(key) or {})

    return True, "workflow sequence accepted.", snapshot


def evaluate_shell_request(
    command: str,
    policy: dict[str, Any],
    project_root: Path,
    *,
    session_id: str | None = None,
    workflow_step: str | None = None,
    approval_token: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_command(command)
    lowered = normalized.lower()

    if not normalized:
        return {"allowed": False, "execute": False, "status_code": 400, "reason": "command is required."}
    if not bool(policy.get("enabled", True)):
        return {"allowed": False, "execute": False, "status_code": 403, "reason": "Shell policy is disabled."}
    if bool(policy.get("kill_switch_active", False)):
        return {"allowed": False, "execute": False, "status_code": 403, "reason": "Shell kill switch is active."}
    if len(normalized) > int(policy.get("max_command_length") or 1200):
        return {
            "allowed": False,
            "execute": False,
            "status_code": 400,
            "reason": f"Command exceeds max length ({int(policy.get('max_command_length') or 1200)}).",
        }
    if not bool(policy.get("allow_multi_statement", False)) and MULTI_STATEMENT_PATTERN.search(command):
        return {
            "allowed": False,
            "execute": False,
            "status_code": 403,
            "reason": "Multi-statement shell commands are blocked by policy.",
        }
    for token in policy.get("blocked_tokens") or []:
        key = str(token or "").strip().lower()
        if key and _contains_token(lowered, key):
            return {
                "allowed": False,
                "execute": False,
                "status_code": 403,
                "reason": f"Command blocked by policy token: {key}",
            }
    for token in policy.get("blocked_path_tokens") or []:
        key = str(token or "").strip().lower()
        if key and key in lowered:
            return {
                "allowed": False,
                "execute": False,
                "status_code": 403,
                "reason": f"Command references blocked path token: {key}",
            }

    operation = _detect_operation(normalized)
    if operation == "destructive":
        return {"allowed": False, "execute": False, "status_code": 403, "reason": "Destructive command category blocked."}

    mode = str(policy.get("operation_mode") or "propose_only")
    coding_governance = normalize_coding_governance(policy.get("coding_governance"))
    if operation == "mutation" and (
        not bool(coding_governance.get("allow_direct_code_changes", False))
        or not bool(coding_governance.get("allow_shell_mutation", False))
    ):
        return {
            "allowed": False,
            "execute": False,
            "status_code": 403,
            "reason": build_mutation_block_reason(coding_governance),
            "operation": operation,
            "policy_mode": mode,
        }

    if not _matches_allowed_prefix(normalized, list(policy.get("allowed_command_prefixes") or [])):
        return {
            "allowed": False,
            "execute": False,
            "status_code": 403,
            "reason": "Command prefix is not in allowlist.",
        }

    paths = _extract_candidate_paths(normalized, project_root)
    path_strings = [str(path) for path in paths]
    protected_roots = list(policy.get("protected_roots") or [])
    protected_hits = [str(path) for path in paths if any(_is_under_root(path, root) for root in protected_roots)]

    if operation == "mutation":
        if mode == "read_only":
            return {
                "allowed": False,
                "execute": False,
                "status_code": 403,
                "reason": "Mutation commands are blocked in read_only mode.",
                "operation": operation,
                "policy_mode": mode,
                "paths": path_strings,
            }

        if not paths:
            return {
                "allowed": False,
                "execute": False,
                "status_code": 403,
                "reason": "Mutation command must include explicit target paths.",
                "operation": operation,
                "policy_mode": mode,
            }

        if protected_hits:
            return {
                "allowed": False,
                "execute": False,
                "status_code": 403,
                "reason": "Mutation command targets protected path(s).",
                "operation": operation,
                "policy_mode": mode,
                "protected_path_hits": protected_hits,
            }

        allowed_write_roots = list(policy.get("allowed_write_roots") or [])
        outside_write_roots = [
            str(path)
            for path in paths
            if not any(_is_under_root(path, root) for root in allowed_write_roots)
        ]
        if outside_write_roots:
            return {
                "allowed": False,
                "execute": False,
                "status_code": 403,
                "reason": "Mutation command targets path(s) outside allowed write roots.",
                "operation": operation,
                "policy_mode": mode,
                "outside_allowed_write_roots": outside_write_roots,
                "allowed_write_roots": [str(path) for path in allowed_write_roots],
            }

    if operation == "read" and protected_hits and not bool(policy.get("allow_read_on_protected_paths", True)):
        return {
            "allowed": False,
            "execute": False,
            "status_code": 403,
            "reason": "Reads on protected paths are blocked by policy.",
            "operation": operation,
            "policy_mode": mode,
            "protected_path_hits": protected_hits,
        }

    workflow_state: dict[str, Any] = {}
    if operation == "mutation" and bool(policy.get("enforce_workflow_sequence", True)):
        ok, detail, snapshot = _validate_workflow_transition(
            policy,
            session_id or "",
            workflow_step or "",
        )
        if not ok:
            return {
                "allowed": False,
                "execute": False,
                "status_code": 409,
                "reason": detail,
                "operation": operation,
                "policy_mode": mode,
                "workflow": snapshot,
            }
        workflow_state = snapshot

    if operation == "mutation" and bool(policy.get("require_approval_for_mutation", True)) and mode == "guarded_execute":
        approval_env = str(policy.get("approval_env") or "SMI_SHELL_APPROVAL_TOKEN")
        expected = (os.environ.get(approval_env) or "").strip()
        provided = (approval_token or "").strip()
        if not expected:
            return {
                "allowed": False,
                "execute": False,
                "status_code": 403,
                "reason": f"Mutation approval token is not configured. Set environment variable {approval_env}.",
                "operation": operation,
                "policy_mode": mode,
            }
        if not provided or not hmac.compare_digest(provided, expected):
            return {
                "allowed": False,
                "execute": False,
                "status_code": 403,
                "reason": "Mutation approval token is missing or invalid.",
                "operation": operation,
                "policy_mode": mode,
            }

    if dry_run:
        return {
            "allowed": True,
            "execute": False,
            "status_code": 200,
            "reason": "Dry-run requested; command accepted but not executed.",
            "operation": operation,
            "policy_mode": mode,
            "paths": path_strings,
            "workflow": workflow_state,
        }

    if mode == "propose_only":
        return {
            "allowed": True,
            "execute": False,
            "status_code": 200,
            "reason": "Policy mode is propose_only; command execution suppressed.",
            "operation": operation,
            "policy_mode": mode,
            "paths": path_strings,
            "workflow": workflow_state,
        }

    return {
        "allowed": True,
        "execute": True,
        "status_code": 200,
        "reason": "Command approved by shell policy.",
        "operation": operation,
        "policy_mode": mode,
        "paths": path_strings,
        "workflow": workflow_state,
    }


def append_shell_audit_event(policy: dict[str, Any], event: dict[str, Any]) -> None:
    path = policy.get("audit_log_path")
    if not isinstance(path, Path):
        return
    record = dict(event)
    record.setdefault("timestamp_utc", datetime.now(tz=timezone.utc).isoformat())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")
    except Exception:
        # Auditing must not break the API path.
        return


def ensure_shell_policy_dirs(policy: dict[str, Any]) -> None:
    for path in policy.get("allowed_write_roots") or []:
        if isinstance(path, Path):
            path.mkdir(parents=True, exist_ok=True)

    audit_path = policy.get("audit_log_path")
    if isinstance(audit_path, Path):
        audit_path.parent.mkdir(parents=True, exist_ok=True)
