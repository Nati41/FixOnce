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
import re
from pathlib import Path

# FastMCP environment settings
# FASTMCP_CHECK_FOR_UPDATES accepts: 'stable', 'prerelease', 'off' (NOT 'true'/'false')
FASTMCP_ENV = {
    "FASTMCP_SHOW_CLI_BANNER": "false",
    "FASTMCP_CHECK_FOR_UPDATES": "off",
}

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


def _build_stdio_mcp_config(command: str, server_path: str, pythonpath: str, fastmcp_path: str = None) -> dict:
    """Build a stdio MCP config shared by all supported editors."""
    if fastmcp_path:
        return {
            "command": fastmcp_path,
            "args": ["run", server_path, "--transport", "stdio", "--no-banner"],
            "env": {"PYTHONPATH": pythonpath, **FASTMCP_ENV}
        }

    return {
        "command": command,
        "args": [server_path],
        "env": {"PYTHONPATH": pythonpath}
    }


def _toml_quote(value: str) -> str:
    """Quote a string for TOML output."""
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _remove_codex_server_blocks(content: str, server_name: str) -> str:
    """Remove previous FixOnce server blocks from a Codex TOML config."""
    patterns = [
        rf'(?ms)^\[mcp_servers\.{re.escape(server_name)}\]\n(?:.*\n)*?(?=^\[|\Z)',
        rf'(?ms)^\[mcp_servers\.{re.escape(server_name)}\.env\]\n(?:.*\n)*?(?=^\[|\Z)',
    ]

    updated = content
    for pattern in patterns:
        updated = re.sub(pattern, '', updated)
    return updated.strip()


def _configure_codex_mcp_file(path: Path, server_name: str, config: dict):
    """Write or update a Codex MCP server entry in config.toml."""
    existing = ""
    if path.exists():
        existing = path.read_text(encoding='utf-8')

    existing = _remove_codex_server_blocks(existing, server_name)

    block_lines = [
        f"[mcp_servers.{server_name}]",
        f"command = {_toml_quote(config['command'])}",
    ]

    args = ", ".join(_toml_quote(arg) for arg in config.get("args", []))
    block_lines.append(f"args = [{args}]")

    env = config.get("env", {})
    if env:
        block_lines.append("")
        block_lines.append(f"[mcp_servers.{server_name}.env]")
        for key, value in env.items():
            block_lines.append(f"{key} = {_toml_quote(value)}")

    new_block = "\n".join(block_lines).rstrip() + "\n"

    if existing:
        new_content = existing + "\n\n" + new_block
    else:
        new_content = new_block

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding='utf-8')

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


# ============ PREFLIGHT CHECK ============

class PreflightResult:
    """Result of a single preflight check."""
    def __init__(self, name: str, passed: bool, critical: bool = False,
                 message: str = "", fix_hint: str = ""):
        self.name = name
        self.passed = passed
        self.critical = critical  # If critical and failed, abort install
        self.message = message
        self.fix_hint = fix_hint

    def __repr__(self):
        status = "✅" if self.passed else ("❌" if self.critical else "⚠️")
        return f"{status} {self.name}: {self.message}"


def check_python_version() -> PreflightResult:
    """Check Python version is 3.8+"""
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    if version.major < 3 or (version.major == 3 and version.minor < 8):
        return PreflightResult(
            name="Python Version",
            passed=False,
            critical=True,
            message=f"Python {version_str} is too old (need 3.8+)",
            fix_hint="Install Python 3.8 or newer: https://python.org/downloads"
        )

    return PreflightResult(
        name="Python Version",
        passed=True,
        message=f"Python {version_str}"
    )


def check_write_permissions() -> PreflightResult:
    """Check write permissions for all required directories."""
    fixonce_dir = get_fixonce_dir()
    data_dir = fixonce_dir / "data"

    dirs_to_check = [
        (data_dir, "data directory"),
        (fixonce_dir / "src", "source directory"),
    ]

    home = Path.home()
    dirs_to_check.append((home / ".fixonce", "~/.fixonce config"))

    failed = []

    for dir_path, name in dirs_to_check:
        if dir_path.exists():
            test_file = dir_path / ".write_test_fixonce"
            try:
                test_file.write_text("test")
                test_file.unlink()
            except (PermissionError, OSError):
                failed.append(f"{name} ({dir_path})")
        else:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                test_file = dir_path / ".write_test_fixonce"
                test_file.write_text("test")
                test_file.unlink()
            except (PermissionError, OSError):
                failed.append(f"{name} ({dir_path})")

    if failed:
        return PreflightResult(
            name="Write Permissions",
            passed=False,
            critical=True,
            message=f"Cannot write to: {', '.join(failed)}",
            fix_hint="Check folder permissions or run from a different location"
        )

    return PreflightResult(
        name="Write Permissions",
        passed=True,
        message="All directories writable"
    )


def check_install_path() -> PreflightResult:
    """Check install path is valid and contains expected files."""
    fixonce_dir = get_fixonce_dir()

    required = [
        ("src/server.py", "server script"),
        ("requirements.txt", "requirements file"),
        ("data", "data directory"),
    ]

    missing = []
    for path, name in required:
        if not (fixonce_dir / path).exists():
            missing.append(name)

    if missing:
        return PreflightResult(
            name="Install Path",
            passed=False,
            critical=True,
            message=f"Missing: {', '.join(missing)}",
            fix_hint=f"Incomplete installation at {fixonce_dir}"
        )

    return PreflightResult(
        name="Install Path",
        passed=True,
        message=str(fixonce_dir)
    )


def check_port_availability() -> PreflightResult:
    """Check if at least one port in 5000-5009 range is available."""
    import socket

    available_port = None

    for port in range(5000, 5010):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            result = s.connect_ex(('localhost', port))
            if result != 0:
                available_port = port
                break

    if available_port is None:
        return PreflightResult(
            name="Port Availability",
            passed=False,
            critical=False,
            message="Ports 5000-5009 all in use",
            fix_hint="Close other applications or FixOnce instances"
        )

    if available_port == 5000:
        return PreflightResult(
            name="Port Availability",
            passed=True,
            message="Port 5000 available"
        )
    else:
        return PreflightResult(
            name="Port Availability",
            passed=True,
            message=f"Port 5000 busy, will use {available_port}"
        )


def check_browser() -> PreflightResult:
    """Check if a supported browser is installed."""
    current_platform = get_platform()
    browsers_found = []

    if current_platform == 'mac':
        browser_paths = [
            ("/Applications/Google Chrome.app", "Chrome"),
            ("/Applications/Brave Browser.app", "Brave"),
            ("/Applications/Microsoft Edge.app", "Edge"),
            ("/Applications/Arc.app", "Arc"),
            ("/Applications/Firefox.app", "Firefox"),
        ]
        for path, name in browser_paths:
            if Path(path).exists():
                browsers_found.append(name)

    elif current_platform == 'windows':
        program_files = [
            Path(os.environ.get('PROGRAMFILES', 'C:\\Program Files')),
            Path(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)')),
            Path(os.environ.get('LOCALAPPDATA', ''))
        ]
        browser_checks = [
            ("Google/Chrome/Application/chrome.exe", "Chrome"),
            ("BraveSoftware/Brave-Browser/Application/brave.exe", "Brave"),
            ("Microsoft/Edge/Application/msedge.exe", "Edge"),
        ]
        for base in program_files:
            for rel_path, name in browser_checks:
                if (base / rel_path).exists():
                    if name not in browsers_found:
                        browsers_found.append(name)

    if not browsers_found:
        return PreflightResult(
            name="Browser",
            passed=False,
            critical=False,
            message="No supported browser found",
            fix_hint="Install Chrome, Brave, or Edge for browser extension"
        )

    if "Chrome" in browsers_found:
        return PreflightResult(
            name="Browser",
            passed=True,
            message=f"Chrome found (+ {len(browsers_found)-1} others)" if len(browsers_found) > 1 else "Chrome"
        )

    return PreflightResult(
        name="Browser",
        passed=True,
        message=f"{browsers_found[0]} (extension may have limited support)"
    )


def check_disk_space() -> PreflightResult:
    """Check if there's enough disk space (at least 100MB)."""
    fixonce_dir = get_fixonce_dir()

    try:
        if platform.system() == 'Windows':
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(str(fixonce_dir)), None, None, ctypes.pointer(free_bytes)
            )
            free_mb = free_bytes.value / (1024 * 1024)
        else:
            stat = os.statvfs(fixonce_dir)
            free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)

        if free_mb < 100:
            return PreflightResult(
                name="Disk Space",
                passed=False,
                critical=False,
                message=f"Only {free_mb:.0f}MB free",
                fix_hint="Free up at least 100MB of disk space"
            )

        return PreflightResult(
            name="Disk Space",
            passed=True,
            message=f"{free_mb:.0f}MB free"
        )
    except Exception:
        return PreflightResult(
            name="Disk Space",
            passed=True,
            message="Could not check (assuming OK)"
        )


def check_fixonce_portable() -> PreflightResult:
    """Check for existing .fixonce/ directory (portable project memory)."""
    fixonce_dir = get_fixonce_dir()
    project_fixonce = fixonce_dir / ".fixonce"

    if project_fixonce.exists():
        metadata_file = project_fixonce / "metadata.json"
        if metadata_file.exists():
            try:
                import json
                with open(metadata_file) as f:
                    metadata = json.load(f)
                project_id = metadata.get("project_id", "unknown")
                return PreflightResult(
                    name="Project Memory",
                    passed=True,
                    message=f"Found .fixonce/ (ID: {project_id}) - will preserve"
                )
            except Exception:
                pass
        return PreflightResult(
            name="Project Memory",
            passed=True,
            message="Found .fixonce/ - will preserve"
        )

    return PreflightResult(
        name="Project Memory",
        passed=True,
        message="No existing .fixonce/ (new install)"
    )


def run_preflight_checks() -> bool:
    """
    Run all preflight checks before installation.
    Returns True if all critical checks pass, False otherwise.
    """
    print(f"\n{Colors.BLUE}{'═' * 50}{Colors.END}")
    print(f"{Colors.BOLD}  PREFLIGHT CHECK{Colors.END}")
    print(f"{Colors.BLUE}{'═' * 50}{Colors.END}\n")

    checks = [
        check_python_version(),
        check_install_path(),
        check_write_permissions(),
        check_port_availability(),
        check_browser(),
        check_disk_space(),
        check_fixonce_portable(),
    ]

    critical_failures = []
    warnings = []

    for result in checks:
        if result.passed:
            print(f"  {Colors.GREEN}✅{Colors.END} {result.name}: {result.message}")
        elif result.critical:
            print(f"  {Colors.RED}❌{Colors.END} {result.name}: {result.message}")
            if result.fix_hint:
                print(f"     {Colors.YELLOW}→ {result.fix_hint}{Colors.END}")
            critical_failures.append(result)
        else:
            print(f"  {Colors.YELLOW}⚠️{Colors.END}  {result.name}: {result.message}")
            if result.fix_hint:
                print(f"     {Colors.YELLOW}→ {result.fix_hint}{Colors.END}")
            warnings.append(result)

    print(f"\n{Colors.BLUE}{'─' * 50}{Colors.END}")

    if critical_failures:
        print(f"\n{Colors.RED}{Colors.BOLD}❌ PREFLIGHT FAILED{Colors.END}")
        print(f"{Colors.RED}Cannot continue installation. Fix the issues above.{Colors.END}\n")
        return False

    if warnings:
        print(f"\n{Colors.YELLOW}⚠️  {len(warnings)} warning(s) - installation will continue{Colors.END}")
    else:
        print(f"\n{Colors.GREEN}✅ All checks passed{Colors.END}")

    print()
    return True


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
        'codex': False,
        'vscode': False,
        'copilot': False
    }

    current_platform = get_platform()

    if current_platform == 'mac':
        success, _ = run_command(['which', 'codex'])
        editors['codex'] = success or (Path.home() / '.codex').exists()

        # Check for Claude Code CLI
        success, _ = run_command(['which', 'claude'])
        editors['claude_code'] = success

        # Check for Cursor
        editors['cursor'] = Path('/Applications/Cursor.app').exists()

        # Check for VS Code (GitHub Copilot runs inside VS Code)
        editors['vscode'] = Path('/Applications/Visual Studio Code.app').exists()
        editors['copilot'] = editors['vscode']  # Copilot is a VS Code extension

    elif current_platform == 'windows':
        success, _ = run_command(['where', 'codex'], silent=True)
        editors['codex'] = success or (Path.home() / '.codex').exists()

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

    else:
        success, _ = run_command(['which', 'codex'])
        editors['codex'] = success or (Path.home() / '.codex').exists()

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

    stdio_config = _build_stdio_mcp_config(
        python_path,
        str(mcp_server_path),
        src_path,
        fastmcp_path
    )

    # Configure Claude Code using the CLI (the proper way)
    if editors.get('claude_code', False):
        try:
            # Remove existing fixonce config if any
            subprocess.run(['claude', 'mcp', 'remove', 'fixonce', '-s', 'user'],
                         capture_output=True, timeout=10)

            # Use fastmcp run if available, otherwise direct python
            mcp_json = json.dumps(stdio_config)

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
                _configure_mcp_file(Path.home() / '.claude.json', stdio_config)
                configured_count += 1

        except Exception as e:
            print(f"  {Colors.YELLOW}[WARN]{Colors.END} Claude CLI not available: {e}")
            # Fallback to file method
            try:
                _configure_mcp_file(Path.home() / '.claude.json', stdio_config)
                print(f"  {Colors.GREEN}[OK]{Colors.END} Claude Code configured via file")
                configured_count += 1
            except Exception as e2:
                print(f"  {Colors.RED}[ERROR]{Colors.END} Failed to configure Claude Code: {e2}")

    # Configure Cursor using file method
    if editors.get('cursor', False):
        cursor_path = Path.home() / '.cursor' / 'mcp.json'
        try:
            _configure_mcp_file(cursor_path, stdio_config)
            print(f"  {Colors.GREEN}[OK]{Colors.END} Cursor configured: {cursor_path}")
            configured_count += 1
        except Exception as e:
            print(f"  {Colors.RED}[ERROR]{Colors.END} Failed to configure Cursor: {e}")

    # Configure Codex
    if editors.get('codex', False):
        codex_config = Path.home() / '.codex' / 'config.toml'
        try:
            _configure_codex_mcp_file(codex_config, 'fixonce', stdio_config)
            print(f"  {Colors.GREEN}[OK]{Colors.END} Codex configured: {codex_config}")
            configured_count += 1
        except Exception as e:
            print(f"  {Colors.RED}[ERROR]{Colors.END} Failed to configure Codex: {e}")

    if configured_count == 0:
        print(f"  {Colors.YELLOW}[INFO]{Colors.END} No editors to configure (install Codex, Claude Code, or Cursor first)")

    # Create project-level .mcp.json with CORRECT paths for this machine
    # This is what Claude Code reads when opening the project
    project_mcp_path = fixonce_dir / ".mcp.json"
    project_codex_path = fixonce_dir / ".codex" / "config.toml"
    try:
        project_mcp_config = {"mcpServers": {"fixonce": stdio_config}}

        with open(project_mcp_path, 'w', encoding='utf-8') as f:
            json.dump(project_mcp_config, f, indent=2)
        print(f"  {Colors.GREEN}[OK]{Colors.END} Created .mcp.json with correct paths")
    except Exception as e:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not create .mcp.json: {e}")

    try:
        _configure_codex_mcp_file(project_codex_path, 'fixonce', stdio_config)
        print(f"  {Colors.GREEN}[OK]{Colors.END} Created .codex/config.toml with correct paths")
    except Exception as e:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not create .codex/config.toml: {e}")

    return True


def _configure_mcp_file(path: Path, server_config: dict):
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

    existing_config['mcpServers']['fixonce'] = server_config

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
    """
    Check if FixOnce server is running FOR THIS USER.

    Cross-user safety: Only returns True if the server belongs to
    the current user AND the same installation path.
    """
    import urllib.request
    import urllib.error
    import json
    import getpass

    fixonce_dir = get_fixonce_dir()
    port_file = fixonce_dir / "data" / "current_port.txt"
    current_user = getpass.getuser()
    my_install_path = str(fixonce_dir)

    # First try to read actual port from file (server writes this on startup)
    ports_to_try = list(range(port, port + 10))  # 5000-5009
    if port_file.exists():
        try:
            saved_port = int(port_file.read_text().strip())
            # Put saved port first in the list
            if saved_port in ports_to_try:
                ports_to_try.remove(saved_port)
            ports_to_try.insert(0, saved_port)
        except (ValueError, IOError):
            pass

    for attempt in range(max_attempts):
        for p in ports_to_try:
            try:
                # Use /api/ping which returns {"service": "fixonce", "user": "...", "install_path": "..."}
                url = f"http://localhost:{p}/api/ping"
                req = urllib.request.urlopen(url, timeout=2)
                if req.status == 200:
                    data = json.loads(req.read().decode())
                    # Verify it's actually FixOnce
                    if data.get("service") == "fixonce":
                        # Cross-user check: verify this is OUR server
                        server_user = data.get("user", "")
                        server_path = data.get("install_path", "")

                        if server_user == current_user and server_path == my_install_path:
                            # This is OUR server
                            return True, p
                        else:
                            # Server belongs to different user/installation - skip
                            print(f"  {Colors.YELLOW}[INFO]{Colors.END} Port {p}: server belongs to '{server_user}' - skipping")
                            continue
            except (urllib.error.URLError, json.JSONDecodeError, Exception):
                pass
        import time
        time.sleep(0.5)

    # Return saved port if available, else default
    if port_file.exists():
        try:
            return False, int(port_file.read_text().strip())
        except (ValueError, IOError):
            pass
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
    print(f"\n{Colors.BLUE}[6/8]{Colors.END} Configuring auto-start...")

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


# ============ Step 7: Mark Installation Complete ============

def mark_installation_complete() -> bool:
    """Mark FixOnce as installed by creating install_state.json.

    CRITICAL: Without this file, the server redirects to /install forever.
    This must be called by CLI installer since web installer may not complete.
    """
    print(f"\n{Colors.BLUE}[7/8]{Colors.END} Marking installation complete...")

    from datetime import datetime

    # Create ~/.fixonce/install_state.json
    user_data_dir = Path.home() / ".fixonce"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    install_state = user_data_dir / "install_state.json"
    state = {
        "installed": True,
        "installed_at": datetime.now().isoformat(),
        "version": "1.0.11",
        "installer": "cli"
    }

    try:
        with open(install_state, 'w') as f:
            json.dump(state, f, indent=2)
        print(f"  {Colors.GREEN}[OK]{Colors.END} Installation state saved to {install_state}")
        return True
    except Exception as e:
        print(f"  {Colors.RED}[ERROR]{Colors.END} Could not save installation state: {e}")
        return False


# ============ Step 8: Chrome Extension ============

def show_chrome_extension_instructions():
    """Show instructions for installing Chrome extension and try to open Chrome"""
    print(f"\n{Colors.BLUE}[8/8]{Colors.END} Chrome Extension (for browser error capture)...")

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
    """
    Initialize data directory for FixOnce installation.

    NON-DESTRUCTIVE POLICY:
    - Creates files/dirs only if they don't exist
    - NEVER deletes existing data
    - NEVER touches .fixonce/ directories (project memory)
    - Preserves all decisions, insights, and solutions

    This function only initializes the FixOnce APPLICATION data,
    not user project memory (which lives in each project's .fixonce/).
    """
    print(f"\n{Colors.BLUE}[0/7]{Colors.END} Initializing data directory...")

    fixonce_dir = get_fixonce_dir()
    data_dir = fixonce_dir / "data"

    # PROTECTION: Never touch .fixonce/ (project memory)
    project_fixonce = fixonce_dir / ".fixonce"
    if project_fixonce.exists():
        print(f"  {Colors.GREEN}[OK]{Colors.END} Found existing .fixonce/ - preserving project memory")

    # Create necessary directories (only if missing)
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


def open_web_installer():
    """Open the web-based installer in browser."""
    print(f"\n{Colors.BLUE}[INSTALLER]{Colors.END} Opening FixOnce installer...")

    import time
    fixonce_dir = get_fixonce_dir()
    current_platform = get_platform()
    server_script = fixonce_dir / "src" / "server.py"
    port_file = fixonce_dir / "data" / "current_port.txt"
    log_file = fixonce_dir / "data" / "server_startup.log"

    # Delete old port file to ensure we get fresh port
    if port_file.exists():
        print(f"  Removing old port file...")
        port_file.unlink()

    # Check if server already running (scan ports 5000-5009)
    print(f"  Checking for running server...")
    is_running, port = check_server_health(5000, max_attempts=2)
    if is_running:
        print(f"  Found existing server on port {port}")

    if not is_running:
        print(f"  Starting FixOnce server...")

        # Start server with logging
        with open(log_file, 'w') as log:
            subprocess.Popen(
                [sys.executable, str(server_script), '--flask-only'],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(fixonce_dir / "src"),
                start_new_session=True
            )

        # Wait for port file (server writes this immediately on startup)
        print(f"  Waiting for server...")
        for i in range(30):  # 15 seconds max
            if port_file.exists():
                try:
                    port = int(port_file.read_text().strip())
                    print(f"  Server starting on port {port}...")
                    break
                except (ValueError, IOError):
                    pass
            time.sleep(0.5)
        else:
            print(f"  {Colors.RED}[ERROR]{Colors.END} Server didn't write port file")
            if log_file.exists():
                print(f"  Log: {log_file}")
            return False

        # Wait for server to respond
        for i in range(20):  # 10 seconds max
            try:
                import urllib.request
                req = urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=1)
                if req.status == 200:
                    print(f"  {Colors.GREEN}[OK]{Colors.END} Server running on port {port}")
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            print(f"  {Colors.YELLOW}[WARN]{Colors.END} Server may still be starting...")

    # Open installer in browser
    installer_url = f"http://localhost:{port}/install"
    try:
        if current_platform == 'mac':
            subprocess.run(['open', installer_url], capture_output=True)
        elif current_platform == 'windows':
            subprocess.run(f'start "" "{installer_url}"', shell=True, capture_output=True)
        else:
            subprocess.run(['xdg-open', installer_url], capture_output=True)

        print(f"  {Colors.GREEN}[OK]{Colors.END} Installer opened: {installer_url}")
        return True
    except Exception as e:
        print(f"  {Colors.YELLOW}[WARN]{Colors.END} Could not open browser: {e}")
        print(f"  Open manually: {installer_url}")
        return True


def main():
    """Main installation process - minimal setup then open web installer."""
    print_banner()

    print(f"{Colors.BOLD}Platform:{Colors.END} {get_platform().title()}")
    print(f"{Colors.BOLD}Python:{Colors.END} {sys.version.split()[0]}")
    print(f"{Colors.BOLD}Location:{Colors.END} {get_fixonce_dir()}")

    # PREFLIGHT CHECK - must pass before anything else
    if not run_preflight_checks():
        print(f"{Colors.RED}Installation aborted.{Colors.END}")
        sys.exit(1)

    # Step 1: Initialize data (NON-DESTRUCTIVE - never deletes existing data)
    initialize_fresh_data()

    # Step 2: Install dependencies
    install_dependencies()

    # Step 3: Detect editors and configure MCP
    editors = detect_editors()
    configure_mcp(editors)

    # Step 4: Configure rules
    sync_rules()

    # Step 5: Create launcher scripts
    create_launcher_scripts()

    # Step 6: Configure auto-start
    configure_auto_start()

    # Step 7: Mark installation as complete
    mark_installation_complete()

    # Step 8: Open web installer
    open_web_installer()

    print(f"""
{'═' * 60}

  {Colors.GREEN}FixOnce Installer opened in your browser!{Colors.END}

  Complete the setup there and you're ready to go.

  {Colors.BOLD}After installation:{Colors.END}
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


# ============ DOCTOR / REPAIR MODE ============

class DoctorCheck:
    """Result of a doctor check with optional repair action."""
    def __init__(self, name: str, status: str, message: str = "",
                 repair_fn=None, repair_hint: str = ""):
        self.name = name
        self.status = status  # "ok", "warning", "error"
        self.message = message
        self.repair_fn = repair_fn
        self.repair_hint = repair_hint


def doctor_check_server() -> DoctorCheck:
    """Check if FixOnce server is running."""
    is_running, port = check_server_health(5000, max_attempts=2)

    if is_running:
        return DoctorCheck(
            name="Server",
            status="ok",
            message=f"Running on port {port}"
        )

    return DoctorCheck(
        name="Server",
        status="error",
        message="Not running",
        repair_fn=repair_server,
        repair_hint="Start server"
    )


def repair_server() -> bool:
    """Start the FixOnce server."""
    print(f"    {Colors.BLUE}Starting server...{Colors.END}")
    fixonce_dir = get_fixonce_dir()
    server_script = fixonce_dir / "src" / "server.py"

    try:
        subprocess.Popen(
            [sys.executable, str(server_script), '--flask-only'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(fixonce_dir / "src"),
            start_new_session=True
        )
        import time
        time.sleep(2)
        is_running, port = check_server_health(5000, max_attempts=5)
        if is_running:
            print(f"    {Colors.GREEN}✅ Server started on port {port}{Colors.END}")
            return True
        else:
            print(f"    {Colors.RED}❌ Server failed to start{Colors.END}")
            return False
    except Exception as e:
        print(f"    {Colors.RED}❌ Error: {e}{Colors.END}")
        return False


def doctor_check_mcp() -> DoctorCheck:
    """Check if MCP is configured for Claude Code."""
    home = Path.home()
    claude_config = home / ".claude.json"

    if not claude_config.exists():
        return DoctorCheck(
            name="MCP Config",
            status="error",
            message="Not found",
            repair_fn=repair_mcp,
            repair_hint="Create MCP config"
        )

    try:
        with open(claude_config) as f:
            config = json.load(f)

        mcp_servers = config.get("mcpServers", {})
        if "fixonce" not in mcp_servers:
            return DoctorCheck(
                name="MCP Config",
                status="error",
                message="FixOnce not in config",
                repair_fn=repair_mcp,
                repair_hint="Add FixOnce to MCP"
            )

        return DoctorCheck(
            name="MCP Config",
            status="ok",
            message="Configured for Claude Code"
        )

    except (json.JSONDecodeError, KeyError) as e:
        return DoctorCheck(
            name="MCP Config",
            status="error",
            message=f"Invalid config: {e}",
            repair_fn=repair_mcp,
            repair_hint="Recreate config"
        )


def repair_mcp() -> bool:
    """Repair MCP configuration."""
    print(f"    {Colors.BLUE}Configuring MCP...{Colors.END}")
    editors = detect_editors()
    success = configure_mcp(editors)
    if success:
        print(f"    {Colors.GREEN}✅ MCP configured{Colors.END}")
        print(f"    {Colors.YELLOW}→ Restart Claude Code to apply changes{Colors.END}")
    return success


def doctor_check_extension() -> DoctorCheck:
    """Check if Chrome extension is connected."""
    import urllib.request

    try:
        is_running, port = check_server_health(5000, max_attempts=1)
        if not is_running:
            return DoctorCheck(
                name="Extension",
                status="warning",
                message="Server not running (can't check)",
                repair_hint="Start server first"
            )

        url = f"http://localhost:{port}/api/status"
        req = urllib.request.urlopen(url, timeout=2)
        data = json.loads(req.read().decode())

        if data.get("extension_connected"):
            return DoctorCheck(name="Extension", status="ok", message="Connected")
        else:
            return DoctorCheck(
                name="Extension",
                status="warning",
                message="Not connected",
                repair_hint="Install from Chrome Web Store"
            )

    except Exception:
        return DoctorCheck(
            name="Extension",
            status="warning",
            message="Could not check",
            repair_hint="Ensure server is running"
        )


def doctor_check_data() -> DoctorCheck:
    """Check if data directory is healthy."""
    fixonce_dir = get_fixonce_dir()
    data_dir = fixonce_dir / "data"

    issues = []

    if not data_dir.exists():
        return DoctorCheck(
            name="Data Directory",
            status="error",
            message="Missing",
            repair_fn=repair_data,
            repair_hint="Create data directory"
        )

    required_dirs = ["projects_v2", "global"]
    for d in required_dirs:
        if not (data_dir / d).exists():
            issues.append(f"missing {d}/")

    required_files = ["active_project.json"]
    for f in required_files:
        if not (data_dir / f).exists():
            issues.append(f"missing {f}")

    test_file = data_dir / ".doctor_test"
    try:
        test_file.write_text("test")
        test_file.unlink()
    except (PermissionError, OSError):
        issues.append("not writable")

    if issues:
        return DoctorCheck(
            name="Data Directory",
            status="error" if "not writable" in issues else "warning",
            message=", ".join(issues),
            repair_fn=repair_data,
            repair_hint="Initialize data directory"
        )

    return DoctorCheck(name="Data Directory", status="ok", message="Healthy")


def repair_data() -> bool:
    """Repair data directory."""
    print(f"    {Colors.BLUE}Initializing data directory...{Colors.END}")
    try:
        initialize_fresh_data()
        print(f"    {Colors.GREEN}✅ Data directory initialized{Colors.END}")
        return True
    except Exception as e:
        print(f"    {Colors.RED}❌ Error: {e}{Colors.END}")
        return False


def doctor_check_fixonce_portable() -> DoctorCheck:
    """Check for .fixonce/ portable project memory."""
    fixonce_dir = get_fixonce_dir()
    project_fixonce = fixonce_dir / ".fixonce"

    if project_fixonce.exists():
        metadata_file = project_fixonce / "metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file) as f:
                    metadata = json.load(f)
                project_id = metadata.get("project_id", "unknown")
                return DoctorCheck(
                    name="Project Memory",
                    status="ok",
                    message=f".fixonce/ exists (ID: {project_id})"
                )
            except Exception:
                return DoctorCheck(
                    name="Project Memory",
                    status="warning",
                    message=".fixonce/ exists but metadata invalid"
                )
        return DoctorCheck(
            name="Project Memory",
            status="warning",
            message=".fixonce/ exists but no metadata.json"
        )

    return DoctorCheck(
        name="Project Memory",
        status="ok",
        message="No .fixonce/ (will be created on first use)"
    )


def run_doctor():
    """Run the FixOnce Doctor to diagnose and repair issues."""
    print(f"\n{Colors.BLUE}{'═' * 50}{Colors.END}")
    print(f"{Colors.BOLD}  🩺 FixOnce Doctor{Colors.END}")
    print(f"{Colors.BLUE}{'═' * 50}{Colors.END}\n")

    checks = [
        doctor_check_server(),
        doctor_check_mcp(),
        doctor_check_extension(),
        doctor_check_data(),
        doctor_check_fixonce_portable(),
    ]

    repairable = []

    for i, check in enumerate(checks):
        if check.status == "ok":
            icon = f"{Colors.GREEN}✅{Colors.END}"
        elif check.status == "warning":
            icon = f"{Colors.YELLOW}⚠️{Colors.END} "
        else:
            icon = f"{Colors.RED}❌{Colors.END}"

        print(f"  {icon} {check.name}: {check.message}")

        if check.repair_fn:
            repairable.append((i, check))
            print(f"       {Colors.YELLOW}[{len(repairable)}] {check.repair_hint}{Colors.END}")
        elif check.repair_hint and check.status != "ok":
            print(f"       {Colors.YELLOW}→ {check.repair_hint}{Colors.END}")

    print(f"\n{Colors.BLUE}{'─' * 50}{Colors.END}")

    errors = sum(1 for c in checks if c.status == "error")
    warnings = sum(1 for c in checks if c.status == "warning")

    if errors == 0 and warnings == 0:
        print(f"\n{Colors.GREEN}✅ All systems healthy!{Colors.END}\n")
        return True

    if repairable:
        print(f"\n{Colors.BOLD}Repair Options:{Colors.END}")
        print(f"  [A] Repair All ({len(repairable)} issues)")
        for i, (_, check) in enumerate(repairable, 1):
            print(f"  [{i}] {check.repair_hint}")
        print(f"  [Q] Quit")

        choice = input(f"\n{Colors.BOLD}Choice:{Colors.END} ").strip().upper()

        if choice == 'A':
            print(f"\n{Colors.BOLD}Repairing all issues...{Colors.END}\n")
            for _, check in repairable:
                print(f"  {Colors.BLUE}▶{Colors.END} {check.name}:")
                check.repair_fn()
                print()
            print(f"{Colors.GREEN}Repair complete. Run doctor again to verify.{Colors.END}\n")

        elif choice.isdigit() and 1 <= int(choice) <= len(repairable):
            idx = int(choice) - 1
            _, check = repairable[idx]
            print(f"\n  {Colors.BLUE}▶{Colors.END} {check.name}:")
            check.repair_fn()
            print()

        elif choice == 'Q':
            print("Bye!")
        else:
            print(f"{Colors.YELLOW}Invalid choice{Colors.END}")

    return errors == 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FixOnce Installer & Doctor")
    parser.add_argument('--doctor', '-d', action='store_true',
                        help='Run Doctor mode to diagnose and repair issues')
    parser.add_argument('--preflight', '-p', action='store_true',
                        help='Run only preflight checks')
    args = parser.parse_args()

    if args.doctor:
        print_banner()
        run_doctor()
    elif args.preflight:
        print_banner()
        run_preflight_checks()
    else:
        main()
