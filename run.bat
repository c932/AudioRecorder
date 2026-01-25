@echo off
chcp 65001 > nul
set PYTHONUTF8=1

echo [Launcher] Starting English Coach...
echo [Launcher] Path: %~dp0

cd /d "%~dp0"

:: Check for virtual environment
if exist ".venv\Scripts\activate.bat" (
    echo [Launcher] Activating virtual environment...
    call .venv\Scripts\activate.bat
)

if exist "venv\Scripts\activate.bat" (
    echo [Launcher] Activating virtual environment...
    call venv\Scripts\activate.bat
)

:: Run Main
python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Launcher] Application crashed or closed with error.
    pause
) else (
    echo [Launcher] Application closed normally.
)
