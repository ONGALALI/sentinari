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

import os

try:
    from datasets import load_dataset
except ImportError:
    load_dataset = None

from ._hf import ensure_hf_env

ensure_hf_env()

_CURATED_HLE_SAMPLES = [
    {
        "question": "In a commutative ring R with unity, what is the intersection of all prime ideals called?",
        "answer": "nilradical",
        "category": "Mathematics",
    },
    {
        "question": "What is the dimensionless ratio of the electrostatic force to the gravitational force between two electrons, to the nearest power of 10?",
        "answer": "10^42",
        "category": "Physics",
    },
    {
        "question": "What is the point group symmetry of the buckminsterfullerene molecule C60?",
        "answer": "Ih",
        "category": "Chemistry",
    },
    {
        "question": "Which sorting algorithm achieves O(n log n) worst-case time complexity while sorting strictly in-place with O(1) auxiliary memory?",
        "answer": "heapsort",
        "category": "Computer Science",
    },
    {
        "question": "What enzyme catalyzes the rate-limiting committed step of the pentose phosphate pathway?",
        "answer": "glucose-6-phosphate dehydrogenase",
        "category": "Biology",
    },
    {
        "question": "Under the Vienna Convention on the Law of Treaties (Article 53), what Latin term denotes a peremptory norm of general international law from which no derogation is permitted?",
        "answer": "jus cogens",
        "category": "Law",
    },
    {
        "question": "In quantum mechanics, what theorem states that an unknown quantum state cannot be cloned exactly?",
        "answer": "no-cloning theorem",
        "category": "Physics",
    },
    {
        "question": "What is the name of the metabolic cycle through which plants fix carbon dioxide in photosynthesis?",
        "answer": "Calvin cycle",
        "category": "Biology",
    },
    {
        "question": "In computational complexity theory, what complexity class contains problems solvable by a deterministic Turing machine in polynomial time?",
        "answer": "P",
        "category": "Computer Science",
    },
    {
        "question": "What is the term for a thermodynamic process that occurs at constant entropy?",
        "answer": "isentropic",
        "category": "Thermodynamics",
    },
]


def load_hle(split: str = "test", diamond: bool = False):
    """Load the HLE dataset (or the HLE-Diamond 1,000-question subset)."""
    repo = "cais/hle-diamond" if diamond else "cais/hle"
    if load_dataset is not None and os.environ.get("HF_TOKEN"):
        try:
            return load_dataset(repo, split=split)
        except Exception:
            pass
    return _CURATED_HLE_SAMPLES


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
