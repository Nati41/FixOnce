"""
Stage 8 foundation: agent identity model.

This is the boundary between agent-aware metadata and Stage 7 policy inputs.
It does not enforce anything by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.intervention_policy import InterventionContext


_INTENT_TOOL_MAP = {
    "apply_fix": {"fo_apply"},
    "completion": {"fo_solved", "fo_component", "update_component_status"},
    "decision": {"fo_decide", "log_decision", "supersede_decision"},
    "read": {"fo_errors", "get_browser_errors", "get_live_record", "fo_init", "auto_init_session"},
    "search": {"fo_search", "search_past_solutions", "_find_solution_for_error"},
    "sync": {"fo_sync", "sync_to_active_project", "update_live_record", "update_work_context"},
}

_INTENT_KEYWORDS = {
    "apply_fix": {"apply", "fix", "repair", "patch"},
    "completion": {"complete", "completion", "done", "close", "finish", "solved"},
    "decision": {"decision", "policy", "supersede", "approve"},
    "read": {"read", "inspect", "observe", "view"},
    "search": {"search", "find", "lookup", "query"},
    "sync": {"sync", "record", "update", "persist"},
    "write": {"write", "edit", "change", "modify"},
}


def classify_agent_intent(
    tool_name: str,
    explicit_intent: str = "",
    intervention_ctx: Optional[InterventionContext] = None,
) -> tuple[str, str]:
    """Normalize runtime intent into a stable Stage 8 label plus raw detail."""
    raw_intent = (explicit_intent or "").strip()
    normalized_raw = raw_intent.lower()
    normalized_tool = (tool_name or "").strip().lower()

    if normalized_raw in {"read", "write", "search", "sync", "apply_fix", "decision", "completion"}:
        return normalized_raw, raw_intent

    for intent_name, tools in _INTENT_TOOL_MAP.items():
        if normalized_tool in tools:
            return intent_name, raw_intent

    if intervention_ctx:
        if intervention_ctx.decision_conflict_severity:
            return "decision", raw_intent
        if intervention_ctx.bug_fix_completed or intervention_ctx.auto_fix_ready:
            return "apply_fix", raw_intent
        if (
            intervention_ctx.task_completed
            or intervention_ctx.significant_work_completed
            or intervention_ctx.component_changed
            or intervention_ctx.fo_solved_called
        ):
            return "completion", raw_intent
        if intervention_ctx.similar_past_solution_found or intervention_ctx.repeat_bug_detected:
            return "search", raw_intent
        if intervention_ctx.live_errors > 0:
            return "read", raw_intent
        if (
            intervention_ctx.blocked_components_relevant > 0
            or intervention_ctx.lock_violation
            or intervention_ctx.risky_change
            or intervention_ctx.stable_component_touched
        ):
            return "write", raw_intent

    if normalized_raw:
        for intent_name, keywords in _INTENT_KEYWORDS.items():
            if any(keyword in normalized_raw for keyword in keywords):
                return intent_name, raw_intent

    if normalized_tool.startswith(("log_", "save_", "write_")):
        return "write", raw_intent

    return "read", raw_intent


@dataclass(frozen=True)
class AgentContext:
    actor_name: str
    actor_source: str
    actor_confidence: float
    tool_name: str
    intent: str
    session_id: str
    project_id: str
    intent_detail: str = ""
    flow_classification: str = "partial"

    def attribution(self) -> Dict[str, Any]:
        """Return the durable provenance fields used by new memory records."""
        return {
            "actor": self.actor_name or "unknown",
            "actor_source": self.actor_source or "none",
            "actor_confidence": float(self.actor_confidence or 0.0),
            "session_id": self.session_id or "unknown-session",
            "tool_name": self.tool_name or "unknown-tool",
        }
