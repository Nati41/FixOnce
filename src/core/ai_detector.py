"""
AI Tool Detection Module for FixOnce.

Detects AI coding tools and their connection status to FixOnce.

States:
- installed: Tool binary/app exists on system
- running: Process is currently active
- connected: MCP connection to FixOnce is active (within threshold)
- unprotected: Running but NOT connected to FixOnce

Supported tools: Claude Code, Codex, Cursor, Aider
"""

import json
import os
import shutil
import subprocess
import sys
import platform
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from config import USER_DATA_DIR
from core.unreported_work import get_latest_actor_state, should_show_unsynced_warning

# Windows subprocess flags to prevent console window flash
if sys.platform == "win32":
    from core.windows_subprocess import no_window_creationflags, is_process_running as win_is_process_running
else:
    def no_window_creationflags() -> int:
        return 0
    def win_is_process_running(name: str) -> bool:
        return False


# Connection freshness thresholds (seconds)
# MUST match ACTIVE_THRESHOLD_SECONDS in mcp_health.py
CONNECTED_THRESHOLD = 300  # 5 minutes - considered "connected"
STALE_THRESHOLD = 1800     # 30 minutes - connection is stale

# Import the canonical threshold to stay in sync
try:
    from core.mcp_health import ACTIVE_THRESHOLD_SECONDS
    CONNECTED_THRESHOLD = ACTIVE_THRESHOLD_SECONDS
except ImportError:
    pass

# Tool definitions
AI_TOOLS = {
    "claude": {
        "display_name": "Claude Code",
        "process_patterns": {
            "darwin": ["claude"],
            "linux": ["claude"],
            "windows": ["claude.exe"],
        },
        "install_checks": {
            "darwin": ["which claude"],
            "linux": ["which claude"],
            "windows": ["where claude"],
        },
    },
    "codex": {
        "display_name": "Codex",
        "process_patterns": {
            "darwin": ["codex"],
            "linux": ["codex"],
            "windows": ["codex.exe"],
        },
        "install_checks": {
            "darwin": ["which codex"],
            "linux": ["which codex"],
            "windows": ["where codex"],
        },
    },
    "cursor": {
        "display_name": "Cursor",
        "process_patterns": {
            "darwin": ["Cursor.app"],  # Must include .app to avoid CursorUIViewService
            "linux": ["cursor"],
            "windows": ["Cursor.exe"],
        },
        "install_checks": {
            "darwin": ["test -d /Applications/Cursor.app"],
            "linux": ["which cursor"],
            "windows": ["where cursor"],
        },
    },
    "aider": {
        "display_name": "Aider",
        "process_patterns": {
            "darwin": ["aider"],
            "linux": ["aider"],
            "windows": ["aider"],
        },
        "install_checks": {
            "darwin": ["which aider"],
            "linux": ["which aider"],
            "windows": ["where aider"],
        },
    },
}


def _get_platform() -> str:
    """Get normalized platform name."""
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    elif system == "windows":
        return "windows"
    return "linux"


def _run_command(cmd, timeout: float = 2.0) -> Optional[str]:
    """Run a command and return stdout, or None on failure.

    On Windows, uses CREATE_NO_WINDOW to prevent console flash.
    Avoids shell=True to prevent cmd.exe spawning conhost.exe.
    """
    try:
        # Convert string command to list to avoid shell=True
        if isinstance(cmd, str):
            import shlex
            if sys.platform == "win32":
                # shlex.split doesn't handle Windows paths well, use simple split
                cmd_list = cmd.split()
            else:
                cmd_list = shlex.split(cmd)
        else:
            cmd_list = cmd

        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=no_window_creationflags(),
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def _check_process_running(patterns: List[str]) -> bool:
    """Check if any process matching the patterns is running.

    On Windows, uses native WinAPI (no subprocess, no console flash).
    On Unix, uses pgrep.
    """
    plat = _get_platform()

    for pattern in patterns:
        if plat == "windows":
            # Use native Windows API - no subprocess, no console flash
            if win_is_process_running(pattern):
                return True
        else:
            # For patterns with dots/slashes, use pgrep -f (full command line match)
            if "." in pattern or "/" in pattern:
                cmd = ["pgrep", "-f", pattern]
                result = _run_command(cmd)
                if result:
                    return True
            else:
                # For simple process names, use pgrep -a (matches process name)
                cmd = ["pgrep", "-a", pattern]
                result = _run_command(cmd)
                if result:
                    return True

    return False


def _check_installed(checks: List[str]) -> bool:
    """Check if tool is installed using platform-specific checks.

    Uses shutil.which() for 'where'/'which' commands to avoid subprocess.
    """
    for check in checks:
        # Handle 'where <exe>' and 'which <exe>' with shutil.which()
        parts = check.split()
        if len(parts) == 2 and parts[0] in ("where", "which"):
            exe_name = parts[1]
            if shutil.which(exe_name):
                return True
            continue

        # Handle 'test -d <path>' for macOS app bundles
        if check.startswith("test -d "):
            path = check[8:].strip()
            if Path(path).is_dir():
                return True
            continue

        # Fallback to running the command (with CREATE_NO_WINDOW)
        result = _run_command(check)
        if result is not None:
            return True
    return False


def _get_connection_status(tool_id: str) -> Dict[str, Any]:
    """Get MCP connection status for a tool from ai_connections.json."""
    connections_file = USER_DATA_DIR / "ai_connections.json"

    try:
        if not connections_file.exists():
            return {"connected": False, "known_connection": False, "last_seen": None, "age_seconds": None}

        data = json.loads(connections_file.read_text(encoding="utf-8"))
        clients = data.get("clients", {})

        if tool_id not in clients:
            return {"connected": False, "known_connection": False, "last_seen": None, "age_seconds": None}

        client = clients[tool_id]
        last_seen_str = client.get("last_seen")

        if not last_seen_str:
            return {"connected": False, "known_connection": True, "last_seen": None, "age_seconds": None}

        try:
            last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
            now = datetime.now(last_seen.tzinfo) if last_seen.tzinfo else datetime.now()
            age_seconds = (now - last_seen).total_seconds()
        except (ValueError, TypeError):
            return {"connected": False, "known_connection": True, "last_seen": last_seen_str, "age_seconds": None}

        connected = age_seconds <= CONNECTED_THRESHOLD

        return {
            "connected": connected,
            "known_connection": True,
            "last_seen": last_seen_str,
            "age_seconds": age_seconds,
            "confidence": client.get("actor_confidence", 0),
            "source": client.get("actor_source"),
            "project_id": client.get("project_id"),
        }

    except Exception:
        return {"connected": False, "known_connection": False, "last_seen": None, "age_seconds": None}


def detect_ai_tools() -> Dict[str, Any]:
    """
    Detect all AI tools and their status.

    Returns:
        {
            "tools": [
                {
                    "id": "claude",
                    "name": "Claude Code",
                    "installed": True,
                    "running": True,
                    "connected": True,
                    "status": "connected",  # connected | unprotected | not_running | not_installed
                    "last_seen": "2026-06-08T12:00:00",
                    "age_seconds": 120,
                },
                ...
            ],
            "summary": {
                "total": 4,
                "connected": 2,
                "unprotected": 1,
                "not_running": 1,
            },
            "has_unprotected": True,
            "unprotected_warning": "Cursor is running without FixOnce memory",
        }
    """
    plat = _get_platform()
    tools = []
    summary = {
        "total": 0,
        "connected": 0,
        "unsynced_work": 0,
        "unprotected": 0,
        "not_running": 0,
        "not_installed": 0,
    }
    unprotected_names = []

    for tool_id, tool_config in AI_TOOLS.items():
        patterns = tool_config["process_patterns"].get(plat, [])
        install_checks = tool_config["install_checks"].get(plat, [])

        # Check states
        installed = _check_installed(install_checks) if install_checks else False
        running = _check_process_running(patterns) if patterns else False
        connection = _get_connection_status(tool_id)
        connected = connection.get("connected", False)
        known_connection = connection.get("known_connection", False)
        behavior_detection_enabled = tool_id in {"claude", "codex"}
        work_state = (
            get_latest_actor_state(tool_id, connection.get("project_id") or "")
            if behavior_detection_enabled
            else {}
        )
        has_significant_unsynced = should_show_unsynced_warning(work_state)

        # Determine status (behavioral states, not connection states)
        # Priority: MCP connection > process detection (process detection can have false negatives)
        if behavior_detection_enabled and has_significant_unsynced and not known_connection:
            status = "unprotected"
            summary["unprotected"] += 1
            unprotected_names.append(tool_config["display_name"])
        elif behavior_detection_enabled and has_significant_unsynced:
            status = "unsynced"
            summary["unsynced_work"] += 1
        elif connected:
            status = "protected" if behavior_detection_enabled else "connected"
            summary["connected"] += 1
            running = True  # If connected via MCP, it must be running
        elif behavior_detection_enabled and (running or installed or known_connection):
            status = "no_activity"
            summary["not_running"] += 1
        elif running:
            status = "unprotected"
            summary["unprotected"] += 1
            unprotected_names.append(tool_config["display_name"])
        elif installed:
            status = "not_running"
            summary["not_running"] += 1
        else:
            status = "not_installed"
            summary["not_installed"] += 1

        tools.append({
            "id": tool_id,
            "name": tool_config["display_name"],
            "installed": installed,
            "running": running,
            "connected": connected,
            "known_connection": known_connection,
            "status": status,
            "last_seen": connection.get("last_seen"),
            "age_seconds": connection.get("age_seconds"),
            "confidence": connection.get("confidence"),
            "work_state": work_state,
        })
        summary["total"] += 1

    # Generate warning message
    warning = None
    if unprotected_names:
        if len(unprotected_names) == 1:
            warning = f"{unprotected_names[0]} changed project files without a FixOnce connection"
        else:
            warning = f"{', '.join(unprotected_names)} changed project files without a FixOnce connection"

    return {
        "tools": tools,
        "summary": summary,
        "has_unprotected": len(unprotected_names) > 0,
        "has_unsynced_work": summary["unsynced_work"] > 0,
        "unprotected_warning": warning,
        "timestamp": datetime.now().isoformat(),
    }


def get_unprotected_tools() -> List[Dict[str, Any]]:
    """Get only the tools that are running but not connected."""
    result = detect_ai_tools()
    return [t for t in result["tools"] if t["status"] == "unprotected"]


# Cache to avoid hammering the system
_cache = {"result": None, "timestamp": None}
_CACHE_TTL = 10  # seconds


def detect_ai_tools_cached() -> Dict[str, Any]:
    """Cached version of detect_ai_tools (10 second TTL)."""
    now = datetime.now()

    if _cache["result"] and _cache["timestamp"]:
        age = (now - _cache["timestamp"]).total_seconds()
        if age < _CACHE_TTL:
            return _cache["result"]

    result = detect_ai_tools()
    _cache["result"] = result
    _cache["timestamp"] = now
    return result
