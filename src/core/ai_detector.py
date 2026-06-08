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
import subprocess
import platform
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from config import USER_DATA_DIR


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
    """Run a command and return stdout, or None on failure."""
    try:
        if isinstance(cmd, str):
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=True,
            )
        else:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def _check_process_running(patterns: List[str]) -> bool:
    """Check if any process matching the patterns is running."""
    plat = _get_platform()

    for pattern in patterns:
        if plat == "windows":
            # Use tasklist on Windows
            cmd = f'tasklist /FI "IMAGENAME eq {pattern}" /NH'
            result = _run_command(cmd)
            if result and pattern.lower() in result.lower():
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
    """Check if tool is installed using platform-specific checks."""
    for check in checks:
        # Pass shell command as string
        result = _run_command(check)
        if result is not None:
            return True
    return False


def _get_connection_status(tool_id: str) -> Dict[str, Any]:
    """Get MCP connection status for a tool from ai_connections.json."""
    connections_file = USER_DATA_DIR / "ai_connections.json"

    try:
        if not connections_file.exists():
            return {"connected": False, "last_seen": None, "age_seconds": None}

        data = json.loads(connections_file.read_text(encoding="utf-8"))
        clients = data.get("clients", {})

        if tool_id not in clients:
            return {"connected": False, "last_seen": None, "age_seconds": None}

        client = clients[tool_id]
        last_seen_str = client.get("last_seen")

        if not last_seen_str:
            return {"connected": False, "last_seen": None, "age_seconds": None}

        try:
            last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
            now = datetime.now(last_seen.tzinfo) if last_seen.tzinfo else datetime.now()
            age_seconds = (now - last_seen).total_seconds()
        except (ValueError, TypeError):
            return {"connected": False, "last_seen": last_seen_str, "age_seconds": None}

        connected = age_seconds <= CONNECTED_THRESHOLD

        return {
            "connected": connected,
            "last_seen": last_seen_str,
            "age_seconds": age_seconds,
            "confidence": client.get("actor_confidence", 0),
            "source": client.get("actor_source"),
            "project_id": client.get("project_id"),
        }

    except Exception:
        return {"connected": False, "last_seen": None, "age_seconds": None}


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

        # Determine status
        # Priority: MCP connection > process detection (process detection can have false negatives)
        if connected:
            # MCP says connected - trust it, regardless of process detection
            status = "connected"
            summary["connected"] += 1
            running = True  # If connected via MCP, it must be running
        elif running:
            # Process detected but not connected to FixOnce
            status = "unprotected"
            summary["unprotected"] += 1
            unprotected_names.append(tool_config["display_name"])
        elif installed:
            # Installed but not running
            status = "not_running"
            summary["not_running"] += 1
        else:
            # Not installed
            status = "not_installed"
            summary["not_installed"] += 1

        tools.append({
            "id": tool_id,
            "name": tool_config["display_name"],
            "installed": installed,
            "running": running,
            "connected": connected,
            "status": status,
            "last_seen": connection.get("last_seen"),
            "age_seconds": connection.get("age_seconds"),
            "confidence": connection.get("confidence"),
        })
        summary["total"] += 1

    # Generate warning message
    warning = None
    if unprotected_names:
        if len(unprotected_names) == 1:
            warning = f"{unprotected_names[0]} is running without FixOnce memory"
        else:
            warning = f"{', '.join(unprotected_names)} are running without FixOnce memory"

    return {
        "tools": tools,
        "summary": summary,
        "has_unprotected": len(unprotected_names) > 0,
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
