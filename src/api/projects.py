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
                # Don't force - let resolver check for live sessions first
                set_active_project(
                    repaired_id,
                    "catalog_repair",
                    replacement.get("name"),
                    create_if_missing=False,
                    working_dir=(replacement.get("working_dir") or None),
                    force=False,  # Respect live sessions
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
    """Get the currently active project with full memory using the resolver."""
    try:
        from core.active_project_resolver import get_active_project_for_dashboard
        from managers.multi_project_manager import load_project_memory

        resolved = get_active_project_for_dashboard()

        # Add full memory if we have a project
        memory = None
        if resolved.get("active_id"):
            memory = load_project_memory(resolved["active_id"])

        return jsonify({
            "active": True if resolved.get("active_id") else False,
            "project_id": resolved.get("active_id"),
            "display_name": resolved.get("display_name"),
            "working_dir": resolved.get("working_dir"),
            "source": resolved.get("source"),
            "source_details": resolved.get("source_details"),
            "confidence": resolved.get("confidence"),
            "rejected_candidates": resolved.get("rejected_candidates", []),
            "memory": memory,
        })
    except ImportError:
        # Fallback if resolver not available
        from managers.multi_project_manager import get_active_project_with_memory
        return jsonify(get_active_project_with_memory())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/sync-cache", methods=["POST"])
def api_sync_cache():
    """Sync active_project.json cache from the resolver's determination."""
    try:
        from core.active_project_resolver import sync_cache_from_resolver
        result = sync_cache_from_resolver()
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@projects_bp.route("/switch/<project_id>", methods=["POST"])
def api_switch_project(project_id):
    """Switch to a different project."""
    try:
        from managers.multi_project_manager import set_active_project, load_project_memory

        data = request.get_json(silent=True) or {}
        display_name = data.get('display_name')

        # force=True for explicit user selection from dashboard
        result = set_active_project(project_id, "manual", display_name, force=True)
        memory = load_project_memory(project_id)

        return jsonify({
            "status": "ok",
            "active": result,
            "memory": memory
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


