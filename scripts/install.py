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
        # Claude Code uses ~/.claude.json (NOT ~/.claude/settings.json)
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

    # Make MCP server executable
    try:
        os.chmod(mcp_server_path, 0o755)
    except Exception:
        pass

    src_path = str(fixonce_dir / "src")
    python_path = sys.executable
    configured_count = 0

    # Find fastmcp path
    fastmcp_path = None
    try:
        result = subprocess.run(['which', 'fastmcp'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            fastmcp_path = result.stdout.strip()
    except Exception:
        pass

    # Fallback paths for fastmcp
    if not fastmcp_path:
        possible_paths = [
            Path(sys.executable).parent / 'fastmcp',
            Path('/usr/local/bin/fastmcp'),
            Path.home() / '.local' / 'bin' / 'fastmcp',
        ]
        for p in possible_paths:
            if p.exists():
                fastmcp_path = str(p)
                break

    # Configure Claude Code using the CLI (the proper way)
    if editors.get('claude_code', False):
        try:
            # Remove existing fixonce config if any
            subprocess.run(['claude', 'mcp', 'remove', 'fixonce', '-s', 'user'],
                         capture_output=True, timeout=10)

            # Use fastmcp run if available, otherwise direct python
            if fastmcp_path:
                mcp_json = json.dumps({
                    "command": fastmcp_path,
                    "args": ["run", str(mcp_server_path), "--transport", "stdio", "--no-banner"],
                    "env": {
                        "PYTHONPATH": src_path,
                        "FASTMCP_SHOW_CLI_BANNER": "false",
                        "FASTMCP_CHECK_FOR_UPDATES": "false"
                    }
                })
            else:
                mcp_json = json.dumps({
                    "command": python_path,
                    "args": [str(mcp_server_path)],
                    "env": {"PYTHONPATH": src_path}
                })

            result = subprocess.run(
                ['claude', 'mcp', 'add-json', 'fixonce', mcp_json, '-s', 'user'],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                print(f"  {Colors.GREEN}[OK]{Colors.END} Claude Code configured via CLI")
                configured_count += 1
            else:
                print(f"  {Colors.YELLOW}[WARN]{Colors.END} Claude CLI config failed, trying file method...")
                # Fallback to file method
                _configure_mcp_file(Path.home() / '.claude.json', python_path, str(mcp_server_path), src_path, fastmcp_path)
                configured_count += 1

        except Exception as e:
            print(f"  {Colors.YELLOW}[WARN]{Colors.END} Claude CLI not available: {e}")
            # Fallback to file method
            try:
                _configure_mcp_file(Path.home() / '.claude.json', python_path, str(mcp_server_path), src_path, fastmcp_path)
                print(f"  {Colors.GREEN}[OK]{Colors.END} Claude Code configured via file")
                configured_count += 1
            except Exception as e2:
                print(f"  {Colors.RED}[ERROR]{Colors.END} Failed to configure Claude Code: {e2}")

    # Configure Cursor using file method
    if editors.get('cursor', False):
        cursor_path = Path.home() / '.cursor' / 'mcp.json'
        try:
            _configure_mcp_file(cursor_path, python_path, str(mcp_server_path), src_path, fastmcp_path)
            print(f"  {Colors.GREEN}[OK]{Colors.END} Cursor configured: {cursor_path}")
            configured_count += 1
        except Exception as e:
            print(f"  {Colors.RED}[ERROR]{Colors.END} Failed to configure Cursor: {e}")

    if configured_count == 0:
        print(f"  {Colors.YELLOW}[INFO]{Colors.END} No editors to configure (install Claude Code or Cursor first)")

    # Create project-level .mcp.json with CORRECT paths for this machine
    # This is what Claude Code reads when opening the project
    project_mcp_path = fixonce_dir / ".mcp.json"
    try:
        if fastmcp_path:
            project_mcp_config = {
                "mcpServers": {
                    "fixonce": {
                        "command": fastmcp_path,
                        "args": ["run", str(mcp_server_path), "--transport", "stdio", "--no-banner"],
                        "env": {
                            "PYTHONPATH": src_path,
                            "FASTMCP_SHOW_CLI_BANNER": "false",
                            "FASTMCP_CHECK_FOR_UPDATES": "false"
                        }
                    }
                }
            }
        else:
            project_mcp_config = {
                "mcpServers": {
                    "fixonce": {
                        "command": python_path,
                        "args": [str(mcp_server_path)],
                        "env": {"PYTHONPATH": src_path}
                    }
                }
            }

        with open(project_mcp_path, 'w', encoding='utf-8') as f:
            json.dump(project_mcp_config, f, indent=2)
        print(f"  {Colors.GREEN}[OK]{Colors.END} Created .mcp.json with correct paths")
    except Exception as e:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not create .mcp.json: {e}")

    return True


def _configure_mcp_file(path: Path, python_cmd: str, server_path: str, pythonpath: str, fastmcp_path: str = None):
    """Helper to configure MCP via config file"""
    existing_config = {}
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        except json.JSONDecodeError:
            existing_config = {}

    if 'mcpServers' not in existing_config:
        existing_config['mcpServers'] = {}

    # Use fastmcp run if available
    if fastmcp_path:
        existing_config['mcpServers']['fixonce'] = {
            "command": fastmcp_path,
            "args": ["run", server_path, "--transport", "stdio", "--no-banner"],
            "env": {
                "PYTHONPATH": pythonpath,
                "FASTMCP_SHOW_CLI_BANNER": "false",
                "FASTMCP_CHECK_FOR_UPDATES": "false"
            }
        }
    else:
        existing_config['mcpServers']['fixonce'] = {
            "command": python_cmd,
            "args": [server_path],
            "env": {"PYTHONPATH": pythonpath}
        }

    # Ensure parent directory exists
    if path.parent != Path.home():
        path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(existing_config, f, indent=2)

# ============ Step 4: Configure Editor Rules ============

FIXONCE_RULES = """# FixOnce - AI Memory Layer

## CRITICAL: Auto-Connect on EVERY Conversation

On EVERY conversation start (ANY greeting like hi, hey, hello, היי, שלום, מה קורה):

1. **IMMEDIATELY call** `auto_init_session` with the current working directory
2. If successful, show the project context
3. If it fails (wrong directory), tell user to open from a project folder

Example flow:
```
User: hi
AI: [calls auto_init_session(cwd="current/path")]
AI: 🧠 FixOnce | Connected to [project]
    ...shows context...
```

## During Work
- Before fixing errors: call `search_past_solutions()` first
- After fixing: call `solution_applied()` to save the fix
- Important decisions: call `log_decision()`

## Session End
On exit (bye, done, סיימתי): summarize what was done.

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

    # Configure Claude Code CLAUDE.md (always update to latest rules)
    claude_md_path = Path.home() / ".claude" / "CLAUDE.md"
    try:
        claude_md_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing content if any
        existing_content = ""
        if claude_md_path.exists():
            with open(claude_md_path, 'r', encoding='utf-8') as f:
                existing_content = f.read()

        # Check if FixOnce rules are already there
        if "FixOnce" not in existing_content:
            # Append FixOnce rules
            with open(claude_md_path, 'a', encoding='utf-8') as f:
                f.write(f"\n\n{FIXONCE_RULES}\n")
            print(f"  {Colors.GREEN}[OK]{Colors.END} Added FixOnce rules to CLAUDE.md")
        else:
            print(f"  {Colors.GREEN}[OK]{Colors.END} CLAUDE.md already has FixOnce rules")
    except Exception as e:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not update CLAUDE.md: {e}")

    # Configure Claude Code hooks (CRITICAL for auto-connect!)
    configure_claude_hooks(fixonce_dir)

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


def configure_claude_hooks(fixonce_dir: Path) -> bool:
    """Configure Claude Code hooks for auto-connect.

    This is CRITICAL - hooks ensure Claude calls auto_init_session
    on every conversation start.
    """
    settings_path = Path.home() / ".claude" / "settings.json"

    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing settings
        existing = {}
        if settings_path.exists():
            with open(settings_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)

        # Prepare hooks config
        hooks_dir = fixonce_dir / "hooks"
        session_start = str(hooks_dir / "session_start.sh")
        session_end = str(hooks_dir / "session_end.sh")
        post_tool = str(hooks_dir / "post_tool_use.sh")

        # Make hooks executable
        for hook_file in [session_start, session_end, post_tool]:
            if Path(hook_file).exists():
                os.chmod(hook_file, 0o755)

        # Configure hooks
        existing["hooks"] = {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": session_start,
                            "timeout": 5
                        }
                    ]
                }
            ],
            "SessionEnd": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": session_end,
                            "timeout": 5
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Edit|Write|NotebookEdit|Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": post_tool,
                            "timeout": 5
                        }
                    ]
                }
            ]
        }

        # Enable MCP for all projects
        existing["enableAllProjectMcpServers"] = True

        # Save settings
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2)

        print(f"  {Colors.GREEN}[OK]{Colors.END} Claude Code hooks configured (auto-connect enabled)")
        return True

    except Exception as e:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not configure hooks: {e}")
        return False

# ============ Step 5: Start Server & Open Dashboard ============

def check_server_health(port: int = 5000, max_attempts: int = 10) -> tuple:
    """Check if server is running and healthy. Returns (is_healthy, actual_port)"""
    import urllib.request
    import urllib.error

    for attempt in range(max_attempts):
        for p in [port, port + 1, port + 2]:  # Try a few ports
            try:
                url = f"http://localhost:{p}/api/health"
                req = urllib.request.urlopen(url, timeout=2)
                if req.status == 200:
                    return True, p
            except (urllib.error.URLError, Exception):
                pass
        import time
        time.sleep(0.5)

    return False, port


def start_server_and_open_dashboard() -> bool:
    """Start the server and open dashboard with health check"""
    print(f"\n{Colors.BLUE}[5/5]{Colors.END} Starting FixOnce...")

    fixonce_dir = get_fixonce_dir()
    server_script = fixonce_dir / "src" / "server.py"

    if not server_script.exists():
        print(f"  {Colors.RED}[ERROR]{Colors.END} Server script not found")
        return False

    current_platform = get_platform()

    # Check if server already running
    is_running, running_port = check_server_health(5000, max_attempts=2)
    if is_running:
        print(f"  {Colors.GREEN}[OK]{Colors.END} Server already running on port {running_port}")
        dashboard_url = f"http://localhost:{running_port}"
    else:
        # Start server in background
        try:
            if current_platform == 'windows':
                python_cmd = sys.executable
                subprocess.Popen(
                    f'start /B "" "{python_cmd}" "{server_script}" --flask-only',
                    shell=True,
                    cwd=str(fixonce_dir / "src")
                )
            else:
                subprocess.Popen(
                    [sys.executable, str(server_script), '--flask-only'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(fixonce_dir / "src"),
                    start_new_session=True
                )

            print(f"  {Colors.YELLOW}[...]{Colors.END} Server starting, waiting for health check...")

            # Health check with retries
            is_healthy, actual_port = check_server_health(5000, max_attempts=15)

            if is_healthy:
                print(f"  {Colors.GREEN}[OK]{Colors.END} Server healthy on port {actual_port}")
                dashboard_url = f"http://localhost:{actual_port}"
            else:
                print(f"  {Colors.YELLOW}[WARN]{Colors.END} Server may still be starting...")
                dashboard_url = "http://localhost:5000"

        except Exception as e:
            print(f"  {Colors.RED}[ERROR]{Colors.END} Failed to start: {e}")
            return False

    # Open dashboard
    try:
        if current_platform == 'mac':
            subprocess.run(['open', dashboard_url], capture_output=True)
        elif current_platform == 'windows':
            subprocess.run(f'start "" "{dashboard_url}"', shell=True, capture_output=True)
        else:
            subprocess.run(['xdg-open', dashboard_url], capture_output=True)

        print(f"  {Colors.GREEN}[OK]{Colors.END} Dashboard opened: {dashboard_url}")
        return True
    except Exception as e:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not open dashboard: {e}")
        print(f"       Open manually: {dashboard_url}")
        return True

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

def initialize_fresh_data():
    """Initialize fresh data directory for new installation."""
    print(f"\n{Colors.BLUE}[0/7]{Colors.END} Initializing fresh data...")

    fixonce_dir = get_fixonce_dir()
    data_dir = fixonce_dir / "data"

    # Create necessary directories
    (data_dir / "projects_v2").mkdir(parents=True, exist_ok=True)
    (data_dir / "global").mkdir(parents=True, exist_ok=True)

    # Create empty active_project.json (no project selected)
    active_project_file = data_dir / "active_project.json"
    if not active_project_file.exists():
        with open(active_project_file, 'w') as f:
            json.dump({"active_id": None, "working_dir": None}, f, indent=2)
        print(f"  {Colors.GREEN}[OK]{Colors.END} Created empty active_project.json")

    # Create empty session registry
    session_file = data_dir / "session_registry.json"
    if not session_file.exists():
        with open(session_file, 'w') as f:
            json.dump({"sessions": {}}, f, indent=2)

    # Create activity log
    activity_file = data_dir / "activity_log.json"
    if not activity_file.exists():
        with open(activity_file, 'w') as f:
            json.dump({"activities": []}, f, indent=2)

    print(f"  {Colors.GREEN}[OK]{Colors.END} Data directory ready")
    return True


def main():
    """Main installation process"""
    print_banner()

    print(f"{Colors.BOLD}Platform:{Colors.END} {get_platform().title()}")
    print(f"{Colors.BOLD}Python:{Colors.END} {sys.version.split()[0]}")
    print(f"{Colors.BOLD}Location:{Colors.END} {get_fixonce_dir()}")

    # Step 0: Initialize fresh data
    initialize_fresh_data()

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

    # Show final status
    print(f"""
{'═' * 60}

  {Colors.GREEN}✓ Installation Complete!{Colors.END}

  {Colors.BOLD}What was installed:{Colors.END}
    ✓ FixOnce Engine (running on port 5000)
    ✓ MCP configured for: {', '.join([e for e, v in editors.items() if v]) or 'None'}
    ✓ Auto-start on login enabled
    ✓ Dashboard: http://localhost:5000

  {Colors.BOLD}How to use:{Colors.END}
    1. Open your terminal IN A PROJECT FOLDER:
       {Colors.YELLOW}cd ~/your-project && claude{Colors.END}

    2. Just say "hi" and FixOnce will connect automatically

  {Colors.RED}IMPORTANT:{Colors.END} Claude Code must be opened FROM a project folder!
  (Not from home directory)

  {Colors.YELLOW}If you have Cursor open, restart it to apply MCP changes.{Colors.END}

{'═' * 60}
""")

    # Keep window open on Windows
    if get_platform() == 'windows':
        input("\nPress Enter to close...")

if __name__ == "__main__":
    main()
