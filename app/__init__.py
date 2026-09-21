
"""Package initializer for app.

Provides a lightweight runtime shim for app.config when a full config.py
is unavailable or corrupted. This ensures imports like `from .config import ...`
do not raise ModuleNotFoundError during early startup.

If a real app.config file exists, Python's import system will override this shim
with the real module. The shim uses safe defaults sufficient for SMI startup.
"""

import sys
import types
from pathlib import Path
import yaml


def _make_config_module():
    mod = types.ModuleType("app.config")
    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def _resolve_existing_config_path():
        candidates = [PROJECT_ROOT / "config" / "settings.yaml", PROJECT_ROOT / "config" / "settings.example.yaml"]
        for c in candidates:
            if c.exists():
                return c
        raise FileNotFoundError("No configuration file found.")

    def _load_yaml(path):
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    _cached = None

    def get_config_path():
        return _resolve_existing_config_path()

    def load_raw_settings():
        return _load_yaml(get_config_path())

    def get_settings():
        nonlocal _cached
        if _cached is not None:
            return _cached
        raw = load_raw_settings()
        raw.setdefault("paths", {})
        raw["paths"].setdefault("sqlite_db", "./data/vocationalllm.db")
        raw["paths"].setdefault("protected_dirs", [str(PROJECT_ROOT / "data" / "knowledge_taxonomy" / "SMI_Log")])
        raw.setdefault("llm", {})
        raw.setdefault("safety", {})
        _cached = raw
        return _cached

    def reload_settings():
        nonlocal _cached
        _cached = None
        return get_settings()

    def save_raw_settings(settings):
        path = _resolve_existing_config_path()
        path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
        return path

    def get_project_root():
        return PROJECT_ROOT

    def clamp_top_k(value, settings=None):
        try:
            return int(value)
        except Exception:
            return int(get_settings().get("llm", {}).get("top_k_context_chunks", 6))

    def clamp_temperature(value, settings=None):
        try:
            return float(value)
        except Exception:
            return float(get_settings().get("llm", {}).get("temperature", 0.2))

    def clamp_behavior_variant(value, settings=None):
        try:
            return float(value)
        except Exception:
            return 1.0

    def ensure_protected_dirs(settings=None):
        s = settings if isinstance(settings, dict) else get_settings()
        for d in s.get("paths", {}).get("protected_dirs", []):
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    def is_protected_path(path, settings=None):
        try:
            p = Path(path).resolve()
        except Exception:
            return False
        s = settings if isinstance(settings, dict) else get_settings()
        for item in s.get("paths", {}).get("protected_dirs", []):
            try:
                cand = Path(item).resolve()
                if str(p).lower().startswith(str(cand).lower()):
                    return True
            except Exception:
                continue
        return False

    def resolve_retrieval_top_k(value, settings=None):
        try:
            v = int(value)
            if v > 0:
                return v
        except Exception:
            pass
        s = settings if isinstance(settings, dict) else get_settings()
        try:
            configured = int(s.get("llm", {}).get("top_k_context_chunks", 6))
        except Exception:
            configured = 6
        return max(1, configured)

    # attach functions to module
    mod.get_settings = get_settings
    mod.get_config_path = get_config_path
    mod.load_raw_settings = load_raw_settings
    mod.reload_settings = reload_settings
    mod.save_raw_settings = save_raw_settings
    mod.get_project_root = get_project_root
    mod.clamp_top_k = clamp_top_k
    mod.clamp_temperature = clamp_temperature
    mod.clamp_behavior_variant = clamp_behavior_variant
    mod.ensure_protected_dirs = ensure_protected_dirs
    mod.is_protected_path = is_protected_path
    mod.resolve_retrieval_top_k = resolve_retrieval_top_k

    return mod


_shim = _make_config_module()
# register in sys.modules so relative imports find it
sys.modules.setdefault("app.config", _shim)
config = _shim

