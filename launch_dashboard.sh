#!/usr/bin/env bash
# One-click launcher for AI Edge Monitor local dashboard.
# Detects Python, installs the package if needed, and opens the dashboard.

set -euo pipefail

PYTHON_CMD=""
PIP_CMD=""

# 1. Find python / python3
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python not found. Please install Python 3.8+ from https://www.python.org"
    exit 1
fi

echo "[INFO] Using Python: $PYTHON_CMD"
"$PYTHON_CMD" --version

PIP_CMD="$PYTHON_CMD -m pip"

# 2. Ensure the package is installed in editable mode
if [[ -f "pyproject.toml" ]]; then
    echo "[INFO] Installing / updating ai-edge-monitor ..."
    $PIP_CMD install -q -e ".[all]"
else
    echo "[WARNING] pyproject.toml not found in current directory. Assuming package is already installed."
fi

# 3. Start the monitor with web dashboard
PORT="${AI_EDGE_PORT:-8080}"
echo "[INFO] Starting ai-edge-monitor web dashboard on port $PORT ..."

# Use nohup so the process keeps running after terminal closes
python -m cli.__main__ dashboard --port "$PORT" > ai-edge-monitor.log 2>&1 &
MON_PID=$!

# 4. Wait briefly for the server to start
sleep 3

# 5. Open browser
echo "[INFO] Opening dashboard in default browser ..."
if command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:$PORT"
elif command -v open &>/dev/null; then
    open "http://localhost:$PORT"
else
    echo "[INFO] Please open http://localhost:$PORT manually in your browser."
fi

echo "[INFO] Monitor is running in the background (PID: $MON_PID). Logs: ai-edge-monitor.log"
echo "[INFO] Press any key to stop."
read -rs -n 1

# 6. Stop background process on exit
kill "$MON_PID" 2>/dev/null || true
