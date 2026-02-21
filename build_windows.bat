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

REM Check/Install PyInstaller
echo Checking PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Install dependencies
echo.
echo Installing dependencies...
pip install -r requirements.txt
pip install fastembed onnxruntime

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
echo Building FixOnce...
echo This may take a few minutes...
echo.

pyinstaller fixonce.spec --clean

if errorlevel 1 (
    echo.
    echo BUILD FAILED!
    echo Check the error messages above.
    pause
    exit /b 1
)

echo.
echo ======================================
echo   BUILD SUCCESSFUL!
echo ======================================
echo.
echo Output: dist\FixOnce\FixOnce.exe
echo.
echo To test:
echo   cd dist\FixOnce
echo   FixOnce.exe
echo.
pause
