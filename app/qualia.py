from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .config import get_settings


DEFAULT_ALPHA = 0.5
DEFAULT_BETA = 0.3
DEFAULT_GAMMA = 0.2
DEFAULT_GAMMA_CAP = 0.25
DEFAULT_STEPS = 20
DEFAULT_STABILITY_BIAS = 0.65
DEFAULT_BELL_MU = 0.5
DEFAULT_BELL_SIGMA = 0.18
DEFAULT_BELL_AMPLITUDE = 1.0
NORMALIZATION_EPSILON = 1e-9

_ALPHA_PATTERN = re.compile(r"(?:alpha|α)\s*=\s*([-+]?\d*\.?\d+)", re.IGNORECASE)
_BETA_PATTERN = re.compile(r"(?:beta|β)\s*=\s*([-+]?\d*\.?\d+)", re.IGNORECASE)
_GAMMA_PATTERN = re.compile(r"(?:gamma|γ)\s*=\s*([-+]?\d*\.?\d+)", re.IGNORECASE)


def _to_bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = float(default)
    if not math.isfinite(parsed):
        parsed = float(default)
    return max(float(minimum), min(float(maximum), float(parsed)))


def _to_bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = int(default)
    return max(int(minimum), min(int(maximum), int(parsed)))


def _first_match_or_default(pattern: re.Pattern[str], text: str, default: float) -> float:
    match = pattern.search(text or "")
    if match is None:
        return float(default)
    return _to_bounded_float(match.group(1), default=default, minimum=0.0, maximum=1.0)


def _read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", namespace):
        parts = [node.text or "" for node in para.findall(".//w:t", namespace)]
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs).strip()


def _read_qualia_source_text(path: Path) -> str:
    ext = path.suffix.lower().strip()
    if ext == ".docx":
        return _read_docx_text(path)
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def load_qualia_block(
    *,
    settings: dict[str, Any] | None = None,
    max_chars_per_file: int = 6500,
) -> tuple[str, list[str]]:
    source = settings if isinstance(settings, dict) else get_settings()
    paths = source.get("paths", {})
    files = paths.get("qualia_files") if isinstance(paths, dict) else []
    if not isinstance(files, list):
        files = []

    blocks: list[str] = []
    loaded_paths: list[str] = []
    for raw in files:
        path = Path(str(raw or "").strip())
        if not path.exists() or not path.is_file():
            continue
        try:
            text = _read_qualia_source_text(path)
        except Exception:
            continue
        if not text:
            continue
        clipped = text[: max(200, int(max_chars_per_file))]
        blocks.append(f"[QualiaSource: {path.name}]\n{clipped}")
        loaded_paths.append(str(path.resolve()))
    return "\n\n".join(blocks).strip(), loaded_paths


def extract_qualia_parameters(
    qualia_text: str,
    *,
    gamma_cap: float = DEFAULT_GAMMA_CAP,
) -> dict[str, float]:
    alpha = _first_match_or_default(_ALPHA_PATTERN, qualia_text, DEFAULT_ALPHA)
    beta = _first_match_or_default(_BETA_PATTERN, qualia_text, DEFAULT_BETA)
    gamma_requested = _first_match_or_default(_GAMMA_PATTERN, qualia_text, DEFAULT_GAMMA)
    cap = _to_bounded_float(gamma_cap, default=DEFAULT_GAMMA_CAP, minimum=0.0, maximum=DEFAULT_GAMMA_CAP)
    gamma_effective = _to_bounded_float(gamma_requested, default=DEFAULT_GAMMA, minimum=0.0, maximum=cap)
    return {
        "alpha": alpha,
        "beta": beta,
        "gamma_requested": gamma_requested,
        "gamma": gamma_effective,
        "gamma_cap": cap,
    }


def _clip_unit(value: float) -> float:
    return _to_bounded_float(value, default=0.0, minimum=-1.0, maximum=1.0)


def _clip_ratio(value: float) -> float:
    return _to_bounded_float(value, default=0.0, minimum=0.0, maximum=1.0)


def _vector_norm(vec: tuple[float, float, float]) -> float:
    return math.sqrt((vec[0] ** 2) + (vec[1] ** 2) + (vec[2] ** 2))


def _clip_bloch_vector(vec: tuple[float, float, float]) -> tuple[float, float, float]:
    x = _clip_unit(vec[0])
    y = _clip_unit(vec[1])
    z = _clip_unit(vec[2])
    norm = _vector_norm((x, y, z))
    if norm <= 1.0 + 1e-9:
        return x, y, z
    if norm <= 1e-9:
        return 0.0, 0.0, 0.0
    scale = 1.0 / norm
    return x * scale, y * scale, z * scale


def _mix_vectors(
    own: tuple[float, float, float],
    sensory: tuple[float, float, float],
    cross: tuple[float, float, float],
    alpha: float,
    beta: float,
    gamma: float,
) -> tuple[float, float, float]:
    return (
        (alpha * own[0]) + (beta * sensory[0]) + (gamma * cross[0]),
        (alpha * own[1]) + (beta * sensory[1]) + (gamma * cross[1]),
        (alpha * own[2]) + (beta * sensory[2]) + (gamma * cross[2]),
    )


def _rotate_x(vec: tuple[float, float, float], theta: float) -> tuple[float, float, float]:
    c = math.cos(theta)
    s = math.sin(theta)
    x, y, z = vec
    return x, (c * y) - (s * z), (s * y) + (c * z)


def _rotate_y(vec: tuple[float, float, float], theta: float) -> tuple[float, float, float]:
    c = math.cos(theta)
    s = math.sin(theta)
    x, y, z = vec
    return (c * x) + (s * z), y, (-s * x) + (c * z)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def _std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    avg = _mean(values)
    variance = sum((v - avg) ** 2 for v in values) / float(len(values))
    return math.sqrt(max(0.0, variance))


def _mean_abs_delta(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    deltas = [abs(values[idx] - values[idx - 1]) for idx in range(1, len(values))]
    return _mean(deltas)


def _gaussian_weight(x: float, mu: float, sigma: float, amplitude: float) -> float:
    sigma_safe = max(0.02, float(sigma))
    exponent = -0.5 * (((float(x) - float(mu)) / sigma_safe) ** 2)
    return _clip_ratio(float(amplitude) * math.exp(exponent))


def build_bell_curve_profile(
    *,
    behavior_variant: float,
    mu: float = DEFAULT_BELL_MU,
    sigma: float = DEFAULT_BELL_SIGMA,
    amplitude: float = DEFAULT_BELL_AMPLITUDE,
    points: int = 61,
) -> dict[str, Any]:
    mu_safe = _clip_ratio(mu)
    sigma_safe = _to_bounded_float(sigma, default=DEFAULT_BELL_SIGMA, minimum=0.02, maximum=0.5)
    amp_safe = _clip_ratio(amplitude)
    count = _to_bounded_int(points, default=61, minimum=11, maximum=401)

    variant = _to_bounded_float(behavior_variant, default=0.1, minimum=0.1, maximum=25.0)
    variant_norm = (variant - 0.1) / 24.9
    weight_at_variant = _gaussian_weight(variant_norm, mu_safe, sigma_safe, amp_safe)

    series: list[dict[str, float]] = []
    if count <= 1:
        count = 2
    for idx in range(count):
        x_norm = float(idx) / float(count - 1)
        x_variant = 0.1 + (24.9 * x_norm)
        series.append(
            {
                "variant": round(x_variant, 4),
                "x_norm": round(x_norm, 6),
                "weight": round(_gaussian_weight(x_norm, mu_safe, sigma_safe, amp_safe), 6),
            }
        )

    return {
        "mu": mu_safe,
        "sigma": sigma_safe,
        "amplitude": amp_safe,
        "weight_at_variant": weight_at_variant,
        "variant_normalized": variant_norm,
        "points": series,
    }


def simulate_qualia_dynamics(
    *,
    alpha: float,
    beta: float,
    gamma: float,
    steps: int = DEFAULT_STEPS,
    q0: tuple[float, float, float] = (0.0, 0.0, 1.0),
    a0: tuple[float, float, float] = (1.0, 0.0, 0.0),
    sensory: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> dict[str, Any]:
    a = max(0.0, float(alpha))
    b = max(0.0, float(beta))
    g = max(0.0, float(gamma))
    total = a + b + g
    normalization_fallback = total <= NORMALIZATION_EPSILON
    if normalization_fallback:
        # A zero vector carries no evidence for preferring any coupling term.
        # Use a neutral simplex point rather than silently restoring tuned defaults.
        a, b, g = 1.0, 1.0, 1.0
        total = 3.0

    alpha_w = a / total
    beta_w = b / total
    gamma_w = g / total
    n_steps = _to_bounded_int(steps, default=DEFAULT_STEPS, minimum=1, maximum=240)

    q_vec = _clip_bloch_vector(q0)
    a_vec = _clip_bloch_vector(a0)
    s_vec = _clip_bloch_vector(sensory)

    trajectory: list[dict[str, float]] = []
    for t in range(n_steps + 1):
        trajectory.append(
            {
                "t": float(t),
                "q_x": round(q_vec[0], 6),
                "q_y": round(q_vec[1], 6),
                "q_z": round(q_vec[2], 6),
                "a_x": round(a_vec[0], 6),
                "a_y": round(a_vec[1], 6),
                "a_z": round(a_vec[2], 6),
            }
        )
        if t >= n_steps:
            break

        q_mix = _mix_vectors(q_vec, s_vec, a_vec, alpha_w, beta_w, gamma_w)
        a_mix = _mix_vectors(a_vec, s_vec, q_vec, alpha_w, beta_w, gamma_w)
        theta_q = a_vec[0] * (math.pi / 2.0)
        theta_a = q_vec[1] * (math.pi / 2.0)
        q_vec = _clip_bloch_vector(_rotate_x(q_mix, theta_q))
        a_vec = _clip_bloch_vector(_rotate_y(a_mix, theta_a))

    q_z = [float(row["q_z"]) for row in trajectory]
    a_z = [float(row["a_z"]) for row in trajectory]
    a_x = [float(row["a_x"]) for row in trajectory]
    q_volatility = _clip_ratio(_mean_abs_delta(q_z))
    a_volatility = _clip_ratio(_mean_abs_delta(a_z))
    volatility = _clip_ratio((q_volatility + a_volatility) / 2.0)
    attention_pull = _clip_ratio(_mean([abs(v) for v in a_x]))
    stability_index = _clip_ratio(1.0 - volatility)

    summary = {
        "q_z_start": float(q_z[0]) if q_z else 0.0,
        "q_z_end": float(q_z[-1]) if q_z else 0.0,
        "a_z_start": float(a_z[0]) if a_z else 0.0,
        "a_z_end": float(a_z[-1]) if a_z else 0.0,
        "q_z_min": float(min(q_z)) if q_z else 0.0,
        "q_z_max": float(max(q_z)) if q_z else 0.0,
        "a_z_min": float(min(a_z)) if a_z else 0.0,
        "a_z_max": float(max(a_z)) if a_z else 0.0,
        "q_z_std": float(_std(q_z)),
        "a_z_std": float(_std(a_z)),
        "volatility": volatility,
        "attention_pull": attention_pull,
        "stability_index": stability_index,
    }

    return {
        "model_scope": "coupled_state_vector_simulation",
        "measurement_status": "not_a_psychological_or_phenomenal_measurement",
        "normalization_fallback": normalization_fallback,
        "steps": n_steps,
        "weights_normalized": {
            "alpha": alpha_w,
            "beta": beta_w,
            "gamma": gamma_w,
        },
        "trajectory": trajectory,
        "summary": summary,
    }


def resolve_qualia_runtime(
    *,
    settings: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    behavior_variant: float = 0.1,
    max_chars_per_file: int = 6500,
    gamma_cap: float = DEFAULT_GAMMA_CAP,
) -> dict[str, Any]:
    base = resolve_qualia_profile(
        settings=settings,
        max_chars_per_file=max_chars_per_file,
        gamma_cap=gamma_cap,
    )
    raw = overrides if isinstance(overrides, dict) else {}
    control_enabled = bool(raw.get("enabled", True))

    cap = _to_bounded_float(raw.get("gamma_cap", base.get("gamma_cap", gamma_cap)), DEFAULT_GAMMA_CAP, 0.0, DEFAULT_GAMMA_CAP)
    alpha = _to_bounded_float(raw.get("alpha", base.get("alpha", DEFAULT_ALPHA)), DEFAULT_ALPHA, 0.0, 1.0)
    beta = _to_bounded_float(raw.get("beta", base.get("beta", DEFAULT_BETA)), DEFAULT_BETA, 0.0, 1.0)
    gamma_requested = _to_bounded_float(raw.get("gamma", base.get("gamma_requested", DEFAULT_GAMMA)), DEFAULT_GAMMA, 0.0, 1.0)
    gamma_effective = _to_bounded_float(gamma_requested, DEFAULT_GAMMA, 0.0, cap)
    if not control_enabled:
        gamma_effective = 0.0

    steps = _to_bounded_int(raw.get("steps", DEFAULT_STEPS), DEFAULT_STEPS, 1, 240)
    q0 = (
        _to_bounded_float(raw.get("q0_x", 0.0), 0.0, -1.0, 1.0),
        _to_bounded_float(raw.get("q0_y", 0.0), 0.0, -1.0, 1.0),
        _to_bounded_float(raw.get("q0_z", 1.0), 1.0, -1.0, 1.0),
    )
    a0 = (
        _to_bounded_float(raw.get("a0_x", 1.0), 1.0, -1.0, 1.0),
        _to_bounded_float(raw.get("a0_y", 0.0), 0.0, -1.0, 1.0),
        _to_bounded_float(raw.get("a0_z", 0.0), 0.0, -1.0, 1.0),
    )
    sensory = (
        _to_bounded_float(raw.get("s_x", 0.0), 0.0, -1.0, 1.0),
        _to_bounded_float(raw.get("s_y", 0.0), 0.0, -1.0, 1.0),
        _to_bounded_float(raw.get("s_z", 0.0), 0.0, -1.0, 1.0),
    )

    simulation = simulate_qualia_dynamics(
        alpha=alpha,
        beta=beta,
        gamma=gamma_effective,
        steps=steps,
        q0=q0,
        a0=a0,
        sensory=sensory,
    )
    summary = simulation.get("summary", {}) if isinstance(simulation.get("summary"), dict) else {}

    gamma_norm = 0.0 if cap <= 1e-9 else _clip_ratio(gamma_effective / cap)
    volatility = _clip_ratio(summary.get("volatility", 0.0))
    attention_pull = _clip_ratio(summary.get("attention_pull", 0.0))
    influence = _clip_ratio((0.55 * gamma_norm) + (0.25 * volatility) + (0.20 * attention_pull))
    if not control_enabled:
        influence = 0.0

    stability_index = _clip_ratio(summary.get("stability_index", 1.0))
    stability_bias = _clip_ratio(raw.get("stability_bias", DEFAULT_STABILITY_BIAS))
    stability_gate = _to_bounded_float(
        (1.0 - stability_bias) + (stability_bias * stability_index),
        default=1.0,
        minimum=0.35,
        maximum=1.0,
    )
    if not control_enabled:
        stability_gate = 1.0

    bell_profile = build_bell_curve_profile(
        behavior_variant=behavior_variant,
        mu=_to_bounded_float(raw.get("bell_mu", DEFAULT_BELL_MU), DEFAULT_BELL_MU, 0.0, 1.0),
        sigma=_to_bounded_float(raw.get("bell_sigma", DEFAULT_BELL_SIGMA), DEFAULT_BELL_SIGMA, 0.02, 0.5),
        amplitude=_to_bounded_float(raw.get("bell_amplitude", DEFAULT_BELL_AMPLITUDE), DEFAULT_BELL_AMPLITUDE, 0.0, 1.0),
        points=_to_bounded_int(raw.get("bell_points", 61), 61, 11, 401),
    )
    if not control_enabled:
        bell_profile["weight_at_variant"] = 0.0

    parameters = {
        "alpha": alpha,
        "beta": beta,
        "gamma_requested": gamma_requested,
        "gamma_effective": gamma_effective,
        "gamma_cap": cap,
        "steps": steps,
        "stability_bias": stability_bias,
    }
    vectors = {
        "q0_x": q0[0],
        "q0_y": q0[1],
        "q0_z": q0[2],
        "a0_x": a0[0],
        "a0_y": a0[1],
        "a0_z": a0[2],
        "s_x": sensory[0],
        "s_y": sensory[1],
        "s_z": sensory[2],
    }

    return {
        "model_scope": "coupled_state_vector_simulation",
        "measurement_status": "exploratory_unvalidated",
        "external_validation_required": True,
        "enabled": bool(base.get("enabled")) and control_enabled,
        "controls_enabled": control_enabled,
        "source_count": int(base.get("source_count") or 0),
        "source_files": base.get("source_files") or [],
        "qualia_block": base.get("qualia_block") or "",
        "alpha": alpha,
        "beta": beta,
        "gamma_requested": gamma_requested,
        "gamma": gamma_effective,
        "gamma_cap": cap,
        "parameters": parameters,
        "vectors": vectors,
        "simulation": simulation,
        "trajectory": simulation.get("trajectory") or [],
        "summary": summary,
        "influence": influence,
        "stability_index": stability_index,
        "stability_gate": stability_gate,
        "bell_curve": bell_profile,
    }


def resolve_qualia_profile(
    *,
    settings: dict[str, Any] | None = None,
    max_chars_per_file: int = 6500,
    gamma_cap: float = DEFAULT_GAMMA_CAP,
) -> dict[str, Any]:
    qualia_block, loaded_paths = load_qualia_block(settings=settings, max_chars_per_file=max_chars_per_file)
    params = extract_qualia_parameters(qualia_block, gamma_cap=gamma_cap)
    return {
        "enabled": bool(qualia_block),
        "source_count": len(loaded_paths),
        "source_files": loaded_paths,
        "qualia_block": qualia_block,
        **params,
    }
