"""
FixOnce Projects API
Multi-project management endpoints.

NOTE: These endpoints are primarily for DASHBOARD use.
They may use active_project.json since they're dashboard-specific.
MCP tools should NOT use these endpoints - they should use their
own session state with ProjectContext.from_path().
"""

from flask import jsonify, request
from . import projects_bp, get_project_from_request


@projects_bp.route("", methods=["GET"])
def api_list_projects():
    """List all projects."""
    try:
        from managers.multi_project_manager import list_projects, get_active_project_id

        projects = list_projects()
        active_id = get_active_project_id()

        return jsonify({
            "projects": projects,
            "active_id": active_id,
            "count": len(projects)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/live-state", methods=["GET"])
def api_get_live_state():
    """
    Fast endpoint for frequently-changing state only.
    Reads directly from project JSON — no heavy processing.
    Returns: active_ais, current_goal, next_step, ai_session.
    Designed to be polled every 3-5 seconds.

    Auto-detects active editor based on MCP config file modification times.
    """
    try:
        from managers.multi_project_manager import get_active_project_id, get_project_path, save_project_memory
        import json
        import os
        from datetime import datetime
        from pathlib import Path

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"status": "no_project"})

        project_path = get_project_path(project_id)
        if not project_path.exists():
            return jsonify({"status": "no_project"})

        with open(project_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Auto-detect active editor from MCP config file modification times
        working_dir = data.get("project_info", {}).get("working_dir", "")
        with open("/tmp/fixonce_detect.log", "a") as f:
            f.write(f"Calling detect with working_dir: {working_dir}\n")
        detected_editor = _detect_active_editor_from_files(working_dir)
        with open("/tmp/fixonce_detect.log", "a") as f:
            f.write(f"Result: {detected_editor}\n")
        if detected_editor:
            data = _update_active_ais_if_needed(data, detected_editor, project_path)

        live_record = data.get("live_record", {})
        intent = live_record.get("intent", {})

        return jsonify({
            "status": "ok",
            "project_id": project_id,
            "active_ais": data.get("active_ais", {}),
            "ai_session": data.get("ai_session", {}),
            "current_goal": intent.get("current_goal", ""),
            "next_step": intent.get("next_step", ""),
            "updated_at": data.get("live_record", {}).get("updated_at", ""),
            "detected_editor": detected_editor,  # For debugging
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _detect_active_editor_from_files(working_dir: str) -> str:
    """
    Detect active editor based on running processes.
    Returns: "cursor", "claude", or None
    """
    import subprocess

    log_file = "/tmp/fixonce_detect.log"

    cursor_running = False
    claude_running = False

    # Check if Cursor is running
    try:
        result = subprocess.run(['pgrep', '-f', 'Cursor'], capture_output=True, text=True, timeout=2)
        cursor_running = result.returncode == 0 and bool(result.stdout.strip())
        with open(log_file, "a") as f:
            f.write(f"Cursor: returncode={result.returncode}, stdout={result.stdout[:50] if result.stdout else 'empty'}, running={cursor_running}\n")
    except Exception as e:
        with open(log_file, "a") as f:
            f.write(f"Cursor error: {e}\n")

    # Check if Claude Code is running
    try:
        result = subprocess.run(['pgrep', '-f', '/claude'], capture_output=True, text=True, timeout=2)
        claude_running = result.returncode == 0 and bool(result.stdout.strip())
        with open(log_file, "a") as f:
            f.write(f"Claude: returncode={result.returncode}, running={claude_running}\n")
    except Exception as e:
        with open(log_file, "a") as f:
            f.write(f"Claude error: {e}\n")

    # Determine result
    if cursor_running and claude_running:
        return "both"  # Both are running
    elif cursor_running:
        return "cursor"
    elif claude_running:
        return "claude"

    return None


def _update_active_ais_if_needed(data: dict, detected_editor: str, project_path) -> dict:
    """
    Update active_ais if detected editor is not in the list or hasn't been updated recently.
    """
    import json
    from datetime import datetime

    if not detected_editor:
        return data

    now = datetime.now()
    ACTIVE_TIMEOUT = 300  # 5 minutes

    if "active_ais" not in data:
        data["active_ais"] = {}

    # Handle "both" case - update both cursor and claude
    editors_to_update = ["cursor", "claude"] if detected_editor == "both" else [detected_editor]

    for editor in editors_to_update:
        # Check if this editor is already tracked and recent
        if editor in data["active_ais"]:
            last_activity = data["active_ais"][editor].get("last_activity", "")
            if last_activity:
                try:
                    last_dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                    if last_dt.tzinfo:
                        last_dt = last_dt.replace(tzinfo=None)
                    # If updated in last 60 seconds, skip
                    if (now - last_dt).total_seconds() < 60:
                        continue
                except:
                    pass

        # Update or add this editor
        if editor not in data["active_ais"]:
            data["active_ais"][editor] = {
                "started_at": now.isoformat(),
                "last_activity": now.isoformat()
            }
            print(f"[AutoDetect] Editor joined: {editor}")
        else:
            data["active_ais"][editor]["last_activity"] = now.isoformat()

    # Clean up inactive editors
    inactive = []
    for editor, info in list(data["active_ais"].items()):
        try:
            last_act = datetime.fromisoformat(info.get("last_activity", "").replace('Z', '+00:00'))
            if last_act.tzinfo:
                last_act = last_act.replace(tzinfo=None)
            if (now - last_act).total_seconds() > ACTIVE_TIMEOUT:
                inactive.append(editor)
        except:
            pass

    for editor in inactive:
        del data["active_ais"][editor]

    # Update ai_session for backward compatibility (use first editor or "both")
    if "ai_session" not in data:
        data["ai_session"] = {}
    data["ai_session"]["editor"] = detected_editor
    data["ai_session"]["last_activity"] = now.isoformat()
    data["ai_session"]["active"] = True

    # Save changes
    try:
        with open(project_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[AutoDetect] Failed to save: {e}")

    return data


@projects_bp.route("/grouped", methods=["GET"])
def api_get_projects_grouped():
    """
    Get projects grouped by status (Phase 1: Active/Recent UI).

    Returns:
        {
            "active": {
                "id": "...",
                "name": "...",
                "current_goal": "...",
                "open_errors": 2,
                "stack": "...",
                "last_activity_relative": "לפני 5 דקות"
            } or null,
            "recent": [
                {"id": "...", "name": "...", "last_activity_relative": "אתמול"},
                ...
            ],
            "stale": [...],
            "total_count": 3
        }
    """
    try:
        from managers.multi_project_manager import get_projects_by_status, get_active_project_id, get_project_path
        import json

        # Auto-detect active editor before returning data (keeps active_ais fresh)
        project_id = get_active_project_id()
        if project_id:
            project_path = get_project_path(project_id)
            if project_path.exists():
                with open(project_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                working_dir = data.get("project_info", {}).get("working_dir", "")
                detected_editor = _detect_active_editor_from_files(working_dir)
                if detected_editor:
                    _update_active_ais_if_needed(data, detected_editor, project_path)

        return jsonify(get_projects_by_status())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/active", methods=["GET"])
def api_get_active_project():
    """Get the currently active project with full memory."""
    try:
        from managers.multi_project_manager import get_active_project_with_memory
        return jsonify(get_active_project_with_memory())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/switch/<project_id>", methods=["POST"])
def api_switch_project(project_id):
    """Switch to a different project."""
    try:
        from managers.multi_project_manager import set_active_project, load_project_memory

        data = request.get_json(silent=True) or {}
        display_name = data.get('display_name')

        result = set_active_project(project_id, "manual", display_name)
        memory = load_project_memory(project_id)

        return jsonify({
            "status": "ok",
            "active": result,
            "memory": memory
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/detect", methods=["POST"])
def api_detect_project():
    """Auto-detect project from URL or path."""
    try:
        from managers.multi_project_manager import (
            detect_project_from_url,
            detect_project_from_path,
            load_project_memory
        )

        data = request.get_json(silent=True) or {}
        url = data.get('url')
        path = data.get('path')

        if url:
            result = detect_project_from_url(url)
        elif path:
            result = detect_project_from_path(path)
        else:
            return jsonify({"status": "error", "message": "URL or path required"}), 400

        if "error" in result:
            return jsonify({"status": "error", "message": result["error"]}), 400

        # Return with full memory
        project_id = result.get('active_id')
        memory = load_project_memory(project_id)

        return jsonify({
            "status": "ok",
            "project": result,
            "memory": memory
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/create", methods=["POST"])
def api_create_project():
    """Manually create a new project."""
    try:
        from managers.multi_project_manager import (
            generate_project_id,
            set_active_project,
            load_project_memory,
            save_project_memory
        )

        data = request.get_json(silent=True) or {}
        name = data.get('name')
        stack = data.get('stack', '')
        root_path = data.get('root_path', '')

        if not name:
            return jsonify({"status": "error", "message": "Name required"}), 400

        # Generate ID from name
        project_id = generate_project_id(name, "manual")

        # Create and switch to it
        result = set_active_project(project_id, "manual", name)

        # Update project info
        memory = load_project_memory(project_id)
        memory['project_info']['name'] = name
        memory['project_info']['stack'] = stack
        memory['project_info']['root_path'] = root_path
        save_project_memory(project_id, memory)

        return jsonify({
            "status": "ok",
            "project_id": project_id,
            "project": result,
            "memory": memory
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/<project_id>", methods=["GET"])
def api_get_project(project_id):
    """Get a specific project's memory."""
    try:
        from managers.multi_project_manager import load_project_memory, get_project_dir

        project_dir = get_project_dir(project_id)
        if not project_dir.exists():
            return jsonify({"status": "error", "message": "Project not found"}), 404

        memory = load_project_memory(project_id)

        return jsonify({
            "project_id": project_id,
            "memory": memory
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/<project_id>", methods=["DELETE"])
def api_delete_project(project_id):
    """Delete a project."""
    try:
        from managers.multi_project_manager import delete_project
        return jsonify(delete_project(project_id))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/migrate", methods=["POST"])
def api_migrate_projects():
    """Migrate from old flat structure to multi-project."""
    try:
        from managers.multi_project_manager import migrate_from_flat_memory
        return jsonify(migrate_from_flat_memory())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/all-insights", methods=["GET"])
def api_get_all_insights():
    """Get insights from ALL projects for unified view."""
    try:
        from managers.multi_project_manager import list_projects, load_project_memory

        all_insights = []
        all_decisions = []
        all_avoid = []

        projects = list_projects()

        for proj in projects:
            project_id = proj.get('id', '')
            project_name = proj.get('display_name', proj.get('id', 'Unknown'))

            try:
                memory = load_project_memory(project_id)
                live_record = memory.get('live_record', {})
                lessons = live_record.get('lessons', {})

                # Get insights
                for insight in lessons.get('insights', []):
                    all_insights.append({
                        'text': insight,
                        'project_id': project_id,
                        'project_name': project_name,
                        'type': 'insight'
                    })

                # Get decisions
                for decision in memory.get('decisions', []):
                    all_decisions.append({
                        **decision,
                        'project_id': project_id,
                        'project_name': project_name,
                        'type': 'decision'
                    })

                # Get avoid patterns
                for avoid in memory.get('avoid', []):
                    all_avoid.append({
                        **avoid,
                        'project_id': project_id,
                        'project_name': project_name,
                        'type': 'avoid'
                    })

            except Exception as e:
                print(f"[Projects] Error loading {project_id}: {e}")
                continue

        return jsonify({
            "insights": all_insights,
            "decisions": all_decisions,
            "avoid": all_avoid,
            "total": len(all_insights) + len(all_decisions) + len(all_avoid),
            "projects_count": len(projects)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/new-session", methods=["POST"])
def api_start_new_session():
    """Start a new AI session for the active project."""
    try:
        from datetime import datetime
        import hashlib
        from managers.multi_project_manager import (
            get_active_project_id,
            load_project_memory,
            save_project_memory
        )

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"status": "error", "message": "No active project"}), 400

        memory = load_project_memory(project_id)
        if not memory:
            return jsonify({"status": "error", "message": "Project not found"}), 404

        # Create new session
        now = datetime.now()
        session_hash = hashlib.md5(f"{project_id}{now.isoformat()}".encode()).hexdigest()[:8]

        memory['ai_session'] = {
            'session_id': session_hash,
            'started_at': now.isoformat(),
            'active': True,
            'editor': 'dashboard',  # Started from dashboard
            'briefing_sent': False
        }

        save_project_memory(project_id, memory)

        return jsonify({
            "status": "ok",
            "session_id": session_hash,
            "started_at": now.isoformat(),
            "message": "New session started"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
