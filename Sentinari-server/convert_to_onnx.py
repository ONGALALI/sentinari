"""
Gemma -> ONNX conversion — run ONCE on a machine WITH internet access.
------------------------------------------------------------------------
This script never runs on the air-gapped machine. Its only job is to
produce a self-contained model folder that gets carried across the air
gap by hand (USB / internal transfer), same as your existing process.

What it does:
  1. Downloads the source Gemma checkpoint from Hugging Face (this is
     the one, one-time internet touchpoint — same as before).
  2. Converts it to ONNX format using Microsoft's onnxruntime-genai
     model builder.
  3. Outputs a folder containing ONNX weights + tokenizer config —
     nothing Hugging Face-authored ships inside that output folder,
     and nothing in it needs `transformers` to run.

Usage:
    pip install onnxruntime-genai huggingface_hub
    # For CPU-only target hardware:
    pip install onnxruntime-genai
    # For CUDA target hardware, use the CUDA build instead:
    # pip install onnxruntime-genai-cuda

    python convert_to_onnx.py --model google/gemma-4-12b-it \
                               --output ./models/gemma-onnx \
                               --precision int4 \
                               --execution-provider cpu

After it finishes: verify the output folder, then copy the ENTIRE
--output folder (not individual files) across the air gap. That
folder is MODEL_PATH in server_onnx.py.
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Convert a Gemma checkpoint to ONNX for onnxruntime-genai.")
    parser.add_argument(
        "--model", required=True,
        help="Source model: a Hugging Face repo id (e.g. google/gemma-4-12b-it) "
             "or a local folder path if you've already downloaded it.",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output folder for the converted ONNX model. This whole folder "
             "is what gets carried across the air gap.",
    )
    parser.add_argument(
        "--precision", default="int4", choices=["fp32", "fp16", "int4", "int8"],
        help="Quantization precision. int4 gives the smallest footprint and "
             "is usually the right choice for CPU-bound air-gapped hardware. "
             "Use fp16 if you have a capable GPU and want higher fidelity.",
    )
    parser.add_argument(
        "--execution-provider", default="cpu", choices=["cpu", "cuda", "dml"],
        help="Target hardware on the AIR-GAPPED machine that will actually "
             "run this model — not the machine doing the conversion. "
             "'dml' is DirectML (Windows GPU). Match this to your real "
             "deployment target, interim Windows box or final Ubuntu rig.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from onnxruntime_genai.models.builder import create_model
    except ImportError:
        print(
            "ERROR: onnxruntime-genai model builder not found.\n"
            "Install it with: pip install onnxruntime-genai\n"
            "(or onnxruntime-genai-cuda for the CUDA build)",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[convert] source model : {args.model}")
    print(f"[convert] output folder: {output_dir}")
    print(f"[convert] precision    : {args.precision}")
    print(f"[convert] target exec. : {args.execution_provider}")
    print("[convert] this will download the source checkpoint from Hugging "
          "Face if --model is a repo id — this is the one internet "
          "touchpoint in the whole pipeline, happening on THIS machine only.")

    # create_model handles: fetching the source checkpoint (if a repo id),
    # converting to ONNX graph(s), and applying the requested quantization.
    create_model(
        model_name=args.model,
        output_dir=str(output_dir),
        precision=args.precision,
        execution_provider=args.execution_provider,
        cache_dir=None,
    )

    print(f"\n[convert] done. Verify the contents of {output_dir}, then carry "
          f"the WHOLE folder across the air gap. Point server_onnx.py's "
          f"MODEL_PATH at wherever it lands on the air-gapped machine.")


if __name__ == "__main__":
    main()
