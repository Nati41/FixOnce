"""
FixOnce System Status - Single Source of Truth
All status checks flow through here.

This module provides unified status for:
- Engine health
- MCP configuration
- Browser extension
- Active project (or no project)
- Overall system readiness
"""

import json
import subprocess
import shutil
import requests
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


@dataclass
class EngineStatus:
    """Engine (Flask server) status."""
    running: bool = False
    port: Optional[int] = None
    version: Optional[str] = None
    error: Optional[str] = None


@dataclass
class AIClientStatus:
    """Per-AI connection status."""
    name: str
    installed: bool = False
    configured: bool = False
    connected: bool = False
    last_seen: Optional[str] = None
    config_scope: Optional[str] = None
    actor_source: Optional[str] = None
    actor_confidence: float = 0.0
    error: Optional[str] = None


@dataclass
class MCPStatus:
    """Aggregate MCP configuration status."""
    configured: bool = False
    claude_code: bool = False
    cursor: bool = False
    codex: bool = False
    clients: Dict[str, AIClientStatus] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ExtensionStatus:
    """Browser extension status."""
    installed: bool = False
    connected: bool = False
    last_seen: Optional[str] = None


@dataclass
class ProjectStatus:
    """Active project status."""
    has_project: bool = False
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    working_dir: Optional[str] = None
    project_count: int = 0


@dataclass
class SystemStatus:
    """Complete system status - single source of truth."""
    engine: EngineStatus = field(default_factory=EngineStatus)
    mcp: MCPStatus = field(default_factory=MCPStatus)
    extension: ExtensionStatus = field(default_factory=ExtensionStatus)
    project: ProjectStatus = field(default_factory=ProjectStatus)
    overall: str = "incomplete"  # incomplete, partial, ready
    is_first_launch: bool = True
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "engine": asdict(self.engine),
            "mcp": asdict(self.mcp),
            "extension": asdict(self.extension),
            "project": asdict(self.project),
            "overall": self.overall,
            "is_first_launch": self.is_first_launch,
            "timestamp": self.timestamp
        }


def _get_data_dir() -> Path:
    """Get the data directory path."""
    return Path(__file__).parent.parent.parent / "data"


def _get_project_root() -> Path:
    """Get FixOnce project root."""
    return Path(__file__).parent.parent.parent


def _mcp_runtime_file() -> Path:
    """Global runtime heartbeat file written by the MCP server."""
    return _get_data_dir() / "ai_connections.json"


def _is_recent(timestamp: Optional[str], threshold_seconds: int = 300) -> bool:
    """Return True when timestamp is recent enough to count as connected."""
    if not timestamp:
        return False
    try:
        seen = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        now = datetime.now(seen.tzinfo) if seen.tzinfo else datetime.now()
        return (now - seen).total_seconds() <= threshold_seconds
    except Exception:
        return False


def _load_runtime_ai_status() -> Dict[str, Dict[str, Any]]:
    """Load last-seen runtime data for AI clients."""
    path = _mcp_runtime_file()
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        return payload.get("clients", {})
    except Exception:
        return {}


def _detect_installed_clients() -> Dict[str, bool]:
    """Best-effort local install detection for supported AI clients."""
    home = Path.home()
    checks = {
        "codex": bool(shutil.which("codex") or (home / ".codex").exists()),
        "claude": bool(shutil.which("claude") or (home / ".claude").exists() or (home / ".claude.json").exists()),
        "cursor": bool(
            (home / ".cursor").exists()
            or Path("/Applications/Cursor.app").exists()
            or Path.home().joinpath("AppData", "Roaming", "Cursor").exists()
        ),
    }
    return checks


def _check_engine(port: int = 5000) -> EngineStatus:
    """Check if the FixOnce engine is running."""
    status = EngineStatus()

    # Try primary port first, then alternates
    ports_to_try = [port, 5000, 5001, 5002]
    seen = set()

    for p in ports_to_try:
        if p in seen:
            continue
        seen.add(p)

        try:
            resp = requests.get(f"http://localhost:{p}/api/health", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                status.running = True
                status.port = p
                status.version = data.get("version", "1.0")
                return status
        except requests.RequestException:
            continue

    status.error = "Engine not responding on any port"
    return status


def _check_mcp() -> MCPStatus:
    """Check MCP configuration in Codex, Claude Code, and Cursor."""
    status = MCPStatus()
    home = Path.home()
    runtime_clients = _load_runtime_ai_status()
    installed_clients = _detect_installed_clients()

    clients = {
        "codex": AIClientStatus(name="Codex", installed=installed_clients.get("codex", False)),
        "claude": AIClientStatus(name="Claude Code", installed=installed_clients.get("claude", False)),
        "cursor": AIClientStatus(name="Cursor", installed=installed_clients.get("cursor", False)),
    }

    for key, client in clients.items():
        runtime = runtime_clients.get(key, {})
        client.last_seen = runtime.get("last_seen")
        client.actor_source = runtime.get("actor_source")
        client.actor_confidence = float(runtime.get("actor_confidence", 0.0) or 0.0)
        client.connected = _is_recent(client.last_seen)

    # Check Codex config (~/.codex/config.toml)
    codex_config = home / ".codex" / "config.toml"
    if codex_config.exists():
        try:
            codex_text = codex_config.read_text(encoding='utf-8')
            if "[mcp_servers.fixonce]" in codex_text:
                clients["codex"].configured = True
                clients["codex"].config_scope = "global"
        except Exception as e:
            clients["codex"].error = str(e)
            status.error = str(e)

    project_root = _get_project_root()
    project_codex = project_root / ".codex" / "config.toml"
    if not clients["codex"].configured and project_codex.exists():
        try:
            codex_text = project_codex.read_text(encoding='utf-8')
            if "[mcp_servers.fixonce]" in codex_text:
                clients["codex"].configured = True
                clients["codex"].config_scope = "project"
        except Exception as e:
            clients["codex"].error = str(e)

    # Check Claude Code config (~/.claude.json)
    claude_json = home / ".claude.json"
    if claude_json.exists():
        try:
            with open(claude_json, 'r') as f:
                config = json.load(f)

            # Check global mcpServers
            mcp_servers = config.get("mcpServers", {})
            if "fixonce" in mcp_servers:
                clients["claude"].configured = True
                clients["claude"].config_scope = "global"

            # Check project-level configs
            projects = config.get("projects", {})
            for project_data in projects.values():
                if "fixonce" in project_data.get("mcpServers", {}):
                    clients["claude"].configured = True
                    clients["claude"].config_scope = "project"
                    break
        except Exception as e:
            clients["claude"].error = str(e)
            status.error = str(e)

    claude_settings = home / ".claude" / "settings.json"
    if claude_settings.exists() and not clients["claude"].configured:
        try:
            with open(claude_settings, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if "fixonce" in config.get("mcpServers", {}):
                clients["claude"].configured = True
                clients["claude"].config_scope = "global"
        except Exception as e:
            clients["claude"].error = str(e)

    # Check Cursor config (~/.cursor/mcp.json)
    cursor_mcp = home / ".cursor" / "mcp.json"
    if cursor_mcp.exists():
        try:
            with open(cursor_mcp, 'r') as f:
                config = json.load(f)
            if "fixonce" in config.get("mcpServers", {}):
                clients["cursor"].configured = True
                clients["cursor"].config_scope = "global"
        except Exception as e:
            clients["cursor"].error = str(e)

    project_mcp = project_root / ".mcp.json"
    if project_mcp.exists() and not clients["cursor"].configured:
        try:
            with open(project_mcp, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if "fixonce" in config.get("mcpServers", {}):
                clients["cursor"].configured = True
                clients["cursor"].config_scope = "project"
        except Exception as e:
            clients["cursor"].error = str(e)

    status.codex = clients["codex"].configured
    status.claude_code = clients["claude"].configured
    status.cursor = clients["cursor"].configured
    status.clients = clients
    status.configured = any(client.configured for client in clients.values())

    return status


def _check_extension() -> ExtensionStatus:
    """Check browser extension status."""
    status = ExtensionStatus()
    data_dir = _get_data_dir()

    # Check extension ping file
    ping_file = data_dir / "extension_ping.json"
    if ping_file.exists():
        try:
            with open(ping_file, 'r') as f:
                ping_data = json.load(f)
            status.installed = True
            status.connected = ping_data.get("connected", False)
            status.last_seen = ping_data.get("timestamp")
        except Exception:
            pass

    # Also check from server state if available
    try:
        from api.status import EXTENSION_CONNECTED, EXTENSION_LAST_SEEN
        if EXTENSION_CONNECTED:
            status.installed = True
            status.connected = True
            status.last_seen = EXTENSION_LAST_SEEN
    except ImportError:
        pass

    return status


def _check_project() -> ProjectStatus:
    """Check active project status.

    IMPORTANT: "No active project" is a valid first-class state.
    We do NOT fall back to the FixOnce repo or any default.
    """
    status = ProjectStatus()
    data_dir = _get_data_dir()

    # Count projects
    projects_dir = data_dir / "projects_v2"
    if projects_dir.exists():
        project_files = [
            f for f in projects_dir.glob("*.json")
            if not f.name.startswith('.') and f.name not in ('__global__.json', 'live-state.json')
        ]
        status.project_count = len(project_files)

    # Check active project
    active_file = data_dir / "active_project.json"
    if not active_file.exists():
        # No active project - this is a valid state
        return status

    try:
        with open(active_file, 'r') as f:
            data = json.load(f)

        active_id = data.get("active_id")

        # Null/empty active_id means no active project - valid state
        if not active_id:
            return status

        # We have an active project
        status.has_project = True
        status.project_id = active_id
        status.working_dir = data.get("working_dir")

        # Try to get project name from memory
        project_file = projects_dir / f"{active_id}.json"
        if project_file.exists():
            try:
                with open(project_file, 'r') as f:
                    project_data = json.load(f)
                project_info = project_data.get("project_info", {})
                status.project_name = project_info.get("name") or active_id.split("_")[0]
            except Exception:
                status.project_name = active_id.split("_")[0]
        else:
            status.project_name = active_id.split("_")[0]

    except (json.JSONDecodeError, IOError):
        # Corrupt file - treat as no project
        pass

    return status


def _is_first_launch() -> bool:
    """Check if this is first launch (no user data)."""
    data_dir = _get_data_dir()

    # Check for key files
    active_file = data_dir / "active_project.json"
    session_file = data_dir / "session_registry.json"

    if not active_file.exists() or not session_file.exists():
        return True

    return False


def get_system_status(port: int = 5000) -> SystemStatus:
    """
    Get complete system status - the single source of truth.

    This is THE function to call for status. All other status
    endpoints should use this.

    Args:
        port: Expected port for engine (default 5000)

    Returns:
        SystemStatus with all components checked
    """
    status = SystemStatus(
        engine=_check_engine(port),
        mcp=_check_mcp(),
        extension=_check_extension(),
        project=_check_project(),
        is_first_launch=_is_first_launch(),
        timestamp=datetime.now().isoformat()
    )

    # Determine overall status
    engine_ok = status.engine.running
    mcp_ok = status.mcp.configured
    has_project = status.project.has_project

    if engine_ok and mcp_ok and has_project:
        status.overall = "ready"
    elif engine_ok:
        # Engine running but missing MCP or project
        status.overall = "partial"
    else:
        status.overall = "incomplete"

    return status


def get_status_for_dashboard() -> Dict[str, Any]:
    """
    Get status formatted for dashboard display.

    Returns a dict suitable for JSON response with user-friendly messages.
    """
    status = get_system_status()

    # Build checks list for UI
    checks = []

    # Engine check
    if status.engine.running:
        checks.append({
            "name": "FixOnce Engine",
            "status": "ok",
            "message": f"Running on port {status.engine.port}"
        })
    else:
        checks.append({
            "name": "FixOnce Engine",
            "status": "error",
            "message": status.engine.error or "Not running"
        })

    # MCP check
    if status.mcp.configured:
        editors = []
        if status.mcp.claude_code:
            editors.append("Claude Code")
        if status.mcp.cursor:
            editors.append("Cursor")
        if status.mcp.codex:
            editors.append("Codex")
        checks.append({
            "name": "MCP Connection",
            "status": "ok",
            "message": f"Configured for {', '.join(editors)}"
        })
    else:
        checks.append({
            "name": "MCP Connection",
            "status": "warning",
            "message": "Not configured - run install.py"
        })

    # Extension check
    if status.extension.connected:
        checks.append({
            "name": "Browser Extension",
            "status": "ok",
            "message": "Connected"
        })
    else:
        checks.append({
            "name": "Browser Extension",
            "status": "warning",
            "message": "Not connected (optional)"
        })

    # Project check - "no project" is valid
    if status.project.has_project:
        checks.append({
            "name": "Active Project",
            "status": "ok",
            "message": status.project.project_name or status.project.project_id
        })
    else:
        checks.append({
            "name": "Active Project",
            "status": "info",
            "message": f"None ({status.project.project_count} available)"
        })

    checks.append({
        "name": "AI Connections",
        "status": "ok" if any(client.connected for client in status.mcp.clients.values()) else "warning",
        "message": ", ".join(
            f"{client.name}: {'live' if client.connected else 'idle'}"
            for client in status.mcp.clients.values()
        )
    })

    return {
        "status": status.to_dict(),
        "checks": checks,
        "overall": status.overall,
        "all_ok": status.overall == "ready",
        "critical_ok": status.engine.running,
        "timestamp": status.timestamp
    }


def clear_active_project():
    """
    Clear the active project (set to no project).

    This is the proper way to deactivate a project.
    """
    data_dir = _get_data_dir()
    active_file = data_dir / "active_project.json"

    data = {
        "active_id": None,
        "working_dir": None,
        "activated_at": None,
        "cleared_at": datetime.now().isoformat()
    }

    with open(active_file, 'w') as f:
        json.dump(data, f, indent=2)


def set_active_project(project_id: str, working_dir: Optional[str] = None):
    """
    Set the active project.

    Args:
        project_id: The project ID to activate
        working_dir: Optional working directory path
    """
    data_dir = _get_data_dir()
    active_file = data_dir / "active_project.json"

    data = {
        "active_id": project_id,
        "working_dir": working_dir,
        "activated_at": datetime.now().isoformat()
    }

    with open(active_file, 'w') as f:
        json.dump(data, f, indent=2)
