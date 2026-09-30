"""Humanity's Last Exam (HLE) loader — Sentinari assessment ladder, stage 3.

Owner-provided pull script, refactored into an importable loader. The
HuggingFace cache is pinned INSIDE the Sentinari folder (data/hf_cache) so the
whole assessment stack migrates with the folder. Zero-cloud doctrine applies
to inference, not to owner-ordered dataset pulls for assessment.

GATED DATASET (§47): cais/hle requires (1) the owner to accept the license
terms on huggingface.co/datasets/cais/hle while signed in, and (2) the
owner's HF token in .env as HF_TOKEN=hf_... . Until then load_hle() raises
DatasetNotFoundError — that is the expected state, not a bug.

Usage:
    python -m assessments.hle
    python -c "from assessments.hle import load_hle; d = load_hle(); print(len(d))"
"""

from __future__ import annotations

from datasets import load_dataset

from ._hf import ensure_hf_env

ensure_hf_env()


def load_hle(split: str = "test", diamond: bool = False):
    """Load the HLE dataset (or the HLE-Diamond 1,000-question subset)."""
    repo = "cais/hle-diamond" if diamond else "cais/hle"
    return load_dataset(repo, split=split)


def sample(count: int = 3) -> list[dict]:
    """First N questions as plain dicts (for API display)."""
    dataset = load_hle()
    items: list[dict] = []
    for i, item in enumerate(dataset):
        if i >= count:
            break
        items.append(
            {
                "index": i,
                "question": str(item.get("question") or "")[:400],
                "answer": str(item.get("answer") or "")[:200],
                "category": str(item.get("category") or item.get("field") or ""),
            }
        )
    return items


if __name__ == "__main__":
    dataset = load_hle()
    print("Total questions loaded:", len(dataset))
    print("Sample item:", dataset[0])
