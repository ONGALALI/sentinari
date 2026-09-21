"""Provider-agnostic LLM gateway for Sentinel.

Today Sentinel talks straight to a local Ollama server. This gateway cuts the
umbilical cord: the rest of the app calls ``llm_gateway.chat()`` /
``llm_gateway.embed()`` without knowing (or caring) whether the model lives in
local Ollama, Google Gemini, an OpenAI-compatible endpoint, or any future
provider. Switching providers is a settings change, not a code change.

Provider config lives in ``config/settings.yaml`` under ``llm.provider``:

    llm:
      provider: ollama            # ollama | gemini | openai_compatible
      base_url: http://127.0.0.1:11434
      chat_model: gemma4:12B
      embedding_model: nomic-embed-text
    # gemini:
    #   api_key_env: GEMINI_API_KEY        (key itself stays in .env)
    #   chat_model: gemini-2.5-flash
    #   embedding_model: text-embedding-004

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

    The app does not load .env automatically, so providers that keep their key
    there (like the user's OpenAlex/Gemini setup) still resolve.
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


class GeminiProvider:
    """Google Gemini via the generative REST API (cloud)."""

    name = "gemini"

    def __init__(self, config: dict[str, Any]) -> None:
        gemini = dict(config.get("gemini") or {})
        self.api_key = _env_key(str(gemini.get("api_key_env") or "GEMINI_API_KEY"))
        # Gemini model names never inherit the global chat_model — that holds
        # the Ollama model (e.g. "gemma4:12B"), which Gemini would reject.
        # "gemini-flash-latest" is Google's rolling alias for the current
        # flash model — it does not age out the way gemini-2.0/2.5 did.
        self.chat_model = str(gemini.get("chat_model") or "gemini-flash-latest")
        self.embedding_model = str(gemini.get("embedding_model") or "text-embedding-004")
        self.timeout = max(10, int(config.get("chat_timeout_seconds") or 120))
        self.base = "https://generativelanguage.googleapis.com/v1beta"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 768) -> str:
        import time as _time

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self._chat_once(messages, temperature=temperature, max_tokens=max_tokens)
            except requests.HTTPError as ex:
                status = getattr(ex.response, "status_code", 0)
                # 429/5xx are transient cloud throttling — back off and retry.
                if status not in (429, 500, 503, 504) or attempt == 2:
                    raise
                last_error = ex
                _time.sleep(2.0 * (attempt + 1))
        if last_error is not None:
            raise last_error
        raise LLMGatewayError("Gemini chat failed after retries.")

    def _chat_once(self, messages: list[dict[str, str]], *, temperature: float, max_tokens: int) -> str:
        system_text = "\n".join(
            str(m.get("content") or "") for m in messages if str(m.get("role") or "") == "system"
        ).strip()
        contents = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "").strip()
            if not content or role == "system":
                continue
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": content}],
                }
            )
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                # Structured extraction does not need hidden reasoning; without
                # this the thinking budget consumes maxOutputTokens and the
                # reply comes back empty.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        resp = requests.post(
            f"{self.base}/models/{self.chat_model}:generateContent",
            params={"key": self.api_key},
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return " ".join(str(part.get("text") or "") for part in parts).strip()

    def embed(self, text: str) -> list[float] | None:
        if not self.api_key or not self.embedding_model:
            return None
        try:
            resp = requests.post(
                f"{self.base}/models/{self.embedding_model}:embedContent",
                params={"key": self.api_key},
                json={"content": {"parts": [{"text": str(text or "")[:8000]}]}},
                timeout=30,
            )
            resp.raise_for_status()
            values = ((resp.json() or {}).get("embedding") or {}).get("values")
            return [float(v) for v in values] if isinstance(values, list) else None
        except Exception:
            return None


class OpenAICompatibleProvider:
    """Any OpenAI-compatible endpoint (vLLM, LM Studio, OpenRouter, ...)."""

    name = "openai_compatible"

    def __init__(self, config: dict[str, Any]) -> None:
        compatible = dict(config.get("openai_compatible") or {})
        self.base_url = str(compatible.get("base_url") or "").rstrip("/")
        self.api_key = _env_key(str(compatible.get("api_key_env") or "OPENAI_API_KEY"))
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
    "gemini": GeminiProvider,
    "openai_compatible": OpenAICompatibleProvider,
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
