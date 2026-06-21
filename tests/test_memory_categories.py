"""
Tests for Memory Categories V1.

Tests the universal memory taxonomy:
- Category definitions
- Quality assessment
- Display mapping
- Backward compatibility
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pytest
from core.memory_categories import (
    Category,
    CATEGORY_DISPLAY,
    get_display,
    format_header,
    assess_quality,
    should_show_as_fix,
    category_from_match_type,
    MATCH_TYPE_TO_CATEGORY,
)


class TestCategoryDefinitions:
    """Test category constants and display mapping."""

    def test_all_categories_have_display(self):
        """Every category has a display mapping."""
        categories = ["fix", "decision", "avoid", "regression", "insight", "handoff", "work", "unknown"]
        for cat in categories:
            assert cat in CATEGORY_DISPLAY, f"Missing display for {cat}"

    def test_get_display_returns_tuple(self):
        """get_display returns (icon, label) tuple."""
        icon, label = get_display("fix")
        assert icon == "✅"
        assert label == "SOLVED BEFORE"

    def test_get_display_unknown_fallback(self):
        """Unknown category falls back to 'unknown' display."""
        icon, label = get_display("nonexistent")
        assert icon == "❓"
        assert label == "RELATED MEMORY"

    def test_format_header(self):
        """format_header creates proper markdown."""
        assert format_header("fix") == "✅ **SOLVED BEFORE**"
        assert format_header("work") == "🔧 **RELATED WORK**"
        assert format_header("decision") == "📌 **ACTIVE DECISION**"


class TestQualityAssessment:
    """Test quality assessment logic."""

    def test_fix_high_quality(self):
        """Fix with root_cause and action_now is high quality."""
        metadata = {
            "root_cause": "Missing null check",
            "action_now": "Add optional chaining",
            "solution": "Fixed it",
        }
        result = assess_quality("fix", metadata)
        assert result["quality"] == "high"
        assert result["actionable"] is True
        assert result["missing"] == []

    def test_fix_medium_quality_missing_root_cause(self):
        """Fix missing root_cause but with solution is medium quality."""
        metadata = {
            "action_now": "Add null check",
            "solution": "Added the check",
        }
        result = assess_quality("fix", metadata)
        assert result["quality"] == "medium"
        assert "root_cause" in result["missing"]

    def test_fix_low_quality_no_action(self):
        """Fix without actionable fields is low quality."""
        metadata = {}
        result = assess_quality("fix", metadata)
        assert result["quality"] == "low"
        assert result["actionable"] is False

    def test_decision_with_reason_is_high(self):
        """Decision with reason is high quality."""
        metadata = {"reason": "Performance considerations"}
        result = assess_quality("decision", metadata)
        assert result["quality"] in ("high", "medium")

    def test_insight_always_passes(self):
        """Insight has no required fields."""
        result = assess_quality("insight", {})
        assert result["missing"] == []


class TestShouldShowAsFix:
    """Test the should_show_as_fix logic."""

    def test_non_fix_category_returns_false(self):
        """Non-fix categories never show as fix."""
        assert should_show_as_fix("work", {"root_cause": "x", "action_now": "y"}) is False
        assert should_show_as_fix("insight", {"root_cause": "x"}) is False
        assert should_show_as_fix("decision", {}) is False

    def test_fix_high_quality_returns_true(self):
        """High quality fix shows as fix."""
        metadata = {"root_cause": "Bug", "action_now": "Fix it", "solution": "Done"}
        assert should_show_as_fix("fix", metadata) is True

    def test_fix_medium_quality_returns_true(self):
        """Medium quality fix still shows as fix."""
        metadata = {"solution": "Fixed"}
        assert should_show_as_fix("fix", metadata) is True

    def test_fix_low_quality_returns_false(self):
        """Low quality fix does not show as fix."""
        metadata = {}
        assert should_show_as_fix("fix", metadata) is False


class TestBackwardCompatibility:
    """Test mapping from legacy match_types to categories."""

    def test_solution_maps_to_fix(self):
        """Legacy 'solution' match_type maps to 'fix' category."""
        assert category_from_match_type("solution") == "fix"

    def test_decision_maps_to_decision(self):
        """'decision' stays as 'decision'."""
        assert category_from_match_type("decision") == "decision"

    def test_avoid_maps_to_avoid(self):
        """'avoid' stays as 'avoid'."""
        assert category_from_match_type("avoid") == "avoid"

    def test_failed_attempt_maps_to_avoid(self):
        """'failed_attempt' maps to 'avoid'."""
        assert category_from_match_type("failed_attempt") == "avoid"

    def test_insight_maps_to_insight(self):
        """'insight' stays as 'insight'."""
        assert category_from_match_type("insight") == "insight"

    def test_component_maps_to_work(self):
        """'component' maps to 'work'."""
        assert category_from_match_type("component") == "work"

    def test_unknown_type_maps_to_unknown(self):
        """Unknown match_type maps to 'unknown'."""
        assert category_from_match_type("some_new_type") == "unknown"
