"""
FixOnce Status Routes
System status, health, and configuration endpoints.

Phase 0: Supports X-Project-Root header for explicit project context.
Dashboard requests can use X-Dashboard: true to fallback to active project.
"""

from flask import jsonify, request, current_app
from datetime import datetime
from pathlib import Path
import sys
import json
import os

from . import status_bp, get_project_from_request

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


def _is_dev_mode() -> bool:
    """Allow test endpoints only in explicit dev/test environments."""
    env_flag = os.getenv("FIXONCE_DEV_MODE") == "1" or os.getenv("FIXONCE_ALLOW_TEST_API") == "1"
    flask_env = os.getenv("FLASK_ENV", "").lower() == "development"
    runtime_flag = bool(current_app.debug or current_app.testing)
    host = (request.host or "").lower()
    loopback_host = host.startswith("127.0.0.1") or host.startswith("localhost")
    return env_flag or flask_env or runtime_flag or loopback_host


def _dev_only_guard():
    if _is_dev_mode():
        return None
    return jsonify({
        "status": "error",
        "message": "Test endpoint is disabled outside dev mode. Set FIXONCE_DEV_MODE=1."
    }), 403


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


@status_bp.route("/context", methods=["GET"])
def api_context_file():
    """
    Return the universal FixOnce context file.
    Generates fresh content from current memory state to ensure it's always up-to-date.
    """
    from config import PROJECT_DIR

    try:
        # Get current memory and generate context on-the-fly
        from managers.multi_project_manager import get_active_project_id, load_project_memory
        from core.context_generator import _generate_content

        project_id = get_active_project_id()
        if project_id:
            memory = load_project_memory(project_id)
            if memory:
                content = _generate_content(memory)
                if request.args.get("format") == "json" or "application/json" in request.headers.get("Accept", ""):
                    return jsonify({
                        "status": "ok",
                        "content": content,
                        "updated_at": datetime.now().isoformat(),
                        "source": "generated"
                    })
                return content, 200, {"Content-Type": "text/markdown; charset=utf-8"}

        # Fallback: try reading from file
        context_path = PROJECT_DIR / ".fixonce" / "CONTEXT.md"
        if context_path.exists():
            content = context_path.read_text(encoding="utf-8")
            if request.args.get("format") == "json" or "application/json" in request.headers.get("Accept", ""):
                return jsonify({
                    "status": "ok",
                    "path": str(context_path),
                    "content": content,
                    "updated_at": datetime.fromtimestamp(context_path.stat().st_mtime).isoformat(),
                    "source": "file"
                })
            return content, 200, {"Content-Type": "text/markdown; charset=utf-8"}

        return jsonify({
            "status": "error",
            "message": "No active project and no context file found"
        }), 404

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@status_bp.route("/test/scenarios", methods=["GET"])
def api_test_scenarios():
    """Return brutal test scenarios JSON file."""
    from config import PROJECT_DIR

    scenarios_path = PROJECT_DIR / "tests" / "brutal" / "scenarios.json"
    if not scenarios_path.exists():
        return jsonify({"status": "error", "message": "scenarios.json not found"}), 404
    try:
        with open(scenarios_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@status_bp.route("/test/results", methods=["POST"])
def api_save_test_results():
    """Save brutal harness results to tests/brutal/results.json (dev only)."""
    guard = _dev_only_guard()
    if guard:
        return guard

    from config import PROJECT_DIR
    data = request.get_json(silent=True) or {}
    results = data.get("results")
    if not isinstance(results, list):
        return jsonify({"status": "error", "message": "results[] is required"}), 400

    out_path = PROJECT_DIR / "tests" / "brutal" / "results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "saved_at": datetime.now().isoformat(),
        "run_meta": data.get("run_meta", {}),
        "summary": data.get("summary", {}),
        "results": results
    }
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return jsonify({"status": "ok", "path": str(out_path), "count": len(results)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@status_bp.route("/test/reset", methods=["POST"])
def api_test_reset():
    """
    Reset active project test memory safely (dev only).
    Keeps project identity while clearing volatile memory sections.
    """
    guard = _dev_only_guard()
    if guard:
        return guard

    from config import DATA_DIR, PROJECT_DIR
    from managers.multi_project_manager import get_active_project_id, load_project_memory, save_project_memory
    from core.error_store import clear_errors

    active_id = get_active_project_id()
    if not active_id:
        return jsonify({"status": "error", "message": "No active project"}), 400

    memory = load_project_memory(active_id)
    now = datetime.now().isoformat()

    # Preserve project identity only
    project_info = memory.get("project_info", {})
    working_dir = project_info.get("working_dir", "")

    memory["project_info"] = project_info
    memory["live_record"] = {
        "gps": {
            "working_dir": working_dir,
            "active_ports": [],
            "url": "",
            "environment": "dev",
            "updated_at": now
        },
        "architecture": {
            "summary": "",
            "stack": "",
            "key_flows": [],
            "updated_at": now
        },
        "intent": {
            "current_goal": "",
            "next_step": "",
            "blockers": [],
            "updated_at": now
        },
        "lessons": {
            "insights": [],
            "failed_attempts": [],
            "updated_at": now
        },
        "updated_at": now
    }
    memory["decisions"] = []
    memory["avoid"] = []
    memory["active_issues"] = []
    memory["solutions_history"] = []
    memory["debug_sessions"] = []
    memory["handover"] = {}
    memory["ai_queue"] = []
    memory["ai_session"] = {}
    memory["active_ais"] = {}
    memory["stats"] = {
        "total_errors_captured": 0,
        "total_solutions_applied": 0,
        "last_updated": now
    }
    memory["roi"] = {
        "solutions_reused": 0,
        "tokens_saved": 0,
        "errors_prevented": 0,
        "decisions_referenced": 0,
        "time_saved_minutes": 0,
        "sessions_with_context": 0
    }

    saved = save_project_memory(active_id, memory)
    cleared_live_errors = clear_errors(active_id)

    # Reset activity file
    activity_file = DATA_DIR / "activity_log.json"
    if activity_file.exists():
        with open(activity_file, "w", encoding="utf-8") as f:
            json.dump({"activities": [], "sessions": {}}, f, ensure_ascii=False, indent=2)

    # Reset brutal test results file
    results_path = PROJECT_DIR / "tests" / "brutal" / "results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"saved_at": now, "results": []}, f, ensure_ascii=False, indent=2)

    return jsonify({
        "status": "ok" if saved else "warning",
        "active_project": active_id,
        "cleared_live_errors": cleared_live_errors,
        "reset_activity": True,
        "results_path": str(results_path)
    })


@status_bp.route("/test/mock_live_error", methods=["POST"])
def api_test_mock_live_error():
    """
    Inject a mock live error and link it into project memory (dev only).
    """
    guard = _dev_only_guard()
    if guard:
        return guard

    from core.error_store import add_error
    from managers.multi_project_manager import get_active_project_id

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400

    active_id = get_active_project_id() or "__global__"
    now = datetime.now().isoformat()
    entry = {
        "type": data.get("type", "mock.error"),
        "message": message,
        "severity": data.get("severity", "error"),
        "url": data.get("url", "http://localhost:5000/v2"),
        "file": data.get("file", "tests/brutal/mock.js"),
        "line": data.get("line", 1),
        "source": "brutal_test",
        "timestamp": now,
        "meta": data.get("meta", {})
    }

    add_error(entry, project_id=active_id)

    issue_result = None
    try:
        from managers.project_memory_manager import add_or_update_issue
        issue_result = add_or_update_issue(
            error_type=entry["type"],
            message=entry["message"],
            url=entry["url"],
            severity=entry["severity"],
            file=entry["file"],
            line=str(entry["line"]),
            function=data.get("function", "brutal_test"),
            snippet=data.get("snippet", []),
            locals_data=data.get("locals", {}),
            stack=data.get("stack", ""),
            extra_data={"source": "brutal_test"}
        )
    except Exception as e:
        issue_result = {"status": "warning", "message": f"live-only inject; memory link failed: {e}"}

    return jsonify({
        "status": "ok",
        "project_id": active_id,
        "entry": entry,
        "issue_result": issue_result
    })


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


@status_bp.route("/semantic_status")
def api_semantic_status():
    """
    Get semantic search status for dashboard.
    Shows: provider, model, index stats per project.
    """
    from config import DATA_DIR

    result = {
        "enabled": False,
        "provider": None,
        "model": None,
        "dimension": None,
        "projects": []
    }

    # Check if semantic search is available
    try:
        from core.embeddings import get_best_provider
        from core.project_semantic import get_project_index_stats

        provider = get_best_provider()
        result["enabled"] = True
        result["provider"] = provider.__class__.__name__
        result["model"] = provider.model_id
        result["dimension"] = provider.dimension

        # Get stats for all projects with embeddings
        projects_dir = DATA_DIR / "projects_v2"
        if projects_dir.exists():
            for emb_dir in projects_dir.glob("*.embeddings"):
                project_id = emb_dir.stem.replace(".embeddings", "")
                config_file = emb_dir / "config.json"

                project_info = {
                    "project_id": project_id,
                    "indexed": False,
                    "document_count": 0,
                    "last_indexed": None
                }

                if config_file.exists():
                    try:
                        import json
                        with open(config_file, 'r') as f:
                            config = json.load(f)
                        project_info["indexed"] = True
                        project_info["document_count"] = config.get("document_count", 0)
                        project_info["last_indexed"] = config.get("last_rebuild") or config.get("created_at")
                        project_info["model"] = config.get("model_id")
                    except:
                        pass

                result["projects"].append(project_info)

    except ImportError as e:
        result["error"] = f"Semantic search not available: {e}"
    except Exception as e:
        result["error"] = str(e)

    return jsonify(result)


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
    from config import PROJECT_ROOT, DATA_DIR

    # In EXE mode, extension is in DATA_DIR (AppData)
    # In dev mode, extension is in PROJECT_ROOT
    if getattr(sys, 'frozen', False):
        extension_path = DATA_DIR / "extension"
    else:
        extension_path = PROJECT_ROOT / "extension"

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
            parent_dir = DATA_DIR if getattr(sys, 'frozen', False) else PROJECT_ROOT
            subprocess.run(["xdg-open", str(parent_dir)], check=True)

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


# ============ Dashboard Snapshot (Unified API for Widgets) ============

@status_bp.route("/dashboard_snapshot", methods=["GET"])
def api_dashboard_snapshot():
    """
    Unified dashboard snapshot - all data for widgets in one call.

    Returns:
        {
            "active_ais": [...],
            "ai_handoffs": [...],
            "roi": {...},
            "projects": [...],
            "knowledge": {...},
            "environment": {...},
            "activity": [...],
            "timestamp": "..."
        }
    """
    from config import DATA_DIR
    from datetime import datetime, timedelta

    snapshot = {
        "active_ais": [],
        "ai_handoffs": [],
        "roi": {
            "solutions_reused": 0,
            "decisions_referenced": 0,
            "errors_prevented": 0,
            "time_saved_minutes": 0,
            "tokens_saved": 0
        },
        "projects": [],
        "knowledge": {
            "total_insights": 0,
            "total_decisions": 0,
            "total_avoids": 0,
            "indexed_docs": 0,
            "top_learnings": []
        },
        "environment": {
            "env": "dev",
            "ports": [],
            "urls": [],
            "working_dir": None,
            "stage": None
        },
        "identity": None,
        "activity": [],
        "timestamp": datetime.now().isoformat()
    }

    try:
        # === Active AIs & Handoffs ===
        try:
            # Get from active project memory (where MCP stores it)
            from managers.multi_project_manager import get_active_project_id, load_project_memory

            active_project_id = get_active_project_id()
            if active_project_id:
                project_memory = load_project_memory(active_project_id) or {}

                # Active AIs
                active_ais = project_memory.get("active_ais", {})
                for ai_name, ai_data in active_ais.items():
                    snapshot["active_ais"].append({
                        "id": ai_name,
                        "editor": ai_name,  # ai_name IS the editor name
                        "started_at": ai_data.get("started_at"),
                        "last_activity": ai_data.get("last_activity")
                    })

                # AI Handoffs (last 10)
                handoffs = project_memory.get("ai_handoffs", [])
                snapshot["ai_handoffs"] = handoffs[-10:] if handoffs else []
        except Exception:
            pass

        # === ROI Stats ===
        try:
            from managers.project_memory_manager import get_roi_stats
            roi = get_roi_stats()
            snapshot["roi"] = {
                "solutions_reused": roi.get("solutions_reused", 0),
                "decisions_referenced": roi.get("decisions_referenced", 0),
                "errors_prevented": roi.get("errors_prevented", 0),
                "time_saved_minutes": roi.get("time_saved_minutes", 0),
                "tokens_saved": roi.get("tokens_saved", 0)
            }
        except Exception:
            pass

        # === Projects List ===
        try:
            from managers.multi_project_manager import (
                get_active_project_id, load_project_memory
            )

            active_id = get_active_project_id()
            all_projects = []

            # Scan projects_v2 directory
            projects_dir = DATA_DIR / "projects_v2"
            if projects_dir.exists():
                for f in projects_dir.glob("*.json"):
                    name = f.stem
                    if name not in ('__global__', 'live-state'):
                        all_projects.append(name)

            now = datetime.now()
            for pid in all_projects[:20]:  # Limit to 20 projects
                try:
                    memory = load_project_memory(pid) or {}
                    project_info = memory.get("project_info", {})
                    live_record = memory.get("live_record", {})

                    # Determine status based on last activity
                    last_updated = memory.get("last_updated") or live_record.get("updated_at")
                    status = "stale"
                    if pid == active_id:
                        status = "active"
                    elif last_updated:
                        try:
                            last_dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00').replace('+00:00', ''))
                            if (now - last_dt).days < 7:
                                status = "recent"
                        except:
                            pass

                    # Get counts
                    lessons = live_record.get("lessons", {})
                    insights_count = len(lessons.get("insights", []))
                    decisions_count = len(memory.get("decisions", []))
                    avoids_count = len(memory.get("avoid", []))

                    # Check semantic index
                    semantic_info = {"indexed": False, "doc_count": 0}
                    emb_dir = DATA_DIR / "projects_v2" / f"{pid}.embeddings"
                    if emb_dir.exists():
                        config_file = emb_dir / "config.json"
                        if config_file.exists():
                            with open(config_file, 'r') as cf:
                                emb_config = json.load(cf)
                            semantic_info = {
                                "indexed": True,
                                "doc_count": emb_config.get("document_count", 0)
                            }

                    snapshot["projects"].append({
                        "project_id": pid,
                        "name": project_info.get("name") or pid.split("_")[0],
                        "status": status,
                        "counts": {
                            "insights": insights_count,
                            "decisions": decisions_count,
                            "avoids": avoids_count
                        },
                        "semantic": semantic_info
                    })
                except Exception:
                    continue

            # Sort: active first, then recent, then stale
            status_order = {"active": 0, "recent": 1, "stale": 2}
            snapshot["projects"].sort(key=lambda p: status_order.get(p["status"], 3))

        except Exception:
            pass

        # === Knowledge Base Stats ===
        try:
            from managers.multi_project_manager import get_active_project_id, load_project_memory

            active_id = get_active_project_id()
            if active_id:
                memory = load_project_memory(active_id) or {}
                lessons = memory.get("live_record", {}).get("lessons", {})
                insights = lessons.get("insights", [])
                decisions = memory.get("decisions", [])
                avoids = memory.get("avoid", [])

                snapshot["knowledge"]["total_insights"] = len(insights)
                snapshot["knowledge"]["total_decisions"] = len(decisions)
                snapshot["knowledge"]["total_avoids"] = len(avoids)

                # Try semantic top learnings
                try:
                    from core.project_semantic import get_project_index_stats
                    stats = get_project_index_stats(active_id)
                    snapshot["knowledge"]["indexed_docs"] = stats.get("document_count", 0)
                except:
                    pass

                # Get top learnings with metadata
                top_learnings = []
                for insight in insights[-10:]:
                    if isinstance(insight, dict):
                        top_learnings.append({
                            "text": insight.get("text", str(insight))[:200],
                            "importance": insight.get("importance", 1),
                            "use_count": insight.get("use_count", 0)
                        })
                    else:
                        top_learnings.append({
                            "text": str(insight)[:200],
                            "importance": 1,
                            "use_count": 0
                        })

                # Sort by importance/use_count
                top_learnings.sort(key=lambda x: (x["importance"], x["use_count"]), reverse=True)
                snapshot["knowledge"]["top_learnings"] = top_learnings[:5]

        except Exception:
            pass

        # === Environment / GPS ===
        try:
            from managers.multi_project_manager import get_active_project_id, load_project_memory

            active_id = get_active_project_id()
            if active_id:
                memory = load_project_memory(active_id) or {}
                project_info = memory.get("project_info", {})
                live_record = memory.get("live_record", {})
                gps = live_record.get("gps", {})
                arch = live_record.get("architecture", {})
                intent = live_record.get("intent", {})

                # Get working_dir from gps or project_info
                working_dir = gps.get("working_dir") or project_info.get("working_dir")

                # Infer stage from intent or default
                stage = intent.get("stage") or project_info.get("stage") or "development"

                snapshot["environment"] = {
                    "env": gps.get("environment", "dev"),
                    "ports": gps.get("active_ports", []),
                    "urls": [gps.get("url")] if gps.get("url") else [],
                    "working_dir": working_dir,
                    "stage": stage,
                    "stack": arch.get("stack") or project_info.get("stack"),
                    "key_flows": arch.get("key_flows", [])
                }
        except Exception:
            pass

        # === Project Identity (human-readable snapshot) ===
        try:
            from managers.multi_project_manager import get_active_project_id, load_project_memory

            active_id = get_active_project_id()
            if active_id:
                memory = load_project_memory(active_id) or {}
                project_info = memory.get("project_info", {})
                live_record = memory.get("live_record", {})
                arch = live_record.get("architecture", {})
                intent = live_record.get("intent", {})
                lessons = live_record.get("lessons", {})
                decisions = memory.get("decisions", [])
                avoids = memory.get("avoid", [])

                last_decision = decisions[-1] if decisions else None
                last_insight_raw = (lessons.get("insights") or [])
                last_insight = last_insight_raw[-1] if last_insight_raw else None
                last_avoid = avoids[-1] if avoids else None

                snapshot["identity"] = {
                    "name": project_info.get("name") or active_id.split("_")[0],
                    "stack": arch.get("stack") or project_info.get("stack") or "",
                    "summary": arch.get("summary") or "",
                    "current_goal": intent.get("current_goal") or "",
                    "next_step": intent.get("next_step") or "",
                    "last_decision": {
                        "text": (last_decision.get("decision") or last_decision.get("text") or "")[:120],
                        "reason": (last_decision.get("reason") or "")[:120],
                    } if last_decision else None,
                    "last_insight": (
                        (last_insight.get("text") or last_insight.get("insight") or str(last_insight))[:120]
                        if isinstance(last_insight, dict) else str(last_insight)[:120]
                    ) if last_insight else None,
                    "last_avoid": (
                        (last_avoid.get("what") or last_avoid.get("text") or "")[:120]
                    ) if last_avoid else None,
                    "counts": {
                        "decisions": len(decisions),
                        "insights": len(last_insight_raw),
                        "avoids": len(avoids),
                    }
                }
        except Exception:
            pass

        # === Activity Stream ===
        try:
            activity_file = DATA_DIR / "activity_log.json"
            if activity_file.exists():
                with open(activity_file, 'r', encoding='utf-8') as f:
                    activity_data = json.load(f)

                activities = activity_data.get("activities", [])[:50]  # First 50 (newest first)

                # Get active project ID for filtering
                active_project_id = None
                try:
                    from managers.multi_project_manager import get_active_project_id
                    active_project_id = get_active_project_id()
                except Exception:
                    pass

                for act in activities:
                    act_project_id = act.get("project_id", "__global__")

                    # Include activity if:
                    # 1. It's from the active project, OR
                    # 2. It's a global activity (fallback), OR
                    # 3. It's an MCP tool activity (memory operations)
                    is_active_project = (act_project_id == active_project_id) if active_project_id else False
                    is_mcp_activity = act.get("type") == "mcp_tool" or act.get("file_context") == "memory"
                    is_global = act_project_id == "__global__"

                    if is_active_project or is_mcp_activity or (is_global and len(snapshot["activity"]) < 10):
                        snapshot["activity"].append({
                            "timestamp": act.get("timestamp"),
                            "tool": act.get("tool"),
                            "file": act.get("file"),
                            "human_name": act.get("human_name"),
                            "project_id": act_project_id,
                            "actor": act.get("editor", "unknown"),
                            "diff": act.get("diff"),  # {added, removed} if available
                            "type": act.get("type", "file_change"),  # Include type for MCP detection
                            "file_context": act.get("file_context", "")  # Include context
                        })

                # Limit and reverse to show newest first
                snapshot["activity"] = snapshot["activity"][:30]
                snapshot["activity"].reverse()
        except Exception:
            pass

        return jsonify({"status": "ok", "snapshot": snapshot})

    except Exception as e:
        snapshot["error"] = str(e)
        return jsonify({"status": "error", "snapshot": snapshot, "message": str(e)}), 500


# ============ Unified Latest Changes ============

@status_bp.route("/changes/latest", methods=["GET"])
def api_latest_changes():
    """
    Unified source of truth for "what's the latest change".

    Returns:
        latest_activity: Most recent file edit from activity_log
        latest_memory_update: Most recent live_record change
        latest_git: Most recent git commit (if available)
        canonical_latest: The authoritative "latest change" with decision rule

    Decision rule for canonical_latest:
        1. activity_feed (if < 10 minutes) → file edit
        2. git_commit (if < 30 minutes) → commit message
        3. live_record.intent (fallback) → current goal
    """
    from config import DATA_DIR
    from datetime import datetime, timedelta
    import subprocess

    now = datetime.now()
    result = {
        "latest_activity": None,
        "latest_memory_update": None,
        "latest_git": None,
        "canonical_latest": None,
        "decision_rule": "activity > git > intent",
        "timestamp": now.isoformat()
    }

    # === 1. Latest Activity (from activity_log.json) ===
    try:
        activity_file = DATA_DIR / "activity_log.json"
        if activity_file.exists():
            with open(activity_file, 'r', encoding='utf-8') as f:
                activity_data = json.load(f)

            activities = activity_data.get("activities", [])
            if activities:
                latest = activities[0]  # Newest first
                latest_ts = latest.get("timestamp")

                result["latest_activity"] = {
                    "type": "file_edit",
                    "file": latest.get("file") or latest.get("human_name"),
                    "tool": latest.get("tool"),
                    "timestamp": latest_ts,
                    "actor": latest.get("editor", "unknown"),
                    "summary": f"Edited {latest.get('human_name') or latest.get('file', 'file')}"
                }
    except Exception:
        pass

    # === 2. Latest Memory Update (from live_record) ===
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory

        active_id = get_active_project_id()
        if active_id:
            memory = load_project_memory(active_id) or {}
            live_record = memory.get("live_record", {})
            intent = live_record.get("intent", {})
            lessons = live_record.get("lessons", {})

            # Get the most recent update timestamp
            lr_updated = live_record.get("updated_at")
            current_goal = intent.get("current_goal")

            # Check for recent insights
            insights = lessons.get("insights", [])
            latest_insight = None
            if insights:
                last = insights[-1]
                if isinstance(last, dict):
                    latest_insight = last.get("text", str(last))
                else:
                    latest_insight = str(last)

            result["latest_memory_update"] = {
                "type": "memory",
                "current_goal": current_goal,
                "latest_insight": latest_insight[:100] if latest_insight else None,
                "timestamp": lr_updated,
                "summary": f"Goal: {current_goal}" if current_goal else "No goal defined"
            }
    except Exception:
        pass

    # === 3. Latest Git Commit (optional) ===
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory

        active_id = get_active_project_id()
        if active_id:
            memory = load_project_memory(active_id) or {}
            working_dir = memory.get("project_info", {}).get("working_dir")

            if working_dir and Path(working_dir).exists():
                git_result = subprocess.run(
                    ["git", "log", "-1", "--format=%H|%s|%ai"],
                    cwd=working_dir,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if git_result.returncode == 0 and git_result.stdout.strip():
                    parts = git_result.stdout.strip().split("|")
                    if len(parts) >= 3:
                        result["latest_git"] = {
                            "type": "git_commit",
                            "hash": parts[0][:8],
                            "message": parts[1],
                            "timestamp": parts[2],
                            "summary": f"commit: {parts[1][:50]}"
                        }
    except Exception:
        pass

    # === 4. Determine Canonical Latest ===
    # Rule: activity (< 10min) > git (< 30min) > intent

    canonical = None

    # Check activity feed first (priority 1)
    if result["latest_activity"]:
        act_ts = result["latest_activity"].get("timestamp")
        if act_ts:
            try:
                act_dt = datetime.fromisoformat(act_ts.replace('Z', '+00:00').replace('+00:00', ''))
                if act_dt.tzinfo:
                    act_dt = act_dt.replace(tzinfo=None)
                if (now - act_dt).total_seconds() < 600:  # < 10 minutes
                    canonical = {
                        "source": "activity",
                        "text": result["latest_activity"]["summary"],
                        "timestamp": act_ts,
                        "age_seconds": int((now - act_dt).total_seconds())
                    }
            except:
                pass

    # Check git if no recent activity (priority 2)
    if not canonical and result["latest_git"]:
        git_ts = result["latest_git"].get("timestamp")
        if git_ts:
            try:
                # Git timestamp format: "2026-02-19 22:00:00 +0200"
                git_dt = datetime.strptime(git_ts.split()[0] + " " + git_ts.split()[1], "%Y-%m-%d %H:%M:%S")
                if (now - git_dt).total_seconds() < 1800:  # < 30 minutes
                    canonical = {
                        "source": "git",
                        "text": result["latest_git"]["summary"],
                        "timestamp": git_ts,
                        "age_seconds": int((now - git_dt).total_seconds())
                    }
            except:
                pass

    # Fallback to intent (priority 3)
    if not canonical and result["latest_memory_update"]:
        canonical = {
            "source": "intent",
            "text": result["latest_memory_update"]["summary"],
            "timestamp": result["latest_memory_update"].get("timestamp"),
            "age_seconds": None
        }

    # Final fallback
    if not canonical:
        canonical = {
            "source": "none",
            "text": "No recent activity",
            "timestamp": None,
            "age_seconds": None
        }

    result["canonical_latest"] = canonical

    return jsonify({"status": "ok", **result})


# ============ Cross-Project Insights ============

@status_bp.route("/cross-project/insights", methods=["GET"])
def api_cross_project_insights():
    """
    Get insights and activity across all projects.

    Returns:
        global_insights: Insights that appear in multiple projects or are highly reusable
        recent_activity: Timeline of recent activity across all projects
        knowledge_stats: Aggregate stats across all projects
        shared_patterns: Common patterns/decisions across projects
    """
    from config import DATA_DIR
    from datetime import datetime, timedelta
    from collections import defaultdict

    result = {
        "global_insights": [],
        "recent_activity": [],
        "knowledge_stats": {
            "total_projects": 0,
            "total_insights": 0,
            "total_decisions": 0,
            "total_avoids": 0,
            "projects_with_knowledge": 0
        },
        "shared_patterns": [],
        "timestamp": datetime.now().isoformat()
    }

    try:
        projects_dir = DATA_DIR / "projects_v2"
        if not projects_dir.exists():
            return jsonify({"status": "ok", **result})

        all_insights = []
        all_decisions = []
        all_avoids = []
        project_activities = []

        # Scan all projects
        for f in projects_dir.glob("*.json"):
            name = f.stem
            if name in ('__global__', 'live-state'):
                continue

            result["knowledge_stats"]["total_projects"] += 1

            try:
                with open(f, 'r', encoding='utf-8') as pf:
                    project_data = json.load(pf)

                project_name = project_data.get("project_info", {}).get("name") or name.split("_")[0]
                live_record = project_data.get("live_record", {})
                lessons = live_record.get("lessons", {})

                # Collect insights
                insights = lessons.get("insights", [])
                for insight in insights:
                    text = insight.get("text", str(insight)) if isinstance(insight, dict) else str(insight)
                    timestamp = insight.get("timestamp") if isinstance(insight, dict) else None
                    all_insights.append({
                        "text": text[:200],
                        "project": project_name,
                        "project_id": name,
                        "timestamp": timestamp,
                        "importance": insight.get("importance", "medium") if isinstance(insight, dict) else "medium"
                    })

                # Collect decisions
                decisions = project_data.get("decisions", [])
                for decision in decisions:
                    dec_text = decision.get("decision", str(decision)) if isinstance(decision, dict) else str(decision)
                    all_decisions.append({
                        "text": dec_text[:150],
                        "project": project_name,
                        "project_id": name,
                        "timestamp": decision.get("timestamp") if isinstance(decision, dict) else None,
                        "reason": decision.get("reason", "") if isinstance(decision, dict) else ""
                    })

                # Collect avoids
                avoids = project_data.get("avoid", [])
                for avoid in avoids:
                    avoid_text = avoid.get("what", str(avoid)) if isinstance(avoid, dict) else str(avoid)
                    all_avoids.append({
                        "text": avoid_text[:150],
                        "project": project_name,
                        "project_id": name,
                        "reason": avoid.get("reason", "") if isinstance(avoid, dict) else ""
                    })

                # Track projects with knowledge
                if insights or decisions or avoids:
                    result["knowledge_stats"]["projects_with_knowledge"] += 1

            except Exception:
                continue

        # Update stats
        result["knowledge_stats"]["total_insights"] = len(all_insights)
        result["knowledge_stats"]["total_decisions"] = len(all_decisions)
        result["knowledge_stats"]["total_avoids"] = len(all_avoids)

        # Sort and get top insights (most recent first)
        all_insights.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
        result["global_insights"] = all_insights[:10]

        # Get recent activity from activity log
        try:
            activity_file = DATA_DIR / "activity_log.json"
            if activity_file.exists():
                with open(activity_file, 'r', encoding='utf-8') as af:
                    activity_data = json.load(af)

                activities = activity_data.get("activities", [])[-50:]

                # Group by project
                for act in activities:
                    project_id = act.get("project_id", "unknown")
                    project_name = project_id.split("_")[0] if project_id else "Unknown"

                    result["recent_activity"].append({
                        "project": project_name,
                        "project_id": project_id,
                        "file": act.get("human_name") or act.get("file", "").split("/")[-1],
                        "tool": act.get("tool"),
                        "timestamp": act.get("timestamp"),
                        "actor": act.get("editor") or act.get("actor", "unknown")
                    })

                # Reverse to show newest first
                result["recent_activity"] = result["recent_activity"][-20:][::-1]

        except Exception:
            pass

        # Find shared patterns (insights/decisions that appear in multiple projects or are generic)
        # Look for keywords that suggest reusability
        reusable_keywords = ['always', 'never', 'must', 'should', 'avoid', 'prefer', 'use', 'don\'t']

        for insight in all_insights[:20]:
            text_lower = insight["text"].lower()
            if any(kw in text_lower for kw in reusable_keywords):
                result["shared_patterns"].append({
                    "type": "insight",
                    "text": insight["text"],
                    "source_project": insight["project"],
                    "applicable_to": "all"
                })

        for decision in all_decisions[:10]:
            text_lower = decision["text"].lower()
            if any(kw in text_lower for kw in reusable_keywords):
                result["shared_patterns"].append({
                    "type": "decision",
                    "text": decision["text"],
                    "source_project": decision["project"],
                    "reason": decision.get("reason", ""),
                    "applicable_to": "all"
                })

        # Limit shared patterns
        result["shared_patterns"] = result["shared_patterns"][:5]

        return jsonify({"status": "ok", **result})

    except Exception as e:
        result["error"] = str(e)
        return jsonify({"status": "error", **result, "message": str(e)}), 500


# ============ AI Behavioral Audit ============

@status_bp.route("/test/ai-scenarios", methods=["GET"])
def api_ai_audit_scenarios():
    """Return AI behavioral audit scenarios."""
    from config import PROJECT_DIR

    scenarios_path = PROJECT_DIR / "tests" / "ai_real_world" / "scenarios.json"
    if not scenarios_path.exists():
        return jsonify({"status": "error", "message": "AI audit scenarios not found"}), 404

    try:
        with open(scenarios_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@status_bp.route("/test/ai-results", methods=["POST"])
def api_save_ai_audit_results():
    """Save AI behavioral audit results."""
    guard = _dev_only_guard()
    if guard:
        return guard

    from config import PROJECT_DIR

    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"status": "error", "message": "No data"}), 400

    # Add timestamp
    data["saved_at"] = datetime.now().isoformat()

    results_path = PROJECT_DIR / "tests" / "ai_real_world" / "results.json"
    try:
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return jsonify({
            "status": "ok",
            "path": str(results_path)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@status_bp.route("/test/ai-audit", methods=["GET"])
def api_serve_ai_audit():
    """Serve the AI behavioral audit HTML page."""
    from config import PROJECT_DIR

    audit_path = PROJECT_DIR / "tests" / "ai_real_world" / "audit.html"
    if not audit_path.exists():
        return jsonify({"status": "error", "message": "Audit page not found"}), 404

    return audit_path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


# ============ FixOnce Global Toggle ============

ENABLED_FLAG_FILE = Path(__file__).parent.parent.parent / "data" / "fixonce_enabled.json"


@status_bp.route("/fixonce/status", methods=["GET"])
def api_fixonce_status():
    """Get FixOnce enabled/disabled state."""
    try:
        if not ENABLED_FLAG_FILE.exists():
            return jsonify({"enabled": True})
        with open(ENABLED_FLAG_FILE, 'r') as f:
            data = json.load(f)
        return jsonify({"enabled": data.get("enabled", True)})
    except Exception:
        return jsonify({"enabled": True})


@status_bp.route("/fixonce/toggle", methods=["POST"])
def api_fixonce_toggle():
    """Toggle FixOnce on/off. Returns new state."""
    try:
        current = True
        if ENABLED_FLAG_FILE.exists():
            with open(ENABLED_FLAG_FILE, 'r') as f:
                current = json.load(f).get("enabled", True)

        new_state = not current
        ENABLED_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ENABLED_FLAG_FILE, 'w') as f:
            json.dump({"enabled": new_state, "toggled_at": datetime.now().isoformat()}, f)

        return jsonify({"enabled": new_state})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
