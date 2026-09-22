"""Live load-progress tracking for Sentinel dataset loads.

The Load flow runs in a background thread with a ``ProgressReporter`` bound
to that thread via :func:`bind`. Deep ingestion code (downloading, digesting,
chunk embedding) emits progress through the module-level helpers — they are
fire-and-forget no-ops whenever no job is bound to the current thread, so
normal (non-job) ingestion is completely unaffected.

Stage bands (percent targets; every report is monotonic and clamped):
    download  2 - 50
    digest    50 - 78
    embed     78 - 98
    finalize  98 - 100
"""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_LOCAL = threading.local()


class LoadCancelled(BaseException):
    """Raised inside deep ingestion when the owner cancels a queued/running load.

    Deliberately a ``BaseException``: the download lanes' broad ``except
    Exception`` blocks must not swallow it, so a cancel stops the whole load
    immediately instead of falling through to the next download attempt.
    """

BANDS: dict[str, tuple[float, float]] = {
    "download": (2.0, 50.0),
    "digest": (50.0, 78.0),
    "embed": (78.0, 98.0),
    "finalize": (98.0, 99.5),
}

_MAX_JOBS = 200
_MAX_EVENTS = 400


class ProgressReporter:
    """Reports stage switches and fractional progress for one load job."""

    def __init__(self, job: dict[str, Any]) -> None:
        self._job = job
        self.job_id = job.get("job_id", "")

    def stage(self, stage: str, message: str | None = None) -> None:
        band = BANDS.get(stage)
        with _LOCK:
            job = self._job
            if band:
                lo, hi = band
                job["stage"] = stage
                job["stage_start"], job["stage_end"] = lo, hi
                if job["percent"] < lo:
                    job["percent"] = lo
            if message:
                job["message"] = str(message)[:300]
            job["updated_at"] = time.time()
            _touch(job)

    def update_meta(self, **fields: Any) -> None:
        """Fill in display metadata (field/source_type/title) once known."""
        with _LOCK:
            for key in ("field", "source_type", "title", "label"):
                if fields.get(key) is not None:
                    self._job[key] = str(fields[key])[:200]
            self._job["updated_at"] = time.time()

    def report(self, fraction: float | None, message: str | None = None) -> None:
        """Advance within the current stage band; ``fraction`` is 0..1."""
        with _LOCK:
            job = self._job
            lo = float(job.get("stage_start") or 0.0)
            hi = float(job.get("stage_end") or 0.0)
            if fraction is not None and hi > lo:
                frac = min(1.0, max(0.0, float(fraction)))
                target = lo + (hi - lo) * frac
                if target > job["percent"]:
                    job["percent"] = target
            if message:
                job["message"] = str(message)[:300]
            job["updated_at"] = time.time()
            _touch(job)


def _touch(job: dict[str, Any]) -> None:
    events = job.setdefault("events", [])
    events.append(
        (round(float(job.get("percent") or 0.0), 1), str(job.get("stage") or ""), str(job.get("message") or ""), time.time())
    )
    if len(events) > _MAX_EVENTS:
        del events[: len(events) - _MAX_EVENTS]


def start_job(
    label: str,
    field: str,
    source_type: str,
    title: str = "",
    candidate_id: int | None = None,
    *,
    initial_state: str = "running",
    initial_message: str = "Preparing load...",
) -> tuple[str, ProgressReporter]:
    job_id = uuid.uuid4().hex[:12]
    job: dict[str, Any] = {
        "job_id": job_id,
        "candidate_id": int(candidate_id) if candidate_id is not None else None,
        "label": str(label)[:200],
        "field": str(field),
        "source_type": str(source_type),
        "title": str(title)[:200],
        "state": initial_state,  # queued | running | done | error
        "stage": "download",
        "percent": 1.0,
        "stage_start": 0.0,
        "stage_end": BANDS["download"][0],
        "message": str(initial_message)[:300],
        "result": None,
        "error": None,
        "created_at": time.time(),
        "started_at": time.time(),
        "finished_at": None,
        "events": [],
    }
    with _LOCK:
        _JOBS[job_id] = job
        if len(_JOBS) > _MAX_JOBS:
            oldest = sorted(_JOBS, key=lambda k: _JOBS[k]["created_at"])
            for k in oldest[: len(_JOBS) - _MAX_JOBS]:
                _JOBS.pop(k, None)
    return job_id, ProgressReporter(job)


@contextmanager
def bind(reporter: ProgressReporter):
    """Bind a reporter to the current thread for the duration of the block."""
    _LOCAL.reporter = reporter
    try:
        yield reporter
    finally:
        _LOCAL.reporter = None


def current() -> ProgressReporter | None:
    return getattr(_LOCAL, "reporter", None)


def emit(stage: str | None = None, message: str | None = None) -> None:
    """Fire-and-forget progress from deep code (no-op without a bound job)."""
    rep = current()
    if rep is None:
        return
    try:
        if stage:
            rep.stage(stage, message)
        elif message:
            rep.report(None, message)
    except Exception:
        pass


def stage(stage: str, message: str | None = None) -> None:
    """Fire-and-forget stage switch (no-op without a bound job)."""
    emit(stage=stage, message=message)


def emit_meta(**fields: Any) -> None:
    """Fire-and-forget metadata update (no-op without a bound job)."""
    rep = current()
    if rep is None:
        return
    try:
        rep.update_meta(**fields)
    except Exception:
        pass


def report_stage_fraction(stage: str, done: int, total: int, message: str | None = None) -> None:
    """Advance ``stage`` by done/total; safe no-op without a bound job."""
    rep = current()
    if rep is None or total <= 0:
        return
    try:
        rep.stage(stage)
        rep.report(min(1.0, max(0.0, done / float(total))), message)
    except Exception:
        pass


def embed_progress(done: int, total: int) -> None:
    """Convenience for the chunk-embedding loop inside the digest stage."""
    rep = current()
    if rep is None or total <= 0:
        return
    try:
        rep.report(done / float(total), f"Embedding chunk {done}/{total}...")
    except Exception:
        pass


def job_reporter(job_id: str) -> ProgressReporter:
    """Return the reporter for an existing job (worker-side accessor)."""
    with _LOCK:
        job = _JOBS[job_id]
    return ProgressReporter(job)


def job_snapshot(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        return {
            "job_id": job["job_id"],
            "candidate_id": job.get("candidate_id"),
            "label": job["label"],
            "field": job["field"],
            "source_type": job["source_type"],
            "title": job["title"],
            "state": job["state"],
            "stage": job["stage"],
            "percent": round(float(job.get("percent") or 0.0), 1),
            "message": job["message"],
            "result": job["result"],
            "error": job["error"],
            "elapsed_ms": int(((job["finished_at"] or time.time()) - job["started_at"]) * 1000),
        }


def finish_job(job_id: str, result: dict[str, Any]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["state"] = "done"
        job["percent"] = 100.0
        job["stage"] = "done"
        job["message"] = "Load complete."
        job["result"] = result
        job["finished_at"] = time.time()


def error_job(job_id: str, error: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["state"] = "error"
        job["error"] = str(error)[:500]
        job["message"] = f"Load failed: {str(error)[:280]}"
        job["finished_at"] = time.time()


def cancel_job(job_id: str, message: str = "Cancelled by owner.") -> bool:
    """Flag a job as cancelled. Cooperative: running pattern-discovery workers
    check the flag at their next document/chunk boundary and exit cleanly."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return False
        job["cancel_requested"] = True
        job["message"] = str(message)[:280]
        return True


def mark_job_running(job_id: str) -> None:
    """Flip a pre-created queued job to running when its worker picks it up."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None and job.get("state") == "queued":
            job["state"] = "running"
            job["started_at"] = time.time()
            job["updated_at"] = time.time()


def cancel_requested() -> bool:
    """True when the job bound to the *current thread* was asked to cancel.

    Deep workers (embed loop, per-work download loops) call this at their
    natural boundaries so a queued/running load can be stopped cleanly."""
    rep = current()
    if rep is None:
        return False
    return is_cancel_requested(rep.job_id)


def is_cancel_requested(job_id: str) -> bool:
    with _LOCK:
        job = _JOBS.get(job_id)
        return bool(job and job.get("cancel_requested"))
