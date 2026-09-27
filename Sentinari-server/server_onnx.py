"""Sentinari Inference Server — cuts the Ollama cord.
================================================================

Phase 2/3 of the_process_to_follow.md: a self-contained FastAPI wrapper
around Microsoft's onnxruntime-genai. At runtime this process imports only
``onnxruntime_genai`` for model work — no transformers, no Hugging Face
library code executing. Phase 5 wires coding_agent.py / gemma_training.py
against these endpoints instead of Ollama.

Design discipline (inherited from llm_gateway.py):
  * No OpenAI-shaped naming anywhere — Sentinel-flavored endpoints only.
  * Provider/engine choice is a settings change, not a code change.
  * API keys would come from env; this server needs none (local weights).
  * One model per process (same as before). A second instance on another
    port with its own MODEL_PATH serves a second workspace later.

DEGRADED MODE — important for the prototype phase:
  If onnxruntime_genai is not installed, or the configured MODEL_PATH
  folder does not exist yet (conversion happens later, on the connected
  machine), the server still boots and answers /health and chat requests
  with an explicit stub reply. Every reply states the engine is not
  loaded, so a stub can never be mistaken for model output. This lets the
  wrapper, persona injection, SQLite logging, and service installation be
  verified TODAY, before any conversion has run.

Gemma chat template (roadmap flag): prompts are rendered in Gemma's
<start_of_turn> format. If tokenizer.apply_chat_template exists (newer
ort-genai releases) it is used instead, since the converted model's
tokenizer config is authoritative. API churn warning from the roadmap is
honoured: pin the ort-genai version in requirements-inference.txt.

Run:
    python server_onnx.py                    # settings from inference_settings.yaml
    python server_onnx.py --port 8100        # CLI overrides
    python server_onnx.py --model ./models/gemma-onnx
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

SETTINGS_PATH = Path(__file__).resolve().parent / "inference_settings.yaml"


def _load_settings() -> dict[str, Any]:
    """Load inference_settings.yaml (small, local, no app package import)."""
    try:
        import yaml  # ships in the Sentinari venv

        data = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
        return dict(data or {})
    except FileNotFoundError:
        return {}
    except Exception as ex:  # a broken settings file must not kill the server
        print(f"[settings] WARNING: could not parse {SETTINGS_PATH.name}: {ex}")
        return {}


SETTINGS = _load_settings()

SERVER_CFG = dict(SETTINGS.get("server") or {})
MODEL_CFG = dict(SETTINGS.get("model") or {})
PERSONA_CFG = dict(SETTINGS.get("personality") or {})
DOMAINS_CFG = dict(SETTINGS.get("domains") or {})
LOG_CFG = dict(SETTINGS.get("logging") or {})

HOST = str(SERVER_CFG.get("host") or "127.0.0.1")
PORT = int(SERVER_CFG.get("port") or 8100)

# --------------------------------------------------------------------------
# SQLite request log (Sentinari-shaped: no OpenAI naming anywhere)
# --------------------------------------------------------------------------

LOG_DB = (Path(__file__).resolve().parent / str(LOG_CFG.get("db_path") or "inference_log.sqlite3")).resolve()


@contextmanager
def log_connection() -> Iterator[sqlite3.Connection]:
    """One short-lived connection per write (same pattern as app/db.py)."""
    conn = sqlite3.connect(LOG_DB, timeout=20)
    try:
        conn.execute("PRAGMA busy_timeout = 20000")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_log_db() -> None:
    with log_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inference_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                domain TEXT NOT NULL,
                persona TEXT NOT NULL,
                engine TEXT NOT NULL,
                prompt_chars INTEGER NOT NULL,
                reply_chars INTEGER NOT NULL,
                elapsed_ms INTEGER NOT NULL,
                status TEXT NOT NULL,
                error_text TEXT
            )
            """
        )


def _log_request(**fields: Any) -> None:
    try:
        with log_connection() as conn:
            conn.execute(
                "INSERT INTO inference_log (ts, endpoint, domain, persona, engine,"
                " prompt_chars, reply_chars, elapsed_ms, status, error_text)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    str(fields.get("endpoint") or "chat"),
                    str(fields.get("domain") or "default"),
                    str(fields.get("persona") or ""),
                    str(fields.get("engine") or ""),
                    int(fields.get("prompt_chars") or 0),
                    int(fields.get("reply_chars") or 0),
                    int(fields.get("elapsed_ms") or 0),
                    str(fields.get("status") or "ok"),
                    fields.get("error_text"),
                ),
            )
    except Exception as ex:  # logging must never take the server down
        print(f"[log] WARNING: could not write inference_log row: {ex}")


# --------------------------------------------------------------------------
# Persona injection (domain-based, mirrors settings.yaml personality block)
# --------------------------------------------------------------------------

PERSONA_NAME = str(PERSONA_CFG.get("name") or "Mira-VET")
PERSONA_TONE = str(PERSONA_CFG.get("tone") or "Friendly, warm, lightly humorous, evidence-first")
PERSONA_LANGUAGE = str(PERSONA_CFG.get("default_language") or "English")


def resolve_domain(requested: str | None) -> tuple[str, dict[str, Any]]:
    """Map a request's domain name to its persona config (default fallback)."""
    key = str(requested or "").strip().lower() or "default"
    if key in DOMAINS_CFG and isinstance(DOMAINS_CFG[key], dict):
        return key, dict(DOMAINS_CFG[key])
    default_cfg = DOMAINS_CFG.get("default")
    return "default", dict(default_cfg if isinstance(default_cfg, dict) else {})


def build_system_prompt(domain: str, domain_cfg: dict[str, Any]) -> str:
    """Domain-based persona injection — the same idea as the main app's
    personality block, applied at the inference boundary."""
    parts = [
        f"You are {PERSONA_NAME}, the resident intelligence of the Sentinari "
        "research platform by Inspirari.",
        f"Tone: {PERSONA_TONE}.",
        f"Language: {PERSONA_LANGUAGE} unless the user writes in another language.",
    ]
    system_text = str(domain_cfg.get("system_prompt") or "").strip()
    if system_text:
        parts.append(system_text)
    focus = domain_cfg.get("focus")
    if focus:
        parts.append(f"Domain focus: {focus}.")
    return "\n".join(part for part in parts if part)


# --------------------------------------------------------------------------
# ONNX engine (the only place onnxruntime_genai is touched)
# --------------------------------------------------------------------------


class OnnxEngine:
    """Loads the converted Gemma folder and generates with ort-genai.

    Honest state machine: ``status`` is one of
      * "unconfigured"  — MODEL_PATH not set / folder missing
      * "library-missing" — onnxruntime_genai not importable
      * "loaded"        — model ready, real generation
    """

    def __init__(self, model_path: str, execution_provider: str, max_length: int) -> None:
        self.requested_path = str(model_path or "")
        self.execution_provider = str(execution_provider or "cpu")
        self.max_length = int(max_length or 2048)
        self.status = "unconfigured"
        self.detail = ""
        self.model: Any = None
        self.tokenizer: Any = None
        self.loaded_path = ""
        self.load_seconds = 0.0

    # -- loading ------------------------------------------------------------

    def load(self, model_path: str | None = None) -> dict[str, Any]:
        """(Re)load the model folder. Safe to call repeatedly (reload hook)."""
        if model_path:
            self.requested_path = str(model_path)
        target = Path(self.requested_path)
        if not self.requested_path or not target.exists():
            self.status = "unconfigured"
            self.detail = f"model folder not found: {self.requested_path or '(unset)'}"
            return self.describe()
        try:
            import onnxruntime_genai as og  # imported ONLY here, lazily
        except Exception as ex:
            self.status = "library-missing"
            self.detail = f"onnxruntime_genai unavailable: {ex}"
            return self.describe()

        started = time.time()
        try:
            self.model = og.Model(str(target))
            self.tokenizer = og.Tokenizer(str(target))
        except Exception as ex:
            self.model = None
            self.tokenizer = None
            self.status = "unconfigured"
            self.detail = f"model load failed: {ex}"
            return self.describe()
        self.load_seconds = round(time.time() - started, 2)
        self.status = "loaded"
        self.loaded_path = str(target.resolve())
        self.detail = f"loaded in {self.load_seconds}s"
        return self.describe()

    # -- state ----------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "engine": "onnxruntime-genai",
            "status": self.status,
            "detail": self.detail,
            "model_path": self.loaded_path or self.requested_path,
            "execution_provider": self.execution_provider,
            "max_length": self.max_length,
            "load_seconds": self.load_seconds,
        }

    def is_loaded(self) -> bool:
        return self.status == "loaded" and self.model is not None

    # -- generation -------------------------------------------------------------

    def render_prompt(self, messages: list[dict[str, str]]) -> str:
        """Gemma <start_of_turn> template — OR the model's own chat template
        when this ort-genai build exposes apply_chat_template (preferred:
        the converted tokenizer config is authoritative)."""
        if self.tokenizer is not None and hasattr(self.tokenizer, "apply_chat_template"):
            try:
                rendered = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True)
                if rendered:
                    return str(rendered)
            except Exception:
                pass  # fall through to the manual Gemma template
        turns: list[str] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            if role == "system":
                # Gemma has no system role: fold system text into the first turn.
                turns.append(f"<start_of_turn>user\n{content}\n<end_of_turn>")
            elif role == "assistant":
                turns.append(f"<start_of_turn>model\n{content}\n<end_of_turn>")
            else:
                turns.append(f"<start_of_turn>user\n{content}\n<end_of_turn>")
        turns.append("<start_of_turn>model\n")
        return "\n".join(turns)

    def generate(self, prompt: str, *, max_tokens: int, temperature: float, top_p: float) -> str:
        """One completion. Raises on engine failure — caller wraps in 503."""
        import numpy  # ort-genai returns numpy token arrays
        import onnxruntime_genai as og

        params = og.GeneratorParams(self.model)
        search: dict[str, Any] = {
            "max_length": int(max_tokens),
            "temperature": float(temperature),
            "top_p": float(top_p),
            "do_sample": float(temperature) > 0.0,
        }
        try:
            params.set_search_options(**search)
        except Exception:
            # Some preview builds reject do_sample — retry without it.
            search.pop("do_sample", None)
            params.set_search_options(**search)

        input_tokens = self.tokenizer.encode(prompt)
        if isinstance(input_tokens, list):  # older builds return lists
            input_tokens = numpy.array([input_tokens], dtype=numpy.int64)
        elif input_tokens.ndim == 1:  # newer builds return 1-D arrays
            input_tokens = input_tokens.reshape(1, -1)

        generator = og.Generator(self.model, params)
        generator.append_tokens(input_tokens)
        output_tokens: list[int] = []
        while not generator.is_done() and len(output_tokens) < max_tokens:
            generator.generate_next_token()
            output_tokens.extend(int(t) for t in generator.get_next_tokens()[0])
        return str(self.tokenizer.decode(output_tokens) or "").strip()


ENGINE = OnnxEngine(
    model_path=str(MODEL_CFG.get("path") or ""),
    execution_provider=str(MODEL_CFG.get("execution_provider") or "cpu"),
    max_length=int(MODEL_CFG.get("max_length") or 2048),
)

STARTED_AT = time.time()
COUNTS = {"chat_ok": 0, "chat_error": 0, "stub_replies": 0}
_COUNTS_LOCK = threading.Lock()


def _bump(key: str) -> None:
    with _COUNTS_LOCK:
        COUNTS[key] = COUNTS.get(key, 0) + 1


# --------------------------------------------------------------------------
# FastAPI app (Sentinari-shaped endpoints — no OpenAI naming anywhere)
# --------------------------------------------------------------------------

app = FastAPI(title="Sentinari Inference Server", version="0.1.0")


class ChatRequest(BaseModel):
    prompt: str | None = None
    messages: list[dict[str, str]] | None = None
    domain: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)


def _stub_reply(domain: str, reason: str) -> str:
    """Explicit, unmistakable degraded-mode reply."""
    return (
        f"[Sentinari inference: engine not loaded — {reason}. This is a stub "
        f"reply from degraded mode, not model output.] "
        f"(domain={domain}, persona={PERSONA_NAME})"
    )


def _normalise_messages(request: ChatRequest, domain_cfg: dict[str, Any], system_prompt: str) -> list[dict[str, str]]:
    if request.messages:
        messages = [
            {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
            for m in request.messages
            if str(m.get("content") or "").strip()
        ]
    else:
        messages = [{"role": "user", "content": str(request.prompt or "").strip()}]
    messages = [m for m in messages if m["content"]]
    if not messages:
        raise HTTPException(status_code=400, detail="prompt or messages required")
    # Persona injection always lands at position 0 as system text.
    messages.insert(0, {"role": "system", "content": system_prompt})
    return messages


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "sentinari-inference",
        "engine_status": ENGINE.status,
        "degraded": not ENGINE.is_loaded(),
        "uptime_seconds": int(time.time() - STARTED_AT),
    }


@app.get("/api/inference/status")
def inference_status() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "sentinari-inference",
        "version": app.version,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "engine": ENGINE.describe(),
        "degraded": not ENGINE.is_loaded(),
        "persona": {"name": PERSONA_NAME, "tone": PERSONA_TONE, "language": PERSONA_LANGUAGE},
        "domains": sorted(DOMAINS_CFG.keys()) if DOMAINS_CFG else ["default"],
        "counts": dict(COUNTS),
        "log_db": LOG_DB.name,
    }


@app.get("/api/inference/domains")
def inference_domains() -> dict[str, Any]:
    return {
        "ok": True,
        "default": "default",
        "domains": [
            {"domain": name, "focus": cfg.get("focus"), "temperature": cfg.get("temperature")}
            for name, cfg in sorted(DOMAINS_CFG.items())
            if isinstance(cfg, dict)
        ],
    }


@app.post("/api/inference/chat")
def inference_chat(request: ChatRequest) -> dict[str, Any]:
    started = time.time()
    domain, domain_cfg = resolve_domain(request.domain)
    system_prompt = build_system_prompt(domain, domain_cfg)
    try:
        messages = _normalise_messages(request, domain_cfg, system_prompt)
    except HTTPException:
        _bump("chat_error")
        raise

    temperature = float(
        request.temperature
        if request.temperature is not None
        else (domain_cfg.get("temperature") if domain_cfg.get("temperature") is not None else 0.1)
    )
    max_tokens = int(request.max_tokens or domain_cfg.get("max_tokens") or 768)
    top_p = float(request.top_p if request.top_p is not None else (domain_cfg.get("top_p") or 0.9))

    prompt_chars = sum(len(m["content"]) for m in messages)
    try:
        if ENGINE.is_loaded():
            prompt = ENGINE.render_prompt(messages)
            reply = ENGINE.generate(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
            engine_label = f"onnx:{ENGINE.execution_provider}"
        else:
            reply = _stub_reply(domain, ENGINE.detail or ENGINE.status)
            engine_label = "degraded-stub"
            _bump("stub_replies")
        elapsed_ms = int((time.time() - started) * 1000)
        _bump("chat_ok")
        _log_request(
            endpoint="chat",
            domain=domain,
            persona=PERSONA_NAME,
            engine=engine_label,
            prompt_chars=prompt_chars,
            reply_chars=len(reply),
            elapsed_ms=elapsed_ms,
            status="ok",
        )
        return {
            "ok": True,
            "reply": reply,
            "domain": domain,
            "persona": PERSONA_NAME,
            "model": str(MODEL_CFG.get("label") or ENGINE.loaded_path or "degraded-stub"),
            "degraded": not ENGINE.is_loaded(),
            "elapsed_ms": elapsed_ms,
        }
    except HTTPException:
        raise
    except Exception as ex:
        elapsed_ms = int((time.time() - started) * 1000)
        _bump("chat_error")
        _log_request(
            endpoint="chat",
            domain=domain,
            persona=PERSONA_NAME,
            engine=ENGINE.status,
            prompt_chars=prompt_chars,
            reply_chars=0,
            elapsed_ms=elapsed_ms,
            status="error",
            error_text=str(ex)[:500],
        )
        raise HTTPException(status_code=503, detail=f"inference failed: {ex}") from ex


@app.post("/api/inference/model/load")
def inference_model_load(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load/reload the ONNX model folder without a service restart —
    lets the conversion output be plugged in live once it exists."""
    path = str((payload or {}).get("path") or "")
    result = ENGINE.load(path or None)
    return {"ok": ENGINE.is_loaded(), "engine": result}


@app.get("/api/inference/log")
def inference_log(limit: int = 20) -> dict[str, Any]:
    limit = max(1, min(int(limit or 20), 200))
    with log_connection() as conn:
        rows = conn.execute(
            "SELECT id, ts, endpoint, domain, persona, engine, prompt_chars,"
            " reply_chars, elapsed_ms, status, error_text"
            f" FROM inference_log ORDER BY id DESC LIMIT {limit}"
        ).fetchall()
    keys = [
        "id", "ts", "endpoint", "domain", "persona", "engine",
        "prompt_chars", "reply_chars", "elapsed_ms", "status", "error_text",
    ]
    return {"ok": True, "rows": [dict(zip(keys, row)) for row in rows]}


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinari ONNX inference server")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--model", default=None, help="override model folder path")
    args = parser.parse_args()

    if args.model:
        MODEL_CFG["path"] = args.model
        ENGINE.requested_path = args.model

    _init_log_db()
    if MODEL_CFG.get("auto_load", True):
        ENGINE.load()

    print(f"[sentinari-inference] engine status: {ENGINE.status} ({ENGINE.detail})")
    print(f"[sentinari-inference] listening on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
