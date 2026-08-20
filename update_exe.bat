@echo off
setlocal enabledelayedexpansion
title Update ShiftManagement.exe - Gaming Zone
cd /d "%~dp0"

echo ========================================================
echo   GAMING ZONE SHIFT MANAGEMENT - 1-CLICK EXE UPDATER
echo ========================================================
echo.

set GITHUB_REPO=zixisnoob873/Equilibrium-Shift-Form

echo [1/3] Checking GitHub for the latest ShiftManagement.exe release...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/%GITHUB_REPO%/releases/latest' -Headers @{'User-Agent'='GamingZone-Updater'}; $asset = $release.assets | Where-Object { $_.name -like '*.exe' } | Select-Object -First 1; if ($asset) { Write-Host '[OK] Found release:' $release.tag_name; Write-Host '[2/3] Downloading' $asset.name '...'; Invoke-WebRequest -Uri $asset.browser_download_url -OutFile 'ShiftManagement.new.exe' -Headers @{'User-Agent'='GamingZone-Updater'}; exit 0 } else { Write-Host '[INFO] No standalone .exe asset found in releases.'; exit 2 } } catch { Write-Host '[INFO] GitHub release check completed.'; exit 1 }"

if %ERRORLEVEL% equ 0 (
    echo.
    echo [3/3] Installing update...
    :: Close running instance if open
    taskkill /F /IM ShiftManagement.exe >nul 2>&1
    timeout /t 1 /nobreak >nul
    
    if exist "ShiftManagement.new.exe" (
        move /y "ShiftManagement.new.exe" "ShiftManagement.exe" >nul
        echo [SUCCESS] ShiftManagement.exe updated to latest release!
        echo.
        echo Starting ShiftManagement.exe...
        start "" "ShiftManagement.exe"
        exit /b 0
    )
)

:: If running in Git folder, fallback to git pull
if exist ".git" (
    echo.
    echo [INFO] Syncing repository via Git...
    call update.bat
) else (
    echo.
    echo [INFO] If you have a Git repository, make sure Git is installed and run update.bat.
    pause
)
