"""
FixOnce Installer API
Endpoints for the web-based installer.
"""

import json
import subprocess
import sys
import re
from pathlib import Path
from datetime import datetime
from flask import Blueprint, jsonify, send_file, request

installer_bp = Blueprint('installer', __name__)


def _build_stdio_mcp_config(mcp_server: Path, src_path: str, fastmcp_path: str = None) -> dict:
    """Build a stdio MCP config shared by all editors."""
    if fastmcp_path:
        return {
            "command": fastmcp_path,
            "args": ["run", str(mcp_server), "--transport", "stdio", "--no-banner"],
            "env": {
                "PYTHONPATH": src_path,
                "FASTMCP_SHOW_CLI_BANNER": "false",
                "FASTMCP_CHECK_FOR_UPDATES": "false"
            }
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

# Installation state file
def _get_install_state_file() -> Path:
    """Get the installation state file path."""
    return Path(__file__).parent.parent.parent / "data" / "install_state.json"


def _is_installed() -> bool:
    """Check if FixOnce is installed."""
    state_file = _get_install_state_file()
    if not state_file.exists():
        return False

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
        return state.get("installed", False)
    except Exception:
        return False


def _mark_installed():
    """Mark FixOnce as installed."""
    state_file = _get_install_state_file()
    state = {
        "installed": True,
        "installed_at": datetime.now().isoformat(),
        "version": "1.0"
    }

    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


@installer_bp.route('/install')
def serve_installer():
    """Serve the installer HTML page."""
    # If already installed, redirect to dashboard
    if _is_installed():
        from flask import redirect
        return redirect('/')

    installer_path = Path(__file__).parent.parent.parent / "data" / "installer.html"
    if installer_path.exists():
        return send_file(installer_path)
    return "Installer not found", 404


@installer_bp.route('/api/installer/status')
def installer_status():
    """Get installation status."""
    return jsonify({
        "installed": _is_installed()
    })


@installer_bp.route('/api/installer/configure-mcp', methods=['POST'])
def configure_mcp():
    """Configure MCP for AI editors."""
    configured = []

    project_root = Path(__file__).parent.parent.parent
    mcp_server = project_root / "src" / "mcp_server" / "mcp_memory_server_v2.py"
    src_path = str(project_root / "src")

    # Find fastmcp
    fastmcp_path = None
    try:
        result = subprocess.run(['which', 'fastmcp'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            fastmcp_path = result.stdout.strip()
    except Exception:
        pass

    stdio_config = _build_stdio_mcp_config(mcp_server, src_path, fastmcp_path)

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

    # Configure Cursor
    try:
        cursor_config = Path.home() / '.cursor' / 'mcp.json'
        cursor_config.parent.mkdir(parents=True, exist_ok=True)

        existing = {}
        if cursor_config.exists():
            with open(cursor_config, 'r') as f:
                existing = json.load(f)

        if 'mcpServers' not in existing:
            existing['mcpServers'] = {}

        existing['mcpServers']['fixonce'] = stdio_config

        with open(cursor_config, 'w') as f:
            json.dump(existing, f, indent=2)

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

    return jsonify({
        "status": "ok",
        "configured": configured
    })


@installer_bp.route('/api/installer/complete', methods=['POST'])
def mark_complete():
    """Mark installation as complete."""
    _mark_installed()
    return jsonify({"status": "ok", "installed": True})


@installer_bp.route('/api/installer/reset', methods=['POST'])
def reset_installation():
    """Reset installation state (for testing)."""
    state_file = _get_install_state_file()
    if state_file.exists():
        state_file.unlink()
    return jsonify({"status": "ok", "installed": False})
