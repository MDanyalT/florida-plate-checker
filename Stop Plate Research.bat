@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "PID_FILE=%CD%\.runtime\plate-research.pid"

if not exist "%VENV_PYTHON%" (
  echo Setup is incomplete. Plate Research is not running from this folder.
  pause
  exit /b 0
)

"%VENV_PYTHON%" -m app.launcher_utils stop --pid-file "%PID_FILE%" --project-root "%CD%"
if errorlevel 2 (
  echo The saved process could not be verified, so no unrelated program was stopped.
) else (
  echo Plate Research is stopped. Stale local markers, if any, were removed.
)
pause

