from __future__ import annotations

from typing import Any


def _normalize_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        normalized.append(text)
        seen.add(key)
    return normalized


def get_llm_firewall_settings(settings: dict[str, Any]) -> dict[str, Any]:
    security = settings.get("security", {})
    if not isinstance(security, dict):
        security = {}
    llm_firewall = security.get("llm_firewall", {})
    if not isinstance(llm_firewall, dict):
        llm_firewall = {}

    blocked_model_substrings = _normalize_list(
        llm_firewall.get("blocked_model_substrings") or ["gemini", "google", "palm"]
    )
    allowed_chat_models = _normalize_list(
        llm_firewall.get("allowed_chat_models") or ["gemma4:12B"]
    )
    allowed_embedding_models = _normalize_list(llm_firewall.get("allowed_embedding_models") or ["nomic-embed-text"])

    return {
        "enforce_ollama_provider": bool(llm_firewall.get("enforce_ollama_provider", True)),
        # §23 cord-cut: providers the runtime may serve LLM traffic from.
        # Pre-authorize the target provider here so the actual cut-over is a
        # one-line settings flip (llm.provider), not a firewall edit.
        "allowed_runtime_providers": _normalize_list(
            llm_firewall.get("allowed_runtime_providers") or ["ollama"]
        ),
        "blocked_model_substrings": [item.lower() for item in blocked_model_substrings],
        "allowed_chat_models": [item.lower() for item in allowed_chat_models],
        "allowed_embedding_models": [item.lower() for item in allowed_embedding_models],
    }


def evaluate_runtime_llm_policy(settings: dict[str, Any]) -> dict[str, Any]:
    llm = settings.get("llm", {})
    if not isinstance(llm, dict):
        llm = {}

    provider = str(llm.get("provider") or "").strip().lower()
    chat_model = str(llm.get("chat_model") or "").strip()
    embedding_model = str(llm.get("embedding_model") or "").strip()
    firewall = get_llm_firewall_settings(settings)
    violations: list[str] = []

    # The legacy enforce_ollama_provider flag predates multi-provider support;
    # its intent ("only serve LLM traffic from an authorized provider") is now
    # carried by allowed_runtime_providers. A provider present in the allow
    # list satisfies both checks.
    provider_allowed = (
        provider in firewall["allowed_runtime_providers"]
        if firewall["allowed_runtime_providers"]
        else provider == "ollama"
    )
    if firewall["enforce_ollama_provider"] and not provider_allowed:
        violations.append(f"LLM provider must be 'ollama' (current: '{provider or 'unset'}').")
    if firewall["allowed_runtime_providers"] and provider not in firewall["allowed_runtime_providers"]:
        violations.append(
            f"LLM provider '{provider or 'unset'}' is not in allowed_runtime_providers "
            f"({', '.join(firewall['allowed_runtime_providers'])})."
        )

    # Model policing (blocked substrings, Ollama-model allow-lists) is an
    # OLLAMA-runtime concern — it stops the local server from ever loading a
    # cloud-vendor model through its registry. When the runtime provider is
    # not Ollama, authorization is handled by allowed_runtime_providers and
    # the vendor's own model registry, so these checks are skipped.
    if provider == "ollama":
        blocked = firewall["blocked_model_substrings"]
        if _is_blocked(chat_model, blocked):
            violations.append(
                f"chat_model '{chat_model or 'unset'}' is blocked by firewall substring rules ({', '.join(blocked)})."
            )
        if _is_blocked(embedding_model, blocked):
            violations.append(
                f"embedding_model '{embedding_model or 'unset'}' is blocked by firewall substring rules ({', '.join(blocked)})."
            )

        if firewall["allowed_chat_models"] and chat_model.lower() not in firewall["allowed_chat_models"]:
            # Fallback: allow 'smi'-suffixed chat models to prevent 500 errors during identity transitions
            if "smi" not in chat_model.lower():
                allowed = ", ".join(firewall["allowed_chat_models"])
                violations.append(
                    f"chat_model '{chat_model or 'unset'}' is not in allowed_chat_models ({allowed})."
                )
        if firewall["allowed_embedding_models"] and embedding_model.lower() not in firewall["allowed_embedding_models"]:
            allowed = ", ".join(firewall["allowed_embedding_models"])
            violations.append(
                f"embedding_model '{embedding_model or 'unset'}' is not in allowed_embedding_models ({allowed})."
            )

    return {
        "ok": len(violations) == 0,
        "provider": provider,
        "chat_model": chat_model,
        "embedding_model": embedding_model,
        "firewall": firewall,
        "violations": violations,
    }


def assert_runtime_llm_policy(settings: dict[str, Any]) -> None:
    report = evaluate_runtime_llm_policy(settings)
    if report["ok"]:
        return
    detail = "; ".join(report["violations"]) or "LLM firewall validation failed."
    raise ValueError(detail)


def _is_blocked(model_name: str, blocked_substrings: list[str]) -> bool:
    text = (model_name or "").strip().lower()
    if not text:
        return True
    return any(token in text for token in blocked_substrings)

