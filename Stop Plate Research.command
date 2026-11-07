#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
PID_FILE="$SCRIPT_DIR/.runtime/plate-research.pid"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Setup is incomplete. Plate Research is not running from this folder."
else
  RESULT="$("$VENV_PYTHON" -m app.launcher_utils stop --pid-file "$PID_FILE" --project-root "$SCRIPT_DIR")"
  case "$RESULT" in
    stopped) echo "Plate Research stopped safely." ;;
    stale) echo "Plate Research was not running. A stale local marker was removed." ;;
    not-running) echo "Plate Research is not running." ;;
    mismatch) echo "The saved process does not belong to this Plate Research folder, so it was not stopped." ;;
    timeout) echo "Plate Research did not stop in time. Use its launcher window and press Control+C." ;;
    *) echo "Plate Research could not be stopped safely." ;;
  esac
fi
echo
read -r -p "Press Return to close this window. "

