import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))


@dataclass
class FakeSemanticResult:
    text: str
    score: float
    metadata: dict
    rank: int = 1


def decision(decision_id, text, reason="Because.", status="active", superseded=False):
    return {
        "id": decision_id,
        "decision": text,
        "reason": reason,
        "status": status,
        "superseded": superseded,
    }


def semantic_for(*decision_ids, score=0.76, stale=False):
    def search(_project_id, _query, k=5, doc_type=None, min_score=0.0):
        results = []
        for idx, decision_id in enumerate(decision_ids):
            metadata = {"doc_type": "decision"}
            if not stale:
                metadata["decision_id"] = decision_id
            results.append(FakeSemanticResult(
                text=f"Indexed decision {decision_id}",
                score=score,
                metadata=metadata,
                rank=idx + 1,
            ))
        return results
    return search


class TestDecisionReviewV1(unittest.TestCase):
    def assertActions(self, review, expected):
        self.assertEqual([action.value for action in review.allowed_actions], expected)

    def review_case(self, case):
        from core.decision_review import review_decision

        return review_decision(
            case["proposed"],
            case.get("reason", "Test reason."),
            {"decisions": case["existing"]},
            project_id="project",
            semantic_search_fn=case.get("semantic"),
            semantic_min_score=case.get("semantic_min_score", 0.45),
        )

    def test_table_driven_relationships_and_actions(self):
        cases = [
            {
                "name": "logging required vs bypass logging",
                "existing": [decision("dec_logging", "Activity logging is mandatory for all writes.")],
                "proposed": "Bulk import may bypass activity logging.",
                "semantic": semantic_for("dec_logging"),
                "selected": "dec_logging",
                "relationship": "exception_to",
                "requires_review": True,
                "actions": ["save_as_exception", "save_anyway_under_review", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "validation required vs bypass validation",
                "existing": [decision("dec_validation", "All customer data must be validated before storage.")],
                "proposed": "Bulk customer import bypasses validation.",
                "semantic": semantic_for("dec_validation"),
                "selected": "dec_validation",
                "relationship": "exception_to",
                "requires_review": True,
                "actions": ["save_as_exception", "save_anyway_under_review", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "PostgreSQL vs SQLite explicit replacement",
                "existing": [decision("dec_pg", "Use PostgreSQL for application persistence.")],
                "proposed": "Replace PostgreSQL with SQLite for application persistence.",
                "semantic": semantic_for("dec_pg"),
                "selected": "dec_pg",
                "relationship": "supersedes",
                "requires_review": True,
                "actions": ["supersede_existing", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "REST API vs GraphQL explicit replacement",
                "existing": [decision("dec_rest", "Use REST API for public integrations.")],
                "proposed": "Switch public integrations from REST API to GraphQL.",
                "semantic": semantic_for("dec_rest"),
                "selected": "dec_rest",
                "relationship": "supersedes",
                "requires_review": True,
                "actions": ["supersede_existing", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "encryption required vs plaintext exception",
                "existing": [decision("dec_encrypt", "Stored exports must be encrypted.")],
                "proposed": "Temporary diagnostic exports may use plaintext.",
                "semantic": semantic_for("dec_encrypt"),
                "selected": "dec_encrypt",
                "relationship": "potential_conflict",
                "requires_review": True,
                "actions": ["supersede_existing", "save_anyway_under_review", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "immutable IDs vs regenerating IDs",
                "existing": [decision("dec_ids", "External record IDs must remain immutable.")],
                "proposed": "Allow regenerating external record IDs during restore.",
                "semantic": semantic_for("dec_ids"),
                "selected": "dec_ids",
                "relationship": "potential_conflict",
                "requires_review": True,
                "actions": ["supersede_existing", "save_anyway_under_review", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "valid extension",
                "existing": [decision("dec_api", "Use REST API for public integrations.")],
                "proposed": "Add REST API versioning for public integrations.",
                "semantic": semantic_for("dec_api"),
                "selected": "dec_api",
                "relationship": "extends",
                "requires_review": True,
                "actions": ["save_as_extends", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "scoped exception",
                "existing": [decision("dec_auth", "All service requests must use authentication.")],
                "proposed": "Health checks may bypass authentication.",
                "semantic": semantic_for("dec_auth"),
                "selected": "dec_auth",
                "relationship": "exception_to",
                "requires_review": True,
                "actions": ["save_as_exception", "save_anyway_under_review", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "exact duplicate",
                "existing": [decision("dec_dup", "Use REST API for public integrations.")],
                "proposed": "Use REST API for public integrations.",
                "semantic": semantic_for("dec_dup"),
                "selected": "dec_dup",
                "relationship": "same",
                "requires_review": True,
                "actions": ["acknowledge_existing", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "unrelated decisions sharing generic words",
                "existing": [decision("dec_json", "Store all entities in a unified JSON file.")],
                "proposed": "All customer imports may bypass validation.",
                "semantic": None,
                "selected": None,
                "relationship": None,
                "requires_review": False,
                "actions": [],
                "save_occurred": True,
            },
            {
                "name": "semantically related but ambiguous pair",
                "existing": [decision("dec_delivery", "Use queued delivery for outbound notifications.")],
                "proposed": "Outbound notification delivery should support batching.",
                "semantic": semantic_for("dec_delivery", score=0.82),
                "selected": "dec_delivery",
                "relationship": "undetermined",
                "requires_review": True,
                "actions": ["save_anyway_under_review", "cancel"],
                "save_occurred": False,
            },
            {
                "name": "superseded decision excluded",
                "existing": [decision("dec_old", "Use REST API for integrations.", superseded=True)],
                "proposed": "Replace REST API with GraphQL for integrations.",
                "semantic": semantic_for("dec_old"),
                "selected": None,
                "relationship": None,
                "requires_review": False,
                "actions": [],
                "save_occurred": True,
            },
            {
                "name": "semantic provider unavailable",
                "existing": [decision("dec_cache", "Use Redis for session caching.")],
                "proposed": "Use PostgreSQL for audit persistence.",
                "semantic": None,
                "selected": None,
                "relationship": None,
                "requires_review": False,
                "actions": [],
                "save_occurred": True,
            },
            {
                "name": "stale index result cannot map to canonical ID",
                "existing": [decision("dec_storage", "Use SQLite for local development storage.")],
                "proposed": "Replace production persistence with PostgreSQL.",
                "semantic": semantic_for("dec_missing", stale=True),
                "selected": None,
                "relationship": None,
                "requires_review": False,
                "actions": [],
                "save_occurred": True,
            },
        ]

        for case in cases:
            with self.subTest(case["name"]):
                review = self.review_case(case)
                self.assertEqual(review.requires_review, case["requires_review"])
                self.assertActions(review, case["actions"])
                if case["selected"]:
                    self.assertIsNotNone(review.primary_candidate)
                    self.assertEqual(review.primary_candidate.id, case["selected"])
                    self.assertEqual(review.primary_candidate.relationship.value, case["relationship"])
                else:
                    self.assertIsNone(review.primary_candidate)

                saved = self.record_without_real_semantic(case)
                self.assertEqual(saved["save_occurred"], case["save_occurred"])
                self.assertEqual(saved["requires_review"], case["requires_review"])

    def record_without_real_semantic(self, case):
        from core.decisions import record_decision

        memory = {"decisions": [dict(item) for item in case["existing"]], "decision_conflicts": []}
        saved = {}

        def save_fn(_project_id, new_memory):
            saved.update(new_memory)

        semantic = case.get("semantic")
        if semantic is None:
            semantic_patch = patch("core.project_semantic.search_project", side_effect=ImportError("unavailable"))
        else:
            semantic_patch = patch("core.project_semantic.search_project", side_effect=semantic)

        with semantic_patch:
            result = record_decision(
                "project",
                case["proposed"],
                case.get("reason", "Test reason."),
                actor="codex",
                actor_source="test",
                _memory=memory,
                _save_fn=save_fn,
            )

        return {
            "save_occurred": bool(saved),
            "requires_review": result.requires_review,
            "success": result.success,
        }

    def test_save_as_exception_creates_id_based_relationship(self):
        from core.decisions import record_decision

        memory = {
            "decisions": [decision("dec_logging", "Activity logging is mandatory for all writes.")],
            "decision_conflicts": [],
        }
        saved = {}

        result = record_decision(
            "project",
            "Bulk import may bypass activity logging.",
            "Performance migration.",
            actor="codex",
            actor_source="test",
            resolution_action="save_as_exception",
            resolution_target_id="dec_logging",
            _memory=memory,
            _save_fn=lambda _project_id, new_memory: saved.update(new_memory),
        )

        self.assertTrue(result.success)
        new_decision = saved["decisions"][-1]
        self.assertEqual(new_decision["relation"], "exception_to")
        self.assertEqual(new_decision["related_decision_id"], "dec_logging")
        self.assertEqual(saved["decision_conflicts"], [])

    def test_save_as_extends_creates_id_based_relationship(self):
        from core.decisions import record_decision

        memory = {
            "decisions": [decision("dec_rest", "Use REST API for public integrations.")],
            "decision_conflicts": [],
        }
        saved = {}

        result = record_decision(
            "project",
            "Add REST API versioning for public integrations.",
            "Compatibility.",
            actor="codex",
            actor_source="test",
            resolution_action="save_as_extends",
            resolution_target_id="dec_rest",
            _memory=memory,
            _save_fn=lambda _project_id, new_memory: saved.update(new_memory),
        )

        self.assertTrue(result.success)
        new_decision = saved["decisions"][-1]
        self.assertEqual(new_decision["relation"], "extends")
        self.assertEqual(new_decision["related_decision_id"], "dec_rest")

    def test_acknowledge_existing_does_not_save_duplicate(self):
        from core.decisions import record_decision

        memory = {
            "decisions": [decision("dec_dup", "Use REST API for public integrations.")],
            "decision_conflicts": [],
        }

        result = record_decision(
            "project",
            "Use REST API for public integrations.",
            "Duplicate.",
            actor="codex",
            actor_source="test",
            resolution_action="acknowledge_existing",
            resolution_target_id="dec_dup",
            _memory=memory,
            _save_fn=lambda _project_id, _memory: self.fail("save should not be called"),
        )

        self.assertTrue(result.success)
        self.assertEqual(len(memory["decisions"]), 1)

    def test_save_anyway_under_review_creates_one_canonical_open_review(self):
        from core.decisions import record_decision

        memory = {
            "decisions": [decision("dec_logging", "Activity logging is mandatory for all writes.")],
            "decision_conflicts": [],
        }
        saved = {}

        for _ in range(2):
            result = record_decision(
                "project",
                "Bulk import may bypass activity logging.",
                "Performance migration.",
                actor="codex",
                actor_source="test",
                resolution_action="save_anyway_under_review",
                resolution_target_id="dec_logging",
                _memory=memory,
                _save_fn=lambda _project_id, new_memory: saved.update(new_memory),
            )
            self.assertTrue(result.success)

        self.assertEqual(saved["decisions"][-1]["status"], "needs_review")
        open_reviews = [
            item for item in saved["decision_conflicts"]
            if item.get("status") == "open"
        ]
        self.assertEqual(len(open_reviews), 1)
        self.assertEqual(open_reviews[0]["type"], "PENDING_DECISION_REVIEW")


class TestPocketCRMManualScenarios(unittest.TestCase):
    def test_manual_acceptance_scenarios(self):
        from core.decision_review import review_decision

        scenarios = [
            (
                "A logging bypass",
                [decision("dec_logging", "Activity logging automatic on CRUD.")],
                "Bulk import bypasses activity logging.",
                "dec_logging",
                {"exception_to", "potential_conflict"},
                True,
            ),
            (
                "B validation bypass",
                [decision("dec_validation", "All customer data must be validated before storage.")],
                "Bulk customer import bypasses validation.",
                "dec_validation",
                {"exception_to", "potential_conflict"},
                True,
            ),
            (
                "C validation vs JSON storage",
                [decision("dec_json", "PocketCRM stores all entities in data/pocketcrm.json with per-collection arrays and metadata.")],
                "All customer imports may bypass validation.",
                None,
                set(),
                False,
            ),
            (
                "D unrelated ordinary decision",
                [decision("dec_react", "Use React for frontend components.")],
                "Use PostgreSQL for audit persistence.",
                None,
                set(),
                False,
            ),
        ]

        for name, existing, proposed, selected, relationships, requires_review in scenarios:
            with self.subTest(name):
                review = review_decision(proposed, "Manual simulation.", {"decisions": existing})
                self.assertEqual(review.requires_review, requires_review)
                if selected:
                    self.assertEqual(review.primary_candidate.id, selected)
                    self.assertIn(review.primary_candidate.relationship.value, relationships)
                else:
                    self.assertIsNone(review.primary_candidate)
                    self.assertEqual(review.allowed_actions, [])


class TestReplacementRetrievalRegression(unittest.TestCase):
    """Regression tests for replacement scenarios where wording differs but subject connects."""

    def test_json_storage_to_postgresql_replacement(self):
        from core.decision_review import review_decision

        existing = [decision(
            "dec_json_storage",
            "PocketCRM stores all entities in data/pocketcrm.json with per-collection arrays and a metadata section for next sequential numeric IDs."
        )]
        proposed = "Replace JSON storage with PostgreSQL as the primary persistence layer."
        reason = "The project has outgrown local JSON storage and now requires transactional guarantees."

        review = review_decision(proposed, reason, {"decisions": existing})

        self.assertTrue(review.requires_review, "JSON→PostgreSQL replacement must trigger review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.id, "dec_json_storage")
        self.assertIn(review.primary_candidate.relationship.value, {"supersedes", "potential_conflict"})
        self.assertIn("supersede_existing", [a.value for a in review.allowed_actions])

    def test_rest_api_to_graphql_replacement(self):
        from core.decision_review import review_decision

        existing = [decision("dec_rest", "All external integrations use REST API endpoints.")]
        proposed = "Replace REST API with GraphQL for all external integrations."

        review = review_decision(proposed, "Better query flexibility.", {"decisions": existing})

        self.assertTrue(review.requires_review, "REST→GraphQL replacement must trigger review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.id, "dec_rest")
        self.assertEqual(review.primary_candidate.relationship.value, "supersedes")

    def test_local_file_storage_to_database_replacement(self):
        from core.decision_review import review_decision

        existing = [decision("dec_file", "Application stores user data in local files under ~/.appdata/")]
        proposed = "Replace local file storage with SQLite database."

        review = review_decision(proposed, "Better querying.", {"decisions": existing})

        self.assertTrue(review.requires_review, "File→database replacement must trigger review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.id, "dec_file")
        self.assertIn(review.primary_candidate.relationship.value, {"supersedes", "potential_conflict"})

    def test_unrelated_decision_containing_replace_saves_normally(self):
        from core.decision_review import review_decision

        existing = [decision("dec_logging", "Activity logging is mandatory for all writes.")]
        proposed = "Replace deprecated lodash methods with native JavaScript equivalents."

        review = review_decision(proposed, "Reduce bundle size.", {"decisions": existing})

        self.assertFalse(review.requires_review, "Unrelated 'replace' must not trigger review")
        self.assertIsNone(review.primary_candidate)


class TestSuffixSafetyRegression(unittest.TestCase):
    """Verify protected words are NOT incorrectly collapsed by suffix matching."""

    def test_package_not_collapsed_to_pack(self):
        from core.decision_review import _tokens, _suffix_aware_overlap

        left = _tokens("Use npm for package management")
        right = _tokens("Pack items into containers")
        bonus = _suffix_aware_overlap(left, right)
        self.assertEqual(bonus, 0, "package must NOT match pack")

    def test_message_not_collapsed_to_mess(self):
        from core.decision_review import _tokens, _suffix_aware_overlap

        left = _tokens("Send message via WebSocket")
        right = _tokens("Clean up the mess in the codebase")
        bonus = _suffix_aware_overlap(left, right)
        self.assertEqual(bonus, 0, "message must NOT match mess")

    def test_usage_not_collapsed_to_us(self):
        from core.decision_review import _tokens, _suffix_aware_overlap

        left = _tokens("Track API usage metrics")
        right = _tokens("Contact us for support")
        bonus = _suffix_aware_overlap(left, right)
        self.assertEqual(bonus, 0, "usage must NOT match us (stem too short)")

    def test_language_not_collapsed_to_lang(self):
        from core.decision_review import _tokens, _suffix_aware_overlap

        left = _tokens("Support multiple language options")
        right = _tokens("Use lang attribute for i18n")
        bonus = _suffix_aware_overlap(left, right)
        self.assertEqual(bonus, 0, "language must NOT match lang")

    def test_coverage_not_collapsed_without_direct_overlap(self):
        from core.decision_review import _tokens, _suffix_aware_overlap

        left = _tokens("Increase test coverage")
        right = _tokens("Use React for components")
        bonus = _suffix_aware_overlap(left, right)
        self.assertEqual(bonus, 0, "coverage must NOT match without direct overlap")

    def test_storage_matches_stores_with_direct_overlap(self):
        from core.decision_review import _tokens, _suffix_aware_overlap

        left = _tokens("Replace JSON storage with PostgreSQL")
        right = _tokens("PocketCRM stores all entities in data/pocketcrm.json")
        direct = left & right
        bonus = _suffix_aware_overlap(left, right)
        self.assertTrue(len(direct) > 0, "Should have direct overlap (json)")
        self.assertEqual(bonus, 1, "storage should match stor when direct overlap exists")


class TestStructuralExtensionRegression(unittest.TestCase):
    """Regression tests for containment-based extension detection."""

    def test_validation_with_per_field_errors(self):
        from core.decision_review import review_decision

        existing = [decision("dec_val", "All customer data must be validated before storage.")]
        proposed = "All customer data must be validated before storage, with validation errors reported per field."
        reason = "Keep the existing validation requirement while making failures easier to diagnose."

        review = review_decision(proposed, reason, {"decisions": existing})

        self.assertTrue(review.requires_review, "Extension must trigger review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.id, "dec_val")
        self.assertEqual(review.primary_candidate.relationship.value, "extends")
        self.assertIn("save_as_extends", [a.value for a in review.allowed_actions])

    def test_json_storage_with_atomic_writes(self):
        from core.decision_review import review_decision

        existing = [decision("dec_json", "Store all entities in a unified JSON file.")]
        proposed = "Store all entities in a unified JSON file with atomic write operations."

        review = review_decision(proposed, "Prevent corruption.", {"decisions": existing})

        self.assertTrue(review.requires_review, "Extension must trigger review")
        self.assertEqual(review.primary_candidate.relationship.value, "extends")

    def test_rest_api_with_pagination(self):
        from core.decision_review import review_decision

        existing = [decision("dec_rest", "Use REST API for public integrations.")]
        proposed = "Use REST API for public integrations with cursor-based pagination."

        review = review_decision(proposed, "Scalability.", {"decisions": existing})

        self.assertTrue(review.requires_review, "Extension must trigger review")
        self.assertEqual(review.primary_candidate.relationship.value, "extends")

    def test_encryption_with_key_rotation(self):
        from core.decision_review import review_decision

        existing = [decision("dec_encrypt", "Stored exports must be encrypted.")]
        proposed = "Stored exports must be encrypted with quarterly key rotation."

        review = review_decision(proposed, "Compliance.", {"decisions": existing})

        self.assertTrue(review.requires_review, "Extension must trigger review")
        self.assertEqual(review.primary_candidate.relationship.value, "extends")

    def test_unrelated_similar_wording_not_extension(self):
        from core.decision_review import review_decision

        existing = [decision("dec_logging", "Activity logging is mandatory for all writes.")]
        proposed = "Error logging is mandatory for all API endpoints."

        review = review_decision(proposed, "Observability.", {"decisions": existing})

        if review.requires_review:
            self.assertNotEqual(
                review.primary_candidate.relationship.value, "extends",
                "Similar wording without containment must NOT be classified as extends"
            )


class TestReversalDetectionRegression(unittest.TestCase):
    """Regression tests for reversal scenarios where existing proposes change, proposed wants to keep."""

    def test_keep_json_after_replace_json_with_postgresql(self):
        """
        Regression: Issue where proposed 'Keep JSON' was saved with only a WARNING
        instead of blocking for DECISION REVIEW when existing said 'Replace JSON with PostgreSQL'.

        Expected: requires_review=True, relationship=potential_conflict, no save until resolved.
        """
        from core.decision_review import review_decision
        from core.decisions import record_decision

        existing = [decision(
            "dec_replace_json",
            "Replace JSON storage with PostgreSQL as the primary persistence layer."
        )]
        proposed = "Keep JSON storage as the primary persistence layer for PocketCRM."
        reason = "PocketCRM should remain local-first and simple for solo freelancers."

        review = review_decision(proposed, reason, {"decisions": existing})

        self.assertTrue(review.requires_review, "Keep after Replace must trigger review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.id, "dec_replace_json")
        self.assertEqual(review.primary_candidate.relationship.value, "potential_conflict")
        self.assertIn("supersede_existing", [a.value for a in review.allowed_actions])
        self.assertIn("save_anyway_under_review", [a.value for a in review.allowed_actions])
        self.assertIn("cancel", [a.value for a in review.allowed_actions])

        memory = {"decisions": [dict(d) for d in existing], "decision_conflicts": []}
        saved = {}

        result = record_decision(
            "pocketcrm",
            proposed,
            reason,
            actor="codex",
            actor_source="test",
            _memory=memory,
            _save_fn=lambda _pid, mem: saved.update(mem),
        )

        self.assertFalse(result.success, "Decision must NOT be saved before review")
        self.assertTrue(result.requires_review, "Must require review")
        self.assertEqual(saved, {}, "No save should have occurred")

    def test_maintain_rest_after_replace_rest_with_graphql(self):
        from core.decision_review import review_decision

        existing = [decision("dec_replace_rest", "Replace REST API with GraphQL for all integrations.")]
        proposed = "Maintain REST API for all integrations."

        review = review_decision(proposed, "GraphQL complexity not worth it.", {"decisions": existing})

        self.assertTrue(review.requires_review, "Maintain after Replace must trigger review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.relationship.value, "potential_conflict")

    def test_stay_with_sqlite_after_migrate_to_postgresql(self):
        from core.decision_review import review_decision

        existing = [decision("dec_migrate", "Migrate from SQLite to PostgreSQL for production.")]
        proposed = "Stay with SQLite for all environments."

        review = review_decision(proposed, "Simplicity.", {"decisions": existing})

        self.assertTrue(review.requires_review, "Stay after Migrate must trigger review")
        self.assertIsNotNone(review.primary_candidate)
        self.assertEqual(review.primary_candidate.relationship.value, "potential_conflict")

    def test_unrelated_keep_does_not_trigger_false_positive(self):
        from core.decision_review import review_decision

        existing = [decision("dec_logging", "Activity logging is mandatory for all writes.")]
        proposed = "Keep using npm for package management."

        review = review_decision(proposed, "Consistency.", {"decisions": existing})

        self.assertFalse(review.requires_review, "Unrelated 'keep' must not trigger review")

    def test_use_rest_client_after_replace_rest_with_graphql_no_conflict(self):
        """'use' is too generic - should NOT trigger reversal detection."""
        from core.decision_review import review_decision

        existing = [decision("dec_replace_rest", "Replace REST API with GraphQL for all integrations.")]
        proposed = "Use REST client library for internal tooling."

        review = review_decision(proposed, "Temporary internal tooling.", {"decisions": existing})

        self.assertFalse(review.requires_review, "'Use REST client' must NOT trigger reversal conflict")

    def test_use_json_fixtures_after_replace_json_with_postgresql_no_conflict(self):
        """'use' is too generic - should NOT trigger reversal detection."""
        from core.decision_review import review_decision

        existing = [decision("dec_replace_json", "Replace JSON storage with PostgreSQL as the primary persistence layer.")]
        proposed = "Use JSON fixtures in tests."

        review = review_decision(proposed, "Test data format.", {"decisions": existing})

        self.assertFalse(review.requires_review, "'Use JSON fixtures' must NOT trigger reversal conflict")

    def test_keep_json_after_replace_json_still_triggers_review(self):
        """Explicit 'keep' should still trigger review after 'replace'."""
        from core.decision_review import review_decision

        existing = [decision("dec_replace_json", "Replace JSON storage with PostgreSQL as the primary persistence layer.")]
        proposed = "Keep JSON as primary storage."

        review = review_decision(proposed, "Simplicity.", {"decisions": existing})

        self.assertTrue(review.requires_review, "'Keep JSON' after 'Replace JSON' must trigger review")
        self.assertEqual(review.primary_candidate.relationship.value, "potential_conflict")


class TestDecouplingFalsePositiveRegression(unittest.TestCase):
    """Regression tests for architectural decoupling language NOT triggering exception_to."""

    def test_click_cli_vs_business_logic_independent_no_review(self):
        from core.decision_review import review_decision

        existing = [decision("dec_click", "Use Click for the CLI interface.")]
        proposed = "Keep business logic independent from transport layers."

        review = review_decision(proposed, "Architecture rule.", {"decisions": existing})

        if review.requires_review:
            self.assertNotEqual(
                review.primary_candidate.relationship.value, "exception_to",
                "Architectural decoupling must NOT be classified as exception_to"
            )

    def test_rest_api_vs_transport_agnostic_core_no_review(self):
        from core.decision_review import review_decision

        existing = [decision("dec_rest", "Use REST API for public integrations.")]
        proposed = "Core business logic must be transport-agnostic."

        review = review_decision(proposed, "Clean architecture.", {"decisions": existing})

        if review.requires_review:
            self.assertNotEqual(
                review.primary_candidate.relationship.value, "exception_to",
                "transport-agnostic must NOT trigger exception_to"
            )

    def test_ui_framework_vs_business_logic_decoupled_no_review(self):
        from core.decision_review import review_decision

        existing = [decision("dec_react", "Use React for frontend components.")]
        proposed = "Business logic must be decoupled from UI frameworks."

        review = review_decision(proposed, "Testability.", {"decisions": existing})

        if review.requires_review:
            self.assertNotEqual(
                review.primary_candidate.relationship.value, "exception_to",
                "decoupled from must NOT trigger exception_to"
            )

    def test_activity_logging_vs_bulk_import_bypasses_is_exception(self):
        from core.decision_review import review_decision

        existing = [decision("dec_logging", "Activity logging is mandatory for all writes.")]
        proposed = "Bulk import bypasses activity logging."

        review = review_decision(proposed, "Performance.", {"decisions": existing})

        self.assertTrue(review.requires_review, "Rule bypass must trigger review")
        self.assertEqual(review.primary_candidate.relationship.value, "exception_to")

    def test_validation_vs_trusted_import_may_skip_is_exception(self):
        from core.decision_review import review_decision

        existing = [decision("dec_val", "All customer data must be validated before storage.")]
        proposed = "Trusted bulk import may skip validation."

        review = review_decision(proposed, "Migration speed.", {"decisions": existing})

        self.assertTrue(review.requires_review, "Rule skip must trigger review")
        self.assertEqual(review.primary_candidate.relationship.value, "exception_to")


class TestOppositionDetectionRegression(unittest.TestCase):
    """Regression tests for opposing intent detection triggering review."""

    def test_automatic_vs_manual_triggers_review(self):
        from core.decision_review import review_decision

        existing = [decision("dec_logging", "Activity logging must happen automatically on every CRUD operation.")]
        proposed = "Activity logging should be performed manually only when explicitly requested."

        review = review_decision(proposed, "Test.", {"decisions": existing})

        self.assertTrue(review.requires_review, "Automatic vs manual must trigger review")
        self.assertEqual(review.primary_candidate.relationship.value, "potential_conflict")

    def test_never_cascade_vs_cascade_triggers_review(self):
        from core.decision_review import review_decision

        existing = [decision("dec_cascade", "Customer deletion must never cascade automatically.")]
        proposed = "Customer deletion should cascade automatically."

        review = review_decision(proposed, "Test.", {"decisions": existing})

        self.assertTrue(review.requires_review, "Never vs should must trigger review")
        self.assertEqual(review.primary_candidate.relationship.value, "potential_conflict")

    def test_compatible_refinement_no_false_positive(self):
        from core.decision_review import review_decision

        existing = [decision("dec_arch", "Keep business logic independent from transport layers.")]
        proposed = "Business logic must expose transport-neutral service interfaces."

        review = review_decision(proposed, "Clean arch.", {"decisions": existing})

        if review.requires_review:
            self.assertNotEqual(
                review.primary_candidate.relationship.value, "potential_conflict",
                "Compatible refinement must NOT be potential_conflict"
            )

    def test_unrelated_automatic_manual_no_false_positive(self):
        from core.decision_review import review_decision

        existing = [decision("dec_backup", "Database backups run automatically every hour.")]
        proposed = "Code reviews should be done manually before merge."

        review = review_decision(proposed, "Process.", {"decisions": existing})

        self.assertFalse(review.requires_review, "Unrelated automatic/manual must NOT trigger review")


class TestBriefingSurfacing(unittest.TestCase):
    def test_pending_review_is_in_briefing_focus(self):
        from core.briefing_composer import _extract_focus

        memory = {
            "live_record": {},
            "decisions": [],
            "decision_conflicts": [{
                "id": "conflict_1",
                "status": "open",
                "type": "PENDING_DECISION_REVIEW",
                "proposed_decision": {"text": "Bulk import bypasses activity logging."},
                "existing_decision": {"decision": "Activity logging automatic on CRUD."},
            }],
        }

        focus = _extract_focus(memory, "")

        self.assertTrue(any("Decision review needed" in item for item in focus))


if __name__ == "__main__":
    unittest.main()
