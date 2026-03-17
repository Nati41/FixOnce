"""
FixOnce Port Manager

Handles dynamic port allocation for multi-user environments.
Each user gets their own port persisted in ~/.fixonce/config.json
"""

import json
import socket
import os
import getpass
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

DEFAULT_PORT = 5000
MAX_PORT = 5009
PORT_RANGE = range(DEFAULT_PORT, MAX_PORT + 1)


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
            with open(config_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_user_config(config: Dict[str, Any]) -> None:
    """Save user-specific configuration."""
    config_file = get_user_config_file()
    config_file.parent.mkdir(exist_ok=True)
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)


def get_preferred_port() -> Optional[int]:
    """Get user's preferred/last-used port from config."""
    config = load_user_config()
    return config.get("port")


def set_preferred_port(port: int) -> None:
    """Save user's preferred port to config."""
    config = load_user_config()
    config["port"] = port
    config["user"] = getpass.getuser()
    save_user_config(config)


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


def find_available_port(preferred: Optional[int] = None) -> int:
    """
    Find an available port, preferring the user's saved port.

    Priority:
    1. User's preferred port (if available)
    2. Default port 5000 (if available)
    3. Next available in range
    """
    # Try preferred port first
    if preferred is None:
        preferred = get_preferred_port()

    if preferred and is_port_available(preferred):
        return preferred

    # Try default port
    if is_port_available(DEFAULT_PORT):
        return DEFAULT_PORT

    # Find any available
    for port in PORT_RANGE:
        if is_port_available(port):
            return port

    raise RuntimeError(f"No available port in range {DEFAULT_PORT}-{MAX_PORT}")


def allocate_and_save_port() -> int:
    """
    Find an available port and save it as the user's preference.

    Returns the allocated port number.
    """
    port = find_available_port()
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
