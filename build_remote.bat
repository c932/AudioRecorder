@echo off
echo ==================================================
echo   English Coach - Remote Build (No Local AI)
echo   LLM via remote API (OpenAI/Ollama/Custom)
echo ==================================================
echo.

echo [1/4] Activating Virtual Environment...
call .venv\Scripts\activate
if %errorlevel% neq 0 (
    echo [Error] Failed to activate .venv.
    pause
    exit /b 1
)

echo.
echo [2/4] Cleaning previous build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [3/4] Running PyInstaller (Remote Build)...
echo       Excluding: torch, whisper, kokoro, azure
echo       This may take 3-5 minutes...
python -m PyInstaller --clean build_remote.spec

if %errorlevel% neq 0 (
    echo.
    echo [FAILURE] Build failed. Check the errors above.
    pause
    exit /b 1
)

echo.
echo [4/4] Checking output...
if exist "dist\EnglishCoach\EnglishCoach.exe" (
    echo.
    echo ==================================================
    echo   [SUCCESS] Build Complete!
    echo   Output folder: dist\EnglishCoach\
    echo   Main exe:      dist\EnglishCoach\EnglishCoach.exe
    echo.
    echo   To create installer:
    echo     1. Download Inno Setup: https://jrsoftware.org/isdl.php
    echo     2. Open installer.iss with Inno Setup Compiler
    echo     3. Click Build ^> Compile (Ctrl+F9)
    echo     4. Installer output: installer_output\EnglishCoach_Setup.exe
    echo ==================================================
) else (
    echo [Error] EnglishCoach.exe not found in dist\EnglishCoach\
)
pause
