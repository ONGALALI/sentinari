from __future__ import annotations

from typing import Any

import requests


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        chat_model: str,
        embedding_model: str,
        temperature: float = 0.7,
        num_ctx: int = 1024,
        chat_timeout_seconds: int = 60,
        embed_timeout_seconds: int = 20,
        max_output_tokens: int = 256,
        num_gpu: int | None = None,
        keep_alive: str | None = "30m",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.temperature = temperature
        self.num_ctx = max(512, int(num_ctx or 4096))
        self.chat_timeout_seconds = max(5, int(chat_timeout_seconds or 45))
        self.embed_timeout_seconds = max(5, int(embed_timeout_seconds or 20))
        self.max_output_tokens = max(64, int(max_output_tokens or 256))
        if num_gpu is None:
            self.num_gpu = None
        else:
            parsed_num_gpu = int(num_gpu)
            self.num_gpu = parsed_num_gpu if parsed_num_gpu >= 0 else None
        keep_alive_text = str(keep_alive or "").strip()
        self.keep_alive = keep_alive_text or None
        self._capability_cache: dict[str, set[str]] = {}

    @staticmethod
    def _supports_chat_transport(capabilities: set[str]) -> bool:
        normalized = {
            str(item or "").strip().lower()
            for item in capabilities
            if str(item or "").strip()
        }
        # Some Ollama builds expose tool-capable message chat via /api/chat but
        # report only "completion" and "tools" from /api/show.
        return "chat" in normalized or "tools" in normalized

    def _build_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self.temperature,
            "num_ctx": self.num_ctx,
            "num_predict": self.max_output_tokens,
        }
        if self.num_gpu is not None:
            options["num_gpu"] = self.num_gpu
        return options

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=4)
            return resp.ok
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=6)
            if not resp.ok:
                return []
            data = resp.json() or {}
            models = data.get("models")
            if not isinstance(models, list):
                return []
            names: list[str] = []
            seen: set[str] = set()
            for item in models:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                names.append(name)
                seen.add(key)
            return names
        except Exception:
            return []

    def embed(self, text: str) -> list[float] | None:
        payload = {
            "model": self.embedding_model,
            "prompt": text,
        }
        try:
            resp = requests.post(f"{self.base_url}/api/embeddings", json=payload, timeout=self.embed_timeout_seconds)
            if not resp.ok:
                return None
            data = resp.json() or {}
            vec = data.get("embedding")
            if isinstance(vec, list) and vec:
                return [float(x) for x in vec]
        except Exception:
            return None
        return None

    def _get_capabilities(self, model: str) -> set[str]:
        key = str(model or "").strip().lower()
        if not key:
            return set()
        cached = self._capability_cache.get(key)
        if cached is not None:
            return cached
        capabilities: set[str] = set()
        try:
            resp = requests.post(f"{self.base_url}/api/show", json={"model": model}, timeout=6)
            if resp.ok:
                data = resp.json() or {}
                raw = data.get("capabilities")
                if isinstance(raw, list):
                    capabilities = {
                        str(item).strip().lower()
                        for item in raw
                        if str(item or "").strip()
                    }
        except Exception:
            capabilities = set()
        self._capability_cache[key] = capabilities
        return capabilities

    @staticmethod
    def _model_exists(configured_name: str, available_models: list[str]) -> bool:
        target = str(configured_name or "").strip().lower()
        if not target:
            return False
        model_keys = {str(item or "").strip().lower() for item in available_models if str(item or "").strip()}
        if target in model_keys:
            return True
        prefix = target + ":"
        return any(item.startswith(prefix) for item in model_keys)

    def get_runtime_diagnostics(self, *, probe: bool = True) -> dict[str, Any]:
        if not probe:
            warnings = ["Ollama runtime probe skipped by local boundary control."]
            return {
                "base_url": self.base_url,
                "reachable": False,
                "ready": False,
                "requires_attention": False,
                "chat_model": str(self.chat_model or "").strip(),
                "embedding_model": str(self.embedding_model or "").strip(),
                "available_models": [],
                "chat_model_present": False,
                "embedding_model_present": False,
                "chat_capabilities": [],
                "embedding_capabilities": [],
                "chat_transport": "boundary_disabled",
                "warnings": warnings,
                "operator_trigger": warnings[0],
            }

        reachable = self.is_available()
        available_models = self.list_models() if reachable else []
        chat_model = str(self.chat_model or "").strip()
        embedding_model = str(self.embedding_model or "").strip()
        chat_present = self._model_exists(chat_model, available_models)
        embedding_present = self._model_exists(embedding_model, available_models)
        chat_capabilities = sorted(self._get_capabilities(chat_model)) if chat_present else []
        embedding_capabilities = sorted(self._get_capabilities(embedding_model)) if embedding_present else []
        warnings: list[str] = []

        if not reachable:
            warnings.append("Ollama API is unreachable.")

        chat_transport = "unavailable"
        if chat_present:
            if self._supports_chat_transport(set(chat_capabilities)):
                chat_transport = "chat"
            elif "completion" in chat_capabilities:
                chat_transport = "generate_fallback"
                warnings.append(
                    f"Configured chat model '{chat_model}' is completion-only on this Ollama runtime. "
                    "SMi is using generate fallback instead of the chat endpoint."
                )
            else:
                chat_transport = "unsupported"
                warnings.append(
                    f"Configured chat model '{chat_model}' does not expose chat or completion capability."
                )
        else:
            chat_transport = "missing"
            if chat_model:
                warnings.append(f"Configured chat model '{chat_model}' is not available in Ollama.")
            else:
                warnings.append("No chat model is configured.")

        if embedding_present:
            if "embedding" not in embedding_capabilities:
                warnings.append(
                    f"Configured embedding model '{embedding_model}' does not expose embedding capability."
                )
        else:
            if embedding_model:
                warnings.append(f"Configured embedding model '{embedding_model}' is not available in Ollama.")
            else:
                warnings.append("No embedding model is configured.")

        ready = reachable and chat_transport in {"chat", "generate_fallback"} and embedding_present
        if not ready and not warnings:
            warnings.append("LLM runtime is not ready for normal chat.")

        return {
            "base_url": self.base_url,
            "reachable": reachable,
            "ready": ready,
            "requires_attention": bool(warnings),
            "chat_model": chat_model,
            "embedding_model": embedding_model,
            "available_models": available_models,
            "chat_model_present": chat_present,
            "embedding_model_present": embedding_present,
            "chat_capabilities": chat_capabilities,
            "embedding_capabilities": embedding_capabilities,
            "chat_transport": chat_transport,
            "warnings": warnings,
            "operator_trigger": warnings[0] if warnings else "",
        }

    @staticmethod
    def _should_fallback_to_generate(resp: requests.Response) -> bool:
        if resp.status_code in {404, 405}:
            return True
        if resp.status_code != 400:
            return False
        try:
            payload = resp.json() or {}
            message = str(payload.get("error") or payload.get("message") or "").strip().lower()
        except Exception:
            message = (resp.text or "").strip().lower()
        return "does not support chat" in message or "does not support messages" in message

    def chat(self, messages: list[dict[str, str]], *, num_ctx: int | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": int(num_ctx or self.num_ctx),
                "num_predict": self.max_output_tokens,
            },
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive

        try:
            # Thinking models (e.g. gemma4:26B) spend the entire num_predict
            # budget on hidden reasoning and return empty "content". Ask the
            # runtime to disable thinking; retry once without the flag for
            # Ollama builds that reject it for non-thinking models.
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json={**payload, "think": False},
                timeout=self.chat_timeout_seconds,
            )
            if resp.status_code == 400 and "think" in str(resp.text or "").lower():
                resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.chat_timeout_seconds)
            resp.raise_for_status()
            data = resp.json() or {}
            message = data.get("message") or {}
            content = str(message.get("content") or "").strip()
            if not content:
                thinking = str(message.get("thinking") or "")
                done_reason = str(data.get("done_reason") or "").strip()
                print(
                    "!!! OLLAMA CHAT: empty content "
                    f"(model={self.chat_model}, done_reason={done_reason or 'unknown'}, "
                    f"thinking_chars={len(thinking)})"
                )
            return content
        except Exception as e:
            print(f"!!! OLLAMA CHAT ERROR: {e}")
            return ""

    def _chat_via_generate(self, messages: list[dict[str, str]]) -> str:
        prompt_lines: list[str] = []
        for item in messages:
            role = str(item.get("role") or "user").strip().lower()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                prompt_lines.append(f"System: {content}")
            elif role == "assistant":
                prompt_lines.append(f"Assistant: {content}")
            else:
                prompt_lines.append(f"User: {content}")
        prompt_lines.append("Assistant:")
        prompt = "\n\n".join(prompt_lines).strip()

        payload: dict[str, Any] = {
            "model": self.chat_model,
            "prompt": prompt,
            "stream": False,
            "options": self._build_options(),
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=self.chat_timeout_seconds)
        resp.raise_for_status()
        data = resp.json() or {}
        return str(data.get("response") or "").strip()
