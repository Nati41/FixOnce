"""
FixOnce Setup API
Endpoints for setup center and system status.

Uses core.system_status as single source of truth.
"""

import subprocess
import sys
from pathlib import Path
from flask import Blueprint, jsonify

setup_bp = Blueprint('setup', __name__)


@setup_bp.route('/api/setup/status', methods=['GET'])
def get_setup_status():
    """Get comprehensive setup status for Setup Center.

    Uses SystemStatus as single source of truth.
    """
    from core.system_status import get_system_status

    sys_status = get_system_status()

    # Format for backward compatibility with dashboard
    status = {
        "engine": {
            "running": sys_status.engine.running,
            "port": sys_status.engine.port,
            "version": sys_status.engine.version
        },
        "mcp": {
            "configured": sys_status.mcp.configured,
            "claude_code": sys_status.mcp.claude_code,
            "cursor": sys_status.mcp.cursor,
            "connected": sys_status.mcp.configured  # backward compat
        },
        "extension": {
            "installed": sys_status.extension.installed,
            "connected": sys_status.extension.connected,
            "last_ping": sys_status.extension.last_seen
        },
        "memory": {
            "ready": not sys_status.is_first_launch,
            "has_active_project": sys_status.project.has_project,
            "project_count": sys_status.project.project_count
        },
        "project": {
            "has_project": sys_status.project.has_project,
            "project_id": sys_status.project.project_id,
            "project_name": sys_status.project.project_name,
            "working_dir": sys_status.project.working_dir
        },
        "overall": sys_status.overall,
        "is_first_launch": sys_status.is_first_launch,
        "timestamp": sys_status.timestamp
    }

    return jsonify(status)


@setup_bp.route('/api/setup/run-install', methods=['POST'])
def run_install():
    """Run the installation script."""
    try:
        install_script = Path(__file__).parent.parent.parent / "scripts" / "install.py"
        if not install_script.exists():
            return jsonify({"error": "Install script not found"}), 404

        result = subprocess.run(
            [sys.executable, str(install_script)],
            capture_output=True,
            text=True,
            timeout=120
        )

        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Installation timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@setup_bp.route('/api/setup/system-check', methods=['GET'])
def system_check():
    """Run a quick system check and return results.

    Uses get_status_for_dashboard() for consistent status.
    """
    from core.system_status import get_status_for_dashboard

    return jsonify(get_status_for_dashboard())
