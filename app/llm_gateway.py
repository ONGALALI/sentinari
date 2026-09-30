"""Provider-agnostic LLM gateway for Sentinari.

Zero-cloud doctrine (§41, reaffirmed §45): the only supported runtime today is
the local Ollama server; the local Sentinari ONNX inference server (:8100) joins
via the 'sentinari' provider on rig day. The former Gemini cloud provider and
the generic OpenAI-compatible provider were REMOVED in §45 — the gateway keeps
its provider registry shape so the local :8100 provider can slot in without
touching any caller.

The rest of the app calls ``llm_gateway.chat()`` / ``llm_gateway.embed()``
without knowing (or caring) where the model lives. Switching providers is a
settings change, not a code change — but the firewall (app/llm_firewall.py)
polices which providers are authorized at all.

Provider config lives in ``config/settings.yaml`` under ``llm.provider``:

    llm:
      provider: ollama            # ollama | http_json_provider (local only)
      base_url: http://127.0.0.1:11434
      chat_model: gemma4:12B
      embedding_model: nomic-embed-text
    # http_json_provider:
    #   base_url: http://127.0.0.1:9000/v1
    #   chat_model: <local model>
    #   api_key_env: <optional, for a local key only>
    # runtime_llm:
    #   client_backend: gateway     # ollama_client | gateway

API keys are read from environment variables only — never hard-coded.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from .config import get_settings

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.S)


class LLMGatewayError(RuntimeError):
    """Raised when no configured provider can serve the request."""


def _settings_llm() -> dict[str, Any]:
    settings = get_settings()
    llm = settings.get("llm") if isinstance(settings, dict) else {}
    return dict(llm or {})


def _env_key(env_var: str) -> str:
    """Read an API key from the environment, falling back to the project .env.

    Only ever used for LOCAL endpoints (e.g. a local proxy that issues its own
    keys). Cloud vendors cannot be configured through this gateway anymore.
    """
    value = str(os.environ.get(str(env_var or "")) or "").strip()
    if value:
        return value
    try:
        from .config import get_project_root

        env_file = get_project_root().parent / ".env"
        if not env_file.exists():
            env_file = get_project_root() / ".env"
        if env_file.exists():
            prefix = f"{env_var}="
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith(prefix):
                    return line[len(prefix):].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


class OllamaProvider:
    """Local Ollama server (current default)."""

    name = "ollama"

    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = str(config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
        self.chat_model = str(config.get("chat_model") or "")
        self.embedding_model = str(config.get("embedding_model") or "")
        self.timeout = max(10, int(config.get("chat_timeout_seconds") or 120))

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.chat_model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=self.timeout,
        )
        if resp.status_code == 400 and "think" in str(resp.text or "").lower():
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.chat_model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=self.timeout,
            )
        resp.raise_for_status()
        data = resp.json() or {}
        return str((data.get("message") or {}).get("content") or "").strip()

    def embed(self, text: str) -> list[float] | None:
        if not self.embedding_model:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.embedding_model, "prompt": str(text or "")[:8000]},
                timeout=30,
            )
            resp.raise_for_status()
            embedding = (resp.json() or {}).get("embedding")
            return list(embedding) if isinstance(embedding, list) else None
        except Exception:
            return None


class HTTPJSONProvider:
    """Any local HTTP JSON endpoint speaking the OpenAI chat wire format.

    Renamed from openai_compatible (§45): the name described a wire format,
    not a vendor. Use it only for endpoints on this machine or the LAN —
    the zero-cloud doctrine forbids pointing it at a cloud vendor.
    """

    name = "http_json_provider"

    def __init__(self, config: dict[str, Any]) -> None:
        compatible = dict(config.get("http_json_provider") or {})
        self.base_url = str(compatible.get("base_url") or "").rstrip("/")
        self.api_key = _env_key(str(compatible.get("api_key_env") or ""))
        self.chat_model = str(compatible.get("chat_model") or config.get("chat_model") or "")
        self.embedding_model = str(compatible.get("embedding_model") or "")
        self.timeout = max(10, int(config.get("chat_timeout_seconds") or 120))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def is_available(self) -> bool:
        return bool(self.base_url and self.chat_model)

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.chat_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("message") or {}).get("content") or "").strip()

    def embed(self, text: str) -> list[float] | None:
        if not self.base_url or not self.embedding_model:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json={"model": self.embedding_model, "input": str(text or "")[:8000]},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            embedding = ((data.get("data") or [{}])[0]).get("embedding")
            return [float(v) for v in embedding] if isinstance(embedding, list) else None
        except Exception:
            return None


_PROVIDERS: dict[str, type] = {
    "ollama": OllamaProvider,
    "http_json_provider": HTTPJSONProvider,
}


class LLMGateway:
    """Single entry point: chat() and embed() on any configured provider."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config) if config else _settings_llm()
        self.provider_name = str(self.config.get("provider") or "ollama").strip().lower()
        provider_cls = _PROVIDERS.get(self.provider_name, OllamaProvider)
        self.provider = provider_cls(self.config)
        self._fallbacks: list[Any] = []
        for fallback_name in self.config.get("fallback_providers") or []:
            fallback_cls = _PROVIDERS.get(str(fallback_name).strip().lower())
            if fallback_cls is not None:
                self._fallbacks.append(fallback_cls(self.config))

    # -- introspection ------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.provider.name,
            "available": self.provider.is_available(),
            "chat_model": getattr(self.provider, "chat_model", ""),
            "embedding_model": getattr(self.provider, "embedding_model", ""),
            "provider_cut_from_ollama": self.provider.name != "ollama",
        }

    # -- core operations ----------------------------------------------------

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        attempts: list[Any] = [self.provider, *self._fallbacks]
        last_error: Exception | None = None
        for provider in attempts:
            if not provider.is_available():
                continue
            try:
                return provider.chat(messages, temperature=temperature, max_tokens=max_tokens)
            except Exception as ex:  # try the next provider
                last_error = ex
        if last_error is not None:
            raise LLMGatewayError(f"All LLM providers failed; last error: {last_error}")
        raise LLMGatewayError(
            f"No LLM provider available (configured: {self.provider.name}). "
            "Check the provider settings and API keys."
        )

    def embed(self, text: str) -> list[float] | None:
        for provider in [self.provider, *self._fallbacks]:
            embedding = provider.embed(text)
            if embedding:
                return embedding
        return None

    # -- structured output --------------------------------------------------

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 1024) -> Any:
        """Chat and parse a JSON object/array out of the reply."""
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return parse_json_loose(raw)


def parse_json_loose(raw: str) -> Any:
    """Extract JSON from a model reply that may include prose or fences."""
    text = str(raw or "").strip()
    if not text:
        raise LLMGatewayError("Model returned an empty reply.")
    if "```" in text:
        fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fenced:
            text = fenced[0].strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = _JSON_OBJECT_RE.search(text) or _JSON_ARRAY_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    raise LLMGatewayError("Model reply did not contain parseable JSON.")


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    """Process-wide gateway instance (re-reads settings on first use)."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


def reset_gateway() -> None:
    """Force the next get_gateway() to reload settings (used after config edits)."""
    global _gateway
    _gateway = None


class GatewayBackedClient:
    """Drop-in replacement for OllamaClient, backed by the provider gateway.

    Implements the exact client surface the app consumes — chat(), embed(),
    is_available(), list_models(), get_runtime_diagnostics() — so callers
    (conversation, ingestion, playground, session_memory) need no changes
    when Sentinari's LLM moves to a different local provider.

    The diagnostics payload keeps the Ollama-runtime shape (the UI renders
    it) but honestly reports the gateway's real provider and models.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._gateway = LLMGateway(config)
        self.provider_name = self._gateway.provider_name
        self.chat_model = str(getattr(self._gateway.provider, "chat_model", "") or "")
        self.embedding_model = str(getattr(self._gateway.provider, "embedding_model", "") or "")
        self.base_url = str(getattr(self._gateway.provider, "base_url", "") or getattr(self._gateway.provider, "base", "") or "")
        self.temperature = float(self._gateway.config.get("temperature") or 0.1)
        self.max_output_tokens = int(self._gateway.config.get("max_output_tokens") or 768)
        self.num_ctx = int(self._gateway.config.get("num_ctx") or 8192)

    # -- capability ----------------------------------------------------------

    def is_available(self) -> bool:
        try:
            return bool(self._gateway.provider.is_available())
        except Exception:
            return False

    def list_models(self) -> list[str]:
        provider = self._gateway.provider
        models = [self.chat_model]
        models.extend(getattr(provider, "chat_fallback_models", []) or [])
        if self.embedding_model:
            models.append(self.embedding_model)
        seen: set[str] = set()
        return [m for m in models if m and not (m in seen or seen.add(m))]

    # -- core operations -------------------------------------------------

    def chat(self, messages: list[dict[str, str]], *, num_ctx: int | None = None) -> str:
        # num_ctx is an Ollama-specific window hint; other providers manage
        # their own context. Temperature/max tokens come from settings.
        return self._gateway.chat(
            messages,
            temperature=self.temperature,
            max_tokens=self.max_output_tokens,
        )

    def embed(self, text: str) -> list[float] | None:
        return self._gateway.embed(text)

    # -- diagnostics -----------------------------------------------------

    def get_runtime_diagnostics(self, *, probe: bool = True) -> dict[str, Any]:
        describe = self._gateway.describe()
        return {
            "base_url": self.base_url or f"gateway:{self.provider_name}",
            "reachable": bool(describe.get("available")),
            "ready": bool(describe.get("available")),
            "requires_attention": not bool(describe.get("available")),
            "chat_model": self.chat_model,
            "embedding_model": self.embedding_model,
            "available_models": self.list_models(),
            "chat_model_present": bool(self.chat_model),
            "embedding_model_present": bool(self.embedding_model),
            "chat_capabilities": ["chat"],
            "embedding_capabilities": ["embedding"] if self.embedding_model else [],
            "chat_transport": f"gateway:{self.provider_name}",
            "warnings": [],
            "operator_trigger": "",
            "provider": self.provider_name,
            "gateway_provider_cut_from_ollama": self.provider_name != "ollama",
        }
