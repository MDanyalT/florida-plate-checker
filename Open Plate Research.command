#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
PID_FILE="$SCRIPT_DIR/.runtime/plate-research.pid"
STOP_MARKER="$SCRIPT_DIR/.runtime/plate-research.stop"
APP_URL="http://127.0.0.1:8000"

pause_and_exit() {
  echo
  read -r -p "Press Return to close this window. "
  exit 1
}

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Setup is incomplete."
  echo "Double-click “Setup Plate Research.command” first."
  pause_and_exit
fi

source "$SCRIPT_DIR/.venv/bin/activate"
if "$VENV_PYTHON" -m app.launcher_utils health; then
  echo "Plate Research is already running. Opening it now."
  open "$APP_URL"
  exit 0
fi
if "$VENV_PYTHON" -m app.launcher_utils port-in-use; then
  echo "Port 8000 is already being used by another application."
  echo "Close that application, then open Plate Research again."
  pause_and_exit
fi

mkdir -p "$SCRIPT_DIR/.runtime"
rm -f "$STOP_MARKER"
export PLATE_RESEARCH_PID_FILE="$PID_FILE"
export OPEN_BROWSER=false
"$VENV_PYTHON" "$SCRIPT_DIR/app.py" &
APP_PID=$!

cleanup() {
  if kill -0 "$APP_PID" 2>/dev/null; then
    kill -TERM "$APP_PID" 2>/dev/null
    wait "$APP_PID" 2>/dev/null
  fi
  if [ -f "$PID_FILE" ] && [ "$(tr -d '[:space:]' < "$PID_FILE")" = "$APP_PID" ]; then
    rm -f "$PID_FILE"
  fi
}
trap cleanup EXIT INT TERM HUP

if ! "$VENV_PYTHON" -m app.launcher_utils wait-health --timeout 30; then
  echo "The application could not start."
  echo "See the error above. Your data has not been deleted."
  cleanup
  pause_and_exit
fi

open "$APP_URL"
echo
echo "Plate Research is running."
echo "Keep this window open."
echo "To stop the application, close this window or press Control+C."
echo
wait "$APP_PID"
APP_STATUS=$?
trap - EXIT INT TERM HUP
cleanup
if [ -f "$STOP_MARKER" ]; then
  rm -f "$STOP_MARKER"
  APP_STATUS=0
fi
if [ "$APP_STATUS" -ne 0 ] && [ "$APP_STATUS" -ne 130 ] && [ "$APP_STATUS" -ne 143 ]; then
  echo "The application stopped because of the error above. Your data has not been deleted."
  pause_and_exit
fi
