"""
Evidence of Impact - Core FixOnce Platform Capability

Records structured evidence of FixOnce contributions during a task/session.
AI-agnostic: any agent (Claude, Codex, Cursor, etc.) can consume this API.

Design principles:
1. Only record observable runtime facts
2. Never estimate time, tokens, or productivity
3. Every event must be traceable to a real FixOnce action
4. Empty report when no contribution occurred
5. Structured data output, not formatted text
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Literal, Optional, Set
from collections import OrderedDict
import hashlib


# Event types that map to existing FixOnce runtime events
ImpactEventType = Literal[
    "solution_reused",        # fo_search found matching solution
    "decision_reused",        # Decision was retrieved and surfaced
    "avoid_pattern_surfaced", # Avoid pattern was shown to agent
    "context_restored",       # fo_init loaded existing project context
    "similar_found",          # Similar solution/decision was surfaced
    "intervention_triggered", # Risk gate or intervention fired
    "conflict_detected",      # Decision or solution conflict detected
    "review_triggered",       # Pre-save review found related items
    "auto_fix_available",     # Auto-fix was ready for an error
    "error_caught_live",      # Browser error detected proactively
]


@dataclass(frozen=True)
class ImpactEvent:
    """
    A single evidence of FixOnce contribution.

    Immutable - once created, cannot be modified.
    Every field must be populated from actual runtime data.
    """
    event_type: ImpactEventType
    source_tool: str              # MCP tool that produced this event
    content_id: str               # ID of the reused/surfaced item
    content_summary: str          # Brief factual summary (max 150 chars)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Optional context
    query: str = ""               # What the agent was searching for
    match_confidence: float = 0.0 # How confident the match was (0-1)
    category: str = ""            # Category of the item (decision, bug, etc.)

    def dedup_key(self) -> str:
        """
        Generate a deduplication key.

        Same event_type + content_id within a session = duplicate.
        """
        return f"{self.event_type}|{self.content_id}"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON output."""
        return asdict(self)


@dataclass
class ImpactReport:
    """
    Structured impact report for a session.

    AI-agnostic: returns data, not formatted text.
    Each AI agent decides how to present this to the user.
    """
    session_id: str
    events: List[Dict[str, Any]]
    has_contribution: bool
    event_count: int
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API output."""
        return {
            "session_id": self.session_id,
            "has_contribution": self.has_contribution,
            "event_count": self.event_count,
            "events": self.events,
            "generated_at": self.generated_at,
        }


# ============================================================
# Session Accumulator
# ============================================================

_ACCUMULATOR_LOCK = Lock()

# Per-session event storage: session_id -> OrderedDict[dedup_key -> ImpactEvent]
# Using OrderedDict to preserve insertion order while enabling dedup
_SESSION_EVENTS: Dict[str, OrderedDict[str, ImpactEvent]] = {}

# Maximum events per session (bounded memory)
_MAX_EVENTS_PER_SESSION = 100

# Maximum sessions to track (LRU cleanup)
_MAX_SESSIONS = 50


def _get_current_session_id() -> str:
    """
    Get the current session ID from MCP session state.

    Falls back to a default if no session is active.
    """
    try:
        # Try to get from MCP session
        from mcp_server.mcp_memory_server_v2 import _get_session
        session = _get_session()
        if session and session.is_active():
            # Use project_id as session identifier for now
            # This groups events by project which is reasonable
            return session.project_id or "default"
    except Exception:
        pass
    return "default"


def _cleanup_old_sessions() -> None:
    """Remove oldest sessions if we exceed the limit."""
    if len(_SESSION_EVENTS) > _MAX_SESSIONS:
        # Remove oldest sessions (first items in dict)
        sessions_to_remove = list(_SESSION_EVENTS.keys())[:-_MAX_SESSIONS]
        for session_id in sessions_to_remove:
            del _SESSION_EVENTS[session_id]


def record_impact_event(
    event_type: ImpactEventType,
    source_tool: str,
    content_id: str,
    content_summary: str,
    query: str = "",
    match_confidence: float = 0.0,
    category: str = "",
    session_id: str = "",
) -> Optional[ImpactEvent]:
    """
    Record an impact event for the current session.

    Deduplicates by event_type + content_id within the same session.
    Returns the event if recorded, None if deduplicated.

    This function is called from existing FixOnce tools to wrap
    runtime events without changing their behavior.
    """
    if not session_id:
        session_id = _get_current_session_id()

    # Truncate summary to prevent unbounded growth
    if len(content_summary) > 150:
        content_summary = content_summary[:147] + "..."

    event = ImpactEvent(
        event_type=event_type,
        source_tool=source_tool,
        content_id=content_id,
        content_summary=content_summary,
        query=query[:100] if query else "",
        match_confidence=match_confidence,
        category=category,
    )

    dedup_key = event.dedup_key()

    with _ACCUMULATOR_LOCK:
        _cleanup_old_sessions()

        if session_id not in _SESSION_EVENTS:
            _SESSION_EVENTS[session_id] = OrderedDict()

        session_events = _SESSION_EVENTS[session_id]

        # Deduplicate
        if dedup_key in session_events:
            return None

        # Enforce per-session limit
        if len(session_events) >= _MAX_EVENTS_PER_SESSION:
            # Remove oldest event
            session_events.popitem(last=False)

        session_events[dedup_key] = event
        return event


def get_session_events(session_id: str = "") -> List[ImpactEvent]:
    """
    Get all impact events for a session.

    Returns events in chronological order (oldest first).
    """
    if not session_id:
        session_id = _get_current_session_id()

    with _ACCUMULATOR_LOCK:
        if session_id not in _SESSION_EVENTS:
            return []
        return list(_SESSION_EVENTS[session_id].values())


def clear_session_events(session_id: str = "") -> int:
    """
    Clear all events for a session.

    Returns the number of events cleared.
    """
    if not session_id:
        session_id = _get_current_session_id()

    with _ACCUMULATOR_LOCK:
        if session_id in _SESSION_EVENTS:
            count = len(_SESSION_EVENTS[session_id])
            del _SESSION_EVENTS[session_id]
            return count
        return 0


# ============================================================
# Report Builder
# ============================================================

# Event type to usage statement mapping
# Format: "Used FixOnce to..." - factual, no estimates, no marketing
_USAGE_STATEMENTS: Dict[ImpactEventType, str] = {
    "solution_reused": "Used FixOnce to reuse a previously saved solution.",
    "decision_reused": "Used FixOnce to check an existing project decision.",
    "avoid_pattern_surfaced": "Used FixOnce to retrieve a known pattern to avoid.",
    "context_restored": "Used FixOnce to restore previous project context.",
    "similar_found": "Used FixOnce to find similar prior experience.",
    "intervention_triggered": "Used FixOnce Guardian guidance before a destructive operation.",
    "conflict_detected": "Used FixOnce to detect a potential conflict.",
    "review_triggered": "Used FixOnce to review related items before saving.",
    "auto_fix_available": "Used FixOnce to retrieve an available auto-fix.",
    "error_caught_live": "Used FixOnce to catch a browser error proactively.",
}


def _format_usage_statement(event: ImpactEvent) -> str:
    """Format a single event into a factual usage statement."""
    return _USAGE_STATEMENTS.get(event.event_type, f"Used FixOnce: {event.content_summary}")


def get_usage_statements(session_id: str = "") -> List[str]:
    """
    Get FixOnce usage statements for the current session.

    Returns a simple list of factual usage statements like:
    - "Used FixOnce to restore previous project context."
    - "Used FixOnce to reuse a previously saved solution."

    These are meant to be included directly in an agent's task summary.
    No estimates, no marketing - just what actually happened.

    Returns empty list if FixOnce wasn't used during this task.
    """
    if not session_id:
        session_id = _get_current_session_id()

    events = get_session_events(session_id)

    if not events:
        return []

    # Deduplicate by statement (same event type = same statement)
    seen_statements = set()
    statements = []

    for event in events:
        statement = _format_usage_statement(event)
        if statement not in seen_statements:
            seen_statements.add(statement)
            statements.append(statement)

    return statements


def build_impact_report(session_id: str = "") -> ImpactReport:
    """
    Build a structured usage report for a session.

    Returns:
        ImpactReport with:
        - has_contribution: True if FixOnce was used
        - events: List of usage details for AI to present
        - event_count: Total number of usage events

    For simple usage, prefer get_usage_statements() which returns
    a list of strings ready to include in task summaries.
    """
    if not session_id:
        session_id = _get_current_session_id()

    events = get_session_events(session_id)

    if not events:
        return ImpactReport(
            session_id=session_id,
            events=[],
            has_contribution=False,
            event_count=0,
        )

    # Build event details
    event_details = []
    for event in events:
        event_details.append({
            "type": event.event_type,
            "statement": _format_usage_statement(event),
            "source_tool": event.source_tool,
            "content_id": event.content_id,
        })

    return ImpactReport(
        session_id=session_id,
        events=event_details,
        has_contribution=True,
        event_count=len(events),
    )


def get_usage_report(session_id: str = "") -> Dict[str, Any]:
    """
    Get FixOnce usage for the current session as a dict.

    Returns:
        {
            "used": bool,           # True if FixOnce was used
            "statements": [str],    # List of usage statements
        }

    This is the primary API for AI agents to include FixOnce usage
    in their task summaries.
    """
    statements = get_usage_statements(session_id)
    return {
        "used": len(statements) > 0,
        "statements": statements,
    }


def get_impact_report_dict(session_id: str = "") -> Dict[str, Any]:
    """
    Convenience function: build report and return as dict.

    For simple usage, prefer get_usage_report() instead.
    """
    report = build_impact_report(session_id)
    return report.to_dict()


# ============================================================
# Integration Helpers
# ============================================================

def record_solution_reused(
    solution_id: str,
    solution_summary: str,
    query: str = "",
    confidence: float = 0.0,
    source_tool: str = "fo_search",
) -> Optional[ImpactEvent]:
    """Helper: Record that a solution was reused."""
    return record_impact_event(
        event_type="solution_reused",
        source_tool=source_tool,
        content_id=solution_id,
        content_summary=solution_summary,
        query=query,
        match_confidence=confidence,
        category="solution",
    )


def record_decision_reused(
    decision_id: str,
    decision_summary: str,
    source_tool: str = "fo_search",
) -> Optional[ImpactEvent]:
    """Helper: Record that a decision was reused."""
    return record_impact_event(
        event_type="decision_reused",
        source_tool=source_tool,
        content_id=decision_id,
        content_summary=decision_summary,
        category="decision",
    )


def record_avoid_pattern_surfaced(
    pattern_id: str,
    pattern_summary: str,
    source_tool: str = "fo_init",
) -> Optional[ImpactEvent]:
    """Helper: Record that an avoid pattern was surfaced."""
    return record_impact_event(
        event_type="avoid_pattern_surfaced",
        source_tool=source_tool,
        content_id=pattern_id,
        content_summary=pattern_summary,
        category="avoid",
    )


def record_context_restored(
    context_id: str,
    context_summary: str,
    source_tool: str = "fo_init",
) -> Optional[ImpactEvent]:
    """Helper: Record that project context was restored."""
    return record_impact_event(
        event_type="context_restored",
        source_tool=source_tool,
        content_id=context_id,
        content_summary=context_summary,
        category="context",
    )


def record_auto_fix_available(
    fix_id: str,
    fix_summary: str,
    source_tool: str = "fo_errors",
) -> Optional[ImpactEvent]:
    """Helper: Record that an auto-fix was available."""
    return record_impact_event(
        event_type="auto_fix_available",
        source_tool=source_tool,
        content_id=fix_id,
        content_summary=fix_summary,
        category="fix",
    )


def record_error_caught_live(
    error_id: str,
    error_summary: str,
    source_tool: str = "fo_errors",
) -> Optional[ImpactEvent]:
    """Helper: Record that a browser error was caught proactively."""
    return record_impact_event(
        event_type="error_caught_live",
        source_tool=source_tool,
        content_id=error_id,
        content_summary=error_summary,
        category="error",
    )


def record_intervention_triggered(
    intervention_id: str,
    intervention_summary: str,
    source_tool: str = "guardian",
) -> Optional[ImpactEvent]:
    """Helper: Record that a safety intervention was triggered."""
    return record_impact_event(
        event_type="intervention_triggered",
        source_tool=source_tool,
        content_id=intervention_id,
        content_summary=intervention_summary,
        category="intervention",
    )


def record_conflict_detected(
    conflict_id: str,
    conflict_summary: str,
    source_tool: str = "fo_solved",
) -> Optional[ImpactEvent]:
    """Helper: Record that a conflict was detected."""
    return record_impact_event(
        event_type="conflict_detected",
        source_tool=source_tool,
        content_id=conflict_id,
        content_summary=conflict_summary,
        category="conflict",
    )


def record_review_triggered(
    review_id: str,
    review_summary: str,
    source_tool: str = "fo_solved",
) -> Optional[ImpactEvent]:
    """Helper: Record that a pre-save review found related items."""
    return record_impact_event(
        event_type="review_triggered",
        source_tool=source_tool,
        content_id=review_id,
        content_summary=review_summary,
        category="review",
    )
