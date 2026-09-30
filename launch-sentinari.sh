#!/usr/bin/env bash
# launch-sentinari.sh — Sentinari core launcher (formerly launch-smi-core.sh)

cd "$(dirname "$0")"

if [ ! -x ".venv/Scripts/python.exe" ]; then
    echo "Could not find Python runtime at .venv/Scripts/python.exe"
    exit 1
fi

# If a Sentinari core server already answers, never spawn a duplicate —
# two servers share one SQLite database and lock each other out.
if curl -s -m 2 http://127.0.0.1:8099/health | grep -q '"ok":true'; then
    echo "Sentinari core is already running. Reusing the existing server..."
    exit 0
fi

mkdir -p Logs
LOG="Logs/launch-sentinari-core.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Launch-Sentinari-Core started" > "$LOG"

export SENTINARI_SHARED_SKILLS_ROOT="$(pwd)/data/skills"
export OLLAMA_GPU_OVERRIDE=0

echo "Starting Sentinari core on 127.0.0.1:8099 ..."
./.venv/Scripts/python.exe run_smi.py serve >> "$LOG" 2>&1 &
CORE_PID=$!

for i in $(seq 1 35); do
    if curl -s -m 2 http://127.0.0.1:8099/health | grep -q '"ok":true'; then
        echo "Sentinari core is running: http://127.0.0.1:8099/ui/playground"
        exit 0
    fi
    sleep 1
done

echo "Sentinari core did not answer in time. Check the log: $LOG"
exit 1
