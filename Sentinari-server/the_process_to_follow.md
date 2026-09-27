Roadmap (see last see key sentence as key note please Buffy)

Phase 0 — One-time conversion (on a connected machine, never touches the air-gapped box, this will come when the new rig lands for now we need to connect to the net)
Please check the last two lines of code 42/43 if it should rather be removed for now within the install_windows.bat
Convert Gemma's checkpoint to ONNX format using Microsoft's onnxruntime-genai model builder tooling. Gemma is natively supported in their conversion pipeline. Output is a self-contained folder: ONNX weight files + a tokenizer config — no Python pickle files, no HF library code bundled in.
See if it is possible to integrate the launch of both the server and the "D:\inpirari\Sentinari\launch-smi-core.bat" as one process and not a independent launches for the server and then sentinari.


Phase 1 — Offline transfer (for the rig yet in desperate awaiting)
Copy that folder to the air-gapped machine by hand (USB/internal transfer), same as your existing model-transfer discipline.

Phase 2 — Inference runtime
onnxruntime-genai (Microsoft, MIT license) loads and runs it. At runtime the process imports only onnxruntime_genai — no transformers, no HF code executing at all. This is the full isolation you asked about earlier, now actually built.

Phase 3 — Gateway/persona layer
Same FastAPI wrapper pattern as before: domain-based persona injection, SQLite logging, no OpenAI-shaped naming.

Phase 4 — Cross-platform packaging
Windows: run as a background process or Windows service (NSSM) now, on the interim box (This machine) . Ubuntu: same Python code, wrapped as a systemd unit at migration — onnxruntime-genai supports both natively, no code changes needed between them.

Phase 5 — Autonomy hooks
Wire this server's endpoints into the existing coding_agent.py / gemma_training.py modules so retraining/calibration loops can call it directly rather than going through Ollama.

A few things worth knowing before you run this:

Gemma is a confirmed-supported architecture in onnxruntime-genai's model list, so the conversion step should work cleanly.
The chat template in the generate() function uses Gemma's <start_of_turn> format — worth double-checking against your specific converted model's tokenizer config, since template details can shift between Gemma point releases.
The onnxruntime-genai Python API is still marked "preview" by Microsoft and has had breaking changes between minor versions (a recent one changed what tokenizer.encode() returns) — pin your installed version once it's working, and re-check the API docs if you upgrade later rather than assuming compatibility.
This gives you one model per running process, same as before — run a second instance on a different port with its own MODEL_PATH for your Qwen-Coder workspace once that side is also converted to ONNX.

How the pieces fit together, end to end:

convert_to_onnx.py — run once, on a connected machine, to turn your Gemma checkpoint into an ONNX folder
Carry that folder across the air gap by hand
server_onnx.py — point MODEL_PATH at it, this is what actually runs
install_windows_service.bat on the interim Windows box, or sentinari-inference.service on Ubuntu at migration — same Python file underneath both, just wrapped so it survives reboots and runs unattended

One honest flag on the Windows installer: it depends on NSSM, a small third-party tool — not Microsoft's, but well-established and widely used for exactly this purpose. Since it needs to be downloaded once on a connected machine before crossing the air gap, worth verifying its checksum against the official nssm.cc release before carrying it over, same diligence as anything else entering that environment.


