from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def create_video_job(*, job_type: str, title: str = "") -> dict[str, Any]:
    job_id = f"vid-{uuid4().hex[:12]}"
    now = _utc_now()
    job = {
        "ok": True,
        "job_id": job_id,
        "job_type": str(job_type or "video"),
        "title": str(title or "").strip(),
        "status": "queued",
        "progress": 0,
        "message": "Queued.",
        "result": None,
        "error": "",
        "created_at": now,
        "updated_at": now,
        "completed_at": "",
    }
    with _lock:
        _jobs[job_id] = job
    return dict(job)


def update_video_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(str(job_id))
        if job is None:
            return {}
        if status is not None:
            job["status"] = str(status)
        if progress is not None:
            job["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            job["message"] = str(message)
        if result is not None:
            job["result"] = result
        if error is not None:
            job["error"] = str(error)
        job["updated_at"] = _utc_now()
        if str(job.get("status")) in {"done", "error"} and not job.get("completed_at"):
            job["completed_at"] = job["updated_at"]
        return dict(job)


def get_video_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(str(job_id))
        return dict(job) if job else None


def list_video_jobs(limit: int = 12) -> list[dict[str, Any]]:
    with _lock:
        items = sorted(_jobs.values(), key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return [dict(item) for item in items[: max(1, min(100, int(limit or 12)))]]
