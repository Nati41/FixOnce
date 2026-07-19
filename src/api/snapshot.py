"""
Snapshot API - Dashboard endpoint using unified project snapshot.

This endpoint uses the SAME get_project_snapshot() function as fo_init,
ensuring Dashboard and AI agents always see the same project state.
"""

from flask import Blueprint, jsonify, request
from typing import Optional, Tuple

snapshot_bp = Blueprint('snapshot', __name__)


def _resolve_project_and_working_dir(project_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Resolve project_id and working_dir.

    Returns:
        (project_id, working_dir, error_message)
    """
    # Resolve project_id if not provided
    if not project_id:
        try:
            from managers.multi_project_manager import get_active_project_id
            project_id = get_active_project_id()
        except Exception:
            pass

    if not project_id:
        return None, None, "No project_id provided and no active project"

    # Resolve working_dir
    working_dir = None

    # Try 1: From project file -> project_info.working_dir
    try:
        from core.project_context import ProjectContext
        import json
        project_file = ProjectContext.get_project_file(project_id)
        if project_file.exists():
            with open(project_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            project_info = data.get("project_info", {})
            working_dir = project_info.get("working_dir")
    except Exception:
        pass

    # Try 2: From active_project.json
    if not working_dir:
        try:
            from pathlib import Path
            active_file = Path.home() / ".fixonce" / "active_project.json"
            if active_file.exists():
                import json
                with open(active_file, 'r', encoding='utf-8') as f:
                    active_data = json.load(f)
                if active_data.get("active_id") == project_id:
                    working_dir = active_data.get("working_dir")
        except Exception:
            pass

    if not working_dir:
        return project_id, None, f"Working directory not found for project {project_id}"

    return project_id, working_dir, None


@snapshot_bp.route('/api/snapshot', methods=['GET'])
def get_snapshot():
    """
    Get unified project snapshot for dashboard.

    Uses the SAME get_project_snapshot() function as fo_init.
    This is the proof that Dashboard and fo_init share a single source.

    Query params:
        project_id: Optional project ID (uses active project if not provided)

    Returns:
        JSON with full snapshot data
    """
    from core.project_snapshot import get_project_snapshot, render_snapshot_for_dashboard

    project_id = request.args.get('project_id')
    project_id, working_dir, error = _resolve_project_and_working_dir(project_id)

    if error:
        status = 400 if "No project_id" in error else 404
        return jsonify({"error": error}), status

    # Get snapshot using the SAME function as fo_init
    snapshot = get_project_snapshot(project_id, working_dir)

    # Return as dashboard-formatted JSON
    return jsonify(render_snapshot_for_dashboard(snapshot))


@snapshot_bp.route('/api/snapshot/agent-opener', methods=['GET'])
def get_agent_opener_preview():
    """
    Preview what the AI agent opener would look like.

    This is for debugging/verification only - shows the same data
    that fo_init would use, formatted as it would appear to the agent.

    Note: This does NOT include error gates, priorities, or reorientation
    logic - those are handled in fo_init. This only shows the core
    snapshot data formatted as text.
    """
    from core.project_snapshot import get_project_snapshot

    project_id = request.args.get('project_id')
    project_id, working_dir, error = _resolve_project_and_working_dir(project_id)

    if error:
        status = 400 if "No project_id" in error else 404
        return jsonify({"error": error}), status

    snapshot = get_project_snapshot(project_id, working_dir)

    # Format as simple text preview (not full fo_init output)
    lines = [f"🧠 Back to {snapshot.project_name}", ""]

    if snapshot.goal:
        lines.append(snapshot.goal)
        if snapshot.work_area:
            lines.append(f"Area: {snapshot.work_area}")
        lines.append("")

    if snapshot.last:
        lines.append(f"Last:\n{snapshot.last}.")
    if snapshot.next:
        lines.append(f"Next:\n{snapshot.next}.")

    if snapshot.last or snapshot.next:
        lines.append("")

    lines.append("Ready.")

    opener_text = "\n".join(lines)

    return jsonify({
        "opener": opener_text,
        "snapshot": snapshot.to_dict(),
    })
