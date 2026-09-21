

# ============================================================
#  launch-smi-core.sh
#  Starts the isolated SMI Standalone Instance on Ubuntu.
# ============================================================

# Get the directory where this script is located
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create Logs directory if it doesn't exist
if [ ! -d "$ROOT/Logs" ]; then
    mkdir -p "$ROOT/Logs"
fi

LOG="$ROOT/Logs/launch-smi-core.log"

echo ""
echo "SMI CORE STANDALONE LAUNCHER"
echo "-----------------------------"
echo "Starting isolated SMI instance..."
echo ""
echo "[$(date)] Launch-SMI-Core started" > "$LOG"

# Set Python path to the virtual environment
# Note: Linux venvs use 'bin/python' instead of 'Scripts/python.exe'

PYTHON="$ROOT/../VocationalLLM/.venv314-linux/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo "Could not find Python runtime at $PYTHON"
    read -p "Press Enter to exit..."
    exit 1
fi

# Synchronize SMi Engine
echo "Synchronizing SMi Engine..."
# Note: PowerShell scripts (.ps1) don't run natively on Ubuntu. 
# If you ported the toggle script to Linux, uncomment and adjust the line below:
# bash /path/to/Toggle-SMIOllamaLink.sh --mode on

# Start the FastAPI server in the background
echo "Starting SMi Core Server..."
export OLLAMA_GPU_OVERRIDE=0

# Run uvicorn in the background and save the process ID (PID)
cd "$ROOT"
"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8099 >> "$LOG" 2>&1 &
SERVER_PID=$!

echo "Waiting for SMi Core to answer..."
DEADLINE=$(( $(date +%s) + 25 ))
SUCCESS=0

while [ $(date +%s) -lt $DEADLINE ]; do
    # Use curl to check the health endpoint
    HEALTH=$(curl -s --max-time 2 http://127.0.0.1:8099/health)
    if [[ "$HEALTH" == *'"ok":true'* ]] || [[ "$HEALTH" == *'"status":"healthy"'* ]] || [ $? -eq 0 ]; then
        SUCCESS=1
        break
    fi
    sleep 0.7
done

if [ $SUCCESS -ne 1 ]; then
    echo "SMi Core did not answer in time. Check the log: $LOG"
    read -p "Press Enter to exit..."
    exit 1
fi

echo "SMi Core is running."

# Open the playground in the default Linux browser
if command -v xdg-open > /dev/null; then
    xdg-open "http://127.0.0.1:8099/ui/playground"
else
    echo "Open this link in your browser: http://127.0.0.1:8099/ui/playground"
fi

read -p "Press Enter to close this window (Server will keep running)..."
