#!/usr/bin/env bash
# Start the ConnectClips backend (serves both API and the built SPA on port 8765).
#
# Used as the entry point for Windows Task Scheduler — see scripts/install-autostart.md.
# Logs are appended to ~/connectclips.log so failures at boot are debuggable.

set -euo pipefail

PROJECT_DIR="$HOME/ConnectClips"
LOG_FILE="$HOME/connectclips.log"
PORT="${CONNECTCLIPS_PORT:-8765}"
HOST="${CONNECTCLIPS_HOST:-0.0.0.0}"

cd "$PROJECT_DIR/backend"
# shellcheck disable=SC1091
source .venv/bin/activate

# If a previous instance is still running on this port, exit early — Task
# Scheduler may fire repeatedly, and we don't want to thrash uvicorn.
if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
  echo "[$(date)] Port $PORT already bound — skipping start." >> "$LOG_FILE"
  exit 0
fi

echo "[$(date)] Starting uvicorn on $HOST:$PORT" >> "$LOG_FILE"
exec uvicorn app.main:app \
  --host "$HOST" --port "$PORT" \
  --log-level info \
  >> "$LOG_FILE" 2>&1
