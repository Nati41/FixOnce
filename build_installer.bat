@echo off
REM FixOnce Full Build Script
REM Builds EXE + Creates Windows Installer

echo ======================================
echo   FixOnce Full Build (EXE + Installer)
echo ======================================
echo.

REM Step 1: Check for .ico file
if not exist "FixOnce.ico" (
    echo ERROR: FixOnce.ico not found!
    echo.
    echo Please create FixOnce.ico first:
    echo   1. Go to https://convertio.co/png-ico/
    echo   2. Upload FixOnce-Icon.png
    echo   3. Download and save as FixOnce.ico
    echo.
    pause
    exit /b 1
)

REM Step 2: Build EXE
echo [1/3] Building EXE with PyInstaller...
call build_windows.bat
if errorlevel 1 (
    echo.
    echo EXE build failed!
    pause
    exit /b 1
)

REM Step 3: Check Inno Setup
echo.
echo [2/3] Checking Inno Setup...

set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
)
if not exist %ISCC% (
    echo ERROR: Inno Setup not found!
    echo.
    echo Please install Inno Setup from:
    echo   https://jrsoftware.org/isdl.php
    echo.
    echo Or build manually:
    echo   1. Open installer\fixonce_setup.iss
    echo   2. Press F9 to compile
    echo.
    pause
    exit /b 1
)

REM Step 4: Build Installer
echo.
echo [3/3] Building Installer...
cd installer
%ISCC% fixonce_setup.iss
cd ..

if errorlevel 1 (
    echo.
    echo Installer build failed!
    pause
    exit /b 1
)

echo.
echo ======================================
echo   BUILD COMPLETE!
echo ======================================
echo.
echo Outputs:
echo   EXE:       dist\FixOnce\FixOnce.exe
echo   Installer: installer\Output\FixOnce_Setup_3.1.exe
echo.
echo Distribution options:
echo   - Share the Installer for full experience
echo   - Share the dist\FixOnce folder for portable use
echo.
pause
