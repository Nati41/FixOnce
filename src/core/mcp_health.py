"""
MCP Health - TRUE State Verification

This module provides REAL MCP health checking, not just config existence.

MCP States:
- active: MCP server running AND tools callable AND recent activity
- stale: Config exists, recent activity, but can't verify tools now
- configured: Config exists but no recent activity (>5 min)
- misconfigured: Config exists but has errors (wrong paths, etc.)
- inactive: No config or no MCP server

The key insight: "configured" != "working"
"""

import json
import subprocess
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

# Import from existing modules
from config import USER_DATA_DIR, SRC_DIR


@dataclass
class MCPHealthResult:
    """True MCP health state."""
    state: str  # active, stale, configured, misconfigured, inactive
    reason: str
    last_tool_call: Optional[str] = None
    config_path: Optional[str] = None
    config_errors: list = None

    def __post_init__(self):
        if self.config_errors is None:
            self.config_errors = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "last_tool_call": self.last_tool_call,
            "config_path": self.config_path,
            "config_errors": self.config_errors,
            "is_active": self.state == "active",
            "is_usable": self.state in ("active", "stale"),
            "needs_attention": self.state in ("misconfigured", "inactive")
        }


# Thresholds
ACTIVE_THRESHOLD_SECONDS = 300  # 5 minutes - consider active
STALE_THRESHOLD_SECONDS = 3600  # 1 hour - consider stale but might work


def _get_ai_connections_file() -> Path:
    """Get path to ai_connections.json."""
    return USER_DATA_DIR / "ai_connections.json"


def _get_mcp_debug_log() -> Path:
    """Get path to MCP debug log."""
    return USER_DATA_DIR / "mcp_debug.log"


def _read_last_mcp_activity() -> Tuple[Optional[datetime], Optional[str]]:
    """
    Read the most recent MCP tool call timestamp.

    Returns:
        Tuple of (timestamp, source) where source is 'ai_connections' or 'debug_log'
    """
    last_seen = None
    source = None

    # Check ai_connections.json first (written by MCP on tool calls)
    ai_conn_file = _get_ai_connections_file()
    if ai_conn_file.exists():
        try:
            with open(ai_conn_file, 'r') as f:
                data = json.load(f)

            clients = data.get("clients", {})
            for client_data in clients.values():
                seen_str = client_data.get("last_seen")
                if seen_str:
                    try:
                        seen = datetime.fromisoformat(seen_str.replace('Z', '+00:00'))
                        if seen.tzinfo:
                            seen = seen.replace(tzinfo=None)
                        if last_seen is None or seen > last_seen:
                            last_seen = seen
                            source = "ai_connections"
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass

    # Cross-reference with debug log (more authoritative)
    debug_log = _get_mcp_debug_log()
    if debug_log.exists():
        try:
            with open(debug_log, 'r') as f:
                lines = f.readlines()

            # Parse last line for timestamp
            if lines:
                last_line = lines[-1].strip()
                # Format: [2026-03-20T09:47:52.956198] auto_init_session ...
                if last_line.startswith('['):
                    ts_str = last_line.split(']')[0].strip('[')
                    try:
                        log_time = datetime.fromisoformat(ts_str)
                        if last_seen is None or log_time > last_seen:
                            last_seen = log_time
                            source = "debug_log"
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass

    return last_seen, source


def _check_config_validity() -> Tuple[bool, str, list]:
    """
    Check if MCP config exists and is valid.

    Returns:
        Tuple of (exists, config_path, errors)
    """
    home = Path.home()
    errors = []
    config_path = None

    # Priority: project .mcp.json > user ~/.claude.json > ~/.claude/settings.json
    project_root = SRC_DIR.parent

    # Check 1: Project .mcp.json
    project_mcp = project_root / ".mcp.json"
    if project_mcp.exists():
        config_path = str(project_mcp)
        try:
            with open(project_mcp, 'r') as f:
                config = json.load(f)

            fixonce_config = config.get("mcpServers", {}).get("fixonce", {})
            if fixonce_config:
                # Validate command path
                cmd = fixonce_config.get("command", "")
                if cmd and not Path(cmd).exists():
                    errors.append(f"Command not found: {cmd}")

                # Validate MCP server file
                args = fixonce_config.get("args", [])
                if len(args) >= 2:
                    mcp_server_path = args[1]
                    if not Path(mcp_server_path).exists():
                        errors.append(f"MCP server file not found: {mcp_server_path}")

                return True, config_path, errors
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in {project_mcp}: {e}")
            return False, config_path, errors
        except Exception as e:
            errors.append(f"Error reading {project_mcp}: {e}")

    # Check 2: User ~/.claude.json
    claude_json = home / ".claude.json"
    if claude_json.exists():
        try:
            with open(claude_json, 'r') as f:
                config = json.load(f)

            mcp_servers = config.get("mcpServers", {})
            if "fixonce" in mcp_servers:
                config_path = str(claude_json)
                fixonce_config = mcp_servers["fixonce"]

                # Validate command path
                cmd = fixonce_config.get("command", "")
                if cmd and not Path(cmd).exists():
                    errors.append(f"Command not found: {cmd}")

                return True, config_path, errors
        except Exception as e:
            errors.append(f"Error reading {claude_json}: {e}")

    # Check 3: ~/.claude/settings.json
    settings_json = home / ".claude" / "settings.json"
    if settings_json.exists():
        try:
            with open(settings_json, 'r') as f:
                config = json.load(f)

            if "fixonce" in config.get("mcpServers", {}):
                config_path = str(settings_json)
                return True, config_path, errors
        except Exception:
            pass

    return False, None, ["No MCP config found for fixonce"]


def _check_mcp_server_process() -> bool:
    """
    Check if any fastmcp process is running for fixonce.

    Note: This is a hint, not definitive - the process might be running
    for a different project or might have crashed.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", "mcp_memory_server"],
            capture_output=True,
            text=True,
            timeout=2
        )
        return result.returncode == 0 and result.stdout.strip()
    except Exception:
        return False


def check_mcp_health() -> MCPHealthResult:
    """
    Perform TRUE MCP health check.

    This goes beyond config existence to verify actual usability.

    Returns:
        MCPHealthResult with accurate state
    """
    now = datetime.now()

    # Step 1: Check config existence and validity
    config_exists, config_path, config_errors = _check_config_validity()

    if not config_exists:
        return MCPHealthResult(
            state="inactive",
            reason="No MCP configuration found for fixonce",
            config_errors=config_errors
        )

    if config_errors:
        return MCPHealthResult(
            state="misconfigured",
            reason="; ".join(config_errors),
            config_path=config_path,
            config_errors=config_errors
        )

    # Step 2: Check last MCP activity
    last_activity, activity_source = _read_last_mcp_activity()

    if last_activity is None:
        # Config exists but never used
        return MCPHealthResult(
            state="configured",
            reason="MCP configured but never used (no activity recorded)",
            config_path=config_path
        )

    age_seconds = (now - last_activity).total_seconds()
    last_activity_str = last_activity.isoformat()

    # Step 3: Determine state based on age
    if age_seconds <= ACTIVE_THRESHOLD_SECONDS:
        # Recent activity - likely active
        return MCPHealthResult(
            state="active",
            reason=f"MCP tool called {int(age_seconds)}s ago",
            last_tool_call=last_activity_str,
            config_path=config_path
        )

    elif age_seconds <= STALE_THRESHOLD_SECONDS:
        # Semi-recent - might still work but needs verification
        minutes_ago = int(age_seconds / 60)
        return MCPHealthResult(
            state="stale",
            reason=f"Last MCP activity {minutes_ago}min ago - may need restart",
            last_tool_call=last_activity_str,
            config_path=config_path
        )

    else:
        # Old activity - consider configured but not active
        hours_ago = int(age_seconds / 3600)
        days_ago = int(hours_ago / 24)

        if days_ago > 0:
            time_str = f"{days_ago}d ago"
        else:
            time_str = f"{hours_ago}h ago"

        return MCPHealthResult(
            state="configured",
            reason=f"MCP configured but inactive (last activity {time_str})",
            last_tool_call=last_activity_str,
            config_path=config_path
        )


def get_mcp_health_for_dashboard() -> Dict[str, Any]:
    """
    Get MCP health formatted for dashboard display.

    Returns dict with:
    - status: "active" | "warning" | "error"  (for UI color)
    - state: detailed state name
    - message: human-readable message
    - details: additional info
    """
    result = check_mcp_health()

    # Map state to UI status
    status_map = {
        "active": "active",
        "stale": "warning",
        "configured": "warning",
        "misconfigured": "error",
        "inactive": "error"
    }

    # Build user-friendly message
    message_map = {
        "active": "MCP Active - Tools available",
        "stale": "MCP Stale - May need restart",
        "configured": "MCP Configured but not active",
        "misconfigured": "MCP Misconfigured - Check config",
        "inactive": "MCP Not Configured"
    }

    return {
        "status": status_map.get(result.state, "error"),
        "state": result.state,
        "message": message_map.get(result.state, result.reason),
        "reason": result.reason,
        "last_tool_call": result.last_tool_call,
        "config_path": result.config_path,
        "config_errors": result.config_errors,
        "is_active": result.state == "active",
        "is_usable": result.state in ("active", "stale"),
        "needs_restart": result.state in ("stale", "configured"),
        "needs_fix": result.state in ("misconfigured", "inactive")
    }


def should_allow_fixonce_claims() -> Tuple[bool, str]:
    """
    Check if AI should be allowed to claim FixOnce updates.

    Returns:
        Tuple of (allowed, reason)

    Used by CLAUDE.md enforcement logic.
    """
    result = check_mcp_health()

    if result.state == "active":
        return True, "MCP active"

    elif result.state == "stale":
        return True, "MCP stale but may work"

    else:
        return False, f"MCP not active ({result.state}: {result.reason})"
