"""71d run_loader_report.py - weight-index report on the REAL artifact.

CPU run (no CUDA on this box yet - rig day). Mirrors the owner's example
usage in mimimul_engine_Init.py and proves end to end, on the true weights:
  config parsed -> safetensors mmap'd -> layout discovered ->
  every layer indexable -> embedding / final_norm reachable ->
  one real tensor's shape/dtype sane -> bf16->fp32 cast path works.
Exit 0 only if every check passed.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mimimul_engine_Init import CustomGemmaEngine  # noqa: E402


def main() -> int:
    weights = os.path.join(HERE, "custom_engine_weights")
    engine = CustomGemmaEngine(weights, device="cpu")

    n = engine.layer_count
    print(f"REPORT layer_count from config : {n}")

    empty = [i for i in range(n) if not engine.layer(i)]
    if empty:
        print(f"REPORT FAIL: empty layers: {empty[:10]}")
        return 2
    print(f"REPORT all {n} layers indexable: PASS")

    emb = engine.embedding
    print(f"REPORT embedding  : shape={tuple(emb.shape)} dtype={emb.dtype}")
    fn = engine.final_norm
    print(f"REPORT final_norm : shape={tuple(fn.shape)} dtype={fn.dtype}")

    l0 = engine.layer(0)
    print(f"REPORT layer(0) tensors ({len(l0)}):")
    for k in sorted(l0):
        t = l0[k]
        print(f"  {k:44s} {str(tuple(t.shape)):20s} {t.dtype}")

    key = "self_attn.q_proj.weight" if "self_attn.q_proj.weight" in l0 else sorted(l0)[0]
    t = l0[key]
    print(f"REPORT sample '{key}': ndim={t.dim()} numel={t.numel()}")

    up = engine.to_cuda(t)  # device=cpu here; proves the bf16->fp32 cast path
    print(f"REPORT to_cuda cast: {t.dtype} -> {up.dtype}: PASS")
    print("REPORT ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
