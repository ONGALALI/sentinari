from __future__ import annotations

from pathlib import Path
from typing import Any

# NOTE: Video Lab is intentionally stubbed out for now. These functions exist
# only so that `main.py` can import successfully and the rest of SMi (chat,
# SMI link, ingestion, etc.) keeps working. Nothing here does real video
# rendering yet — each function returns a clear "disabled" response instead
# of raising an ImportError at startup.

_DISABLED_MESSAGE = "Video Lab is not implemented yet. This feature is intentionally disabled."


def get_video_lab_status() -> dict[str, Any]:
    return {"ok": True, "enabled": False, "message": _DISABLED_MESSAGE}


def get_wan_video_status() -> dict[str, Any]:
    return {"ok": True, "enabled": False, "message": _DISABLED_MESSAGE}


def build_plan_from_prompt(
    *,
    prompt: str = "",
    language: str = "",
    fps: int | float | None = None,
    max_scenes: int | None = None,
) -> dict[str, Any]:
    raise ValueError(_DISABLED_MESSAGE)


def render_text_plan(plan: dict[str, Any], *, filename_hint: str = "") -> dict[str, Any]:
    raise RuntimeError(_DISABLED_MESSAGE)


def render_wan_text_video(
    *,
    prompt: str = "",
    task: str = "",
    size: str = "",
    ckpt_dir: str = "",
    wan_repo_dir: str = "",
    wan_python: str = "",
    offload_model: bool | None = None,
    t5_cpu: bool | None = None,
    sample_steps: int | None = None,
    sample_shift: float | None = None,
    sample_guide_scale: float | None = None,
    base_seed: int | None = None,
    timeout_seconds: int | None = None,
    filename_hint: str = "",
) -> dict[str, Any]:
    raise RuntimeError(_DISABLED_MESSAGE)


def render_stitched_images(
    *,
    input_dir: str = "",
    seconds_per_image: float | None = None,
    fps: int | float | None = None,
    width: int | None = None,
    height: int | None = None,
    filename_hint: str = "",
) -> dict[str, Any]:
    raise RuntimeError(_DISABLED_MESSAGE)


def resolve_output_file(file_name: str) -> Path | None:
    return None
