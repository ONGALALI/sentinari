"""Sentinel firewall — policy gate for everything that enters the knowledge library.

Every upload (file, GitHub pull, HF dataset, chat attachment, URL ingest) passes
``firewall.check()`` BEFORE ingestion. Anything refused is moved to
``data/sentinel_quarantine/`` and logged with a reason — nothing is silently
dropped and nothing prohibited reaches either library.

Policy lives in ``config/sentinel_policy.yaml`` (operator-editable):

    allowed_extensions: [.pdf, .md, ...]   # empty list = allow all
    blocked_extensions: [.exe, ...]
    max_file_mb: 300
    blocked_name_patterns: ["^~\\$", "\\.tmp$"]
    quarantine_on_block: true
"""
from __future__ import annotations

import fnmatch
import re
import shutil
import time
from pathlib import Path
from typing import Any

from .config import get_project_root

_DEFAULT_POLICY: dict[str, Any] = {
    "allowed_extensions": [],
    "blocked_extensions": [".exe", ".dll", ".bat", ".cmd", ".ps1", ".msi", ".sh", ".bin", ".iso"],
    "blocked_name_patterns": ["^~\\$", "\\.tmp$", "\\.part$", "\\.crdownload$"],
    "max_file_mb": 300,
    "quarantine_on_block": True,
}


def _load_policy() -> dict[str, Any]:
    policy_path = get_project_root() / "config" / "sentinel_policy.yaml"
    policy = dict(_DEFAULT_POLICY)
    if policy_path.exists():
        try:
            import yaml

            loaded = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                policy.update(loaded)
        except Exception:
            pass
    return policy


class SentinelFirewall:
    """Stateless policy gate with a quarantine + audit trail."""

    def __init__(self) -> None:
        self._policy_path = get_project_root() / "config" / "sentinel_policy.yaml"

    # -- policy ------------------------------------------------------------

    def reload_policy(self) -> dict[str, Any]:
        return _load_policy()

    @property
    def quarantine_dir(self) -> Path:
        return get_project_root() / "data" / "sentinel_quarantine"

    @property
    def log_path(self) -> Path:
        return get_project_root() / "data" / "sentinel_quarantine" / "quarantine_log.jsonl"

    # -- verdicts ------------------------------------------------------------

    def check(self, path: str | Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return {'allowed': bool, 'reason': str} for a candidate file."""
        policy = _load_policy()
        p = Path(str(path))
        name = p.name

        if not p.exists():
            return {"allowed": False, "reason": "file does not exist"}

        max_mb = float(policy.get("max_file_mb") or 300)
        try:
            size_mb = p.stat().st_size / (1024.0 * 1024.0)
        except OSError as ex:
            return {"allowed": False, "reason": f"unreadable: {ex}"}
        if size_mb > max_mb:
            return {"allowed": False, "reason": f"file {size_mb:.1f} MB exceeds policy cap {max_mb:.0f} MB"}

        suffix = p.suffix.lower()
        blocked_exts = {str(e).lower() for e in (policy.get("blocked_extensions") or [])}
        if suffix in blocked_exts:
            return {"allowed": False, "reason": f"extension {suffix} is blocked by policy"}

        allowed_exts = {str(e).lower() for e in (policy.get("allowed_extensions") or [])}
        if allowed_exts and suffix not in allowed_exts:
            return {"allowed": False, "reason": f"extension {suffix} not in policy allowlist"}

        for pattern in policy.get("blocked_name_patterns") or []:
            try:
                if re.search(str(pattern), name, re.IGNORECASE) or fnmatch.fnmatch(name.lower(), str(pattern).lower()):
                    return {"allowed": False, "reason": f"filename matches blocked pattern {pattern!r}"}
            except re.error:
                continue

        return {"allowed": True, "reason": "ok"}

    # -- quarantine ----------------------------------------------------------

    def quarantine(self, path: str | Path, verdict: dict[str, Any], metadata: dict[str, Any] | None = None) -> str | None:
        """Move a refused file into quarantine and append an audit entry."""
        policy = _load_policy()
        if not bool(policy.get("quarantine_on_block", True)):
            self._log(path, verdict, metadata, moved=False)
            return None
        src = Path(str(path))
        if not src.exists():
            self._log(path, verdict, metadata, moved=False)
            return None
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        target = self.quarantine_dir / src.name
        counter = 1
        while target.exists():
            target = self.quarantine_dir / f"{src.stem}-{counter}{src.suffix}"
            counter += 1
        try:
            shutil.move(str(src), str(target))
            moved = True
        except Exception:
            moved = False
        self._log(path, verdict, metadata, moved=moved, quarantined_as=str(target) if moved else None)
        return str(target) if moved else None

    def _log(self, path: str | Path, verdict: dict[str, Any], metadata: dict[str, Any] | None, *, moved: bool, quarantined_as: str | None = None) -> None:
        import json

        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "path": str(path),
                "allowed": bool(verdict.get("allowed")),
                "reason": str(verdict.get("reason") or ""),
                "quarantined_as": quarantined_as,
                "library_hint": str((metadata or {}).get("scientific_field") or ""),
            }
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except Exception:
            pass

    def recent_refusals(self, limit: int = 20) -> list[dict[str, Any]]:
        import json

        if not self.log_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            for line in lines[-max(1, limit):]:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            pass
        return rows


firewall = SentinelFirewall()
