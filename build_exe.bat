@echo off
setlocal enabledelayedexpansion
title Build ShiftManagement.exe - Gaming Zone
cd /d "%~dp0"

echo ========================================================
echo   BUILDING STANDALONE SHIFT MANAGEMENT EXECUTABLE (.EXE)
echo ========================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not found in system PATH.
    pause
    exit /b 1
)

:: 2. Check & install PyInstaller if needed
echo [1/3] Checking PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] Installing PyInstaller...
    pip install pyinstaller
) else (
    echo [OK] PyInstaller is ready.
)

:: 3. Clean previous build artifacts
echo.
echo [2/3] Cleaning previous build folders...
if exist "build" rd /s /q "build"
if exist "dist\ShiftManagement.exe" del /f /q "dist\ShiftManagement.exe"

:: 4. Build .exe with PyInstaller
echo.
echo [3/3] Compiling ShiftManagement.exe (this takes about 30 seconds)...
pyinstaller --clean ShiftManagement.spec

if exist "dist\ShiftManagement.exe" (
    echo.
    echo ========================================================
    echo   [SUCCESS] Standalone EXE created successfully!
    echo   Location: dist\ShiftManagement.exe
    echo ========================================================
    echo.
) else (
    echo.
    echo [ERROR] Build failed. Check the output above for errors.
    echo.
)

pause
