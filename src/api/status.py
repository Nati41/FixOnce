"""
FixOnce Status Routes
System status, health, and configuration endpoints.
"""

from flask import jsonify, request
from datetime import datetime
from pathlib import Path
import sys
import json

from . import status_bp

# Global state (will be set by main app)
EXTENSION_CONNECTED = False
EXTENSION_LAST_SEEN = None
ACTUAL_PORT = 5000


def set_extension_connected(connected: bool, last_seen: str = None):
    """Update extension connection state."""
    global EXTENSION_CONNECTED, EXTENSION_LAST_SEEN
    EXTENSION_CONNECTED = connected
    EXTENSION_LAST_SEEN = last_seen or datetime.now().isoformat()


def set_actual_port(port: int):
    """Set the actual port being used."""
    global ACTUAL_PORT
    ACTUAL_PORT = port


@status_bp.route("/handshake", methods=["POST"])
def api_handshake():
    """Called by Chrome Extension on install/startup to signal connection."""
    global EXTENSION_CONNECTED, EXTENSION_LAST_SEEN
    EXTENSION_CONNECTED = True
    EXTENSION_LAST_SEEN = datetime.now().isoformat()
    print(f"🤝 Extension handshake received at {EXTENSION_LAST_SEEN}")
    return jsonify({"status": "connected", "timestamp": EXTENSION_LAST_SEEN})


@status_bp.route("/status")
def api_status():
    """Return system health status for the dashboard wizard."""
    return jsonify({
        "extension_connected": EXTENSION_CONNECTED,
        "extension_last_seen": EXTENSION_LAST_SEEN,
        "server_running": True,
        "port": ACTUAL_PORT
    })


@status_bp.route("/ping")
def api_ping():
    """Simple endpoint for Extension to discover the server."""
    return jsonify({"status": "ok", "service": "fixonce", "port": ACTUAL_PORT})


@status_bp.route("/config")
def api_config():
    """API endpoint to get server configuration."""
    from config import PERSONAL_DB_PATH, TEAM_DB_PATH

    # Check if semantic engine is available
    try:
        from core.semantic_engine import SemanticEngine
        semantic_enabled = True
    except ImportError:
        semantic_enabled = False

    return jsonify({
        "team_db_configured": TEAM_DB_PATH is not None and TEAM_DB_PATH.exists() if TEAM_DB_PATH else False,
        "team_db_path": str(TEAM_DB_PATH) if TEAM_DB_PATH else None,
        "personal_db_path": str(PERSONAL_DB_PATH),
        "semantic_enabled": semantic_enabled,
        "version": "3.1"
    })


@status_bp.route("/system/mcp_status", methods=["GET"])
def api_mcp_status():
    """Check which AI editors are configured."""
    from pathlib import Path

    def check_editor(config_path, search_key="fixonce"):
        """Check if editor is configured."""
        try:
            path = Path(config_path).expanduser()
            if not path.exists():
                return {"installed": False, "configured": False}

            with open(path, 'r') as f:
                content = f.read()
                configured = search_key in content

            return {"installed": True, "configured": configured, "path": str(path)}
        except:
            return {"installed": False, "configured": False}

    def check_vscode():
        """Check if VS Code is installed and has MCP configured."""
        import subprocess
        try:
            result = subprocess.run(["mdfind", "kMDItemCFBundleIdentifier == 'com.microsoft.VSCode'"],
                                  capture_output=True, text=True, timeout=5)
            installed = bool(result.stdout.strip())

            continue_config = Path("~/.continue/config.json").expanduser()
            configured = False
            if continue_config.exists():
                try:
                    with open(continue_config, 'r') as f:
                        configured = "fixonce" in f.read()
                except:
                    pass

            return {"installed": installed, "configured": configured}
        except:
            return {"installed": False, "configured": False}

    return jsonify({
        "claude": check_editor("~/.claude.json"),
        "cursor": check_editor("~/.cursor/mcp.json"),
        "windsurf": check_editor("~/.windsurf/mcp.json") if Path("~/.windsurf").expanduser().exists()
                    else check_editor("~/.codeium/windsurf/mcp.json"),
        "continue": check_vscode()
    })


@status_bp.route("/system/setup_mcp", methods=["POST"])
def api_setup_mcp():
    """Configure MCP for AI editors."""
    import platform
    from pathlib import Path
    from config import SRC_DIR

    data = request.get_json(silent=True) or {}
    editor = data.get("editor", "all")

    mcp_server_path = str(SRC_DIR / "mcp_server" / "mcp_memory_server.py")
    results = {}

    def configure_editor(name, config_path, config_structure):
        """Helper to configure an editor."""
        try:
            config_path = Path(config_path).expanduser()
            config_path.parent.mkdir(parents=True, exist_ok=True)

            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
            else:
                config = {}

            for key, value in config_structure.items():
                if key not in config:
                    config[key] = value
                elif isinstance(value, dict):
                    config[key].update(value)

            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)

            return {"status": "configured", "path": str(config_path)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    mcp_config = {
        "command": sys.executable,
        "args": [mcp_server_path]
    }

    if editor in ["all", "claude"]:
        results["claude"] = configure_editor(
            "claude",
            "~/.claude.json",
            {"mcpServers": {"fixonce": mcp_config}}
        )

    if editor in ["all", "cursor"]:
        results["cursor"] = configure_editor(
            "cursor",
            "~/.cursor/mcp.json",
            {"mcpServers": {"fixonce": mcp_config}}
        )

    if editor in ["all", "windsurf"]:
        windsurf_path = "~/.windsurf/mcp.json"
        if not Path("~/.windsurf").expanduser().exists():
            windsurf_path = "~/.codeium/windsurf/mcp.json"
        results["windsurf"] = configure_editor(
            "windsurf",
            windsurf_path,
            {"mcpServers": {"fixonce": mcp_config}}
        )

    if editor in ["all", "continue"]:
        continue_config = {
            "experimental": {
                "modelContextProtocolServers": [{
                    "name": "fixonce",
                    "transport": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": [mcp_server_path]
                    }
                }]
            }
        }
        results["continue"] = configure_editor(
            "continue",
            "~/.continue/config.json",
            continue_config
        )

    return jsonify({"status": "ok", "results": results})


@status_bp.route("/setup/cursor-rules", methods=["GET"])
def api_cursor_rules():
    """Get the rules text for Cursor's 'Rules for AI' setting."""
    rules = """On any greeting (hi, hey, היי, שלום, hello):
1. Call get_project_context_tool() from FixOnce MCP
2. Call get_last_handover() from FixOnce MCP
3. Call get_avoid_patterns() from FixOnce MCP
4. Present the context in Hebrew with: project name, stack, last handover summary, and ask "מאיפה ממשיכים?"

Before fixing any error: call search_past_solutions() first.
After fixing: call update_solution_status() with keywords.
On exit (bye/סיימתי/יאללה): call create_handover() then say goodbye briefly."""
    return jsonify({"rules": rules, "instructions": "Copy this to Cursor → Settings → Rules for AI"})


@status_bp.route("/system/open_folder", methods=["POST"])
def api_open_folder():
    """Open the FixOnce folder and highlight/select the extension folder."""
    import subprocess
    import platform
    from config import PROJECT_DIR

    extension_path = PROJECT_DIR / "extension"

    if not extension_path.exists():
        return jsonify({"status": "error", "message": "Extension folder not found"}), 404

    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run([
                "osascript", "-e",
                f'tell application "Finder" to reveal POSIX file "{extension_path}"'
            ], check=True)
            subprocess.run([
                "osascript", "-e",
                'tell application "Finder" to activate'
            ], check=True)
        elif system == "Windows":
            subprocess.run(["explorer", "/select,", str(extension_path)], check=True)
        else:
            subprocess.run(["xdg-open", str(PROJECT_DIR)], check=True)

        return jsonify({"status": "ok", "path": str(extension_path)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
