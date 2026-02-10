"""
FixOnce Rules Routes
Rules sync API for Cursor/Windsurf integration.
"""

from flask import jsonify, request

from . import rules_bp


@rules_bp.route("/sync", methods=["POST"])
def api_sync_rules():
    """
    Manual sync of memory to .cursorrules and .windsurfrules files.
    Called from dashboard "Sync Now" button.
    """
    try:
        from managers.rules_generator import manual_sync
        data = request.get_json(silent=True) or {}
        project_path = data.get("project_path")

        result = manual_sync(project_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@rules_bp.route("/status", methods=["GET"])
def api_rules_status():
    """Get current rules sync status for dashboard display"""
    try:
        from managers.rules_generator import get_sync_status
        result = get_sync_status()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@rules_bp.route("/preview", methods=["GET"])
def api_rules_preview():
    """Preview what the generated rules content looks like"""
    try:
        from managers.rules_generator import get_memory_data, generate_fixonce_block
        memory = get_memory_data()

        if not memory:
            return jsonify({"error": "No memory data found"}), 404

        content = generate_fixonce_block(memory)
        return jsonify({
            "success": True,
            "content": content,
            "project": memory.get('project_info', {}).get('name', 'Unknown')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
