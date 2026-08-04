#!/usr/bin/env python3
"""
Tests for Evidence of Impact - Core FixOnce Platform Capability.

Tests prove:
- ImpactEvents are recorded from real runtime evidence
- Duplicate events are deduplicated within a session
- Report builder returns structured data, not formatted text
- Empty report when no contribution occurred
- Session isolation works correctly
- Bounded memory (max events, max sessions)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class TestImpactEventBasics(unittest.TestCase):
    """Basic ImpactEvent creation and serialization."""

    def test_create_impact_event(self):
        """ImpactEvent can be created with required fields."""
        from core.impact_events import ImpactEvent

        event = ImpactEvent(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Added null check for undefined",
        )

        self.assertEqual(event.event_type, "solution_reused")
        self.assertEqual(event.source_tool, "fo_search")
        self.assertEqual(event.content_id, "sol_123")
        self.assertEqual(event.content_summary, "Added null check for undefined")
        self.assertTrue(event.timestamp)  # Auto-generated

    def test_impact_event_is_immutable(self):
        """ImpactEvent is frozen - cannot be modified after creation."""
        from core.impact_events import ImpactEvent

        event = ImpactEvent(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Test",
        )

        with self.assertRaises(Exception):
            event.content_summary = "Modified"

    def test_dedup_key_format(self):
        """Dedup key is event_type|content_id."""
        from core.impact_events import ImpactEvent

        event = ImpactEvent(
            event_type="decision_reused",
            source_tool="fo_init",
            content_id="dec_456",
            content_summary="Use shlex",
        )

        self.assertEqual(event.dedup_key(), "decision_reused|dec_456")

    def test_to_dict_serialization(self):
        """ImpactEvent serializes to dict correctly."""
        from core.impact_events import ImpactEvent

        event = ImpactEvent(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Test summary",
            query="TypeError",
            match_confidence=0.95,
            category="solution",
        )

        d = event.to_dict()

        self.assertEqual(d["event_type"], "solution_reused")
        self.assertEqual(d["source_tool"], "fo_search")
        self.assertEqual(d["content_id"], "sol_123")
        self.assertEqual(d["query"], "TypeError")
        self.assertEqual(d["match_confidence"], 0.95)


class TestSessionAccumulator(unittest.TestCase):
    """Session accumulator tests."""

    def setUp(self):
        """Clear session state before each test."""
        from core.impact_events import clear_session_events
        clear_session_events("test_session")
        clear_session_events("session_a")
        clear_session_events("session_b")

    def test_record_impact_event(self):
        """record_impact_event stores event in session."""
        from core.impact_events import record_impact_event, get_session_events

        event = record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Test solution",
            session_id="test_session",
        )

        self.assertIsNotNone(event)

        events = get_session_events("test_session")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].content_id, "sol_123")

    def test_deduplication_same_session(self):
        """Duplicate events in same session are deduplicated."""
        from core.impact_events import record_impact_event, get_session_events

        # Record same event twice
        event1 = record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Test solution",
            session_id="test_session",
        )
        event2 = record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Test solution (duplicate)",
            session_id="test_session",
        )

        self.assertIsNotNone(event1)
        self.assertIsNone(event2)  # Deduplicated

        events = get_session_events("test_session")
        self.assertEqual(len(events), 1)

    def test_different_content_ids_not_deduplicated(self):
        """Different content_ids are not deduplicated."""
        from core.impact_events import record_impact_event, get_session_events

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Solution 1",
            session_id="test_session",
        )
        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_456",
            content_summary="Solution 2",
            session_id="test_session",
        )

        events = get_session_events("test_session")
        self.assertEqual(len(events), 2)

    def test_different_event_types_not_deduplicated(self):
        """Different event_types are not deduplicated."""
        from core.impact_events import record_impact_event, get_session_events

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="item_123",
            content_summary="As solution",
            session_id="test_session",
        )
        record_impact_event(
            event_type="decision_reused",
            source_tool="fo_search",
            content_id="item_123",
            content_summary="As decision",
            session_id="test_session",
        )

        events = get_session_events("test_session")
        self.assertEqual(len(events), 2)

    def test_session_isolation(self):
        """Events are isolated per session."""
        from core.impact_events import record_impact_event, get_session_events

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_a",
            content_summary="Session A solution",
            session_id="session_a",
        )
        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_b",
            content_summary="Session B solution",
            session_id="session_b",
        )

        events_a = get_session_events("session_a")
        events_b = get_session_events("session_b")

        self.assertEqual(len(events_a), 1)
        self.assertEqual(len(events_b), 1)
        self.assertEqual(events_a[0].content_id, "sol_a")
        self.assertEqual(events_b[0].content_id, "sol_b")

    def test_clear_session_events(self):
        """clear_session_events removes all events for a session."""
        from core.impact_events import record_impact_event, get_session_events, clear_session_events

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Test",
            session_id="test_session",
        )

        count = clear_session_events("test_session")
        self.assertEqual(count, 1)

        events = get_session_events("test_session")
        self.assertEqual(len(events), 0)

    def test_summary_truncation(self):
        """Long summaries are truncated to 150 chars."""
        from core.impact_events import record_impact_event, get_session_events

        long_summary = "x" * 200

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary=long_summary,
            session_id="test_session",
        )

        events = get_session_events("test_session")
        self.assertEqual(len(events[0].content_summary), 150)
        self.assertTrue(events[0].content_summary.endswith("..."))

    def test_events_preserve_order(self):
        """Events are returned in chronological order."""
        from core.impact_events import record_impact_event, get_session_events

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="first",
            content_summary="First event",
            session_id="test_session",
        )
        record_impact_event(
            event_type="decision_reused",
            source_tool="fo_init",
            content_id="second",
            content_summary="Second event",
            session_id="test_session",
        )
        record_impact_event(
            event_type="avoid_pattern_surfaced",
            source_tool="fo_init",
            content_id="third",
            content_summary="Third event",
            session_id="test_session",
        )

        events = get_session_events("test_session")
        self.assertEqual(events[0].content_id, "first")
        self.assertEqual(events[1].content_id, "second")
        self.assertEqual(events[2].content_id, "third")


class TestImpactReport(unittest.TestCase):
    """Impact report builder tests."""

    def setUp(self):
        from core.impact_events import clear_session_events
        clear_session_events("test_session")

    def test_empty_report_no_contribution(self):
        """Empty session returns has_contribution=False."""
        from core.impact_events import build_impact_report

        report = build_impact_report("test_session")

        self.assertFalse(report.has_contribution)
        self.assertEqual(report.event_count, 0)
        self.assertEqual(report.events, [])

    def test_report_with_events(self):
        """Session with events returns has_contribution=True."""
        from core.impact_events import record_impact_event, build_impact_report

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Added null check",
            session_id="test_session",
        )

        report = build_impact_report("test_session")

        self.assertTrue(report.has_contribution)
        self.assertEqual(report.event_count, 1)
        self.assertEqual(len(report.events), 1)

    def test_report_event_structure(self):
        """Report events have correct structure."""
        from core.impact_events import record_impact_event, build_impact_report

        record_impact_event(
            event_type="decision_reused",
            source_tool="fo_search",
            content_id="dec_456",
            content_summary="Use shlex for parsing",
            category="decision",
            session_id="test_session",
        )

        report = build_impact_report("test_session")
        event = report.events[0]

        self.assertEqual(event["type"], "decision_reused")
        self.assertEqual(event["source_tool"], "fo_search")
        self.assertEqual(event["content_id"], "dec_456")
        self.assertIn("statement", event)

    def test_report_to_dict(self):
        """Report serializes to dict correctly."""
        from core.impact_events import record_impact_event, build_impact_report

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Test",
            session_id="test_session",
        )

        report = build_impact_report("test_session")
        d = report.to_dict()

        self.assertIn("session_id", d)
        self.assertIn("has_contribution", d)
        self.assertIn("event_count", d)
        self.assertIn("events", d)
        self.assertIn("generated_at", d)

    def test_get_impact_report_dict(self):
        """get_impact_report_dict returns dict directly."""
        from core.impact_events import record_impact_event, get_impact_report_dict

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Test",
            session_id="test_session",
        )

        d = get_impact_report_dict("test_session")

        self.assertIsInstance(d, dict)
        self.assertTrue(d["has_contribution"])


class TestEventSummaryTemplates(unittest.TestCase):
    """Event summary formatting tests."""

    def setUp(self):
        from core.impact_events import clear_session_events
        clear_session_events("test_session")

    def test_solution_reused_statement(self):
        """Solution reused events have correct statement format."""
        from core.impact_events import record_impact_event, build_impact_report

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_123",
            content_summary="Added null check for undefined",
            session_id="test_session",
        )

        report = build_impact_report("test_session")
        statement = report.events[0]["statement"]

        self.assertEqual(statement, "Used FixOnce to reuse a previously saved solution.")

    def test_decision_reused_statement(self):
        """Decision reused events have correct statement format."""
        from core.impact_events import record_impact_event, build_impact_report

        record_impact_event(
            event_type="decision_reused",
            source_tool="fo_init",
            content_id="dec_456",
            content_summary="Use shlex instead of regex",
            session_id="test_session",
        )

        report = build_impact_report("test_session")
        statement = report.events[0]["statement"]

        self.assertEqual(statement, "Used FixOnce to check an existing project decision.")

    def test_avoid_pattern_statement(self):
        """Avoid pattern events have correct statement format."""
        from core.impact_events import record_impact_event, build_impact_report

        record_impact_event(
            event_type="avoid_pattern_surfaced",
            source_tool="fo_init",
            content_id="avoid_789",
            content_summary="Never force push without confirmation",
            session_id="test_session",
        )

        report = build_impact_report("test_session")
        statement = report.events[0]["statement"]

        self.assertEqual(statement, "Used FixOnce to retrieve a known pattern to avoid.")

    def test_context_restored_statement(self):
        """Context restored events have correct statement format."""
        from core.impact_events import record_impact_event, build_impact_report

        record_impact_event(
            event_type="context_restored",
            source_tool="fo_init",
            content_id="ctx_001",
            content_summary="Goal: Fix Guardian bug, Next: Test the fix",
            session_id="test_session",
        )

        report = build_impact_report("test_session")
        statement = report.events[0]["statement"]

        self.assertEqual(statement, "Used FixOnce to restore previous project context.")


class TestHelperFunctions(unittest.TestCase):
    """Helper function tests."""

    def setUp(self):
        from core.impact_events import clear_session_events
        clear_session_events("test_session")

    def test_record_solution_reused_helper(self):
        """record_solution_reused helper works correctly."""
        from core.impact_events import record_solution_reused, get_session_events

        with patch("core.impact_events._get_current_session_id", return_value="test_session"):
            event = record_solution_reused(
                solution_id="sol_123",
                solution_summary="Fixed TypeError",
                query="TypeError",
                confidence=0.9,
            )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "solution_reused")
        self.assertEqual(event.category, "solution")

    def test_record_decision_reused_helper(self):
        """record_decision_reused helper works correctly."""
        from core.impact_events import record_decision_reused, get_session_events

        with patch("core.impact_events._get_current_session_id", return_value="test_session"):
            event = record_decision_reused(
                decision_id="dec_456",
                decision_summary="Use TypeScript",
            )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "decision_reused")
        self.assertEqual(event.category, "decision")

    def test_record_avoid_pattern_surfaced_helper(self):
        """record_avoid_pattern_surfaced helper works correctly."""
        from core.impact_events import record_avoid_pattern_surfaced

        with patch("core.impact_events._get_current_session_id", return_value="test_session"):
            event = record_avoid_pattern_surfaced(
                pattern_id="avoid_789",
                pattern_summary="Don't commit secrets",
            )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "avoid_pattern_surfaced")

    def test_record_context_restored_helper(self):
        """record_context_restored helper works correctly."""
        from core.impact_events import record_context_restored

        with patch("core.impact_events._get_current_session_id", return_value="test_session"):
            event = record_context_restored(
                context_id="ctx_001",
                context_summary="Goal: Fix bug",
            )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "context_restored")


class TestBoundedMemory(unittest.TestCase):
    """Memory bounds tests."""

    def setUp(self):
        from core.impact_events import clear_session_events
        clear_session_events("test_session")

    def test_max_events_per_session(self):
        """Sessions are bounded to max events."""
        from core.impact_events import record_impact_event, get_session_events, _MAX_EVENTS_PER_SESSION

        # Record more than max events
        for i in range(_MAX_EVENTS_PER_SESSION + 10):
            record_impact_event(
                event_type="solution_reused",
                source_tool="fo_search",
                content_id=f"sol_{i}",
                content_summary=f"Solution {i}",
                session_id="test_session",
            )

        events = get_session_events("test_session")
        self.assertLessEqual(len(events), _MAX_EVENTS_PER_SESSION)


class TestNoRuntimeBehaviorChange(unittest.TestCase):
    """Verify existing behavior is unchanged."""

    def test_record_does_not_throw(self):
        """Recording events never throws."""
        from core.impact_events import record_impact_event

        # Should not throw even with weird inputs
        try:
            record_impact_event(
                event_type="solution_reused",
                source_tool="",
                content_id="",
                content_summary="",
                session_id="test",
            )
        except Exception as e:
            self.fail(f"record_impact_event threw: {e}")

    def test_get_report_does_not_throw(self):
        """Getting report never throws."""
        from core.impact_events import get_impact_report_dict

        # Should not throw for non-existent session
        try:
            result = get_impact_report_dict("nonexistent_session")
            self.assertIsInstance(result, dict)
        except Exception as e:
            self.fail(f"get_impact_report_dict threw: {e}")


class TestUsageStatements(unittest.TestCase):
    """Test usage statement generation."""

    def setUp(self):
        from core.impact_events import clear_session_events
        clear_session_events("test_usage")

    def test_empty_session_returns_empty_list(self):
        """No events = empty usage list."""
        from core.impact_events import get_usage_statements

        with patch("core.impact_events._get_current_session_id", return_value="test_usage"):
            statements = get_usage_statements()

        self.assertEqual(statements, [])

    def test_solution_reused_statement(self):
        """Solution reused produces correct statement."""
        from core.impact_events import record_solution_reused, get_usage_statements

        with patch("core.impact_events._get_current_session_id", return_value="test_usage"):
            record_solution_reused("sol_123", "Fixed TypeError")
            statements = get_usage_statements()

        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0], "Used FixOnce to reuse a previously saved solution.")

    def test_context_restored_statement(self):
        """Context restored produces correct statement."""
        from core.impact_events import record_context_restored, get_usage_statements

        with patch("core.impact_events._get_current_session_id", return_value="test_usage"):
            record_context_restored("ctx_1", "Goal: Fix bug")
            statements = get_usage_statements()

        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0], "Used FixOnce to restore previous project context.")

    def test_decision_reused_statement(self):
        """Decision reused produces correct statement."""
        from core.impact_events import record_decision_reused, get_usage_statements

        with patch("core.impact_events._get_current_session_id", return_value="test_usage"):
            record_decision_reused("dec_1", "Use TypeScript")
            statements = get_usage_statements()

        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0], "Used FixOnce to check an existing project decision.")

    def test_multiple_same_type_deduplicated(self):
        """Multiple events of same type produce one statement."""
        from core.impact_events import record_solution_reused, get_usage_statements

        with patch("core.impact_events._get_current_session_id", return_value="test_usage"):
            record_solution_reused("sol_1", "Fix 1")
            record_solution_reused("sol_2", "Fix 2")
            record_solution_reused("sol_3", "Fix 3")
            statements = get_usage_statements()

        # Same event type = one statement
        self.assertEqual(len(statements), 1)

    def test_multiple_different_types(self):
        """Different event types produce multiple statements."""
        from core.impact_events import (
            record_solution_reused,
            record_context_restored,
            get_usage_statements,
        )

        with patch("core.impact_events._get_current_session_id", return_value="test_usage"):
            record_context_restored("ctx_1", "Goal")
            record_solution_reused("sol_1", "Fix")
            statements = get_usage_statements()

        self.assertEqual(len(statements), 2)


class TestUsageReport(unittest.TestCase):
    """Test usage report API."""

    def setUp(self):
        from core.impact_events import clear_session_events
        clear_session_events("test_report")

    def test_empty_report(self):
        """Empty session returns used=False."""
        from core.impact_events import get_usage_report

        with patch("core.impact_events._get_current_session_id", return_value="test_report"):
            report = get_usage_report()

        self.assertFalse(report["used"])
        self.assertEqual(report["statements"], [])

    def test_report_with_usage(self):
        """Session with events returns used=True."""
        from core.impact_events import record_solution_reused, get_usage_report

        with patch("core.impact_events._get_current_session_id", return_value="test_report"):
            record_solution_reused("sol_123", "Fixed bug")
            report = get_usage_report()

        self.assertTrue(report["used"])
        self.assertEqual(len(report["statements"]), 1)

    def test_report_is_json_serializable(self):
        """Report can be serialized to JSON."""
        import json
        from core.impact_events import record_solution_reused, get_usage_report

        with patch("core.impact_events._get_current_session_id", return_value="test_report"):
            record_solution_reused("sol_123", "Fixed bug")
            report = get_usage_report()

        json_str = json.dumps(report)
        self.assertIsInstance(json_str, str)

        # Should round-trip
        parsed = json.loads(json_str)
        self.assertTrue(parsed["used"])
        self.assertEqual(parsed["used"], report["used"])


class TestClearOnRequest(unittest.TestCase):
    """Test clearing session events on request."""

    def setUp(self):
        from core.impact_events import clear_session_events
        clear_session_events("test_clear")

    def test_clear_session_returns_count(self):
        """clear_session_events returns count of cleared events."""
        from core.impact_events import record_impact_event, clear_session_events

        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_1",
            content_summary="Fix 1",
            session_id="test_clear",
        )
        record_impact_event(
            event_type="solution_reused",
            source_tool="fo_search",
            content_id="sol_2",
            content_summary="Fix 2",
            session_id="test_clear",
        )

        count = clear_session_events("test_clear")
        self.assertEqual(count, 2)

        # Second clear should return 0
        count = clear_session_events("test_clear")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
