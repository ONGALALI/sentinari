# RIG DAY RUNBOOK — Gemma → ONNX conversion & Sentinari inference server

The Windows interim box runs the server wrapper NOW (verified degraded,
port 8100). The CONVERSION belongs to the new rig — it has the RAM
(84 GB) and GPU (24 GB) that this 15.5 GB box lacks. This runbook makes
rig day a copy-paste job.

## ⭐ 74h UPDATE (2026-10-01) — READ THIS FIRST

- **The weights are ALREADY downloaded and verified on this box.**
  `engine/custom_engine_weights/` holds the complete HF checkpoint —
  model.safetensors 23,919,549,408 B, SHA-256 verified against the HF
  pointer, plus config/tokenizer/chat-template/generation/processor.
  **No download on the rig is needed**: carry that folder across and
  point `--input` at it (Options A and B below collapse into this).
- **Rig RAM confirmed 92 GB by the owner** — the 40–50 GB conversion
  peak has huge headroom; the 84 GB figure above is superseded.
- **Carry-back option (owner ruling: "speed has no impact")** — after
  conversion, `models/gemma-12b-onnx` (~7–8 GB) can ride BACK to this
  Windows box: `execution_provider: cpu` here serves it slowly but
  honestly, and the learning needle moves on BOTH machines — still 100%
  Enigma (onnxruntime-genai only; no Ollama, no cloud, no new runtime).
- **Gateway step added (§74g/§74h):** rig day ends with the 'sentinari'
  provider in app/llm_gateway.py speaking /api/inference/chat, one
  firewall allowlist line (security.llm_firewall.allowed_runtime_providers),
  and llm.provider: sentinari — until that lands the Examiner stays DARK
  by §58 design. See docs/CONTINUITY_LOG.md §74g–§74h.

## 0. What transfers from the Windows box → rig

Copy the whole `Sentinari-server/` folder (it is self-contained). Skip
these (regenerable): `hf_cache/`, `carry/`, `models/`, `__pycache__/`,
`inference_log.sqlite3`, `*.log`. Create the rig venv fresh:

```bash
python3 -m venv .venv-rig
```

## 1. Runtime environment on the rig (Ubuntu)

```bash
cd Sentinari-server
python3 -m venv .venv-rig
./.venv-rig/bin/pip install -r requirements-inference.txt
```

Smoke test the wrapper before any model exists:

```bash
./.venv-rig/bin/python server_onnx.py            # boots degraded on :8100
curl -s http://127.0.0.1:8100/health             # ok:true, degraded:true
```

## 2. Option A — conversion ONLINE on the rig (one download)

If the rig is (or can briefly be) connected:

```bash
./.venv-rig/bin/pip install -r requirements-conversion.txt
./.venv-rig/bin/python convert_to_onnx.py \
    --model google/gemma-4-12B-it \
    --output ./models/gemma-12b-onnx \
    --precision int4 --execution-provider cuda   # GPU rig → cuda
```

Peak RAM during CPU export: ~40–50 GB (fine on 84 GB). Download ~24 GB.
int4 output: roughly 7–8 GB. On CUDA the export is faster and lighter.

## 3. Option B — conversion OFFLINE (roadmap discipline, two hops)

On THIS Windows box (connected), download the checkpoint for carrying:

```bash
./.venv-convert/Scripts/python.exe convert_to_onnx.py --download-only \
    --model google/gemma-4-12B-it --snapshot-dir ./carry/gemma-4-12B-it
```

Carry `Sentinari-server/carry/gemma-4-12B-it` across by hand (~24 GB).
On the rig, still offline:

```bash
./.venv-rig/bin/pip install -r requirements-conversion.txt
./.venv-rig/bin/python convert_to_onnx.py \
    --input ./carry/gemma-4-12B-it \
    --output ./models/gemma-12b-onnx \
    --precision int4 --execution-provider cuda
```

## 4. Wire the model in

Edit `inference_settings.yaml`:

```yaml
model:
  path: "./models/gemma-12b-onnx"
  execution_provider: cuda     # or cpu
```

Then either restart, or hot-plug into a running server:

```bash
curl -X POST http://127.0.0.1:8100/api/inference/model/load \
     -H "Content-Type: application/json" \
     -d '{"path": "./models/gemma-12b-onnx"}'
```

## 5. Verify a real generation

```bash
curl -s -X POST http://127.0.0.1:8100/api/inference/chat \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Say hello to Inspirari.", "domain": "default"}'
```

Expect `"degraded": false` and a genuine Sentinari reply (persona per config/persona_sentinari.yaml). Then check the
log rows: `curl "http://127.0.0.1:8100/api/inference/log?limit=5"` —
engine should read `onnx:cuda` (or `onnx:cpu`), not `degraded-stub`.

## 6. Keep-alive (Ubuntu)

`sentinari-inference.service` is ready (hardened: IPAddressDeny=any,
localhost allowed). Install:

```bash
sudo cp sentinari-inference.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now sentinari-inference
journalctl -u sentinari-inference -f
```

Edit the unit's paths first to match the rig layout.

## 7. Version-pin discipline

The moment generation works, the installed versions ARE the pin
(they are already recorded in requirements-inference.txt /
requirements-conversion.txt). If you ever upgrade onnxruntime-genai,
re-read its changelog first — preview-API churn moved functions twice
during this build (create_model signature; builder CLI entry).

## Notes carried from the Windows session (2026-09-27)

- `google/gemma-4-12B-it` is UN-GATED now — no HF token needed.
- Ollama was fully severed on Windows: processes killed, install dir
  renamed to `Ollama.disabled`, `fallback_providers: []` in settings.yaml
  (no silent cloud). App chat runs dark until 8100 carries real weights.
- The old Ollama GGUF blobs (D:\inpirari\Ollama\models) are Q4-quantized
  — NOT convertible via the GGUF import path (f16/f32 only). Ignore them;
  the HF checkpoint is the source of truth.
- Interim-box workaround while dark: nothing required — degraded stubs
  are loud and honest, and the examiner is paused.
