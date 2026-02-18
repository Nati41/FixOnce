#!/usr/bin/env python3
"""
FixOnce One-Click Installer
Works on Mac and Windows
"""

import os
import sys
import json
import shutil
import platform
import subprocess
from pathlib import Path

# Colors for terminal (work on both platforms with colorama fallback)
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

# Disable colors on Windows unless colorama is available
if platform.system() == 'Windows':
    try:
        import colorama
        colorama.init()
    except ImportError:
        for attr in dir(Colors):
            if not attr.startswith('_'):
                setattr(Colors, attr, '')

def print_banner():
    """Print FixOnce banner"""
    print(f"""
{Colors.BLUE}
  ███████╗██╗██╗  ██╗ ██████╗ ███╗   ██╗ ██████╗███████╗
  ██╔════╝██║╚██╗██╔╝██╔═══██╗████╗  ██║██╔════╝██╔════╝
  █████╗  ██║ ╚███╔╝ ██║   ██║██╔██╗ ██║██║     █████╗
  ██╔══╝  ██║ ██╔██╗ ██║   ██║██║╚██╗██║██║     ██╔══╝
  ██║     ██║██╔╝ ██╗╚██████╔╝██║ ╚████║╚██████╗███████╗
  ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝╚══════╝
{Colors.END}
  {Colors.YELLOW}"Your AI Never Forgets"{Colors.END}

{'═' * 60}
""")

def get_fixonce_dir() -> Path:
    """Get the FixOnce installation directory (project root)"""
    return Path(__file__).parent.parent.absolute()

def get_platform() -> str:
    """Get current platform: 'mac', 'windows', or 'linux'"""
    system = platform.system().lower()
    if system == 'darwin':
        return 'mac'
    elif system == 'windows':
        return 'windows'
    else:
        return 'linux'


def get_windows_pythonw(executable: str) -> str:
    """Best-effort resolve pythonw.exe path from current Python executable."""
    exe = Path(executable)
    if exe.name.lower() == "pythonw.exe":
        return str(exe)

    candidates = [
        exe.with_name("pythonw.exe"),
        Path(sys.prefix) / "pythonw.exe",
        Path(sys.base_prefix) / "pythonw.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    # Fallback: keep python.exe if pythonw is unavailable
    return executable

def run_command(cmd: list, silent: bool = False) -> tuple:
    """Run a command and return (success, output)"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

# ============ Step 1: Python Dependencies ============

def install_dependencies() -> bool:
    """Install Python dependencies"""
    print(f"\n{Colors.BLUE}[1/5]{Colors.END} Installing Python dependencies...")

    requirements_file = get_fixonce_dir() / "requirements.txt"

    if not requirements_file.exists():
        print(f"  {Colors.RED}[ERROR]{Colors.END} requirements.txt not found")
        return False

    success, output = run_command([
        sys.executable, "-m", "pip", "install", "-r", str(requirements_file), "-q"
    ])

    if success:
        print(f"  {Colors.GREEN}[OK]{Colors.END} Dependencies installed")
        return True
    else:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Some dependencies may have failed")
        print(f"       Run manually: pip install -r requirements.txt")
        return True  # Continue anyway

# ============ Step 2: Detect Editors ============

def detect_editors() -> dict:
    """Detect installed AI editors"""
    print(f"\n{Colors.BLUE}[2/5]{Colors.END} Detecting AI editors...")

    editors = {
        'claude_code': False,
        'cursor': False,
        'vscode': False,
        'copilot': False
    }

    current_platform = get_platform()

    if current_platform == 'mac':
        # Check for Claude Code CLI
        success, _ = run_command(['which', 'claude'])
        editors['claude_code'] = success

        # Check for Cursor
        editors['cursor'] = Path('/Applications/Cursor.app').exists()

        # Check for VS Code (GitHub Copilot runs inside VS Code)
        editors['vscode'] = Path('/Applications/Visual Studio Code.app').exists()
        editors['copilot'] = editors['vscode']  # Copilot is a VS Code extension

    elif current_platform == 'windows':
        # Check common Windows paths
        local_app_data = Path(os.environ.get('LOCALAPPDATA', ''))
        app_data = Path(os.environ.get('APPDATA', ''))

        # Claude Code
        success, _ = run_command(['where', 'claude'], silent=True)
        editors['claude_code'] = success

        # Cursor
        editors['cursor'] = (
            (local_app_data / 'Programs' / 'Cursor').exists() or
            (local_app_data / 'Programs' / 'cursor').exists()
        )

        # VS Code
        editors['vscode'] = (local_app_data / 'Programs' / 'Microsoft VS Code').exists()

    # Print results
    for editor, installed in editors.items():
        status = f"{Colors.GREEN}[FOUND]{Colors.END}" if installed else f"{Colors.YELLOW}[NOT FOUND]{Colors.END}"
        name = editor.replace('_', ' ').title()
        print(f"  {status} {name}")

    return editors

# ============ Step 3: Configure MCP ============

def get_mcp_config_paths() -> dict:
    """Get MCP configuration file paths for each editor"""
    current_platform = get_platform()
    home = Path.home()

    paths = {}

    if current_platform == 'mac':
        paths['claude_code'] = home / '.claude.json'
        paths['cursor'] = home / '.cursor' / 'mcp.json'

    elif current_platform == 'windows':
        app_data = Path(os.environ.get('APPDATA', home / 'AppData' / 'Roaming'))
        paths['claude_code'] = home / '.claude.json'
        paths['cursor'] = app_data / 'Cursor' / 'mcp.json'

    else:  # Linux
        paths['claude_code'] = home / '.claude.json'
        paths['cursor'] = home / '.cursor' / 'mcp.json'

    return paths

def configure_mcp(editors: dict) -> bool:
    """Configure MCP for detected editors"""
    print(f"\n{Colors.BLUE}[3/5]{Colors.END} Configuring MCP (AI Memory Connection)...")

    fixonce_dir = get_fixonce_dir()
    mcp_server_path = fixonce_dir / "src" / "mcp_server" / "mcp_memory_server_v2.py"

    if not mcp_server_path.exists():
        print(f"  {Colors.RED}[ERROR]{Colors.END} MCP server not found at {mcp_server_path}")
        return False

    mcp_config = {
        "mcpServers": {
            "fixonce": {
                "command": sys.executable,
                "args": [str(mcp_server_path)]
            }
        }
    }

    config_paths = get_mcp_config_paths()
    configured_count = 0

    for editor, path in config_paths.items():
        if not editors.get(editor, False):
            continue

        try:
            # Read existing config if exists
            existing_config = {}
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    try:
                        existing_config = json.load(f)
                    except json.JSONDecodeError:
                        existing_config = {}

            # Merge configs
            if 'mcpServers' not in existing_config:
                existing_config['mcpServers'] = {}

            existing_config['mcpServers']['fixonce'] = mcp_config['mcpServers']['fixonce']

            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write config
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(existing_config, f, indent=2)

            editor_name = editor.replace('_', ' ').title()
            print(f"  {Colors.GREEN}[OK]{Colors.END} {editor_name} configured: {path}")
            configured_count += 1

        except Exception as e:
            print(f"  {Colors.RED}[ERROR]{Colors.END} Failed to configure {editor}: {e}")

    if configured_count == 0:
        print(f"  {Colors.YELLOW}[INFO]{Colors.END} No editors to configure (install Claude Code or Cursor first)")

    return True

# ============ Step 4: Configure Editor Rules ============

FIXONCE_RULES = """You have FixOnce MCP tools for persistent project memory.

On ANY greeting (hi, היי, hello, שלום, hey, מה קורה, מה המצב):
1. Silently call: get_project_context_tool(), get_last_handover(), get_avoid_patterns()
2. Present in Hebrew:
   היי! FixOnce חיבר אותי לפרויקט [name].
   🎯 הקשר: [stack] - [focus]
   📜 חוקי בית: [key decision]
   ⏸️ איפה עצרנו: [handover]
   מאיפה ממשיכים?

During work:
- Before fixing: call search_past_solutions() first
- After fixing: call update_solution_status() with keywords
- Decisions: call log_project_decision()

On exit (bye, סיימתי, done): call create_handover() with summary.

Core principle: Never debug the same bug twice."""


def configure_cursor_rules() -> bool:
    """Create .cursorrules in FixOnce project directory.

    Note: Cursor reads .cursorrules from each project root, not from a global location.
    Users need to copy this file to their own projects, or add rules via Cursor Settings UI.
    """
    fixonce_dir = get_fixonce_dir()
    cursorrules_path = fixonce_dir / ".cursorrules"

    try:
        with open(cursorrules_path, 'w', encoding='utf-8') as f:
            f.write(f"# FixOnce - AI Memory Protocol\n\n{FIXONCE_RULES}\n")
        return True
    except Exception as e:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not create .cursorrules: {e}")
        return False


def sync_rules() -> bool:
    """Sync rules files for all editors"""
    print(f"\n{Colors.BLUE}[4/5]{Colors.END} Configuring editor rules...")

    fixonce_dir = get_fixonce_dir()

    # Create .cursorrules in project
    if configure_cursor_rules():
        print(f"  {Colors.GREEN}[OK]{Colors.END} .cursorrules created (for Cursor)")
    else:
        print(f"  {Colors.YELLOW}[SKIP]{Colors.END} Could not create .cursorrules")

    # Note: GitHub Copilot uses prompts from dashboard, no global rules file

    # Configure Claude Code CLAUDE.md
    claude_md_path = Path.home() / ".claude" / "CLAUDE.md"
    if not claude_md_path.exists():
        try:
            claude_md_path.parent.mkdir(parents=True, exist_ok=True)
            with open(claude_md_path, 'w', encoding='utf-8') as f:
                f.write(f"# FixOnce - Your Debugging Memory\n\n{FIXONCE_RULES}\n")
            print(f"  {Colors.GREEN}[OK]{Colors.END} Claude Code CLAUDE.md configured")
        except Exception:
            pass

    # Import and run project-level sync
    sys.path.insert(0, str(fixonce_dir / "src"))

    try:
        from managers.rules_generator import sync_all_rules
        result = sync_all_rules(str(fixonce_dir))

        if result.get('success'):
            print(f"  {Colors.GREEN}[OK]{Colors.END} Project rules synced")
            return True
        else:
            return True
    except ImportError:
        return True
    except Exception as e:
        return True

# ============ Step 5: Start Server & Open Dashboard ============

def start_server_and_open_dashboard() -> bool:
    """Start the server and open dashboard"""
    print(f"\n{Colors.BLUE}[5/5]{Colors.END} Starting FixOnce...")

    fixonce_dir = get_fixonce_dir()
    server_script = fixonce_dir / "src" / "server.py"

    if not server_script.exists():
        print(f"  {Colors.RED}[ERROR]{Colors.END} Server script not found")
        return False

    current_platform = get_platform()

    # Start server in background
    try:
        if current_platform == 'windows':
            python_cmd = sys.executable
            # Windows: use START command
            subprocess.Popen(
                f'start /B "" "{python_cmd}" "{server_script}" --flask-only',
                shell=True,
                cwd=str(fixonce_dir / "src")
            )
        else:
            # Mac/Linux: use nohup
            subprocess.Popen(
                [sys.executable, str(server_script), '--flask-only'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(fixonce_dir / "src"),
                start_new_session=True
            )

        print(f"  {Colors.GREEN}[OK]{Colors.END} Server starting...")

        # Wait a moment for server to start
        import time
        time.sleep(2)

        # Open dashboard
        dashboard_url = "http://localhost:5000"

        if current_platform == 'mac':
            subprocess.run(['open', dashboard_url], capture_output=True)
        elif current_platform == 'windows':
            subprocess.run(f'start "" "{dashboard_url}"', shell=True, capture_output=True)
        else:
            subprocess.run(['xdg-open', dashboard_url], capture_output=True)

        print(f"  {Colors.GREEN}[OK]{Colors.END} Dashboard opened: {dashboard_url}")
        return True

    except Exception as e:
        print(f"  {Colors.RED}[ERROR]{Colors.END} Failed to start: {e}")
        return False

# ============ Create Launcher Scripts ============

def create_launcher_scripts():
    """Create platform-specific launcher scripts that open the desktop app"""
    fixonce_dir = get_fixonce_dir()

    # Mac launcher - uses RELATIVE path (works on any machine)
    mac_launcher = fixonce_dir / "FixOnce.command"
    mac_content = '''#!/bin/bash
# FixOnce Launcher for Mac
cd "$(dirname "$0")"
python3 scripts/app_launcher.py
'''

    with open(mac_launcher, 'w') as f:
        f.write(mac_content)
    os.chmod(mac_launcher, 0o755)

    # Windows launcher - uses RELATIVE path (works on any machine)
    win_launcher = fixonce_dir / "FixOnce.bat"
    win_content = '''@echo off
REM FixOnce Launcher for Windows
cd /d "%~dp0"
set "PYW=%LOCALAPPDATA%\\Programs\\Python\\Python313\\pythonw.exe"
if exist "%PYW%" (
  "%PYW%" scripts\\app_launcher.py
) else (
  pyw scripts\\app_launcher.py 2>nul || py -3 scripts\\app_launcher.py
)
'''

    with open(win_launcher, 'w') as f:
        f.write(win_content)

# ============ Add to Dock/Desktop ============

def add_to_dock_or_desktop():
    """Add FixOnce to Dock (Mac) or Desktop (Windows)"""
    print(f"\n{Colors.BLUE}[+]{Colors.END} Adding FixOnce to Dock/Desktop...")

    fixonce_dir = get_fixonce_dir()
    current_platform = get_platform()

    if current_platform == 'mac':
        app_path = fixonce_dir / "FixOnce.app"

        if app_path.exists():
            try:
                # Check if already in Dock
                result = subprocess.run(
                    ['defaults', 'read', 'com.apple.dock', 'persistent-apps'],
                    capture_output=True, text=True
                )
                if 'FixOnce' in result.stdout:
                    print(f"  {Colors.GREEN}[OK]{Colors.END} Already in Dock")
                    return

                # Add to Dock using defaults (persistent dock item)
                subprocess.run([
                    'defaults', 'write', 'com.apple.dock', 'persistent-apps', '-array-add',
                    f'<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>{app_path}</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>'
                ], capture_output=True)

                # Restart Dock to apply
                subprocess.run(['killall', 'Dock'], capture_output=True)

                print(f"  {Colors.GREEN}[OK]{Colors.END} Added to Dock")
            except Exception as e:
                print(f"  {Colors.YELLOW}[INFO]{Colors.END} Drag FixOnce.app to your Dock manually")
        else:
            print(f"  {Colors.YELLOW}[INFO]{Colors.END} FixOnce.app not found")

    elif current_platform == 'windows':
        try:
            # Create desktop shortcut
            desktop = Path(os.environ.get('USERPROFILE', '')) / 'Desktop'
            shortcut_path = desktop / 'FixOnce.lnk'

            # Use PowerShell to create shortcut
            bat_path = fixonce_dir / 'FixOnce.bat'
            icon_path = fixonce_dir / 'FixOnce-Icon.png'

            ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{bat_path}"
$Shortcut.WorkingDirectory = "{fixonce_dir}"
$Shortcut.Description = "FixOnce - Never debug the same bug twice"
$Shortcut.Save()
'''
            subprocess.run(['powershell', '-Command', ps_script], capture_output=True)
            print(f"  {Colors.GREEN}[OK]{Colors.END} Desktop shortcut created")
        except Exception as e:
            print(f"  {Colors.YELLOW}[INFO]{Colors.END} Create desktop shortcut manually")

# ============ Step 6: Configure Auto-Start ============

def configure_auto_start() -> bool:
    """Configure FixOnce to start automatically on login"""
    print(f"\n{Colors.BLUE}[6/7]{Colors.END} Configuring auto-start...")

    fixonce_dir = get_fixonce_dir()
    current_platform = get_platform()

    if current_platform == 'mac':
        # Create LaunchAgent for auto-start
        launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        launch_agents_dir.mkdir(parents=True, exist_ok=True)

        plist_path = launch_agents_dir / "com.fixonce.server.plist"
        server_script = fixonce_dir / "src" / "server.py"

        plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fixonce.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{server_script}</string>
        <string>--flask-only</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{fixonce_dir / "src"}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>{fixonce_dir / "data" / "server.log"}</string>
    <key>StandardErrorPath</key>
    <string>{fixonce_dir / "data" / "server.log"}</string>
</dict>
</plist>
'''
        try:
            # Check if already exists and running
            check_result = subprocess.run(
                ['launchctl', 'list', 'com.fixonce.server'],
                capture_output=True, text=True
            )
            if check_result.returncode == 0:
                print(f"  {Colors.GREEN}[OK]{Colors.END} Auto-start already configured")
                return True

            # Unload if exists but not running
            subprocess.run(['launchctl', 'unload', str(plist_path)], capture_output=True)

            # Write new plist
            with open(plist_path, 'w') as f:
                f.write(plist_content)

            # Load the LaunchAgent
            subprocess.run(['launchctl', 'load', str(plist_path)], capture_output=True)

            print(f"  {Colors.GREEN}[OK]{Colors.END} Auto-start configured (LaunchAgent with restart on failure)")
            return True
        except Exception as e:
            print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not configure auto-start: {e}")
            return False

    elif current_platform == 'windows':
        # Create scheduled task for auto-start
        try:
            server_script = fixonce_dir / "src" / "server.py"
            task_name = "FixOnceServer"
            pythonw_cmd = get_windows_pythonw(sys.executable)

            # Remove existing task if any
            subprocess.run(
                ['schtasks', '/delete', '/tn', task_name, '/f'],
                capture_output=True
            )

            # Create new task that runs at logon
            result = subprocess.run([
                'schtasks', '/create',
                '/tn', task_name,
                '/tr', f'"{pythonw_cmd}" "{server_script}" --flask-only',
                '/sc', 'onlogon',
                '/rl', 'limited',
                '/f'
            ], capture_output=True, text=True)

            if result.returncode == 0:
                print(f"  {Colors.GREEN}[OK]{Colors.END} Auto-start configured (Task Scheduler)")
                return True
            else:
                print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not configure auto-start")
                print(f"       Run manually: python src/server.py")
                return False
        except Exception as e:
            print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not configure auto-start: {e}")
            return False

    else:
        print(f"  {Colors.YELLOW}[INFO]{Colors.END} Auto-start not configured for Linux")
        print(f"       Add to your startup: python3 {fixonce_dir}/src/server.py --flask-only")
        return True


# ============ Step 7: Chrome Extension ============

def show_chrome_extension_instructions():
    """Show instructions for installing Chrome extension and try to open Chrome"""
    print(f"\n{Colors.BLUE}[7/7]{Colors.END} Chrome Extension (for browser error capture)...")

    fixonce_dir = get_fixonce_dir()
    extension_dir = fixonce_dir / "extension"
    current_platform = get_platform()

    if not extension_dir.exists():
        print(f"  {Colors.YELLOW}[SKIP]{Colors.END} Extension folder not found")
        return

    # Try to open chrome://extensions automatically
    print(f"  {Colors.YELLOW}Opening Chrome extensions page...{Colors.END}")

    try:
        if current_platform == 'mac':
            # On Mac, we can use 'open' with Chrome
            subprocess.run([
                'open', '-a', 'Google Chrome', 'chrome://extensions/'
            ], capture_output=True, timeout=5)
            print(f"  {Colors.GREEN}[OK]{Colors.END} Chrome extensions page opened!")
        elif current_platform == 'windows':
            # On Windows, start command with Chrome
            subprocess.run(
                'start "" "chrome://extensions/"',
                shell=True,
                capture_output=True,
                timeout=5
            )
            print(f"  {Colors.GREEN}[OK]{Colors.END} Chrome extensions page opened!")
        else:
            # Linux - try xdg-open or google-chrome directly
            subprocess.run([
                'google-chrome', 'chrome://extensions/'
            ], capture_output=True, timeout=5)
    except Exception:
        print(f"  {Colors.YELLOW}[INFO]{Colors.END} Could not open Chrome automatically")

    # Always show clear instructions
    print(f"""
  {Colors.BOLD}╔══════════════════════════════════════════════════════════╗
  ║          CHROME EXTENSION INSTALLATION                   ║
  ╠══════════════════════════════════════════════════════════╣
  ║                                                          ║
  ║  1. Enable 'Developer mode' (toggle in top right)        ║
  ║                                                          ║
  ║  2. Click 'Load unpacked'                                ║
  ║                                                          ║
  ║  3. Select this folder:                                  ║
  ║     {Colors.YELLOW}{str(extension_dir)[:50]}{Colors.BOLD}
  ║                                                          ║
  ╚══════════════════════════════════════════════════════════╝{Colors.END}

  {Colors.GREEN}The extension captures browser errors for FixOnce to analyze.{Colors.END}
""")


# ============ Start App ============

def start_app():
    """Start the FixOnce desktop app"""
    print(f"\n{Colors.BLUE}[✓]{Colors.END} Launching FixOnce...")

    fixonce_dir = get_fixonce_dir()
    current_platform = get_platform()

    try:
        if current_platform == 'mac':
            app_path = fixonce_dir / "FixOnce.app"
            if app_path.exists():
                subprocess.Popen(['open', str(app_path)])
                print(f"  {Colors.GREEN}[OK]{Colors.END} FixOnce app launched!")
            else:
                # Fallback to app_launcher.py
                subprocess.Popen([sys.executable, str(fixonce_dir / 'scripts' / 'app_launcher.py')])
                print(f"  {Colors.GREEN}[OK]{Colors.END} FixOnce launched!")
        elif current_platform == 'windows':
            pythonw_cmd = get_windows_pythonw(sys.executable)
            subprocess.Popen(
                [pythonw_cmd, str(fixonce_dir / 'scripts' / 'app_launcher.py')],
                creationflags=subprocess.DETACHED_PROCESS
            )
            print(f"  {Colors.GREEN}[OK]{Colors.END} FixOnce launched!")
        else:
            subprocess.Popen([sys.executable, str(fixonce_dir / 'scripts' / 'app_launcher.py')])
            print(f"  {Colors.GREEN}[OK]{Colors.END} FixOnce launched!")

    except Exception as e:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not auto-launch. Double-click FixOnce.app to start.")

# ============ Main Installation ============

def main():
    """Main installation process"""
    print_banner()

    print(f"{Colors.BOLD}Platform:{Colors.END} {get_platform().title()}")
    print(f"{Colors.BOLD}Python:{Colors.END} {sys.version.split()[0]}")
    print(f"{Colors.BOLD}Location:{Colors.END} {get_fixonce_dir()}")

    # Run installation steps
    steps = [
        ("Dependencies", install_dependencies),
        ("Detect Editors", detect_editors),
        ("Configure MCP", lambda: configure_mcp(detect_editors())),
        ("Sync Rules", sync_rules),
        ("Start Server", start_server_and_open_dashboard),
    ]

    # Step 1: Dependencies
    install_dependencies()

    # Step 2: Detect editors
    editors = detect_editors()

    # Step 3: Configure MCP
    configure_mcp(editors)

    # Step 4: Sync rules
    sync_rules()

    # Create launcher scripts
    create_launcher_scripts()

    # Add to Dock/Desktop
    add_to_dock_or_desktop()

    # Step 5: Configure auto-start (NEW!)
    configure_auto_start()

    # Step 6: Chrome Extension instructions (NEW!)
    show_chrome_extension_instructions()

    # Step 7: Start server and launch app
    start_app()

    # Done!
    print(f"""
{'═' * 60}

  {Colors.GREEN}✓ Installation Complete!{Colors.END}

  {Colors.BOLD}FixOnce is now in your Dock/Desktop!{Colors.END}
  Just click the FixOnce icon to start.

  {Colors.BOLD}To start a session:{Colors.END}
    In Claude Code / Cursor / GitHub Copilot, just say:
    "היי" or "מה המצב?" or "hello"

  {Colors.YELLOW}NOTE: Restart Cursor/GitHub Copilot to apply changes!{Colors.END}

{'═' * 60}
""")

    # Keep window open on Windows
    if get_platform() == 'windows':
        input("\nPress Enter to close...")

if __name__ == "__main__":
    main()
