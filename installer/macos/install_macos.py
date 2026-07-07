#!/usr/bin/env python3
"""
FixOnce macOS Installer
Installs FixOnce.app to /Applications and configures LaunchAgent.

This script is designed to be run from within the built app bundle
or from a DMG installer.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


# Colors for terminal output
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    END = "\033[0m"


# Paths
APPLICATIONS_DIR = Path("/Applications")
APP_NAME = "FixOnce.app"
TARGET_APP = APPLICATIONS_DIR / APP_NAME
USER_DATA_DIR = Path.home() / ".fixonce"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LOGS_DIR = USER_DATA_DIR / "logs"

# LaunchAgent labels to clean up (old split agents)
OLD_LAUNCH_AGENT_LABELS = [
    "com.fixonce.server",
    "com.fixonce.tray",
    "com.fixonce.menubar",
]

# New unified LaunchAgent
LAUNCH_AGENT_LABEL = "com.fixonce.app"
LAUNCH_AGENT_PLIST = LAUNCH_AGENTS_DIR / f"{LAUNCH_AGENT_LABEL}.plist"


def log(message: str, color: str = ""):
    """Print a message with optional color."""
    if color:
        print(f"{color}{message}{Colors.END}")
    else:
        print(message)


def log_step(step: int, total: int, message: str):
    """Print a step message."""
    print(f"\n{Colors.BLUE}[{step}/{total}]{Colors.END} {message}")


def unload_launch_agent(label: str) -> bool:
    """Unload a LaunchAgent by label."""
    plist_path = LAUNCH_AGENTS_DIR / f"{label}.plist"

    # Try to unload
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True
    )

    # Try to remove by label
    subprocess.run(
        ["launchctl", "remove", label],
        capture_output=True
    )

    return True


def remove_old_launch_agents():
    """Remove old split LaunchAgents."""
    for label in OLD_LAUNCH_AGENT_LABELS:
        unload_launch_agent(label)
        plist_path = LAUNCH_AGENTS_DIR / f"{label}.plist"
        if plist_path.exists():
            try:
                plist_path.unlink()
            except Exception:
                pass

    # Also unload the new one in case we're reinstalling
    unload_launch_agent(LAUNCH_AGENT_LABEL)
    if LAUNCH_AGENT_PLIST.exists():
        try:
            LAUNCH_AGENT_PLIST.unlink()
        except Exception:
            pass


def kill_fixonce_processes():
    """Kill any running FixOnce processes."""
    patterns = [
        "FixOnce",
        "app_launcher.py",
        "menubar_app.py",
        "server.py",
        "mcp_memory_server",
    ]

    for pattern in patterns:
        subprocess.run(
            ["pkill", "-f", pattern],
            capture_output=True
        )


def install_app(source_app: Path) -> bool:
    """Install FixOnce.app to /Applications."""
    if not source_app.exists():
        log(f"Error: Source app not found: {source_app}", Colors.RED)
        return False

    # Remove existing app if present
    if TARGET_APP.exists():
        try:
            shutil.rmtree(TARGET_APP)
        except PermissionError:
            log(f"Error: Cannot remove existing app. Try: sudo rm -rf {TARGET_APP}", Colors.RED)
            return False

    # Copy app to /Applications
    try:
        shutil.copytree(source_app, TARGET_APP)
    except PermissionError:
        log(f"Error: Cannot install to /Applications. Try running with sudo.", Colors.RED)
        return False

    return True


def ensure_user_data_dir():
    """Create user data directory if it doesn't exist."""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def merge_config_launch_mode():
    """Ensure config.json has launch_mode: tray without overwriting other settings."""
    config_file = USER_DATA_DIR / "config.json"

    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Only add launch_mode if not already present
    if "launch_mode" not in config:
        config["launch_mode"] = "tray"
        config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")


def create_launch_agent() -> bool:
    """Create the unified LaunchAgent pointing to /Applications/FixOnce.app."""
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    # App executable path
    app_executable = TARGET_APP / "Contents" / "MacOS" / "FixOnce"

    plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{app_executable}</string>
        <string>--tray</string>
    </array>
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
    <integer>30</integer>
    <key>StandardOutPath</key>
    <string>{LOGS_DIR}/fixonce.out.log</string>
    <key>StandardErrorPath</key>
    <string>{LOGS_DIR}/fixonce.err.log</string>
</dict>
</plist>
'''

    try:
        LAUNCH_AGENT_PLIST.write_text(plist_content)
        return True
    except Exception as e:
        log(f"Error creating LaunchAgent: {e}", Colors.RED)
        return False


def load_launch_agent() -> bool:
    """Load the LaunchAgent."""
    result = subprocess.run(
        ["launchctl", "load", str(LAUNCH_AGENT_PLIST)],
        capture_output=True,
        text=True
    )
    return result.returncode == 0


def verify_installation() -> bool:
    """Verify that the installation was successful."""
    checks = [
        (TARGET_APP.exists(), f"{TARGET_APP} exists"),
        ((TARGET_APP / "Contents" / "MacOS" / "FixOnce").exists(), "FixOnce executable exists"),
        (LAUNCH_AGENT_PLIST.exists(), "LaunchAgent plist exists"),
        (USER_DATA_DIR.exists(), "User data directory exists"),
    ]

    all_passed = True
    for passed, description in checks:
        if passed:
            log(f"  ✓ {description}", Colors.GREEN)
        else:
            log(f"  ✗ {description}", Colors.RED)
            all_passed = False

    return all_passed


def main():
    """Main installation routine."""
    print("\n" + "=" * 50)
    print("  FixOnce macOS Installer")
    print("=" * 50)

    # Determine source app location
    # If running from within an app bundle, find the app
    script_path = Path(__file__).resolve()

    # Look for FixOnce.app in various locations
    possible_sources = [
        script_path.parent.parent.parent,  # If inside installer/macos/
        script_path.parent / "FixOnce.app",
        Path.cwd() / "FixOnce.app",
        Path.cwd() / "dist" / "FixOnce.app",
    ]

    source_app = None
    for path in possible_sources:
        if path.name == "FixOnce.app" and path.exists():
            source_app = path
            break
        elif (path / "FixOnce.app").exists():
            source_app = path / "FixOnce.app"
            break

    if not source_app:
        log("\nError: Cannot find FixOnce.app to install.", Colors.RED)
        log("Run this script from the same directory as FixOnce.app", Colors.YELLOW)
        log("or specify the path: python3 install_macos.py /path/to/FixOnce.app", Colors.YELLOW)
        sys.exit(1)

    # Allow specifying source via command line
    if len(sys.argv) > 1:
        source_app = Path(sys.argv[1])
        if not source_app.exists():
            log(f"\nError: Specified app not found: {source_app}", Colors.RED)
            sys.exit(1)

    log(f"\nSource: {source_app}")
    log(f"Target: {TARGET_APP}")

    total_steps = 6

    # Step 1: Kill existing processes
    log_step(1, total_steps, "Stopping existing FixOnce processes...")
    kill_fixonce_processes()
    log("  Done", Colors.GREEN)

    # Step 2: Remove old LaunchAgents
    log_step(2, total_steps, "Removing old LaunchAgents...")
    remove_old_launch_agents()
    log("  Done", Colors.GREEN)

    # Step 3: Install app
    log_step(3, total_steps, "Installing FixOnce.app to /Applications...")
    if not install_app(source_app):
        sys.exit(1)
    log("  Done", Colors.GREEN)

    # Step 4: Ensure user data directory
    log_step(4, total_steps, "Setting up user data directory...")
    ensure_user_data_dir()
    merge_config_launch_mode()
    log("  Done", Colors.GREEN)

    # Step 5: Create LaunchAgent
    log_step(5, total_steps, "Creating LaunchAgent...")
    if not create_launch_agent():
        sys.exit(1)
    log("  Done", Colors.GREEN)

    # Step 6: Verify installation
    log_step(6, total_steps, "Verifying installation...")
    if not verify_installation():
        log("\nWarning: Some verification checks failed.", Colors.YELLOW)

    print("\n" + "=" * 50)
    log("  Installation complete!", Colors.GREEN)
    print("=" * 50)

    print(f"""
To start FixOnce:
  • Double-click /Applications/FixOnce.app
  • Or run: open /Applications/FixOnce.app

To enable auto-start at login:
  launchctl load {LAUNCH_AGENT_PLIST}

To disable auto-start:
  launchctl unload {LAUNCH_AGENT_PLIST}

User data is stored in:
  {USER_DATA_DIR}
""")


if __name__ == "__main__":
    main()
