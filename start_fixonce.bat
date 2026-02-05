@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: Run the native app launcher
python app_launcher.py

:: If it exits, pause to see any errors
pause
