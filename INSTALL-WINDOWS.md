# FixOnce - Installation Guide for Windows

## Quick Start (2 minutes)

### Step 1: Extract
1. Right-click on `FixOnce-Windows.zip`
2. Click "Extract All..."
3. Choose a location (recommended: `C:\Users\YourName\FixOnce`)

### Step 2: Run Installer
1. Open the extracted `FixOnce` folder
2. Preferred: **Right-click** on `install.ps1` → **"Run with PowerShell"**
3. Fallback: double-click `install.bat` (uses `py -3` / `python`)

> If you see a security warning, click "Run anyway" or type `Y` to continue.

### Step 3: Done!
The installer will:
- Install Python dependencies
- Configure Claude Code / Cursor
- Set up auto-start on login
- Open the dashboard

---

## What Gets Installed

| Component | Description |
|-----------|-------------|
| **FixOnce Server** | Runs in background on port 5000 |
| **MCP Connection** | Connects to Claude Code / Cursor |
| **Chrome Extension** | Captures browser errors (optional) |
| **Dashboard** | Web UI at http://localhost:5000 |

---

## Requirements

- **Python 3.9+** - [Download here](https://www.python.org/downloads/)
  - **IMPORTANT:** Check "Add Python to PATH" during installation!
- **Claude Code** or **Cursor** - At least one AI editor

---

## Chrome Extension (Optional)

To capture browser errors:

1. Open Chrome and go to `chrome://extensions/`
2. Enable "Developer mode" (toggle in top right)
3. Click "Load unpacked"
4. Select the `extension` folder inside FixOnce

---

## Troubleshooting

### "Python not found"
Install Python from https://www.python.org/downloads/
Make sure to check "Add Python to PATH"!

If `python` still fails, run with launcher:
```powershell
py -3 install.py
```

### "Script cannot be loaded" (Execution Policy)
Run PowerShell as Administrator and type:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
Then try again.

### "VC++ Build Tools required"
Some packages need C++ compiler. Download from:
https://visualstudio.microsoft.com/visual-cpp-build-tools/
Install "Desktop development with C++"

### Server not starting
Run manually:
```
cd C:\path\to\FixOnce
python src\server.py --flask-only
```

---

## Uninstall

Run `uninstall.ps1` to:
- Stop the server
- Remove auto-start task
- (Does NOT delete your data)

---

## Usage

After installation, just say in Claude Code or Cursor:
- "hi" / "hello" / "היי"

FixOnce will respond with your project context!

**Dashboard:** http://localhost:5000

---

## Support

Issues: https://github.com/Nati41/FixOnce/issues
