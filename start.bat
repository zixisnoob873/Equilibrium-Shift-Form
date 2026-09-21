@echo off
title Gaming Zone Shift Management
cd /d "%~dp0"
if exist "GamingZoneShift.exe" (
    start "" "GamingZoneShift.exe"
    exit /b 0
)

if exist "dist\GamingZoneShift\GamingZoneShift.exe" (
    start "" "dist\GamingZoneShift\GamingZoneShift.exe"
    exit /b 0
)

where pythonw >nul 2>&1
if %ERRORLEVEL% equ 0 (
    if exist "launcher.py" (
        start "" pythonw launcher.py
        exit /b 0
    )
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    if exist "launcher.py" (
        start "" python launcher.py
        exit /b 0
    )
)

start "" http://localhost:5000
python server.py
pause
