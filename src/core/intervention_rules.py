"""
Intervention Rules V1 for FixOnce.

Determines when the librarian should speak vs remain silent.
Based on observable triggers only - no LLM judgment.

Core principle: Speak at transitions, silent during continuous work.

Triggers that warrant speaking:
1. Session start (fo_init) - with sufficient subject confidence
2. Error with high match (fo_errors)
3. Explicit request (fo_search)
4. Subject change (fo_sync with new work_area)
5. AVOID pattern match (file OR subject)

All other cases: SILENT
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from enum import Enum


class Trigger(Enum):
    """Observable triggers that may warrant intervention."""
    SESSION_START = "fo_init"
    ERROR_DETECTED = "fo_errors"
    EXPLICIT_SEARCH = "fo_search"
    SUBJECT_CHANGE = "fo_sync"
    FILE_EDIT = "file_edit"
    NONE = "none"


@dataclass
class SessionState:
    """Tracks what has been surfaced this session to avoid repetition."""
    surfaced_subjects: Set[str] = field(default_factory=set)
    surfaced_files: Set[str] = field(default_factory=set)
    surfaced_memory_ids: Set[str] = field(default_factory=set)
    last_work_area: str = ""

    def mark_surfaced(self, subject: str = "", file: str = "", memory_ids: List[str] = None):
        """Mark knowledge as surfaced this session."""
        if subject:
            self.surfaced_subjects.add(subject.lower())
        if file:
            self.surfaced_files.add(file.lower())
        if memory_ids:
            self.surfaced_memory_ids.update(memory_ids)

    def was_surfaced(self, subject: str = "", file: str = "", memory_id: str = "") -> bool:
        """Check if knowledge was already surfaced."""
        if subject and subject.lower() in self.surfaced_subjects:
            return True
        if file and file.lower() in self.surfaced_files:
            return True
        if memory_id and memory_id in self.surfaced_memory_ids:
            return True
        return False

    def is_subject_change(self, new_work_area: str) -> bool:
        """Check if work_area represents a subject change."""
        if not new_work_area:
            return False
        if not self.last_work_area:
            return True
        return new_work_area.lower() != self.last_work_area.lower()


@dataclass
class SubjectContext:
    """Context for making intervention decisions."""
    trigger: Trigger
    subject_tags: List[str] = field(default_factory=list)
    subject_confidence: float = 0.0  # 0.0 to 1.0
    current_file: str = ""
    work_area: str = ""
    error_message: str = ""
    matches: List[Dict[str, Any]] = field(default_factory=list)
    match_confidence: float = 0.0  # Best match confidence
    has_avoid_match: bool = False


# Thresholds
SUBJECT_CONFIDENCE_THRESHOLD = 0.5
MATCH_CONFIDENCE_THRESHOLD = 0.5
ERROR_MATCH_THRESHOLD = 0.8


def should_surface_context(
    context: SubjectContext,
    session_state: SessionState,
) -> bool:
    """
    Determine if the librarian should surface knowledge now.

    Returns True only if:
    1. There is a clear trigger
    2. There is relevant knowledge
    3. It hasn't been surfaced this session
    4. Confidence thresholds are met

    Args:
        context: Current intervention context
        session_state: Session state tracking what was surfaced

    Returns:
        True if should speak, False if should remain silent
    """
    # No matches = always silent
    if not context.matches:
        return False

    # Check trigger-specific rules
    if context.trigger == Trigger.SESSION_START:
        return _should_surface_on_init(context, session_state)

    elif context.trigger == Trigger.ERROR_DETECTED:
        return _should_surface_on_error(context, session_state)

    elif context.trigger == Trigger.EXPLICIT_SEARCH:
        # Always respond to explicit search
        return True

    elif context.trigger == Trigger.SUBJECT_CHANGE:
        return _should_surface_on_subject_change(context, session_state)

    elif context.trigger == Trigger.FILE_EDIT:
        return _should_surface_on_file_edit(context, session_state)

    # No recognized trigger = silent
    return False


def _should_surface_on_init(
    context: SubjectContext,
    session_state: SessionState,
) -> bool:
    """
    Decide if fo_init should surface context.

    Only if:
    - Subject confidence >= threshold
    - Relevant knowledge exists
    - Subject not already surfaced
    """
    # Need sufficient subject confidence
    if context.subject_confidence < SUBJECT_CONFIDENCE_THRESHOLD:
        return False

    # Need at least one subject tag
    if not context.subject_tags:
        return False

    # Check if main subject already surfaced
    main_subject = context.subject_tags[0] if context.subject_tags else ""
    if session_state.was_surfaced(subject=main_subject):
        return False

    # Need matches with sufficient confidence
    if context.match_confidence < MATCH_CONFIDENCE_THRESHOLD:
        return False

    return True


def _should_surface_on_error(
    context: SubjectContext,
    session_state: SessionState,
) -> bool:
    """
    Decide if fo_errors should surface a matching solution.

    Only if:
    - Match confidence >= 80%
    - Not already surfaced this session
    """
    # Need high confidence match for errors
    if context.match_confidence < ERROR_MATCH_THRESHOLD:
        return False

    # Check if this specific match was surfaced
    for match in context.matches:
        match_id = match.get('id', match.get('text', '')[:50])
        if not session_state.was_surfaced(memory_id=match_id):
            return True

    return False


def _should_surface_on_subject_change(
    context: SubjectContext,
    session_state: SessionState,
) -> bool:
    """
    Decide if fo_sync with new work_area should surface context.

    Only if:
    - Work area actually changed
    - New subject not already surfaced
    - Matches have sufficient confidence
    """
    # Check if this is actually a subject change
    if not session_state.is_subject_change(context.work_area):
        return False

    # Check if new subject already surfaced
    main_subject = context.subject_tags[0] if context.subject_tags else context.work_area
    if session_state.was_surfaced(subject=main_subject):
        return False

    # Need matches with sufficient confidence
    if context.match_confidence < MATCH_CONFIDENCE_THRESHOLD:
        return False

    return True


def _should_surface_on_file_edit(
    context: SubjectContext,
    session_state: SessionState,
) -> bool:
    """
    Decide if file edit should surface AVOID pattern.

    Only if:
    - There's an AVOID match (file OR subject)
    - Not already surfaced for this file
    - Not already surfaced for this subject
    """
    # Only speak if there's an AVOID
    if not context.has_avoid_match:
        return False

    # Check if file already covered
    if context.current_file and session_state.was_surfaced(file=context.current_file):
        return False

    # Check if subject already covered (for subject-based AVOIDs)
    main_subject = context.subject_tags[0] if context.subject_tags else ""
    if main_subject and session_state.was_surfaced(subject=main_subject):
        return False

    return True


def get_intervention_decision(
    context: SubjectContext,
    session_state: SessionState,
) -> Dict[str, Any]:
    """
    Get full intervention decision with reasoning.

    Returns a dict with:
    - should_speak: bool
    - reason: str (for debugging/logging)
    - max_items: int (how many to surface)
    """
    should_speak = should_surface_context(context, session_state)

    if not should_speak:
        reason = _get_silence_reason(context, session_state)
        return {
            "should_speak": False,
            "reason": reason,
            "max_items": 0,
        }

    # Determine how many items to surface based on trigger
    if context.trigger == Trigger.ERROR_DETECTED:
        max_items = 1  # Just the matching solution
    elif context.trigger == Trigger.FILE_EDIT:
        max_items = 1  # Just the AVOID
    else:
        max_items = 5  # Full context for init/subject change

    return {
        "should_speak": True,
        "reason": f"Trigger: {context.trigger.value}",
        "max_items": max_items,
    }


def _get_silence_reason(
    context: SubjectContext,
    session_state: SessionState,
) -> str:
    """Get reason for remaining silent (for debugging)."""
    if not context.matches:
        return "No relevant matches"

    if context.trigger == Trigger.NONE:
        return "No trigger detected"

    if context.subject_confidence < SUBJECT_CONFIDENCE_THRESHOLD:
        return f"Subject confidence too low: {context.subject_confidence:.2f}"

    if context.match_confidence < MATCH_CONFIDENCE_THRESHOLD:
        return f"Match confidence too low: {context.match_confidence:.2f}"

    main_subject = context.subject_tags[0] if context.subject_tags else ""
    if session_state.was_surfaced(subject=main_subject):
        return f"Subject already surfaced: {main_subject}"

    if context.current_file and session_state.was_surfaced(file=context.current_file):
        return f"File already surfaced: {context.current_file}"

    return "Unknown reason"
