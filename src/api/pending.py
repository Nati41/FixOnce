"""
Pending Memories API endpoints for Memory Review MVP.

DATA INTEGRITY GUARANTEES:
1. Items are saved to their STORED project_id, not the active dashboard project
2. Only successfully saved items are removed from pending queue
3. Partial failures are reported (GLOBAL success + LOCAL failure)
4. Unchecked items remain in queue after approval

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
    """
    Get pending memories for review.

    Returns error information if queue is corrupted.
    """
    try:
        from core.pending_memories import get_pending_safe

        data, error = get_pending_safe()

        response = {
            "status": "ok" if not error else "warning",
            "pending": data.get("pending", []),
            "next_task": data.get("next_task", ""),
            "count": len(data.get("pending", [])),
        }

        if error:
            response["warning"] = error

        return jsonify(response)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@pending_bp.route('/api/pending/approve', methods=['POST'])
def approve_pending():
    """
    Approve selected pending items and save to durable memory.

    CRITICAL DATA INTEGRITY:
    1. Items are saved to their STORED project_id (not active dashboard project)
    2. Only successfully saved items are removed from pending
    3. Unchecked items remain in queue
    4. Partial failures (GLOBAL ok, LOCAL failed) are reported

    Request body:
    {
        "approved_ids": ["pending_abc123", "pending_def456"],  // item IDs to approve
        "next_task": "edited next task text",
        "custom_memory": "optional custom note to add"
    }

    Legacy support (indices):
    {
        "approved_indices": [0, 1, 2],  // indices of items (deprecated)
    }

    Response:
    {
        "status": "ok" | "partial" | "error",
        "saved": {"decisions": 1, "avoid": 0, ...},
        "removed_ids": ["pending_abc123", ...],
        "kept_ids": ["pending_xyz789", ...],  // items that failed to save
        "projects_saved": ["ProjectA_123", ...],
        "local_sync_failed": false,
        "warnings": [...]
    }
    """
    try:
        from core.pending_memories import (
            get_pending,
            extract_approved_by_ids,
            remove_items_by_ids,
        )
        from managers.multi_project_manager import (
            get_active_project_id,
            load_project_memory,
            save_project_memory_with_status,
        )
        from datetime import datetime

        data = request.get_json() or {}
        approved_ids = data.get("approved_ids", [])
        approved_indices = data.get("approved_indices", [])  # Legacy support
        next_task = data.get("next_task", "")
        custom_memory = data.get("custom_memory", "")

        # Legacy: convert indices to IDs
        if approved_indices and not approved_ids:
            pending_data = get_pending()
            pending_items = pending_data.get("pending", [])
            for idx in approved_indices:
                if 0 <= idx < len(pending_items):
                    item_id = pending_items[idx].get("id")
                    if item_id:
                        approved_ids.append(item_id)

        if not approved_ids:
            return jsonify({
                "status": "ok",
                "saved": {"decisions": 0, "avoid": 0, "solutions": 0, "custom": 0},
                "message": "No items to approve"
            })

        # Extract items grouped by project_id
        extracted = extract_approved_by_ids(
            approved_ids=approved_ids,
            next_task=next_task,
            custom_memory=custom_memory,
        )

        by_project = extracted.get("by_project", {})
        attribution = _get_attribution()

        saved_counts = {"decisions": 0, "avoid": 0, "solutions": 0, "custom": 0}
        removed_ids = []
        kept_ids = []
        projects_saved = []
        warnings = []
        local_sync_failed = False

        # Get fallback project for items without project_id
        fallback_project_id = get_active_project_id()

        # Save each project's items to THEIR project
        for project_id, items in by_project.items():
            # Handle unknown project (use fallback)
            actual_project_id = project_id if project_id != "_unknown_" else fallback_project_id

            if not actual_project_id:
                warnings.append(f"No project_id for {len(items)} items and no active project")
                for item_list in items.values():
                    for item in item_list:
                        kept_ids.append(item.get("id"))
                continue

            # Load project memory
            memory = load_project_memory(actual_project_id)
            if not memory:
                memory = {}

            # Collect item IDs for this project (for removal tracking)
            project_item_ids = []

            # Add decisions
            if not memory.get("decisions"):
                memory["decisions"] = []
            for item in items.get("decisions", []):
                memory["decisions"].append({
                    "decision": item.get("text", ""),
                    "reason": item.get("reason", ""),
                    "superseded": False,
                    "timestamp": item.get("timestamp") or item.get("created_at"),
                    **attribution,
                })
                saved_counts["decisions"] += 1
                if item.get("id"):
                    project_item_ids.append(item["id"])

            # Add avoid patterns
            if not memory.get("avoid"):
                memory["avoid"] = []
            for item in items.get("avoid", []):
                memory["avoid"].append({
                    "what": item.get("text", ""),
                    "reason": item.get("reason", ""),
                    "timestamp": item.get("timestamp") or item.get("created_at"),
                    **attribution,
                })
                saved_counts["avoid"] += 1
                if item.get("id"):
                    project_item_ids.append(item["id"])

            # Add solutions - WITH VALIDATION
            if not memory.get("debug_sessions"):
                memory["debug_sessions"] = []
            from core.solution_validator import validate_solution_record
            for item in items.get("solutions", []):
                # Build record for validation
                solution_record = {
                    "problem": item.get("problem", ""),
                    "solution": item.get("solution", ""),
                    "files_changed": item.get("files", []),
                    "importance": "high",
                    "timestamp": item.get("timestamp") or item.get("created_at"),
                    **attribution,
                }
                # Validate before persisting
                validation = validate_solution_record(solution_record)
                if validation.valid:
                    memory["debug_sessions"].append(validation.record)
                    saved_counts["solutions"] += 1
                    if item.get("id"):
                        project_item_ids.append(item["id"])
                else:
                    # REJECT invalid records - do not silently accept
                    warnings.append(
                        f"Solution rejected (invalid content): {validation.errors}"
                    )
                    if item.get("id"):
                        kept_ids.append(item["id"])

            # Add custom/notes
            if items.get("custom"):
                if not memory.get("live_record"):
                    memory["live_record"] = {}
                if not memory["live_record"].get("lessons"):
                    memory["live_record"]["lessons"] = {}
                if not memory["live_record"]["lessons"].get("insights"):
                    memory["live_record"]["lessons"]["insights"] = []
                for item in items.get("custom", []):
                    memory["live_record"]["lessons"]["insights"].append({
                        "text": item.get("text", ""),
                        "importance": "medium",
                        "timestamp": item.get("timestamp") or item.get("created_at"),
                        **attribution,
                    })
                    saved_counts["custom"] += 1
                    if item.get("id"):
                        project_item_ids.append(item["id"])

            # Update next_task if this is the active project
            if next_task and actual_project_id == fallback_project_id:
                if not memory.get("resume_state"):
                    memory["resume_state"] = {}
                memory["resume_state"]["next_step"] = next_task
                if not memory.get("live_record"):
                    memory["live_record"] = {}
                if not memory["live_record"].get("intent"):
                    memory["live_record"]["intent"] = {}
                memory["live_record"]["intent"]["next_step"] = next_task

            # Save with detailed status
            save_result = save_project_memory_with_status(actual_project_id, memory)

            if save_result.get("global_saved"):
                # GLOBAL succeeded - mark items for removal
                removed_ids.extend(project_item_ids)
                projects_saved.append(actual_project_id)

                if not save_result.get("local_synced"):
                    local_sync_failed = True
                    warnings.append(
                        f"Project {actual_project_id}: saved to GLOBAL but LOCAL sync failed. "
                        f"Error: {save_result.get('error')}"
                    )
            else:
                # GLOBAL failed - keep items in pending
                kept_ids.extend(project_item_ids)
                warnings.append(
                    f"Project {actual_project_id}: save FAILED. "
                    f"Items kept in pending. Error: {save_result.get('error')}"
                )

        # Remove ONLY successfully saved items from pending
        if removed_ids:
            removed_count, not_found = remove_items_by_ids(removed_ids)
            if not_found:
                warnings.append(f"Some item IDs not found during cleanup: {not_found}")

        # Determine overall status
        if not warnings:
            status = "ok"
        elif local_sync_failed and not kept_ids:
            status = "partial"  # GLOBAL ok, LOCAL failed
        elif kept_ids:
            status = "partial"  # Some items failed to save
        else:
            status = "ok"

        return jsonify({
            "status": status,
            "saved": saved_counts,
            "total": sum(saved_counts.values()),
            "removed_ids": removed_ids,
            "kept_ids": kept_ids,
            "projects_saved": projects_saved,
            "next_task_saved": bool(next_task),
            "local_sync_failed": local_sync_failed,
            "warnings": warnings,
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
        "project_id": "ProjectA_123"  (optional, uses active project if not provided)
    }
    """
    try:
        from core.pending_memories import add_custom_memory
        from managers.multi_project_manager import get_active_project_id

        data = request.get_json() or {}
        text = data.get("text", "").strip()
        memory_type = data.get("type", "note")
        project_id = data.get("project_id") or get_active_project_id()

        if not text:
            return jsonify({
                "status": "error",
                "message": "Text is required"
            }), 400

        item = add_custom_memory(
            text=text,
            memory_type=memory_type,
            project_id=project_id,
        )

        return jsonify({
            "status": "ok",
            "item": item,
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@pending_bp.route('/api/pending/clear', methods=['POST'])
def clear_pending_route():
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
