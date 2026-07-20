"""
Knowledge V2 API endpoints.

Provides:
- GET /api/knowledge/pending - Get pending knowledge objects for dashboard
- GET /api/knowledge/stats - Get knowledge object counts
"""

from flask import Blueprint, jsonify, request

knowledge_bp = Blueprint('knowledge', __name__)


@knowledge_bp.route('/api/knowledge/pending', methods=['GET'])
def get_pending_knowledge():
    """
    Get pending knowledge objects.

    Args (query params):
        project_id: Optional. If provided, use this project.
                   Otherwise, fall back to active/selected project.

    Returns objects that have been created but not yet committed.
    This is a preview for the future fo_commit feature.
    """
    try:
        from core.knowledge_objects import get_pending_objects, get_pending_changes, generate_commit_message

        # Priority: request arg > active project
        project_id = request.args.get("project_id")

        if not project_id:
            from managers.multi_project_manager import get_active_project
            active = get_active_project()
            if active:
                project_id = active.get("project_id") or active.get("active_id")

        if not project_id:
            return jsonify({
                "status": "no_project",
                "message": "No project ID",
                "pending": {},
                "counts": {},
            })

        # Get pending object IDs
        pending_ids = get_pending_changes(project_id)

        # Get full objects
        pending_objects = get_pending_objects(project_id)

        # Count by type
        counts = {
            "decisions": len(pending_ids.get("decisions", [])),
            "bugs": len(pending_ids.get("bugs", [])),
            "avoids": len(pending_ids.get("avoids", [])),
            "questions": len(pending_ids.get("questions", [])),
        }
        total = sum(counts.values())

        # Generate suggested commit message if there's pending content
        suggested_message = ""
        if total > 0:
            suggested_message = generate_commit_message(project_id)

        return jsonify({
            "status": "ok",
            "project_id": project_id,
            "pending": pending_objects,
            "counts": counts,
            "total": total,
            "suggested_message": suggested_message,
        })

    except ImportError as e:
        return jsonify({
            "status": "error",
            "message": f"Module not available: {e}",
            "pending": {},
            "counts": {},
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "pending": {},
            "counts": {},
        })


@knowledge_bp.route('/api/knowledge/stats', methods=['GET'])
def get_knowledge_stats():
    """
    Get knowledge object statistics.

    Args (query params):
        project_id: Optional. If provided, use this project.
                   Otherwise, fall back to active/selected project.
    """
    try:
        from core.knowledge_objects import get_object_count, get_pending_changes

        # Priority: request arg > active project
        project_id = request.args.get("project_id")

        if not project_id:
            from managers.multi_project_manager import get_active_project
            active = get_active_project()
            if active:
                project_id = active.get("project_id") or active.get("active_id")

        if not project_id:
            return jsonify({
                "status": "no_project",
                "total_objects": 0,
                "pending_count": 0,
            })

        # Get total counts
        counts = get_object_count(project_id)
        total = sum(counts.values())

        # Get pending counts
        pending = get_pending_changes(project_id)
        pending_count = sum(len(v) for v in pending.values())

        return jsonify({
            "status": "ok",
            "project_id": project_id,
            "counts": counts,
            "total_objects": total,
            "pending_count": pending_count,
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "total_objects": 0,
            "pending_count": 0,
        })


@knowledge_bp.route('/api/knowledge/commit/preview', methods=['GET'])
def get_commit_preview():
    """
    Get a preview of what would be committed.

    Returns pending objects and a suggested commit message.
    """
    try:
        from core.knowledge_objects import (
            get_pending_objects,
            get_pending_changes,
            generate_commit_message,
        )

        project_id = request.args.get("project_id")

        if not project_id:
            from managers.multi_project_manager import get_active_project
            active = get_active_project()
            if active:
                project_id = active.get("project_id") or active.get("active_id")

        if not project_id:
            return jsonify({
                "status": "no_project",
                "message": "No project ID",
            })

        pending_ids = get_pending_changes(project_id)
        pending_objects = get_pending_objects(project_id)
        total = sum(len(v) for v in pending_ids.values())

        if total == 0:
            return jsonify({
                "status": "empty",
                "message": "Nothing to commit",
                "total": 0,
            })

        suggested_message = generate_commit_message(project_id)

        return jsonify({
            "status": "ok",
            "project_id": project_id,
            "total": total,
            "pending": pending_objects,
            "suggested_message": suggested_message,
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        })


@knowledge_bp.route('/api/knowledge/commit', methods=['POST'])
def create_knowledge_commit():
    """
    Create a knowledge commit from pending changes.

    Request body:
        message: Commit message (optional, will use generated if missing)

    Returns the created commit.
    """
    try:
        from core.knowledge_objects import create_commit, generate_commit_message

        data = request.get_json() or {}
        project_id = data.get("project_id") or request.args.get("project_id")

        if not project_id:
            from managers.multi_project_manager import get_active_project
            active = get_active_project()
            if active:
                project_id = active.get("project_id") or active.get("active_id")

        if not project_id:
            return jsonify({
                "status": "no_project",
                "message": "No project ID",
            })

        # Get message from request or generate one
        message = data.get("message", "").strip()
        if not message:
            message = generate_commit_message(project_id)

        # Get actor from request or default
        actor = data.get("actor", "dashboard")

        # Create commit
        commit = create_commit(project_id, message, actor)

        if not commit:
            return jsonify({
                "status": "empty",
                "message": "Nothing to commit",
            })

        return jsonify({
            "status": "ok",
            "commit": commit,
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        })


@knowledge_bp.route('/api/knowledge/integrity', methods=['GET'])
def get_integrity_report():
    """
    Generate integrity report for solution records.

    This is READ-ONLY - reports issues but does not modify data.

    Checks:
    - Empty/invalid content (corrupted records)
    - Missing or duplicate IDs
    - Canonical records missing from Project Memory
    - Project Memory records missing from Canonical
    - Superseded records incorrectly counted as active

    Query params:
        project_id: Optional. Uses active project if not provided.

    Returns:
        Detailed integrity report with issues and recommendations.
    """
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory
        from core.committed_knowledge import read_committed_knowledge
        from core.solution_validator import generate_integrity_report

        # Get project
        project_id = request.args.get("project_id")
        if not project_id:
            project_id = get_active_project_id()

        if not project_id:
            return jsonify({
                "status": "no_project",
                "message": "No project ID",
            })

        # Load Project Memory
        memory = load_project_memory(project_id) or {}
        pm_records = memory.get("debug_sessions", [])

        # Get working_dir for committed knowledge
        working_dir = memory.get("project_info", {}).get("working_dir")
        if not working_dir:
            return jsonify({
                "status": "error",
                "message": "No working_dir found for project",
            })

        # Load Committed Knowledge
        ck = read_committed_knowledge(working_dir)
        ck_records = ck.get("solutions", [])

        # Generate report
        report = generate_integrity_report(pm_records, ck_records)
        report["project_id"] = project_id
        report["working_dir"] = working_dir

        # Add status based on issues
        if report["summary"]["error_count"] > 0:
            report["status"] = "issues_found"
        elif report["summary"]["warning_count"] > 0:
            report["status"] = "warnings"
        else:
            report["status"] = "healthy"

        return jsonify(report)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": str(e),
        })


@knowledge_bp.route('/api/knowledge/commits', methods=['GET'])
def list_knowledge_commits():
    """
    List recent knowledge commits.
    """
    try:
        from core.knowledge_objects import list_commits

        project_id = request.args.get("project_id")
        limit = request.args.get("limit", 10, type=int)

        if not project_id:
            from managers.multi_project_manager import get_active_project
            active = get_active_project()
            if active:
                project_id = active.get("project_id") or active.get("active_id")

        if not project_id:
            return jsonify({
                "status": "no_project",
                "commits": [],
            })

        commits = list_commits(project_id, limit)

        return jsonify({
            "status": "ok",
            "project_id": project_id,
            "commits": commits,
            "count": len(commits),
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "commits": [],
        })
