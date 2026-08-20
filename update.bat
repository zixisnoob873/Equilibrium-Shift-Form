@echo off
setlocal enabledelayedexpansion
title Update Gaming Zone Shift Management
cd /d "%~dp0"

echo ========================================================
echo    GAMING ZONE SHIFT MANAGEMENT - SYSTEM UPDATER
echo ========================================================
echo.

:: 1. Check if Git is installed
where git >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Git is not installed or not found in system PATH.
    echo Please download and install Git from: https://git-scm.com/download/win
    echo.
    pause
    exit /b 1
)

:: 2. Check if folder is a Git repository
if not exist ".git" (
    echo [WARNING] This folder is not yet linked to a Git repository.
    echo.
    echo To link this folder for the first time:
    echo 1. Open PowerShell or Command Prompt in this folder.
    echo 2. Run: git init
    echo 3. Run: git remote add origin ^<YOUR_GITHUB_REPO_URL^>
    echo 4. Run: git fetch
    echo 5. Run: git checkout -f main
    echo.
    pause
    exit /b 1
)

:: 3. Pull latest changes from GitHub
echo [1/2] Fetching latest changes from GitHub...
git pull origin main
if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] Git pull encountered an issue. 
    echo Please check your internet connection or GitHub login.
    echo.
) else (
    echo [OK] Code updated successfully.
)

:: 4. Update Python dependencies if requirements.txt changed
echo.
echo [2/2] Checking and updating Python packages...
pip install -r requirements.txt --quiet
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Dependency update had an issue. Retrying with full log...
    pip install -r requirements.txt
) else (
    echo [OK] Dependencies up to date.
)

echo.
echo ========================================================
echo    UPDATE FINISHED! You can now launch start.bat
echo ========================================================
echo.
pause
