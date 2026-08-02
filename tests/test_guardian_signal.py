#!/usr/bin/env python3
"""
Unit tests for GuardianSignal infrastructure.

Phase 1: Tests for the data contracts only - no aggregation, no policy integration.
"""

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.guardian_signal import (
    GuardianCategory,
    GuardianConcern,
    GuardianEvidence,
    GuardianSeverity,
    GuardianSignal,
    GuardianSource,
    get_categories_for_concern,
    validate_category_for_concern,
)
from core.intervention_policy import InterventionContext


class TestGuardianEvidence(unittest.TestCase):
    """Tests for GuardianEvidence dataclass."""

    def test_empty_evidence_valid(self):
        """Empty evidence is valid - all fields are optional."""
        evidence = GuardianEvidence()
        self.assertIsNone(evidence.file_path)
        self.assertIsNone(evidence.operation)

    def test_partial_evidence_valid(self):
        """Partial evidence with only some fields populated."""
        evidence = GuardianEvidence(
            file_path="src/core/foo.py",
            line_number=42,
        )
        self.assertEqual(evidence.file_path, "src/core/foo.py")
        self.assertEqual(evidence.line_number, 42)
        self.assertIsNone(evidence.operation)

    def test_full_evidence_valid(self):
        """Full evidence with all fields populated."""
        evidence = GuardianEvidence(
            file_path="src/core/foo.py",
            line_number=42,
            operation="write",
            tool_name="fo_sync",
            matched_pattern="AVOID: direct db access",
            related_decision_id="dec_001",
            related_solution_id="sol_002",
            similarity_score=0.87,
            context_snippet="def dangerous_function():",
        )
        self.assertEqual(evidence.file_path, "src/core/foo.py")
        self.assertEqual(evidence.similarity_score, 0.87)

    def test_evidence_is_immutable(self):
        """GuardianEvidence should be frozen (immutable)."""
        evidence = GuardianEvidence(file_path="test.py")
        with self.assertRaises(Exception):
            evidence.file_path = "other.py"  # type: ignore

    def test_to_dict_excludes_none(self):
        """to_dict only includes non-None values."""
        evidence = GuardianEvidence(file_path="test.py", line_number=10)
        d = evidence.to_dict()
        self.assertEqual(d, {"file_path": "test.py", "line_number": 10})
        self.assertNotIn("operation", d)

    def test_from_dict_roundtrip(self):
        """from_dict correctly deserializes."""
        original = GuardianEvidence(
            file_path="src/foo.py",
            operation="delete",
            similarity_score=0.95,
        )
        d = original.to_dict()
        restored = GuardianEvidence.from_dict(d)
        self.assertEqual(restored, original)

    def test_json_roundtrip(self):
        """to_json and from_json preserve data."""
        original = GuardianEvidence(
            file_path="src/foo.py",
            tool_name="fo_apply",
        )
        json_str = original.to_json()
        restored = GuardianEvidence.from_json(json_str)
        self.assertEqual(restored, original)


class TestGuardianSignal(unittest.TestCase):
    """Tests for GuardianSignal dataclass."""

    def test_minimal_valid_signal(self):
        """Minimal valid signal with required fields."""
        signal = GuardianSignal(
            concern="risk",
            source="detector",
            category="risk_destructive_op",
            severity="high",
            confidence=0.9,
            reason="File deletion detected",
        )
        self.assertEqual(signal.concern, "risk")
        self.assertEqual(signal.severity, "high")
        self.assertIsInstance(signal.evidence, GuardianEvidence)

    def test_signal_with_evidence(self):
        """Signal with full evidence attached."""
        evidence = GuardianEvidence(
            file_path="src/db/schema.py",
            operation="delete",
        )
        signal = GuardianSignal(
            concern="risk",
            source="agent",
            category="risk_agent_declared",
            severity="medium",
            confidence=0.75,
            reason="Agent flagged risky operation",
            evidence=evidence,
        )
        self.assertEqual(signal.evidence.file_path, "src/db/schema.py")

    def test_signal_is_immutable(self):
        """GuardianSignal should be frozen (immutable)."""
        signal = GuardianSignal(
            concern="error",
            source="detector",
            category="error_live_browser",
            severity="high",
            confidence=1.0,
            reason="Browser error detected",
        )
        with self.assertRaises(Exception):
            signal.severity = "low"  # type: ignore

    def test_timestamp_auto_generated(self):
        """Timestamp is automatically generated."""
        signal = GuardianSignal(
            concern="compliance",
            source="detector",
            category="compliance_sync_needed",
            severity="low",
            confidence=0.8,
            reason="fo_sync not called",
        )
        self.assertIsNotNone(signal.timestamp)
        # Should be valid ISO format
        datetime.fromisoformat(signal.timestamp)


class TestGuardianSignalValidation(unittest.TestCase):
    """Tests for GuardianSignal validation rules."""

    def test_confidence_must_be_in_range(self):
        """confidence must be between 0.0 and 1.0."""
        with self.assertRaises(ValueError) as ctx:
            GuardianSignal(
                concern="risk",
                source="detector",
                category="risk_destructive_op",
                severity="high",
                confidence=1.5,  # Invalid
                reason="Test",
            )
        self.assertIn("confidence", str(ctx.exception))

    def test_confidence_negative_invalid(self):
        """Negative confidence is invalid."""
        with self.assertRaises(ValueError):
            GuardianSignal(
                concern="risk",
                source="detector",
                category="risk_destructive_op",
                severity="high",
                confidence=-0.1,
                reason="Test",
            )

    def test_confidence_zero_valid(self):
        """confidence=0.0 is valid (very uncertain)."""
        signal = GuardianSignal(
            concern="risk",
            source="llm",
            category="risk_unknown_impact",
            severity="low",
            confidence=0.0,
            reason="Very uncertain",
        )
        self.assertEqual(signal.confidence, 0.0)

    def test_confidence_one_valid(self):
        """confidence=1.0 is valid (completely certain)."""
        signal = GuardianSignal(
            concern="error",
            source="detector",
            category="error_live_browser",
            severity="critical",
            confidence=1.0,
            reason="Absolute certainty",
        )
        self.assertEqual(signal.confidence, 1.0)

    def test_category_must_match_concern(self):
        """category must start with concern_ prefix."""
        with self.assertRaises(ValueError) as ctx:
            GuardianSignal(
                concern="risk",
                source="detector",
                category="error_live_browser",  # Wrong prefix
                severity="high",
                confidence=0.9,
                reason="Test",
            )
        self.assertIn("must start with concern", str(ctx.exception))

    def test_reason_cannot_be_empty(self):
        """reason must not be empty."""
        with self.assertRaises(ValueError) as ctx:
            GuardianSignal(
                concern="risk",
                source="detector",
                category="risk_destructive_op",
                severity="high",
                confidence=0.9,
                reason="",
            )
        self.assertIn("empty", str(ctx.exception))

    def test_reason_cannot_be_whitespace_only(self):
        """reason must not be whitespace only."""
        with self.assertRaises(ValueError):
            GuardianSignal(
                concern="risk",
                source="detector",
                category="risk_destructive_op",
                severity="high",
                confidence=0.9,
                reason="   ",
            )


class TestGuardianSignalSerialization(unittest.TestCase):
    """Tests for GuardianSignal serialization."""

    def test_to_dict(self):
        """to_dict produces correct structure."""
        signal = GuardianSignal(
            concern="conflict",
            source="detector",
            category="conflict_decision",
            severity="medium",
            confidence=0.85,
            reason="Conflicts with existing decision",
            evidence=GuardianEvidence(related_decision_id="dec_001"),
        )
        d = signal.to_dict()
        self.assertEqual(d["concern"], "conflict")
        self.assertEqual(d["source"], "detector")
        self.assertEqual(d["category"], "conflict_decision")
        self.assertEqual(d["severity"], "medium")
        self.assertEqual(d["confidence"], 0.85)
        self.assertEqual(d["reason"], "Conflicts with existing decision")
        self.assertEqual(d["evidence"]["related_decision_id"], "dec_001")
        self.assertIn("timestamp", d)

    def test_from_dict_roundtrip(self):
        """from_dict correctly deserializes."""
        original = GuardianSignal(
            concern="opportunity",
            source="detector",
            category="opportunity_past_solution",
            severity="medium",
            confidence=0.9,
            reason="Similar bug found",
            evidence=GuardianEvidence(
                related_solution_id="sol_005",
                similarity_score=0.88,
            ),
        )
        d = original.to_dict()
        restored = GuardianSignal.from_dict(d)
        self.assertEqual(restored.concern, original.concern)
        self.assertEqual(restored.source, original.source)
        self.assertEqual(restored.category, original.category)
        self.assertEqual(restored.severity, original.severity)
        self.assertEqual(restored.confidence, original.confidence)
        self.assertEqual(restored.reason, original.reason)
        self.assertEqual(restored.evidence.related_solution_id, "sol_005")

    def test_json_roundtrip(self):
        """to_json and from_json preserve data."""
        original = GuardianSignal(
            concern="compliance",
            source="detector",
            category="compliance_solved_needed",
            severity="low",
            confidence=0.7,
            reason="fo_solved should be called",
        )
        json_str = original.to_json()
        restored = GuardianSignal.from_json(json_str)
        self.assertEqual(restored.concern, original.concern)
        self.assertEqual(restored.reason, original.reason)

    def test_json_valid_format(self):
        """to_json produces valid JSON."""
        signal = GuardianSignal(
            concern="error",
            source="user",
            category="error_auto_fix_ready",
            severity="high",
            confidence=1.0,
            reason="User reported auto-fix ready",
        )
        json_str = signal.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["concern"], "error")


class TestGuardianSignalSeveritySemantics(unittest.TestCase):
    """Tests documenting severity semantics.

    Severity represents INTERVENTION INTENSITY, not risk severity.
    These tests document the expected interpretation.
    """

    def test_opportunity_high_severity_meaning(self):
        """High severity opportunity = strongly encourage reuse, not 'bad'."""
        signal = GuardianSignal(
            concern="opportunity",
            source="detector",
            category="opportunity_past_solution",
            severity="high",  # Strong intervention: "You should definitely use this"
            confidence=0.95,
            reason="Nearly identical bug solved 3 days ago",
            evidence=GuardianEvidence(related_solution_id="sol_123"),
        )
        self.assertEqual(signal.severity, "high")
        self.assertEqual(signal.concern, "opportunity")

    def test_compliance_medium_severity_meaning(self):
        """Medium severity compliance = gentle reminder."""
        signal = GuardianSignal(
            concern="compliance",
            source="detector",
            category="compliance_sync_needed",
            severity="medium",  # Moderate intervention: "Don't forget to sync"
            confidence=0.8,
            reason="Significant work completed without fo_sync",
        )
        self.assertEqual(signal.severity, "medium")
        self.assertEqual(signal.concern, "compliance")


class TestGuardianCategoryValidation(unittest.TestCase):
    """Tests for category validation helpers."""

    def test_validate_category_for_concern_valid(self):
        """Valid category-concern pairs return True."""
        self.assertTrue(validate_category_for_concern("risk_destructive_op", "risk"))
        self.assertTrue(validate_category_for_concern("error_live_browser", "error"))
        self.assertTrue(validate_category_for_concern("conflict_decision", "conflict"))

    def test_validate_category_for_concern_invalid(self):
        """Invalid category-concern pairs return False."""
        self.assertFalse(validate_category_for_concern("error_live_browser", "risk"))
        self.assertFalse(validate_category_for_concern("risk_destructive_op", "error"))

    def test_get_categories_for_concern(self):
        """get_categories_for_concern returns correct categories."""
        risk_cats = get_categories_for_concern("risk")
        self.assertIn("risk_destructive_op", risk_cats)
        self.assertIn("risk_protected_area", risk_cats)
        self.assertIn("risk_unknown_impact", risk_cats)
        self.assertIn("risk_agent_declared", risk_cats)
        self.assertNotIn("error_live_browser", risk_cats)

    def test_all_concerns_have_categories(self):
        """Every concern type has at least one category."""
        concerns = ["error", "conflict", "risk", "opportunity", "compliance"]
        for concern in concerns:
            cats = get_categories_for_concern(concern)
            self.assertGreater(len(cats), 0, f"No categories for {concern}")


class TestInterventionContextGuardianSignals(unittest.TestCase):
    """Tests for guardian_signals field in InterventionContext."""

    def test_guardian_signals_defaults_to_empty_tuple(self):
        """guardian_signals defaults to empty tuple."""
        ctx = InterventionContext()
        self.assertEqual(ctx.guardian_signals, ())

    def test_guardian_signals_accepts_tuple_of_signals(self):
        """guardian_signals can be populated with signals."""
        signal = GuardianSignal(
            concern="risk",
            source="agent",
            category="risk_agent_declared",
            severity="medium",
            confidence=0.8,
            reason="Agent flagged this operation",
        )
        ctx = InterventionContext(guardian_signals=(signal,))
        self.assertEqual(len(ctx.guardian_signals), 1)
        self.assertEqual(ctx.guardian_signals[0].concern, "risk")

    def test_guardian_signals_multiple(self):
        """Multiple signals can be attached."""
        signal1 = GuardianSignal(
            concern="risk",
            source="detector",
            category="risk_destructive_op",
            severity="high",
            confidence=0.95,
            reason="Delete operation",
        )
        signal2 = GuardianSignal(
            concern="opportunity",
            source="detector",
            category="opportunity_past_solution",
            severity="medium",
            confidence=0.8,
            reason="Similar bug found",
        )
        ctx = InterventionContext(guardian_signals=(signal1, signal2))
        self.assertEqual(len(ctx.guardian_signals), 2)
        concerns = [s.concern for s in ctx.guardian_signals]
        self.assertIn("risk", concerns)
        self.assertIn("opportunity", concerns)

    def test_existing_fields_unchanged(self):
        """Adding guardian_signals doesn't affect existing fields."""
        ctx = InterventionContext(
            live_errors=2,
            risky_change=True,
            guardian_signals=(),
        )
        self.assertEqual(ctx.live_errors, 2)
        self.assertTrue(ctx.risky_change)

    def test_guardian_signals_is_tuple_not_list(self):
        """guardian_signals is tuple (immutable), not list."""
        ctx = InterventionContext()
        self.assertIsInstance(ctx.guardian_signals, tuple)


class TestGuardianSignalAllConcerns(unittest.TestCase):
    """Test that all concern types can create valid signals."""

    def test_error_signal(self):
        """error concern with valid category."""
        signal = GuardianSignal(
            concern="error",
            source="detector",
            category="error_live_browser",
            severity="high",
            confidence=1.0,
            reason="Browser error detected",
        )
        self.assertEqual(signal.concern, "error")

    def test_conflict_signal(self):
        """conflict concern with valid category."""
        signal = GuardianSignal(
            concern="conflict",
            source="detector",
            category="conflict_avoid_pattern",
            severity="high",
            confidence=0.9,
            reason="Matches AVOID pattern",
        )
        self.assertEqual(signal.concern, "conflict")

    def test_risk_signal(self):
        """risk concern with valid category."""
        signal = GuardianSignal(
            concern="risk",
            source="agent",
            category="risk_agent_declared",
            severity="medium",
            confidence=0.75,
            reason="Agent declared risky",
        )
        self.assertEqual(signal.concern, "risk")

    def test_opportunity_signal(self):
        """opportunity concern with valid category."""
        signal = GuardianSignal(
            concern="opportunity",
            source="detector",
            category="opportunity_reuse",
            severity="low",
            confidence=0.6,
            reason="Consider reusing pattern",
        )
        self.assertEqual(signal.concern, "opportunity")

    def test_compliance_signal(self):
        """compliance concern with valid category."""
        signal = GuardianSignal(
            concern="compliance",
            source="detector",
            category="compliance_review_needed",
            severity="medium",
            confidence=0.85,
            reason="Review required before merge",
        )
        self.assertEqual(signal.concern, "compliance")


class TestGuardianSignalAllSources(unittest.TestCase):
    """Test that all source types can create valid signals."""

    def test_agent_source(self):
        """agent source is valid."""
        signal = GuardianSignal(
            concern="risk",
            source="agent",
            category="risk_agent_declared",
            severity="medium",
            confidence=0.8,
            reason="Agent declared this risky",
        )
        self.assertEqual(signal.source, "agent")

    def test_llm_source(self):
        """llm source is valid."""
        signal = GuardianSignal(
            concern="conflict",
            source="llm",
            category="conflict_semantic",
            severity="medium",
            confidence=0.7,
            reason="LLM detected semantic conflict",
        )
        self.assertEqual(signal.source, "llm")

    def test_detector_source(self):
        """detector source is valid."""
        signal = GuardianSignal(
            concern="error",
            source="detector",
            category="error_build_failure",
            severity="critical",
            confidence=1.0,
            reason="Build failed",
        )
        self.assertEqual(signal.source, "detector")

    def test_user_source(self):
        """user source is valid."""
        signal = GuardianSignal(
            concern="risk",
            source="user",
            category="risk_protected_area",
            severity="high",
            confidence=1.0,
            reason="User marked this area protected",
        )
        self.assertEqual(signal.source, "user")


if __name__ == "__main__":
    unittest.main()
