# Sentinari Inference Server — cutting the Ollama cord

Phase 2–4 of `the_process_to_follow.md`, built as a working prototype.

## What lives here

| File | Role |
|---|---|
| `server_onnx.py` | FastAPI wrapper around onnxruntime-genai — the actual server |
| `inference_settings.yaml` | Port, model path, personas/domains, logging |
| `convert_to_onnx.py` | One-time conversion on a connected machine (Phase 0) |
| `requirements-inference.txt` | Pinned deps (preview-API churn warning honoured) |
| `install_windows_service.bat` | NSSM service install for THIS box (paths fixed) |
| `sentinari-inference.service` | systemd unit for the Ubuntu rig (Phase 4) |
| `launch-all.bat` | ONE process: inference server + SMI core together |
| `inference_log.sqlite3` | SQLite request log (created on first run) |

## Endpoints (no OpenAI-shaped naming anywhere)

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness + engine status |
| `GET /api/inference/status` | full status: engine, persona, domains, counts |
| `GET /api/inference/domains` | persona domains available for injection |
| `POST /api/inference/chat` | main chat — body: `prompt` or `messages`, optional `domain`, `temperature`, `max_tokens` |
| `POST /api/inference/model/load` | load/reload the ONNX folder without restart |
| `GET /api/inference/log` | recent SQLite log rows |

## Degraded mode (why it boots today)

Until `convert_to_onnx.py` has run and `model.path` points at the output
folder, the server boots WITHOUT a model and answers chat with a stub that
says so explicitly ("engine not loaded — stub reply, not model output").
The wrapper, persona injection, SQLite logging, service install, and the
combined launcher are all verifiable before any conversion happens.

When the converted folder lands: edit `model.path` in
`inference_settings.yaml`, or POST it to `/api/inference/model/load` live.

## Phase 5 wiring (later)

Point `coding_agent.py` / `gemma_training.py` at
`http://127.0.0.1:8100/api/inference/chat` instead of Ollama. The response
shape is deliberately tiny (`ok`, `reply`, `degraded`, `elapsed_ms`) so a
10-line adapter call replaces the current Ollama client.

## Security posture

- Binds 127.0.0.1 only — the air-gap starts at the socket.
- No API keys needed (local weights); nothing calls the internet.
- On Ubuntu, `sentinari-inference.service` enforces `IPAddressDeny=any`
  (localhost allowed) at the systemd/cgroup level as defense-in-depth.
