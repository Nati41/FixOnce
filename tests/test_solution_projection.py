"""
Tests for solution projection consistency between V1/V2 and .fixonce/solutions.json.

These tests verify that superseded state is correctly propagated to all storage layers.
"""

import sys
import json
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))


class TestSolutionProjectionConsistency(unittest.TestCase):
    """Tests for projection of superseded state to .fixonce/solutions.json."""

    def test_sanitize_solution_preserves_superseded_state(self):
        """sanitize_solution must preserve superseded and related fields."""
        from core.committed_knowledge import sanitize_solution

        solution = {
            "id": "sol_123",
            "problem": "Connection timeout error",
            "solution": "Increase timeout to 30s",
            "root_cause": "Default timeout too low",
            "superseded": True,
            "superseded_at": "2024-01-15T10:00:00",
            "superseded_by_problem": "Connection timeout error",
            "superseded_by_solution": "Use async with retry",
            "superseded_by_actor": "claude",
            "superseded_by_source": "mcp",
            "reuse_count": 2,
        }

        sanitized = sanitize_solution(solution)

        self.assertTrue(sanitized.get("superseded"), "superseded must be preserved")
        self.assertEqual(sanitized.get("superseded_at"), "2024-01-15T10:00:00")
        self.assertEqual(sanitized.get("superseded_by_solution"), "Use async with retry")
        self.assertEqual(sanitized.get("superseded_by_actor"), "claude")
        self.assertEqual(sanitized.get("id"), "sol_123", "ID must be preserved")

    def test_sanitize_solution_preserves_id(self):
        """sanitize_solution must preserve solution ID for stable identification."""
        from core.committed_knowledge import sanitize_solution

        solution = {
            "id": "fix_20240115_100000",
            "problem": "Test error",
            "solution": "Test fix",
        }

        sanitized = sanitize_solution(solution)

        self.assertEqual(sanitized.get("id"), "fix_20240115_100000")

    def test_active_solution_has_superseded_false(self):
        """Active solutions have superseded=False in sanitized output."""
        from core.committed_knowledge import sanitize_solution

        solution = {
            "problem": "Active error",
            "solution": "Active fix",
        }

        sanitized = sanitize_solution(solution)

        self.assertFalse(sanitized.get("superseded"), "Active solution must have superseded=False")

    def test_write_committed_knowledge_includes_superseded_solutions(self):
        """write_committed_knowledge includes superseded solutions in output."""
        from core.committed_knowledge import write_committed_knowledge

        with tempfile.TemporaryDirectory() as tmpdir:
            # Note: problem and solution must be >= 10 chars to pass quality filter
            solutions = [
                {
                    "id": "sol_old",
                    "problem": "Connection timeout when calling the external API service",
                    "solution": "Increase timeout from 5s to 30s in the config",
                    "importance": "high",
                    "superseded": True,
                    "superseded_at": "2024-01-15T10:00:00",
                    "superseded_by_solution": "Use async with retry backoff",
                },
                {
                    "id": "sol_new",
                    "problem": "Connection timeout when calling the external API service",
                    "solution": "Use async with retry backoff for better reliability",
                    "importance": "high",
                },
            ]

            result = write_committed_knowledge(
                tmpdir,
                decisions=[],
                avoid_patterns=[],
                solutions=solutions,
            )

            self.assertEqual(result["status"], "ok")

            # Read the written file
            solutions_path = Path(tmpdir) / ".fixonce" / "solutions.json"
            self.assertTrue(solutions_path.exists(), f"solutions.json not created. Stats: {result.get('stats')}")

            with open(solutions_path) as f:
                data = json.load(f)

            self.assertEqual(data["count"], 2, "Total count includes superseded")
            self.assertEqual(data["active_count"], 1, "Active count excludes superseded")
            self.assertEqual(data["superseded_count"], 1)

            # Both solutions should be present
            self.assertEqual(len(data["solutions"]), 2)

            # Find the superseded one
            superseded = next(s for s in data["solutions"] if s.get("superseded"))
            self.assertEqual(superseded["id"], "sol_old")
            self.assertIn("superseded_by_solution", superseded)

    def test_superseded_solution_remains_in_history(self):
        """Superseded solution remains in projection for history/audit."""
        from core.committed_knowledge import write_committed_knowledge

        with tempfile.TemporaryDirectory() as tmpdir:
            solutions = [
                {
                    "id": "sol_superseded",
                    "problem": "Original database connection problem that caused failures",
                    "solution": "Original fix that was later replaced with a better approach",
                    "importance": "high",
                    "superseded": True,
                    "reuse_count": 5,  # High reuse count
                },
            ]

            write_committed_knowledge(tmpdir, [], [], solutions=solutions)

            solutions_path = Path(tmpdir) / ".fixonce" / "solutions.json"
            with open(solutions_path) as f:
                data = json.load(f)

            # Superseded solution should still be present
            self.assertEqual(len(data["solutions"]), 1)
            self.assertTrue(data["solutions"][0].get("superseded"))

    def test_only_one_active_solution_after_supersede(self):
        """After supersede, only one solution remains active for the issue."""
        from core.committed_knowledge import write_committed_knowledge

        with tempfile.TemporaryDirectory() as tmpdir:
            solutions = [
                {
                    "id": "sol_v1",
                    "problem": "Memory leak in React component causing browser slowdown",
                    "solution": "Add cleanup function to useEffect hook",
                    "importance": "high",
                    "superseded": True,
                },
                {
                    "id": "sol_v2",
                    "problem": "Memory leak in React component causing browser slowdown",
                    "solution": "Better cleanup with explicit GC hint after unmount",
                    "importance": "high",
                    "superseded": True,
                },
                {
                    "id": "sol_v3",
                    "problem": "Memory leak in React component causing browser slowdown",
                    "solution": "Use WeakRef pattern for event listeners to prevent leaks",
                    "importance": "high",
                    # Active - not superseded
                },
            ]

            write_committed_knowledge(tmpdir, [], [], solutions=solutions)

            solutions_path = Path(tmpdir) / ".fixonce" / "solutions.json"
            with open(solutions_path) as f:
                data = json.load(f)

            self.assertEqual(data["active_count"], 1, "Only one active solution")
            self.assertEqual(data["superseded_count"], 2)

            active = [s for s in data["solutions"] if not s.get("superseded")]
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["id"], "sol_v3")

    def test_unrelated_records_unchanged(self):
        """Superseding one solution doesn't affect unrelated solutions."""
        from core.committed_knowledge import write_committed_knowledge

        with tempfile.TemporaryDirectory() as tmpdir:
            solutions = [
                {
                    "id": "sol_superseded",
                    "problem": "Memory leak in the dashboard component causing slow performance",
                    "solution": "Old fix that was later replaced with a better implementation",
                    "importance": "high",
                    "superseded": True,
                },
                {
                    "id": "sol_unrelated",
                    "problem": "CSS styles not loading in production build correctly",
                    "solution": "Fix webpack configuration for CSS extraction module",
                    "importance": "high",
                    # Active
                },
            ]

            write_committed_knowledge(tmpdir, [], [], solutions=solutions)

            solutions_path = Path(tmpdir) / ".fixonce" / "solutions.json"
            with open(solutions_path) as f:
                data = json.load(f)

            unrelated = next(s for s in data["solutions"] if s["id"] == "sol_unrelated")
            self.assertFalse(unrelated.get("superseded"), "Unrelated solution unchanged")


class TestKnowledgeCounters(unittest.TestCase):
    """Tests for knowledge counters filtering superseded solutions."""

    def test_counters_exclude_superseded_solutions(self):
        """get_live_project_counters excludes superseded solutions."""
        from core.knowledge_counters import get_live_project_counters

        memory = {
            "debug_sessions": [
                {"problem": "Active 1", "solution": "Fix 1"},
                {"problem": "Active 2", "solution": "Fix 2"},
                {"problem": "Superseded", "solution": "Old fix", "superseded": True},
            ],
            "decisions": [
                {"decision": "Active decision", "reason": "Test"},
                {"decision": "Superseded decision", "reason": "Test", "superseded": True},
            ],
            "avoid": [
                {"what": "Avoid pattern", "reason": "Test"},
            ],
        }

        counters = get_live_project_counters(memory)

        self.assertEqual(counters["solved"], 2, "Only active solutions counted")
        self.assertEqual(counters["decisions"], 1, "Only active decisions counted")
        self.assertEqual(counters["avoid"], 1)

    def test_counters_handle_empty_memory(self):
        """get_live_project_counters handles empty/None memory."""
        from core.knowledge_counters import get_live_project_counters

        counters = get_live_project_counters(None)
        self.assertEqual(counters["solved"], 0)
        self.assertEqual(counters["decisions"], 0)
        self.assertEqual(counters["avoid"], 0)

        counters = get_live_project_counters({})
        self.assertEqual(counters["solved"], 0)


class TestSearchFiltersSupereded(unittest.TestCase):
    """Tests for search excluding superseded solutions."""

    def test_search_excludes_superseded_solutions(self):
        """Search results do not include superseded solutions."""
        from core.search import search_memory

        memory = {
            "debug_sessions": [
                {"problem": "Connection timeout", "solution": "Increase timeout", "superseded": True},
                {"problem": "Connection timeout", "solution": "Use async with retry"},
            ],
            "decisions": [],
            "avoid": [],
            "live_record": {"lessons": {"insights": [], "archived": [], "failed_attempts": []}},
        }

        result = search_memory(memory, "connection timeout")

        # Only active solution should appear
        solution_matches = [m for m in result.matches if m.match_type == "solution"]
        self.assertEqual(len(solution_matches), 1)
        self.assertIn("async", solution_matches[0].text)
        self.assertNotIn("Increase timeout", solution_matches[0].text)


class TestProjectionIdempotency(unittest.TestCase):
    """Tests for idempotent projection writes."""

    def test_repeated_write_is_idempotent(self):
        """Repeated writes with same data produce same output."""
        from core.committed_knowledge import write_committed_knowledge

        with tempfile.TemporaryDirectory() as tmpdir:
            solutions = [
                {
                    "id": "sol_test",
                    "problem": "Test database connection problem that needs fixing",
                    "solution": "Test fix that resolves the database connection issue",
                    "importance": "high",
                },
            ]

            # Write twice
            write_committed_knowledge(tmpdir, [], [], solutions=solutions)
            solutions_path = Path(tmpdir) / ".fixonce" / "solutions.json"
            with open(solutions_path) as f:
                first_write = json.load(f)

            write_committed_knowledge(tmpdir, [], [], solutions=solutions)
            with open(solutions_path) as f:
                second_write = json.load(f)

            # Count and structure should be identical (timestamp may differ)
            self.assertEqual(first_write["count"], second_write["count"])
            self.assertEqual(first_write["active_count"], second_write["active_count"])
            self.assertEqual(len(first_write["solutions"]), len(second_write["solutions"]))


class TestExistingNonResolutionWrites(unittest.TestCase):
    """Tests ensuring existing solution writes remain unchanged."""

    def test_normal_solution_write_works(self):
        """Normal (non-resolution) solution writes work correctly."""
        from core.solutions import record_solution

        memory = {"debug_sessions": []}
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="Normal error",
            solution="Normal fix",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success)
        self.assertFalse(result.requires_review)
        self.assertEqual(len(saved["memory"]["debug_sessions"]), 1)
        self.assertFalse(saved["memory"]["debug_sessions"][0].get("superseded", False))


if __name__ == "__main__":
    unittest.main()
