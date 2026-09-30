from __future__ import annotations

import json
import os
from pathlib import Path


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_SMI_link_enabled() -> bool:
    """Read the runtime-link toggle. In-tree copy first (data/toggles/), then
    the legacy parent-folder location. Returns True (link ON) unless a readable
    file explicitly sets ollamaLinkEnabled=false.
    """
    candidates = (
        get_project_root() / "data" / "toggles" / "runtime-link.json",
        get_project_root().parent / "Data" / "SMIStandalone" / "SMI-runtime-link.json",
    )
    for link_file in candidates:
        try:
            if not link_file.exists():
                continue
            # utf-8-sig transparently strips the BOM that PowerShell Set-Content -Encoding UTF8 adds
            text = link_file.read_text(encoding="utf-8-sig").strip()
            if not text:
                return True  # Transient empty file during PS1 atomic write — default to ON
            data = json.loads(text)
            # Honour explicit false; any other value (True, missing) keeps the link alive
            if data.get("ollamaLinkEnabled") is False:
                return False
        except Exception:
            pass  # Unreadable → default ON (Ollama.is_available() is the real guard)
    return True


def is_ollama_runtime_probe_disabled() -> bool:
    # 1. Env-var override (highest priority)
    raw = (
        os.environ.get("SENTINARI_SKIP_OLLAMA_AUTOSTART")
        or os.environ.get("SMI_SKIP_OLLAMA_AUTOSTART")
        or ""
    ).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    # 2. Flag file override (inside the project tree — survives folder moves)
    if (get_project_root() / "data" / "flags" / "skip_ollama_autostart.flag").exists():
        return True
    # 3. Toggle JSON config (in-tree copy first, legacy parent location second)
    return not _read_SMI_link_enabled()


def build_ollama_boundary_runtime(base_url: str, chat_model: str, embedding_model: str) -> dict[str, object]:
    warnings = [
        "Ollama contact is disabled by local boundary control.",
        "Remove the boundary flag only when a live local Sentinari/Ollama run is explicitly required.",
    ]
    return {
        "base_url": str(base_url or "http://127.0.0.1:11434"),
        "reachable": False,
        "ready": False,
        "requires_attention": False,
        "chat_model": str(chat_model or ""),
        "embedding_model": str(embedding_model or ""),
        "available_models": [],
        "chat_model_present": False,
        "embedding_model_present": False,
        "chat_capabilities": [],
        "embedding_capabilities": [],
        "chat_transport": "boundary_disabled",
        "warnings": warnings,
        "operator_trigger": warnings[0],
    }
