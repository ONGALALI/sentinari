"""Offline behavioral checks for the qr-v2 recommendation rewrite."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.qualia_recommendation import build_qualia_recommendation  # noqa: E402


def call(question, answer, citations=None, qualia=None, variant=1.0, gamma=0.2, bias=0.65, cap=0.25):
    return build_qualia_recommendation(
        question=question,
        answer=answer,
        citations=citations or [],
        qualia=qualia or {},
        current_variant=variant,
        current_gamma=gamma,
        current_stability_bias=bias,
        gamma_cap=cap,
        settings={},
    )


def main() -> int:
    failures = []

    # 1. Word-boundary integrity: "however" must NOT trigger the "how" token.
    plain = call("What is X?", "X is a constant.")
    however = call("However defined is X?", "X is a constant.")
    r_plain = plain["focus_scores"]["reasoning_demand"]
    r_however = however["focus_scores"]["reasoning_demand"]
    if r_plain != 0.0 or r_however != 0.0:
        failures.append(f"word-boundary bug: 'However' should score 0 demand like 'What is X?' ({r_plain} vs {r_however})")

    # 2. Genuine demand terms still count, and saturate.
    one = call("How do we explain conduction?", "Heat flows.")
    two = call("How and why should we explain and compare conduction, and justify the analysis?", "Heat flows.")
    d_one = one["focus_scores"]["reasoning_demand"]
    d_two = two["focus_scores"]["reasoning_demand"]
    if not (0.30 < d_one < 0.36):  # 2 tokens: 1-exp(-2/5) ≈ 0.3297
        failures.append(f"two demand tokens should give ~0.330, got {d_one}")
    if not (d_two > d_one):
        failures.append(f"more demand tokens should raise the index ({d_two} <= {d_one})")
    if d_two > 0.7:
        failures.append(f"demand should saturate smoothly, got {d_two}")

    # 3. No double-counting: composites are now disjoint. Reasoning no longer
    #    includes citations or answer length; check citations do not move reasoning.
    no_cit = call("Explain the mechanism.", "Long answer. " * 40)
    with_cit = call("Explain the mechanism.", "Long answer. " * 40, citations=["a", "b", "c", "d"])
    rs_no = no_cit["focus_scores"]["reasoning"]
    rs_cit = with_cit["focus_scores"]["reasoning"]
    if rs_cit != rs_no:
        failures.append(f"double-count leak: citations changed reasoning score ({rs_no} -> {rs_cit})")
    g_no = no_cit["focus_scores"]["grounding"]
    g_cit = with_cit["focus_scores"]["grounding"]
    if not (g_cit > g_no):
        failures.append(f"citations should raise grounding ({g_no} -> {g_cit})")

    # 4. Confidence: ceiling 0.85, floor 0.20; strong info -> high, empty -> low.
    strong = call(
        "Explain why the mechanism fails, and compare it with the standard model in detail.",
        " ".join(["The mechanism fails because the gradient collapses; therefore the conclusion follows from the premise."] * 6),
        citations=["s1", "s2", "s3"],
        qualia={"stability_index": 0.9, "summary": {"attention_pull": 0.8}},
    )
    weak = call("", "")
    if strong["confidence"] <= weak["confidence"]:
        failures.append(f"confidence ordering wrong: strong {strong['confidence']} <= weak {weak['confidence']}")
    if weak["confidence"] < 0.20 or strong["confidence"] > 0.85:
        failures.append(f"confidence outside bounds: weak={weak['confidence']} strong={strong['confidence']}")

    # 5. Confidence-gated damping: the strong case must move the variant further than the weak one.
    if abs(strong["delta"]) <= abs(weak["delta"]):
        failures.append(f"damping gate wrong: strong delta {strong['delta']} <= weak delta {weak['delta']}")

    # 6. should_apply requires meaningful shift AND concern AND adequate confidence.
    sa_strong = strong["should_apply"]
    sa_weak = weak["should_apply"]
    if sa_weak:
        failures.append("weak/empty exchange must not propose applying changes")
    if not isinstance(sa_strong, bool):
        failures.append("should_apply must be a boolean")

    # 7. Determinism: identical inputs -> identical outputs (no hidden state).
    a = call("Explain why and how the model works.", "Because therefore thus. 1. step\n2. step\n3. step", citations=["x"], qualia={"stability_index": 0.5})
    b = call("Explain why and how the model works.", "Because therefore thus. 1. step\n2. step\n3. step", citations=["x"], qualia={"stability_index": 0.5})
    if a != b:
        failures.append("non-deterministic output between identical calls")

    # 8. Legacy keys still present for API/history compatibility.
    required = ["variant", "gamma", "stability_bias", "delta", "confidence", "focus_scores", "reason", "should_apply", "model_scope", "measurement_status"]
    for key in required:
        if key not in strong:
            failures.append(f"missing legacy key: {key}")

    # 9. Extreme inputs are safely clipped (no exceptions, no NaN out of range).
    try:
        wild = call("why " * 500, "because " * 2000, citations=list("abcdefghij"), qualia={"stability_index": 7.5, "summary": {"attention_pull": 42}}, variant=99, gamma=5, bias=-3, cap=2)
        for name in ("reasoning", "logic", "attention", "anxiety", "gamma"):
            v = wild["focus_scores"][name]
            if not (0.0 <= v <= 1.0):
                failures.append(f"focus score {name} out of range: {v}")
        if not (0.0 <= wild["confidence"] <= 0.85):
            failures.append(f"confidence out of range: {wild['confidence']}")
        if not (0.1 <= wild["variant"] <= 25.0):
            failures.append(f"variant out of range: {wild['variant']}")
        if not (0.0 <= wild["gamma"] <= 0.25):
            failures.append(f"gamma out of range: {wild['gamma']}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"extreme inputs raised: {exc}")

    if failures:
        print("FAIL")
        for item in failures:
            print(" -", item)
        return 1
    print("PASS: 9/9 behavioral checks green (boundaries, saturation, no double-count, confidence gate, determinism, compat, extremes)")
    print("sample strong:", {k: strong[k] for k in ("variant", "gamma", "stability_bias", "confidence", "should_apply")})
    print("sample weak:  ", {k: weak[k] for k in ("variant", "gamma", "stability_bias", "confidence", "should_apply")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
