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
    Get pending knowledge objects for the active project.

    Returns objects that have been created but not yet committed.
    This is a preview for the future fo_commit feature.
    """
    try:
        from managers.multi_project_manager import get_active_project
        from core.knowledge_objects import get_pending_objects, get_pending_changes

        active = get_active_project()
        if not active:
            return jsonify({
                "status": "no_project",
                "message": "No active project",
                "pending": {},
                "counts": {},
            })

        project_id = active.get("project_id")
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

        return jsonify({
            "status": "ok",
            "project_id": project_id,
            "pending": pending_objects,
            "counts": counts,
            "total": total,
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
    Get knowledge object statistics for the active project.
    """
    try:
        from managers.multi_project_manager import get_active_project
        from core.knowledge_objects import get_object_count, get_pending_changes

        active = get_active_project()
        if not active:
            return jsonify({
                "status": "no_project",
                "total_objects": 0,
                "pending_count": 0,
            })

        project_id = active.get("project_id")
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
