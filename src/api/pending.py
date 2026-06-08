"""
Pending Memories API endpoints for Memory Review MVP.

Provides:
- GET /api/pending - Get pending memories and next_task
- POST /api/pending/approve - Approve selected items and save to durable memory
- POST /api/pending/add - Add a custom memory item
"""

from flask import Blueprint, jsonify, request
from typing import Dict, Any, List

pending_bp = Blueprint('pending', __name__)


def _get_attribution() -> Dict[str, Any]:
    """Build attribution dict for durable writes."""
    return {
        "actor": "user",
        "actor_source": "dashboard",
        "actor_confidence": 1.0,
        "session_id": "dashboard-review",
        "tool_name": "memory_review",
    }


@pending_bp.route('/api/pending', methods=['GET'])
def get_pending():
    """Get pending memories for review."""
    try:
        from core.pending_memories import get_pending
        data = get_pending()
        return jsonify({
            "status": "ok",
            "pending": data.get("pending", []),
            "next_task": data.get("next_task", ""),
            "count": len(data.get("pending", [])),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@pending_bp.route('/api/pending/approve', methods=['POST'])
def approve_pending():
    """
    Approve selected pending items and save to durable memory.

    Request body:
    {
        "approved_indices": [0, 1, 2],  // indices of items to approve
        "next_task": "edited next task text",
        "custom_memory": "optional custom note to add"
    }
    """
    try:
        from core.pending_memories import approve_selected
        from core.durable_memory import durable_memory_write
        from config import USER_DATA_DIR
        from managers.multi_project_manager import get_active_project_id

        data = request.get_json() or {}
        approved_indices = data.get("approved_indices", [])
        next_task = data.get("next_task", "")
        custom_memory = data.get("custom_memory", "")

        approved = approve_selected(
            approved_indices=approved_indices,
            next_task=next_task,
            custom_memory=custom_memory,
        )

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({
                "status": "error",
                "message": "No active project"
            }), 400

        project_memory_path = USER_DATA_DIR / "projects_v2" / f"{project_id}.json"
        saved_counts = {"decisions": 0, "avoid": 0, "solutions": 0, "custom": 0}
        attribution = _get_attribution()

        def mutator(memory: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal saved_counts

            if not memory.get("decisions"):
                memory["decisions"] = []
            for item in approved.get("decisions", []):
                memory["decisions"].append({
                    "decision": item.get("text", ""),
                    "reason": item.get("reason", ""),
                    "superseded": False,
                    **attribution,
                })
                saved_counts["decisions"] += 1

            if not memory.get("avoid"):
                memory["avoid"] = []
            for item in approved.get("avoid", []):
                memory["avoid"].append({
                    "what": item.get("text", ""),
                    "reason": item.get("reason", ""),
                    **attribution,
                })
                saved_counts["avoid"] += 1

            if not memory.get("debug_sessions"):
                memory["debug_sessions"] = []
            for item in approved.get("solutions", []):
                memory["debug_sessions"].append({
                    "problem": item.get("problem", ""),
                    "solution": item.get("solution", ""),
                    "files_changed": item.get("files", []),
                    "importance": "high",
                    **attribution,
                })
                saved_counts["solutions"] += 1

            if approved.get("custom"):
                if not memory.get("live_record"):
                    memory["live_record"] = {}
                if not memory["live_record"].get("lessons"):
                    memory["live_record"]["lessons"] = {}
                if not memory["live_record"]["lessons"].get("insights"):
                    memory["live_record"]["lessons"]["insights"] = []
                for item in approved.get("custom", []):
                    memory["live_record"]["lessons"]["insights"].append({
                        "text": item.get("text", ""),
                        "importance": "medium",
                        **attribution,
                    })
                    saved_counts["custom"] += 1

            if next_task:
                if not memory.get("resume_state"):
                    memory["resume_state"] = {}
                memory["resume_state"]["next_step"] = next_task
                if not memory.get("live_record"):
                    memory["live_record"] = {}
                if not memory["live_record"].get("intent"):
                    memory["live_record"]["intent"] = {}
                memory["live_record"]["intent"]["next_step"] = next_task

            return memory

        durable_memory_write(
            project_memory_path,
            mutator=mutator,
            attribution=attribution,
            tool_name="memory_review",
        )

        return jsonify({
            "status": "ok",
            "saved": saved_counts,
            "next_task_saved": bool(next_task),
            "total": sum(saved_counts.values()),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@pending_bp.route('/api/pending/add', methods=['POST'])
def add_custom():
    """
    Add a custom memory item to the pending queue.

    Request body:
    {
        "text": "memory text",
        "type": "decision" | "avoid" | "note"  (optional, default: note)
    }
    """
    try:
        from core.pending_memories import add_custom_memory

        data = request.get_json() or {}
        text = data.get("text", "").strip()
        memory_type = data.get("type", "note")

        if not text:
            return jsonify({
                "status": "error",
                "message": "Text is required"
            }), 400

        item = add_custom_memory(text, memory_type)

        return jsonify({
            "status": "ok",
            "item": item,
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@pending_bp.route('/api/pending/clear', methods=['POST'])
def clear_pending():
    """Clear all pending items without saving."""
    try:
        from core.pending_memories import clear_pending
        count = clear_pending()
        return jsonify({
            "status": "ok",
            "cleared": count,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
