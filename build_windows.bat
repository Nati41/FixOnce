@echo off
REM FixOnce Windows Build Script
REM Builds a standalone EXE using PyInstaller

echo ======================================
echo   FixOnce Windows Build
echo ======================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.9+ from python.org
    pause
    exit /b 1
)

set "PYTHON=python"

REM Check/Install PyInstaller
echo Checking PyInstaller...
%PYTHON% -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    %PYTHON% -m pip install pyinstaller
)

REM Install dependencies
echo.
echo Installing dependencies...
%PYTHON% -m pip install -r requirements.txt
%PYTHON% -m pip install fastembed onnxruntime

REM Create .ico if missing (Windows needs .ico, not .icns)
if not exist "FixOnce.ico" (
    echo.
    echo WARNING: FixOnce.ico not found!
    echo The EXE will be built without an icon.
    echo To add an icon, convert FixOnce.icns to FixOnce.ico
    echo.
)

REM Build
echo.
echo Checking installer PowerShell syntax...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$null = [scriptblock]::Create((Get-Content -Raw install.ps1)); 'install.ps1 syntax OK'"
if errorlevel 1 (
    echo.
    echo INSTALLER SYNTAX CHECK FAILED!
    pause
    exit /b 1
)

echo.
echo Checking Windows-safe runtime output...
%PYTHON% scripts\windows_runtime_output_check.py
if errorlevel 1 (
    echo.
    echo WINDOWS RUNTIME OUTPUT CHECK FAILED!
    pause
    exit /b 1
)

echo.
echo Building FixOnce...
echo This may take a few minutes...
echo.

%PYTHON% -m PyInstaller fixonce.spec --clean

if errorlevel 1 (
    echo.
    echo BUILD FAILED!
    echo Check the error messages above.
    pause
    exit /b 1
)

echo.
echo Copying installer entrypoints to package root...
copy /Y install.ps1 dist\FixOnce\install.ps1 >nul
if errorlevel 1 (
    echo ERROR: Failed to copy install.ps1
    pause
    exit /b 1
)
copy /Y uninstall.ps1 dist\FixOnce\uninstall.ps1 >nul
if errorlevel 1 (
    echo ERROR: Failed to copy uninstall.ps1
    pause
    exit /b 1
)
copy /Y install.bat dist\FixOnce\install.bat >nul
if errorlevel 1 (
    echo ERROR: Failed to copy install.bat
    pause
    exit /b 1
)
copy /Y requirements.txt dist\FixOnce\requirements.txt >nul
if errorlevel 1 (
    echo ERROR: Failed to copy requirements.txt
    pause
    exit /b 1
)

echo.
echo Running packaging audit...
%PYTHON% scripts\windows_packaging_audit.py dist\FixOnce dist\FixOnce\packaging_audit.txt

if errorlevel 1 (
    echo.
    echo PACKAGING AUDIT FAILED!
    echo See dist\FixOnce\packaging_audit.txt
    pause
    exit /b 1
)

echo.
echo ======================================
echo   BUILD SUCCESSFUL!
echo ======================================
echo.
echo Output: dist\FixOnce\FixOnce.exe
echo Audit: dist\FixOnce\packaging_audit.txt
echo Entry point: scripts\app_launcher.py
echo Windowed mode: enabled
echo.
echo To test:
echo   cd dist\FixOnce
echo   FixOnce.exe
echo.
pause
