#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

echo "Safe update guide"
echo
if [ -x "$VENV_PYTHON" ]; then
  if BACKUP_PATH="$("$VENV_PYTHON" -m app.launcher_utils backup 2>/dev/null)"; then
    echo "A database backup was created at:"
    echo "$BACKUP_PATH"
  else
    echo "A backup could not be created. Open the app and choose “Back up my data” before updating."
  fi
else
  echo "Setup is not complete, so no database backup was needed."
fi
echo
echo "1. Download the newest macOS ZIP from the official GitHub Releases page."
echo "2. Extract it into a new folder."
echo "3. Copy your user_data folder from this version into the new folder."
echo "4. Double-click Setup Plate Research.command in the new folder."
echo
echo "Do not replace or delete user_data. It contains your plate library and history."
read -r -p "Press Return to close this window. "

