# FixOnce Windows Installer

Build a professional Windows installer using Inno Setup.

## Prerequisites

1. **PyInstaller build** - First build the EXE:
   ```cmd
   build_windows.bat
   ```

2. **FixOnce.ico** - Windows icon generated from the same artwork as the macOS app:
   - Source artwork: `data/app-icon.png`
   - Required ICO sizes: 16x16, 32x32, 48x48, 256x256
   - Save as `FixOnce.ico` in project root

3. **Inno Setup** - Download from https://jrsoftware.org/isdl.php

## Building the Installer

### Option 1: GUI
1. Open `fixonce_setup.iss` in Inno Setup Compiler
2. Click **Build > Compile** (or press F9)
3. Output: `installer/Output/FixOnce_Setup_1.0.12.exe`

### Option 2: Command Line
```cmd
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" fixonce_setup.iss
```

## What the Installer Does

### Install
- Copies FixOnce to `C:\Users\<user>\AppData\Local\Programs\FixOnce`
- Runs `FixOnce.exe --bootstrap` and **waits** for setup to finish
- Prepares FixOnce so users can open it when they start working
- Adds Start Menu shortcut
- Adds Desktop shortcut (optional)
- Shows optional Chrome extension instructions after setup succeeds

### Uninstall
- Removes program files
- Asks user whether to keep their data (decisions, insights, memory)
- Removes registry entries
- Removes shortcuts

## Installer Features

| Feature | Status |
|---------|--------|
| Per-user install (no admin) | ✅ |
| Bootstrap on install (wait) | ✅ |
| Open FixOnce from app shortcut | ✅ |
| Desktop shortcut | ✅ |
| Start Menu shortcut | ✅ |
| Hebrew language support | ✅ |
| Clean uninstaller | ✅ |
| Data preservation option | ✅ |
| Modern wizard style | ✅ |

## File Structure

```
installer/
├── fixonce_setup.iss    # Inno Setup script
├── README.md            # This file
└── Output/              # Generated installers go here
    └── FixOnce_Setup_1.0.12.exe
```

## Customization

Edit `fixonce_setup.iss` to change:
- `MyAppVersion` - Version number
- `AppId` - Unique app GUID (generate new one for forks)
- `DefaultDirName` - Install location
- Registry keys and startup behavior
