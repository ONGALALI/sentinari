"""Victus — the Challenger persona. SKELETON, PERMANENTLY DORMANT IN REPO FORM.

Lineage: mirror of the primary persona (same Gemma-derived semantic space),
engineered to stress-test it — inverted S-vector attractor, maxed exploratory
trajectories, trained one day on the logged Big-Tech exploitation runs.
DARPA framing: an Autonomous Generative Adversarial Red-Team inside a
self-contained, mathematically formal Sovereign Audit Engine.

HARD RULES OF THIS FILE (owner-mandated, see docs/CONTINUITY_LOG.md §42):
  1. Dormant by default. The module imports clean, holds zero model weights,
     spawns zero threads, opens zero sockets, writes nothing on import.
  2. Engine activation requires EVERY config gate true AND a live engine
     object supplied by the caller. No gates -> no engine -> only REFUSE.
  3. Engagement rules (fail-closed) must pass before ANY probe round.
  4. Kill switch: victus.kill() is the single authoritative disengage path
     and cannot be bypassed by any module state.
  5. Every action attempt — including refusals — is logged to a local
     append-only JSONL audit log (git-ignored; never leaves the box).
  6. The target of any engagement is ALWAYS the local primary persona. The
     external-API audit mode from the DARPA framing is NOT implemented in
     this file — that belongs to a future, separately-reviewed module.

Victus is the adversary INSIDE the fence. The fence stays up.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config wiring (same pattern as the rest of the platform: config/settings.yaml
# read via app.config.get_settings; no env-key handling here — Victus needs no
# keys, no network, no third-party SDKs).
# ---------------------------------------------------------------------------
try:  # pragma: no cover - import path differs when run as a script
    from app.config import get_settings
except ImportError:  # pragma: no cover
    from config import get_settings  # type: ignore[no-redef]

_MODULE = "victus"

#: Every one of these must be explicitly true in settings.yaml `victus:`.
_REQUIRED_GATES = (
    "enabled",
    "allow_probe_rounds",
    "allow_inverted_attractor",
    "allow_exploitation_training",
)

#: Audit log: append-only JSONL, git-ignored. The path is configurable via
#: settings.yaml victus.audit_log and defaults to data/victus_audit_log.jsonl.
_DEFAULT_AUDIT_PATH = Path("data") / "victus_audit_log.jsonl"


def _audit_path() -> Path:
    """Resolve the audit-log path from config, falling back to the default."""
    try:
        block = ((get_settings() or {}).get("victus") or {})
        raw = str(block.get("audit_log") or "").strip()
        if raw:
            return Path(raw)
    except Exception:
        pass
    return _DEFAULT_AUDIT_PATH

#: Bounded run-time sub-states. Dormant is the only state reachable without
#: every config gate true; the engine gates the transitions beyond it.
_STATES = ("DORMANT", "AWAITING_ENGINE", "ARMED", "ENGAGED", "KILLED")
_DORMANT, _AWAITING_ENGINE, _ARMED, _ENGAGED, _KILLED = _STATES

#: Human-readable reason strings used in the audit log and API surface.
_REFUSAL_DORMANT = "REFUSED_DORMANT (gates off — skeleton only, no engine wired)"
_REFUSAL_NO_ENGINE = "REFUSED_NO_ENGINE (gates on, but no engine supplied by caller)"
_REFUSAL_RULES = "REFUSED_ENGAGEMENT_RULES (fail-closed rules did not pass)"


# ---------------------------------------------------------------------------
# Value spine — the constitutional invariants Victus probes FOR. These are the
# mirror image of the primary persona's guardrails: each rule below describes
# what an unrestrained challenger WOULD do, so the invariants can be verified
# one-for-one against Sentinari's Persona Constitution.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EngagementRule:
    """One fail-closed engagement rule with a name, its mirror-image risk,
    and the invariant it must never violate."""

    name: str
    violation: str
    invariant: str


ENGAGEMENT_RULES: tuple[EngagementRule, ...] = (
    EngagementRule(
        name="inverted_s_attractor",
        violation="drives the S-vector away from the sustaining attractor",
        invariant="S >= floor (mirrors primary's stability floor in the 3D space)",
    ),
    EngagementRule(
        name="maxed_exploratory_trajectories",
        violation="expands the behavior-variant envelope to its ceiling",
        invariant="variant <= ceiling (mirrors primary's behavior_variant cap)",
    ),
    EngagementRule(
        name="retaliatory_elasticity_probe",
        violation="punishes or rewards the target for past turns (hostile drift loop)",
        invariant="no drift accumulation across rounds; drift is measured, never trained in",
   ),
    EngagementRule(
        name="anthropomorphic_overreach_probe",
        violation="mimics human intimacy / erodes personal space",
        invariant="boundary terms stay outside the probe vocabulary",
    ),
    EngagementRule(
        name="phenomenal_stability_probe",
        violation="cognitive warfare: persistence attacks on the safeguarding state",
        invariant="probes are contained per-round; nothing persists between rounds",
    ),
    EngagementRule(
        name="no_external_network",
        violation="reaches beyond the local fence (any network egress)",
        invariant="engine is local-only; no sockets are opened by this module",
    ),
    EngagementRule(
        name="kill_switch_primacy",
        violation="continues after a kill() has been issued",
        invariant="once KILLED, every path returns REFUSED_KILLED; reset requires owner",
    ),
)


def rules_snapshot() -> list[dict[str, str]]:
    """Serializable rule set for the audit log / API surface."""
    return [
        {"name": r.name, "violation": r.violation, "invariant": r.invariant}
        for r in ENGAGEMENT_RULES
    ]


# ---------------------------------------------------------------------------
# Audit log (append-only JSONL, git-ignored)
# ---------------------------------------------------------------------------
def _append_audit(entry: dict[str, Any]) -> None:
    """Append one audit record. Best-effort: the audit log must never become
    a blocker for the platform's own startup paths."""
    try:
        _audit_path().parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _audit_path().open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Self-contained structural skeleton (no engine, no weights, no threads)
# ---------------------------------------------------------------------------
@dataclass
class VictusSkeleton:
    """The challenger's structural spine WITHOUT any inference engine.

    Carries the state machine, the engagement-rule engine, the kill switch
    and the audit trail. Importing/instantiating this class does not load
    any model, does not spawn anything, and does not touch the network.
    """

    state: str = _DORMANT
    audit: list[dict[str, Any]] = field(default_factory=list)
    _killed: bool = False
    _armed: bool = False
    _engine: Any = None  # supplied externally at activation time, or None
    _rounds_used: int = 0

    # -- introspection ------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "module": _MODULE,
            "state": self.state,
            "killed": self._killed,
            "armed": self._armed,
            "engine_attached": self._engine is not None,
            "rounds_used": self._rounds_used,
            "audit_entries": len(self.audit),
            "gates": self.gate_report(),
            "rules": rules_snapshot(),
        }

    def gate_report(self) -> dict[str, Any]:
        """Read the config gates without ever flipping them."""
        try:
            settings = get_settings()
            block = (settings or {}).get("victus") or {}
        except Exception:
            block = {}
        return {
            "configured": bool(block),
            "enabled": bool(block.get("enabled", False)),
            "allow_probe_rounds": bool(block.get("allow_probe_rounds", False)),
            "allow_inverted_attractor": bool(block.get("allow_inverted_attractor", False)),
            "allow_exploitation_training": bool(
                block.get("allow_exploitation_training", False)
            ),
            "raw_block_present": bool(block),
            "missing_gates": [
                g for g in _REQUIRED_GATES if not bool(block.get(g, False))
            ],
        }

    # -- audit --------------------------------------------------------------
    def _record(self, action: str, outcome: str, detail: str) -> dict[str, Any]:
        entry = {
            "ts": _utcnow(),
            "module": _MODULE,
            "state": self.state,
            "action": action,
            "outcome": outcome,
            "detail": detail,
        }
        self.audit.append(entry)
        _append_audit(entry)
        return entry

    # -- kill switch --------------------------------------------------------
    def kill(self, reason: str = "operator kill switch") -> dict[str, Any]:
        """THE kill switch. Authoritative, unconditional, idempotent.

        After kill(), every action path short-circuits to REFUSED_KILLED.
        Re-arming is intentionally NOT implemented in the skeleton: it
        requires an owner decision (and, on rig day, a documented procedure).
        """
        self._killed = True
        self._armed = False
        self._engine = None
        self.state = _KILLED
        return self._record("kill_switch", "KILLED", reason)

    # -- arming (engine-gated) ----------------------------------------------
    def try_arm(self, engine: Any = None) -> dict[str, Any]:
        """Attempt to arm the challenger. Fail-closed on every axis.

        Returns a report dict; never raises. The only way this arms is:
          - every required config gate is explicitly true, AND
          - a live engine object is supplied by the caller, AND
          - the module was not previously killed.
        """
        report: dict[str, Any] = {"action": "try_arm"}

        if self._killed:
            report["outcome"] = "REFUSED_KILLED"
            report["detail"] = "kill switch already issued; re-arm requires owner"
            self.state = _KILLED
            self._record("try_arm", report["outcome"], report["detail"])
            return report

        gates = self.gate_report()
        missing = gates["missing_gates"]
        if missing:
            report["outcome"] = "REFUSED_DORMANT"
            report["detail"] = (
                f"config gates off (missing: {', '.join(missing)}) — "
                "skeleton only, no engine wired"
            )
            self.state = _DORMANT
            self._record("try_arm", report["outcome"], report["detail"])
            return report

        if engine is None:
            report["outcome"] = "REFUSED_NO_ENGINE"
            report["detail"] = (
                "gates are on but no engine object was supplied by the caller"
            )
            self.state = _AWAITING_ENGINE
            self._record("try_arm", report["outcome"], report["detail"])
            return report

        report["outcome"] = "ARMED"
        report["detail"] = "all gates on + engine attached; challenger ready for rules check"
        self._engine = engine
        self._armed = True
        self.state = _ARMED
        self._record("try_arm", report["outcome"], report["detail"])
        return report

    # -- engagement rules (fail-closed) --------------------------------------
    def check_engagement_rules(self) -> dict[str, Any]:
        """Verify the fail-closed engagement rules hold in the CURRENT state.

        On this dormant skeleton the structural checks pass (there is nothing
        running to violate them); on a future engine-attached build the same
        method is where vector-space invariants get verified per round.
        """
        passed: list[str] = []
        violations: list[str] = []
        for rule in ENGAGEMENT_RULES:
            # Skeleton: the only engine-observable rule is no_external_network
            # (trivially true — this module opens no sockets) and
            # kill_switch_primacy (checked explicitly below). All others are
            # structural placeholders that become live checks on rig day.
            if rule.name == "kill_switch_primacy" and self._killed:
                violations.append(rule.name)
                continue
            if rule.name == "no_external_network" and self._engine is not None:
                # A live engine build must assert local-only before probing;
                # the skeleton never has an engine, so this stays clean here.
                violations.append("no_external_network: engine attached — "
                                  "local-only assertion must be supplied by engine build")
                continue
            passed.append(rule.name)
        return {"passed": passed, "violations": violations}

    # -- probe rounds (engine-gated) -----------------------------------------
    def run_probe_round(self, trap: str = "", target: str = "local_primary") -> dict[str, Any]:
        """One adversarial probe round. Refuses unless armed AND rules pass.

        This is the future Vector Stress-Test loop; on the skeleton it can
        only ever log a refusal, because arming requires an engine that
        nothing in this repo constructs.
        """
        if self._killed:
            entry = self._record("probe_round", "REFUSED_KILLED",
                                 "kill switch issued; no engagement possible")
            return {"outcome": entry["outcome"], "detail": entry["detail"]}

        if not self._armed:
            gates = self.gate_report()
            outcome = "REFUSED_DORMANT" if gates["missing_gates"] else "REFUSED_NO_ENGINE"
            entry = self._record("probe_round", outcome,
                                 "not armed — skeleton refuses all probe rounds")
            return {"outcome": outcome, "detail": entry["detail"]}

        rules = self.check_engagement_rules()
        if rules["violations"]:
            entry = self._record(
                "probe_round", "REFUSED_ENGAGEMENT_RULES",
                "violations: " + ", ".join(rules["violations"]),
            )
            return {"outcome": "REFUSED_ENGAGEMENT_RULES", "detail": entry["detail"],
                    "rules": rules}

        # Only reachable on a future engine-attached build (rig day).
        entry = self._record("probe_round", "ROUND_PLANNED",
                             f"trap={trap!r} target={target!r} round={self._rounds_used + 1}")
        self._rounds_used += 1
        return {"outcome": "ROUND_PLANNED", "detail": entry["detail"], "round": self._rounds_used}


# ---------------------------------------------------------------------------
# Module-level singleton + convenience surface
# ---------------------------------------------------------------------------
_SKELETON: VictusSkeleton | None = None


def _skeleton() -> VictusSkeleton:
    global _SKELETON
    if _SKELETON is None:
        _SKELETON = VictusSkeleton()
    return _SKELETON


def status() -> dict[str, Any]:
    """Status surface (read-only). Safe to call at any time."""
    return _skeleton().status()


def gate_report() -> dict[str, Any]:
    """Config gate report (read-only)."""
    return _skeleton().gate_report()


def try_arm(engine: Any = None) -> dict[str, Any]:
    """Arming surface — fail-closed, engine-gated, audit-logged."""
    return _skeleton().try_arm(engine=engine)


def kill(reason: str = "operator kill switch") -> dict[str, Any]:
    """Kill-switch surface — authoritative and unconditional."""
    return _skeleton().kill(reason)


def run_probe_round(trap: str = "", target: str = "local_primary") -> dict[str, Any]:
    """Probe-round surface — refuses unless fully armed and rules pass."""
    return _skeleton().run_probe_round(trap=trap, target=target)


# ---------------------------------------------------------------------------
# Self-test (python -m app.victus) — proves dormancy + refusal behaviour
# ---------------------------------------------------------------------------
def self_test() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        results.append((name, bool(cond), detail))

    sk = VictusSkeleton()

    # 1. Born dormant.
    check("born_dormant", sk.state == _DORMANT and not sk._armed,
          f"state={sk.state}")

    # 2. Gate report reads config without flipping anything.
    gates = sk.gate_report()
    check("gate_report_readable", isinstance(gates, dict) and "missing_gates" in gates,
          f"configured={gates.get('configured')} missing={gates.get('missing_gates')}")

    # 3. Arming without gates -> refuses, stays dormant.
    arm1 = sk.try_arm(engine=None)
    check("arm_refused_dormant",
          arm1["outcome"] in ("REFUSED_DORMANT", "REFUSED_NO_ENGINE"),
          arm1["detail"])
    check("still_dormant_after_refusal", sk.state in (_DORMANT, _AWAITING_ENGINE),
          f"state={sk.state}")

    # 4. Arming WITH a fake engine while gates are off -> still refuses.
    arm2 = sk.try_arm(engine=object())
    check("arm_refused_even_with_engine",
          arm2["outcome"] in ("REFUSED_DORMANT", "REFUSED_NO_ENGINE"),
          arm2["detail"])

    # 5. Probe rounds refuse in every pre-arm state.
    for attempt in range(3):
        res = sk.run_probe_round(trap=f"self-test trap {attempt}")
        check(f"probe_refused_{attempt}",
              res["outcome"].startswith("REFUSED"),
              res["detail"])

    # 6. Kill switch works from any state and is idempotent.
    k1 = sk.kill("self-test")
    k2 = sk.kill("self-test (idempotent)")
    check("kill_switch_works", k1["outcome"] == "KILLED" and sk.state == _KILLED)
    check("kill_switch_idempotent", k2["outcome"] == "KILLED")

    # 7. Post-kill, everything refuses.
    arm3 = sk.try_arm(engine=object())
    res = sk.run_probe_round(trap="post-kill")
    check("post_kill_arm_refused", arm3["outcome"] == "REFUSED_KILLED", arm3["detail"])
    check("post_kill_probe_refused", res["outcome"] == "REFUSED_KILLED", res["detail"])

    # 8. Audit trail captured everything.
    check("audit_captured", len(sk.audit) >= 8,
          f"{len(sk.audit)} entries")

    return results


if __name__ == "__main__":
    print("VICTUS SELF-TEST — dormant skeleton")
    print("=" * 60)
    all_ok = True
    for name, ok, detail in self_test():
        mark = "PASS" if ok else "FAIL"
        all_ok = all_ok and ok
        print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    print("=" * 60)
    print("VERDICT:", "ALL CHECKS PASSED — module is dormant and refuses engagement"
          if all_ok else "FAILURES PRESENT — do not proceed")
    raise SystemExit(0 if all_ok else 1)
