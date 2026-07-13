"""
Minimal regression tests for Solution Review using the shared relationship engine.

These tests prove that the same engine used for Decision Review also works for Solved Bugs.
"""

import sys
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))


def solution(solution_id, problem, sol, status="active", superseded=False):
    """Helper to create a solution record."""
    return {
        "id": solution_id,
        "problem": problem,
        "solution": sol,
        "status": status,
        "superseded": superseded,
    }


class TestSolutionReviewCore(unittest.TestCase):
    """Core tests proving the shared engine works for solutions."""

    def test_identical_solution_detected_as_same(self):
        """An identical solved bug + solution is detected as same."""
        from core.decision_review import review_solution

        existing = [solution(
            "sol_json_parse",
            "JSONDecodeError: Expecting value",
            "Check response status before parsing JSON",
        )]
        new_problem = "JSONDecodeError: Expecting value"
        new_solution = "Check response status before parsing JSON"

        review = review_solution(new_problem, new_solution, {"solutions": existing})

        self.assertTrue(review.requires_review, "Identical solution must require review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.id, "sol_json_parse")
        self.assertEqual(review.primary_candidate.relationship.value, "same")

    def test_replacement_solution_requires_review(self):
        """A clearly replaced solution for the same problem requires review."""
        from core.decision_review import review_solution

        existing = [solution(
            "sol_timeout",
            "Connection timeout when calling external API",
            "Increase timeout from 5s to 30s",
        )]
        new_problem = "Replace timeout increase with async requests for external API"
        new_solution = "Use aiohttp for async requests instead of synchronous calls"

        review = review_solution(new_problem, new_solution, {"solutions": existing})

        self.assertTrue(review.requires_review, "Replacement solution must require review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.id, "sol_timeout")
        self.assertIn(
            review.primary_candidate.relationship.value,
            {"supersedes", "potential_conflict"},
            "Replacement must be supersedes or potential_conflict"
        )

    def test_production_style_replacement_wording_in_solution_is_supersedes(self):
        """Production fo_solved-style input: replacement wording can live in solution text."""
        from core.decision_review import review_solution

        existing = [solution(
            "sol_customer_validation",
            "Customer records were saved with invalid required fields.",
            "Validate required customer fields before writing the record.",
        )]
        new_problem = "Customer records were saved with invalid required fields after legacy validation was removed."
        new_solution = "Replace the existing customer field validation solution with schema-based validation before saving customer records."

        review = review_solution(new_problem, new_solution, {"solutions": existing})

        self.assertTrue(review.requires_review)
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.relationship.value, "supersedes")
        self.assertEqual([action.value for action in review.allowed_actions], ["supersede_existing", "cancel"])
        self.assertEqual(
            review.to_dict()["primary_candidate"]["explanation"],
            "Explicit replacement wording targets a related active decision",
        )

    def test_production_style_replacement_variants_in_solution_are_supersedes(self):
        """Complete fo_solved-style inputs with explicit replacement wording classify as supersedes."""
        from core.decision_review import review_solution

        cases = [
            {
                "name": "replace previous fix",
                "existing": solution(
                    "sol_launchagent",
                    "The macOS LaunchAgent entered a crash loop after installation.",
                    "Install dependencies in the packaged environment and recreate the LaunchAgent.",
                ),
                "problem": "The macOS LaunchAgent still entered a crash loop after installation.",
                "solution": "Replace the previous fix with a launchctl bootstrap repair that rewrites the packaged environment path.",
            },
            {
                "name": "instead of",
                "existing": solution(
                    "sol_customer_validation",
                    "Customer records were saved with invalid required fields.",
                    "Validate required customer fields before writing the record.",
                ),
                "problem": "Customer records were saved with invalid required fields after validation drifted.",
                "solution": "Use schema validation instead of field validation before saving customer records.",
            },
            {
                "name": "replace x with y",
                "existing": solution(
                    "sol_metadata_atomic",
                    "Concurrent writes corrupted the project metadata file.",
                    "Write to a temporary file and atomically replace the original file.",
                ),
                "problem": "Concurrent writes still corrupted the project metadata file under contention.",
                "solution": "Replace direct metadata file writes with a locked atomic write helper.",
            },
        ]

        for case in cases:
            with self.subTest(case["name"]):
                review = review_solution(case["problem"], case["solution"], {"solutions": [case["existing"]]})

                self.assertTrue(review.requires_review)
                self.assertIsNotNone(review.primary_candidate)
                self.assertEqual(review.primary_candidate.relationship.value, "supersedes")
                self.assertEqual([action.value for action in review.allowed_actions], ["supersede_existing", "cancel"])

    def test_scoped_exception_detected(self):
        """A scoped solution exception is detected as exception_to."""
        from core.decision_review import review_solution

        existing = [solution(
            "sol_validation",
            "All customer data must be validated before storage",
            "Add client-side validation for all form fields",
        )]
        new_problem = "Bulk import bypasses validation for customer data"
        new_solution = "Bulk import may skip client-side validation for performance"

        review = review_solution(new_problem, new_solution, {"solutions": existing})

        self.assertTrue(review.requires_review, "Exception must require review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.id, "sol_validation")
        self.assertEqual(
            review.primary_candidate.relationship.value, "exception_to",
            "Scoped bypass must be exception_to"
        )

    def test_compatible_refinement_no_conflict(self):
        """A compatible refinement does not create a false conflict."""
        from core.decision_review import review_solution

        existing = [solution(
            "sol_null_check",
            "TypeError: Cannot read property 'map' of undefined",
            "Add null check before calling .map()",
        )]
        new_problem = "TypeError: Cannot read property 'map' of undefined"
        new_solution = "Add null check before calling .map() with fallback to empty array"

        review = review_solution(new_problem, new_solution, {"solutions": existing})

        if review.requires_review and review.primary_candidate:
            self.assertNotEqual(
                review.primary_candidate.relationship.value, "potential_conflict",
                "Compatible refinement must NOT be potential_conflict"
            )

    def test_unrelated_solution_remains_unrelated(self):
        """A completely unrelated solved bug remains unrelated."""
        from core.decision_review import review_solution

        existing = [solution(
            "sol_css",
            "CSS styles not loading in production",
            "Fix webpack configuration for CSS extraction",
        )]
        new_problem = "Database connection pool exhausted"
        new_solution = "Increase max pool connections from 10 to 50"

        review = review_solution(new_problem, new_solution, {"solutions": existing})

        self.assertFalse(review.requires_review, "Unrelated must NOT require review")
        self.assertIsNone(review.primary_candidate)

    def test_superseded_solution_excluded(self):
        """Superseded solutions are not considered as candidates."""
        from core.decision_review import review_solution

        existing = [solution(
            "sol_old",
            "JSONDecodeError: Expecting value",
            "Wrap in try-except and log error",
            superseded=True,
        )]
        new_problem = "JSONDecodeError: Expecting value"
        new_solution = "Check response status before parsing JSON"

        review = review_solution(new_problem, new_solution, {"solutions": existing})

        self.assertFalse(review.requires_review, "Superseded solution must be excluded")
        self.assertIsNone(review.primary_candidate)


class TestSolutionIdGeneration(unittest.TestCase):
    """Tests for solution ID generation."""

    def test_solution_id_for_generates_sol_prefix(self):
        """solution_id_for generates IDs with sol_ prefix."""
        from core.decision_review import solution_id_for

        sol = {"problem": "Test error", "solution": "Test fix"}
        sol_id = solution_id_for(sol)

        self.assertTrue(sol_id.startswith("sol_"), f"ID must start with sol_, got: {sol_id}")

    def test_solution_id_for_uses_existing_id(self):
        """solution_id_for returns existing ID if present."""
        from core.decision_review import solution_id_for

        sol = {"id": "my_custom_id", "problem": "Test", "solution": "Fix"}
        sol_id = solution_id_for(sol)

        self.assertEqual(sol_id, "my_custom_id")

    def test_solution_id_for_deterministic(self):
        """solution_id_for produces same ID for same content."""
        from core.decision_review import solution_id_for

        sol1 = {"problem": "Error X", "solution": "Fix Y"}
        sol2 = {"problem": "Error X", "solution": "Fix Y"}

        self.assertEqual(solution_id_for(sol1), solution_id_for(sol2))


class TestSharedEngine(unittest.TestCase):
    """Tests proving decisions and solutions use the same relationship logic."""

    def test_classify_relationship_unchanged(self):
        """classify_relationship works the same for both types (it's text-based)."""
        from core.decision_review import classify_relationship, RelationshipType

        rel1, _, _ = classify_relationship(
            "Use PostgreSQL for storage",
            "Better scale",
            "Use PostgreSQL for storage",
            "Better scale",
        )
        self.assertEqual(rel1, RelationshipType.SAME)

        rel2, _, _ = classify_relationship(
            "Replace PostgreSQL with SQLite",
            "Simpler",
            "Use PostgreSQL for storage",
            "Better scale",
        )
        self.assertEqual(rel2, RelationshipType.SUPERSEDES)

    def test_both_types_use_same_allowed_actions(self):
        """Both decisions and solutions get the same allowed actions for same relationship."""
        from core.decision_review import review_decision, review_solution, RelationshipType

        decision_memory = {"decisions": [{"id": "d1", "decision": "Use REST API", "reason": "Standard"}]}
        solution_memory = {"solutions": [{"id": "s1", "problem": "API error", "solution": "Use REST client"}]}

        dec_review = review_decision("Use REST API", "Standard", decision_memory)
        sol_review = review_solution("API error", "Use REST client", solution_memory)

        if dec_review.primary_candidate and sol_review.primary_candidate:
            if dec_review.primary_candidate.relationship == sol_review.primary_candidate.relationship:
                self.assertEqual(dec_review.allowed_actions, sol_review.allowed_actions)


if __name__ == "__main__":
    unittest.main()
