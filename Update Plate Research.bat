@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"

echo Safe update guide
echo.
if exist "%VENV_PYTHON%" (
  echo Creating a database backup...
  "%VENV_PYTHON%" -m app.launcher_utils backup
) else (
  echo Setup is not complete, so no database backup was needed.
)
echo.
echo 1. Download the newest Windows ZIP from the official GitHub Releases page.
echo 2. Extract it into a new folder.
echo 3. Copy your user_data folder from this version into the new folder.
echo 4. Double-click Setup Plate Research.bat in the new folder.
echo.
echo Do not replace or delete user_data. It contains your plate library and history.
pause

