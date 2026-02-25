"""
FixOnce Safety Routes
Safety Switch API - Preview, Approve, Undo code changes.
"""

from flask import jsonify, request

from . import safety_bp


@safety_bp.route("/settings", methods=["GET"])
def api_safety_settings_get():
    """Get current safety switch settings."""
    try:
        from managers.safety_manager import get_safety_settings
        return jsonify(get_safety_settings())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/settings", methods=["POST"])
def api_safety_settings_update():
    """Update safety switch settings."""
    try:
        from managers.safety_manager import update_safety_settings
        data = request.get_json(silent=True) or {}
        result = update_safety_settings(
            enabled=data.get("enabled"),
            auto_backup=data.get("auto_backup"),
            require_approval=data.get("require_approval")
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/changes/preview", methods=["POST"])
def api_safety_preview_change():
    """Create a pending change with diff preview."""
    try:
        from managers.safety_manager import create_pending_change
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "No JSON body"}), 400

        file_path = data.get("file_path")
        new_content = data.get("new_content")
        description = data.get("description", "Code change")

        if not file_path or new_content is None:
            return jsonify({"status": "error", "message": "file_path and new_content required"}), 400

        result = create_pending_change(file_path, new_content, description)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/changes/pending", methods=["GET"])
def api_safety_pending_changes():
    """Get list of pending changes."""
    try:
        from managers.safety_manager import get_pending_changes
        changes = get_pending_changes()
        return jsonify({"count": len(changes), "changes": changes})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/changes/<change_id>/approve", methods=["POST"])
def api_safety_approve_change(change_id: str):
    """Approve a pending change."""
    try:
        from managers.safety_manager import approve_change
        return jsonify(approve_change(change_id))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/changes/<change_id>/reject", methods=["POST"])
def api_safety_reject_change(change_id: str):
    """Reject a pending change."""
    try:
        from managers.safety_manager import reject_change
        data = request.get_json(silent=True) or {}
        reason = data.get("reason", "")
        return jsonify(reject_change(change_id, reason))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/changes/<change_id>/apply", methods=["POST"])
def api_safety_apply_change(change_id: str):
    """Apply an approved change."""
    try:
        from managers.safety_manager import apply_change
        return jsonify(apply_change(change_id))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/undo/<change_id>", methods=["POST"])
def api_safety_undo_change(change_id: str):
    """Undo an applied change."""
    try:
        from managers.safety_manager import undo_change
        return jsonify(undo_change(change_id))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/undo-last", methods=["POST"])
def api_safety_undo_last():
    """Undo the most recent applied change."""
    try:
        from managers.safety_manager import undo_last_change
        return jsonify(undo_last_change())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/history", methods=["GET"])
def api_safety_history():
    """Get change history."""
    try:
        from managers.safety_manager import get_change_history
        limit = request.args.get("limit", 20, type=int)
        history = get_change_history(limit)
        return jsonify({"count": len(history), "history": history})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/backups", methods=["GET"])
def api_safety_backups():
    """Get list of backup files."""
    try:
        from managers.safety_manager import get_backups_list
        backups = get_backups_list()
        return jsonify({"count": len(backups), "backups": backups})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/backups/cleanup", methods=["POST"])
def api_safety_cleanup_backups():
    """Clean up old backup files."""
    try:
        from managers.safety_manager import cleanup_old_backups
        data = request.get_json(silent=True) or {}
        days = data.get("days", 30)
        return jsonify(cleanup_old_backups(days))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/init", methods=["POST"])
def api_safety_init():
    """Initialize safety system."""
    try:
        from managers.safety_manager import init_safety_system
        data = request.get_json(silent=True) or {}
        project_root = data.get("project_root", "")
        return jsonify(init_safety_system(project_root))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================
# PROJECT DATA BACKUPS (Auto-backup system)
# ============================================================

@safety_bp.route("/project-backups", methods=["GET"])
def api_project_backups():
    """Get list of project data backups."""
    try:
        project_id = request.args.get("project_id")
        if not project_id:
            # Get active project
            from managers.multi_project_manager import get_active_project
            active = get_active_project()
            project_id = active.get("active_id") if active else None

        if not project_id:
            return jsonify({"status": "error", "message": "No project specified"}), 400

        from managers.multi_project_manager import get_project_path
        from core.safe_file import list_backups, get_data_stats

        project_path = get_project_path(project_id)
        backups = list_backups(str(project_path))
        stats = get_data_stats(str(project_path))

        return jsonify({
            "project_id": project_id,
            "stats": stats,
            "backups": backups
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/project-backups/restore", methods=["POST"])
def api_restore_project_backup():
    """Restore project data from a backup."""
    try:
        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id")
        backup_path = data.get("backup_path")  # Optional, uses latest if not specified

        if not project_id:
            from managers.multi_project_manager import get_active_project
            active = get_active_project()
            project_id = active.get("active_id") if active else None

        if not project_id:
            return jsonify({"status": "error", "message": "No project specified"}), 400

        from managers.multi_project_manager import get_project_path
        from core.safe_file import restore_from_backup, get_latest_backup

        project_path = get_project_path(project_id)

        if backup_path:
            success = restore_from_backup(str(project_path), backup_path)
        else:
            latest = get_latest_backup(str(project_path))
            if not latest:
                return jsonify({"status": "error", "message": "No backups found"}), 404
            success = restore_from_backup(str(project_path), str(latest))

        if success:
            return jsonify({"status": "ok", "message": f"Restored {project_id} from backup"})
        else:
            return jsonify({"status": "error", "message": "Restore failed"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@safety_bp.route("/data-stats", methods=["GET"])
def api_data_stats():
    """Get data statistics for all projects."""
    try:
        from managers.multi_project_manager import list_projects, get_project_path
        from core.safe_file import get_data_stats
        from pathlib import Path

        projects = list_projects()
        stats = []

        for proj in projects[:20]:  # Limit to 20 projects
            project_id = proj.get("id")
            if project_id:
                project_path = get_project_path(project_id)
                proj_stats = get_data_stats(str(project_path))
                proj_stats["project_id"] = project_id
                proj_stats["name"] = proj.get("name", project_id)
                stats.append(proj_stats)

        # Sort by size descending
        stats.sort(key=lambda x: x.get("size_kb", 0), reverse=True)

        return jsonify({
            "projects": stats,
            "total_size_kb": sum(s.get("size_kb", 0) for s in stats)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
