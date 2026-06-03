"""
FixOnce Installer API
Endpoints for the web-based installer.
"""

import json
import subprocess
import sys
import os
from pathlib import Path
from flask import Blueprint, Response, jsonify, request

from config import DATA_DIR, INSTALL_DATA_DIR, get_install_data_dir  # compatibility for tests that patch installer data dir
from core.mcp_config import build_stdio_mcp_config, write_codex_config, write_json_mcp_config
from core.install_state import get_install_snapshot, is_fixonce_installed, mark_install_state
from core.install_state_machine import InstallState

installer_bp = Blueprint('installer', __name__)


def _configure_json_mcp_file(path: Path, server_name: str, config: dict):
    """Write or update a JSON MCP config file."""
    write_json_mcp_config(path, server_name, config)


def _config_with_client_actor(stdio_config: dict, actor: str) -> dict:
    config = dict(stdio_config)
    env = dict(config.get("env", {}))
    env.setdefault("FIXONCE_ACTOR", actor)
    config["env"] = env
    return config

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


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _resolved_app_dir() -> Path:
    """Return the directory containing the packaged app executable."""
    return Path(sys.executable).resolve().parent


def _installer_html_candidates() -> list[Path]:
    app_dir = _resolved_app_dir()
    module_root = Path(__file__).resolve().parent.parent.parent
    meipass = getattr(sys, "_MEIPASS", None)

    candidates = [
        get_install_data_dir() / "installer.html",
        INSTALL_DATA_DIR / "installer.html",
        app_dir / "_internal" / "data" / "installer.html",
        app_dir / "data" / "installer.html",
        Path.cwd() / "_internal" / "data" / "installer.html",
        Path.cwd() / "data" / "installer.html",
        module_root / "data" / "installer.html",
    ]
    if meipass:
        candidates.insert(0, Path(meipass) / "data" / "installer.html")

    return _unique_paths(candidates)


def _installer_entrypoint_candidates() -> list[Path]:
    app_dir = _resolved_app_dir()
    names = ("install.ps1", "install.bat", "uninstall.ps1")
    return _unique_paths([app_dir / name for name in names])


def _write_installer_discovery_diagnostics(html_candidates: list[Path]):
    """Print installer discovery diagnostics for packaged Windows support."""
    app_dir = _resolved_app_dir()
    lines = [
        "FixOnce installer discovery diagnostics:",
        f"  sys.executable={sys.executable}",
        f"  __file__={__file__}",
        f"  resolved_app_directory={app_dir}",
        f"  sys.frozen={getattr(sys, 'frozen', False)}",
        f"  sys._MEIPASS={getattr(sys, '_MEIPASS', None)}",
        "  installer_html_paths_checked:",
    ]
    for path in html_candidates:
        lines.append(f"    {path} exists={os.path.exists(path)}")

    lines.append("  installer_entrypoint_paths_checked:")
    for path in _installer_entrypoint_candidates():
        lines.append(f"    {path} exists={os.path.exists(path)}")

    message = "\n".join(lines)
    try:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    except Exception:
        pass

    try:
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "installer_discovery.log").open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        pass


def _serve_installer_html(path: Path):
    """Return installer HTML without holding a Windows file handle open."""
    return Response(path.read_bytes(), mimetype="text/html")


@installer_bp.route('/install')
def serve_installer():
    """Serve the installer HTML page."""
    html_candidates = _installer_html_candidates()
    _write_installer_discovery_diagnostics(html_candidates)
    for installer_path in html_candidates:
        if os.path.exists(installer_path):
            return _serve_installer_html(installer_path)

    if html_candidates:
        installer_path = html_candidates[0]
    else:
        installer_path = Path("installer.html")
    if os.path.exists(installer_path):
        return _serve_installer_html(installer_path)
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
        "runtime_pid": snapshot.runtime_pid,
        "metadata": snapshot.metadata,
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

    stdio_config = build_stdio_mcp_config(mcp_server, src_path, fastmcp_path)
    if not fastmcp_path:
        stdio_config["command"] = sys.executable
    claude_stdio_config = _config_with_client_actor(stdio_config, "claude")
    cursor_stdio_config = _config_with_client_actor(stdio_config, "cursor")
    codex_stdio_config = _config_with_client_actor(stdio_config, "codex")
    windsurf_stdio_config = _config_with_client_actor(stdio_config, "windsurf")

    claude_config = Path.home() / '.claude.json'

    # Try to configure Claude Code
    try:
        subprocess.run(['claude', 'mcp', 'remove', 'fixonce', '-s', 'user'],
                      capture_output=True, timeout=10)

        mcp_json = json.dumps(claude_stdio_config)

        result = subprocess.run(
            ['claude', 'mcp', 'add-json', 'fixonce', mcp_json, '-s', 'user'],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            configured.append("Claude Code")
    except Exception:
        pass

    try:
        _configure_json_mcp_file(claude_config, 'fixonce', claude_stdio_config)
        if "Claude Code" not in configured:
            configured.append("Claude Code")
    except Exception:
        pass

    # Configure Cursor
    try:
        cursor_config = Path.home() / '.cursor' / 'mcp.json'
        _configure_json_mcp_file(cursor_config, 'fixonce', cursor_stdio_config)
        configured.append("Cursor")
    except Exception:
        pass

    # Configure Codex
    try:
        codex_config = Path.home() / '.codex' / 'config.toml'
        write_codex_config(codex_config, 'fixonce', codex_stdio_config)
        configured.append("Codex")
    except Exception:
        pass

    # Configure Windsurf
    try:
        windsurf_config = Path.home() / '.codeium' / 'windsurf' / 'mcp_config.json'
        _configure_json_mcp_file(windsurf_config, 'fixonce', windsurf_stdio_config)
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


@installer_bp.route('/api/installer/extension-status')
def installer_extension_status():
    """Return the same extension status source used by dashboard/status APIs."""
    try:
        from api.status import _get_extension_status_payload
        extension = _get_extension_status_payload()
    except Exception:
        extension = {"connected": False, "last_seen": None, "source": "unknown"}

    if extension.get("connected"):
        try:
            mark_install_state(InstallState.READY, detail="Extension handshake completed")
        except Exception:
            pass

    return jsonify({
        "status": "ok",
        "extension": extension,
        "installed": bool(extension.get("connected")),
    })


@installer_bp.route('/api/installer/open-chrome-extensions', methods=['POST'])
def open_chrome_extensions():
    """Open Chrome extensions page from installer UI."""
    try:
        subprocess.run(
            ['open', '-a', 'Google Chrome', 'chrome://extensions/'],
            capture_output=True,
            timeout=5,
        )
        return jsonify({"status": "ok"})
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500


@installer_bp.route('/api/installer/open-extension-folder', methods=['POST'])
def open_extension_folder():
    """Open the installed extension folder from installer UI."""
    extension_dir = Path.home() / "FixOnce" / "extension"
    if not extension_dir.exists():
        return jsonify({
            "status": "error",
            "error": f"Extension folder not found: {extension_dir}",
        }), 404

    try:
        subprocess.run(['open', str(extension_dir)], capture_output=True, timeout=5)
        return jsonify({"status": "ok", "path": str(extension_dir)})
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500


@installer_bp.route('/api/installer/reset', methods=['POST'])
def reset_installation():
    """Reset installation state (for testing)."""
    snapshot = mark_install_state(InstallState.NOT_INSTALLED, detail="Installation reset from installer API")
    return jsonify({"status": "ok", "installed": False, "state": snapshot.state.value})
