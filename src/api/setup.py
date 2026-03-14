"""
FixOnce Setup API
Endpoints for setup center and system status.
"""

import subprocess
import sys
from pathlib import Path
from flask import Blueprint, jsonify

setup_bp = Blueprint('setup', __name__)


def check_mcp_connection() -> dict:
    """Check if MCP is configured and connected."""
    status = {
        "configured": False,
        "connected": False,
        "error": None
    }

    # Check if Claude Code has MCP configured
    home = Path.home()
    claude_json = home / ".claude.json"

    if claude_json.exists():
        try:
            import json
            with open(claude_json, 'r') as f:
                config = json.load(f)

            # Check for fixonce in mcpServers
            mcp_servers = config.get("mcpServers", {})
            if "fixonce" in mcp_servers:
                status["configured"] = True

            # Also check project-level configs
            projects = config.get("projects", {})
            for project_data in projects.values():
                if "fixonce" in project_data.get("mcpServers", {}):
                    status["configured"] = True
                    break

        except Exception as e:
            status["error"] = str(e)

    # Check Cursor config
    cursor_mcp = home / ".cursor" / "mcp.json"
    if cursor_mcp.exists():
        try:
            import json
            with open(cursor_mcp, 'r') as f:
                config = json.load(f)
            if "fixonce" in config.get("mcpServers", {}):
                status["configured"] = True
        except Exception:
            pass

    return status


def check_browser_extension() -> dict:
    """Check browser extension status."""
    from core.error_store import get_error_log

    status = {
        "installed": False,
        "connected": False,
        "last_ping": None
    }

    # Check if we've received any errors (means extension is connected)
    error_log = get_error_log()
    if len(error_log) > 0:
        status["installed"] = True
        status["connected"] = True

    # Check extension ping file
    data_dir = Path(__file__).parent.parent.parent / "data"
    ping_file = data_dir / "extension_ping.json"
    if ping_file.exists():
        try:
            import json
            with open(ping_file, 'r') as f:
                ping_data = json.load(f)
            status["installed"] = True
            status["connected"] = ping_data.get("connected", False)
            status["last_ping"] = ping_data.get("timestamp")
        except Exception:
            pass

    return status


def check_engine_status() -> dict:
    """Check FixOnce engine status."""
    import requests

    status = {
        "running": False,
        "port": None,
        "version": None
    }

    try:
        # Try to reach the health endpoint
        resp = requests.get("http://localhost:5000/api/health", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            status["running"] = True
            status["port"] = 5000
            status["version"] = data.get("version", "1.0")
    except Exception:
        # Try alternate ports
        for port in [5001, 5002]:
            try:
                resp = requests.get(f"http://localhost:{port}/api/health", timeout=1)
                if resp.status_code == 200:
                    status["running"] = True
                    status["port"] = port
                    break
            except Exception:
                continue

    return status


def check_project_memory() -> dict:
    """Check if project memory is loaded."""
    from core.first_launch import get_first_launch_status

    fl_status = get_first_launch_status()

    return {
        "ready": not fl_status["is_first_launch"],
        "has_active_project": fl_status["has_active_project"],
        "project_count": fl_status["project_count"]
    }


@setup_bp.route('/api/setup/status', methods=['GET'])
def get_setup_status():
    """Get comprehensive setup status for Setup Center."""
    status = {
        "engine": check_engine_status(),
        "mcp": check_mcp_connection(),
        "extension": check_browser_extension(),
        "memory": check_project_memory(),
        "overall": "incomplete"
    }

    # Determine overall status
    critical_ok = status["engine"]["running"]
    all_ok = (
        critical_ok and
        status["mcp"]["configured"] and
        status["memory"]["ready"]
    )

    if all_ok:
        status["overall"] = "ready"
    elif critical_ok:
        status["overall"] = "partial"
    else:
        status["overall"] = "incomplete"

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
    """Run a quick system check and return results."""
    checks = []

    # Check 1: Engine running
    engine = check_engine_status()
    checks.append({
        "name": "FixOnce Engine",
        "status": "ok" if engine["running"] else "error",
        "message": f"Running on port {engine['port']}" if engine["running"] else "Not running"
    })

    # Check 2: MCP configured
    mcp = check_mcp_connection()
    checks.append({
        "name": "MCP Connection",
        "status": "ok" if mcp["configured"] else "warning",
        "message": "Configured" if mcp["configured"] else "Not configured"
    })

    # Check 3: Browser extension
    ext = check_browser_extension()
    checks.append({
        "name": "Browser Extension",
        "status": "ok" if ext["connected"] else "warning",
        "message": "Connected" if ext["connected"] else "Not connected (optional)"
    })

    # Check 4: Memory ready
    mem = check_project_memory()
    checks.append({
        "name": "Project Memory",
        "status": "ok" if mem["ready"] else "warning",
        "message": f"{mem['project_count']} projects" if mem["ready"] else "No projects yet"
    })

    return jsonify({
        "checks": checks,
        "all_ok": all(c["status"] == "ok" for c in checks),
        "critical_ok": checks[0]["status"] == "ok"  # Engine is critical
    })
