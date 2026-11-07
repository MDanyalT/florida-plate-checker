@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "PLATE_RESEARCH_PID_FILE=%CD%\.runtime\plate-research.pid"
set "STOP_MARKER=%CD%\.runtime\plate-research.stop"
set "APP_URL=http://127.0.0.1:8000"

if not exist "%VENV_PYTHON%" (
  echo Setup is incomplete.
  echo Double-click "Setup Plate Research.bat" first.
  pause
  exit /b 1
)

"%VENV_PYTHON%" -m app.launcher_utils health >nul 2>&1
if not errorlevel 1 (
  echo Plate Research is already running. Opening it now.
  start "" "%APP_URL%"
  exit /b 0
)
"%VENV_PYTHON%" -m app.launcher_utils port-in-use >nul 2>&1
if not errorlevel 1 (
  echo Port 8000 is already being used by another application.
  echo Close that application, then open Plate Research again.
  pause
  exit /b 1
)

if not exist ".runtime" mkdir ".runtime"
if exist "%STOP_MARKER%" del /q "%STOP_MARKER%"
set "OPEN_BROWSER=true"
echo.
echo Plate Research is starting.
echo Keep this window open.
echo To stop the application, close this window or press Control+C.
echo.
"%VENV_PYTHON%" "%CD%\app.py"
set "APP_STATUS=%ERRORLEVEL%"
if exist "%STOP_MARKER%" (
  del /q "%STOP_MARKER%"
  set "APP_STATUS=0"
)
if not "%APP_STATUS%"=="0" (
  echo.
  echo The application could not start.
  echo See the error above. Your data has not been deleted.
  pause
)
exit /b %APP_STATUS%
