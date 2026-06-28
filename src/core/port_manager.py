"""
FixOnce Port Manager

Handles dynamic port allocation for multi-user environments.
Each user gets their own port persisted in ~/.fixonce/config.json

SINGLE SOURCE OF TRUTH:
- ~/.fixonce/runtime.json contains the canonical {port, pid, started_at}
- All components (server, dashboard, MCP) must read from this file
- Server writes on startup, validates with lock
"""

import json
import socket
import os
import getpass
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from config import PROJECT_ROOT

DEFAULT_PORT = 5000
MAX_PORT = 5009
PORT_RANGE = range(DEFAULT_PORT, MAX_PORT + 1)

# Runtime file - SINGLE SOURCE OF TRUTH for port/pid
RUNTIME_FILE = Path.home() / ".fixonce" / "runtime.json"
LOCK_FILE = Path.home() / ".fixonce" / "server.lock"


def get_user_config_dir() -> Path:
    """Get the user-specific FixOnce config directory."""
    config_dir = Path.home() / ".fixonce"
    config_dir.mkdir(exist_ok=True)
    return config_dir


def get_user_config_file() -> Path:
    """Get the user-specific config file path."""
    return get_user_config_dir() / "config.json"


def load_user_config() -> Dict[str, Any]:
    """Load user-specific configuration."""
    config_file = get_user_config_file()
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_user_config(config: Dict[str, Any]) -> None:
    """Save user-specific configuration."""
    config_file = get_user_config_file()
    config_file.parent.mkdir(exist_ok=True)
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_preferred_port() -> Optional[int]:
    """Get user's preferred/last-used port from config."""
    config = load_user_config()
    port = config.get("port")
    try:
        return int(port)
    except (TypeError, ValueError):
        return None


def set_preferred_port(port: int, user_configured: bool = False) -> None:
    """
    Save port to config.

    Args:
        port: The port number
        user_configured: If True, marks this as an explicit user choice (sticky).
                        If False, just records last-used port (not sticky).
    """
    config = load_user_config()
    config["port"] = port
    config["user"] = getpass.getuser()
    if user_configured:
        config["user_configured"] = True
    elif "user_configured" in config:
        del config["user_configured"]
    save_user_config(config)


def set_user_configured_port(port: int) -> None:
    """Explicitly set a custom port that will be preferred over 5000."""
    set_preferred_port(port, user_configured=True)


def clear_stale_port_preference() -> bool:
    """
    Clear non-user-configured port preferences.

    Returns True if config was modified.
    """
    config = load_user_config()
    if config.get("user_configured"):
        return False
    if "port" in config and config.get("port") != DEFAULT_PORT:
        config.pop("port", None)
        config.pop("user_configured", None)
        save_user_config(config)
        return True
    return False


def is_port_available(port: int) -> bool:
    """Check if a port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('localhost', port))
            return True
        except OSError:
            return False


def is_port_ours(port: int) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if a port is running OUR FixOnce instance.

    Returns: (is_ours, owner_user, owner_path)
    """
    try:
        url = f"http://localhost:{port}/api/ping"
        req = urllib.request.urlopen(url, timeout=2)
        if req.status == 200:
            data = json.loads(req.read().decode())
            if data.get("service") == "fixonce":
                owner_user = data.get("user", "unknown")
                owner_path = data.get("install_path", "unknown")
                current_user = getpass.getuser()
                is_ours = owner_user == current_user
                return is_ours, owner_user, owner_path
    except (urllib.error.URLError, Exception):
        pass

    return False, None, None


def get_port_status() -> Dict[str, Any]:
    """
    Get comprehensive port status for all ports in range.

    Returns dict with:
    - available_ports: list of free ports
    - occupied_ports: list of {port, user, path, is_ours}
    - my_port: our current/preferred port (or None)
    """
    current_user = getpass.getuser()
    status = {
        "available_ports": [],
        "occupied_ports": [],
        "my_port": None,
        "user": current_user
    }

    for port in PORT_RANGE:
        if is_port_available(port):
            status["available_ports"].append(port)
        else:
            is_ours, owner, path = is_port_ours(port)
            port_info = {
                "port": port,
                "user": owner,
                "path": path,
                "is_fixonce": owner is not None,
                "is_ours": is_ours
            }
            status["occupied_ports"].append(port_info)

            if is_ours:
                status["my_port"] = port

    # If no running instance, check preferred port from config
    if status["my_port"] is None:
        preferred = get_preferred_port()
        if preferred and preferred in status["available_ports"]:
            status["my_port"] = preferred

    return status


def is_user_configured_port(port: int) -> bool:
    """Check if a port was explicitly configured by the user (not a fallback)."""
    config = load_user_config()
    return config.get("user_configured") is True and config.get("port") == port


def find_available_port(preferred: Optional[int] = None) -> int:
    """
    Find an available port.

    Priority:
    1. Default port 5000 (if available) — ALWAYS preferred
    2. User-configured port (if explicitly set and available)
    3. Next available in range (fallback, not persisted)

    Fallback ports are NOT sticky — we always try 5000 first.
    """
    # Always try default port first
    if is_port_available(DEFAULT_PORT):
        return DEFAULT_PORT

    # Try user-configured port (only if explicitly set by user, not a fallback)
    if preferred is None:
        saved_port = get_preferred_port()
        if saved_port and is_user_configured_port(saved_port):
            preferred = saved_port

    if preferred and preferred != DEFAULT_PORT and is_port_available(preferred):
        return preferred

    # Find any available (fallback - will NOT be saved as preferred)
    for port in PORT_RANGE:
        if port != DEFAULT_PORT and is_port_available(port):
            return port

    raise RuntimeError(f"No available port in range {DEFAULT_PORT}-{MAX_PORT}")


def allocate_and_save_port() -> int:
    """
    Find an available port.

    Only saves to config if using the default port (5000).
    Fallback ports are ephemeral and not persisted.

    Returns the allocated port number.
    """
    port = find_available_port()
    if port == DEFAULT_PORT:
        set_preferred_port(port)
    return port


def discover_running_instance() -> Optional[int]:
    """
    Find our running FixOnce instance.

    Returns the port number if found, None otherwise.
    """
    # First check preferred port
    preferred = get_preferred_port()
    if preferred:
        is_ours, _, _ = is_port_ours(preferred)
        if is_ours:
            return preferred

    # Scan all ports
    for port in PORT_RANGE:
        is_ours, _, _ = is_port_ours(port)
        if is_ours:
            return port

    return None


def get_dashboard_url() -> str:
    """Get the URL for this user's dashboard."""
    port = discover_running_instance()
    if port:
        return f"http://localhost:{port}"

    # Fallback to preferred or default
    preferred = get_preferred_port() or DEFAULT_PORT
    return f"http://localhost:{preferred}"


def format_port_report() -> str:
    """Generate a human-readable port status report for Doctor."""
    status = get_port_status()
    lines = []

    lines.append(f"Port Status for user: {status['user']}")
    lines.append("-" * 40)

    if status["my_port"]:
        lines.append(f"✓ Your FixOnce is on port {status['my_port']}")
    else:
        lines.append("✗ No running FixOnce instance found")

    if status["occupied_ports"]:
        lines.append("")
        lines.append("Occupied ports:")
        for p in status["occupied_ports"]:
            if p["is_fixonce"]:
                owner = p["user"] or "unknown"
                if p["is_ours"]:
                    lines.append(f"  Port {p['port']}: FixOnce (yours)")
                else:
                    lines.append(f"  Port {p['port']}: FixOnce (user: {owner})")
            else:
                lines.append(f"  Port {p['port']}: Other service")

    if status["available_ports"]:
        available = ", ".join(str(p) for p in status["available_ports"][:5])
        lines.append(f"\nAvailable ports: {available}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runtime State Management (SINGLE SOURCE OF TRUTH)
# ---------------------------------------------------------------------------

def is_pid_running(pid: int) -> bool:
    """Check if a process with given PID is running.

    Windows note: os.kill(pid, 0) can raise SystemError with WinError 6
    (invalid handle) for stale PIDs from previous boots. We treat all
    such errors as "not running".
    """
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, SystemError):
        return False


def get_runtime_state() -> Optional[Dict[str, Any]]:
    """
    Read the canonical runtime state.

    Returns:
        Dict with {port, pid, started_at} or None if no valid state
    """
    if not RUNTIME_FILE.exists():
        return None

    try:
        with open(RUNTIME_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)

        # Validate PID is still running
        pid = state.get("pid")
        if pid and is_pid_running(pid):
            return state

        # Stale state - server not running
        return None
    except (json.JSONDecodeError, IOError):
        return None


def set_runtime_state(port: int, pid: int) -> bool:
    """
    Write the canonical runtime state.

    Args:
        port: The port the server is running on
        pid: The process ID of the server

    Returns:
        True if successful, False if another server is running
    """
    RUNTIME_FILE.parent.mkdir(exist_ok=True)

    # Check if another server is already running
    existing = get_runtime_state()
    if existing and existing.get("pid") != pid:
        existing_pid = existing.get("pid")
        if is_pid_running(existing_pid):
            return False  # Another server is running

    state = {
        "port": port,
        "pid": pid,
        "started_at": datetime.now().isoformat(),
        "user": getpass.getuser(),
        "install_path": str(PROJECT_ROOT),
    }

    with open(RUNTIME_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    return True


def clear_runtime_state() -> None:
    """Clear runtime state (called on server shutdown)."""
    if RUNTIME_FILE.exists():
        try:
            RUNTIME_FILE.unlink()
        except IOError:
            pass


def get_canonical_port() -> Optional[int]:
    """
    Get the canonical port from runtime state.

    This is the SINGLE SOURCE OF TRUTH for which port to use.
    All components (dashboard, MCP, API) should use this.

    Returns:
        Port number or None if no server is running
    """
    state = get_runtime_state()
    return state.get("port") if state else None


def acquire_server_lock(pid: int) -> bool:
    """
    Acquire the server lock.

    Returns:
        True if lock acquired, False if another server holds it
    """
    LOCK_FILE.parent.mkdir(exist_ok=True)

    if LOCK_FILE.exists():
        try:
            with open(LOCK_FILE, 'r', encoding='utf-8') as f:
                existing_pid = int(f.read().strip())

            if is_pid_running(existing_pid):
                return False  # Another server has the lock
        except (ValueError, IOError):
            pass  # Stale or invalid lock file

    # Write our PID
    with open(LOCK_FILE, 'w', encoding='utf-8') as f:
        f.write(str(pid))

    return True


def release_server_lock() -> None:
    """Release the server lock (called on server shutdown)."""
    if LOCK_FILE.exists():
        try:
            LOCK_FILE.unlink()
        except IOError:
            pass


# ---------------------------------------------------------------------------
# Stale Server Cleanup
# ---------------------------------------------------------------------------

def _kill_process(pid: int) -> bool:
    """
    Kill a process by PID.

    Returns True if killed successfully or process was already dead.
    """
    import signal
    import time

    if not is_pid_running(pid):
        return True

    try:
        # First try SIGTERM (graceful)
        os.kill(pid, signal.SIGTERM)

        # Wait up to 3 seconds for graceful shutdown
        for _ in range(30):
            time.sleep(0.1)
            if not is_pid_running(pid):
                return True

        # Force kill with SIGKILL
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.2)
        return not is_pid_running(pid)

    except (OSError, ProcessLookupError, SystemError):
        return True  # Process already dead or invalid handle


def _is_fixonce_server_responding(port: int) -> bool:
    """Check if a FixOnce server is responding on the given port."""
    try:
        url = f"http://localhost:{port}/api/ping"
        req = urllib.request.urlopen(url, timeout=2)
        if req.status == 200:
            data = json.loads(req.read().decode())
            return data.get("service") == "fixonce"
    except Exception:
        pass
    return False


def _get_server_install_path(port: int) -> Optional[str]:
    """Get the install_path of a running FixOnce server."""
    try:
        url = f"http://localhost:{port}/api/ping"
        req = urllib.request.urlopen(url, timeout=2)
        if req.status == 200:
            data = json.loads(req.read().decode())
            if data.get("service") == "fixonce":
                return data.get("install_path")
    except Exception:
        pass
    return None


def cleanup_stale_runtime() -> bool:
    """
    Clean up stale runtime.json if the PID is not running.

    Returns True if cleanup was performed.
    """
    if not RUNTIME_FILE.exists():
        return False

    try:
        with open(RUNTIME_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)

        pid = state.get("pid")
        if pid and not is_pid_running(pid):
            # PID is dead, clean up
            RUNTIME_FILE.unlink()
            if LOCK_FILE.exists():
                LOCK_FILE.unlink()
            return True

    except (json.JSONDecodeError, IOError):
        # Corrupted file, clean up
        if RUNTIME_FILE.exists():
            RUNTIME_FILE.unlink()
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
        return True

    return False


def ensure_clean_startup(current_install_path: str) -> Tuple[bool, str]:
    """
    Ensure startup does not trust stale runtime files.

    This function should be called at the very beginning of server startup.
    It handles:
    1. Stale runtime.json with dead PID → cleanup
    2. Live same-install server → do not kill; caller should reuse or wait
    3. FixOnce server from different install_path → error
    4. Port occupied by non-FixOnce process → error

    Args:
        current_install_path: Path to the current FixOnce installation

    Returns:
        (success, message) - True if startup can proceed, False with error message
    """
    # Step 1: Clean up stale runtime.json
    cleanup_stale_runtime()

    # Step 2: Check if there's still a running server in runtime.json
    state = get_runtime_state()
    if state:
        old_pid = state.get("pid")
        old_port = state.get("port")
        old_install_path = state.get("install_path", "")

        if is_pid_running(old_pid):
            if old_install_path == current_install_path:
                if old_port and _is_fixonce_server_responding(old_port):
                    return False, (
                        f"FixOnce server is already running on port {old_port} "
                        f"from this install path (PID {old_pid})."
                    )

                return False, (
                    f"FixOnce server process is already starting from this install path "
                    f"(PID {old_pid}, port {old_port or 'unknown'}), but health is not ready yet. "
                    "Wait for it to become healthy instead of starting another server."
                )
            else:
                return False, (
                    f"Another FixOnce server is running from a different location:\n"
                    f"  Running: {old_install_path}\n"
                    f"  Current: {current_install_path}\n"
                    f"Please stop the other server first (PID {old_pid})."
                )

    # Step 3: Check if the default port is available
    if not is_port_available(DEFAULT_PORT):
        # Port is busy - check if it's a FixOnce server
        if _is_fixonce_server_responding(DEFAULT_PORT):
            server_path = _get_server_install_path(DEFAULT_PORT)
            if server_path == current_install_path:
                # Our server is running but runtime.json was cleaned up somehow
                # This shouldn't happen, but handle it gracefully
                return False, (
                    f"FixOnce server already running on port {DEFAULT_PORT}.\n"
                    f"If you need to restart, stop the existing server first."
                )
            else:
                return False, (
                    f"Another FixOnce server is running on port {DEFAULT_PORT}:\n"
                    f"  Install path: {server_path or 'unknown'}\n"
                    f"Please stop it first or use a different port."
                )
        else:
            return False, (
                f"Port {DEFAULT_PORT} is occupied by a non-FixOnce process. "
                "Stop that process or free the port before starting FixOnce."
            )

    return True, "Clean startup"


def get_stale_server_info() -> Optional[Dict[str, Any]]:
    """
    Get information about a potentially stale server.

    Returns dict with server info if a stale server is detected, None otherwise.
    """
    if not RUNTIME_FILE.exists():
        return None

    try:
        with open(RUNTIME_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)

        pid = state.get("pid")
        port = state.get("port")

        # Check if PID is dead
        if pid and not is_pid_running(pid):
            return {
                "status": "dead_pid",
                "pid": pid,
                "port": port,
                "install_path": state.get("install_path"),
                "started_at": state.get("started_at"),
                "message": f"Server PID {pid} is not running (stale runtime.json)",
            }

        # Check if server is responding
        if port and not _is_fixonce_server_responding(port):
            return {
                "status": "not_responding",
                "pid": pid,
                "port": port,
                "install_path": state.get("install_path"),
                "started_at": state.get("started_at"),
                "message": f"Server PID {pid} exists but not responding on port {port}",
            }

        return None

    except (json.JSONDecodeError, IOError):
        return {
            "status": "corrupted",
            "message": "runtime.json is corrupted",
        }
