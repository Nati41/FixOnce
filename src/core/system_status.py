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
import re
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
    windsurf: bool = False
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


SUPPORTED_ONBOARDING_CLIENTS = ("claude", "cursor", "codex", "windsurf")
FIXONCE_RULES_START = "<!-- FIXONCE-AUTO-INIT:START -->"
ONBOARDING_STATE_FILE = "onboarding_state.json"
ONBOARDING_VISIBLE_STATES = {
    "fresh_install",
    "detecting",
    "auto_connecting",
    "needs_restart",
    "needs_user_choice",
    "failed_actionable",
}

ONBOARDING_TRANSLATIONS = {
    "en": {
        "connected_reason": "Ready to use",
        "needs_restart_reason": "Close and reopen this app to finish connecting it.",
        "not_installed_reason": "Install this app first if you want to use FixOnce with it.",
        "failed_reason": "FixOnce could not finish this app connection yet.",
    },
    "he": {
        "connected_reason": "מוכן לשימוש",
        "needs_restart_reason": "סגור ופתח מחדש את האפליקציה כדי לסיים את החיבור.",
        "not_installed_reason": "התקן קודם את האפליקציה אם תרצה להשתמש בה עם FixOnce.",
        "failed_reason": "FixOnce עדיין לא הצליח להשלים את החיבור לאפליקציה הזו.",
    },
}


def _get_data_dir() -> Path:
    """Get the user data directory path (~/.fixonce/)."""
    from config import USER_DATA_DIR
    return USER_DATA_DIR


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
        "codex": bool(shutil.which("codex") or Path("/Applications/Codex.app").exists()),
        "claude": bool(
            shutil.which("claude")
            or Path("/Applications/Claude.app").exists()
            or Path("/Applications/Claude Code.app").exists()
        ),
        "cursor": bool(
            shutil.which("cursor")
            or Path("/Applications/Cursor.app").exists()
            or Path.home().joinpath("AppData", "Roaming", "Cursor").exists()
        ),
        "windsurf": bool(
            shutil.which("windsurf")
            or Path("/Applications/Windsurf.app").exists()
            or Path.home().joinpath("AppData", "Roaming", "Codeium", "Windsurf").exists()
        ),
    }
    return checks


def _normalize_language(language: Optional[str]) -> str:
    value = (language or "").strip().lower()
    return "he" if value.startswith("he") else "en"


def _tr(language: str, key: str) -> str:
    return ONBOARDING_TRANSLATIONS[_normalize_language(language)][key]


def _has_managed_rules(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return FIXONCE_RULES_START in path.read_text(encoding="utf-8")
    except Exception:
        return False


def _claude_hooks_valid(home: Path) -> bool:
    settings_path = home / ".claude" / "settings.json"
    if not settings_path.exists():
        return True

    try:
        config = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    hooks = config.get("hooks")
    if not hooks:
        return True

    pattern = re.compile(r'([/~][^"\']+\.(?:sh|ps1))')
    for event_hooks in hooks.values():
        if not isinstance(event_hooks, list):
            continue
        for matcher_entry in event_hooks:
            for hook in matcher_entry.get("hooks", []):
                command = str(hook.get("command", "")).strip()
                if not command:
                    continue
                matches = pattern.findall(command)
                for match in matches:
                    path = Path(match).expanduser()
                    if not path.exists():
                        return False
    return True


def _client_rules_ready(client_key: str, home: Path) -> bool:
    if client_key == "claude":
        return _has_managed_rules(home / ".claude" / "CLAUDE.md") and _claude_hooks_valid(home)
    if client_key == "cursor":
        settings_path = home / "Library" / "Application Support" / "Cursor" / "User" / "settings.json"
        if not settings_path.exists():
            settings_path = home / ".config" / "Cursor" / "User" / "settings.json"
        if not settings_path.exists():
            settings_path = home / "AppData" / "Roaming" / "Cursor" / "User" / "settings.json"
        if not settings_path.exists():
            return False
        try:
            config = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        rules = str(config.get("cursor.general.aiRules", ""))
        return "fo_init" in rules
    if client_key == "codex":
        return _has_managed_rules(home / ".codex" / "AGENTS.md")
    if client_key == "windsurf":
        return _has_managed_rules(home / ".codeium" / "windsurf" / "memories" / "global_rules.md")
    return False


def _onboarding_state_path() -> Path:
    return _get_data_dir() / ONBOARDING_STATE_FILE


def _load_onboarding_state() -> Dict[str, Any]:
    defaults = {
        "onboarding_completed": False,
        "primary_client": None,
        "should_show_onboarding": True,
    }
    path = _onboarding_state_path()
    if not path.exists():
        return defaults

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults

    state = defaults.copy()
    state.update({
        "onboarding_completed": bool(payload.get("onboarding_completed")),
        "primary_client": payload.get("primary_client"),
        "should_show_onboarding": bool(payload.get("should_show_onboarding", True)),
    })
    if state["primary_client"] not in SUPPORTED_ONBOARDING_CLIENTS:
        state["primary_client"] = None
    return state


def _save_onboarding_state(state: Dict[str, Any]) -> None:
    payload = {
        "onboarding_completed": bool(state.get("onboarding_completed")),
        "primary_client": state.get("primary_client"),
        "should_show_onboarding": bool(state.get("should_show_onboarding", True)),
    }
    _onboarding_state_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _resolve_primary_client(
    sys_status: SystemStatus,
    clients_payload: List[Dict[str, Any]],
    persisted_primary: Optional[str] = None,
) -> Optional[str]:
    for client_key in SUPPORTED_ONBOARDING_CLIENTS:
        client = sys_status.mcp.clients.get(client_key)
        if client and client.connected:
            return client_key

    for state_name in ("needs_restart", "failed"):
        match = next((item["client"] for item in clients_payload if item["status"] == state_name and item["installed"]), None)
        if match:
            return match

    match = next((item["client"] for item in clients_payload if item["installed"]), None)
    if match:
        return match

    if persisted_primary in SUPPORTED_ONBOARDING_CLIENTS:
        return persisted_primary

    return None


def _derive_onboarding_flow_state(
    sys_status: SystemStatus,
    clients_payload: List[Dict[str, Any]],
    state: Dict[str, Any],
) -> str:
    has_connected = any(sys_status.mcp.clients.get(client_key, AIClientStatus(name=client_key.title())).connected for client_key in SUPPORTED_ONBOARDING_CLIENTS)
    installed_clients = [item for item in clients_payload if item["installed"]]
    has_retryable_failure = any(item["status"] == "failed" and item["retry_available"] for item in clients_payload)
    has_needs_restart = any(item["status"] == "needs_restart" for item in clients_payload)

    if state.get("onboarding_completed") and not has_connected:
        return "completed_hidden"
    if has_connected:
        return "connected"
    if has_needs_restart:
        return "needs_restart"
    if not installed_clients:
        return "fresh_install" if sys_status.is_first_launch else "needs_user_choice"
    if sys_status.is_first_launch and has_retryable_failure:
        return "auto_connecting"
    if has_retryable_failure:
        return "failed_actionable"
    return "detecting"


def build_client_onboarding_payload(status: Optional[SystemStatus] = None, language: str = "en") -> Dict[str, Any]:
    """Map low-level client health to the first-run dashboard contract."""
    sys_status = status or get_system_status()
    home = Path.home()
    clients_payload = []

    for client_key in SUPPORTED_ONBOARDING_CLIENTS:
        client = sys_status.mcp.clients.get(client_key, AIClientStatus(name=client_key.title()))
        installed = bool(client.installed)
        config_ready = bool(client.configured)
        rules_ready = _client_rules_ready(client_key, home)
        ready = config_ready and rules_ready

        if not installed:
            state = "not_installed"
            reason = _tr(language, "not_installed_reason")
            retry_available = False
            needs_restart = False
        elif ready and client.connected:
            state = "connected"
            reason = _tr(language, "connected_reason")
            retry_available = False
            needs_restart = False
        elif ready:
            state = "needs_restart"
            reason = _tr(language, "needs_restart_reason")
            retry_available = False
            needs_restart = True
        else:
            state = "failed"
            reason = _tr(language, "failed_reason")
            retry_available = True
            needs_restart = False

        clients_payload.append({
            "client": client_key,
            "status": state,
            "reason": reason,
            "retry_available": retry_available,
            "installed": installed,
            "needs_restart": needs_restart,
        })
    onboarding_state = _load_onboarding_state()
    primary_client = _resolve_primary_client(sys_status, clients_payload, onboarding_state.get("primary_client"))
    flow_state = _derive_onboarding_flow_state(sys_status, clients_payload, onboarding_state)
    onboarding_completed = bool(onboarding_state.get("onboarding_completed"))

    if flow_state == "connected":
        onboarding_completed = True

    should_show_onboarding = flow_state in ONBOARDING_VISIBLE_STATES and not onboarding_completed
    if flow_state == "completed_hidden":
        should_show_onboarding = False

    next_state = {
        "onboarding_completed": onboarding_completed,
        "primary_client": primary_client,
        "should_show_onboarding": should_show_onboarding,
    }
    if next_state != onboarding_state:
        _save_onboarding_state(next_state)

    return {
        "clients": clients_payload,
        "flow_state": flow_state,
        "primary_client": primary_client,
        "onboarding_completed": onboarding_completed,
        "should_show_onboarding": should_show_onboarding,
    }


def get_client_onboarding_status(language: str = "en") -> Dict[str, Any]:
    """Public helper for the dashboard first-run onboarding contract."""
    return build_client_onboarding_payload(language=language)


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
    """Check MCP configuration in Codex, Claude Code, Cursor, and Windsurf."""
    status = MCPStatus()
    home = Path.home()
    runtime_clients = _load_runtime_ai_status()
    installed_clients = _detect_installed_clients()

    clients = {
        "codex": AIClientStatus(name="Codex", installed=installed_clients.get("codex", False)),
        "claude": AIClientStatus(name="Claude Code", installed=installed_clients.get("claude", False)),
        "cursor": AIClientStatus(name="Cursor", installed=installed_clients.get("cursor", False)),
        "windsurf": AIClientStatus(name="Windsurf", installed=installed_clients.get("windsurf", False)),
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
            with open(claude_json, 'r', encoding='utf-8') as f:
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
            with open(cursor_mcp, 'r', encoding='utf-8') as f:
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

    windsurf_mcp = home / ".codeium" / "windsurf" / "mcp_config.json"
    if windsurf_mcp.exists():
        try:
            with open(windsurf_mcp, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if "fixonce" in config.get("mcpServers", {}):
                clients["windsurf"].configured = True
                clients["windsurf"].config_scope = "global"
        except Exception as e:
            clients["windsurf"].error = str(e)

    status.codex = clients["codex"].configured
    status.claude_code = clients["claude"].configured
    status.cursor = clients["cursor"].configured
    status.windsurf = clients["windsurf"].configured
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
            with open(ping_file, 'r', encoding='utf-8') as f:
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
        with open(active_file, 'r', encoding='utf-8') as f:
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
                with open(project_file, 'r', encoding='utf-8') as f:
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

    # Get TRUE MCP health (not just config existence)
    try:
        from core.mcp_health import get_mcp_health_for_dashboard
        mcp_health = get_mcp_health_for_dashboard()
    except Exception as e:
        mcp_health = {"state": "unknown", "is_active": False, "error": str(e)}

    return {
        "status": status.to_dict(),
        "checks": checks,
        "overall": status.overall,
        "all_ok": status.overall == "ready",
        "critical_ok": status.engine.running,
        "timestamp": status.timestamp,
        "mcp_health": mcp_health  # TRUE MCP state
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

    with open(active_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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

    with open(active_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
