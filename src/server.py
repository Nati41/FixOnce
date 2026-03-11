"""
FixOnce Server
Main Flask application with route registration.
"""

import socket
import sys
import threading
from pathlib import Path
from datetime import datetime

from flask import Flask, send_file, jsonify, request, make_response
from flask_cors import CORS

# MCP import - may fail if mcp package has issues
try:
    from fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError as e:
    MCP_AVAILABLE = False
    print(f"[WARNING] FastMCP not available: {e}")
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
    print("[OK] Semantic Engine loaded successfully")
except ImportError as e:
    SEMANTIC_ENABLED = False
    print(f"[WARNING] Semantic Engine not available: {e}")
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
def _send_dashboard_file(path):
    """Serve dashboard HTML without browser caching."""
    response = make_response(send_file(path))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@flask_app.route("/")
def dashboard():
    """Serve the main dashboard (lite)."""
    dashboard_path = DATA_DIR / "dashboard_lite.html"
    return _send_dashboard_file(dashboard_path)


@flask_app.route("/next")
@flask_app.route("/vnext")
def dashboard_vnext():
    """Redirect to lite dashboard (vnext disabled)."""
    from flask import redirect
    return redirect("/lite")


@flask_app.route("/app")
def dashboard_app():
    """Serve the compact app dashboard (for native window)."""
    app_path = DATA_DIR / "dashboard_app.html"
    return _send_dashboard_file(app_path)


@flask_app.route("/lite")
def dashboard_lite():
    """Serve the minimal Dashboard Lite."""
    lite_path = DATA_DIR / "dashboard_lite.html"
    return _send_dashboard_file(lite_path)


@flask_app.route("/test-error")
def test_error_page():
    """Serve test error page for debugging error capture."""
    test_path = DATA_DIR / "test_error.html"
    return _send_dashboard_file(test_path)


@flask_app.route("/logo.png")
def serve_logo():
    """Serve the FixOnce logo."""
    logo_path = DATA_DIR / "logo.png"
    if logo_path.exists():
        return send_file(logo_path, mimetype='image/png')
    # Fallback - return 404
    return "Logo not found", 404


@flask_app.route("/app-icon.png")
def serve_app_icon():
    """Serve the FixOnce app icon."""
    icon_path = DATA_DIR / "app-icon.png"
    if icon_path.exists():
        return send_file(icon_path, mimetype='image/png')
    return "App icon not found", 404


@flask_app.route("/fixonce-logo.svg")
def serve_fixonce_logo():
    """Serve the FixOnce SVG logo."""
    logo_path = DATA_DIR / "fixonce_logo.svg"
    if logo_path.exists():
        return send_file(logo_path, mimetype='image/svg+xml')
    return "FixOnce logo not found", 404



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
            return "[ERROR] Team database is not configured. Set TEAM_DB_PATH in config.py"
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

    return f"[OK] Solution saved to {db_name} database! Error pattern stored for future reference."


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
        print(f"[WARNING] {e}")
        print("   Kill other processes or free up a port.")
        return

    # Update status module with actual port
    set_actual_port(ACTUAL_PORT)

    # Save port to file so Extension can find it
    port_file = DATA_DIR / "current_port.txt"
    port_file.write_text(str(ACTUAL_PORT))

    if ACTUAL_PORT != DEFAULT_PORT:
        print(f"[WARNING] Port {DEFAULT_PORT} is in use, using port {ACTUAL_PORT} instead")

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
        print(f"[API] Flask API: http://localhost:{ACTUAL_PORT}")
        print(f"[UI] Dashboard: http://localhost:{ACTUAL_PORT}/")
        print("[MCP] Tools: get_console_errors, check_mission_log, save_solution")
        print()
        if SEMANTIC_ENABLED:
            print("[SEMANTIC] Engine: ENABLED (TF-IDF + Cosine Similarity)")
        print()
        print("=" * 60)
    elif args.minimized:
        # Minimized mode - just log to file, no console output
        print(f"FixOnce started on port {ACTUAL_PORT}")

    if args.flask_only or not MCP_AVAILABLE:
        if not MCP_AVAILABLE:
            print("[MODE] Running Flask-only mode (MCP not available)")
        else:
            print("[MODE] Running Flask-only mode (no MCP)")
        _run_flask()
    else:
        flask_thread = threading.Thread(target=_run_flask, daemon=True)
        flask_thread.start()
        mcp.run()
