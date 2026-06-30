"""
Tests for Intervention Rules V1.

Verifies when the librarian should speak vs remain silent.
All rules are observable and deterministic.
"""

import pytest
import sys
sys.path.insert(0, 'src')

from core.intervention_rules import (
    should_surface_context,
    get_intervention_decision,
    SubjectContext,
    SessionState,
    Trigger,
    SUBJECT_CONFIDENCE_THRESHOLD,
    MATCH_CONFIDENCE_THRESHOLD,
    ERROR_MATCH_THRESHOLD,
)


class TestSessionState:
    """Tests for SessionState tracking."""

    def test_mark_and_check_subject(self):
        """Can track surfaced subjects."""
        state = SessionState()
        assert not state.was_surfaced(subject="website")

        state.mark_surfaced(subject="website")
        assert state.was_surfaced(subject="website")
        assert state.was_surfaced(subject="WEBSITE")  # Case insensitive

    def test_mark_and_check_file(self):
        """Can track surfaced files."""
        state = SessionState()
        assert not state.was_surfaced(file="/src/core/search.py")

        state.mark_surfaced(file="/src/core/search.py")
        assert state.was_surfaced(file="/src/core/search.py")

    def test_is_subject_change(self):
        """Detects subject changes correctly."""
        state = SessionState()

        # First work_area is always a change
        assert state.is_subject_change("website")

        # Same area is not a change
        state.last_work_area = "website"
        assert not state.is_subject_change("website")
        assert not state.is_subject_change("WEBSITE")  # Case insensitive

        # Different area is a change
        assert state.is_subject_change("dashboard")

    def test_empty_work_area_not_change(self):
        """Empty work_area is not a subject change."""
        state = SessionState()
        state.last_work_area = "website"
        assert not state.is_subject_change("")


class TestSessionStartTrigger:
    """Tests for fo_init trigger."""

    def test_speak_with_good_confidence(self):
        """Speak when subject confidence is high and matches exist."""
        context = SubjectContext(
            trigger=Trigger.SESSION_START,
            subject_tags=["website"],
            subject_confidence=0.8,
            matches=[{"text": "Dashboard decision"}],
            match_confidence=0.7,
        )
        state = SessionState()

        assert should_surface_context(context, state) is True

    def test_silent_low_subject_confidence(self):
        """Silent when subject confidence is too low."""
        context = SubjectContext(
            trigger=Trigger.SESSION_START,
            subject_tags=["website"],
            subject_confidence=0.3,  # Below threshold
            matches=[{"text": "Dashboard decision"}],
            match_confidence=0.7,
        )
        state = SessionState()

        assert should_surface_context(context, state) is False

    def test_silent_no_subject_tags(self):
        """Silent when no subject tags detected."""
        context = SubjectContext(
            trigger=Trigger.SESSION_START,
            subject_tags=[],  # No tags
            subject_confidence=0.8,
            matches=[{"text": "Dashboard decision"}],
            match_confidence=0.7,
        )
        state = SessionState()

        assert should_surface_context(context, state) is False

    def test_silent_already_surfaced(self):
        """Silent when subject already surfaced this session."""
        context = SubjectContext(
            trigger=Trigger.SESSION_START,
            subject_tags=["website"],
            subject_confidence=0.8,
            matches=[{"text": "Dashboard decision"}],
            match_confidence=0.7,
        )
        state = SessionState()
        state.mark_surfaced(subject="website")

        assert should_surface_context(context, state) is False

    def test_silent_no_matches(self):
        """Silent when no matches found."""
        context = SubjectContext(
            trigger=Trigger.SESSION_START,
            subject_tags=["website"],
            subject_confidence=0.8,
            matches=[],  # No matches
            match_confidence=0.0,
        )
        state = SessionState()

        assert should_surface_context(context, state) is False


class TestErrorTrigger:
    """Tests for fo_errors trigger."""

    def test_speak_high_match(self):
        """Speak when error has high confidence match."""
        context = SubjectContext(
            trigger=Trigger.ERROR_DETECTED,
            error_message="Port binding failed",
            matches=[{"id": "sol_001", "text": "Port fix"}],
            match_confidence=0.9,  # Above 80%
        )
        state = SessionState()

        assert should_surface_context(context, state) is True

    def test_silent_low_match(self):
        """Silent when error match confidence is too low."""
        context = SubjectContext(
            trigger=Trigger.ERROR_DETECTED,
            error_message="Port binding failed",
            matches=[{"text": "Some solution"}],
            match_confidence=0.6,  # Below 80%
        )
        state = SessionState()

        assert should_surface_context(context, state) is False

    def test_silent_already_surfaced(self):
        """Silent when this solution already surfaced."""
        context = SubjectContext(
            trigger=Trigger.ERROR_DETECTED,
            error_message="Port binding failed",
            matches=[{"id": "sol_001", "text": "Port fix"}],
            match_confidence=0.9,
        )
        state = SessionState()
        state.mark_surfaced(memory_ids=["sol_001"])

        assert should_surface_context(context, state) is False


class TestExplicitSearchTrigger:
    """Tests for fo_search trigger."""

    def test_always_speak_with_matches(self):
        """Always respond to explicit search if matches exist."""
        context = SubjectContext(
            trigger=Trigger.EXPLICIT_SEARCH,
            matches=[{"text": "Some result"}],
            match_confidence=0.3,  # Even low confidence
        )
        state = SessionState()

        assert should_surface_context(context, state) is True

    def test_silent_no_matches(self):
        """Silent when no matches for explicit search."""
        context = SubjectContext(
            trigger=Trigger.EXPLICIT_SEARCH,
            matches=[],
        )
        state = SessionState()

        assert should_surface_context(context, state) is False


class TestSubjectChangeTrigger:
    """Tests for fo_sync subject change trigger."""

    def test_speak_on_subject_change(self):
        """Speak when work_area changes to new subject."""
        context = SubjectContext(
            trigger=Trigger.SUBJECT_CHANGE,
            subject_tags=["dashboard"],
            work_area="dashboard",
            matches=[{"text": "Dashboard decision"}],
            match_confidence=0.7,
        )
        state = SessionState()
        state.last_work_area = "website"  # Previous subject

        assert should_surface_context(context, state) is True

    def test_silent_same_subject(self):
        """Silent when work_area hasn't changed."""
        context = SubjectContext(
            trigger=Trigger.SUBJECT_CHANGE,
            subject_tags=["website"],
            work_area="website",
            matches=[{"text": "Website decision"}],
            match_confidence=0.7,
        )
        state = SessionState()
        state.last_work_area = "website"  # Same subject

        assert should_surface_context(context, state) is False

    def test_silent_subject_already_surfaced(self):
        """Silent when new subject was already surfaced."""
        context = SubjectContext(
            trigger=Trigger.SUBJECT_CHANGE,
            subject_tags=["dashboard"],
            work_area="dashboard",
            matches=[{"text": "Dashboard decision"}],
            match_confidence=0.7,
        )
        state = SessionState()
        state.last_work_area = "website"
        state.mark_surfaced(subject="dashboard")  # Already shown

        assert should_surface_context(context, state) is False


class TestFileEditTrigger:
    """Tests for file edit with AVOID trigger."""

    def test_speak_avoid_match(self):
        """Speak when file edit matches AVOID pattern."""
        context = SubjectContext(
            trigger=Trigger.FILE_EDIT,
            current_file="/website/dashboard.html",
            subject_tags=["website", "dashboard"],
            has_avoid_match=True,
            matches=[{"text": "AVOID: inline styles"}],
            match_confidence=0.8,
        )
        state = SessionState()

        assert should_surface_context(context, state) is True

    def test_silent_no_avoid(self):
        """Silent when file edit has no AVOID match."""
        context = SubjectContext(
            trigger=Trigger.FILE_EDIT,
            current_file="/website/dashboard.html",
            subject_tags=["website", "dashboard"],
            has_avoid_match=False,  # No AVOID
            matches=[{"text": "Some decision"}],
            match_confidence=0.8,
        )
        state = SessionState()

        assert should_surface_context(context, state) is False

    def test_silent_file_already_surfaced(self):
        """Silent when AVOID already surfaced for this file."""
        context = SubjectContext(
            trigger=Trigger.FILE_EDIT,
            current_file="/website/dashboard.html",
            subject_tags=["website", "dashboard"],
            has_avoid_match=True,
            matches=[{"text": "AVOID: inline styles"}],
            match_confidence=0.8,
        )
        state = SessionState()
        state.mark_surfaced(file="/website/dashboard.html")

        assert should_surface_context(context, state) is False

    def test_silent_subject_already_surfaced(self):
        """Silent when AVOID already surfaced for this subject."""
        context = SubjectContext(
            trigger=Trigger.FILE_EDIT,
            current_file="/website/other.html",
            subject_tags=["website"],
            has_avoid_match=True,
            matches=[{"text": "AVOID: inline styles"}],
            match_confidence=0.8,
        )
        state = SessionState()
        state.mark_surfaced(subject="website")

        assert should_surface_context(context, state) is False


class TestNoTrigger:
    """Tests for cases with no trigger."""

    def test_silent_no_trigger(self):
        """Always silent when no trigger detected."""
        context = SubjectContext(
            trigger=Trigger.NONE,
            subject_tags=["website"],
            subject_confidence=0.9,
            matches=[{"text": "Great match"}],
            match_confidence=0.95,
        )
        state = SessionState()

        assert should_surface_context(context, state) is False


class TestInterventionDecision:
    """Tests for get_intervention_decision()."""

    def test_returns_max_items_for_init(self):
        """Init returns max 5 items."""
        context = SubjectContext(
            trigger=Trigger.SESSION_START,
            subject_tags=["website"],
            subject_confidence=0.8,
            matches=[{"text": "Decision"}],
            match_confidence=0.7,
        )
        state = SessionState()

        decision = get_intervention_decision(context, state)
        assert decision["should_speak"] is True
        assert decision["max_items"] == 5

    def test_returns_1_item_for_error(self):
        """Error returns max 1 item (the solution)."""
        context = SubjectContext(
            trigger=Trigger.ERROR_DETECTED,
            matches=[{"id": "sol", "text": "Solution"}],
            match_confidence=0.9,
        )
        state = SessionState()

        decision = get_intervention_decision(context, state)
        assert decision["should_speak"] is True
        assert decision["max_items"] == 1

    def test_returns_1_item_for_avoid(self):
        """File edit AVOID returns max 1 item."""
        context = SubjectContext(
            trigger=Trigger.FILE_EDIT,
            current_file="/website/x.html",
            has_avoid_match=True,
            matches=[{"text": "AVOID"}],
        )
        state = SessionState()

        decision = get_intervention_decision(context, state)
        assert decision["should_speak"] is True
        assert decision["max_items"] == 1

    def test_returns_reason_for_silence(self):
        """Silent decision includes reason."""
        context = SubjectContext(
            trigger=Trigger.SESSION_START,
            subject_tags=["website"],
            subject_confidence=0.2,  # Too low
            matches=[{"text": "Decision"}],
            match_confidence=0.7,
        )
        state = SessionState()

        decision = get_intervention_decision(context, state)
        assert decision["should_speak"] is False
        assert "confidence too low" in decision["reason"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
