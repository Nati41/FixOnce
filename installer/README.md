# FixOnce Windows Installer

Build a professional Windows installer using Inno Setup.

## Prerequisites

1. **PyInstaller build** - First build the EXE:
   ```cmd
   build_windows.bat
   ```

2. **assets/FixOnce.ico** - Approved Windows application icon:
   - Required ICO sizes: 16x16, 32x32, 48x48, 256x256
   - `build_windows.bat` copies it to `dist/FixOnce/FixOnce.ico`

3. **Inno Setup** - Download from https://jrsoftware.org/isdl.php

## Building the Installer

### Option 1: GUI
1. Open `fixonce_setup.iss` in Inno Setup Compiler
2. Click **Build > Compile** (or press F9)
3. Output: `installer/Output/FixOnce_Setup_1.0.14.exe`

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
- Asks user whether to keep local runtime AppData
- Removes FixOnce-owned MCP registrations for Claude Code, Codex, and Cursor
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
| Project memory preserved by default | ✅ |
| Modern wizard style | ✅ |

## Public Beta Notes

- The Windows beta installer is not code-signed yet. SmartScreen warnings are expected for first-time beta testers.
- Windows login autostart is intentionally disabled. Users open FixOnce when they start working.
- Public downloads should be published through GitHub Releases, not committed into `website/downloads/`.
- Public beta AI tool support is demonstrated with Claude Code, Codex, and Cursor.

## File Structure

```
installer/
├── fixonce_setup.iss    # Inno Setup script
├── README.md            # This file
└── Output/              # Generated installers go here
    └── FixOnce_Setup_1.0.14.exe
```

## Customization

Edit `fixonce_setup.iss` to change:
- `MyAppVersion` - Version number
- `AppId` - Unique app GUID (generate new one for forks)
- `DefaultDirName` - Install location
- Registry keys and startup behavior
