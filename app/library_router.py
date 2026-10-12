"""Sentinari library router — the single source of truth for the library.

The knowledge library is ONE physical SQLite database:

* ``sentinari.db`` — the Sentinel / Guardian library (renamed from the legacy
  ``library_gemma.db`` filename in §51; the file itself moved untouched, so
  every embedding, chunk, and FTS index rides along). Only the Sentinel
  gateway writes here. The knowledge corpus lives in this single database.

The active persona is:

* ``sentinari`` — grounded scientific assistant, reads the Sentinari library.

The persona persists in the ``app_runtime_state`` table of the main database so
all server processes agree. Focus profiles weight which scientific fields lead
retrieval for Sentinari without hiding the others.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .config import get_project_root, get_settings

# §51: persona/model keys are runtime-coupled (Ollama tags, persisted state
# rows) and stay as-is; only the LIBRARY FILENAME is rebranded here.
SENTINARI_PERSONA = "gemma"
GEMMA_PERSONA = SENTINARI_PERSONA  # legacy alias — persisted app_runtime_state rows carry 'gemma'
VALID_PERSONAS = (SENTINARI_PERSONA,)

CODING_FIELD = "computer-and-information-sciences"

PERSONA_MODELS = {
    GEMMA_PERSONA: "gemma4:12B",
}

_lock = threading.Lock()


def sentinari_library_path() -> Path:
    """The one library database. §51: file renamed library_gemma.db → sentinari.db."""
    path = get_project_root() / "data" / "sentinari.db"
    if not path.exists():
        legacy = get_project_root() / "data" / "library_gemma.db"
        if legacy.exists():
            return legacy  # not yet renamed on this checkout — keep working
    return path


def gemma_library_path() -> Path:
    """Legacy name kept for the call sites that still import it."""
    return sentinari_library_path()


def _ensure_state_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_runtime_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def get_active_persona() -> str:
    """Return the active persona (always 'gemma')."""
    settings = get_settings()
    db_path = Path(settings["paths"]["sqlite_db"]).resolve()
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        _ensure_state_table(conn)
        row = conn.execute("SELECT value FROM app_runtime_state WHERE key = 'active_persona';").fetchone()
        value = str(row[0] or "").strip().lower() if row else ""
        return value if value in VALID_PERSONAS else GEMMA_PERSONA
    except Exception:
        return GEMMA_PERSONA
    finally:
        conn.close()


def set_active_persona(persona: str) -> str:
    """Persist the active persona; returns the normalized value."""
    value = str(persona or "").strip().lower()
    if value not in VALID_PERSONAS:
        raise ValueError(f"Unknown persona {persona!r}; expected one of {VALID_PERSONAS}.")
    settings = get_settings()
    db_path = Path(settings["paths"]["sqlite_db"]).resolve()
    with _lock:
        conn = sqlite3.connect(str(db_path), timeout=15)
        try:
            _ensure_state_table(conn)
            conn.execute(
                """
                INSERT INTO app_runtime_state (key, value, updated_at)
                VALUES ('active_persona', ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now');
                """,
                (value,),
            )
            conn.commit()
        finally:
            conn.close()
    return value


def persona_model(persona: str | None = None) -> str:
    """The Ollama chat model bound to a persona (default: active persona).

    Gemma uses the configured ``llm.chat_model`` when it is actually a gemma
    variant; the config default protects against a config file left pointing
    at a different model.
    """
    p = (persona or get_active_persona()).strip().lower()
    settings = get_settings()
    configured = str((settings.get("llm", {}) or {}).get("chat_model", "")).strip()
    if configured and "gemma" in configured.lower():
        return configured
    return PERSONA_MODELS[GEMMA_PERSONA]


def library_path_for(persona: str | None = None) -> Path:
    """Which library database a persona reads (always the Sentinari library)."""
    return sentinari_library_path()


def library_name_for_field(
    scientific_field: str | None,
    *,
    source_collection: str | None = None,
    module: str | None = None,
    target_library: str | None = None,
    persona: str | None = None,
) -> str:
    """Which library a *write* belongs to: always the Sentinari library.

    Legacy metadata that still carries target_library/persona values is
    accepted and routed to the Sentinari library — every field lives there.
    """
    del scientific_field, source_collection, module, target_library, persona
    return GEMMA_PERSONA



# ---------------------------------------------------------------------------
# Focus profiles — weight (not hide) scientific fields during retrieval.
# Operators extend these in config/settings.yaml under `sentinel.focus_profiles`.
# ---------------------------------------------------------------------------

_DEFAULT_FOCUS_PROFILES: dict[str, list[str]] = {
    "balanced": [],
    "human-behavior": [
        "philosophy",
        "psychology",
        "sociology",
        "anthropology",
        "economics",
        "political-science",
        "laws-per-country-and-international-law",
        "war",
        "religion",
    ],
    "engineering": ["engineering", "computer-and-information-sciences", "materials-science"],
    "life-sciences": ["biology", "genetics-molecular-biology", "neuroscience", "ecology-environmental-biology", "medicine"],
    "foundations": ["physics", "chemistry", "mathematics", "astronomy-cosmology", "earth-sciences"],
}


def focus_profiles() -> dict[str, list[str]]:
    settings = get_settings()
    configured = settings.get("sentinel", {}).get("focus_profiles", {})
    merged = dict(_DEFAULT_FOCUS_PROFILES)
    if isinstance(configured, dict):
        for name, fields in configured.items():
            if isinstance(fields, list):
                merged[str(name)] = [str(f) for f in fields]
    return merged


def active_focus_profile() -> str:
    settings = get_settings()
    return str(settings.get("sentinel", {}).get("active_focus_profile", "balanced")).strip().lower() or "balanced"


def focus_field_boosts() -> dict[str, float]:
    """Map of scientific_field -> boost multiplier for the active focus profile."""
    profile = active_focus_profile()
    fields = focus_profiles().get(profile) or []
    return {str(f).strip().lower(): 1.35 for f in fields}


_FIELD_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _norm_field(value: str) -> str:
    return "-".join(_FIELD_TOKEN_RE.findall(str(value or "").lower()))


def field_boost_for(scientific_field: str | None) -> float:
    boosts = focus_field_boosts()
    key = _norm_field(scientific_field)
    for boost_key, boost in boosts.items():
        if key == _norm_field(boost_key) or key.endswith(boost_key) or boost_key in key:
            return boost
    return 1.0


def persona_status() -> dict[str, Any]:
    active = get_active_persona()
    return {
        "ok": True,
        "active_persona": active,
        "active_model": persona_model(active),
        "available_personas": [
            {"persona": p, "model": PERSONA_MODELS[p], "library": str(library_path_for(p).name)}
            for p in VALID_PERSONAS
        ],
        "gemma_library": str(sentinari_library_path()),
        "focus_profile": active_focus_profile(),
        "focus_profiles": focus_profiles(),
    }
