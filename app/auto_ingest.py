from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config as _config

# Ensure compatibility if config module lacks is_protected_path (some copies may be trimmed).
get_settings = getattr(_config, "get_settings", lambda: {})
def is_protected_path(path, settings=None):
    fn = getattr(_config, "is_protected_path", None)
    if callable(fn):
        return fn(path, settings=settings)
    # default conservative behaviour: do not treat as protected
    try:
        return False
    except Exception:
        return False
from .db import get_connection
from .ingestion import ingest_files
from .taxonomy import ensure_configured_taxonomy_dirs, infer_metadata_from_taxonomy_path
from .unsupervised import rebuild_unsupervised_clusters


SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
}


class AutoIngestService:
    def __init__(self) -> None:
        settings = get_settings()
        ingestion = settings.get("ingestion", {})
        unsupervised = settings.get("unsupervised", {})
        self.enabled = bool(ingestion.get("auto_ingest_enabled", True))
        self.poll_seconds = max(10, int(ingestion.get("auto_polling_seconds") or 20))
        self.recursive_scan = bool(ingestion.get("recursive_scan", True))
        self.failed_retry_interval_seconds = max(
            60,
            int(ingestion.get("failed_retry_interval_seconds") or 3600),
        )
        self.max_auto_file_size_mb = max(1, int(ingestion.get("auto_max_file_size_mb") or 200))
        self.max_auto_file_size_bytes = int(self.max_auto_file_size_mb * 1024 * 1024)
        self.auto_rebuild_unsupervised = bool(unsupervised.get("auto_rebuild_on_ingest", True))
        self.unsupervised_rebuild_interval_seconds = max(
            30,
            int(unsupervised.get("auto_rebuild_min_interval_seconds") or 300),
        )
        self._last_unsupervised_rebuild_ts = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vocationalllm-auto-ingest", daemon=True)
        self._thread.start()

    def stop(self, timeout_seconds: int = 4) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_seconds)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def scan_once(self) -> dict[str, Any]:
        if not self.enabled:
            return {"processed": 0, "failed": 0, "skipped": 0, "items": [], "stopped_early": False}

        processed = 0
        failed = 0
        skipped = 0
        details: list[dict[str, Any]] = []

        with get_connection() as conn:
            ensure_configured_taxonomy_dirs(conn)
            conn.commit()

        candidates = self._discover_candidate_files()
        stopped_early = False
        for path in candidates:
            if self._stop.is_set():
                stopped_early = True
                break

            with get_connection() as conn:
                should_ingest = self._should_ingest(conn, path)
                if not should_ingest:
                    skipped += 1
                    continue
                metadata = infer_metadata_from_taxonomy_path(conn, path)

            try:
                outcome = ingest_files([str(path)], metadata=metadata, allow_embeddings=False)
                item = (outcome.get("items") or [{}])[0]
                processed += int(outcome.get("ingested") or 0)
                failed += int(outcome.get("failed") or 0)
                checksum = str(item.get("checksum") or "")
                status = "ok" if bool(item.get("ok")) else "failed"
                error = str(item.get("error") or "")
                with get_connection() as conn:
                    self._upsert_state_with_retry(conn, path, checksum, status, error)
                details.append(
                    {
                        "path": str(path),
                        "status": status,
                        "source_id": item.get("source_id"),
                        "error": error,
                    }
                )
            except Exception as ex:
                failed += 1
                with get_connection() as conn:
                    self._upsert_state_with_retry(conn, path, "", "failed", str(ex))
                details.append({"path": str(path), "status": "failed", "error": str(ex)})

        unsupervised_rebuild = self._maybe_run_unsupervised_rebuild(processed)

        return {
            "processed": processed,
            "failed": failed,
            "skipped": skipped,
            "items": details,
            "stopped_early": stopped_early,
            "unsupervised_rebuild": unsupervised_rebuild,
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:
                # Keep daemon alive; failures are captured in file_ingest_state where possible.
                pass
            self._stop.wait(self.poll_seconds)

    def _discover_candidate_files(self) -> list[Path]:
        settings = get_settings()
        configured_roots = settings.get("paths", {}).get("ingest_roots") or []
        if isinstance(configured_roots, list) and configured_roots:
            roots = [Path(str(root)).resolve() for root in configured_roots if str(root).strip()]
        else:
            roots = [
                Path(settings["paths"]["raw_root"]).resolve(),
                Path(settings["paths"]["taxonomy_root"]).resolve(),
            ]
        found: list[Path] = []
        seen = set()

        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            # Owner directive: Sentinel's scientific-field containers are
            # served ONLY by the load/upload lanes. The auto-ingest daemon
            # must never re-digest them — its no-embedding re-digest used to
            # wipe fresh chunk vectors and its scans collided with active
            # loads (the post-load "freeze" on the small machine).
            root_name = root.name.lower()
            if root_name in {"scientific_fields", "scientific-fields"} or "scientific_fields" in str(root).lower().replace("\\", "/").split("/"):
                continue
            iterator = root.rglob("*") if self.recursive_scan else root.glob("*")
            for path in iterator:
                if not path.is_file():
                    continue
                # Owner directive (subtree guard): never re-digest Sentinel's
                # scientific-field containers even when they sit under a
                # configured scan root — those files belong to the load/upload
                # lanes, and a no-embedding re-digest would wipe fresh vectors.
                if "scientific_fields" in path.parts:
                    continue
                # §31 (owner): Sentinel's own code is not knowledge. Never
                # auto-digest files under the project's own templates/app/
                # scripts/config directories. Dataset repos elsewhere (e.g.
                # github checkouts inside containers with their own scripts/
                # folders) are knowledge and stay eligible.
                _project_root = Path(__file__).resolve().parents[1]
                try:
                    _relative = path.resolve().relative_to(_project_root)
                except ValueError:
                    _relative = None
                if _relative is not None and _relative.parts and _relative.parts[0] in {
                    "templates", "app", "scripts", "config"
                }:
                    continue
                if self._is_discussion_memory_file(path, settings):
                    continue
                if is_protected_path(path, settings=settings) and not self._is_allowed_protected_ingest(path, settings):
                    continue
                if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                try:
                    if path.stat().st_size > self.max_auto_file_size_bytes:
                        continue
                except Exception:
                    continue
                full = str(path.resolve()).lower()
                if full in seen:
                    continue
                seen.add(full)
                found.append(path.resolve())
        return sorted(found)

    def _is_allowed_protected_ingest(self, path: Path, settings: dict[str, Any]) -> bool:
        memory = settings.get("memory", {}) if isinstance(settings.get("memory"), dict) else {}
        configured_root = str(memory.get("discussion_log_dir") or "").strip()
        if configured_root:
            log_root = Path(configured_root).resolve()
        else:
            taxonomy_root = Path(settings["paths"]["taxonomy_root"]).resolve()
            log_root = (taxonomy_root / "SMI_Log").resolve()
        try:
            resolved = path.resolve()
            if resolved.is_relative_to(log_root):
                return True
            taxonomy_root = Path(settings["paths"]["taxonomy_root"]).resolve()
            vocational_root = (taxonomy_root / "vocational_disciplines").resolve()
            return resolved.is_relative_to(vocational_root)
        except Exception:
            return False

    def _is_discussion_memory_file(self, path: Path, settings: dict[str, Any]) -> bool:
        memory = settings.get("memory", {}) if isinstance(settings.get("memory"), dict) else {}
        configured_root = str(memory.get("discussion_log_dir") or "").strip()
        prefix = str(memory.get("discussion_log_prefix") or "discussion_memory").strip().lower() or "discussion_memory"
        if configured_root:
            log_root = Path(configured_root).resolve()
        else:
            taxonomy_root = Path(settings["paths"]["taxonomy_root"]).resolve()
            log_root = (taxonomy_root / "SMI_Log").resolve()
        try:
            relative = path.resolve().relative_to(log_root)
        except Exception:
            return False
        return any(part.strip().lower() == prefix for part in relative.parts)

    def _maybe_run_unsupervised_rebuild(self, processed_count: int) -> dict[str, Any] | None:
        if int(processed_count) <= 0:
            return None
        if not self.auto_rebuild_unsupervised:
            return {"status": "skipped", "reason": "auto_rebuild_on_ingest_disabled"}

        now = time.time()
        if (now - self._last_unsupervised_rebuild_ts) < float(self.unsupervised_rebuild_interval_seconds):
            return {
                "status": "skipped",
                "reason": "interval_throttled",
                "min_interval_seconds": int(self.unsupervised_rebuild_interval_seconds),
            }

        try:
            with get_connection() as conn:
                result = rebuild_unsupervised_clusters(conn)
                conn.commit()
            self._last_unsupervised_rebuild_ts = now
            return {
                "status": "completed" if bool(result.get("ok")) else "failed",
                "run_id": result.get("run_id"),
                "result": result,
            }
        except Exception as ex:
            return {"status": "failed", "error": str(ex)}

    def _should_ingest(self, conn, path: Path) -> bool:
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        row = conn.execute(
            "SELECT file_size, mtime_utc, last_status, updated_at FROM file_ingest_state WHERE path = ?;",
            (str(path),),
        ).fetchone()
        if row is None:
            return True
        status = str(row["last_status"] or "").strip().lower()
        size_changed = int(row["file_size"]) != int(stat.st_size)
        mtime_changed = str(row["mtime_utc"]) != mtime
        if status == "ok":
            return size_changed or mtime_changed

        if size_changed or mtime_changed:
            return True

        # Avoid hot-looping expensive failed files every scan cycle.
        if status == "failed":
            updated_at = str(row["updated_at"] or "").strip()
            if updated_at:
                try:
                    last = datetime.fromisoformat(updated_at.replace(" ", "T"))
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    age_seconds = (datetime.now(timezone.utc) - last.astimezone(timezone.utc)).total_seconds()
                    return age_seconds >= float(self.failed_retry_interval_seconds)
                except Exception:
                    return True
            return True

        return True

    def _upsert_state(self, conn, path: Path, checksum: str, status: str, error: str) -> None:
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO file_ingest_state (path, file_size, mtime_utc, checksum, last_status, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(path) DO UPDATE SET
                file_size = excluded.file_size,
                mtime_utc = excluded.mtime_utc,
                checksum = excluded.checksum,
                last_status = excluded.last_status,
                last_error = excluded.last_error,
                updated_at = datetime('now');
            """,
            (str(path), int(stat.st_size), mtime, checksum or "", status, error or ""),
        )

    def _upsert_state_with_retry(self, conn, path: Path, checksum: str, status: str, error: str) -> None:
        attempts = 4
        for attempt in range(attempts):
            try:
                self._upsert_state(conn, path, checksum, status, error)
                conn.commit()
                return
            except sqlite3.OperationalError as ex:
                if "locked" not in str(ex).lower() or attempt == attempts - 1:
                    raise
                time.sleep(0.15 * float(attempt + 1))
