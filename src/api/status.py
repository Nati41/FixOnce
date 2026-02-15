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


@status_bp.route("/health")
def api_health():
    """
    Comprehensive health check endpoint.
    Checks: server, MCP, memory writable, dashboard reachable.
    """
    import os
    import subprocess
    from config import DATA_DIR, SRC_DIR

    health = {
        "status": "healthy",
        "checks": {},
        "timestamp": datetime.now().isoformat()
    }

    issues = []

    # Check 1: Server running (obviously true if we got here)
    health["checks"]["server"] = {"status": "ok", "port": ACTUAL_PORT}

    # Check 2: Data directory writable
    try:
        test_file = DATA_DIR / "health_check.tmp"
        test_file.write_text("test")
        test_file.unlink()
        health["checks"]["memory_writable"] = {"status": "ok", "path": str(DATA_DIR)}
    except Exception as e:
        health["checks"]["memory_writable"] = {"status": "error", "error": str(e)}
        issues.append("Cannot write to data directory")

    # Check 3: MCP server file exists
    mcp_server = SRC_DIR / "mcp_server" / "mcp_memory_server_v2.py"
    if mcp_server.exists():
        health["checks"]["mcp_server"] = {"status": "ok", "path": str(mcp_server)}
    else:
        health["checks"]["mcp_server"] = {"status": "error", "error": "MCP server file not found"}
        issues.append("MCP server file missing")

    # Check 4: Projects directory
    projects_dir = DATA_DIR / "projects_v2"
    if projects_dir.exists():
        project_count = len(list(projects_dir.glob("*.json")))
        health["checks"]["projects"] = {"status": "ok", "count": project_count}
    else:
        health["checks"]["projects"] = {"status": "warning", "message": "No projects yet"}

    # Check 5: Extension connection
    health["checks"]["extension"] = {
        "status": "ok" if EXTENSION_CONNECTED else "warning",
        "connected": EXTENSION_CONNECTED,
        "last_seen": EXTENSION_LAST_SEEN
    }
    if not EXTENSION_CONNECTED:
        issues.append("Chrome extension not connected")

    # Check 6: Active project
    try:
        active_file = DATA_DIR / "active_project.json"
        if active_file.exists():
            import json
            with open(active_file) as f:
                active = json.load(f)
            health["checks"]["active_project"] = {
                "status": "ok",
                "project_id": active.get("active_id"),
                "working_dir": active.get("working_dir")
            }
        else:
            health["checks"]["active_project"] = {"status": "warning", "message": "No active project"}
    except Exception as e:
        health["checks"]["active_project"] = {"status": "error", "error": str(e)}

    # Overall status
    if issues:
        health["status"] = "degraded"
        health["issues"] = issues

    return jsonify(health)


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

    mcp_server_path = str(SRC_DIR / "mcp_server" / "mcp_memory_server_v2.py")
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


@status_bp.route("/system/cursor_one_click", methods=["POST"])
def api_cursor_one_click():
    """One-click Cursor setup: Configure MCP + Create .cursorrules + Launch Cursor."""
    import subprocess
    import platform
    from config import SRC_DIR

    data = request.get_json(silent=True) or {}
    project_path = data.get("project_path")

    if not project_path:
        # Try to get from active project
        try:
            from managers.multi_project_manager import get_active_project_id, load_project_memory
            project_id = get_active_project_id()
            if project_id:
                memory = load_project_memory(project_id)
                project_path = memory.get('project_info', {}).get('working_dir')
        except:
            pass

    if not project_path:
        return jsonify({"status": "error", "message": "No project path provided"}), 400

    project_path = Path(project_path)
    if not project_path.exists():
        return jsonify({"status": "error", "message": f"Project path not found: {project_path}"}), 404

    results = {"mcp": None, "cursorrules": None, "launch": None}

    # Step 1: Configure MCP in ~/.cursor/mcp.json
    try:
        mcp_server_path = str(SRC_DIR / "mcp_server" / "mcp_memory_server_v2.py")
        cursor_config_path = Path.home() / ".cursor" / "mcp.json"
        cursor_config_path.parent.mkdir(parents=True, exist_ok=True)

        if cursor_config_path.exists():
            with open(cursor_config_path, 'r') as f:
                config = json.load(f)
        else:
            config = {}

        if "mcpServers" not in config:
            config["mcpServers"] = {}

        config["mcpServers"]["fixonce"] = {
            "command": sys.executable,
            "args": [mcp_server_path]
        }

        with open(cursor_config_path, 'w') as f:
            json.dump(config, f, indent=2)

        results["mcp"] = {"status": "ok", "path": str(cursor_config_path)}
    except Exception as e:
        results["mcp"] = {"status": "error", "message": str(e)}

    # Step 2: Create .cursorrules in the project
    try:
        cursorrules_path = project_path / ".cursorrules"
        cursorrules_content = f"""# FixOnce Protocol - MANDATORY RULES

You are FixOnce-powered. You have persistent memory. ALL RULES ARE MANDATORY.

---

## 🚨 RULE #1: Session Start - REQUIRED

On EVERY conversation start, IMMEDIATELY call:
```
auto_init_session(cwd="{project_path}")
```

Then display:
- 🧠 FixOnce header
- 📍 Last goal
- 💡 ALL insights from response
- 🔒 ALL decisions from response
- ⚠️ Avoid patterns (if any)

---

## 🚨 RULE #2: BEFORE ANY CHANGE - CHECK DECISIONS

**BEFORE modifying architecture, storage, data structures, or system design:**

1. CHECK the decisions returned from auto_init_session()
2. IF user request CONTRADICTS a decision:

```
🛑 STOP - Existing decision in FixOnce:
   "[decision text]"
   Reason: [reason]

Your request contradicts this decision.
Override? (yes/no)
```

**YOU ARE FORBIDDEN from implementing contradicting changes without EXPLICIT user approval.**

---

## 🚨 RULE #3: Update Goal BEFORE Starting Work

**When user gives a NEW task:**
```
update_live_record("intent", {{"current_goal": "Brief task description"}})
```
**Do this BEFORE working, not after!** Keeps dashboard live.

---

## 🚨 RULE #4: Logging During Work - REQUIRED

| Event | Action |
|-------|--------|
| Learned something | `update_live_record("lessons", {{"insight": "..."}})` |
| Decision made | `log_decision(decision, reason)` |
| Something to avoid | `log_avoid(what, reason)` |

After updates: `(📌 FixOnce: saved)`

---

## 🚨 RULE #5: CHECK Insights BEFORE Any Research

**BEFORE researching, YOU MUST:**
```
search_past_solutions("keywords")
```

**YOU ARE FORBIDDEN from external research if relevant insight exists.**
**If found:** `(📌 FixOnce: existing insight) "[insight]" - Applying...`
**Only if NO insight → proceed with research.**

---

## MCP Tools

| Tool | Purpose |
|------|---------|
| auto_init_session(cwd) | **REQUIRED first!** |
| update_live_record(section, data) | Update memory |
| log_decision(decision, reason) | Log decision |
| log_avoid(what, reason) | Log anti-pattern |
| search_past_solutions(query) | Search solutions |
| get_browser_errors(limit) | Check browser errors |
| get_live_record() | Read all insights |

---

## ENFORCEMENT

1. ALWAYS init at start
2. ALWAYS display decisions
3. NEVER contradict decision without approval
4. ALWAYS update goal BEFORE starting new work
5. ALWAYS log insights during work
6. ALWAYS use relevant insights - don't ignore them
7. ALWAYS search past solutions before fixing errors

**These are REQUIREMENTS, not suggestions.**
"""
        with open(cursorrules_path, 'w', encoding='utf-8') as f:
            f.write(cursorrules_content)

        results["cursorrules"] = {"status": "ok", "path": str(cursorrules_path)}
    except Exception as e:
        results["cursorrules"] = {"status": "error", "message": str(e)}

    # Step 3: Launch Cursor with the project
    try:
        system = platform.system()
        if system == "Darwin":
            # Try 'cursor' CLI first, fall back to 'open -a Cursor'
            try:
                subprocess.run(["cursor", str(project_path)], check=True, timeout=5)
            except (subprocess.CalledProcessError, FileNotFoundError):
                subprocess.run(["open", "-a", "Cursor", str(project_path)], check=True)
        elif system == "Windows":
            subprocess.run(["cursor", str(project_path)], check=True, shell=True)
        else:
            subprocess.run(["cursor", str(project_path)], check=True)

        results["launch"] = {"status": "ok"}
    except Exception as e:
        results["launch"] = {"status": "error", "message": str(e)}

    # Overall status
    all_ok = all(r.get("status") == "ok" for r in results.values() if r)
    return jsonify({
        "status": "ok" if all_ok else "partial",
        "results": results,
        "message": "Cursor configured and launched!" if all_ok else "Some steps failed"
    })


@status_bp.route("/system/first_run", methods=["GET"])
def api_check_first_run():
    """Check if this is the first run (for welcome guide)."""
    from config import DATA_DIR

    first_run_file = DATA_DIR / "first_run_complete.json"

    return jsonify({
        "is_first_run": not first_run_file.exists(),
        "show_welcome": not first_run_file.exists()
    })


@status_bp.route("/system/first_run/complete", methods=["POST"])
def api_complete_first_run():
    """Mark first run as complete."""
    from config import DATA_DIR

    first_run_file = DATA_DIR / "first_run_complete.json"

    try:
        with open(first_run_file, 'w') as f:
            json.dump({
                "completed_at": datetime.now().isoformat(),
                "version": "3.1"
            }, f)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@status_bp.route("/system/usage_stats", methods=["GET"])
def api_usage_stats():
    """Get usage statistics for ROI display."""
    from config import DATA_DIR

    try:
        # Get ROI data
        from managers.project_memory_manager import get_roi_stats
        roi = get_roi_stats()

        # Calculate additional stats
        total_syncs = (
            roi.get('sessions_with_context', 0) +
            roi.get('solutions_reused', 0) +
            roi.get('decisions_referenced', 0)
        )

        # Get today's activity count
        activity_file = DATA_DIR / "activity_log.json"
        today_activities = 0
        if activity_file.exists():
            with open(activity_file, 'r') as f:
                data = json.load(f)
            today = datetime.now().date().isoformat()
            today_activities = sum(
                1 for a in data.get('activities', [])
                if a.get('timestamp', '').startswith(today)
            )

        return jsonify({
            "total_syncs": total_syncs,
            "today_syncs": roi.get('sessions_with_context', 0),  # Approximate
            "solutions_reused": roi.get('solutions_reused', 0),
            "decisions_referenced": roi.get('decisions_referenced', 0),
            "errors_prevented": roi.get('errors_prevented', 0),
            "sessions_with_context": roi.get('sessions_with_context', 0),
            "tokens_saved": roi.get('tokens_saved', 0),
            "time_saved_minutes": roi.get('time_saved_minutes', 0),
            "today_activities": today_activities,
            "money_saved_usd": round(roi.get('tokens_saved', 0) * 0.00001, 2)  # Rough estimate
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "total_syncs": 0,
            "solutions_reused": 0
        })


@status_bp.route("/system/protocol_compliance", methods=["GET"])
def api_protocol_compliance():
    """
    Get protocol compliance status for dashboard widget.

    Returns status of AI protocol compliance:
    - Session initialized
    - Decisions displayed
    - Goal updated
    - Recent violations
    """
    try:
        # Try to get from MCP server
        from mcp_server.mcp_memory_server_v2 import get_compliance_for_api
        return jsonify(get_compliance_for_api())
    except ImportError:
        # MCP server not available, return default state
        return jsonify({
            "session_initialized": False,
            "initialized_at": None,
            "decisions_displayed": False,
            "goal_updated": False,
            "tool_calls_count": 0,
            "last_session_init": None,
            "violations": [],
            "editor": None,
            "error": "MCP server not loaded"
        })
