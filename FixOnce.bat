@echo off
REM FixOnce Launcher for Windows
cd /d "%~dp0"
if exist "FixOnce.exe" (
  start "" "%~dp0FixOnce.exe"
  exit /b 0
)
if exist "dist\FixOnce\FixOnce.exe" (
  start "" "%~dp0dist\FixOnce\FixOnce.exe"
  exit /b 0
)
set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if exist "%PYW%" (
  "%PYW%" scripts\app_launcher.py
) else (
  pyw scripts\app_launcher.py 2>nul || py -3 scripts\app_launcher.py
)
