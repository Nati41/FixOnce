@echo off
REM FixOnce One-Click Installer for Windows
cd /d "%~dp0"
py -3 scripts\install.py 2>nul || python scripts\install.py
pause
