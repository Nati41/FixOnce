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

from core.solutions import record_solution, SolutionResult, _create_pending_solution_review


def _setup_valid_review(memory, project_id, problem, solution, target_id, allowed_actions=None):
    """Create a valid pending review for resolution tests."""
    if allowed_actions is None:
        allowed_actions = ["supersede_existing", "cancel"]

    target = next(
        (s for s in memory.get("debug_sessions", []) if s.get("id") == target_id),
        {"id": target_id, "problem": "", "solution": ""}
    )

    review = _create_pending_solution_review(
        memory=memory,
        project_id=project_id,
        relationship="supersedes",
        target_solution=target,
        proposed_problem=problem,
        proposed_solution=solution,
        allowed_actions=allowed_actions,
        actor="test",
        actor_source="test",
    )
    return review["id"]


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


class TestSolutionReviewIntegration(unittest.TestCase):
    """Regression tests for Solution Review integration with shared engine."""

    def test_same_solution_remains_silent_increments_reuse(self):
        """SAME: identical problem + solution = silent update, reuse_count++."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "JSONDecodeError: Expecting value",
                    "solution": "Check response status before parsing JSON",
                    "reuse_count": 3,
                }
            ]
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="JSONDecodeError: Expecting value",
            solution="Check response status before parsing JSON",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success, "SAME should succeed silently")
        self.assertTrue(result.is_update, "SAME should be an update")
        self.assertFalse(result.requires_review, "SAME should NOT require review")
        self.assertEqual(result.message, "Solution updated.")
        self.assertEqual(len(saved["memory"]["debug_sessions"]), 1, "No duplicate created")
        self.assertEqual(saved["memory"]["debug_sessions"][0]["reuse_count"], 4)

    def test_supersedes_requires_review_no_storage(self):
        """SUPERSEDES: explicit replacement blocks save, requires review."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_timeout",
                    "problem": "Connection timeout when calling external API",
                    "solution": "Increase timeout from 5s to 30s",
                    "reuse_count": 0,
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="Replace timeout increase with async requests for external API connection",
            solution="Switch to aiohttp for async requests instead of synchronous calls",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertFalse(result.success, "SUPERSEDES should NOT succeed")
        self.assertTrue(result.requires_review, "SUPERSEDES requires review")
        self.assertIsNotNone(result.review_result)
        self.assertEqual(
            result.review_result["primary_candidate"]["relationship"],
            "supersedes"
        )
        # Solution should NOT be added, only pending review stored
        self.assertEqual(len(memory["debug_sessions"]), 1, "No solution added for SUPERSEDES")
        # Review ID should be included in response
        self.assertIn("review_id", result.review_result)
        self.assertTrue(result.review_result["review_id"].startswith("solrev_"))

    def test_supersedes_from_solution_text_requires_review_no_storage(self):
        """SUPERSEDES: production fo_solved wording may place replacement in solution text."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_customer_validation",
                    "problem": "Customer records were saved with invalid required fields.",
                    "solution": "Validate required customer fields before writing the record.",
                    "reuse_count": 0,
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="Customer records were saved with invalid required fields after legacy validation was removed.",
            solution="Replace the existing customer field validation solution with schema-based validation before saving customer records.",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertFalse(result.success, "SUPERSEDES should NOT succeed")
        self.assertTrue(result.requires_review, "SUPERSEDES requires review")
        self.assertIsNotNone(result.review_result)
        self.assertEqual(
            result.review_result["primary_candidate"]["relationship"],
            "supersedes"
        )
        # Solution should NOT be added
        self.assertEqual(len(memory["debug_sessions"]), 1, "No solution added for SUPERSEDES")
        # Review ID should be included
        self.assertIn("review_id", result.review_result)

    def test_exception_requires_review_no_storage(self):
        """EXCEPTION_TO: scoped bypass blocks save, requires review."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_validation",
                    "problem": "All customer data must be validated before storage",
                    "solution": "Add client-side validation for all form fields",
                    "reuse_count": 0,
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="Bulk import bypasses validation for customer data",
            solution="Bulk import may skip client-side validation for performance",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertFalse(result.success, "EXCEPTION_TO should NOT succeed")
        self.assertTrue(result.requires_review, "EXCEPTION_TO requires review")
        self.assertIsNotNone(result.review_result)
        self.assertEqual(
            result.review_result["primary_candidate"]["relationship"],
            "exception_to"
        )
        # Solution should NOT be added
        self.assertEqual(len(memory["debug_sessions"]), 1, "No solution added for EXCEPTION_TO")
        # Review ID should be included
        self.assertIn("review_id", result.review_result)

    def test_potential_conflict_requires_review_no_storage(self):
        """POTENTIAL_CONFLICT: opposing solutions block save, require review."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_logging",
                    "problem": "Activity logging must happen automatically on every write",
                    "solution": "Add automatic logging to all CRUD operations",
                    "reuse_count": 0,
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="Activity logging should be performed manually only when explicitly requested",
            solution="Remove automatic logging, add manual logging triggers",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertFalse(result.success, "POTENTIAL_CONFLICT should NOT succeed")
        self.assertTrue(result.requires_review, "POTENTIAL_CONFLICT requires review")
        self.assertIsNotNone(result.review_result)
        self.assertEqual(
            result.review_result["primary_candidate"]["relationship"],
            "potential_conflict"
        )
        # Solution should NOT be added
        self.assertEqual(len(memory["debug_sessions"]), 1, "No solution added for POTENTIAL_CONFLICT")
        # Review ID should be included
        self.assertIn("review_id", result.review_result)

    def test_unrelated_saves_normally(self):
        """UNRELATED: completely different solution saves without interruption."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_css",
                    "problem": "CSS styles not loading in production",
                    "solution": "Fix webpack configuration for CSS extraction",
                    "reuse_count": 0,
                }
            ]
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="Database connection pool exhausted",
            solution="Increase max pool connections from 10 to 50",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success, "UNRELATED should succeed")
        self.assertFalse(result.requires_review, "UNRELATED should NOT require review")
        self.assertFalse(result.is_update, "UNRELATED should be new, not update")
        self.assertEqual(len(saved["memory"]["debug_sessions"]), 2, "New solution added")


class TestSolutionResolution(unittest.TestCase):
    """Tests for solution resolution actions (supersede_existing, cancel)."""

    def test_supersede_existing_marks_old_solution_inactive(self):
        """SUPERSEDE_EXISTING: marks existing solution as superseded."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_timeout",
                    "problem": "Connection timeout when calling external API",
                    "solution": "Increase timeout from 5s to 30s",
                    "reuse_count": 2,
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Create valid pending review first
        review_id = _setup_valid_review(
            memory, "test-project",
            "Connection timeout when calling external API",
            "Use async requests with retry backoff",
            "sol_timeout"
        )

        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling external API",
            solution="Use async requests with retry backoff",
            resolution_action="supersede_existing",
            resolution_target_id="sol_timeout",
            resolution_review_id=review_id,
            actor="claude",
            actor_source="mcp",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success, f"Resolution should succeed: {result.message}")
        self.assertFalse(result.requires_review, "No further review needed")

        # Old solution should be marked superseded
        old_solution = saved["memory"]["debug_sessions"][0]
        self.assertTrue(old_solution.get("superseded"), "Old solution must be superseded")
        self.assertIsNotNone(old_solution.get("superseded_at"))
        self.assertEqual(old_solution.get("superseded_by_solution"), "Use async requests with retry backoff")
        self.assertEqual(old_solution.get("superseded_by_actor"), "claude")

    def test_supersede_existing_saves_new_solution(self):
        """SUPERSEDE_EXISTING: saves the new solution as active."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_old",
                    "problem": "Database connection error",
                    "solution": "Increase pool size",
                    "reuse_count": 0,
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Create valid pending review
        review_id = _setup_valid_review(
            memory, "test-project",
            "Replace pool size increase for database connection error",
            "Use connection pooling with health checks",
            "sol_old"
        )

        result = record_solution(
            project_id="test-project",
            error_message="Replace pool size increase for database connection error",
            solution="Use connection pooling with health checks",
            resolution_action="supersede_existing",
            resolution_target_id="sol_old",
            resolution_review_id=review_id,
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success)
        self.assertEqual(len(saved["memory"]["debug_sessions"]), 2, "New solution added")

        # New solution should be active
        new_solution = saved["memory"]["debug_sessions"][1]
        self.assertNotIn("superseded", new_solution)
        self.assertIn("health checks", new_solution["solution"])

    def test_supersede_existing_preserves_history(self):
        """SUPERSEDE_EXISTING: old solution remains in debug_sessions for history."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_history",
                    "problem": "Memory leak in component",
                    "solution": "Clear intervals on unmount",
                    "reuse_count": 5,
                    "resolved_at": "2024-01-01T10:00:00",
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Create valid pending review
        review_id = _setup_valid_review(
            memory, "test-project",
            "Replace interval cleanup for memory leak in component",
            "Use useEffect cleanup with AbortController",
            "sol_history"
        )

        result = record_solution(
            project_id="test-project",
            error_message="Replace interval cleanup for memory leak in component",
            solution="Use useEffect cleanup with AbortController",
            resolution_action="supersede_existing",
            resolution_target_id="sol_history",
            resolution_review_id=review_id,
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success)

        # Old solution preserved with original data
        old_solution = saved["memory"]["debug_sessions"][0]
        self.assertEqual(old_solution["id"], "sol_history")
        self.assertEqual(old_solution["reuse_count"], 5)
        self.assertEqual(old_solution["resolved_at"], "2024-01-01T10:00:00")
        self.assertTrue(old_solution.get("superseded"))

    def test_cancel_performs_no_write(self):
        """CANCEL: saves consumed state but not the new solution."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_cancel_test",
                    "problem": "Test error message here",
                    "solution": "Test fix approach here",
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Create valid pending review for cancel
        review_id = _setup_valid_review(
            memory, "test-project",
            "Replace test fix approach",
            "New approach to fix issue",
            "sol_cancel_test",
            allowed_actions=["supersede_existing", "cancel"]
        )

        result = record_solution(
            project_id="test-project",
            error_message="Replace test fix approach",
            solution="New approach to fix issue",
            resolution_action="cancel",
            resolution_target_id="sol_cancel_test",
            resolution_review_id=review_id,
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertFalse(result.success, "Cancel should not succeed (no solution saved)")
        self.assertIn("cancelled", result.message.lower())
        # Original solution should still be active (not superseded)
        self.assertFalse(memory["debug_sessions"][0].get("superseded"))

    def test_invalid_target_rejected(self):
        """Invalid target ID returns error without modifying storage."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Existing error message",
                    "solution": "Existing fix approach",
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Create review targeting sol_existing but then try to supersede sol_nonexistent
        review_id = _setup_valid_review(
            memory, "test-project",
            "Some error message here",
            "Some fix approach here",
            "sol_existing"  # Review is for sol_existing
        )

        result = record_solution(
            project_id="test-project",
            error_message="Some error message here",
            solution="Some fix approach here",
            resolution_action="supersede_existing",
            resolution_target_id="sol_nonexistent",  # But trying different target
            resolution_review_id=review_id,
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertFalse(result.success, "Invalid target should fail")
        self.assertIn("target", result.message.lower())  # Target mismatch error
        self.assertEqual(saved, {}, "No storage modification for invalid target")

    def test_unsupported_action_rejected(self):
        """Unsupported resolution actions return error before review check."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_test",
                    "problem": "Test error",
                    "solution": "Test fix",
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Even with a review_id, unsupported actions should fail
        result = record_solution(
            project_id="test-project",
            error_message="Some error",
            solution="Some fix",
            resolution_action="save_as_exception",  # Not supported for solutions
            resolution_target_id="sol_test",
            resolution_review_id="solrev_fake",  # Won't be validated - fails earlier
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertFalse(result.success, "Unsupported action should fail")
        # Fails during enum conversion before review validation
        self.assertIn("error", result.message.lower())
        self.assertEqual(saved, {}, "No storage modification for unsupported action")

    def test_repeated_resolution_is_idempotent(self):
        """Repeated identical resolution is idempotent (returns success)."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_idempotent",
                    "problem": "Original problem here",
                    "solution": "Original fix here",
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Create valid pending review
        review_id = _setup_valid_review(
            memory, "test-project",
            "Replace original fix here",
            "New fix approach here",
            "sol_idempotent"
        )

        # Mark the review as already consumed with same action
        memory["pending_solution_reviews"][0]["status"] = "consumed"
        memory["pending_solution_reviews"][0]["resolution_action"] = "supersede_existing"

        # Idempotent retry with same action should succeed
        result = record_solution(
            project_id="test-project",
            error_message="Replace original fix here",
            solution="New fix approach here",
            resolution_action="supersede_existing",
            resolution_target_id="sol_idempotent",
            resolution_review_id=review_id,
            _memory=memory,
            _save_fn=mock_save,
        )

        # Idempotent retry succeeds
        self.assertTrue(result.success, "Idempotent retry should succeed")
        self.assertIn("idempotent", result.message.lower())

    def test_unrelated_solutions_unaffected(self):
        """SUPERSEDE_EXISTING only affects the targeted solution."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_target",
                    "problem": "Target error message here",
                    "solution": "Target fix approach here",
                },
                {
                    "id": "sol_unrelated",
                    "problem": "Unrelated CSS error",
                    "solution": "Unrelated CSS fix",
                },
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Create valid pending review
        review_id = _setup_valid_review(
            memory, "test-project",
            "Replace target fix for target error",
            "Better target fix approach",
            "sol_target"
        )

        result = record_solution(
            project_id="test-project",
            error_message="Replace target fix for target error",
            solution="Better target fix approach",
            resolution_action="supersede_existing",
            resolution_target_id="sol_target",
            resolution_review_id=review_id,
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success)

        # Target superseded
        target = saved["memory"]["debug_sessions"][0]
        self.assertTrue(target.get("superseded"))

        # Unrelated unchanged
        unrelated = saved["memory"]["debug_sessions"][1]
        self.assertFalse(unrelated.get("superseded", False))
        self.assertEqual(unrelated["id"], "sol_unrelated")

    def test_same_behavior_unchanged_with_resolution(self):
        """SAME (duplicate) behavior remains unchanged - resolution not needed."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "JSONDecodeError: Expecting value",
                    "solution": "Check response status before parsing",
                    "reuse_count": 0,
                }
            ]
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Identical problem text triggers duplicate detection, not review
        result = record_solution(
            project_id="test-project",
            error_message="JSONDecodeError: Expecting value",
            solution="Check response status before parsing",
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success, "SAME should succeed silently")
        self.assertTrue(result.is_update, "SAME should be an update")
        self.assertFalse(result.requires_review, "SAME should NOT require review")
        self.assertEqual(saved["memory"]["debug_sessions"][0]["reuse_count"], 1)

    def test_resolution_skips_review_check(self):
        """Resolution action with valid review skips the review check."""
        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling external API",
                    "solution": "Increase timeout from 5s to 30s",
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Create valid pending review
        review_id = _setup_valid_review(
            memory, "test-project",
            "Replace timeout increase with async requests for external API",
            "Use aiohttp for async requests",
            "sol_existing"
        )

        # Resolution with valid review skips the re-review check
        result = record_solution(
            project_id="test-project",
            error_message="Replace timeout increase with async requests for external API",
            solution="Use aiohttp for async requests",
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id=review_id,
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success, f"Resolution should succeed: {result.message}")
        self.assertFalse(result.requires_review, "No review needed with valid resolution")


if __name__ == "__main__":
    unittest.main()
