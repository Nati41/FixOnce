"""
Core decision recording logic.

This module contains transport-independent business logic for recording decisions.
MCP, REST API, CLI, and tests should all call these functions.

Architecture:
- MCP tool (fo_decide) is a thin wrapper over these core functions
- All storage (V1 project_memory.json + V2 knowledge_objects) happens here
- actor/actor_source are explicit parameters, not detected internally
"""

from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class DecisionResult:
    """Result of a decision recording operation."""
    success: bool
    decision_id: Optional[str] = None  # V2 object ID if created
    message: str = ""
    conflicts: List[Dict[str, Any]] = None
    warning: str = ""

    def __post_init__(self):
        if self.conflicts is None:
            self.conflicts = []


def record_decision(
    project_id: str,
    text: str,
    reason: str,
    actor: str = "unknown",
    actor_source: str = "unknown",
    force: bool = False,
    relation: str = "",
    related_decision: str = "",
    _memory: Optional[Dict[str, Any]] = None,
    _save_fn: Optional[callable] = None,
) -> DecisionResult:
    """
    Record a decision to both V1 (project_memory.json) and V2 (knowledge_objects).

    This is the core business logic - no MCP or transport dependencies.

    Args:
        project_id: The project ID (required)
        text: The decision text
        reason: Why this decision was made
        actor: Who made this decision (e.g., "claude", "user", "dashboard")
        actor_source: How actor was determined (e.g., "mcp_session", "api_header")
        force: If True, override conflict detection
        relation: Optional relation ("refines" or "clarifies")
        related_decision: Text of related decision if relation is set
        _memory: Optional pre-loaded memory (for testing/MCP integration)
        _save_fn: Optional custom save function (for testing/MCP integration)

    Returns:
        DecisionResult with success status, message, and any conflicts
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
    }

    if force:
        decision_record["forced"] = True

    # Handle relations
    relation = (relation or "").lower()
    if relation in {"refines", "clarifies"} and related_decision:
        decision_record["relation"] = relation
        decision_record["related_decision"] = related_decision

        # Add fingerprint for related decision
        try:
            from core.conflict_lifecycle import decision_fingerprint
            for existing in memory.get("decisions", []):
                if existing.get("superseded"):
                    continue
                existing_text = existing.get("decision", "")
                if (
                    existing_text.lower() == related_decision.lower()
                    or related_decision.lower() in existing_text.lower()
                    or existing_text.lower() in related_decision.lower()
                ):
                    decision_record["related_decision_fingerprint"] = decision_fingerprint(existing)
                    break
            else:
                decision_record["related_decision_fingerprint"] = decision_fingerprint(related_decision)
        except ImportError:
            pass  # Fingerprinting is optional

    memory['decisions'].append(decision_record)

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
        from core.project_semantic import get_semantic_index
        semantic = get_semantic_index()
        if semantic and hasattr(semantic, 'index_decision'):
            semantic.index_decision(project_id, text, reason)
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
