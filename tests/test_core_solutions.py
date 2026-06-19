"""
Tests for core solutions module.

These tests prove that solutions can be recorded without MCP.
"""

import sys
from pathlib import Path

TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import unittest
from unittest.mock import patch, MagicMock

from core.solutions import record_solution, SolutionResult


class TestRecordSolution(unittest.TestCase):
    """Test record_solution function."""

    def test_requires_project_id(self):
        """Should fail without project_id."""
        result = record_solution(
            project_id="",
            error_message="Test error",
            solution="Test solution",
        )
        self.assertFalse(result.success)
        self.assertIn("project_id", result.message)

    def test_requires_error_message(self):
        """Should fail without error_message."""
        result = record_solution(
            project_id="test-project",
            error_message="",
            solution="Test solution",
        )
        self.assertFalse(result.success)
        self.assertIn("error_message", result.message)

    def test_requires_solution(self):
        """Should fail without solution."""
        result = record_solution(
            project_id="test-project",
            error_message="Test error",
            solution="",
        )
        self.assertFalse(result.success)
        self.assertIn("solution", result.message)

    def test_records_to_debug_sessions(self):
        """Should add solution to debug_sessions."""
        memory = {"debug_sessions": []}
        saved = {}

        def mock_save(pid, mem):
            saved["project_id"] = pid
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="TypeError: undefined is not a function",
            solution="Fixed by adding null check",
            actor="claude",
            actor_source="mcp_session",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success)
        self.assertEqual(saved["project_id"], "test-project")
        self.assertEqual(len(saved["memory"]["debug_sessions"]), 1)

        session = saved["memory"]["debug_sessions"][0]
        self.assertIn("TypeError", session["problem"])
        self.assertIn("null check", session["solution"])
        self.assertEqual(session["actor"], "claude")
        self.assertEqual(session["actor_source"], "mcp_session")

    def test_records_files_changed(self):
        """Should record files_changed in solution."""
        memory = {"debug_sessions": []}
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="Build error",
            solution="Fixed imports",
            files_changed=["src/app.ts", "src/utils.ts"],
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success)
        session = saved["memory"]["debug_sessions"][0]
        self.assertEqual(session["files_changed"], ["src/app.ts", "src/utils.ts"])

    def test_updates_existing_solution(self):
        """Should update reuse_count for duplicate error."""
        memory = {
            "debug_sessions": [
                {
                    "id": "fix_old",
                    "problem": "TypeError: cannot read property",
                    "solution": "Old solution",
                    "reuse_count": 0,
                }
            ]
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="TypeError: cannot read property 'x' of undefined",
            solution="Better solution",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success)
        self.assertTrue(result.is_update)
        self.assertEqual(result.message, "Solution updated.")

        # Should update existing, not add new
        self.assertEqual(len(saved["memory"]["debug_sessions"]), 1)
        session = saved["memory"]["debug_sessions"][0]
        self.assertEqual(session["reuse_count"], 1)
        self.assertEqual(session["solution"], "Better solution")

    def test_creates_new_for_different_error(self):
        """Should create new solution for different error."""
        memory = {
            "debug_sessions": [
                {
                    "id": "fix_old",
                    "problem": "TypeError: something else",
                    "solution": "Old solution",
                }
            ]
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="SyntaxError: unexpected token",
            solution="Fixed syntax",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success)
        self.assertFalse(result.is_update)
        self.assertEqual(len(saved["memory"]["debug_sessions"]), 2)

    def test_full_flow_without_mcp(self):
        """Should work completely without MCP - record and retrieve."""
        memory = {"debug_sessions": []}
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Record a solution
        result = record_solution(
            project_id="test-project",
            error_message="API timeout error",
            solution="Added retry logic with exponential backoff",
            files_changed=["src/api/client.ts"],
            actor="dashboard",
            actor_source="web_ui",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success)
        self.assertIn("solution_id", dir(result))
        self.assertIsNotNone(result.solution_id)

        # Verify the solution is in memory
        session = saved["memory"]["debug_sessions"][0]
        self.assertIn("timeout", session["problem"])
        self.assertIn("retry", session["solution"])
        self.assertEqual(session["actor"], "dashboard")

    def test_attribution_from_different_sources(self):
        """Should accept attribution from any source."""
        test_cases = [
            ("claude", "mcp_session"),
            ("user", "dashboard_commit"),
            ("api", "rest_endpoint"),
            ("cli", "terminal"),
        ]

        for actor, actor_source in test_cases:
            memory = {"debug_sessions": []}
            saved = {}

            def mock_save(pid, mem, s=saved):
                s["memory"] = mem

            result = record_solution(
                project_id="test-project",
                error_message=f"Error from {actor}",
                solution="Fixed it",
                actor=actor,
                actor_source=actor_source,
                _memory=memory,
                _save_fn=mock_save,
            )

            self.assertTrue(result.success, f"Failed for {actor}/{actor_source}")
            session = saved["memory"]["debug_sessions"][0]
            self.assertEqual(session["actor"], actor)
            self.assertEqual(session["actor_source"], actor_source)


class TestSolutionResult(unittest.TestCase):
    """Test SolutionResult dataclass."""

    def test_success_result(self):
        """Should create success result."""
        result = SolutionResult(
            success=True,
            solution_id="fix_123",
            message="Solution saved.",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.solution_id, "fix_123")
        self.assertFalse(result.is_update)
        self.assertEqual(result.similar_files, [])

    def test_update_result(self):
        """Should indicate update vs new."""
        result = SolutionResult(
            success=True,
            is_update=True,
            message="Solution updated.",
        )
        self.assertTrue(result.is_update)

    def test_failure_result(self):
        """Should create failure result."""
        result = SolutionResult(
            success=False,
            message="Error: project_id is required",
        )
        self.assertFalse(result.success)
        self.assertIn("project_id", result.message)


if __name__ == "__main__":
    unittest.main()
