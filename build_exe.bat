@echo off
echo ==================================================
echo   English Pronunciation Coach - Build Script
echo ==================================================
echo.
echo [1/3] Activating Virtual Environment...
call .venv\Scripts\activate
if %errorlevel% neq 0 (
    echo [Error] Failed to activate .venv. Please ensure .venv exists.
    pause
    exit /b 1
)

:: Removed Anaconda PATH forcing - we rely on pure .venv now
echo.
echo [2/3] Cleaning previous build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [3/3] Running PyInstaller (Internal Venv)...
echo       This may take 5-10 minutes. Please wait...
python -m PyInstaller --clean build.spec

if %errorlevel% neq 0 (
    echo.
    echo [FAILURE] Build failed. Check the errors above.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo   [SUCCESS] Build Complete!
echo   Executable is in: dist\EnglishCoach.exe
echo ==================================================
pause
