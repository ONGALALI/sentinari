"""71d test_loader_fixture.py - smoke-test the loader chain on a tiny fixture.

Builds a fake 2-layer Gemma4Unified artifact (real key convention:
model.language_model.*) in a temp dir, then runs the SAME report the
watcher will run on the real weights. Proves the whole report chain
(config parse, layout discovery, layer indexing, dtype path) without
needing the 22 GB artifact present.

Run:  .venv\\Scripts\\python.exe engine\\test_loader_fixture.py
ASCII only.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import torch
from safetensors.torch import save_file

HERE = os.path.dirname(os.path.abspath(__file__))


def build_fixture(root: str) -> None:
    p = "model.language_model."
    tensors = {
        p + "embed_tokens.weight": torch.randn(16, 8, dtype=torch.bfloat16),
        p + "final_norm.weight": torch.randn(8, dtype=torch.bfloat16),
    }
    for i in range(2):
        tensors[p + f"layers.{i}.self_attn.q_proj.weight"] = torch.randn(8, 8, dtype=torch.bfloat16)
        tensors[p + f"layers.{i}.self_attn.k_proj.weight"] = torch.randn(4, 8, dtype=torch.bfloat16)
        tensors[p + f"layers.{i}.mlp.gate_proj.weight"] = torch.randn(8, 8, dtype=torch.bfloat16)
    save_file(tensors, os.path.join(root, "model.safetensors"))
    cfg = {
        "architectures": ["Gemma4UnifiedForConditionalGeneration"],
        "text_config": {
            "num_hidden_layers": 2, "hidden_size": 8,
            "num_attention_heads": 2, "num_key_value_heads": 1,
            "vocab_size": 16,
        },
    }
    with open(os.path.join(root, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def main() -> int:
    root = tempfile.mkdtemp(prefix="sentinari_loader_fixture_")
    build_fixture(root)
    print(f"fixture built in {root}")
    sys.path.insert(0, HERE)
    import run_loader_report
    sys.argv = [run_loader_report.__file__, root]
    return run_loader_report.main()


if __name__ == "__main__":
    sys.exit(main())
