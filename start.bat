@echo off
title Gaming Zone Shift Management
cd /d "%~dp0"
start "" http://localhost:5000
python server.py
pause
