@echo off
title Build Gaming Zone Shift Executable
cd /d "%~dp0"
echo ========================================================
echo    BUILDING GAMING ZONE SHIFT MANAGEMENT EXECUTABLE
echo ========================================================
echo.
python build_exe.py
echo.
pause
