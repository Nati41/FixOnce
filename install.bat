@echo off
echo.
echo ================================
echo   FixOnce Installer for Windows
echo ================================
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
    echo.
    echo PowerShell installer failed. Falling back to Python installer...
    python "%~dp0scripts\install.py"
    pause
)
