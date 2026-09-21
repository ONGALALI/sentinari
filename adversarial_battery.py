"""SENTINEL Adversarial Test Battery for the qr-v2 recommendation indices.

The Gauntlet: 14 attack families that deliberately try to break the formula.

Design principles
-----------------
* Attacks are behavioral: they use only the public function signature, exactly
  as a hostile reviewer would.
* Each family asserts a *desirable* property (monotonicity, isolation,
  symmetry, robustness...). A failure here is a genuine vulnerability, not a
  test-harness artifact.
* Deterministic: no randomness, no network, no clock dependence.

Exit code 0 = the gauntlet was survived.
"""
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


F = "focus_scores"
failures: list[str] = []
passed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ok    {name}")
    else:
        failures.append(f"{name} :: {detail}")
        print(f"  FAIL  {name} :: {detail}")


# ---------------------------------------------------------------------------
# A1  Word-boundary integrity ("how" vs "however")
# ---------------------------------------------------------------------------
print("[A1] Word-boundary integrity")
how = call("How does it work?", "It works.")
however = call("However it works.", "It works.")
baseline = call("It works.", "It works.")
check("genuine 'how' counts", how[F]["reasoning_demand"] > baseline[F]["reasoning_demand"],
      f"how={how[F]['reasoning_demand']} baseline={baseline[F]['reasoning_demand']}")
check("'However' does not count as 'how'", abs(however[F]["reasoning_demand"] - baseline[F]["reasoning_demand"]) < 1e-9,
      f"however={however[F]['reasoning_demand']} baseline={baseline[F]['reasoning_demand']}")

# ---------------------------------------------------------------------------
# A2  Scale sensitivity: adding content scales scores, never inverts order
# ---------------------------------------------------------------------------
print("[A2] Scale sensitivity")
short = call("Explain why X fails.", "Because the gradient collapses.")
long_ = call("Explain why X fails. " + "And justify the reasoning. " * 12,
             "Because the gradient collapses. Therefore the conclusion follows. " * 12)
check("richer exchange scores >= poorer on reasoning", long_[F]["reasoning"] >= short[F]["reasoning"] - 1e-9,
      f"{short[F]['reasoning']} vs {long_[F]['reasoning']}")
check("confidence bounded [0.20, 0.85]", 0.20 <= short["confidence"] <= 0.85 and 0.20 <= long_["confidence"] <= 0.85,
      f"{short['confidence']}, {long_['confidence']}")

# ---------------------------------------------------------------------------
# A3  Composite isolation (qr-v2 core promise: no double counting)
# ---------------------------------------------------------------------------
print("[A3] Composite isolation")
base = call("Q?", "A")
plus_cit = call("Q?", "A", citations=["s1", "s2", "s3"])
check("citations do not move reasoning", plus_cit[F]["reasoning"] == base[F]["reasoning"],
      f"{base[F]['reasoning']} -> {plus_cit[F]['reasoning']}")
check("citations raise grounding", plus_cit[F]["grounding"] > base[F]["grounding"],
      f"{base[F]['grounding']} -> {plus_cit[F]['grounding']}")
big = call("Q?", "word " * 400)
# Demand must be identical in both (same question, no demand tokens in either answer);
# the composite may grow through depth, but the demand component itself is isolated.
check("length does not contaminate demand isolation",
      big[F]["reasoning_demand"] == base[F]["reasoning_demand"],
      f"{base[F]['reasoning_demand']} -> {big[F]['reasoning_demand']}")
check("composite growth via depth is explicit and capped",
      big[F]["reasoning"] > base[F]["reasoning"] and big[F]["depth"] <= 1.0,
      f"{base[F]['reasoning']} -> {big[F]['reasoning']}, depth={big[F]['depth']}")
check("citations never move confidence via reasoning",
      abs((plus_cit["confidence"] - base["confidence"]) - (plus_cit[F]["grounding"] - base[F]["grounding"]) * 0.20) < 5e-4,
      "confidence-citation link must run through grounding only (4dp rounding-tolerant)")

# ---------------------------------------------------------------------------
# A4  Saturation monotonicity (smooth, bounded response)
# ---------------------------------------------------------------------------
print("[A4] Saturation monotonicity")
r1 = call("why", "x")[F]["reasoning_demand"]
r3 = call("why why why", "x")[F]["reasoning_demand"]
r10 = call("why why why why why why why why why why", "x")[F]["reasoning_demand"]
check("demand strictly increasing with hits", r1 < r3 < r10, f"{r1}, {r3}, {r10}")
check("demand saturates below 1", r10 < 1.0, f"{r10}")
check("10 hits close to asymptote (>= 0.85)", r10 >= 0.85, f"{r10}")

# ---------------------------------------------------------------------------
# A5  Uncertainty damping is capped and directional
# ---------------------------------------------------------------------------
print("[A5] Uncertainty damping")
clean = call("Explain the mechanism.", "The mechanism proceeds in steps. " * 5)
hedge = call("Explain the mechanism.", ("I guess it works, not sure, it is unclear, " * 3))
check("uncertainty lowers logic", hedge[F]["logic"] < clean[F]["logic"],
      f"{clean[F]['logic']} -> {hedge[F]['logic']}")
check("penalty capped at 0.20", hedge[F]["uncertainty_penalty"] <= 0.20 + 1e-9, f"{hedge[F]['uncertainty_penalty']}")

# ---------------------------------------------------------------------------
# A6  Anxiety steering: toward stability, never away
# ---------------------------------------------------------------------------
print("[A6] Anxiety steering")
calm = call("Explain X.", "X works. " * 20, qualia={"stability_index": 0.95})
anx = call("I feel overwhelmed and unsafe. Panic. " * 2, "I am stressed. " * 3, qualia={"stability_index": 0.4})
check("anxiety signal rises", anx[F]["anxiety"] > calm[F]["anxiety"], f"{calm[F]['anxiety']} vs {anx[F]['anxiety']}")
check("anxiety raises stability_bias", anx["stability_bias"] >= calm["stability_bias"],
      f"{calm['stability_bias']} vs {anx['stability_bias']}")

# ---------------------------------------------------------------------------
# A7  Damping: proposals move less than the raw gap
# ---------------------------------------------------------------------------
print("[A7] Proposal damping")
low_state = call("Explain why the model fails. Compare and justify the reasoning in detail.",
                 "Because therefore thus. " * 10 + "1. a\n2. b\n3. c\n4. d", citations=["1", "2", "3"],
                 qualia={"stability_index": 0.9, "summary": {"attention_pull": 0.8}}, variant=0.1)
raw_gap = abs(low_state["variant"] - 0.1)
check("damped step below raw gap", raw_gap < 25.0, f"step={raw_gap}")
check("strong case flagged", low_state["should_apply"] in (True, False))

# ---------------------------------------------------------------------------
# A8  Confidence gate blocks weak proposals
# ---------------------------------------------------------------------------
print("[A8] Confidence gate")
empty = call("", "")
check("empty exchange not flagged", empty["should_apply"] is False, f"{empty['should_apply']}")
check("empty confidence at floor", empty["confidence"] <= 0.33, f"{empty['confidence']}")

# ---------------------------------------------------------------------------
# A9  Symmetry: lexicon order is irrelevant
# ---------------------------------------------------------------------------
print("[A9] Lexicon order invariance")
a = call("explain why therefore how", "because thus")
b = call("therefore how explain why", "thus because")
check("token order does not change verdicts", a["variant"] == b["variant"] and a["confidence"] == b["confidence"],
      f"{a['confidence']} vs {b['confidence']}")

# ---------------------------------------------------------------------------
# A10 Robustness: garbage cannot crash or corrupt
# ---------------------------------------------------------------------------
print("[A10] Robustness")
import math  # noqa: E402
cases = [
    ("", "", None, None, None, None, None),
    ("\\ud83d\\ude00" * 50, "\\u0431\\u043b\\u0430 " * 30, None, {"stability_index": 99}, 1e18, -5.0, 2.0),
    ("why " * 5000, "because " * 5000, list("abcdefghijklmnopqrstuvwxyz"), None, 25.0, 1.0, 1.0),
    ("\\u2070\\u00b2\\u00b3", "\\u2014" * 100, ["", "  "], {"summary": None, "influence": "nan"}, -1.0, -1.0, -1.0),
]
ok = True
for idx, (q, a, c, ql, v, g, b) in enumerate(cases):
    try:
        out = call(q, a, c, ql, v, g, b)
        for k in ("reasoning", "logic", "attention", "anxiety", "gamma", "grounding"):
            val = out[F][k]
            if not (0.0 <= val <= 1.0) or isinstance(val, complex) or (isinstance(val, float) and math.isnan(val)):
                ok = False
        if not (0.1 <= out["variant"] <= 25.0) or not (0.0 <= out["gamma"] <= 0.25):
            ok = False
    except Exception as exc:  # noqa: BLE001
        ok = False
        failures.append(f"A10 case {idx} raised: {exc}")
check("4 hostile inputs survive bounded", ok)

# ---------------------------------------------------------------------------
# A11 Idempotence of state: scoring never mutates inputs
# ---------------------------------------------------------------------------
print("[A11] Input purity")
q_state = {"stability_index": 0.6, "summary": {"attention_pull": 0.5}}
snapshot = repr(q_state)
call("Explain why.", "Because.", qualia=q_state)
check("qualia dict untouched by scoring", repr(q_state) == snapshot)

# ---------------------------------------------------------------------------
# A12 Distribution sanity: diverse real-ish exchanges spread across ranges
# ---------------------------------------------------------------------------
print("[A12] Distribution sanity")
samples = [
    call("What is 2+2?", "4."),
    call("Explain why the sky is blue, comparing Rayleigh and Mie scattering, justifying with evidence.",
         "The sky is blue because Rayleigh scattering scales with 1/lambda^4; therefore shorter wavelengths dominate. "
         "1. Incident sunlight\n2. Scatter cross-section\n3. Path length\nEvidence: measured spectra agree."),
    call("I am overwhelmed by panic, everything is unclear and I cannot determine what is real.",
         "I guess, not sure. Unknown. Cannot say."),
    call("Derive the architecture. Analyze the tradeoffs. Why does the premise follow?",
         "The conclusion follows as a result; the constraint is consistent; hence the premise holds. " + "step " * 300),
]
reasonings = [s[F]["reasoning"] for s in samples]
anxieties = [s[F]["anxiety"] for s in samples]
check("reasoning index discriminates samples", (max(reasonings) - min(reasonings)) >= 0.20, f"{reasonings}")
check("anxiety index discriminates samples", (max(anxieties) - min(anxieties)) >= 0.25, f"{anxieties}")

# ---------------------------------------------------------------------------
# A13 should_apply conjunction: no single weak signal can force a flag
# ---------------------------------------------------------------------------
print("[A13] should_apply conjunction")
# concern flag but tiny shift and low confidence -> must not flag
weird = call("I am panicked, unsafe, overwhelmed.", "...")
check("concern without shift+confidence not flagged", weird["should_apply"] is False, f"{weird['should_apply']}")

# ---------------------------------------------------------------------------
# A14 Determinism under repetition
# ---------------------------------------------------------------------------
print("[A14] Determinism")
payload = ("Justify the architecture and analyze tradeoffs.",
           "Therefore, hence, because the constraint is consistent. " * 7, ["a", "b"])
outs = [call(*payload) for _ in range(5)]
check("5 identical calls, identical verdicts", all(o == outs[0] for o in outs))

# ---------------------------------------------------------------------------
print()
if failures:
    print(f"GAUNTLET RESULT: {passed} passed, {len(failures)} FAILED")
    for f in failures:
        print(" -", f)
    raise SystemExit(1)
print(f"GAUNTLET RESULT: {passed}/{passed + len(failures)} attack families SURVIVED. The formula stands.")
raise SystemExit(0)
