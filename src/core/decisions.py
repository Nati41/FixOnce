"""
Core decision recording logic.

This module contains transport-independent business logic for recording decisions.
MCP, REST API, CLI, and tests should all call these functions.

Architecture:
- MCP tool (fo_decide) is a thin wrapper over these core functions
- All storage (V1 project_memory.json + V2 knowledge_objects) happens here
- actor/actor_source are explicit parameters, not detected internally
- Pre-save review checks for potential conflicts before saving
"""

from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, field


@dataclass
class DecisionResult:
    """Result of a decision recording operation."""
    success: bool
    decision_id: Optional[str] = None  # V2 object ID if created
    message: str = ""
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    warning: str = ""
    # Review fields (when requires_review=True, decision was not saved)
    requires_review: bool = False
    review_result: Optional[Dict[str, Any]] = None


def _find_decision_by_review_id(
    memory: Dict[str, Any],
    target_id: str,
) -> Optional[Dict[str, Any]]:
    """Find an active decision by stored ID or generated review ID."""
    if not target_id:
        return None
    try:
        from core.decision_review import decision_id_for
    except ImportError:
        decision_id_for = None

    normalized_target = target_id.lower()
    for decision in memory.get("decisions", []):
        if not isinstance(decision, dict) or decision.get("superseded"):
            continue
        stored_id = str(decision.get("id", ""))
        generated_id = decision_id_for(decision) if decision_id_for else ""
        text = str(decision.get("decision", ""))
        if stored_id == target_id or generated_id == target_id:
            return decision
        if normalized_target and normalized_target in text.lower():
            return decision
    return None


def record_decision(
    project_id: str,
    text: str,
    reason: str,
    actor: str = "unknown",
    actor_source: str = "unknown",
    force: bool = False,
    relation: str = "",
    related_decision: str = "",
    skip_review: bool = False,
    resolution_action: str = "",
    resolution_target_id: str = "",
    session_id: str = "",
    _memory: Optional[Dict[str, Any]] = None,
    _save_fn: Optional[callable] = None,
) -> DecisionResult:
    """
    Record a decision to both V1 (project_memory.json) and V2 (knowledge_objects).

    This is the core business logic - no MCP or transport dependencies.

    Pre-save review: Before saving, checks for related/conflicting decisions.
    If a potential conflict is found, returns requires_review=True with resolution options.
    Caller must then call again with resolution_action to complete the save.

    Args:
        project_id: The project ID (required)
        text: The decision text
        reason: Why this decision was made
        actor: Who made this decision (e.g., "claude", "user", "dashboard")
        actor_source: How actor was determined (e.g., "mcp_session", "api_header")
        force: If True, override conflict detection (deprecated, use resolution_action)
        relation: Optional relation ("refines" or "clarifies")
        related_decision: Text of related decision if relation is set
        skip_review: If True, skip pre-save review (for internal calls)
        resolution_action: Action to resolve a review (save_as_exception, save_as_extends, supersede_existing, etc.)
        resolution_target_id: ID of existing decision for resolution actions
        session_id: Session ID for attribution
        _memory: Optional pre-loaded memory (for testing/MCP integration)
        _save_fn: Optional custom save function (for testing/MCP integration)

    Returns:
        DecisionResult with success status, message, and any conflicts.
        If requires_review=True, decision was NOT saved - call again with resolution_action.
    """
    if not project_id:
        return DecisionResult(
            success=False,
            message="Error: project_id is required"
        )

    if not text or not text.strip():
        return DecisionResult(
            success=False,
            message="Error: decision text is required"
        )

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
            return DecisionResult(
                success=False,
                message=f"Error loading project memory: {e}"
            )

    if 'decisions' not in memory:
        memory['decisions'] = []

    # Handle resolution actions (called after review)
    if resolution_action:
        try:
            from core.decision_review import ResolutionAction, decision_id_for
            from core.conflict_lifecycle import resolve_decision_conflicts

            action = ResolutionAction(resolution_action)
            target_decision = _find_decision_by_review_id(memory, resolution_target_id)
            target_text = target_decision.get("decision", "") if target_decision else ""
            target_id = decision_id_for(target_decision) if target_decision else resolution_target_id

            if action == ResolutionAction.CANCEL:
                return DecisionResult(
                    success=False,
                    message="Decision cancelled by user",
                )

            if action == ResolutionAction.ACKNOWLEDGE_EXISTING:
                return DecisionResult(
                    success=True,
                    message="Existing decision acknowledged; duplicate decision was not recorded",
                )

            if action == ResolutionAction.SAVE_AS_EXCEPTION:
                if not target_decision:
                    return DecisionResult(
                        success=False,
                        message="Error: target decision was not found for exception resolution",
                    )
                relation = "exception_to"
                related_decision = target_text

            elif action == ResolutionAction.SAVE_AS_EXTENDS:
                if not target_decision:
                    return DecisionResult(
                        success=False,
                        message="Error: target decision was not found for extends resolution",
                    )
                relation = "extends"
                related_decision = target_text

            elif action == ResolutionAction.SUPERSEDE_EXISTING:
                if not target_decision:
                    return DecisionResult(
                        success=False,
                        message="Error: target decision was not found for supersede resolution",
                    )
                target_decision["superseded"] = True
                target_decision["superseded_at"] = datetime.now().isoformat()
                target_decision["superseded_by"] = text
                target_decision["supersede_reason"] = reason
                target_decision["superseded_by_actor"] = actor
                target_decision["superseded_by_source"] = actor_source

            elif action == ResolutionAction.SAVE_ANYWAY_UNDER_REVIEW:
                if not target_decision:
                    return DecisionResult(
                        success=False,
                        message="Error: target decision was not found for under-review resolution",
                    )

            # Resolve matching legacy conflicts if this resolution came after an old block.
            # Saving under review intentionally leaves one canonical open review.
            if action != ResolutionAction.SAVE_ANYWAY_UNDER_REVIEW:
                resolve_decision_conflicts(
                    memory,
                    status="resolved",
                    action=resolution_action,
                    reason=f"Resolved via {resolution_action}",
                    attribution={
                        "actor": actor,
                        "actor_source": actor_source,
                        "session_id": session_id,
                    },
                    existing_decision_text=target_text,
                )

        except (ImportError, ValueError) as e:
            return DecisionResult(
                success=False,
                message=f"Error processing resolution action: {e}",
            )

    # Policy enforcement - check for conflicts
    warning = ""
    conflicts = []
    try:
        from core.policy_engine import validate_decision as policy_validate

        active_decisions = [d for d in memory['decisions'] if not d.get('superseded')]

        # Get non-negotiables from live_record.vision (correct location)
        live_record = memory.get("live_record", {})
        vision = live_record.get("vision", {})
        non_negotiables = []
        nn_items = vision.get("non_negotiables", [])
        if isinstance(nn_items, list):
            non_negotiables = [
                item for item in nn_items
                if isinstance(item, dict) and item.get("status", "active") == "active"
            ]

        # Get avoid patterns
        avoid_patterns = [p for p in memory.get("avoid", []) if isinstance(p, dict)]

        is_valid, message, conflicts = policy_validate(
            text, reason, active_decisions,
            non_negotiables=non_negotiables,
            avoid_patterns=avoid_patterns,
            force=force,
            relation=relation,
            related_decision_text=related_decision,
        )

        if not is_valid and not force:
            return DecisionResult(
                success=False,
                message=message,
                conflicts=conflicts,
            )

        if conflicts:
            warning = message

    except ImportError:
        # Policy engine not available - use simple fallback
        decision_lower = text.lower()
        for existing in memory['decisions']:
            if existing.get("superseded"):
                continue
            existing_text = existing.get('decision', '').lower()
            decision_words = set(decision_lower.split())
            existing_words = set(existing_text.split())
            overlap = decision_words & existing_words
            if len(overlap) >= 3:
                warning = f"Similar decision exists: {existing.get('decision', '')[:60]}..."
                break
    except Exception as e:
        # Don't block on policy errors
        warning = f"Policy check failed: {e}"

    # Pre-save review checks only gaps not already blocked by the policy engine.
    if not skip_review and not force and not resolution_action and not relation:
        try:
            from core.decision_review import review_decision

            semantic_search_fn = None
            try:
                from core.project_semantic import search_project
                semantic_search_fn = search_project
            except Exception:
                semantic_search_fn = None

            review = review_decision(
                text,
                reason,
                memory,
                project_id=project_id,
                semantic_search_fn=semantic_search_fn,
            )

            if review.requires_review and review.primary_candidate:
                return DecisionResult(
                    success=False,
                    requires_review=True,
                    message=review.message,
                    review_result=review.to_dict(),
                )
        except ImportError:
            pass  # Review module not available, continue without review

    # Create decision record (V1)
    timestamp = datetime.now().isoformat()
    decision_record = {
        "type": "decision",
        "decision": text,
        "reason": reason,
        "expected_benefit": "",
        "timestamp": timestamp,
        "importance": "permanent",
        "actor": actor,
        "actor_source": actor_source,
        "status": "active",
    }

    if force:
        decision_record["forced"] = True

    # Set status based on resolution action
    if resolution_action == "save_anyway_under_review":
        decision_record["status"] = "needs_review"

    # Handle relations (including new types from resolution)
    relation = (relation or "").lower()
    if relation in {"refines", "clarifies", "exception_to", "extends"} and related_decision:
        decision_record["relation"] = relation
        decision_record["related_decision"] = related_decision

        # Find and link to existing decision by ID or text
        try:
            from core.decision_review import decision_id_for
            from core.conflict_lifecycle import decision_fingerprint
            for existing in memory.get("decisions", []):
                if existing.get("superseded"):
                    continue
                existing_id = existing.get("id", "")
                existing_text = existing.get("decision", "")
                review_id = decision_id_for(existing)
                # Match by ID or text
                if existing_id == related_decision or \
                   review_id == related_decision or \
                   existing_text.lower() == related_decision.lower() or \
                   related_decision.lower() in existing_text.lower() or \
                   existing_text.lower() in related_decision.lower():
                    decision_record["related_decision_id"] = existing_id or review_id
                    decision_record["related_decision_fingerprint"] = decision_fingerprint(existing)
                    break
            else:
                decision_record["related_decision_fingerprint"] = decision_fingerprint(related_decision)
        except ImportError:
            pass  # Fingerprinting is optional

    memory['decisions'].append(decision_record)

    # Create pending review record for save_anyway_under_review
    if resolution_action == "save_anyway_under_review" and resolution_target_id:
        try:
            from core.decision_review import decision_id_for
            from core.conflict_lifecycle import upsert_decision_conflicts

            existing = _find_decision_by_review_id(memory, resolution_target_id)
            if existing:
                decision_record["review_target_decision_id"] = decision_id_for(existing)
                conflict_evidence = [{
                    "type": "PENDING_DECISION_REVIEW",
                    "severity": "MEDIUM",
                    "existing_decision": existing.get("decision", ""),
                    "existing_reason": existing.get("reason", ""),
                    "existing_actor": existing.get("actor", "unknown"),
                    "existing_actor_source": existing.get("actor_source", "none"),
                    "timestamp": existing.get("timestamp", ""),
                    "topics": [],
                    "message": (
                        "Decision saved under review; verify compatibility with: "
                        f"{existing.get('decision', '')[:80]}"
                    ),
                }]
                upsert_decision_conflicts(
                    memory,
                    conflict_evidence,
                    text,
                    reason,
                    attribution={
                        "actor": actor,
                        "actor_source": actor_source,
                        "session_id": session_id,
                    },
                )
        except ImportError:
            pass  # Conflict lifecycle not available

    # Save V1
    try:
        if save_fn:
            save_fn(project_id, memory)
        else:
            from managers.multi_project_manager import save_project_memory
            save_project_memory(project_id, memory)
    except Exception as e:
        return DecisionResult(
            success=False,
            message=f"Error saving project memory: {e}"
        )

    # Create V2 knowledge object
    v2_id = None
    try:
        from core.knowledge_objects import create_object
        links = {}
        if relation and related_decision:
            links[relation] = related_decision

        obj = create_object(
            project_id=project_id,
            obj_type="decision",
            text=text,
            reason=reason,
            actor=actor,
            actor_source=actor_source,
            links=links,
        )
        v2_id = obj.id
    except Exception as e:
        # V2 creation is non-blocking - log but don't fail
        warning = f"{warning}\nV2 object creation failed: {e}".strip()

    # Index for semantic search (non-blocking)
    try:
        from core.project_semantic import index_decision
        from core.decision_review import decision_id_for
        index_decision(project_id, text, reason, {
            "decision_id": decision_id_for(decision_record),
            "status": decision_record.get("status", "active"),
        })
    except Exception:
        pass  # Semantic indexing is optional

    return DecisionResult(
        success=True,
        decision_id=v2_id,
        message=f"Decision recorded: {text}",
        conflicts=conflicts,
        warning=warning,
    )


def record_avoid(
    project_id: str,
    text: str,
    reason: str,
    actor: str = "unknown",
    actor_source: str = "unknown",
    _memory: Optional[Dict[str, Any]] = None,
    _save_fn: Optional[callable] = None,
) -> DecisionResult:
    """
    Record an avoid pattern to both V1 and V2.

    Args:
        project_id: The project ID (required)
        text: What to avoid
        reason: Why to avoid it
        actor: Who recorded this
        actor_source: How actor was determined
        _memory: Optional pre-loaded memory (for testing/MCP integration)
        _save_fn: Optional custom save function (for testing/MCP integration)

    Returns:
        DecisionResult with success status
    """
    if not project_id:
        return DecisionResult(
            success=False,
            message="Error: project_id is required"
        )

    if not text or not text.strip():
        return DecisionResult(
            success=False,
            message="Error: avoid text is required"
        )

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
            return DecisionResult(
                success=False,
                message=f"Error loading project memory: {e}"
            )

    if 'avoid' not in memory:
        memory['avoid'] = []

    # Create avoid record (V1)
    timestamp = datetime.now().isoformat()
    avoid_record = {
        "type": "avoid",
        "what": text,
        "reason": reason,
        "timestamp": timestamp,
        "importance": "permanent",
        "actor": actor,
        "actor_source": actor_source,
    }

    memory['avoid'].append(avoid_record)

    # Save V1
    try:
        if save_fn:
            save_fn(project_id, memory)
        else:
            from managers.multi_project_manager import save_project_memory
            save_project_memory(project_id, memory)
    except Exception as e:
        return DecisionResult(
            success=False,
            message=f"Error saving project memory: {e}"
        )

    # Create V2 knowledge object
    v2_id = None
    try:
        from core.knowledge_objects import create_object
        obj = create_object(
            project_id=project_id,
            obj_type="avoid",
            text=text,
            reason=reason,
            actor=actor,
            actor_source=actor_source,
        )
        v2_id = obj.id
    except Exception as e:
        pass  # V2 creation is non-blocking

    # Index for semantic search (non-blocking)
    try:
        from core.project_semantic import get_semantic_index
        semantic = get_semantic_index()
        if semantic and hasattr(semantic, 'index_avoid'):
            semantic.index_avoid(project_id, text, reason)
    except Exception:
        pass

    return DecisionResult(
        success=True,
        decision_id=v2_id,
        message=f"Avoid pattern recorded: {text}",
    )
