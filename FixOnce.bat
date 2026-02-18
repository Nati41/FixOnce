@echo off
REM FixOnce Launcher for Windows
cd /d "%~dp0"
set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if exist "%PYW%" (
  "%PYW%" scripts\app_launcher.py
) else (
  pyw scripts\app_launcher.py 2>nul || py -3 scripts\app_launcher.py
)
