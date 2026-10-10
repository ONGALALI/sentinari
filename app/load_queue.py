"""Sequential background load queue for Sentinel dataset loads.

Owner directive: multiple candidate loads can be lined up and are processed
**one at a time** automatically — the safe pattern for the small machine, and
a precursor to unattended batch loading on the new rig.

Design:
- Single worker thread ⇒ two loads can never overlap (the freeze-era guard).
- Each entry pre-creates its live progress job at enqueue time, so the UI can
  show "Queued — position N" immediately and keep polling the same job id
  once the worker starts it.
- Queued entries cancel instantly; a running load is cancelled cooperatively
  at the next chunk boundary (the embed loop checks the flag).
- The queue itself is per-session (in-memory); the underlying candidate rows
  persist, so a restart never loses what was approved — only the lineup.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any

from . import load_progress

_MAX_QUEUE = 25
_MAX_FINISHED = 60


class LoadQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._seq = 0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(target=self._loop, name="load-queue", daemon=True)
            self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def enqueue(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Line a stored candidate up for loading; returns the queue entry."""
        self.start()
        candidate_id = int(candidate.get("id") or 0)
        if candidate_id <= 0:
            raise ValueError("Candidate has no database id; cannot queue it.")
        with self._lock:
            for entry in self._entries:
                if entry["candidate_id"] == candidate_id and entry["state"] in ("queued", "running"):
                    return {**entry, "already_queued": True}
            if sum(1 for e in self._entries if e["state"] == "queued") >= _MAX_QUEUE:
                raise ValueError(f"The load queue is full ({_MAX_QUEUE} waiting). Let it drain first.")
            self._seq += 1
            entry: dict[str, Any] = {
                "entry_id": f"q{self._seq}",
                "candidate_id": candidate_id,
                "title": str(candidate.get("title") or f"Candidate {candidate_id}")[:200],
                "field": str(candidate.get("scientific_field") or "")[:80],
                "source_type": str(candidate.get("source_type") or "")[:40],
                "state": "queued",  # queued | running | done | error | cancelled
                "position": sum(1 for e in self._entries if e["state"] == "queued") + 1,
                "enqueued_at": time.time(),
                "started_at": None,
                "finished_at": None,
                "job_id": None,
                "error": None,
                "summary": None,
            }
            self._entries.append(entry)
            self._trim_finished_locked()
        self._wake.set()
        return dict(entry)

    def cancel(self, entry_id: str) -> dict[str, Any]:
        with self._lock:
            entry = next((e for e in self._entries if e["entry_id"] == str(entry_id)), None)
            if entry is None:
                return {"ok": False, "error": "Unknown queue entry."}
            state = entry["state"]
            if state == "queued":
                entry["state"] = "cancelled"
                entry["finished_at"] = time.time()
                entry["error"] = "Cancelled while queued."
                job_id = entry.get("job_id")
            elif state == "running":
                job_id = entry.get("job_id")
            else:
                return {"ok": False, "error": f"Entry already {state}."}
        if state == "queued" and job_id:
            # Close the progress job so any card polling it stops cleanly.
            load_progress.cancel_job(job_id, "Cancelled while queued.")
            load_progress.error_job(job_id, "Cancelled by owner while queued.")
        elif state == "running" and job_id:
            load_progress.cancel_job(job_id, "Cancel requested — stopping at the next chunk boundary.")
        return {"ok": True, "entry_id": str(entry_id), "state": state}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            entries = [dict(e) for e in self._entries]
        for entry in entries:
            job_id = entry.get("job_id")
            if job_id:
                snap = load_progress.job_snapshot(str(job_id))
                if snap is not None:
                    entry["progress"] = {
                        "state": snap.get("state"),
                        "stage": snap.get("stage"),
                        "percent": snap.get("percent"),
                        "message": snap.get("message"),
                    }
        queued = sum(1 for e in entries if e["state"] == "queued")
        running = sum(1 for e in entries if e["state"] == "running")
        return {
            "ok": True,
            "queued": queued,
            "running": running,
            "entries": entries[-( _MAX_FINISHED + _MAX_QUEUE ):],
        }

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------
    def _loop(self) -> None:
        from .skill_review import _ingest_with_lock_armor  # deferred: avoids circular import

        while not self._stop.is_set():
            entry = None
            with self._lock:
                entry = next((e for e in self._entries if e["state"] == "queued"), None)
            if entry is None:
                self._wake.wait(1.0)
                self._wake.clear()
                continue

            job_id = None
            try:
                candidate_id = int(entry["candidate_id"])
                job_id, _rep = load_progress.start_job(
                    label=f"Queue load candidate {candidate_id}",
                    field=str(entry.get("field") or ""),
                    source_type=str(entry.get("source_type") or ""),
                    title=str(entry.get("title") or ""),
                    candidate_id=candidate_id,
                )
                with self._lock:
                    entry["job_id"] = job_id
                    entry["state"] = "running"
                    entry["started_at"] = time.time()
                    entry["position"] = 0
                load_progress.mark_job_running(job_id)
                rep = load_progress.job_reporter(job_id)
                # §39: the Learning Index's background exams must not compete
                # with a load for the LLM and the database on the small
                # machine (lock storms during loads were part of the owner's
                # 4–8 reload problem). The examiner pauses for the load and
                # is ALWAYS restored in finally.
                from .learning_index import learning_enabled as _li_enabled, _set_setting as _li_set

                _li_was_on = _li_enabled()
                if _li_was_on:
                    _li_set("learning_enabled", "off")
                try:
                    with load_progress.bind(rep):
                        # §74j: same lock armor as the legacy worker — a
                        # transient 'database is locked' now rides itself out
                        # with a calm progress message instead of surfacing
                        # as a scary failed entry the owner must re-click.
                        result = _ingest_with_lock_armor(candidate_id, rep)
                finally:
                    if _li_was_on:
                        _li_set("learning_enabled", "on")
                ingested_count = int(result.get("ingested") or 0)
                failed_count = int(result.get("failed") or 0)
                if ingested_count <= 0:
                    err_notes = [
                        str(it.get("error") or it.get("note") or "")
                        for it in (result.get("items") or [])
                        if isinstance(it, dict) and not it.get("ok") and (it.get("error") or it.get("note"))
                    ]
                    err_msg = err_notes[-1] if err_notes else f"Ingested 0 documents ({failed_count or 1} failed)."
                    load_progress.error_job(job_id, err_msg)
                    with self._lock:
                        entry["state"] = "error"
                        entry["finished_at"] = time.time()
                        entry["error"] = err_msg[:500]
                        entry["summary"] = {
                            "ingested": 0,
                            "failed": failed_count or 1,
                            "document_id": None,
                            "candidate_status": result.get("candidate_status") or "failed",
                        }
                else:
                    load_progress.finish_job(job_id, result)
                    with self._lock:
                        entry["state"] = "done"
                        entry["finished_at"] = time.time()
                        entry["summary"] = {
                            "ingested": ingested_count,
                            "failed": failed_count,
                            "document_id": result.get("document_id"),
                            "candidate_status": result.get("candidate_status"),
                        }
            except load_progress.LoadCancelled as ex:
                if job_id:
                    load_progress.error_job(job_id, str(ex) or "Cancelled by owner.")
                with self._lock:
                    entry["state"] = "cancelled"
                    entry["finished_at"] = time.time()
                    entry["error"] = str(ex)[:500]
            except Exception as ex:
                message = str(ex) or ex.__class__.__name__
                if job_id:
                    load_progress.error_job(job_id, message)
                with self._lock:
                    entry["state"] = "error"
                    entry["finished_at"] = time.time()
                    entry["error"] = message[:500]
                traceback.print_exc()
            finally:
                self._wake.set()  # nudge the next iteration promptly

    def _trim_finished_locked(self) -> None:
        finished = [e for e in self._entries if e["state"] in ("done", "error", "cancelled")]
        if len(finished) > _MAX_FINISHED:
            for entry in finished[: len(finished) - _MAX_FINISHED]:
                self._entries.remove(entry)


_QUEUE = LoadQueue()


def get_load_queue() -> LoadQueue:
    return _QUEUE
