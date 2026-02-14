"""
FixOnce Memory Routes
Project memory API endpoints for AI context persistence.
"""

from flask import jsonify, request, send_file
from datetime import datetime
import json
import io

from . import memory_bp


@memory_bp.route("", methods=["GET"])
def api_get_memory():
    """Get full project memory JSON."""
    try:
        from managers.project_memory_manager import get_project_context
        return jsonify(get_project_context())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/summary", methods=["GET"])
def api_get_memory_summary():
    """Get markdown summary of project memory (for AI consumption)."""
    try:
        from managers.project_memory_manager import get_context_summary
        return get_context_summary(), 200, {'Content-Type': 'text/markdown'}
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/issues", methods=["GET"])
def api_get_active_issues():
    """Get active issues list."""
    try:
        from managers.project_memory_manager import get_project_context
        memory = get_project_context()
        return jsonify({
            "count": len(memory['active_issues']),
            "issues": memory['active_issues']
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/issues/<issue_id>/resolve", methods=["POST"])
def api_resolve_issue(issue_id):
    """Resolve an issue and move to solutions history."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    solution_desc = data.get("solution", "")
    worked = data.get("worked", True)

    if not solution_desc:
        return jsonify({"status": "error", "message": "Solution description required"}), 400

    try:
        from managers.project_memory_manager import resolve_issue
        result = resolve_issue(issue_id, solution_desc, worked)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/context", methods=["PUT"])
def api_update_context():
    """Update the AI context snapshot."""
    data = request.get_json(silent=True)
    if not data or "context" not in data:
        return jsonify({"status": "error", "message": "Context required"}), 400

    try:
        from managers.project_memory_manager import update_ai_context
        result = update_ai_context(data["context"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/project", methods=["PUT"])
def api_update_project_info():
    """Update project information."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    try:
        from managers.project_memory_manager import update_project_info
        result = update_project_info(
            name=data.get("name"),
            stack=data.get("stack"),
            status=data.get("status"),
            description=data.get("description")
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/project", methods=["POST"])
def api_set_project_info():
    """Set project info (name, stack, root_path) - used by wizard."""
    try:
        from managers.project_memory_manager import get_project_context, save_memory
        data = request.get_json() or {}

        memory = get_project_context()

        if 'name' in data:
            memory['project_info']['name'] = data['name']
        if 'stack' in data:
            memory['project_info']['stack'] = data['stack']
        if 'root_path' in data and data['root_path']:
            memory['project_info']['root_path'] = data['root_path']

        save_memory(memory)

        return jsonify({
            "status": "ok",
            "message": "Project info updated",
            "project": memory['project_info']
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/project/root", methods=["POST"])
def api_set_project_root():
    """Set the project root path."""
    try:
        from managers.project_memory_manager import set_project_root
        data = request.get_json() or {}
        root_path = data.get("root_path")
        if not root_path:
            return jsonify({"status": "error", "message": "root_path is required"}), 400
        return jsonify(set_project_root(root_path))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/project/root", methods=["GET"])
def api_get_project_root():
    """Get the current project root path."""
    try:
        from managers.project_memory_manager import get_project_root
        root_path = get_project_root()
        return jsonify({"root_path": root_path or ""})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/clear-issues", methods=["POST"])
def api_clear_issues():
    """Clear all active issues."""
    try:
        from managers.project_memory_manager import clear_active_issues
        return jsonify(clear_active_issues())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/solutions/<solution_id>", methods=["DELETE"])
def api_delete_memory_solution(solution_id):
    """Delete a solution from project memory history."""
    try:
        from managers.project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        original_count = len(memory['solutions_history'])
        memory['solutions_history'] = [s for s in memory['solutions_history'] if s.get('id') != solution_id]
        deleted = len(memory['solutions_history']) < original_count
        if deleted:
            save_memory(memory)
            return jsonify({"status": "ok", "message": f"Solution {solution_id} deleted"})
        return jsonify({"error": "Solution not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/clear-history", methods=["POST"])
def api_clear_history():
    """Clear all solution history."""
    try:
        from managers.project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        count = len(memory['solutions_history'])
        memory['solutions_history'] = []
        memory['stats']['total_solutions_applied'] = 0
        save_memory(memory)
        return jsonify({"status": "ok", "cleared": count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/health", methods=["GET"])
def api_memory_health():
    """Get memory health status for dashboard display."""
    try:
        from managers.project_memory_manager import get_memory_health
        return jsonify(get_memory_health())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/roi", methods=["GET"])
def api_get_roi():
    """Get ROI statistics for dashboard display."""
    try:
        from managers.project_memory_manager import get_roi_stats
        return jsonify(get_roi_stats())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/roi/track", methods=["POST"])
def api_track_roi():
    """Track an ROI event."""
    try:
        from managers.project_memory_manager import (
            track_solution_reused, track_decision_used,
            track_error_prevented, track_session_with_context
        )
        data = request.get_json() or {}
        event_type = data.get("event")

        if event_type == "solution_reused":
            return jsonify(track_solution_reused(data.get("solution_id")))
        elif event_type == "decision_used":
            return jsonify(track_decision_used(data.get("decision_id")))
        elif event_type == "error_prevented":
            return jsonify(track_error_prevented())
        elif event_type == "session_context":
            return jsonify(track_session_with_context())
        else:
            return jsonify({"status": "error", "message": f"Unknown event type: {event_type}"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/roi/reset", methods=["POST"])
def api_reset_roi():
    """Reset ROI statistics."""
    try:
        from managers.project_memory_manager import reset_roi_stats
        return jsonify(reset_roi_stats())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/detect", methods=["POST"])
def api_detect_project():
    """Auto-detect project info from filesystem."""
    try:
        from managers.project_memory_manager import auto_update_project_info
        result = auto_update_project_info()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Decisions API ============

@memory_bp.route("/decisions", methods=["GET"])
def api_get_decisions():
    """Get all logged decisions."""
    try:
        from managers.project_memory_manager import get_decisions
        decisions = get_decisions()
        return jsonify({"count": len(decisions), "decisions": decisions})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/decisions", methods=["POST"])
def api_add_decision():
    """Add a new decision."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    decision = data.get("decision", "")
    reason = data.get("reason", "")

    if not decision or not reason:
        return jsonify({"status": "error", "message": "Decision and reason required"}), 400

    try:
        from managers.project_memory_manager import log_decision
        result = log_decision(decision, reason, data.get("context", ""))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/decisions/<decision_id>", methods=["DELETE"])
def api_delete_decision(decision_id):
    """Delete a decision."""
    try:
        from managers.project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        original_count = len(memory.get('decisions', []))
        memory['decisions'] = [d for d in memory.get('decisions', []) if d.get('id') != decision_id]
        deleted = len(memory['decisions']) < original_count
        if deleted:
            save_memory(memory)
            return jsonify({"status": "ok", "message": f"Decision {decision_id} deleted"})
        return jsonify({"error": "Decision not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/decisions/<decision_id>/used", methods=["POST"])
def api_mark_decision_used(decision_id):
    """Mark a decision as used by AI."""
    try:
        from managers.project_memory_manager import mark_decision_used
        result = mark_decision_used(decision_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Avoid Patterns API ============

@memory_bp.route("/avoid", methods=["GET"])
def api_get_avoid():
    """Get all avoid patterns."""
    try:
        from managers.project_memory_manager import get_avoid_list
        avoid = get_avoid_list()
        return jsonify({"count": len(avoid), "avoid": avoid})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/avoid", methods=["POST"])
def api_add_avoid():
    """Add a new avoid pattern."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    what = data.get("what", "")
    reason = data.get("reason", "")

    if not what or not reason:
        return jsonify({"status": "error", "message": "What and reason required"}), 400

    try:
        from managers.project_memory_manager import log_avoid
        result = log_avoid(what, reason)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/avoid/<avoid_id>", methods=["DELETE"])
def api_delete_avoid(avoid_id):
    """Delete an avoid pattern."""
    try:
        from managers.project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        original_count = len(memory.get('avoid', []))
        memory['avoid'] = [a for a in memory.get('avoid', []) if a.get('id') != avoid_id]
        deleted = len(memory['avoid']) < original_count
        if deleted:
            save_memory(memory)
            return jsonify({"status": "ok", "message": f"Avoid pattern {avoid_id} deleted"})
        return jsonify({"error": "Avoid pattern not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/avoid/<avoid_id>/used", methods=["POST"])
def api_mark_avoid_used(avoid_id):
    """Mark an avoid pattern as used by AI."""
    try:
        from managers.project_memory_manager import mark_avoid_used
        result = mark_avoid_used(avoid_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Handover API ============

@memory_bp.route("/handover", methods=["GET"])
def api_get_handover():
    """Get the last handover summary."""
    try:
        from managers.project_memory_manager import get_handover
        handover = get_handover()
        return jsonify({"handover": handover or {}})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/handover", methods=["POST"])
def api_save_handover():
    """Save a handover summary."""
    data = request.get_json(silent=True)
    if not data or not data.get("summary"):
        return jsonify({"status": "error", "message": "Summary required"}), 400

    try:
        from managers.project_memory_manager import save_handover
        result = save_handover(data["summary"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/handover", methods=["DELETE"])
def api_clear_handover():
    """Clear the handover."""
    try:
        from managers.project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        memory['handover'] = {}
        save_memory(memory)
        return jsonify({"status": "ok", "message": "Handover cleared"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Export/Import API ============

@memory_bp.route("/export", methods=["GET"])
def api_export_memory():
    """Export full memory as JSON file."""
    try:
        from managers.project_memory_manager import get_project_context
        memory = get_project_context()

        output = io.BytesIO()
        output.write(json.dumps(memory, ensure_ascii=False, indent=2).encode('utf-8'))
        output.seek(0)

        return send_file(
            output,
            mimetype='application/json',
            as_attachment=True,
            download_name=f"fixonce_memory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/import", methods=["POST"])
def api_import_memory():
    """Import memory from JSON."""
    try:
        from managers.project_memory_manager import save_memory, _create_default_memory

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "No JSON body"}), 400

        default = _create_default_memory()
        required_keys = ["project_info", "active_issues", "solutions_history"]

        for key in required_keys:
            if key not in data:
                return jsonify({"status": "error", "message": f"Missing required key: {key}"}), 400

        for key in default:
            if key not in data:
                data[key] = default[key]

        save_memory(data)
        return jsonify({"status": "ok", "message": "Memory imported successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Live Record API ============

@memory_bp.route("/live-record", methods=["GET"])
def api_get_live_record():
    """Get the full Live Record for warm start."""
    try:
        from managers.project_memory_manager import get_live_record
        return jsonify(get_live_record())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/live-record/summary", methods=["GET"])
def api_get_live_record_summary():
    """Get Live Record as formatted markdown summary."""
    try:
        from managers.project_memory_manager import get_live_record_summary
        return get_live_record_summary(), 200, {'Content-Type': 'text/markdown'}
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/live-record/<section>", methods=["PUT"])
def api_update_live_record(section):
    """
    Update a Live Record section.

    Sections: gps, architecture, lessons, intent
    Mode: APPEND for lessons (accumulates), REPLACE for others (overwrites)
    """
    valid_sections = {'gps', 'architecture', 'lessons', 'intent'}
    if section not in valid_sections:
        return jsonify({
            "status": "error",
            "message": f"Invalid section. Must be one of: {', '.join(valid_sections)}"
        }), 400

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    try:
        from managers.project_memory_manager import update_live_record
        result = update_live_record(section, data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/live-record/<section>", methods=["DELETE"])
def api_clear_live_record_section(section):
    """Clear a specific Live Record section."""
    valid_sections = {'gps', 'architecture', 'lessons', 'intent'}
    if section not in valid_sections:
        return jsonify({
            "status": "error",
            "message": f"Invalid section. Must be one of: {', '.join(valid_sections)}"
        }), 400

    try:
        from managers.project_memory_manager import clear_live_record_section
        result = clear_live_record_section(section)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Active Project API ============

@memory_bp.route("/active-project", methods=["GET"])
def api_get_active_project():
    """Get the active project info including connected server for hooks.

    Returns:
        - active_id: The current project ID
        - working_dir: Project root directory
        - connected_server: Server info with port (if active)
        - display_name: Human readable project name
    """
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory
        from pathlib import Path
        import json

        # Load active project info
        active_project_file = Path(__file__).parent.parent.parent / 'data' / 'active_project.json'
        if active_project_file.exists():
            with open(active_project_file, 'r', encoding='utf-8') as f:
                active_info = json.load(f)
        else:
            active_info = {}

        project_id = active_info.get('active_id') or get_active_project_id()

        if not project_id:
            return jsonify({
                "active_id": None,
                "working_dir": None,
                "connected_server": None,
                "display_name": None
            })

        # Get full project memory for connected_server info
        memory = load_project_memory(project_id)

        result = {
            "active_id": project_id,
            "working_dir": active_info.get('working_dir') or (
                memory.get('project_info', {}).get('working_dir') if memory else None
            ),
            "display_name": active_info.get('display_name') or (
                memory.get('project_info', {}).get('name') if memory else None
            ),
            "connected_server": memory.get('connected_server') if memory else None
        }

        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
