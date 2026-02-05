@echo off
chcp 65001 >nul

echo Creating FixOnce desktop shortcut...

:: Create VBS script to make shortcut
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%temp%\createshortcut.vbs"
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\FixOnce.lnk" >> "%temp%\createshortcut.vbs"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%temp%\createshortcut.vbs"
echo oLink.TargetPath = "%~dp0start_fixonce.bat" >> "%temp%\createshortcut.vbs"
echo oLink.WorkingDirectory = "%~dp0" >> "%temp%\createshortcut.vbs"
echo oLink.IconLocation = "%~dp0FixOnce.ico" >> "%temp%\createshortcut.vbs"
echo oLink.Description = "FixOnce - Never debug the same bug twice" >> "%temp%\createshortcut.vbs"
echo oLink.Save >> "%temp%\createshortcut.vbs"

:: Run the VBS script
cscript //nologo "%temp%\createshortcut.vbs"
del "%temp%\createshortcut.vbs"

echo.
echo [OK] Shortcut created on Desktop!
echo.
pause
