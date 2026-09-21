@echo off
title Build Windows Installer - Gaming Zone Shift Management
cd /d "%~dp0"
echo ========================================================
echo    BUILDING GAMING ZONE SHIFT MANAGEMENT SETUP INSTALLER
echo ========================================================
echo.
python build_installer.py
echo.
pause
