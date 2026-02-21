"""
FixOnce Server
Main Flask application with route registration.
"""

import socket
import sys
import threading
from pathlib import Path
from datetime import datetime

from flask import Flask, send_file, jsonify, request
from flask_cors import CORS

# MCP import - may fail if mcp package has issues
try:
    from fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError as e:
    MCP_AVAILABLE = False
    print(f"⚠️ FastMCP not available: {e}")
    print("   Running in Flask-only mode")

# Add server directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import VERSION, APP_NAME, DEFAULT_PORT, MAX_PORT_ATTEMPTS, DATA_DIR, PROJECT_ROOT as PROJECT_DIR
from core.db_solutions import init_all_databases, find_solution_hybrid
from api import register_blueprints, errors_bp
from core.error_store import get_error_log, get_log_lock
from api.status import set_actual_port, set_extension_connected

# ---------------------------------------------------------------------------
# Port Management
# ---------------------------------------------------------------------------
ACTUAL_PORT = DEFAULT_PORT


def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def find_available_port(start_port: int = DEFAULT_PORT, max_attempts: int = MAX_PORT_ATTEMPTS) -> int:
    """Find an available port starting from start_port."""
    for i in range(max_attempts):
        port = start_port + i
        if not is_port_in_use(port):
            return port
    raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_attempts - 1}")


# ---------------------------------------------------------------------------
# Semantic Engine (optional)
# ---------------------------------------------------------------------------
try:
    from core.semantic_engine import SemanticEngine, get_engine, reset_engine
    SEMANTIC_ENABLED = True
    print("🧠 Semantic Engine loaded successfully")
except ImportError as e:
    SEMANTIC_ENABLED = False
    print(f"⚠️ Semantic Engine not available: {e}")
    print("   Falling back to exact/LIKE matching")


# ---------------------------------------------------------------------------
# Flask Application
# ---------------------------------------------------------------------------
flask_app = Flask(__name__)
CORS(flask_app)

# Register all route blueprints
register_blueprints(flask_app)


# ---------------------------------------------------------------------------
# Dashboard & Static Routes
# ---------------------------------------------------------------------------
@flask_app.route("/")
def dashboard():
    """Serve the main dashboard (vNext)."""
    dashboard_path = DATA_DIR / "dashboard_vnext.html"
    return send_file(dashboard_path)


@flask_app.route("/v3")
def dashboard_v3():
    """Serve the 3-layer dashboard (human-first, depth-on-demand)."""
    v3_path = DATA_DIR / "dashboard_v3.html"
    return send_file(v3_path)


@flask_app.route("/next")
@flask_app.route("/vnext")
def dashboard_vnext():
    """Serve the vNext dashboard (Project State Engine - minimalist)."""
    vnext_path = DATA_DIR / "dashboard_vnext.html"
    return send_file(vnext_path)


@flask_app.route("/app")
def dashboard_app():
    """Serve the compact app dashboard (for native window)."""
    app_path = DATA_DIR / "dashboard_app.html"
    return send_file(app_path)


@flask_app.route("/logo.png")
def serve_logo():
    """Serve the FixOnce logo."""
    logo_path = DATA_DIR / "logo.png"
    if logo_path.exists():
        return send_file(logo_path, mimetype='image/png')
    # Fallback - return 404
    return "Logo not found", 404


@flask_app.route("/test")
def test_site():
    """Serve the comprehensive test site."""
    test_path = PROJECT_DIR / "tests" / "test-site" / "index.html"
    return send_file(test_path)


@flask_app.route("/test/brutal")
def brutal_test_site():
    """Serve brutal adversarial test harness."""
    brutal_path = PROJECT_DIR / "tests" / "brutal" / "brutal_test.html"
    return send_file(brutal_path)


@flask_app.route("/demo")
def demo_site():
    """Serve the FixOnce demo/test page."""
    demo_path = DATA_DIR / "test_site.html"
    return send_file(demo_path)


# ---------------------------------------------------------------------------
# Current Site Tracking
# ---------------------------------------------------------------------------
CURRENT_SITE = None
CURRENT_SITE_LOCK = threading.Lock()


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


# ---------------------------------------------------------------------------
# Server Connection
# ---------------------------------------------------------------------------
@flask_app.route("/api/server/connect", methods=["POST"])
def api_server_connect():
    """Connect to user's server for monitoring."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    target_url = data.get("url", "")
    target_port = data.get("port", "")

    if not target_url and not target_port:
        return jsonify({"status": "error", "message": "URL or port required"}), 400

    if target_url and not target_port:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(target_url)
            target_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        except:
            pass

    try:
        from managers.project_memory_manager import get_project_context, save_memory
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
        from managers.project_memory_manager import get_project_context
        memory = get_project_context()
        server = memory.get("connected_server", {})
        return jsonify({
            "connected": bool(server.get("status") == "active"),
            "server": server
        })
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})


# ---------------------------------------------------------------------------
# AI Session
# ---------------------------------------------------------------------------
@flask_app.route("/api/session/start", methods=["POST"])
def api_session_start():
    """Start an AI session."""
    from managers.project_memory_manager import get_project_context, save_memory

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
        current_os = platform.system()
        if current_os == "Darwin":
            if editor == "claude":
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
            elif editor in ("vscode", "continue"):
                subprocess.run(["open", "-a", "Visual Studio Code"], check=True)
            else:
                return jsonify({"status": "error", "message": f"Unknown editor: {editor}"}), 400
        elif current_os == "Windows":
            if editor == "claude":
                # Prefer Claude CLI in a visible terminal
                subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", "claude"])
            elif editor == "cursor":
                subprocess.Popen(["cmd", "/c", "start", "", "cursor"])
            elif editor in ("vscode", "continue"):
                subprocess.Popen(["cmd", "/c", "start", "", "code"])
            else:
                return jsonify({"status": "error", "message": f"Unknown editor: {editor}"}), 400
        else:
            return jsonify({"status": "error", "message": "Unsupported OS for launch"}), 400

        return jsonify({"status": "ok", "message": f"Launched {editor}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@flask_app.route("/api/session/status", methods=["GET"])
def api_session_status():
    """Get current session status."""
    from managers.project_memory_manager import get_project_context

    memory = get_project_context()
    session = memory.get("ai_session", {})

    return jsonify({
        "active": session.get("active", False),
        "editor": session.get("editor"),
        "started_at": session.get("started_at"),
        "briefing_sent": session.get("briefing_sent", False)
    })


@flask_app.route("/api/launch-app", methods=["POST"])
def api_launch_app():
    """Launch the FixOnce desktop app."""
    import subprocess

    app_launcher = PROJECT_DIR / "scripts" / "app_launcher.py"

    if not app_launcher.exists():
        return jsonify({"success": False, "error": "app_launcher.py not found"}), 404

    try:
        subprocess.Popen(
            [sys.executable, str(app_launcher)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        return jsonify({"success": True, "message": "Desktop app launching..."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# FastMCP Tools (only if MCP available)
# ---------------------------------------------------------------------------
if MCP_AVAILABLE:
    mcp = FastMCP("fixonce")
    mcp_tool = mcp.tool
else:
    mcp = None
    # Dummy decorator when MCP not available
    def mcp_tool():
        return lambda f: f


@mcp_tool()
def get_console_errors() -> list:
    """Return the last 50 browser console errors stored in memory."""
    error_log = get_error_log()
    log_lock = get_log_lock()

    with log_lock:
        errors = list(error_log)

    # Enrich each error with previous solution if available
    for error in errors:
        error_msg = error.get("message", "")
        if error_msg:
            try:
                from config import PERSONAL_DB_PATH
                engine = get_engine(PERSONAL_DB_PATH) if SEMANTIC_ENABLED else None
                previous = find_solution_hybrid(error_msg, engine)
            except:
                previous = find_solution_hybrid(error_msg)

            if previous:
                error["previous_solution"] = previous

    return errors


@mcp_tool()
def clear_logs() -> str:
    """Clear all stored browser console errors from memory."""
    error_log = get_error_log()
    log_lock = get_log_lock()

    with log_lock:
        error_log.clear()
    return "Logs cleared successfully."


@mcp_tool()
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
    from core.db_solutions import save_solution as db_save_solution
    from config import PERSONAL_DB_PATH, TEAM_DB_PATH

    if scope == "team":
        if not TEAM_DB_PATH:
            return "❌ Team database is not configured. Set TEAM_DB_PATH in config.py"
        db_path = TEAM_DB_PATH
        db_name = "Team"
    else:
        db_path = PERSONAL_DB_PATH
        db_name = "Personal"

    try:
        engine = get_engine(db_path) if SEMANTIC_ENABLED else None
        db_save_solution(error_message, solution_text, db_path, engine)
    except:
        db_save_solution(error_message, solution_text, db_path)

    return f"✅ Solution saved to {db_name} database! Error pattern stored for future reference."


@mcp_tool()
def list_solutions(scope: str = "all") -> list:
    """
    List saved solutions in the learning database.

    Args:
        scope: Which database to query - "personal", "team", or "all" (default)

    Returns:
        List of all stored solutions with their error messages and source
    """
    from core.db_solutions import get_all_solutions
    from config import PERSONAL_DB_PATH, TEAM_DB_PATH

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

    results.sort(key=lambda x: x["timestamp"], reverse=True)
    return results


@mcp_tool()
def check_mission_log() -> dict:
    """
    Check the latest error status from the mission log.
    IMPORTANT: Claude MUST call this before attempting to fix any error.

    Returns:
        Dict with latest_error, has_verified_solution, solution, recommendation
    """
    error_log = get_error_log()
    log_lock = get_log_lock()

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

    if SEMANTIC_ENABLED and error_msg:
        try:
            from config import PERSONAL_DB_PATH
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
# Flask Runner
# ---------------------------------------------------------------------------
def _run_flask():
    global ACTUAL_PORT

    try:
        ACTUAL_PORT = find_available_port(DEFAULT_PORT)
    except RuntimeError as e:
        print(f"⚠️  {e}")
        print("   Kill other processes or free up a port.")
        return

    # Update status module with actual port
    set_actual_port(ACTUAL_PORT)

    # Save port to file so Extension can find it
    port_file = DATA_DIR / "current_port.txt"
    port_file.write_text(str(ACTUAL_PORT))

    if ACTUAL_PORT != DEFAULT_PORT:
        print(f"⚠️  Port {DEFAULT_PORT} is in use, using port {ACTUAL_PORT} instead")

    flask_app.run(host="0.0.0.0", port=ACTUAL_PORT, debug=False, use_reloader=False)


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--flask-only", action="store_true", help="Run Flask server only (no MCP)")
    parser.add_argument("--minimized", action="store_true", help="Start minimized (for Windows startup)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress startup messages")
    args = parser.parse_args()

    # Initialize databases
    init_all_databases()

    # Skip banner in quiet/minimized mode
    if not args.quiet and not args.minimized:
        print("=" * 60)
        print(f"  {APP_NAME} v{VERSION} - AI Memory Layer")
        print("=" * 60)
        print()
        print(f"🔥 Flask API: http://localhost:{ACTUAL_PORT}")
        print(f"📊 Dashboard: http://localhost:{ACTUAL_PORT}/")
        print("🤖 MCP Tools: get_console_errors, check_mission_log, save_solution")
        print()
        if SEMANTIC_ENABLED:
            print("🧠 Semantic Engine: ENABLED (TF-IDF + Cosine Similarity)")
        print()
        print("=" * 60)
    elif args.minimized:
        # Minimized mode - just log to file, no console output
        print(f"FixOnce started on port {ACTUAL_PORT}")

    if args.flask_only or not MCP_AVAILABLE:
        if not MCP_AVAILABLE:
            print("🌐 Running Flask-only mode (MCP not available)")
        else:
            print("🌐 Running Flask-only mode (no MCP)")
        _run_flask()
    else:
        flask_thread = threading.Thread(target=_run_flask, daemon=True)
        flask_thread.start()
        mcp.run()
