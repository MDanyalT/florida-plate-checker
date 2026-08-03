@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "setup_logs" mkdir "setup_logs"
set "LOG_FILE=%CD%\setup_logs\windows-setup.log"

echo Florida Plate Research setup
echo This first setup may take several minutes.
echo Detailed installation output is saved in setup_logs\windows-setup.log.
echo.>>"%LOG_FILE%"
echo Setup started %DATE% %TIME%>>"%LOG_FILE%"

set "PYTHON_CMD="
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.11"
if not defined PYTHON_CMD (
  python -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3,11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD goto :python_missing

if not exist ".venv\Scripts\python.exe" (
  echo Creating the private application environment...
  %PYTHON_CMD% -m venv ".venv" >>"%LOG_FILE%" 2>&1
  if errorlevel 1 goto :failed
)
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"

echo Updating the installer...
"%VENV_PYTHON%" -m pip install --upgrade pip >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto :failed
echo Installing Plate Research...
"%VENV_PYTHON%" -m pip install -r "requirements.txt" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto :failed
echo Installing the visible Chromium browser used for plate checks...
"%VENV_PYTHON%" -m playwright install chromium >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto :chromium_failed

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
) else (
  echo Keeping your existing local settings file.
)

echo Preparing local data folders and database...
"%VENV_PYTHON%" -m app.launcher_utils initialize >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto :failed
"%VENV_PYTHON%" -c "import fastapi, playwright, sqlalchemy, uvicorn" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto :failed

echo.
echo Setup is complete.
echo Your existing data and settings were preserved.
choice /M "Open Plate Research now"
if errorlevel 2 goto :success
start "" "%CD%\Open Plate Research.bat"
:success
echo Setup completed successfully %DATE% %TIME%>>"%LOG_FILE%"
pause
exit /b 0

:python_missing
echo.
echo Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/ then run this setup file again.
goto :failed_pause

:chromium_failed
echo.
echo Chromium installation failed.
echo Check your internet connection and run setup again.
goto :failed_pause

:failed
echo.
echo Setup could not finish. Review setup_logs\windows-setup.log for details.
:failed_pause
echo Your existing data has not been deleted or replaced.
pause
exit /b 1

