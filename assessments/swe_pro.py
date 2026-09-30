"""SWE-bench Pro loader — Sentinari assessment ladder, stage 5.

Owner-provided pull script, refactored. The execution harness itself is the
owner-downloaded swe-workbench folder + zip beside this file; this module
loads the DATASET (instance list, problem statements) from HuggingFace into
the folder-internal cache. Execution-based grading (patch applied to the real
repo, unit tests must pass) runs through the workbench harness on rig day —
it cannot run from the dataset script alone.

Usage:
    python -m assessments.swe_pro
    python -c "from assessments.swe_pro import load_swe_pro; d = load_swe_pro(); print(len(d))"
"""

from __future__ import annotations

from pathlib import Path

from datasets import load_dataset

from ._hf import ensure_hf_env

ensure_hf_env()

WORKBENCH_ROOT = Path(__file__).resolve().parent / "swe-workbench"


def load_swe_pro(split: str = "test", name: str = "default"):
    """Load SWE-bench Pro (long-horizon execution tasks).

    NOTE: the hub dataset exposes configs ['default', 'hard', 'v1'] — the
    owner script's 'v2' name referred to the harness generation in
    assessments/swe-workbench, not a dataset config. 'default' is the
    canonical instance set.
    """
    if name not in {"default", "hard", "v1"}:
        raise ValueError(f"Unknown SWE-bench Pro config '{name}'. Available: default | hard | v1")
    return load_dataset("ScaleAI/SWE-bench_Pro", name=name, split=split)


def sample(count: int = 3) -> list[dict]:
    dataset = load_swe_pro()
    items: list[dict] = []
    for i, item in enumerate(dataset):
        if i >= count:
            break
        items.append(
            {
                "instance_id": str(item.get("instance_id") or ""),
                "problem_statement": str(item.get("problem_statement") or "")[:400],
            }
        )
    return items


if __name__ == "__main__":
    dataset = load_swe_pro()
    print("Total software tasks loaded:", len(dataset))
    print("Sample repo & issue:", dataset[0]["instance_id"])
    print("Problem description:", dataset[0]["problem_statement"])
