"""Gemma -> ONNX conversion — Phase 0 of the_process_to_follow.md.

This script drives Microsoft's onnxruntime-genai model builder via its
OFFICIAL command-line interface (``python -m onnxruntime_genai.models.builder``).
The 0.17.0 API moved the plumbing into the CLI (create_model now demands
prepared hf_details), so we wrap the supported entrypoint instead of
re-implementing it — that keeps this script churn-proof across releases.

MODES
-----
1. ONLINE (machine has internet — the one sanctioned touchpoint):

       python convert_to_onnx.py --model google/gemma-4-12B-it \\
           --output ./models/gemma-12b-onnx --precision int4 \\
           --execution-provider cpu

   Downloads the source checkpoint from Hugging Face (un-gated, no token),
   converts to ONNX, writes a self-contained folder: ONNX weights +
   tokenizer + genai config. NOTHING HF-authored needs to execute at
   runtime — the runtime installs onnxruntime-genai only.

2. OFFLINE (air-gapped rig — the roadmap's discipline):

   Step A (on the CONNECTED box, e.g. this Windows machine):

       python convert_to_onnx.py --download-only --model google/gemma-4-12B-it \\
           --snapshot-dir ./carry/gemma-4-12B-it

   Step B: carry ./carry/gemma-4-12B-it across by hand (USB / LAN).

   Step C (on the rig, still offline):

       python convert_to_onnx.py --input ./carry/gemma-4-12B-it \\
           --output ./models/gemma-12b-onnx --precision int4 \\
           --execution-provider cpu

The conversion itself is CPU/RAM heavy: ~24 GB download (fp16 weights),
~40-50 GB RAM peak during export on CPU. int4 output lands around 7-8 GB.

After it finishes: verify the output folder, then point the runtime's
inference_settings.yaml (model.path) at it — or POST it live to
/api/inference/model/load on a running Sentinari inference server.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Python 3.14 law (learned the hard way 2026-09-27, conversion.log):
# argparse now VALIDATES help strings at add_argument time
# (ArgumentParser._check_help), and onnxruntime-genai's builder help text
# contains literal '%' characters — the builder crashes before it even
# parses our arguments ("ValueError: badly formed help string"). The shim
# relaxes that one check inside the builder's own subprocess; nothing else
# is touched, and on Python <= 3.13 it is a no-op (the attribute is absent).
_BUILDER_SHIM = (
    "import argparse, runpy, sys\n"
    "if hasattr(argparse.ArgumentParser, '_check_help'):\n"
    "    argparse.ArgumentParser._check_help = lambda self, action: None\n"
    "runpy.run_module('onnxruntime_genai.models.builder', run_name='__main__')\n"
)


def _builder_module() -> str:
    """Confirm the conversion toolchain is installed, or die loudly."""
    try:
        import onnxruntime_genai  # noqa: F401
    except ImportError:
        print(
            "ERROR: onnxruntime-genai not installed in this environment.\n"
            "Install the conversion toolchain first:\n"
            "    pip install -r requirements-conversion.txt",
            file=sys.stderr,
        )
        sys.exit(1)
    return "onnxruntime_genai.models.builder"


def _download_snapshot(model: str, snapshot_dir: Path) -> None:
    """Download the HF checkpoint to a portable folder (no conversion)."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("ERROR: huggingface_hub not installed (see requirements-conversion.txt).", file=sys.stderr)
        sys.exit(1)
    print(f"[download-only] fetching {model} -> {snapshot_dir}")
    snapshot_download(repo_id=model, local_dir=str(snapshot_dir))
    print(f"[download-only] done. Carry {snapshot_dir} to the air-gapped machine by hand.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a Gemma checkpoint to ONNX for onnxruntime-genai.")
    parser.add_argument("--model", default="google/gemma-4-12B-it", help="Hugging Face repo id (online mode).")
    parser.add_argument("--input", default="", help="Local HF-format checkpoint folder (offline mode, -i hf_path).")
    parser.add_argument("--output", required=True, help="Output folder for the converted ONNX model.")
    parser.add_argument("--precision", default="int4", choices=["fp32", "fp16", "int4", "int8"])
    parser.add_argument("--execution-provider", default="cpu", choices=["cpu", "cuda", "dml"])
    parser.add_argument("--cache-dir", default="./hf_cache", help="HF download / temp export cache.")
    parser.add_argument(
        "--download-only", action="store_true",
        help="Only download the checkpoint to --snapshot-dir for hand-carrying (no conversion).",
    )
    parser.add_argument("--snapshot-dir", default="./carry", help="Target folder for --download-only.")
    parser.add_argument(
        "--extra-options",
        nargs="*",
        default=[],
        metavar="KEY=VALUE",
        help="Forwarded verbatim to the builder's --extra_options (e.g. hf_token=false for ungated repos with no token).",
    )
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.download_only:
        _download_snapshot(args.model, Path(args.snapshot_dir).resolve())
        return

    module = _builder_module()  # importability check only (see _BUILDER_SHIM)
    cli = [sys.executable, "-c", _BUILDER_SHIM]
    if args.input:
        input_path = Path(args.input).resolve()
        if not input_path.exists():
            print(f"ERROR: --input folder not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        # 0.17 law (learned 2026-10-06): pass the BARE path. The builder's
        # help text advertises `hf_path: <path>` but no code parses that
        # prefix — with it, isdir() fails, hf_name falls back to the hub
        # model id, and the gated Gemma repo demands a token we don't need
        # (everything is local). Bare dir -> config/tokenizer load from disk.
        cli += ["-i", str(input_path)]
    else:
        cli += ["-m", args.model]
    cli += [
        "-o", str(output_dir),
        "-p", args.precision,
        "-e", args.execution_provider,
        "-c", str(Path(args.cache_dir).resolve()),
    ]
    if args.extra_options:
        cli += ["--extra_options", *args.extra_options]

    print("[convert] official builder CLI:", " ".join(cli))
    print(f"[convert] target: {args.precision} / {args.execution_provider} -> {output_dir}")
    if not args.input:
        print("[convert] ONLINE MODE: this downloads the checkpoint from Hugging Face —")
        print("[convert] the one internet touchpoint of the whole pipeline.")
    result = subprocess.run(cli)
    if result.returncode != 0:
        print(f"[convert] builder exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    print(f"\n[convert] DONE. Verify {output_dir} contains: *.onnx + tokenizer files + genai_config.json.")
    print("[convert] Point the runtime's inference_settings.yaml (model.path) at this folder,")
    print("[convert] or POST it to a running server via /api/inference/model/load.")
    if shutil.which("nvidia-smi") is None and args.execution_provider != "cpu":
        print("[convert] NOTE: no NVIDIA driver visible — double-check the execution provider.", file=sys.stderr)


if __name__ == "__main__":
    main()
