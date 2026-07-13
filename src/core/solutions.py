"""
Core solution recording logic.

This module contains transport-independent business logic for recording bug solutions.
MCP, REST API, CLI, and tests should all call these functions.

Architecture:
- MCP tool (fo_solved) is a thin wrapper over these core functions
- All storage (V1 debug_sessions + V2 knowledge_objects) happens here
- actor/actor_source are explicit parameters, not detected internally
- Pre-save review checks for potential conflicts before saving
- Resolution actions require a valid pending review (no direct bypass)
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
import hashlib


# Pending review expiration (1 hour)
PENDING_REVIEW_EXPIRY_SECONDS = 3600


@dataclass
class SolutionResult:
    """Result of a solution recording operation."""
    success: bool
    solution_id: Optional[str] = None  # V2 object ID if created
    message: str = ""
    is_update: bool = False  # True if existing solution was updated
    similar_files: List[str] = None  # Files that might need same fix
    requires_review: bool = False  # True if review needed before save
    review_result: Optional[Dict[str, Any]] = None  # Review details if requires_review

    def __post_init__(self):
        if self.similar_files is None:
            self.similar_files = []


def _normalize_text(text: str) -> str:
    """Normalize text for fingerprinting."""
    import re
    text = str(text or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text[:500]


def _solution_fingerprint(problem: str, solution: str) -> str:
    """Generate fingerprint for a solution (problem + solution text)."""
    payload = f"{_normalize_text(problem)}|{_normalize_text(solution)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _generate_review_id() -> str:
    """Generate unique pending review ID."""
    import uuid
    return f"solrev_{uuid.uuid4().hex[:16]}"


def _create_pending_solution_review(
    memory: Dict[str, Any],
    project_id: str,
    relationship: str,
    target_solution: Dict[str, Any],
    proposed_problem: str,
    proposed_solution: str,
    allowed_actions: List[str],
    actor: str = "unknown",
    actor_source: str = "unknown",
) -> Dict[str, Any]:
    """
    Create a pending solution review record in project memory.

    Returns the created review record with its ID.
    """
    try:
        from core.decision_review import solution_id_for
        target_id = solution_id_for(target_solution)
    except ImportError:
        target_id = target_solution.get("id", "")

    now = datetime.now()
    expires_at = now + timedelta(seconds=PENDING_REVIEW_EXPIRY_SECONDS)

    review = {
        "id": _generate_review_id(),
        "project_id": project_id,
        "relationship": relationship,
        "target_solution_id": target_id,
        "target_fingerprint": _solution_fingerprint(
            target_solution.get("problem", ""),
            target_solution.get("solution", ""),
        ),
        "proposed_problem": proposed_problem[:200],
        "proposed_solution": proposed_solution[:500],
        "proposed_fingerprint": _solution_fingerprint(proposed_problem, proposed_solution),
        "allowed_actions": allowed_actions,
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "actor": actor,
        "actor_source": actor_source,
    }

    if "pending_solution_reviews" not in memory:
        memory["pending_solution_reviews"] = []

    memory["pending_solution_reviews"].append(review)
    return review


def _find_pending_solution_review(
    memory: Dict[str, Any],
    review_id: str,
) -> Optional[Dict[str, Any]]:
    """Find a pending solution review by ID."""
    if not review_id:
        return None
    for review in memory.get("pending_solution_reviews", []):
        if review.get("id") == review_id:
            return review
    return None


def _validate_pending_solution_review(
    review: Dict[str, Any],
    project_id: str,
    resolution_action: str,
    resolution_target_id: str,
    proposed_problem: str,
    proposed_solution: str,
    target_solution: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    """
    Validate a pending solution review before allowing resolution.

    Returns (is_valid, error_message).
    """
    # 1. Review must exist
    if not review:
        return False, "Error: pending review not found. Call fo_solved without resolution first."

    # 2. Status must be pending (or consumed for idempotent retry)
    status = review.get("status", "")
    if status == "consumed":
        # Idempotent retry if same action, otherwise reject
        if review.get("resolution_action") == resolution_action:
            return True, "idempotent"  # Signal to caller for early return
        return False, "Error: review already consumed with different action."
    if status == "cancelled":
        return False, "Error: review was cancelled."
    if status == "expired":
        return False, "Error: review has expired. Call fo_solved again to get a new review."
    if status != "pending":
        return False, f"Error: review has invalid status '{status}'."

    # 3. Not expired
    expires_at = review.get("expires_at", "")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at)
            if datetime.now() > expiry:
                return False, "Error: review has expired. Call fo_solved again to get a new review."
        except ValueError:
            pass

    # 4. Project must match
    if review.get("project_id") != project_id:
        return False, "Error: review belongs to a different project."

    # 5. Relationship must support the action
    relationship = review.get("relationship", "")
    if resolution_action == "supersede_existing":
        if relationship != "supersedes":
            return False, f"Error: review relationship '{relationship}' does not support supersede_existing."

    # 6. Action must be allowed
    allowed = review.get("allowed_actions", [])
    if resolution_action not in allowed:
        return False, f"Error: action '{resolution_action}' not allowed. Allowed: {allowed}"

    # 7. Target must match
    if review.get("target_solution_id") != resolution_target_id:
        return False, "Error: resolution target does not match reviewed target."

    # 8. Proposed text must match
    proposed_fp = _solution_fingerprint(proposed_problem, proposed_solution)
    if review.get("proposed_fingerprint") != proposed_fp:
        return False, "Error: proposed solution text does not match reviewed proposal."

    # 9. Target hasn't changed (staleness check)
    if target_solution:
        current_fp = _solution_fingerprint(
            target_solution.get("problem", ""),
            target_solution.get("solution", ""),
        )
        if review.get("target_fingerprint") != current_fp:
            return False, "Error: target solution has changed since review. Get a new review."

    return True, ""


def _consume_pending_solution_review(
    memory: Dict[str, Any],
    review_id: str,
    action: str,
) -> None:
    """Mark a pending solution review as consumed."""
    for review in memory.get("pending_solution_reviews", []):
        if review.get("id") == review_id:
            review["status"] = "consumed" if action != "cancel" else "cancelled"
            review["consumed_at"] = datetime.now().isoformat()
            review["resolution_action"] = action
            break


def _find_solution_by_review_id(
    memory: Dict[str, Any],
    target_id: str,
) -> Optional[Dict[str, Any]]:
    """Find an active solution by stored ID or generated review ID."""
    if not target_id:
        return None
    try:
        from core.decision_review import solution_id_for
    except ImportError:
        solution_id_for = None

    normalized_target = target_id.lower()
    for solution in memory.get("debug_sessions", []):
        if not isinstance(solution, dict) or solution.get("superseded"):
            continue
        stored_id = str(solution.get("id", ""))
        generated_id = solution_id_for(solution) if solution_id_for else ""
        problem = str(solution.get("problem", ""))
        # Match by stored ID, generated ID, or problem text substring
        if stored_id == target_id or generated_id == target_id:
            return solution
        if normalized_target and normalized_target in problem.lower():
            return solution
    return None


def record_solution(
    project_id: str,
    error_message: str,
    solution: str,
    files_changed: Optional[List[str]] = None,
    actor: str = "unknown",
    actor_source: str = "unknown",
    resolution_action: str = "",
    resolution_target_id: str = "",
    resolution_review_id: str = "",
    _memory: Optional[Dict[str, Any]] = None,
    _save_fn: Optional[callable] = None,
) -> SolutionResult:
    """
    Record a bug solution to both V1 (debug_sessions) and V2 (knowledge_objects).

    This is the core business logic - no MCP or transport dependencies.

    Pre-save review: Before saving, checks for related/conflicting solutions.
    If a potential conflict is found, returns requires_review=True with a review ID.
    Caller must then call again with resolution_action AND resolution_review_id.

    Security: Resolution actions require a valid pending review. Direct bypass
    (providing resolution_action without a valid review) is rejected.

    Args:
        project_id: The project ID (required)
        error_message: The error that was fixed
        solution: What was done to fix it
        files_changed: List of files modified (optional)
        actor: Who fixed this (e.g., "claude", "user", "dashboard")
        actor_source: How actor was determined (e.g., "mcp_session", "api_header")
        resolution_action: Action to resolve a review:
            - supersede_existing: Save and mark existing as superseded
            - cancel: Don't save
        resolution_target_id: ID of existing solution for resolution actions
        resolution_review_id: ID of pending review (required for resolution_action)
        _memory: Optional pre-loaded memory (for testing/MCP integration)
        _save_fn: Optional custom save function (for testing/MCP integration)

    Returns:
        SolutionResult with success status and solution ID.
        If requires_review=True, includes review_id for secure resolution.
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

    # Handle resolution actions (requires valid pending review)
    if resolution_action:
        try:
            from core.decision_review import ResolutionAction, solution_id_for

            action = ResolutionAction(resolution_action)

            # SECURITY: Resolution requires a valid pending review
            if not resolution_review_id:
                return SolutionResult(
                    success=False,
                    message="Error: resolution_review_id is required. Call fo_solved without resolution first to get a review.",
                )

            # Find and validate the pending review
            pending_review = _find_pending_solution_review(memory, resolution_review_id)
            target_solution = _find_solution_by_review_id(memory, resolution_target_id)
            target_id = solution_id_for(target_solution) if target_solution else resolution_target_id

            is_valid, error_msg = _validate_pending_solution_review(
                review=pending_review,
                project_id=project_id,
                resolution_action=resolution_action,
                resolution_target_id=target_id,
                proposed_problem=error_message,
                proposed_solution=solution,
                target_solution=target_solution,
            )

            # Handle idempotent retry (same review, same action)
            if is_valid and error_msg == "idempotent":
                return SolutionResult(
                    success=True,
                    message="Resolution already applied (idempotent retry).",
                    is_update=True,
                )

            if not is_valid:
                return SolutionResult(
                    success=False,
                    message=error_msg,
                )

            # Consume the review before making changes
            _consume_pending_solution_review(memory, resolution_review_id, resolution_action)

            if action == ResolutionAction.CANCEL:
                # Save memory to persist the cancelled review state
                try:
                    if save_fn:
                        save_fn(project_id, memory)
                except Exception:
                    pass
                return SolutionResult(
                    success=False,
                    message="Solution cancelled by user",
                )

            if action == ResolutionAction.SUPERSEDE_EXISTING:
                if not target_solution:
                    return SolutionResult(
                        success=False,
                        message=f"Error: target solution '{resolution_target_id}' not found for supersede resolution",
                    )
                # Mark existing solution as superseded
                target_solution["superseded"] = True
                target_solution["superseded_at"] = datetime.now().isoformat()
                target_solution["superseded_by_problem"] = error_message[:200]
                target_solution["superseded_by_solution"] = solution
                target_solution["superseded_by_actor"] = actor
                target_solution["superseded_by_source"] = actor_source
                # Fall through to save the new solution

            else:
                # Only SUPERSEDE_EXISTING and CANCEL are supported for solutions
                return SolutionResult(
                    success=False,
                    message=f"Error: resolution action '{resolution_action}' not supported for solutions",
                )

        except (ImportError, ValueError) as e:
            return SolutionResult(
                success=False,
                message=f"Error processing resolution action: {e}",
            )

    # Review against existing solutions for relationships that require interruption
    # Only SUPERSEDES, EXCEPTION_TO, POTENTIAL_CONFLICT interrupt - others are silent
    # Skip review if resolution_action is provided (review already happened)
    if not resolution_action:
        try:
            from core.decision_review import review_solution, RelationshipType

            # Build solutions list in the format review_solution expects
            solutions_for_review = [
                {
                    "id": s.get("id", ""),
                    "problem": s.get("problem", ""),
                    "solution": s.get("solution", ""),
                    "status": "active" if not s.get("superseded") else "superseded",
                    "superseded": s.get("superseded", False),
                    "actor": s.get("actor", "unknown"),
                    "actor_source": s.get("actor_source", "unknown"),
                    "timestamp": s.get("resolved_at", ""),
                }
                for s in memory.get('debug_sessions', [])
            ]

            review = review_solution(
                error_message,
                solution,
                {"solutions": solutions_for_review},
            )

            if review.requires_review and review.primary_candidate:
                rel = review.primary_candidate.relationship
                # Only interrupt for these three relationships
                if rel in (RelationshipType.SUPERSEDES,
                           RelationshipType.EXCEPTION_TO,
                           RelationshipType.POTENTIAL_CONFLICT):
                    # Find the target solution to get its full data
                    target_id = review.primary_candidate.id
                    target_solution = _find_solution_by_review_id(memory, target_id)

                    # Create a pending review record for secure resolution
                    pending_review = _create_pending_solution_review(
                        memory=memory,
                        project_id=project_id,
                        relationship=rel.value,
                        target_solution=target_solution or {"id": target_id, "problem": "", "solution": ""},
                        proposed_problem=error_message,
                        proposed_solution=solution,
                        allowed_actions=[a.value if hasattr(a, 'value') else a for a in review.allowed_actions],
                        actor=actor,
                        actor_source=actor_source,
                    )

                    # Save memory to persist the pending review
                    try:
                        if save_fn:
                            save_fn(project_id, memory)
                    except Exception:
                        pass  # Don't fail the review if save fails

                    # Include review ID in the result
                    review_dict = review.to_dict()
                    review_dict["review_id"] = pending_review["id"]
                    review_dict["expires_at"] = pending_review["expires_at"]

                    return SolutionResult(
                        success=False,
                        requires_review=True,
                        message=(
                            f"Solution review required.\n"
                            f"Relationship: {rel.value}\n"
                            f"Existing: {review.primary_candidate.text[:80]}...\n"
                            f"Reason: {review.primary_candidate.explanation}\n"
                            f"Review ID: {pending_review['id']}"
                        ),
                        review_result=review_dict,
                    )
            # SAME, EXTENDS, UNRELATED, UNDETERMINED - fall through to existing logic
        except ImportError:
            pass  # Review module not available, continue without review

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
    # Skip duplicate check when resolution_action is provided - we're intentionally creating
    # a new solution that supersedes the old one
    if not resolution_action:
        error_lower = error_message.lower()[:100]
        for existing in memory['debug_sessions']:
            existing_problem = existing.get('problem', '').lower()[:100]
            # Skip empty problems - they match everything via substring
            if not existing_problem.strip():
                continue
            # Require meaningful overlap: exact match OR substantial (20+ char) substring
            is_duplicate = (
                error_lower == existing_problem or
                (len(error_lower) >= 20 and error_lower in existing_problem) or
                (len(existing_problem) >= 20 and existing_problem in error_lower)
            )
            if not is_duplicate:
                continue
            if is_duplicate:
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
