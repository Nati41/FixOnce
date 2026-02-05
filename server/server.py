import json
import socket
import sqlite3
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Desktop Notifications
# ---------------------------------------------------------------------------
def send_desktop_notification(title: str, message: str, sound: bool = False):
    """Send a macOS desktop notification."""
    try:
        # Escape quotes for AppleScript
        title = title.replace('"', '\\"')
        message = message.replace('"', '\\"')

        script = f'display notification "{message}" with title "{title}"'
        if sound:
            script += ' sound name "Basso"'

        subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            timeout=2
        )
    except Exception:
        pass  # Silent fail - notifications are optional

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from fastmcp import FastMCP

# V2: Semantic Search Engine
try:
    from semantic_engine import SemanticEngine, get_engine, reset_engine
    SEMANTIC_ENABLED = True
    print("🧠 Semantic Engine V2 loaded successfully")
except ImportError as e:
    SEMANTIC_ENABLED = False
    print(f"⚠️ Semantic Engine not available: {e}")
    print("   Falling back to exact/LIKE matching")


def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def find_available_port(start_port: int = 5000, max_attempts: int = 10) -> int:
    """Find an available port starting from start_port."""
    for i in range(max_attempts):
        port = start_port + i
        if not is_port_in_use(port):
            return port
    raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_attempts - 1}")


# Global variable to store the actual port being used
ACTUAL_PORT = 5000

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PERSONAL_DB_PATH = Path(__file__).parent / "personal_solutions.db"
TEAM_DB_PATH: Path | None = None  # Set to a shared path for team DB, e.g.: Path("/shared/team_solutions.db")

# ---------------------------------------------------------------------------
# Shared in-memory store – last 50 errors
# ---------------------------------------------------------------------------
error_log: deque[dict] = deque(maxlen=50)
log_lock = threading.Lock()

# ---------------------------------------------------------------------------
# SQLite Database – Hybrid "Learning System" (Personal + Team)
# ---------------------------------------------------------------------------

def init_db(db_path: Path, db_name: str = "Database"):
    """Initialize a SQLite database and create the solutions table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_message TEXT NOT NULL,
            solution_text TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    print(f"📚 {db_name} initialized at {db_path}")


def find_similar_solution(error_message: str, db_path: Path) -> dict | None:
    """
    Search for a similar error in a specific database.
    V2: Uses semantic similarity if available, falls back to LIKE matching.
    """
    if not db_path or not db_path.exists():
        return None

    # V2: Try semantic search first
    if SEMANTIC_ENABLED:
        try:
            engine = get_engine(db_path)
            match = engine.find_similar(error_message)

            if match:
                solution_id, similarity_score, matched_clean = match
                solution = engine.get_solution_by_id(solution_id)

                if solution:
                    # Increment success count
                    engine.increment_success_count(solution_id)

                    return {
                        "matched_error": solution["error_message"],
                        "solution": solution["solution_text"],
                        "saved_at": solution["timestamp"],
                        "similarity_score": similarity_score,
                        "match_type": "semantic",
                        "success_count": solution["success_count"] + 1
                    }
        except Exception as e:
            print(f"[SemanticEngine] Error: {e}, falling back to LIKE matching")

    # Fallback: Traditional LIKE matching
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # First try exact match
    cursor.execute(
        "SELECT error_message, solution_text, timestamp FROM solutions WHERE error_message = ? ORDER BY timestamp DESC LIMIT 1",
        (error_message,)
    )
    result = cursor.fetchone()

    if not result:
        # Try partial match - search for key parts of the error
        search_key = error_message[:100] if len(error_message) > 100 else error_message
        cursor.execute(
            "SELECT error_message, solution_text, timestamp FROM solutions WHERE error_message LIKE ? ORDER BY timestamp DESC LIMIT 1",
            (f"%{search_key}%",)
        )
        result = cursor.fetchone()

    conn.close()

    if result:
        return {
            "matched_error": result[0],
            "solution": result[1],
            "saved_at": result[2],
            "match_type": "exact" if error_message == result[0] else "partial"
        }
    return None


def find_solution_hybrid(error_message: str) -> dict | None:
    """
    Search for a solution in both personal and team databases.
    Returns the solution with its source.
    V2: Uses semantic similarity for smarter matching.
    """
    # Check personal DB first (priority)
    personal_result = find_similar_solution(error_message, PERSONAL_DB_PATH)
    if personal_result:
        personal_result["source"] = "personal"
        return personal_result

    # Check team DB if configured
    if TEAM_DB_PATH and TEAM_DB_PATH.exists():
        team_result = find_similar_solution(error_message, TEAM_DB_PATH)
        if team_result:
            team_result["source"] = "team"
            return team_result

    return None


def get_all_solutions(db_path: Path) -> list[dict]:
    """Get all solutions from a specific database."""
    if not db_path or not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, error_message, solution_text, timestamp FROM solutions ORDER BY timestamp DESC"
    )
    results = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "error_message": row[1],
            "solution_text": row[2],
            "timestamp": row[3]
        }
        for row in results
    ]


# Initialize databases on module load
init_db(PERSONAL_DB_PATH, "Personal DB")
if TEAM_DB_PATH:
    init_db(TEAM_DB_PATH, "Team DB")

# ---------------------------------------------------------------------------
# Flask – receives POST /log from the browser snippet + Dashboard API
# ---------------------------------------------------------------------------
flask_app = Flask(__name__)
CORS(flask_app)


@flask_app.route("/log", methods=["POST"])
def receive_log():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    entry = {
        "type": data.get("type", "unknown"),
        "message": data.get("message", ""),
        "url": data.get("url", ""),
        "source": data.get("source", ""),
        "line": data.get("line", ""),
        "column": data.get("column", ""),
        "stack": data.get("stack", ""),
        "timestamp": data.get("timestamp", datetime.now().isoformat()),
    }

    with log_lock:
        error_log.append(entry)

    print(
        f"\n🔥 [{entry['type']}] {entry['timestamp']}\n"
        f"   URL:     {entry['url']}\n"
        f"   Message: {entry['message']}"
    )

    return jsonify({"status": "ok"})


@flask_app.route("/")
def dashboard():
    """Serve the dashboard HTML page."""
    # Use brain_dashboard as the main dashboard
    dashboard_path = Path(__file__).parent / "brain_dashboard.html"
    return send_file(dashboard_path)


@flask_app.route("/diary")
def smart_diary():
    """V3.1: Serve the Smart Diary page."""
    diary_path = Path(__file__).parent / "templates" / "smart_diary.html"
    return send_file(diary_path)


@flask_app.route("/brain")
def brain_dashboard():
    """V4: Serve the Brain Dashboard (AI Memory sidebar)."""
    brain_path = Path(__file__).parent / "brain_dashboard.html"
    return send_file(brain_path)


@flask_app.route("/v2")
def brain_dashboard_v2():
    """V2: Clean, minimal dashboard."""
    v2_path = Path(__file__).parent / "dashboard_v2.html"
    return send_file(v2_path)


@flask_app.route("/test")
def test_site():
    """Serve the comprehensive test site."""
    test_path = Path(__file__).parent.parent / "test-site" / "index.html"
    return send_file(test_path)


@flask_app.route("/api/solutions/<scope>")
def api_get_solutions(scope: str):
    """API endpoint to get solutions by scope."""
    if scope == "personal":
        solutions = get_all_solutions(PERSONAL_DB_PATH)
    elif scope == "team":
        if TEAM_DB_PATH:
            solutions = get_all_solutions(TEAM_DB_PATH)
        else:
            return jsonify({"error": "Team DB not configured", "solutions": []}), 200
    else:
        return jsonify({"error": "Invalid scope"}), 400

    return jsonify({"solutions": solutions, "scope": scope})


@flask_app.route("/api/solutions/<scope>/<int:solution_id>", methods=["DELETE"])
def api_delete_solution(scope: str, solution_id: int):
    """API endpoint to delete a solution."""
    if scope == "personal":
        db_path = PERSONAL_DB_PATH
    elif scope == "team":
        if not TEAM_DB_PATH:
            return jsonify({"error": "Team DB not configured"}), 400
        db_path = TEAM_DB_PATH
    else:
        return jsonify({"error": "Invalid scope"}), 400

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM solutions WHERE id = ?", (solution_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()

    if deleted:
        return jsonify({"status": "ok", "message": f"Solution {solution_id} deleted"})
    return jsonify({"error": "Solution not found"}), 404


@flask_app.route("/api/config")
def api_config():
    """API endpoint to get server configuration."""
    return jsonify({
        "team_db_configured": TEAM_DB_PATH is not None and TEAM_DB_PATH.exists(),
        "team_db_path": str(TEAM_DB_PATH) if TEAM_DB_PATH else None,
        "personal_db_path": str(PERSONAL_DB_PATH),
        "semantic_enabled": SEMANTIC_ENABLED,
        "version": "2.0" if SEMANTIC_ENABLED else "1.0"
    })


# ---------------------------------------------------------------------------
# Handshake Protocol - Extension Connection State
# ---------------------------------------------------------------------------
EXTENSION_CONNECTED = False
EXTENSION_LAST_SEEN = None

# ---------------------------------------------------------------------------
# Current Site Tracking - What the user is working on
# ---------------------------------------------------------------------------
CURRENT_SITE = None
CURRENT_SITE_LOCK = threading.Lock()


@flask_app.route("/api/handshake", methods=["POST"])
def api_handshake():
    """Called by Chrome Extension on install/startup to signal connection."""
    global EXTENSION_CONNECTED, EXTENSION_LAST_SEEN
    EXTENSION_CONNECTED = True
    EXTENSION_LAST_SEEN = datetime.now().isoformat()
    print(f"🤝 Extension handshake received at {EXTENSION_LAST_SEEN}")
    return jsonify({"status": "connected", "timestamp": EXTENSION_LAST_SEEN})


@flask_app.route("/api/status")
def api_status():
    """Return system health status for the dashboard wizard."""
    return jsonify({
        "extension_connected": EXTENSION_CONNECTED,
        "extension_last_seen": EXTENSION_LAST_SEEN,
        "server_running": True,
        "port": ACTUAL_PORT
    })


@flask_app.route("/api/ping")
def api_ping():
    """Simple endpoint for Extension to discover the server."""
    return jsonify({"status": "ok", "service": "fixonce", "port": ACTUAL_PORT})


@flask_app.route("/api/current-site", methods=["POST"])
def api_current_site_update():
    """Receive current site from extension."""
    global CURRENT_SITE
    data = request.get_json(silent=True)
    if data:
        with CURRENT_SITE_LOCK:
            CURRENT_SITE = {
                "url": data.get("url", ""),
                "domain": data.get("domain", ""),
                "title": data.get("title", ""),
                "timestamp": data.get("timestamp", datetime.now().isoformat())
            }
        print(f"[CurrentSite] Updated: {CURRENT_SITE['domain']}")
    return jsonify({"status": "ok"})


@flask_app.route("/api/current-site", methods=["GET"])
def api_current_site_get():
    """Get the current site the user is working on."""
    with CURRENT_SITE_LOCK:
        if CURRENT_SITE:
            return jsonify(CURRENT_SITE)
    return jsonify({"url": None, "domain": None, "message": "No active dev site detected"})


@flask_app.route("/api/server/connect", methods=["POST"])
def api_server_connect():
    """Connect to user's server for monitoring.
    This enables HTTP error tracking for the specified server.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    target_url = data.get("url", "")
    target_port = data.get("port", "")

    if not target_url and not target_port:
        return jsonify({"status": "error", "message": "URL or port required"}), 400

    # Extract port from URL if not provided
    if target_url and not target_port:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(target_url)
            target_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        except:
            pass

    # Store the connected server info
    try:
        from project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        memory["connected_server"] = {
            "url": target_url,
            "port": target_port,
            "connected_at": datetime.now().isoformat(),
            "status": "active"
        }
        save_memory(memory)

        print(f"[ServerConnect] Connected to {target_url or f'localhost:{target_port}'}")
        return jsonify({
            "status": "ok",
            "message": f"Connected to server on port {target_port}",
            "monitoring": "HTTP errors will be captured automatically via browser extension"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/server/status", methods=["GET"])
def api_server_status():
    """Get connected server status."""
    try:
        from project_memory_manager import get_project_context
        memory = get_project_context()
        server = memory.get("connected_server", {})
        return jsonify({
            "connected": bool(server.get("status") == "active"),
            "server": server
        })
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})


@flask_app.route("/api/system/setup_mcp", methods=["POST"])
def api_setup_mcp():
    """Configure MCP for AI editors."""
    import platform
    import json
    from pathlib import Path

    data = request.get_json(silent=True) or {}
    editor = data.get("editor", "all")  # all, claude, cursor, windsurf, continue

    mcp_server_path = str(Path(__file__).parent / "mcp_memory_server.py")
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

            # Merge the new config
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

    # Claude Code
    if editor in ["all", "claude"]:
        results["claude"] = configure_editor(
            "claude",
            "~/.claude.json",
            {"mcpServers": {"fixonce": mcp_config}}
        )

    # Cursor
    if editor in ["all", "cursor"]:
        results["cursor"] = configure_editor(
            "cursor",
            "~/.cursor/mcp.json",
            {"mcpServers": {"fixonce": mcp_config}}
        )

    # Windsurf
    if editor in ["all", "windsurf"]:
        windsurf_path = "~/.windsurf/mcp.json"
        if not Path("~/.windsurf").expanduser().exists():
            windsurf_path = "~/.codeium/windsurf/mcp.json"
        results["windsurf"] = configure_editor(
            "windsurf",
            windsurf_path,
            {"mcpServers": {"fixonce": mcp_config}}
        )

    # Continue (VS Code)
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


@flask_app.route("/api/system/mcp_status", methods=["GET"])
def api_mcp_status():
    """Check which AI editors are configured."""
    import json
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

    return jsonify({
        "claude": check_editor("~/.claude.json"),
        "cursor": check_editor("~/.cursor/mcp.json"),
        "windsurf": check_editor("~/.windsurf/mcp.json") if Path("~/.windsurf").expanduser().exists()
                    else check_editor("~/.codeium/windsurf/mcp.json"),
        "continue": check_vscode()
    })

def check_vscode():
    """Check if VS Code is installed and has MCP configured."""
    import subprocess
    try:
        # Check if VS Code is installed
        result = subprocess.run(["mdfind", "kMDItemCFBundleIdentifier == 'com.microsoft.VSCode'"],
                              capture_output=True, text=True, timeout=5)
        installed = bool(result.stdout.strip())

        # Check if Continue extension has FixOnce configured
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


# ========== AI SESSION ENDPOINTS ==========

@flask_app.route("/api/session/start", methods=["POST"])
def api_session_start():
    """Start an AI session - sets a flag that the MCP will read."""
    from datetime import datetime
    from project_memory_manager import get_project_context, save_memory

    data = request.get_json(silent=True) or {}
    editor = data.get("editor", "unknown")

    memory = get_project_context()
    memory["ai_session"] = {
        "active": True,
        "editor": editor,
        "started_at": datetime.now().isoformat(),
        "briefing_sent": False
    }
    save_memory(memory)

    return jsonify({"status": "ok", "message": "Session started"})


@flask_app.route("/api/session/launch", methods=["POST"])
def api_session_launch():
    """Launch an AI editor."""
    import subprocess
    import platform

    data = request.get_json(silent=True) or {}
    editor = data.get("editor", "claude")

    try:
        if platform.system() == "Darwin":  # macOS
            if editor == "claude":
                # Open Terminal and run claude
                script = '''
                tell application "Terminal"
                    activate
                    do script "cd ~ && claude"
                end tell
                '''
                subprocess.run(["osascript", "-e", script], check=True)
            elif editor == "cursor":
                subprocess.run(["open", "-a", "Cursor"], check=True)
            elif editor == "windsurf":
                subprocess.run(["open", "-a", "Windsurf"], check=True)
            elif editor == "vscode" or editor == "continue":
                subprocess.run(["open", "-a", "Visual Studio Code"], check=True)
            else:
                return jsonify({"status": "error", "message": f"Unknown editor: {editor}"}), 400
        else:
            return jsonify({"status": "error", "message": "Only macOS supported for launch"}), 400

        return jsonify({"status": "ok", "message": f"Launched {editor}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/session/status", methods=["GET"])
def api_session_status():
    """Get current session status."""
    from project_memory_manager import get_project_context

    memory = get_project_context()
    session = memory.get("ai_session", {})

    return jsonify({
        "active": session.get("active", False),
        "editor": session.get("editor"),
        "started_at": session.get("started_at"),
        "briefing_sent": session.get("briefing_sent", False)
    })


@flask_app.route("/api/system/open_folder", methods=["POST"])
def api_open_folder():
    """Open the FixOnce folder and highlight/select the extension folder."""
    import subprocess
    import platform

    # Get paths
    fixonce_path = Path(__file__).parent.parent
    extension_path = fixonce_path / "extension"

    if not extension_path.exists():
        return jsonify({"status": "error", "message": "Extension folder not found"}), 404

    try:
        system = platform.system()
        if system == "Darwin":  # macOS - open Finder and select the extension folder
            subprocess.run([
                "osascript", "-e",
                f'tell application "Finder" to reveal POSIX file "{extension_path}"'
            ], check=True)
            subprocess.run([
                "osascript", "-e",
                'tell application "Finder" to activate'
            ], check=True)
        elif system == "Windows":
            # Windows - open explorer and select the folder
            subprocess.run(["explorer", "/select,", str(extension_path)], check=True)
        else:  # Linux
            subprocess.run(["xdg-open", str(fixonce_path)], check=True)

        return jsonify({"status": "ok", "path": str(extension_path)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/live-errors")
def api_live_errors():
    """API endpoint to get live errors with matched solutions."""
    with log_lock:
        errors = list(error_log)

    # Enrich each error with previous solution if available
    for error in errors:
        error_msg = error.get("message", "")
        if error_msg:
            previous = find_solution_hybrid(error_msg)
            if previous:
                error["previous_solution"] = previous

    return jsonify({"errors": errors, "count": len(errors)})


@flask_app.route("/api/clear-logs", methods=["POST"])
def api_clear_logs():
    """API endpoint to clear all live error logs."""
    with log_lock:
        error_log.clear()
    return jsonify({"status": "ok", "message": "Logs cleared"})


@flask_app.route("/api/log_error", methods=["POST"])
def api_log_error():
    """V3.1: New endpoint for extension to log errors.
    Now also updates Project Memory for AI context persistence.
    """
    # Anti-loop guard: Skip errors from FixOnce hooks to prevent infinite loops
    if request.headers.get('X-FixOnce-Origin'):
        origin = request.headers.get('X-FixOnce-Origin')
        # Still log it, but mark as from hook
        print(f"[FixOnce] Received error from hook: {origin}")

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    # Extract error info
    error_data = data.get("data", {})
    entry = {
        "type": data.get("type", "unknown"),
        "message": error_data.get("message", data.get("message", "")),
        "severity": error_data.get("severity", "error"),
        "url": data.get("url", data.get("tabUrl", "")),
        "file": error_data.get("file", ""),
        "line": error_data.get("line", ""),
        "timestamp": data.get("timestamp", datetime.now().isoformat()),
    }

    # Check for existing solution
    if entry["message"] and SEMANTIC_ENABLED:
        try:
            engine = get_engine(PERSONAL_DB_PATH)
            match = engine.find_similar(entry["message"])
            if match:
                solution_id, score, _ = match
                solution = engine.get_solution_by_id(solution_id)
                if solution:
                    entry["matched_solution"] = {
                        "id": solution_id,
                        "score": score,
                        "solution": solution["solution_text"],
                        "success_count": solution.get("success_count", 0)
                    }
        except Exception as e:
            print(f"[V3.1] Match error: {e}")

    with log_lock:
        error_log.append(entry)

    # V4: Update Project Memory (deduplication handled inside)
    try:
        from project_memory_manager import add_or_update_issue
        # Extract rich context for X-Ray feature
        snippet = data.get("snippet", error_data.get("snippet", []))
        locals_data = data.get("locals", error_data.get("locals", {}))
        func_name = data.get("function", error_data.get("function", ""))
        stack_trace = data.get("stack", error_data.get("stack", ""))

        memory_result = add_or_update_issue(
            error_type=entry["type"],
            message=entry["message"],
            url=entry["url"],
            severity=entry["severity"],
            file=entry["file"],
            line=str(entry["line"]),
            function=func_name,
            snippet=snippet if isinstance(snippet, list) else [],
            locals_data=locals_data if isinstance(locals_data, dict) else {},
            stack=stack_trace,
            extra_data={"matched_solution": entry.get("matched_solution")}
        )
        print(f"[ProjectMemory] {memory_result['status']}: {memory_result['issue_id']} (count: {memory_result['count']})")

        # Send desktop notification for new errors
        if memory_result['status'] == 'new':
            is_critical = entry['severity'] == 'critical'
            short_msg = entry['message'][:100] + '...' if len(entry['message']) > 100 else entry['message']
            send_desktop_notification(
                title=f"🔴 FixOnce: {entry['type']}" if is_critical else f"⚠️ FixOnce: {entry['type']}",
                message=short_msg,
                sound=is_critical  # Sound only for critical errors
            )
    except Exception as e:
        print(f"[ProjectMemory] Error: {e}")

    print(f"[V3.1] {entry['severity'].upper()}: {entry['message'][:80]}")

    return jsonify({
        "status": "ok",
        "has_solution": "matched_solution" in entry,
        "solution_score": entry.get("matched_solution", {}).get("score", 0)
    })


@flask_app.route("/api/log_errors_batch", methods=["POST"])
def api_log_errors_batch():
    """V3.2: Batch endpoint for logging multiple errors in one request.
    Handles high traffic scenarios without overwhelming browser connections.
    """
    data = request.get_json(silent=True)
    if not data or "errors" not in data:
        return jsonify({"status": "error", "message": "No errors array"}), 400

    errors = data.get("errors", [])
    processed = 0

    for error_data in errors:
        try:
            entry = {
                "type": error_data.get("type", "unknown"),
                "message": error_data.get("message", ""),
                "severity": error_data.get("severity", "error"),
                "url": error_data.get("url", error_data.get("tabUrl", "")),
                "file": error_data.get("file", ""),
                "line": error_data.get("line", ""),
                "timestamp": error_data.get("timestamp", datetime.now().isoformat()),
            }

            with log_lock:
                error_log.append(entry)

            # Update Project Memory with rich context if available
            try:
                from project_memory_manager import add_or_update_issue
                snippet = error_data.get("snippet", [])
                locals_data = error_data.get("locals", {})
                func_name = error_data.get("function", "")
                stack_trace = error_data.get("stack", "")

                memory_result = add_or_update_issue(
                    error_type=entry["type"],
                    message=entry["message"],
                    url=entry["url"],
                    severity=entry["severity"],
                    file=entry["file"],
                    line=str(entry["line"]),
                    function=func_name,
                    snippet=snippet if isinstance(snippet, list) else [],
                    locals_data=locals_data if isinstance(locals_data, dict) else {},
                    stack=stack_trace,
                    extra_data={}
                )

                # Send desktop notification for new errors
                if memory_result.get('status') == 'new':
                    is_critical = entry['severity'] == 'critical'
                    short_msg = entry['message'][:100] + '...' if len(entry['message']) > 100 else entry['message']
                    send_desktop_notification(
                        title=f"🔴 FixOnce: {entry['type']}" if is_critical else f"⚠️ FixOnce: {entry['type']}",
                        message=short_msg,
                        sound=is_critical
                    )
            except Exception as e:
                print(f"[ProjectMemory] Batch error: {e}")

            processed += 1
        except Exception as e:
            print(f"[Batch] Error processing item: {e}")

    print(f"[V3.2] Batch processed: {processed}/{len(errors)} errors")

    return jsonify({
        "status": "ok",
        "processed": processed,
        "total": len(errors)
    })


@flask_app.route("/api/feedback", methods=["POST"])
def api_feedback():
    """V3.1: User feedback on solution matches."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error"}), 400

    solution_id = data.get("solution_id")
    feedback = data.get("feedback")  # "verified" or "incorrect"

    if not solution_id or feedback not in ["verified", "incorrect"]:
        return jsonify({"status": "error", "message": "Invalid feedback"}), 400

    if SEMANTIC_ENABLED:
        try:
            engine = get_engine(PERSONAL_DB_PATH)
            if feedback == "verified":
                engine.increment_success_count(solution_id)
            # For incorrect, we could decrease confidence or flag for review
            return jsonify({"status": "ok", "message": f"Feedback recorded: {feedback}"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# V4: Project Memory API - AI Context Persistence
# ---------------------------------------------------------------------------

@flask_app.route("/api/memory", methods=["GET"])
def api_get_memory():
    """Get full project memory JSON."""
    try:
        from project_memory_manager import get_project_context
        return jsonify(get_project_context())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/summary", methods=["GET"])
def api_get_memory_summary():
    """Get markdown summary of project memory (for AI consumption)."""
    try:
        from project_memory_manager import get_context_summary
        return get_context_summary(), 200, {'Content-Type': 'text/markdown'}
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/issues", methods=["GET"])
def api_get_active_issues():
    """Get active issues list."""
    try:
        from project_memory_manager import get_project_context
        memory = get_project_context()
        return jsonify({
            "count": len(memory['active_issues']),
            "issues": memory['active_issues']
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/issues/<issue_id>/resolve", methods=["POST"])
def api_resolve_issue(issue_id):
    """Resolve an issue and move to solutions history."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    solution_desc = data.get("solution", "")
    worked = data.get("worked", True)

    if not solution_desc:
        return jsonify({"status": "error", "message": "Solution description required"}), 400

    try:
        from project_memory_manager import resolve_issue
        result = resolve_issue(issue_id, solution_desc, worked)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/context", methods=["PUT"])
def api_update_context():
    """Update the AI context snapshot."""
    data = request.get_json(silent=True)
    if not data or "context" not in data:
        return jsonify({"status": "error", "message": "Context required"}), 400

    try:
        from project_memory_manager import update_ai_context
        result = update_ai_context(data["context"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/project", methods=["PUT"])
def api_update_project_info():
    """Update project information."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    try:
        from project_memory_manager import update_project_info
        result = update_project_info(
            name=data.get("name"),
            stack=data.get("stack"),
            status=data.get("status"),
            description=data.get("description")
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/clear-issues", methods=["POST"])
def api_clear_issues():
    """Clear all active issues."""
    try:
        from project_memory_manager import clear_active_issues
        return jsonify(clear_active_issues())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/solutions/<solution_id>", methods=["DELETE"])
def api_delete_memory_solution(solution_id):
    """Delete a solution from project memory history."""
    try:
        from project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        original_count = len(memory['solutions_history'])
        memory['solutions_history'] = [s for s in memory['solutions_history'] if s.get('id') != solution_id]
        deleted = len(memory['solutions_history']) < original_count
        if deleted:
            save_memory(memory)
            return jsonify({"status": "ok", "message": f"Solution {solution_id} deleted"})
        return jsonify({"error": "Solution not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/clear-history", methods=["POST"])
def api_clear_history():
    """Clear all solution history."""
    try:
        from project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        count = len(memory['solutions_history'])
        memory['solutions_history'] = []
        memory['stats']['total_solutions_applied'] = 0
        save_memory(memory)
        return jsonify({"status": "ok", "cleared": count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/health", methods=["GET"])
def api_memory_health():
    """Get memory health status for dashboard display."""
    try:
        from project_memory_manager import get_memory_health
        return jsonify(get_memory_health())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/roi", methods=["GET"])
def api_get_roi():
    """Get ROI statistics for dashboard display."""
    try:
        from project_memory_manager import get_roi_stats
        return jsonify(get_roi_stats())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/roi/track", methods=["POST"])
def api_track_roi():
    """Track an ROI event (solution_reused, decision_used, error_prevented, session_context)."""
    try:
        from project_memory_manager import (
            track_solution_reused, track_decision_used,
            track_error_prevented, track_session_with_context
        )
        data = request.get_json() or {}
        event_type = data.get("event")

        if event_type == "solution_reused":
            return jsonify(track_solution_reused(data.get("solution_id")))
        elif event_type == "decision_used":
            return jsonify(track_decision_used(data.get("decision_id")))
        elif event_type == "error_prevented":
            return jsonify(track_error_prevented())
        elif event_type == "session_context":
            return jsonify(track_session_with_context())
        else:
            return jsonify({"status": "error", "message": f"Unknown event type: {event_type}"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/roi/reset", methods=["POST"])
def api_reset_roi():
    """Reset ROI statistics (for testing)."""
    try:
        from project_memory_manager import reset_roi_stats
        return jsonify(reset_roi_stats())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/detect", methods=["POST"])
def api_detect_project():
    """Auto-detect project info from filesystem."""
    try:
        from project_memory_manager import auto_update_project_info
        result = auto_update_project_info()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/project/root", methods=["POST"])
def api_set_project_root():
    """Set the project root path."""
    try:
        from project_memory_manager import set_project_root
        data = request.get_json() or {}
        root_path = data.get("root_path")
        if not root_path:
            return jsonify({"status": "error", "message": "root_path is required"}), 400
        return jsonify(set_project_root(root_path))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/project/root", methods=["GET"])
def api_get_project_root():
    """Get the current project root path."""
    try:
        from project_memory_manager import get_project_root
        root_path = get_project_root()
        return jsonify({"root_path": root_path or ""})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/decisions", methods=["GET"])
def api_get_decisions():
    """Get all logged decisions."""
    try:
        from project_memory_manager import get_decisions
        decisions = get_decisions()
        return jsonify({"count": len(decisions), "decisions": decisions})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/decisions", methods=["POST"])
def api_add_decision():
    """Add a new decision."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    decision = data.get("decision", "")
    reason = data.get("reason", "")

    if not decision or not reason:
        return jsonify({"status": "error", "message": "Decision and reason required"}), 400

    try:
        from project_memory_manager import log_decision
        result = log_decision(decision, reason, data.get("context", ""))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/decisions/<decision_id>", methods=["DELETE"])
def api_delete_decision(decision_id):
    """Delete a decision."""
    try:
        from project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        original_count = len(memory.get('decisions', []))
        memory['decisions'] = [d for d in memory.get('decisions', []) if d.get('id') != decision_id]
        deleted = len(memory['decisions']) < original_count
        if deleted:
            save_memory(memory)
            return jsonify({"status": "ok", "message": f"Decision {decision_id} deleted"})
        return jsonify({"error": "Decision not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/decisions/<decision_id>/used", methods=["POST"])
def api_mark_decision_used(decision_id):
    """Mark a decision as used by AI."""
    try:
        from project_memory_manager import mark_decision_used
        result = mark_decision_used(decision_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/avoid", methods=["GET"])
def api_get_avoid():
    """Get all avoid patterns."""
    try:
        from project_memory_manager import get_avoid_list
        avoid = get_avoid_list()
        return jsonify({"count": len(avoid), "avoid": avoid})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/avoid", methods=["POST"])
def api_add_avoid():
    """Add a new avoid pattern."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    what = data.get("what", "")
    reason = data.get("reason", "")

    if not what or not reason:
        return jsonify({"status": "error", "message": "What and reason required"}), 400

    try:
        from project_memory_manager import log_avoid
        result = log_avoid(what, reason)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/avoid/<avoid_id>", methods=["DELETE"])
def api_delete_avoid(avoid_id):
    """Delete an avoid pattern."""
    try:
        from project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        original_count = len(memory.get('avoid', []))
        memory['avoid'] = [a for a in memory.get('avoid', []) if a.get('id') != avoid_id]
        deleted = len(memory['avoid']) < original_count
        if deleted:
            save_memory(memory)
            return jsonify({"status": "ok", "message": f"Avoid pattern {avoid_id} deleted"})
        return jsonify({"error": "Avoid pattern not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/avoid/<avoid_id>/used", methods=["POST"])
def api_mark_avoid_used(avoid_id):
    """Mark an avoid pattern as used by AI."""
    try:
        from project_memory_manager import mark_avoid_used
        result = mark_avoid_used(avoid_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/handover", methods=["GET"])
def api_get_handover():
    """Get the last handover summary."""
    try:
        from project_memory_manager import get_handover
        handover = get_handover()
        return jsonify({"handover": handover or {}})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/handover", methods=["POST"])
def api_save_handover():
    """Save a handover summary."""
    data = request.get_json(silent=True)
    if not data or not data.get("summary"):
        return jsonify({"status": "error", "message": "Summary required"}), 400

    try:
        from project_memory_manager import save_handover
        result = save_handover(data["summary"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/handover", methods=["DELETE"])
def api_clear_handover():
    """Clear the handover."""
    try:
        from project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        memory['handover'] = {}
        save_memory(memory)
        return jsonify({"status": "ok", "message": "Handover cleared"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/export", methods=["GET"])
def api_export_memory():
    """Export full memory as JSON file."""
    try:
        from project_memory_manager import get_project_context
        import io
        memory = get_project_context()

        # Create file-like object
        output = io.BytesIO()
        output.write(json.dumps(memory, ensure_ascii=False, indent=2).encode('utf-8'))
        output.seek(0)

        return send_file(
            output,
            mimetype='application/json',
            as_attachment=True,
            download_name=f"fixonce_memory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/memory/import", methods=["POST"])
def api_import_memory():
    """Import memory from JSON."""
    try:
        from project_memory_manager import save_memory, _create_default_memory

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "No JSON body"}), 400

        # Validate structure
        default = _create_default_memory()
        required_keys = ["project_info", "active_issues", "solutions_history"]

        for key in required_keys:
            if key not in data:
                return jsonify({"status": "error", "message": f"Missing required key: {key}"}), 400

        # Merge with defaults for any missing optional keys
        for key in default:
            if key not in data:
                data[key] = default[key]

        save_memory(data)
        return jsonify({"status": "ok", "message": "Memory imported successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/save-solution", methods=["POST"])
def api_save_solution():
    """API endpoint to save a solution to the learning database.
    V2: Now stores cleaned error text for semantic matching.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    error_message = data.get("error_message", "")
    solution_text = data.get("solution_text", "")
    scope = data.get("scope", "personal")

    if not error_message or not solution_text:
        return jsonify({"status": "error", "message": "Missing error_message or solution_text"}), 400

    if scope == "team":
        if not TEAM_DB_PATH:
            return jsonify({"status": "error", "message": "Team database not configured"}), 400
        db_path = TEAM_DB_PATH
    else:
        db_path = PERSONAL_DB_PATH

    # V2: Use semantic engine for saving (includes cleaning and vectorization)
    if SEMANTIC_ENABLED:
        try:
            engine = get_engine(db_path)
            solution_id = engine.save_solution(error_message, solution_text)
            return jsonify({
                "status": "ok",
                "message": f"Solution saved to {scope} database (V2 semantic)",
                "solution_id": solution_id
            })
        except Exception as e:
            print(f"[SemanticEngine] Save error: {e}, falling back to direct insert")

    # Fallback: Direct insert
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()

    cursor.execute(
        "INSERT INTO solutions (error_message, solution_text, timestamp) VALUES (?, ?, ?)",
        (error_message, solution_text, timestamp)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "message": f"Solution saved to {scope} database"})


def _run_flask():
    global ACTUAL_PORT

    try:
        ACTUAL_PORT = find_available_port(5000)
    except RuntimeError as e:
        print(f"⚠️  {e}")
        print("   Kill other processes or free up a port.")
        return

    # Save port to file so Extension can find it
    port_file = Path(__file__).parent / "current_port.txt"
    port_file.write_text(str(ACTUAL_PORT))

    if ACTUAL_PORT != 5000:
        print(f"⚠️  Port 5000 is in use, using port {ACTUAL_PORT} instead")

    flask_app.run(host="0.0.0.0", port=ACTUAL_PORT, debug=False, use_reloader=False)


# ---------------------------------------------------------------------------
# FastMCP – tools that Claude Code can call via STDIO
# ---------------------------------------------------------------------------
mcp = FastMCP("nati-debugger")


@mcp.tool()
def get_console_errors() -> list[dict]:
    """Return the last 50 browser console errors stored in memory."""
    with log_lock:
        errors = list(error_log)

    # Enrich each error with previous solution if available (hybrid search)
    for error in errors:
        error_msg = error.get("message", "")
        if error_msg:
            previous = find_solution_hybrid(error_msg)
            if previous:
                error["previous_solution"] = previous

    return errors


@mcp.tool()
def clear_logs() -> str:
    """Clear all stored browser console errors from memory."""
    with log_lock:
        error_log.clear()
    return "Logs cleared successfully."


@mcp.tool()
def save_solution(error_message: str, solution_text: str, scope: str = "personal") -> str:
    """
    Save a solution for an error to the learning database.

    Args:
        error_message: The error message that was solved
        solution_text: The solution (explanation + code) that fixed the error
        scope: Where to save - "personal" (default) or "team"

    Returns:
        Confirmation message
    """
    if scope == "team":
        if not TEAM_DB_PATH:
            return "❌ Team database is not configured. Set TEAM_DB_PATH in server.py"
        db_path = TEAM_DB_PATH
        db_name = "Team"
    else:
        db_path = PERSONAL_DB_PATH
        db_name = "Personal"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()

    cursor.execute(
        "INSERT INTO solutions (error_message, solution_text, timestamp) VALUES (?, ?, ?)",
        (error_message, solution_text, timestamp)
    )
    conn.commit()
    conn.close()

    return f"✅ Solution saved to {db_name} database! Error pattern stored for future reference."


@mcp.tool()
def list_solutions(scope: str = "all") -> list[dict]:
    """
    List saved solutions in the learning database.

    Args:
        scope: Which database to query - "personal", "team", or "all" (default)

    Returns:
        List of all stored solutions with their error messages and source
    """
    results = []

    if scope in ("personal", "all"):
        personal = get_all_solutions(PERSONAL_DB_PATH)
        for item in personal:
            results.append({
                "id": item["id"],
                "error_message": item["error_message"][:100] + "..." if len(item["error_message"]) > 100 else item["error_message"],
                "solution_preview": item["solution_text"][:200] + "..." if len(item["solution_text"]) > 200 else item["solution_text"],
                "timestamp": item["timestamp"],
                "source": "personal"
            })

    if scope in ("team", "all") and TEAM_DB_PATH and TEAM_DB_PATH.exists():
        team = get_all_solutions(TEAM_DB_PATH)
        for item in team:
            results.append({
                "id": item["id"],
                "error_message": item["error_message"][:100] + "..." if len(item["error_message"]) > 100 else item["error_message"],
                "solution_preview": item["solution_text"][:200] + "..." if len(item["solution_text"]) > 200 else item["solution_text"],
                "timestamp": item["timestamp"],
                "source": "team"
            })

    # Sort by timestamp descending
    results.sort(key=lambda x: x["timestamp"], reverse=True)

    return results


@mcp.tool()
def check_mission_log() -> dict:
    """
    V3.1: Check the latest error status from the mission log.
    IMPORTANT: Claude MUST call this before attempting to fix any error.

    Returns:
        Dict with:
        - latest_error: The most recent error message
        - has_verified_solution: Whether a verified fix exists
        - solution: The verified solution if exists
        - recommendation: What Claude should do next
    """
    with log_lock:
        if not error_log:
            return {
                "status": "empty",
                "message": "No errors in the log",
                "recommendation": "No action needed - no errors to fix"
            }

        latest = error_log[-1]

    error_msg = latest.get("message", "")
    result = {
        "latest_error": error_msg,
        "error_type": latest.get("type", "unknown"),
        "severity": latest.get("severity", "error"),
        "timestamp": latest.get("timestamp", ""),
        "url": latest.get("url", "")
    }

    # Check for existing solution
    if SEMANTIC_ENABLED and error_msg:
        try:
            engine = get_engine(PERSONAL_DB_PATH)
            match = engine.find_similar(error_msg)

            if match:
                solution_id, score, matched_clean = match
                solution = engine.get_solution_by_id(solution_id)

                if solution:
                    result["has_verified_solution"] = True
                    result["solution_id"] = solution_id
                    result["match_score"] = round(score * 100)
                    result["solution_text"] = solution["solution_text"]
                    result["success_count"] = solution.get("success_count", 0)
                    result["recommendation"] = (
                        f"FOUND VERIFIED SOLUTION ({result['match_score']}% match, "
                        f"verified {result['success_count']} times). "
                        "ASK USER: 'I found a verified fix. Shall I apply it?'"
                    )
                    return result
        except Exception as e:
            result["semantic_error"] = str(e)

    result["has_verified_solution"] = False
    result["recommendation"] = (
        "NO VERIFIED SOLUTION. Analyze the error and propose a fix, "
        "but ALWAYS ask user permission before making changes."
    )

    return result


# ---------------------------------------------------------------------------
# Main – start Flask in a background thread, then run MCP on STDIO
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--flask-only", action="store_true", help="Run Flask server only (no MCP)")
    args = parser.parse_args()

    print("=" * 60)
    print("  NATI DEBUGGER PRO v3.1 - Ultimate Edition")
    print("=" * 60)
    print()
    print(f"🔥 Flask API: http://localhost:{ACTUAL_PORT}")
    print(f"📊 Dashboard: http://localhost:{ACTUAL_PORT}/")
    print(f"📝 Smart Diary: http://localhost:{ACTUAL_PORT}/diary")
    print("🤖 MCP Tools: get_console_errors, check_mission_log, save_solution")
    print()
    if SEMANTIC_ENABLED:
        print("🧠 Semantic Engine: ENABLED (TF-IDF + Cosine Similarity)")
    if TEAM_DB_PATH:
        print(f"👥 Team DB: {TEAM_DB_PATH}")
    else:
        print("👤 Mode: Personal-only")
    print()
    print("=" * 60)

    if args.flask_only:
        # Run Flask in foreground (for standalone server mode)
        print("🌐 Running Flask-only mode (no MCP)")
        _run_flask()
    else:
        # Run Flask as daemon thread, MCP on stdio (for Claude Code integration)
        flask_thread = threading.Thread(target=_run_flask, daemon=True)
        flask_thread.start()
        mcp.run()
