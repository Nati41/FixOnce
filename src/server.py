"""
FixOnce Server
Main Flask application with route registration.
"""

import subprocess
import sys
import threading
import time
import traceback
import os
import signal
import logging
from pathlib import Path
from datetime import datetime

from flask import Flask, send_file, jsonify, request, make_response
from core.windows_subprocess import no_window_creationflags
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

_STARTUP_T0 = time.monotonic()
_STARTUP_LOG_FILE = Path.home() / ".fixonce" / "logs" / "server_startup.log"


def _startup_log(label: str):
    """Log startup diagnostics to file (stdout may be unavailable on Windows)."""
    elapsed = time.monotonic() - _STARTUP_T0
    message = f"[STARTUP {elapsed:6.2f}s] {label}"
    print(message, flush=True)
    try:
        _STARTUP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _STARTUP_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
            f.flush()
    except Exception:
        pass


def _startup_flag_enabled(flag: str) -> bool:
    return flag in sys.argv[1:]


if _startup_flag_enabled("--no-boundary"):
    os.environ["FIXONCE_DISABLE_BOUNDARY"] = "1"


# MCP import - may fail if mcp package has issues
if _startup_flag_enabled("--no-mcp-import"):
    MCP_AVAILABLE = False
    FastMCP = None
    print("[STARTUP] MCP import skipped by --no-mcp-import", flush=True)
else:
    _startup_log("import fastmcp: start")
    try:
        from fastmcp import FastMCP
        MCP_AVAILABLE = True
        _startup_log("import fastmcp: ok")
    except ImportError as e:
        MCP_AVAILABLE = False
        FastMCP = None
        print(f"[WARNING] FastMCP not available: {e}")
        print("   Running in Flask-only mode")
        _startup_log("import fastmcp: unavailable")

# Add server directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

_startup_log("import config/core/api modules: start")
from config import (
    VERSION,
    APP_NAME,
    DEFAULT_PORT,
    MAX_PORT_ATTEMPTS,
    DATA_DIR,
    INSTALL_DATA_DIR,
    PROJECT_ROOT as PROJECT_DIR,
    get_install_data_dir,
)
from core.db_solutions import init_all_databases, find_solution_hybrid
from api import register_blueprints, errors_bp
from core.error_store import get_error_log, get_log_lock
from api.status import set_actual_port, set_extension_connected
from core.port_manager import (
    find_available_port as pm_find_port,
    set_preferred_port,
    get_preferred_port,
    is_port_available,
    get_runtime_state,
    set_runtime_state,
    clear_runtime_state,
    acquire_server_lock,
    release_server_lock,
    get_canonical_port
)
from core.install_state import is_fixonce_installed
from core.runtime_log import log_runtime_event
_startup_log("import config/core/api modules: ok")


SERVER_LOG_FILE = DATA_DIR / "logs" / "server.log"


def _write_server_log(message: str, exc=None):
    """Append diagnostics directly; do not rely only on Flask logging handlers."""
    log_runtime_event(message, exc)


def _configure_server_error_logging():
    """Write packaged runtime tracebacks to the per-user FixOnce log folder."""
    try:
        SERVER_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(SERVER_LOG_FILE, encoding="utf-8")
        handler.setLevel(logging.ERROR)
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
        ))
        flask_app.logger.addHandler(handler)
        flask_app.logger.setLevel(logging.INFO)
    except Exception as exc:
        print(f"[WARNING] Could not configure server log file: {exc}", file=sys.stderr, flush=True)


def _install_data_dir() -> Path:
    return get_install_data_dir()


def _asset_path(filename: str) -> Path:
    return _install_data_dir() / filename

# ---------------------------------------------------------------------------
# Port Management (uses core.port_manager for multi-user support)
# ---------------------------------------------------------------------------
ACTUAL_PORT = DEFAULT_PORT
_FLASK_SERVER_HANDLE = None


def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    return not is_port_available(port)


def find_available_port(start_port: int = DEFAULT_PORT, max_attempts: int = MAX_PORT_ATTEMPTS) -> int:
    """Find an available port, respecting user's preferred port."""
    # First try user's preferred port
    preferred = get_preferred_port()
    if preferred and is_port_available(preferred):
        return preferred

    # Use port manager's logic
    return pm_find_port(preferred)


# ---------------------------------------------------------------------------
# Semantic Engine (optional)
# ---------------------------------------------------------------------------
try:
    if _startup_flag_enabled("--no-semantic"):
        raise ImportError("--no-semantic startup flag")
    else:
        _startup_log("semantic import: start")
        from core.semantic_engine import SemanticEngine, get_engine, reset_engine
        SEMANTIC_ENABLED = True
        print("[OK] Semantic Engine loaded successfully")
        _startup_log("semantic import: ok")
except ImportError as e:
    SEMANTIC_ENABLED = False
    print(f"[WARNING] Semantic Engine not available: {e}")
    print("   Falling back to exact/LIKE matching")
    _startup_log("semantic import: unavailable")


# ---------------------------------------------------------------------------
# Flask Application
# ---------------------------------------------------------------------------
# Configure Flask with data directory for templates and static files
# Flask serves static files from INSTALL directory (dashboard, templates)
# User data goes to USER_DATA_DIR (~/.fixonce/)
_startup_log("flask app creation: start")
flask_app = Flask(__name__,
                  template_folder=str(INSTALL_DATA_DIR),
                  static_folder=str(INSTALL_DATA_DIR))
CORS(flask_app)
_configure_server_error_logging()
_startup_log("flask app creation: ok")

# Register all route blueprints
_startup_log("register blueprints: start")
register_blueprints(flask_app)
_startup_log("register blueprints: ok")


# ---------------------------------------------------------------------------
# Dashboard & Static Routes
# ---------------------------------------------------------------------------
@flask_app.route("/_minimal_alive")
def minimal_alive():
    """Minimal route inside the real FixOnce Flask app for lifecycle isolation."""
    return "ok"


@flask_app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Stop the local FixOnce Flask server for menu/tray Quit."""
    remote_addr = request.remote_addr or ""
    if remote_addr not in {"127.0.0.1", "::1", "localhost"}:
        return jsonify({"status": "error", "message": "local requests only"}), 403

    def shutdown_later():
        time.sleep(0.1)
        handle = _FLASK_SERVER_HANDLE
        if handle is not None and hasattr(handle, "shutdown"):
            try:
                handle.shutdown()
                return
            except Exception as exc:
                _write_server_log("Server handle shutdown failed; falling back to SIGTERM", exc)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=shutdown_later, daemon=True).start()
    return jsonify({"status": "shutting_down", "pid": os.getpid(), "port": ACTUAL_PORT})


def _send_dashboard_file(path):
    """Serve dashboard HTML without browser caching."""
    path = Path(path)
    if not path.exists():
        current_install_data_dir = _install_data_dir()
        path = current_install_data_dir / path.name

    if not path.exists():
        message = (
            f"Dashboard asset missing: {path} "
            f"(INSTALL_DATA_DIR={INSTALL_DATA_DIR} resolved={_install_data_dir()} "
            f"frozen={getattr(sys, 'frozen', False)} "
            f"meipass={getattr(sys, '_MEIPASS', None)} "
            f"executable={sys.executable} cwd={Path.cwd()})"
        )
        _write_server_log(message)
        return make_response(f"Dashboard asset not found: {path.name}", 404)

    response = make_response(send_file(path))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@flask_app.errorhandler(Exception)
def log_unhandled_exception(exc):
    """Persist unhandled Flask errors for packaged Windows diagnostics."""
    if isinstance(exc, HTTPException):
        return exc

    _write_server_log(
        f"Unhandled request error path={getattr(request, 'path', 'unknown')} "
        f"method={getattr(request, 'method', 'unknown')} "
        f"install_data_dir={INSTALL_DATA_DIR} resolved={_install_data_dir()}",
        exc,
    )
    return jsonify({
        "error": "internal_server_error",
        "message": "FixOnce hit an internal server error.",
        "log": str(SERVER_LOG_FILE),
    }), 500


def _is_installed() -> bool:
    """Check if FixOnce installation is complete."""
    _startup_log("install state check: start")
    install_state = DATA_DIR / "install_state.json"
    request_port = request.host.split(':')[-1] if ':' in request.host else None
    try:
        request_port = int(request_port) if request_port is not None else None
    except ValueError:
        request_port = None

    result = is_fixonce_installed(request_port=request_port)
    if not result and sys.platform == "win32" and getattr(sys, "frozen", False):
        # Windows packaged installs are shared across local users, while
        # install_state.json/runtime.json are per-user. If this frozen server is
        # already serving the requested port, the installed app is usable for a
        # fresh Windows account without requiring a reinstall.
        result = request_port == ACTUAL_PORT
    _startup_log(f"install state check: ok installed={result}")
    _write_server_log(
        f"_is_installed install_state_exists={install_state.exists()} "
        f"request_port={request_port} installed={result}"
    )
    return result


@flask_app.route("/")
def dashboard():
    """Serve the main dashboard or redirect to installer."""
    from flask import redirect

    # If not installed, redirect to installer
    if not _is_installed():
        return redirect("/install")

    dashboard_path = _asset_path("dashboard.html")
    return _send_dashboard_file(dashboard_path)


@flask_app.route("/install")
def install_wizard():
    """Serve the installer wizard."""
    return _send_dashboard_file(_asset_path("installer.html"))


@flask_app.route("/setup-debug")
def setup_debug():
    """Debug route to manually access setup wizard (for troubleshooting)."""
    return _send_dashboard_file(_asset_path("installer.html"))


@flask_app.route("/next")
@flask_app.route("/vnext")
def dashboard_next():
    """Serve the current main dashboard for legacy vNext links."""
    return _send_dashboard_file(_asset_path("dashboard.html"))


@flask_app.route("/lite")
def dashboard_lite():
    """Serve the compact/minimal dashboard route."""
    return _send_dashboard_file(_asset_path("dashboard_minimal.html"))


@flask_app.route("/app")
def dashboard_app():
    """Serve the compact app dashboard (for native window)."""
    app_path = _asset_path("dashboard_app.html")
    return _send_dashboard_file(app_path)


@flask_app.route("/test-error")
def test_error_page():
    """Serve test error page for debugging error capture."""
    test_path = _asset_path("test_error.html")
    return _send_dashboard_file(test_path)


@flask_app.route("/logo.png")
def serve_logo():
    """Serve the FixOnce logo."""
    logo_path = _asset_path("logo.png")
    if logo_path.exists():
        return send_file(logo_path, mimetype='image/png')
    # Fallback - return 404
    return "Logo not found", 404


@flask_app.route("/app-icon.png")
def serve_app_icon():
    """Serve the FixOnce app icon."""
    icon_path = _asset_path("app-icon.png")
    if icon_path.exists():
        return send_file(icon_path, mimetype='image/png')
    return "App icon not found", 404


@flask_app.route("/favicon.ico")
def serve_favicon():
    """Serve the FixOnce favicon (uses app-icon.png)."""
    icon_path = _asset_path("app-icon.png")
    if icon_path.exists():
        return send_file(icon_path, mimetype='image/png')
    return "Favicon not found", 404


@flask_app.route("/fixonce-logo.svg")
def serve_fixonce_logo():
    """Serve the FixOnce SVG logo."""
    logo_path = _asset_path("fixonce_logo.svg")
    if logo_path.exists():
        return send_file(logo_path, mimetype='image/svg+xml')
    return "FixOnce logo not found", 404


@flask_app.route("/privacy.html")
def serve_privacy():
    """Serve the privacy policy page."""
    return _send_dashboard_file(_asset_path("privacy.html"))


@flask_app.route("/terms.html")
def serve_terms():
    """Serve the terms of use page."""
    return _send_dashboard_file(_asset_path("terms.html"))


@flask_app.route("/security.html")
def serve_security():
    """Serve the security overview page."""
    return _send_dashboard_file(_asset_path("security.html"))


@flask_app.route("/api/canonical-runtime")
def canonical_runtime():
    """
    Return the canonical runtime state.

    This endpoint allows dashboards to verify they're on the correct port.
    If the dashboard port doesn't match the canonical port, it should redirect.

    Returns:
        JSON with {port, pid, started_at, is_canonical}
    """
    import os
    state = get_runtime_state()

    if not state:
        return jsonify({
            "status": "error",
            "message": "No canonical server running"
        }), 503

    # Check if the requester is on the canonical port
    request_port = request.host.split(':')[-1] if ':' in request.host else '80'
    try:
        request_port = int(request_port)
    except ValueError:
        request_port = 80

    canonical_port = state.get("port")

    return jsonify({
        "status": "ok",
        "port": canonical_port,
        "pid": state.get("pid"),
        "started_at": state.get("started_at"),
        "user": state.get("user"),
        "is_canonical": request_port == canonical_port,
        "request_port": request_port
    })


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
def _describe_port_owner(port: int) -> str:
    """Best-effort description of the process occupying a local TCP port."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=no_window_creationflags(),
            )
            if result.returncode == 0:
                needle = f":{port}"
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 5 and parts[0].upper().startswith("TCP"):
                        local_addr = parts[1]
                        state = parts[3].upper()
                        pid = parts[-1]
                        if local_addr.endswith(needle) and state == "LISTENING":
                            name = _windows_process_name(pid)
                            return f"PID {pid}" + (f" ({name})" if name else "")
        except Exception as exc:
            return f"unknown process; netstat failed: {type(exc).__name__}: {exc}"

    return "unknown process"


def _windows_process_name(pid: str) -> str:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=no_window_creationflags(),
        )
        if result.returncode != 0:
            return ""
        line = (result.stdout or "").strip().splitlines()[0]
        if not line or "INFO:" in line:
            return ""
        return line.split('","', 1)[0].strip('"')
    except Exception:
        return ""


def _run_flask(strict_port: bool = False):
    global ACTUAL_PORT
    import os
    import atexit
    from core.port_manager import ensure_clean_startup

    current_pid = os.getpid()
    _startup_log(f"_run_flask enter pid={current_pid} strict_port={strict_port}")

    current_install_path = str(PROJECT_DIR)
    success, message = ensure_clean_startup(current_install_path)
    if not success:
        print()
        print(f"\033[1;31mERROR: {message}\033[0m")
        print()
        _startup_log(f"_run_flask returning: ensure_clean_startup failed: {message}")
        return
    elif "Stale server stopped" in message:
        print(f"[FixOnce] {message}")
        _startup_log(f"ensure_clean_startup: {message}")

    if strict_port and not is_port_available(DEFAULT_PORT):
        owner = _describe_port_owner(DEFAULT_PORT)
        print(
            f"ERROR: port {DEFAULT_PORT} occupied by {owner}. "
            f"FixOnce QA startup requires port {DEFAULT_PORT}; not falling back.",
            file=sys.stderr,
            flush=True,
        )
        _startup_log("_run_flask returning: strict port occupied")
        return

    # Try to acquire server lock
    if not acquire_server_lock(current_pid):
        print()
        print("\033[1;31mERROR: Another FixOnce server is already running.\033[0m")
        print("   Use 'kill <pid>' to stop it, or check ~/.fixonce/runtime.json")
        print()
        _startup_log("_run_flask returning: server lock unavailable")
        return

    if strict_port:
        requested_port = DEFAULT_PORT
    else:
        try:
            requested_port = find_available_port(DEFAULT_PORT)
        except RuntimeError as e:
            print(f"[WARNING] {e}")
            print("   Kill other processes or free up a port.")
            release_server_lock()
            _startup_log("_run_flask returning: no available port")
            return

    ACTUAL_PORT = int(requested_port)

    if ACTUAL_PORT != DEFAULT_PORT:
        print()
        print(f"\033[1;33mWARNING: Port {DEFAULT_PORT} busy. FixOnce is live on http://localhost:{ACTUAL_PORT}\033[0m")
        print()

    # Publish the discovered port before entering the blocking Flask run loop.
    set_actual_port(ACTUAL_PORT)

    # Write canonical runtime state (SINGLE SOURCE OF TRUTH)
    if not set_runtime_state(ACTUAL_PORT, current_pid):
        print()
        print("\033[1;31mERROR: Failed to set runtime state - another server may be running.\033[0m")
        print()
        release_server_lock()
        _startup_log("_run_flask returning: runtime state rejected")
        return

    # Save port to multiple locations for different consumers:
    # 1. User-specific config (~/.fixonce/config.json) - only for default port
    #    Fallback ports are ephemeral and not persisted as preferences
    if ACTUAL_PORT == DEFAULT_PORT:
        set_preferred_port(ACTUAL_PORT)
    # 2. Project data dir (for legacy/backup) - always write current port
    port_file = DATA_DIR / "current_port.txt"
    port_file.write_text(str(ACTUAL_PORT), encoding="utf-8")

    # Cleanup on exit
    def cleanup():
        _startup_log("_run_flask cleanup enter")
        clear_runtime_state()
        release_server_lock()
        _startup_log("_run_flask cleanup exit")

    atexit.register(cleanup)

    try:
        _serve_flask_blocking("127.0.0.1", ACTUAL_PORT)
    except KeyboardInterrupt:
        print("\n[MODE] Flask server stopped")
    finally:
        _startup_log("_run_flask finally: cleanup starting")
        cleanup()
        _startup_log("_run_flask finally: cleanup complete")

    _startup_log("_run_flask returning after blocking server path")
    _startup_log("_run_flask exit")


def _serve_flask_blocking(host: str, port: int):
    """Run Flask in blocking mode.

    On Windows we use Waitress because the Werkzeug dev server can crash with
    WinError 10038 / "serve_forever returned without exception" when serving
    the dashboard. macOS/Linux keep using Werkzeug.
    """
    global _FLASK_SERVER_HANDLE
    _startup_log(f"_serve_flask_blocking enter host={host} port={port} platform={sys.platform!r}")

    if sys.platform == "win32":
        _startup_log("waitress import: start")
        from waitress import serve
        from waitress.server import create_server
        _startup_log("waitress import: ok")

        _startup_log(f"waitress create_server: start http://{host}:{port}")
        try:
            server = create_server(flask_app, host=host, port=port, threads=8)
            _FLASK_SERVER_HANDLE = server
            _startup_log(f"waitress create_server: ok server={server}")
        except BaseException as e:
            _startup_log(f"waitress create_server: CRASH {type(e).__name__}: {e}")
            try:
                _STARTUP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with _STARTUP_LOG_FILE.open("a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [CREATE_SERVER CRASH]\n")
                    traceback.print_exc(file=f)
                    f.flush()
            except Exception:
                pass
            raise

        _startup_log("waitress server.run: start")
        print(f" * Running on http://{host}:{port}", flush=True)
        try:
            server.run()
            _startup_log("waitress server.run: returned normally (unexpected)")
        except KeyboardInterrupt:
            _startup_log("waitress server.run: KeyboardInterrupt")
            raise
        except SystemExit as e:
            _startup_log(f"waitress server.run: SystemExit code={e.code}")
            raise
        except BaseException as e:
            _startup_log(f"waitress server.run: CRASH {type(e).__name__}: {e}")
            try:
                _STARTUP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with _STARTUP_LOG_FILE.open("a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [SERVER.RUN CRASH]\n")
                    traceback.print_exc(file=f)
                    f.flush()
            except Exception:
                pass
            raise
        finally:
            _startup_log("waitress server.run: finally block reached")
            _FLASK_SERVER_HANDLE = None

        print("[ERROR] Waitress returned unexpectedly", file=sys.stderr, flush=True)
        _startup_log("_serve_flask_blocking returned unexpectedly from waitress")
        return

    from werkzeug.serving import make_server

    server = None
    try:
        _startup_log("werkzeug make_server: start")
        server = make_server(host, port, flask_app, threaded=True)
        _FLASK_SERVER_HANDLE = server
        _startup_log(f"werkzeug serve_forever: start http://{host}:{port}")
        print(f" * Running on http://{host}:{port}", flush=True)
        server.serve_forever()
        _startup_log("werkzeug serve_forever returned without exception")
    except KeyboardInterrupt:
        _startup_log("werkzeug serve_forever interrupted by KeyboardInterrupt")
        raise
    except BaseException as exc:
        print(f"[ERROR] Flask server crashed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        raise
    finally:
        if server is not None:
            _startup_log("_serve_flask_blocking finally: server_close starting")
            server.server_close()
            _startup_log("_serve_flask_blocking finally: server_close complete")
        _FLASK_SERVER_HANDLE = None
        _startup_log("_serve_flask_blocking exit")

    print("[ERROR] Flask run returned unexpectedly (serve_forever returned without exception)", file=sys.stderr, flush=True)
    _startup_log("_serve_flask_blocking returning after unexpected serve_forever return")


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--flask-only", action="store_true", help="Run Flask server only (no MCP)")
    parser.add_argument("--minimized", action="store_true", help="Start minimized (for Windows startup)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress startup messages")
    parser.add_argument("--strict-port", action="store_true", help="Fail instead of falling back when port 5000 is busy")
    parser.add_argument("--no-semantic", action="store_true", help="Disable semantic engine for startup isolation")
    parser.add_argument("--no-boundary", action="store_true", help="Disable boundary detection for startup isolation")
    parser.add_argument("--no-db", action="store_true", help="Skip database initialization for startup isolation")
    parser.add_argument("--no-init", action="store_true", help="Skip first-launch initialization for startup isolation")
    parser.add_argument("--no-mcp-import", action="store_true", help="Skip FastMCP import for startup isolation")
    args = parser.parse_args(argv)

    _startup_log(
        f"main parsed args: flask_only={args.flask_only} minimized={args.minimized} "
        f"quiet={args.quiet} strict_port={args.strict_port} "
        f"no_semantic={args.no_semantic} no_boundary={args.no_boundary} "
        f"no_db={args.no_db} no_init={args.no_init} "
        f"no_mcp_import={args.no_mcp_import}"
    )

    # First launch initialization - create data files from templates
    if args.no_init:
        _startup_log("project init / first launch: skipped by --no-init")
    else:
        _startup_log("project init / first launch: start")
        from core.first_launch import ensure_initialized
        ensure_initialized()
        _startup_log("project init / first launch: ok")

    # Initialize databases
    if args.no_db:
        _startup_log("database init: skipped by --no-db")
    else:
        _startup_log("database init: start")
        init_all_databases()
        _startup_log("database init: ok")

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
        _startup_log("flask-only run path: start")
        _run_flask(strict_port=args.strict_port)
        _startup_log("main flask-only path returned from _run_flask")
    else:
        _startup_log("starting Flask background thread for MCP mode")
        flask_thread = threading.Thread(target=_run_flask, daemon=True)
        flask_thread.start()
        _startup_log("starting MCP stdio run loop")
        mcp.run()


if __name__ == "__main__":
    try:
        _startup_log("__main__ entry")
        main()
        _startup_log("__main__ main() returned normally")
    except SystemExit as e:
        _startup_log(f"__main__ SystemExit: code={e.code}")
        raise
    except BaseException as e:
        _startup_log(f"__main__ unhandled exception: {type(e).__name__}: {e}")
        import traceback
        try:
            _STARTUP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _STARTUP_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [CRASH]\n")
                traceback.print_exc(file=f)
                f.flush()
        except Exception:
            pass
        raise
