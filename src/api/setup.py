"""
FixOnce Setup API
Endpoints for setup center and system status.

Uses core.system_status as single source of truth.
"""

import subprocess
import sys
import json
from dataclasses import asdict
from pathlib import Path
from flask import Blueprint, jsonify, request

setup_bp = Blueprint('setup', __name__)


def _get_request_language() -> str:
    language = (request.headers.get("Accept-Language") or "").lower()
    return "he" if language.startswith("he") else "en"


def _load_install_module():
    scripts_dir = Path(__file__).parent.parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import install
    return install


@setup_bp.route('/api/setup/status', methods=['GET'])
def get_setup_status():
    """Get comprehensive setup status for Setup Center.

    Uses SystemStatus as single source of truth.
    """
    from core.system_status import get_system_status, build_client_onboarding_payload

    sys_status = get_system_status()
    onboarding = build_client_onboarding_payload(sys_status, _get_request_language())

    # Format for backward compatibility with dashboard
    status = {
        "engine": {
            "running": sys_status.engine.running,
            "port": sys_status.engine.port,
            "version": sys_status.engine.version
        },
        "mcp": {
            "configured": sys_status.mcp.configured,
            "codex": sys_status.mcp.codex,
            "claude_code": sys_status.mcp.claude_code,
            "cursor": sys_status.mcp.cursor,
            "clients": {name: asdict(client) for name, client in sys_status.mcp.clients.items()},
            "connected": any(client.connected for client in sys_status.mcp.clients.values())  # backward compat
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
        "client_onboarding": onboarding,
        "overall": sys_status.overall,
        "is_first_launch": sys_status.is_first_launch,
        "timestamp": sys_status.timestamp
    }

    return jsonify(status)


@setup_bp.route('/api/setup/client-onboarding', methods=['GET'])
def get_client_onboarding():
    """Return the product-facing first-run client onboarding contract."""
    from core.system_status import get_client_onboarding_status

    return jsonify(get_client_onboarding_status(_get_request_language()))


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


@setup_bp.route('/api/setup/test-ai/<client>', methods=['POST'])
def test_ai_connection(client: str):
    """Run a smoke test for a specific AI MCP client."""
    client = (client or "").strip().lower()
    if client not in {"codex", "claude", "cursor"}:
        return jsonify({"error": f"Unsupported AI client: {client}"}), 400

    try:
        smoke_script = Path(__file__).parent.parent.parent / "scripts" / "mcp_smoke_test.py"
        result = subprocess.run(
            [sys.executable, str(smoke_script), "--client", client],
            capture_output=True,
            text=True,
            timeout=20
        )

        output = result.stdout.strip() or "{}"
        payload = json.loads(output)
        payload["success"] = bool(payload.get("ok"))
        return jsonify(payload), (200 if payload["success"] else 422)
    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "client": client,
            "code": "timeout",
            "doctor": {
                "title": "Smoke test timed out",
                "summary": "The MCP process did not respond in time.",
                "steps": [
                    "Check that the configured Python/FastMCP environment still exists.",
                    "Re-run `python3 scripts/install.py` from the FixOnce project."
                ]
            }
        }), 504
    except Exception as e:
        return jsonify({
            "success": False,
            "client": client,
            "code": "internal_error",
            "doctor": {
                "title": "Dashboard test failed",
                "summary": str(e),
                "steps": [
                    "Check FixOnce server logs.",
                    "Retry after restarting FixOnce."
                ]
            }
        }), 500


@setup_bp.route('/api/setup/retry-ai/<client>', methods=['POST'])
def retry_ai_connection(client: str):
    """Retry onboarding for a single client without reinstalling core FixOnce."""
    client = (client or "").strip().lower()
    if client not in {"claude", "cursor", "codex", "windsurf"}:
        return jsonify({"error": f"Unsupported AI client: {client}"}), 400

    install = _load_install_module()

    try:
        fixonce_dir = install.get_fixonce_dir()
        editors = install.detect_editors()
        stdio_config = install.build_install_stdio_config(fixonce_dir)

        config_ok = install.configure_client_mcp(client, stdio_config=stdio_config, editors=editors)
        rules_ok = install.sync_client_rules(client, fixonce_dir=fixonce_dir)

        from core.system_status import get_client_onboarding_status
        payload = get_client_onboarding_status(_get_request_language())
        client_payload = next((item for item in payload["clients"] if item["client"] == client), None)

        return jsonify({
            "success": bool(config_ok and rules_ok),
            "client": client_payload,
            "clients": payload["clients"],
        }), (200 if config_ok and rules_ok else 422)
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


@setup_bp.route('/api/setup/repair-mcp', methods=['POST'])
def repair_mcp_connection():
    """Repair local MCP setup and report honest client-session limitations."""
    from core.mcp_health import get_mcp_health_for_dashboard
    from core.mcp_session_health import mark_recovery_attempt, record_mcp_success

    actor = None
    try:
        payload = request.get_json(silent=True) or {}
        actor = (payload.get("client") or payload.get("actor") or "").strip().lower() or None
    except Exception:
        actor = None

    mark_recovery_attempt(actor=actor, source="dashboard")

    checks = {
        "server_running": True,
        "config_checked": False,
        "config_repaired": False,
        "rules_synced": False,
        "stale_process_cleanup": "skipped_client_owned_transport",
    }

    try:
        install = _load_install_module()
        fixonce_dir = install.get_fixonce_dir()
        stdio_config = install.build_install_stdio_config(fixonce_dir, probe_fastmcp=False)
        # Dashboard reconnect runs inside the packaged GUI on Windows. Avoid
        # external editor probes/CLI commands here because short-lived console
        # subprocesses can flash a window. The repair action only needs to
        # rewrite known config/rules files.
        editors = {
            "claude_code": False,
            "cursor": False,
            "codex": False,
            "windsurf": False,
        }

        targets = [actor] if actor in {"claude", "cursor", "codex", "windsurf"} else ["claude", "cursor", "codex", "windsurf"]
        config_results = []
        rules_results = []
        for client in targets:
            config_results.append(bool(install.configure_client_mcp(client, stdio_config=stdio_config, editors=editors)))
            rules_results.append(bool(install.sync_client_rules(client, fixonce_dir=fixonce_dir)))

        checks["config_checked"] = True
        checks["config_repaired"] = all(config_results) if config_results else False
        checks["rules_synced"] = all(rules_results) if rules_results else False
    except Exception as e:
        checks["config_error"] = str(e)

    health = get_mcp_health_for_dashboard()
    if health.get("state") in {"active", "stale"} and health.get("session", {}).get("state") != "session_lost":
        record_mcp_success(tool_name="repair_mcp", actor_identity={"editor": actor or "unknown", "source": "dashboard"})

    return jsonify({
        "success": True,
        "checks": checks,
        "mcp_health": get_mcp_health_for_dashboard(),
        "message": (
            "Repair completed. If this chat still cannot use FixOnce tools, "
            "open a new AI chat or reconnect the MCP server in your client."
        ),
    })


@setup_bp.route('/api/setup/open-app/<client>', methods=['POST'])
def open_app(client: str):
    """Best-effort open action for supported desktop apps."""
    client = (client or "").strip().lower()
    app_map = {
        "claude": ["Claude", "Claude Code"],
        "cursor": ["Cursor"],
        "windsurf": ["Windsurf"],
        "codex": ["Codex"],
    }
    if client not in app_map:
        return jsonify({"success": False, "error": f"Unsupported AI client: {client}"}), 400

    for app_name in app_map[client]:
        try:
            result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return jsonify({"success": True})
        except Exception:
            continue

    return jsonify({"success": False, "error": "Could not open app"}), 422


@setup_bp.route('/api/setup/system-check', methods=['GET'])
def system_check():
    """Run a quick system check and return results.

    Uses get_status_for_dashboard() for consistent status.
    """
    from core.system_status import get_status_for_dashboard

    return jsonify(get_status_for_dashboard())
