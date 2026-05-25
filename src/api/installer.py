"""
FixOnce Installer API
Endpoints for the web-based installer.
"""

import json
import subprocess
import sys
import re
from pathlib import Path
from flask import Blueprint, jsonify, send_file, request

from config import DATA_DIR  # compatibility for tests that patch installer data dir
from core.install_state import get_install_snapshot, is_fixonce_installed, mark_install_state
from core.install_state_machine import InstallState

installer_bp = Blueprint('installer', __name__)

# FastMCP environment settings
# FASTMCP_CHECK_FOR_UPDATES accepts: 'stable', 'prerelease', 'off' (NOT 'true'/'false')
FASTMCP_ENV = {
    "FASTMCP_SHOW_CLI_BANNER": "false",
    "FASTMCP_CHECK_FOR_UPDATES": "off",
}


def _build_stdio_mcp_config(mcp_server: Path, src_path: str, fastmcp_path: str = None) -> dict:
    """Build a stdio MCP config shared by all editors."""
    if fastmcp_path:
        return {
            "command": fastmcp_path,
            "args": ["run", str(mcp_server), "--transport", "stdio", "--no-banner"],
            "env": {"PYTHONPATH": src_path, **FASTMCP_ENV}
        }

    return {
        "command": sys.executable,
        "args": [str(mcp_server)],
        "env": {"PYTHONPATH": src_path}
    }


def _toml_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _write_codex_config(path: Path, server_name: str, config: dict):
    """Write or update a Codex MCP server entry."""
    content = path.read_text(encoding='utf-8') if path.exists() else ""
    for pattern in (
        rf'(?ms)^\[mcp_servers\.{re.escape(server_name)}\]\n(?:.*\n)*?(?=^\[|\Z)',
        rf'(?ms)^\[mcp_servers\.{re.escape(server_name)}\.env\]\n(?:.*\n)*?(?=^\[|\Z)',
    ):
        content = re.sub(pattern, '', content)
    content = content.strip()

    lines = [
        f"[mcp_servers.{server_name}]",
        f"command = {_toml_quote(config['command'])}",
        f"args = [{', '.join(_toml_quote(arg) for arg in config.get('args', []))}]",
    ]

    env = config.get("env", {})
    if env:
        lines.append("")
        lines.append(f"[mcp_servers.{server_name}.env]")
        for key, value in env.items():
            lines.append(f"{key} = {_toml_quote(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((content + "\n\n" + "\n".join(lines) if content else "\n".join(lines)) + "\n", encoding='utf-8')


def _configure_json_mcp_file(path: Path, server_name: str, config: dict):
    """Write or update a JSON MCP config file."""
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}

    if not isinstance(existing, dict):
        existing = {}

    existing.setdefault("mcpServers", {})
    existing["mcpServers"][server_name] = config

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

def _is_installed() -> bool:
    """Check if FixOnce is installed."""
    request_port = request.host.split(':')[-1] if ':' in request.host else None
    try:
        request_port = int(request_port) if request_port is not None else None
    except ValueError:
        request_port = None
    return is_fixonce_installed(request_port=request_port)


def _get_request_port() -> int | None:
    request_port = request.host.split(':')[-1] if ':' in request.host else None
    try:
        return int(request_port) if request_port is not None else None
    except ValueError:
        return None


@installer_bp.route('/install')
def serve_installer():
    """Serve the installer HTML page."""
    installer_path = Path(__file__).parent.parent.parent / "data" / "installer.html"
    if installer_path.exists():
        return send_file(installer_path)
    return "Installer not found", 404


@installer_bp.route('/api/installer/status')
def installer_status():
    """Get installation status."""
    snapshot = get_install_snapshot(request_port=_get_request_port())
    return jsonify({
        "installed": snapshot.installed,
        "state": snapshot.state.value,
        "detail": snapshot.detail,
        "runtime_port": snapshot.runtime_port,
    })


@installer_bp.route('/api/installer/configure-mcp', methods=['POST'])
def configure_mcp():
    """Configure MCP for AI editors."""
    configured = []

    project_root = Path(__file__).parent.parent.parent
    mcp_server = project_root / "src" / "mcp_server" / "mcp_memory_server_v2.py"
    src_path = str(project_root / "src")

    if not mcp_server.exists():
        return jsonify({
            "status": "error",
            "configured": [],
            "error": f"MCP server not found: {mcp_server}",
        }), 500

    # Find fastmcp
    fastmcp_path = None
    try:
        result = subprocess.run(['which', 'fastmcp'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            fastmcp_path = result.stdout.strip()
    except Exception:
        pass

    stdio_config = _build_stdio_mcp_config(mcp_server, src_path, fastmcp_path)

    claude_config = Path.home() / '.claude.json'

    # Try to configure Claude Code
    try:
        subprocess.run(['claude', 'mcp', 'remove', 'fixonce', '-s', 'user'],
                      capture_output=True, timeout=10)

        mcp_json = json.dumps(stdio_config)

        result = subprocess.run(
            ['claude', 'mcp', 'add-json', 'fixonce', mcp_json, '-s', 'user'],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            configured.append("Claude Code")
    except Exception:
        pass

    try:
        _configure_json_mcp_file(claude_config, 'fixonce', stdio_config)
        if "Claude Code" not in configured:
            configured.append("Claude Code")
    except Exception:
        pass

    # Configure Cursor
    try:
        cursor_config = Path.home() / '.cursor' / 'mcp.json'
        _configure_json_mcp_file(cursor_config, 'fixonce', stdio_config)
        configured.append("Cursor")
    except Exception:
        pass

    # Configure Codex
    try:
        codex_config = Path.home() / '.codex' / 'config.toml'
        _write_codex_config(codex_config, 'fixonce', stdio_config)
        configured.append("Codex")
    except Exception:
        pass

    # Configure Windsurf
    try:
        windsurf_config = Path.home() / '.codeium' / 'windsurf' / 'mcp_config.json'
        _configure_json_mcp_file(windsurf_config, 'fixonce', stdio_config)
        configured.append("Windsurf")
    except Exception:
        pass

    return jsonify({
        "status": "ok",
        "configured": configured
    })


@installer_bp.route('/api/installer/complete', methods=['POST'])
def mark_complete():
    """Mark installation as complete."""
    snapshot = mark_install_state(InstallState.READY, detail="Installation completed from installer API")
    return jsonify({"status": "ok", "installed": True, "state": snapshot.state.value})


@installer_bp.route('/api/installer/reset', methods=['POST'])
def reset_installation():
    """Reset installation state (for testing)."""
    snapshot = mark_install_state(InstallState.NOT_INSTALLED, detail="Installation reset from installer API")
    return jsonify({"status": "ok", "installed": False, "state": snapshot.state.value})
