@echo off
chcp 65001 >nul
cls

echo.
echo  ███████╗██╗██╗  ██╗ ██████╗ ███╗   ██╗ ██████╗███████╗
echo  ██╔════╝██║╚██╗██╔╝██╔═══██╗████╗  ██║██╔════╝██╔════╝
echo  █████╗  ██║ ╚███╔╝ ██║   ██║██╔██╗ ██║██║     █████╗
echo  ██╔══╝  ██║ ██╔██╗ ██║   ██║██║╚██╗██║██║     ██╔══╝
echo  ██║     ██║██╔╝ ██╗╚██████╔╝██║ ╚████║╚██████╗███████╗
echo  ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝╚══════╝
echo.
echo  "Never debug the same bug twice"
echo.
echo ═══════════════════════════════════════════════════════════
echo.

echo [1/5] Installing Python dependencies...
pip install -r "%~dp0requirements.txt" >nul 2>&1
if %errorlevel% equ 0 (
    echo       [OK] Dependencies installed
) else (
    echo       [!] Some dependencies may have failed - continuing anyway
)

echo.
echo [2/5] Opening installation guide...
start "" "%~dp0INSTALL.html"
timeout /t 1 >nul

echo.
echo [3/5] Opening Chrome Extensions page...
start chrome://extensions
timeout /t 2 >nul

echo.
echo [4/5] Opening folder (drag 'extension' folder to Chrome)...
explorer.exe "%~dp0"
timeout /t 1 >nul

echo.
echo [5/6] Creating desktop shortcut...
:: Create VBS script to make shortcut
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%temp%\createshortcut.vbs"
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\FixOnce.lnk" >> "%temp%\createshortcut.vbs"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%temp%\createshortcut.vbs"
echo oLink.TargetPath = "%~dp0start_fixonce.bat" >> "%temp%\createshortcut.vbs"
echo oLink.WorkingDirectory = "%~dp0" >> "%temp%\createshortcut.vbs"
echo oLink.IconLocation = "%~dp0FixOnce.ico" >> "%temp%\createshortcut.vbs"
echo oLink.Description = "FixOnce - Never debug the same bug twice" >> "%temp%\createshortcut.vbs"
echo oLink.Save >> "%temp%\createshortcut.vbs"
cscript //nologo "%temp%\createshortcut.vbs"
del "%temp%\createshortcut.vbs"
echo       [OK] Desktop shortcut created

echo.
echo [6/6] Setup complete!
echo.
echo ═══════════════════════════════════════════════════════════
echo.
echo   Now follow the instructions in the browser:
echo.
echo   1. Enable "Developer mode" in Chrome (top right)
echo   2. Drag the 'extension' folder into Chrome
echo   3. Done! Double-click "FixOnce" on your desktop!
echo.
echo ═══════════════════════════════════════════════════════════
echo.
pause
