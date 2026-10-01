"""Minimal Gemma engine initializer — 71 (owner's material, patched to the real artifact).

Loads raw safetensors weights with mmap (zero-copy), parses the architecture
config, and exposes per-layer tensors for CUDA kernels or PyTorch execution.
NO transformers, NO Ollama, NO cloud — weights from disk, engine ours.

Patches applied to the owner's original template (verified against the live
HF repo, see CONTINUITY_LOG 71):
  1. Key-agnostic layer indexing: the repo is Gemma4UnifiedForConditionalGeneration
     (gemma4_unified), so text-stack keys may be `model.language_model.layers.N.*`
     (or `model.layers.N.*` on classic checkpoints). We discover the layout from
     the actual keys and normalize both to `layers.N.*`.
  2. Dtype honesty: weights are bf16. `to_cuda()` casts to float32 by default
     (most custom CUDA kernels are fp32; cast explicitly if you go bf16-native).
  3. Weight-index report: prints embedding / final-norm / language-vs-vision
     breakdown so the operator sees exactly what was mapped.

Usage:
    engine = CustomGemmaEngine("./custom_engine_weights", device="cuda")
    layer_0 = engine.layer(0)
    hidden = engine.to_cuda(layer_0["self_attn.q_proj.weight"])   # -> torch.Tensor (cuda)
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import torch
from safetensors.torch import load_file


class CustomGemmaEngine:
    def __init__(self, weights_dir: str, device: str = "cuda"):
        self.device = torch.device(device)
        self.weights_dir = weights_dir

        # 1) Parse architecture configuration matrices
        with open(os.path.join(weights_dir, "config.json"), "r", encoding="utf-8") as f:
            self.config: dict[str, Any] = json.load(f)
        arch = (self.config.get("architectures") or ["?"])[0]
        # Unified wrappers hide the text config in text_config; classic models are flat.
        text_cfg = self.config.get("text_config") or self.config
        print(f"Loaded config. Architecture: {arch}")
        print(f"Layers: {text_cfg.get('num_hidden_layers')}, Hidden Size: {text_cfg.get('hidden_size')}")

        # 2) Map weight chunks into memory (safetensors mmap = zero-copy)
        self.weights: dict[str, torch.Tensor] = {}
        weight_files = [f for f in os.listdir(weights_dir) if f.endswith(".safetensors")]
        if not weight_files:
            raise FileNotFoundError(f"No .safetensors files found in {weights_dir}")
        print(f"Loading safetensors directly to engine memory ({len(weight_files)} file(s))...")
        for file in sorted(weight_files):
            state_dict = load_file(os.path.join(weights_dir, file), device="cpu")
            self.weights.update(state_dict)

        # 3) Discover the real key layout and build a normalized index
        self._layout = self._discover_layout()
        self._index: dict[str, torch.Tensor] = {}
        for k, v in self.weights.items():
            norm = self._normalize_key(k)
            if norm is not None:
                self._index[norm] = v

        n_layers = self.layer_count
        print(f"Successfully indexed {len(self.weights)} tensor keys "
              f"({len(self._index)} normalized to the text stack; {n_layers} layers).")
        self._report()

    # -- layout discovery ----------------------------------------------------

    _LANG_PREFIXES = ("model.", "language_model.model.", "text_model.model.")

    def _discover_layout(self) -> dict[str, str]:
        """Find which prefix family the text stack actually uses."""
        keys = list(self.weights.keys())
        layout = {"prefix": "", "final_norm": "", "embed": ""}
        for pref in ("model.language_model.", "language_model.model.", "model."):
            if any(k.startswith(pref + "layers.") for k in keys):
                layout["prefix"] = pref
                break
        for emb in (layout["prefix"] + "embed_tokens.weight", "model.embed_tokens.weight",
                    "language_model.model.embed_tokens.weight"):
            if emb in self.weights:
                layout["embed"] = emb
                break
        # 71d: the REAL artifact (google/gemma-4-12B-it) names its final norm
        # 'norm.weight' (HF Gemma convention), not 'final_norm.weight' -
        # discovered live from the verified safetensors header. Old spellings
        # stay as fallbacks for classic checkpoints.
        for fn in (layout["prefix"] + "norm.weight", "model.language_model.norm.weight",
                   layout["prefix"] + "final_norm.weight", "model.final_norm.weight",
                   "language_model.model.final_norm.weight"):
            if fn in self.weights:
                layout["final_norm"] = fn
                break
        return layout

    @staticmethod
    def _normalize_key(key: str) -> str | None:
        """Map any Gemma family layout onto 'layers.N.<module>' style keys."""
        if key.startswith(("layers.", "embed_tokens", "final_norm")):
            return key  # already normalized (recursion base case)
        for pref in ("model.language_model.", "language_model.model.", "model."):
            if key.startswith(pref):
                tail = key[len(pref):]
                if tail.startswith("language_model."):  # nested unified artifact
                    return CustomGemmaEngine._normalize_key(tail[len("language_model."):])
                if tail.startswith(("layers.", "embed_tokens", "final_norm")):
                    return tail
                return None  # vision tower / multi_modal_projector etc. — indexed, not normalized
        return None

    def _report(self) -> None:
        # 71d fix: count RAW keys that normalize cleanly; the old code compared
        # raw keys against normalized ones and mislabeled the whole file as
        # vision/other on top of the text count.
        n_norm = sum(1 for k in self.weights if self._normalize_key(k) is not None)
        dtypes = sorted({str(v.dtype).replace('torch.', '') for v in list(self.weights.values())[:64]})
        print(f"  layout: prefix='{self._layout['prefix'] or '(flat)'}' "
              f"embed='{self._layout['embed'] or 'NOT FOUND'}' "
              f"final_norm='{self._layout['final_norm'] or 'NOT FOUND'}'")
        print(f"  text-stack keys: {n_norm} | vision/other keys: "
              f"{len(self.weights) - n_norm} | dtypes: {dtypes}")

    # -- tensor access -------------------------------------------------------

    @property
    def layer_count(self) -> int:
        m = self.config.get("text_config") or self.config
        return int(m.get("num_hidden_layers") or 0)

    def layer(self, idx: int) -> dict[str, torch.Tensor]:
        """Tensors for one transformer layer, keys stripped of the prefix."""
        prefix = f"layers.{idx}."
        out = {k[len(prefix):]: v for k, v in self._index.items() if k.startswith(prefix)}
        if not out:
            raise KeyError(f"layer {idx} not found (layout prefix '{self._layout['prefix']}')")
        return out

    @property
    def embedding(self) -> torch.Tensor:
        key = self._layout["embed"]
        if not key:
            raise KeyError("embed_tokens not found in this artifact")
        return self.weights[key]

    @property
    def final_norm(self) -> torch.Tensor:
        key = self._layout["final_norm"]
        if not key:
            raise KeyError("final_norm not found in this artifact")
        return self.weights[key]

    def to_cuda(self, tensor: torch.Tensor, dtype: torch.dtype = torch.float32) -> torch.Tensor:
        """Push to the active CUDA context; casts bf16 weights for fp32 kernels."""
        return tensor.to(device=self.device, dtype=dtype, non_blocking=True)


# Example Usage
# engine = CustomGemmaEngine("./custom_engine_weights")
# layer_0 = engine.layer(0)
# q = engine.to_cuda(layer_0["self_attn.q_proj.weight"])
