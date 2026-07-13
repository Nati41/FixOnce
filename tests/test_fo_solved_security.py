"""
Security tests for fo_solved resolution flow.

These tests verify that direct bypass of the review validation is blocked.
The pending-review mechanism ensures that resolution can only happen through
a valid review workflow.

Hostile cases A-I as specified in requirements.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))


class TestDirectBypassBlocked(unittest.TestCase):
    """Case A: Direct bypass without prior review is blocked."""

    def test_supersede_without_review_id_rejected(self):
        """Direct supersede call without review_id is rejected."""
        from core.solutions import record_solution

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id="",  # Empty - no valid review
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertFalse(result.success)
        self.assertIn("resolution_review_id is required", result.message.lower())
        # Should NOT have superseded the existing solution
        self.assertNotIn("memory", saved)

    def test_supersede_with_fake_review_id_rejected(self):
        """Supersede with fabricated review_id is rejected."""
        from core.solutions import record_solution

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id="solrev_fake123",  # Fabricated - not in pending reviews
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertFalse(result.success)
        self.assertIn("not found", result.message.lower())


class TestProjectIdMismatch(unittest.TestCase):
    """Case B: Project ID mismatch is blocked."""

    def test_review_from_different_project_rejected(self):
        """Review ID from different project is rejected."""
        from core.solutions import record_solution, _create_pending_solution_review

        # Create a pending review for project-a
        memory_a = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }

        review = _create_pending_solution_review(
            memory=memory_a,
            project_id="project-a",
            relationship="supersedes",
            target_solution=memory_a["debug_sessions"][0],
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["supersede_existing", "cancel"],
            actor="claude",
            actor_source="mcp",
        )

        review_id = review["id"]

        # Try to use the review in project-b
        memory_b = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [review],  # Copy the review from project-a
        }

        result = record_solution(
            project_id="project-b",  # Different project
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id=review_id,
            _memory=memory_b,
            _save_fn=lambda pid, mem: None,
        )

        self.assertFalse(result.success)
        self.assertIn("project", result.message.lower())


class TestRelationshipMismatch(unittest.TestCase):
    """Case C: Action not allowed by relationship is blocked."""

    def test_supersede_not_in_allowed_actions_rejected(self):
        """Supersede rejected when not in allowed actions."""
        from core.solutions import record_solution, _create_pending_solution_review

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }

        # Create review that only allows cancel (e.g., for POTENTIAL_CONFLICT)
        # Note: relationship must be "supersedes" to not fail that check first
        review = _create_pending_solution_review(
            memory=memory,
            project_id="test-project",
            relationship="supersedes",  # Must be supersedes to pass relationship check
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["cancel"],  # Only cancel allowed
            actor="claude",
            actor_source="mcp",
        )

        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",  # Not allowed
            resolution_target_id="sol_existing",
            resolution_review_id=review["id"],
            _memory=memory,
            _save_fn=lambda pid, mem: None,
        )

        self.assertFalse(result.success)
        self.assertIn("not allowed", result.message.lower())


class TestTargetIdMismatch(unittest.TestCase):
    """Case D: Target ID mismatch is blocked."""

    def test_different_target_id_rejected(self):
        """Superseding a different solution than reviewed is rejected."""
        from core.solutions import record_solution, _create_pending_solution_review

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_a",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                },
                {
                    "id": "sol_b",
                    "problem": "Memory leak in dashboard component",
                    "solution": "Add cleanup function to useEffect hook",
                },
            ],
            "pending_solution_reviews": [],
        }

        # Create review targeting sol_a
        review = _create_pending_solution_review(
            memory=memory,
            project_id="test-project",
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],  # sol_a
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["supersede_existing", "cancel"],
            actor="claude",
            actor_source="mcp",
        )

        # Try to supersede sol_b using review for sol_a
        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",
            resolution_target_id="sol_b",  # Different target
            resolution_review_id=review["id"],
            _memory=memory,
            _save_fn=lambda pid, mem: None,
        )

        self.assertFalse(result.success)
        self.assertIn("target", result.message.lower())


class TestProposalMismatch(unittest.TestCase):
    """Case E: Proposal text mismatch is blocked."""

    def test_different_problem_text_rejected(self):
        """Submitting different problem than reviewed is rejected."""
        from core.solutions import record_solution, _create_pending_solution_review

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }

        # Create review for specific problem
        review = _create_pending_solution_review(
            memory=memory,
            project_id="test-project",
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["supersede_existing", "cancel"],
            actor="claude",
            actor_source="mcp",
        )

        # Try to submit with different problem text
        result = record_solution(
            project_id="test-project",
            error_message="Completely different error message",  # Different
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id=review["id"],
            _memory=memory,
            _save_fn=lambda pid, mem: None,
        )

        self.assertFalse(result.success)
        self.assertIn("proposal", result.message.lower())

    def test_different_solution_text_rejected(self):
        """Submitting different solution than reviewed is rejected."""
        from core.solutions import record_solution, _create_pending_solution_review

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }

        # Create review for specific solution
        review = _create_pending_solution_review(
            memory=memory,
            project_id="test-project",
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["supersede_existing", "cancel"],
            actor="claude",
            actor_source="mcp",
        )

        # Try to submit with different solution text
        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Completely different solution text here",  # Different
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id=review["id"],
            _memory=memory,
            _save_fn=lambda pid, mem: None,
        )

        self.assertFalse(result.success)
        self.assertIn("proposal", result.message.lower())


class TestExpiredReview(unittest.TestCase):
    """Case F: Expired review is blocked."""

    def test_expired_review_rejected(self):
        """Review that has expired is rejected."""
        from core.solutions import record_solution, _create_pending_solution_review

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }

        # Create review
        review = _create_pending_solution_review(
            memory=memory,
            project_id="test-project",
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["supersede_existing", "cancel"],
            actor="claude",
            actor_source="mcp",
        )

        # Manually expire the review
        review["expires_at"] = "2020-01-01T00:00:00"
        memory["pending_solution_reviews"][0]["expires_at"] = "2020-01-01T00:00:00"

        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id=review["id"],
            _memory=memory,
            _save_fn=lambda pid, mem: None,
        )

        self.assertFalse(result.success)
        self.assertIn("expired", result.message.lower())


class TestConsumedReview(unittest.TestCase):
    """Case G: Already-consumed review is blocked (for different actions)."""

    def test_consumed_review_with_different_action_rejected(self):
        """Review consumed with one action cannot be reused for different action."""
        from core.solutions import record_solution, _create_pending_solution_review

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }

        # Create review
        review = _create_pending_solution_review(
            memory=memory,
            project_id="test-project",
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["supersede_existing", "cancel"],
            actor="claude",
            actor_source="mcp",
        )

        # Mark as consumed with "cancel" action
        review["status"] = "consumed"
        review["consumed_at"] = "2024-01-15T12:00:00"
        review["resolution_action"] = "cancel"
        memory["pending_solution_reviews"][0]["status"] = "consumed"
        memory["pending_solution_reviews"][0]["resolution_action"] = "cancel"

        # Try to use it for supersede_existing (different action)
        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",  # Different from cancel
            resolution_target_id="sol_existing",
            resolution_review_id=review["id"],
            _memory=memory,
            _save_fn=lambda pid, mem: None,
        )

        self.assertFalse(result.success)
        self.assertIn("consumed", result.message.lower())

    def test_consumed_review_idempotent_retry_succeeds(self):
        """Same review with same action is idempotent (succeeds silently)."""
        from core.solutions import record_solution, _create_pending_solution_review

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }

        # Create review
        review = _create_pending_solution_review(
            memory=memory,
            project_id="test-project",
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["supersede_existing", "cancel"],
            actor="claude",
            actor_source="mcp",
        )

        # Mark as consumed with "supersede_existing" action
        review["status"] = "consumed"
        review["consumed_at"] = "2024-01-15T12:00:00"
        review["resolution_action"] = "supersede_existing"
        memory["pending_solution_reviews"][0]["status"] = "consumed"
        memory["pending_solution_reviews"][0]["resolution_action"] = "supersede_existing"

        # Retry with same action (idempotent)
        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",  # Same as before
            resolution_target_id="sol_existing",
            resolution_review_id=review["id"],
            _memory=memory,
            _save_fn=lambda pid, mem: None,
        )

        # Should succeed (idempotent)
        self.assertTrue(result.success)
        self.assertIn("idempotent", result.message.lower())


class TestStalenessDetection(unittest.TestCase):
    """Case H: Staleness via fingerprint change is blocked."""

    def test_target_changed_since_review_rejected(self):
        """Review for target that changed since review is rejected."""
        from core.solutions import record_solution, _create_pending_solution_review, _solution_fingerprint

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }

        # Create review with current target state
        review = _create_pending_solution_review(
            memory=memory,
            project_id="test-project",
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["supersede_existing", "cancel"],
            actor="claude",
            actor_source="mcp",
        )

        # Target solution was modified since review
        memory["debug_sessions"][0]["solution"] = "Completely different solution now"

        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id=review["id"],
            _memory=memory,
            _save_fn=lambda pid, mem: None,
        )

        self.assertFalse(result.success)
        self.assertIn("changed since review", result.message.lower())


class TestAtomicOperation(unittest.TestCase):
    """Case I: Operation is atomic (all-or-nothing)."""

    def test_failed_validation_leaves_memory_unchanged(self):
        """Failed validation does not modify memory state."""
        from core.solutions import record_solution

        original_sessions = [
            {
                "id": "sol_existing",
                "problem": "Connection timeout when calling API endpoint",
                "solution": "Increase timeout from 5s to 30s in config",
                "superseded": False,
            }
        ]

        memory = {
            "debug_sessions": [dict(s) for s in original_sessions],  # Deep copy
            "pending_solution_reviews": [],
        }

        saves = []

        def track_save(pid, mem):
            saves.append(dict(mem))

        # Try invalid resolution
        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id="solrev_invalid",  # Invalid
            _memory=memory,
            _save_fn=track_save,
        )

        self.assertFalse(result.success)
        # No saves should have occurred
        self.assertEqual(len(saves), 0)
        # Original solution should be unchanged
        self.assertFalse(memory["debug_sessions"][0].get("superseded", False))


class TestValidReviewFlow(unittest.TestCase):
    """Positive test: Valid review flow succeeds."""

    def test_valid_supersede_flow_works(self):
        """Complete valid supersede flow works correctly."""
        from core.solutions import record_solution, _create_pending_solution_review

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout when calling API endpoint",
                    "solution": "Increase timeout from 5s to 30s in config",
                }
            ],
            "pending_solution_reviews": [],
        }
        saved = {}

        def mock_save(pid, mem):
            saved["memory"] = mem

        # Step 1: Create valid pending review
        review = _create_pending_solution_review(
            memory=memory,
            project_id="test-project",
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Connection timeout when calling API endpoint",
            proposed_solution="Use async with retry for better reliability",
            allowed_actions=["supersede_existing", "cancel"],
            actor="claude",
            actor_source="mcp",
        )

        # Save the memory with the pending review
        mock_save("test-project", memory)

        # Step 2: Execute resolution with valid review
        result = record_solution(
            project_id="test-project",
            error_message="Connection timeout when calling API endpoint",
            solution="Use async with retry for better reliability",
            resolution_action="supersede_existing",
            resolution_target_id="sol_existing",
            resolution_review_id=review["id"],
            _memory=memory,
            _save_fn=mock_save,
        )

        self.assertTrue(result.success, f"Expected success, got: {result.message}")
        # Old solution should be superseded
        old_sol = next(
            s for s in saved["memory"]["debug_sessions"]
            if s["id"] == "sol_existing"
        )
        self.assertTrue(old_sol.get("superseded"))
        # New solution should exist
        new_sol = next(
            (s for s in saved["memory"]["debug_sessions"]
             if "async" in s.get("solution", "").lower()),
            None
        )
        self.assertIsNotNone(new_sol)
        self.assertFalse(new_sol.get("superseded", False))


class TestMCPLayerValidation(unittest.TestCase):
    """Tests for MCP layer validation."""

    def test_mcp_fo_solved_requires_review_id_for_resolution(self):
        """MCP fo_solved rejects resolution without review_id."""
        from mcp_server.mcp_memory_server_v2 import fo_solved

        with patch("mcp_server.mcp_memory_server_v2._universal_gate") as mock_gate:
            mock_gate.return_value = (None, "")

            result = fo_solved(
                error="Test error",
                solution="Test fix",
                resolution_action="supersede_existing",
                resolution_target_id="sol_123",
                # No resolution_review_id
            )

            self.assertIn("resolution_review_id is required", result)

    def test_mcp_fo_solved_passes_review_id_to_core(self):
        """MCP fo_solved passes resolution_review_id to core."""
        from mcp_server.mcp_memory_server_v2 import fo_solved

        with patch("mcp_server.mcp_memory_server_v2._universal_gate") as mock_gate:
            mock_gate.return_value = (None, "")

            with patch("mcp_server.mcp_memory_server_v2.solution_applied") as mock_sa:
                mock_sa.return_value = "Test result"

                fo_solved(
                    error="Test error",
                    solution="Test fix",
                    resolution_action="supersede_existing",
                    resolution_target_id="sol_123",
                    resolution_review_id="solrev_valid456",
                )

                mock_sa.assert_called_once()
                call_kwargs = mock_sa.call_args[1]
                self.assertEqual(call_kwargs.get("resolution_review_id"), "solrev_valid456")


class TestReviewCreation(unittest.TestCase):
    """Tests for pending review creation."""

    def test_review_id_included_in_response(self):
        """Review-required response includes review_id."""
        from core.solutions import record_solution

        memory = {
            "debug_sessions": [
                {
                    "id": "sol_existing",
                    "problem": "Connection timeout error in the API client",
                    "solution": "Increased timeout from 5s to 30s",
                }
            ],
            "pending_solution_reviews": [],
        }

        # Mock the decision_review to return SUPERSEDES
        with patch("core.decision_review.review_solution") as mock_review:
            mock_result = MagicMock()
            mock_result.requires_review = True
            mock_result.primary_candidate = MagicMock()
            mock_result.primary_candidate.id = "sol_existing"
            mock_result.primary_candidate.text = "Increased timeout from 5s to 30s"
            mock_result.primary_candidate.explanation = "Same error, different solution"

            from core.decision_review import RelationshipType
            mock_result.primary_candidate.relationship = RelationshipType.SUPERSEDES
            mock_result.allowed_actions = ["supersede_existing", "cancel"]
            mock_result.to_dict = MagicMock(return_value={
                "requires_review": True,
                "primary_candidate": {
                    "id": "sol_existing",
                    "relationship": "supersedes",
                    "text": "Increased timeout from 5s to 30s",
                    "explanation": "Same error, different solution",
                },
                "allowed_actions": ["supersede_existing", "cancel"],
            })
            mock_review.return_value = mock_result

            result = record_solution(
                project_id="test-project",
                error_message="Connection timeout error in the API client",
                solution="Use async with retry backoff for reliability",
                _memory=memory,
                _save_fn=lambda pid, mem: None,
            )

            self.assertTrue(result.requires_review)
            self.assertIn("review_id", result.review_result)
            self.assertTrue(result.review_result["review_id"].startswith("solrev_"))


if __name__ == "__main__":
    unittest.main()
