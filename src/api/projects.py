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
        from managers.multi_project_manager import (
            list_projects,
            get_active_project_id,
            load_project_memory,
            set_active_project,
        )

        projects = list_projects()
        active_id = get_active_project_id()
        project_ids = {p.get("id") for p in projects}

        # Self-heal active pointer when it targets an old duplicate ID that was
        # collapsed by server-side deduplication.
        if active_id and active_id not in project_ids and projects:
            replacement = None
            try:
                active_memory = load_project_memory(active_id) or {}
                active_info = active_memory.get("project_info", {})
                active_dir = (active_info.get("working_dir") or "").strip().lower()
                active_name = (active_info.get("name") or "").strip().lower()

                if active_dir:
                    replacement = next(
                        (p for p in projects if (p.get("working_dir") or "").strip().lower() == active_dir),
                        None
                    )
                if not replacement and active_name:
                    replacement = next(
                        (p for p in projects if (p.get("name") or "").strip().lower() == active_name),
                        None
                    )
            except Exception:
                replacement = None

            if replacement and replacement.get("id"):
                repaired_id = replacement["id"]
                set_active_project(
                    repaired_id,
                    "dedupe_repair",
                    replacement.get("name"),
                    create_if_missing=False,
                    working_dir=(replacement.get("working_dir") or None),
                )
                active_id = repaired_id

        return jsonify({
            "projects": projects,
            "active_id": active_id,
            "count": len(projects)
        })
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


