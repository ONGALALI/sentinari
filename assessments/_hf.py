"""Shared HuggingFace token plumbing for the assessment loaders.

Reads HF_TOKEN from the environment, then from the in-tree .env. The token is
the OWNER's (HLE is a gated dataset — the license acceptance must be the
owner's). Never commit a token; .env is git-ignored.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HF_HOME = ROOT / "data" / "hf_cache"
HF_HOME.mkdir(parents=True, exist_ok=True)


def ensure_hf_env() -> None:
    """Pin the cache in-tree and surface the owner's HF token if present."""
    os.environ.setdefault("HF_HOME", str(HF_HOME))
    if os.environ.get("HF_TOKEN"):
        return
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("HF_TOKEN="):
            token = line[len("HF_TOKEN="):].strip().strip('"').strip("'")
            if token:
                os.environ["HF_TOKEN"] = token
            return
