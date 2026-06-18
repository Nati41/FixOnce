"""
Phase 2 Auto-Context Tests

Regression tests for:
1. Fix fo_decide false positives (STOP_WORDS expansion)
2. Improve relevance quality (60% threshold)
3. Solved bugs auto-injection

Run: python3 -m pytest tests/test_phase2_auto_context.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ============================================================
# Test 1: fo_decide False Positive Regression Tests
# ============================================================

class TestConflictDetectionFalsePositives(unittest.TestCase):
    """
    Regression tests for false positive conflict detection.

    These words were causing false positive blocks in fo_decide:
    - manual, explicit, only, auto, memory, fixonce, provide
    """

    def setUp(self):
        from core.policy_engine import detect_antonym_conflict
        self.detect = detect_antonym_conflict

    def test_manual_not_flagged_as_conflict(self):
        """'without manual fo_search' should not conflict with 'manual cleanup'."""
        text1 = "Memory injection happens automatically without manual fo_search"
        text2 = "AI Commands auto-cleanup: Clear History button for manual cleanup"
        result = self.detect(text1, text2)
        self.assertIsNone(result, f"False positive: {result}")

    def test_explicit_not_flagged_as_conflict(self):
        """'without explicit' should not conflict with 'explicit marker'."""
        text1 = "Injection works without explicit MCP tool calls"
        text2 = "AI Command Injection Security Layer with Explicit Marker Lock"
        result = self.detect(text1, text2)
        self.assertIsNone(result, f"False positive: {result}")

    def test_only_not_flagged_as_conflict(self):
        """'not only' should not conflict with 'only' in unrelated context."""
        text1 = "Memory injection happens on file access, not only on MCP calls"
        text2 = "Store all data in Hebrew only"
        result = self.detect(text1, text2)
        self.assertIsNone(result, f"False positive: {result}")

    def test_auto_not_flagged_as_conflict(self):
        """'auto' should not conflict with 'cannot auto-detect'."""
        text1 = "Phase 1 auto-context injection works"
        text2 = "Extension required, FixOnce cannot auto-detect browser errors"
        result = self.detect(text1, text2)
        self.assertIsNone(result, f"False positive: {result}")

    def test_memory_not_flagged_as_conflict(self):
        """'memory' should not conflict with 'not memory'."""
        text1 = "Project memory injection is automatic"
        text2 = "Vision V1: decisions judging is not memory dependent"
        result = self.detect(text1, text2)
        self.assertIsNone(result, f"False positive: {result}")

    def test_fixonce_not_flagged_as_conflict(self):
        """'fixonce' should not conflict with 'doesn't fixonce'."""
        text1 = "FixOnce direction is context-before-action"
        text2 = "Dogfooding: AI must use FixOnce MCP tools"
        result = self.detect(text1, text2)
        self.assertIsNone(result, f"False positive: {result}")

    def test_provide_not_flagged_as_conflict(self):
        """'provide' should not conflict with 'doesn't provide'."""
        text1 = "The system will provide relevant context"
        text2 = "MVP doesn't provide advanced analytics"
        result = self.detect(text1, text2)
        self.assertIsNone(result, f"False positive: {result}")

    def test_real_contradiction_still_detected(self):
        """Real contradictions should still be detected."""
        text1 = "Use PostgreSQL for the database"
        text2 = "Do not use PostgreSQL"
        result = self.detect(text1, text2)
        self.assertIsNotNone(result, "Real contradiction should be detected")
        self.assertEqual(result[2], "HIGH")

    def test_english_hebrew_still_detected(self):
        """Language contradictions should still be detected."""
        text1 = "Store data in English"
        text2 = "Store data in Hebrew"
        result = self.detect(text1, text2)
        self.assertIsNotNone(result, "Language contradiction should be detected")


# ============================================================
# Test 2: Relevance Quality (60% Threshold)
# ============================================================

class MockSearchResult:
    def __init__(self, text: str, score: float):
        self.text = text
        self.score = score


class TestRelevanceThreshold(unittest.TestCase):
    """Tests for 60% relevance threshold filtering."""

    def test_filters_below_60_percent(self):
        """Results below 60% should be filtered out."""
        from api.activity import _get_relevant_project_memory

        mock_results_high = [MockSearchResult("High relevance decision", 0.75)]
        mock_results_low = [MockSearchResult("Low relevance noise", 0.45)]

        def mock_search(project_id, query, k=2, doc_type=None, min_score=0.25):
            if min_score >= 0.60:
                return mock_results_high
            return mock_results_high + mock_results_low

        with patch("api.activity._get_project_id_from_file", return_value="test_project"):
            with patch("core.project_semantic.search_project", side_effect=mock_search) as mock:
                result = _get_relevant_project_memory("/src/core/test.py", "core")

                # Verify min_score=0.60 is passed
                for call in mock.call_args_list:
                    self.assertGreaterEqual(call.kwargs.get("min_score", 0), 0.60)

    def test_keeps_results_above_60_percent(self):
        """Results above 60% should be kept."""
        from api.activity import _get_relevant_project_memory

        mock_results = [
            MockSearchResult("High relevance", 0.85),
            MockSearchResult("Medium-high relevance", 0.65),
        ]

        with patch("api.activity._get_project_id_from_file", return_value="test_project"):
            with patch("core.project_semantic.search_project", return_value=mock_results):
                result = _get_relevant_project_memory("/src/core/test.py", "core")
                self.assertEqual(len(result["decisions"]), 2)


# ============================================================
# Test 3: Solved Bugs Auto-Injection
# ============================================================

class TestSolvedBugsInjection(unittest.TestCase):
    """Tests for solved bugs appearing in area-context."""

    def test_rebuild_indexes_debug_sessions(self):
        """rebuild_project_index should index solved bugs from debug_sessions."""
        # This is a code inspection test - verify the indexing code exists
        import inspect
        from core.project_semantic import rebuild_project_index

        source = inspect.getsource(rebuild_project_index)

        # Verify debug_sessions indexing code exists
        self.assertIn("debug_sessions", source)
        self.assertIn('index.add("error"', source)
        self.assertIn("Error:", source)
        self.assertIn("Solution:", source)

    def test_fo_solved_indexes_to_project_semantic(self):
        """fo_solved should index to project semantic index."""
        # This is an integration test - verify the index_error call exists
        import ast

        mcp_server_path = PROJECT_ROOT / "src" / "mcp_server" / "mcp_memory_server_v2.py"
        with open(mcp_server_path, 'r') as f:
            content = f.read()

        # Check that index_error is imported and called
        self.assertIn("from core.project_semantic import index_error", content)
        self.assertIn("index_error(session.project_id", content)

    def test_solved_bugs_appear_in_format(self):
        """Solved bugs should appear with ✅ Solved format."""
        from api.activity import _format_project_memory_section

        memory = {
            "decisions": [],
            "solved": [
                {"text": "Error: null pointer. Solution: add check", "score": 78}
            ],
            "avoid": [],
        }

        lines = _format_project_memory_section(memory)
        solved_lines = [l for l in lines if "✅ Solved" in l]
        self.assertEqual(len(solved_lines), 1)
        self.assertIn("78%", solved_lines[0])


# ============================================================
# Integration Tests
# ============================================================

class TestPhase2Integration(unittest.TestCase):
    """Integration tests for Phase 2 changes."""

    def test_stop_words_includes_all_known_false_positives(self):
        """Verify STOP_WORDS includes all known false positive triggers."""
        from core.policy_engine import detect_antonym_conflict
        import inspect

        source = inspect.getsource(detect_antonym_conflict)

        required_words = [
            "manual", "explicit", "auto", "only", "memory", "fixonce", "provide",
            "automatically", "specifically", "directly", "actually",
        ]

        for word in required_words:
            self.assertIn(f'"{word}"', source, f"STOP_WORDS missing: {word}")

    def test_min_score_is_60_in_activity(self):
        """Verify min_score=0.60 is used in _get_relevant_project_memory."""
        import inspect
        from api.activity import _get_relevant_project_memory

        source = inspect.getsource(_get_relevant_project_memory)
        self.assertIn("min_score=0.60", source)
        self.assertNotIn("min_score=0.25", source)


if __name__ == "__main__":
    unittest.main()
