#!/bin/bash

set -Eeo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p "$SCRIPT_DIR/setup_logs"
LOG_FILE="$SCRIPT_DIR/setup_logs/macos-setup-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

fail() {
  trap - ERR
  echo
  echo "Setup could not finish. Your existing data has not been deleted or replaced."
  echo "See the details above or review: $LOG_FILE"
  read -r -p "Press Return to close this window. "
  exit 1
}
trap fail ERR

echo "Florida Plate Research setup"
echo "This first setup may take several minutes."
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer was not found."
  echo "Install Python from https://www.python.org/downloads/ then run this setup file again."
  fail
fi

PYTHON_CMD="$(command -v python3)"
if ! "$PYTHON_CMD" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11 or newer was not found."
  echo "Install a current version from https://www.python.org/downloads/ then run this setup file again."
  echo "Detected: $("$PYTHON_CMD" --version 2>&1)"
  fail
fi

echo "Using $("$PYTHON_CMD" --version 2>&1)."
if [ ! -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  echo "Creating the private application environment..."
  "$PYTHON_CMD" -m venv "$SCRIPT_DIR/.venv"
fi

# Activation is limited to this setup window and does not change the user's shell.
source "$SCRIPT_DIR/.venv/bin/activate"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

echo "Updating the installer..."
"$VENV_PYTHON" -m pip install --upgrade pip
echo "Installing Plate Research..."
"$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt"
echo "Installing the visible Chromium browser used for plate checks..."
if ! "$VENV_PYTHON" -m playwright install chromium; then
  echo "Chromium installation failed."
  echo "Check your internet connection and run setup again."
  fail
fi

if [ ! -f "$SCRIPT_DIR/.env" ]; then
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  echo "Created your local settings file."
else
  echo "Keeping your existing local settings file."
fi

echo "Preparing local data folders and database..."
"$VENV_PYTHON" -m app.launcher_utils initialize
"$VENV_PYTHON" -c 'import fastapi, playwright, sqlalchemy, uvicorn'

trap - ERR
echo
echo "Setup is complete."
echo "Your data and settings were preserved."
echo
read -r -p "Open Plate Research now? [Y/n] " REPLY
if [[ ! "$REPLY" =~ ^[Nn]$ ]]; then
  open "$SCRIPT_DIR/Open Plate Research.command"
fi
echo "You may close this setup window."

