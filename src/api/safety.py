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
