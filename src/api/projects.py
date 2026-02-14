"""
FixOnce Projects API
Multi-project management endpoints.
"""

from flask import jsonify, request
from . import projects_bp


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
        from managers.multi_project_manager import get_projects_by_status
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
