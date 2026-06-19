"""
Core solution recording logic.

This module contains transport-independent business logic for recording bug solutions.
MCP, REST API, CLI, and tests should all call these functions.

Architecture:
- MCP tool (fo_solved) is a thin wrapper over these core functions
- All storage (V1 debug_sessions + V2 knowledge_objects) happens here
- actor/actor_source are explicit parameters, not detected internally
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class SolutionResult:
    """Result of a solution recording operation."""
    success: bool
    solution_id: Optional[str] = None  # V2 object ID if created
    message: str = ""
    is_update: bool = False  # True if existing solution was updated
    similar_files: List[str] = None  # Files that might need same fix

    def __post_init__(self):
        if self.similar_files is None:
            self.similar_files = []


def record_solution(
    project_id: str,
    error_message: str,
    solution: str,
    files_changed: Optional[List[str]] = None,
    actor: str = "unknown",
    actor_source: str = "unknown",
    _memory: Optional[Dict[str, Any]] = None,
    _save_fn: Optional[callable] = None,
) -> SolutionResult:
    """
    Record a bug solution to both V1 (debug_sessions) and V2 (knowledge_objects).

    This is the core business logic - no MCP or transport dependencies.

    Args:
        project_id: The project ID (required)
        error_message: The error that was fixed
        solution: What was done to fix it
        files_changed: List of files modified (optional)
        actor: Who fixed this (e.g., "claude", "user", "dashboard")
        actor_source: How actor was determined (e.g., "mcp_session", "api_header")
        _memory: Optional pre-loaded memory (for testing/MCP integration)
        _save_fn: Optional custom save function (for testing/MCP integration)

    Returns:
        SolutionResult with success status and solution ID
    """
    if not project_id:
        return SolutionResult(
            success=False,
            message="Error: project_id is required"
        )

    if not error_message or not error_message.strip():
        return SolutionResult(
            success=False,
            message="Error: error_message is required"
        )

    if not solution or not solution.strip():
        return SolutionResult(
            success=False,
            message="Error: solution is required"
        )

    files_list = files_changed or []

    # Load project memory (V1) - use provided memory or load fresh
    if _memory is not None:
        memory = _memory
        save_fn = _save_fn
    else:
        try:
            from managers.multi_project_manager import load_project_memory, save_project_memory
            memory = load_project_memory(project_id)
            save_fn = lambda pid, mem: save_project_memory(pid, mem)
        except Exception as e:
            return SolutionResult(
                success=False,
                message=f"Error loading project memory: {e}"
            )

    # Initialize debug_sessions if needed
    if 'debug_sessions' not in memory:
        memory['debug_sessions'] = []

    # Create solution record
    timestamp = datetime.now()
    solution_id = f"fix_{timestamp.strftime('%Y%m%d_%H%M%S')}"

    solution_record = {
        "id": solution_id,
        "problem": error_message[:200],
        "root_cause": "",
        "solution": solution,
        "lesson_learned": "",
        "symptoms": [error_message[:100]],
        "files_changed": files_list,
        "resolved_at": timestamp.isoformat(),
        "importance": "high",
        "reuse_count": 0,
        "actor": actor,
        "actor_source": actor_source,
    }

    # Check for duplicate (same error already solved)
    error_lower = error_message.lower()[:100]
    for existing in memory['debug_sessions']:
        existing_problem = existing.get('problem', '').lower()[:100]
        if error_lower in existing_problem or existing_problem in error_lower:
            # Update reuse_count instead of creating duplicate
            existing['reuse_count'] = existing.get('reuse_count', 0) + 1
            existing['solution'] = solution
            existing['files_changed'] = files_list or existing.get('files_changed', [])
            existing.setdefault("actor", actor)
            existing.setdefault("actor_source", actor_source)

            # Save V1
            try:
                if save_fn:
                    save_fn(project_id, memory)
                else:
                    from managers.multi_project_manager import save_project_memory
                    save_project_memory(project_id, memory)
            except Exception as e:
                return SolutionResult(
                    success=False,
                    message=f"Error saving project memory: {e}"
                )

            return SolutionResult(
                success=True,
                solution_id=existing.get('id'),
                message="Solution updated.",
                is_update=True,
            )

    # Add new solution
    memory['debug_sessions'].append(solution_record)

    # Save V1
    try:
        if save_fn:
            save_fn(project_id, memory)
        else:
            from managers.multi_project_manager import save_project_memory
            save_project_memory(project_id, memory)
    except Exception as e:
        return SolutionResult(
            success=False,
            message=f"Error saving project memory: {e}"
        )

    # Save to semantic engine for auto-apply matching (non-blocking)
    try:
        from core.semantic_engine import get_engine
        from config import PERSONAL_DB_PATH
        engine = get_engine(PERSONAL_DB_PATH)
        engine.save_solution(error_message, solution)
    except Exception:
        pass  # Semantic engine is optional

    # Index to project semantic (non-blocking)
    try:
        from core.project_semantic import index_error
        full_text = f"Error: {error_message}. Solution: {solution}"
        index_error(project_id, full_text, {
            "error": error_message,
            "solution": solution,
            "files": files_list,
        })
    except Exception:
        pass  # Project semantic is optional

    # Create V2 knowledge object
    v2_id = None
    try:
        from core.knowledge_objects import create_object
        obj = create_object(
            project_id=project_id,
            obj_type="bug",
            text=f"Error: {error_message}",
            reason=f"Solution: {solution}",
            actor=actor,
            actor_source=actor_source,
            links={"files": files_list} if files_list else {},
        )
        v2_id = obj.id
    except Exception:
        pass  # V2 creation is non-blocking

    return SolutionResult(
        success=True,
        solution_id=v2_id or solution_id,
        message="Solution saved.",
        is_update=False,
    )
