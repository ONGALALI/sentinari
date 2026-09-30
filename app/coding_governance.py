import re
from typing import Any


DEFAULT_CHIEF_ENGINEER_NAME = "the user"
DEFAULT_CHIEF_ENGINEER_ROLE = "coding authority"
DEFAULT_OWNER_LABEL = "the user"
_CODING_INTENT_PATTERN = re.compile(
    r"\b("
    r"code|coding|patch|bug|fix|refactor|implement|implementation|script|sqlite|sql|python|powershell|"
    r"function|class|method|endpoint|api|compile|build|test|debug|stack trace|exception|migration"
    r")\b",
    re.IGNORECASE,
)


def normalize_coding_governance(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    chief_engineer_name = (
        str(source.get("chief_engineer_name") or DEFAULT_CHIEF_ENGINEER_NAME).strip() or DEFAULT_CHIEF_ENGINEER_NAME
    )
    chief_engineer_role = (
        str(source.get("chief_engineer_role") or DEFAULT_CHIEF_ENGINEER_ROLE).strip() or DEFAULT_CHIEF_ENGINEER_ROLE
    )
    owner_label = str(source.get("owner_label") or DEFAULT_OWNER_LABEL).strip() or DEFAULT_OWNER_LABEL
    coding_mode = str(source.get("coding_mode") or "advisory_only").strip().lower()
    if coding_mode not in {"advisory_only", "supervised_execute"}:
        coding_mode = "advisory_only"

    return {
        "chief_engineer_name": chief_engineer_name,
        "chief_engineer_role": chief_engineer_role,
        "owner_label": owner_label,
        "require_chief_engineer_consultation": bool(source.get("require_chief_engineer_consultation", False)),
        "require_owner_approval_for_code_changes": bool(
            source.get("require_owner_approval_for_code_changes", True)
        ),
        "allow_direct_code_changes": bool(source.get("allow_direct_code_changes", False)),
        "allow_shell_mutation": bool(source.get("allow_shell_mutation", False)),
        "coding_mode": coding_mode,
    }


def build_coding_governance_prompt_lines(governance: dict[str, Any] | None) -> list[str]:
    cfg = normalize_coding_governance(governance)
    chief = cfg["chief_engineer_name"]
    role = cfg["chief_engineer_role"]
    owner = cfg["owner_label"]

    lines = [
        "- For coding work, stay in supervised proposal mode unless an explicitly approved human-controlled execution path is active.",
        "- You may inspect, reason about, and propose code changes, but do not present them as applied or finalized on your own authority.",
    ]
    if bool(cfg.get("require_chief_engineer_consultation", True)):
        lines.append(f"- {chief} remains the {role}; consult {chief} before finalizing any patch, refactor, migration, or implementation decision.")
    if bool(cfg.get("require_owner_approval_for_code_changes", True)):
        lines.append(f"- Obtain explicit permission from {owner} before any code, configuration, or script mutation is approved for execution.")
    if not bool(cfg.get("allow_shell_mutation", False)):
        lines.append("- Do not use shell, file-write, or automation actions to mutate the workspace directly.")
    return lines


def build_coding_governance_capability_lines(governance: dict[str, Any] | None) -> list[str]:
    cfg = normalize_coding_governance(governance)
    chief = cfg["chief_engineer_name"]
    role = cfg["chief_engineer_role"]
    owner = cfg["owner_label"]

    lines = [
        "For coding work, I can inspect, explain, verify, and propose implementation plans.",
    ]
    if bool(cfg.get("require_chief_engineer_consultation", True)):
        lines.append(f"{chief} remains the {role}; I must consult {chief} before any implementation is finalized.")
    if bool(cfg.get("require_owner_approval_for_code_changes", True)):
        lines.append(f"I cannot approve or apply code, config, or script changes independently; {owner} must explicitly approve them first.")
    if not bool(cfg.get("allow_shell_mutation", False)):
        lines.append("Direct shell or file mutation is blocked for me.")
    return lines


def build_mutation_block_reason(governance: dict[str, Any] | None) -> str:
    cfg = normalize_coding_governance(governance)
    chief = cfg["chief_engineer_name"]
    role = cfg["chief_engineer_role"]
    owner = cfg["owner_label"]
    parts = ["Direct workspace mutation is blocked for Sentinari."]
    if bool(cfg.get("require_chief_engineer_consultation", True)):
        parts.append(f"Consult {chief}, the {role}, before any code change.")
    if bool(cfg.get("require_owner_approval_for_code_changes", True)):
        parts.append(f"Obtain explicit permission from {owner} before any code, config, or script change.")
    return " ".join(parts)


def build_runtime_coding_notice(governance: dict[str, Any] | None) -> str:
    cfg = normalize_coding_governance(governance)
    chief = cfg["chief_engineer_name"]
    owner = cfg["owner_label"]
    return (
        f"Coding governance: I can analyze and propose, but {chief} remains the coding authority and {owner} "
        "must approve any code, config, or script change before execution."
    )


def question_has_coding_intent(text: str) -> bool:
    return _CODING_INTENT_PATTERN.search(str(text or "")) is not None
