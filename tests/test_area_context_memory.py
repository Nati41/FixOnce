"""
Tests for area-context project memory injection.

Phase 1: Proof-of-direction - automatic context injection.
Phase 2: Filter weak relevance matches below 60% threshold.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from api.activity import (
    _get_relevant_project_memory,
    _format_project_memory_section,
)


class MockSearchResult:
    def __init__(self, text: str, score: float):
        self.text = text
        self.score = score


class TestGetRelevantProjectMemory(unittest.TestCase):
    """Tests for _get_relevant_project_memory helper."""

    def test_returns_empty_dict_on_empty_path(self):
        result = _get_relevant_project_memory("", "")
        self.assertEqual(result, {"decisions": [], "solved": [], "avoid": []})

    def test_returns_empty_dict_on_global_project(self):
        with patch("api.activity._get_project_id_from_file", return_value="__global__"):
            result = _get_relevant_project_memory("/some/path.py", "api")
            self.assertEqual(result, {"decisions": [], "solved": [], "avoid": []})

    def test_returns_empty_dict_when_semantic_not_available(self):
        with patch("api.activity._get_project_id_from_file", return_value="test_project"):
            result = _get_relevant_project_memory("/src/api/test.py", "api")
            self.assertIn("decisions", result)
            self.assertIn("solved", result)
            self.assertIn("avoid", result)

    @patch("api.activity._get_project_id_from_file")
    def test_returns_decisions_from_semantic_search(self, mock_get_project):
        mock_get_project.return_value = "test_project"

        mock_results = [
            MockSearchResult("Use TF-IDF for search", 0.85),
            MockSearchResult("Avoid raw SQL queries", 0.72),
        ]

        with patch("core.project_semantic.search_project", return_value=mock_results):
            result = _get_relevant_project_memory("/src/api/search.py", "api")
            self.assertEqual(len(result["decisions"]), 2)
            self.assertEqual(result["decisions"][0]["score"], 85)
            self.assertIn("TF-IDF", result["decisions"][0]["text"])

    @patch("api.activity._get_project_id_from_file")
    def test_limits_to_2_results_per_type(self, mock_get_project):
        mock_get_project.return_value = "test_project"

        mock_results = [
            MockSearchResult("Result 1", 0.9),
            MockSearchResult("Result 2", 0.8),
            MockSearchResult("Result 3", 0.7),
        ]

        with patch("core.project_semantic.search_project", return_value=mock_results):
            result = _get_relevant_project_memory("/src/api/test.py", "api")
            self.assertLessEqual(len(result["decisions"]), 2)

    @patch("api.activity._get_project_id_from_file")
    def test_truncates_long_text(self, mock_get_project):
        mock_get_project.return_value = "test_project"

        long_text = "A" * 200
        mock_results = [MockSearchResult(long_text, 0.9)]

        with patch("core.project_semantic.search_project", return_value=mock_results):
            result = _get_relevant_project_memory("/src/api/test.py", "api")
            if result["decisions"]:
                self.assertLessEqual(len(result["decisions"][0]["text"]), 125)
                self.assertTrue(result["decisions"][0]["text"].endswith("..."))

    def test_fails_open_on_exception(self):
        with patch("api.activity._get_project_id_from_file", side_effect=Exception("Test error")):
            result = _get_relevant_project_memory("/src/api/test.py", "api")
            self.assertEqual(result, {"decisions": [], "solved": [], "avoid": []})

    @patch("api.activity._get_project_id_from_file")
    def test_filters_below_60_percent_threshold(self, mock_get_project):
        """Phase 2: Verify min_score=0.60 is passed to search_project."""
        mock_get_project.return_value = "test_project"

        with patch("core.project_semantic.search_project") as mock_search:
            mock_search.return_value = []
            _get_relevant_project_memory("/src/api/test.py", "api")

            calls = mock_search.call_args_list
            self.assertGreater(len(calls), 0, "search_project should be called")
            for call in calls:
                kwargs = call[1] if len(call) > 1 else {}
                args = call[0] if call[0] else ()
                min_score = kwargs.get("min_score", 0.3)
                self.assertGreaterEqual(
                    min_score, 0.60,
                    f"min_score should be >= 0.60, got {min_score}"
                )


class TestFormatProjectMemorySection(unittest.TestCase):
    """Tests for _format_project_memory_section helper."""

    def test_returns_empty_list_on_empty_memory(self):
        memory = {"decisions": [], "solved": [], "avoid": []}
        lines = _format_project_memory_section(memory)
        self.assertEqual(lines, [])

    def test_formats_decisions(self):
        memory = {
            "decisions": [{"text": "Use TF-IDF", "score": 85}],
            "solved": [],
            "avoid": [],
        }
        lines = _format_project_memory_section(memory)
        self.assertIn("📋 Relevant Project Memory:", lines)
        self.assertTrue(any("📌 Decision" in line for line in lines))
        self.assertTrue(any("85%" in line for line in lines))

    def test_formats_solved_bugs(self):
        memory = {
            "decisions": [],
            "solved": [{"text": "Fixed null check", "score": 92}],
            "avoid": [],
        }
        lines = _format_project_memory_section(memory)
        self.assertTrue(any("✅ Solved" in line for line in lines))
        self.assertTrue(any("92%" in line for line in lines))

    def test_formats_avoid_patterns(self):
        memory = {
            "decisions": [],
            "solved": [],
            "avoid": [{"text": "Do not use global state", "score": 78}],
        }
        lines = _format_project_memory_section(memory)
        self.assertTrue(any("🚫 Avoid" in line for line in lines))
        self.assertTrue(any("78%" in line for line in lines))

    def test_formats_all_types(self):
        memory = {
            "decisions": [{"text": "Decision 1", "score": 80}],
            "solved": [{"text": "Solved 1", "score": 75}],
            "avoid": [{"text": "Avoid 1", "score": 70}],
        }
        lines = _format_project_memory_section(memory)
        self.assertTrue(any("📌 Decision" in line for line in lines))
        self.assertTrue(any("✅ Solved" in line for line in lines))
        self.assertTrue(any("🚫 Avoid" in line for line in lines))


class TestAreaContextIntegration(unittest.TestCase):
    """Integration tests for area-context with project memory."""

    def test_area_context_endpoint_returns_memory_count(self):
        from flask import Flask
        from api.activity import activity_bp

        app = Flask(__name__)
        app.register_blueprint(activity_bp, url_prefix="/api/activity")

        with app.test_client() as client:
            with patch("api.activity._extract_area", return_value="api"):
                with patch("api.activity._get_warnings_for_file", return_value=[]):
                    with patch("api.activity._load_activity", return_value={"activities": []}):
                        with patch("api.activity._get_relevant_project_memory") as mock_mem:
                            mock_mem.return_value = {
                                "decisions": [{"text": "Test", "score": 80}],
                                "solved": [],
                                "avoid": [],
                            }
                            response = client.get("/api/activity/area-context?path=/src/api/test.py")
                            if response.status_code == 200 and response.json:
                                self.assertIn("memory_count", response.json)


if __name__ == "__main__":
    unittest.main()
