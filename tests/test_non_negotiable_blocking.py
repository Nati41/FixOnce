#!/usr/bin/env python3
"""Tests for non-negotiable constraint blocking in decision validation."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "mcp_server"))


class _FakeFastMCP:
    def __init__(self, *_args, **_kwargs):
        pass

    def tool(self, *_args, **_kwargs):
        def decorator(func):
            return func
        return decorator


sys.modules.setdefault("fastmcp", types.SimpleNamespace(FastMCP=_FakeFastMCP))

from core.policy_engine import (
    check_non_negotiable_violations,
    check_avoid_pattern_conflicts,
    detect_conflicts,
    validate_decision,
)
import mcp_memory_server_v2 as server


class TestNonNegotiableViolations(unittest.TestCase):
    """Test check_non_negotiable_violations function."""

    def test_firebase_blocked_by_local_only(self):
        """Firebase should be blocked when 'local only' non-negotiable exists."""
        non_negotiables = [
            {"text": "Local only", "status": "active"}
        ]
        violations = check_non_negotiable_violations(
            "Use Firebase for storage",
            non_negotiables
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["severity"], "HIGH")
        self.assertEqual(violations[0]["type"], "NON_NEGOTIABLE_VIOLATION")
        self.assertIn("firebase", violations[0]["blocked_keyword"])

    def test_firebase_blocked_by_no_cloud(self):
        """Firebase should be blocked when 'no cloud' non-negotiable exists."""
        non_negotiables = [
            {"text": "No cloud services", "status": "active"}
        ]
        violations = check_non_negotiable_violations(
            "Move storage to Firebase",
            non_negotiables
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["severity"], "HIGH")
        self.assertIn("firebase", violations[0]["blocked_keyword"])

    def test_firestore_blocked_by_no_cloud(self):
        """Firestore should be blocked when 'no cloud' non-negotiable exists."""
        non_negotiables = [
            {"text": "No cloud", "status": "active"}
        ]
        violations = check_non_negotiable_violations(
            "Use Firestore for data",
            non_negotiables
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["severity"], "HIGH")

    def test_postgres_blocked_by_no_database(self):
        """PostgreSQL should be blocked when 'no database' non-negotiable exists."""
        non_negotiables = [
            {"text": "No database", "status": "active"}
        ]
        violations = check_non_negotiable_violations(
            "Use PostgreSQL for storage",
            non_negotiables
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["severity"], "HIGH")
        self.assertIn(violations[0]["blocked_keyword"], ["postgres", "postgresql", "sql", "database"])

    def test_sqlite_blocked_by_no_database(self):
        """SQLite should be blocked when 'no database' non-negotiable exists."""
        non_negotiables = [
            {"text": "No database", "status": "active"}
        ]
        violations = check_non_negotiable_violations(
            "Use SQLite for local storage",
            non_negotiables
        )
        self.assertEqual(len(violations), 1)

    def test_json_storage_allowed_under_local_only(self):
        """Local JSON storage should NOT be blocked by 'local only'."""
        non_negotiables = [
            {"text": "Local only", "status": "active"}
        ]
        violations = check_non_negotiable_violations(
            "Use JSON file for storage",
            non_negotiables
        )
        self.assertEqual(len(violations), 0)

    def test_json_storage_allowed_under_no_cloud(self):
        """Local JSON storage should NOT be blocked by 'no cloud services'."""
        non_negotiables = [
            {"text": "No cloud services", "status": "active"}
        ]
        violations = check_non_negotiable_violations(
            "Store data in local JSON files",
            non_negotiables
        )
        self.assertEqual(len(violations), 0)

    def test_inactive_non_negotiable_ignored(self):
        """Inactive non-negotiables should not block anything."""
        non_negotiables = [
            {"text": "Local only", "status": "inactive"}
        ]
        violations = check_non_negotiable_violations(
            "Use Firebase for storage",
            non_negotiables
        )
        self.assertEqual(len(violations), 0)

    def test_aws_blocked_by_no_external_service(self):
        """AWS should be blocked by 'no external service'."""
        non_negotiables = [
            {"text": "No external service", "status": "active"}
        ]
        violations = check_non_negotiable_violations(
            "Deploy to AWS Lambda",
            non_negotiables
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["severity"], "HIGH")

    def test_multiple_non_negotiables_all_checked(self):
        """Multiple non-negotiables should all be checked."""
        non_negotiables = [
            {"text": "Local only", "status": "active"},
            {"text": "No database", "status": "active"},
        ]
        violations = check_non_negotiable_violations(
            "Use Firebase with Firestore database",
            non_negotiables
        )
        self.assertGreaterEqual(len(violations), 1)


class TestAvoidPatternConflicts(unittest.TestCase):
    """Test check_avoid_pattern_conflicts function."""

    def test_avoid_pattern_creates_medium_conflict(self):
        """Avoid patterns should create MEDIUM severity conflicts."""
        avoid_patterns = [
            {"what": "External API calls", "reason": "Keep it simple"}
        ]
        conflicts = check_avoid_pattern_conflicts(
            "Add external API integration",
            avoid_patterns
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["severity"], "MEDIUM")
        self.assertEqual(conflicts[0]["type"], "AVOID_PATTERN_CONFLICT")

    def test_no_conflict_when_avoid_not_matched(self):
        """No conflict when decision doesn't match avoid pattern."""
        avoid_patterns = [
            {"what": "External API calls", "reason": "Keep it simple"}
        ]
        conflicts = check_avoid_pattern_conflicts(
            "Use local JSON storage",
            avoid_patterns
        )
        self.assertEqual(len(conflicts), 0)


class TestDetectConflictsIntegration(unittest.TestCase):
    """Test detect_conflicts with non-negotiables and avoid patterns."""

    def test_non_negotiable_violation_is_highest_priority(self):
        """Non-negotiable violations should appear first (HIGH severity)."""
        existing_decisions = [
            {"decision": "Use JSON for storage", "reason": "Simple"}
        ]
        non_negotiables = [
            {"text": "Local only", "status": "active"}
        ]
        conflicts = detect_conflicts(
            "Move to Firebase",
            "Better sync",
            existing_decisions,
            non_negotiables=non_negotiables,
        )
        self.assertGreater(len(conflicts), 0)
        self.assertEqual(conflicts[0]["type"], "NON_NEGOTIABLE_VIOLATION")
        self.assertEqual(conflicts[0]["severity"], "HIGH")

    def test_avoid_pattern_included_in_conflicts(self):
        """Avoid patterns should be included in conflict detection."""
        avoid_patterns = [
            {"what": "Cloud services", "reason": "Stay local"}
        ]
        conflicts = detect_conflicts(
            "Use cloud storage",
            "Better availability",
            [],
            avoid_patterns=avoid_patterns,
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["type"], "AVOID_PATTERN_CONFLICT")


class TestValidateDecisionWithConstraints(unittest.TestCase):
    """Test validate_decision with non-negotiables and avoid patterns."""

    def test_firebase_decision_blocked_by_local_only(self):
        """Firebase decision should be blocked when 'local only' exists."""
        non_negotiables = [
            {"text": "Local only", "status": "active"}
        ]
        is_valid, message, conflicts = validate_decision(
            "Use Firebase for storage",
            "Cloud sync",
            [],
            non_negotiables=non_negotiables,
        )
        self.assertFalse(is_valid)
        self.assertIn("BLOCKED", message)
        self.assertIn("NON_NEGOTIABLE_VIOLATION", conflicts[0]["type"])

    def test_postgres_decision_blocked_by_no_database(self):
        """PostgreSQL decision should be blocked when 'no database' exists."""
        non_negotiables = [
            {"text": "No database", "status": "active"}
        ]
        is_valid, message, conflicts = validate_decision(
            "Use PostgreSQL",
            "Relational data",
            [],
            non_negotiables=non_negotiables,
        )
        self.assertFalse(is_valid)
        self.assertIn("BLOCKED", message)

    def test_force_overrides_non_negotiable_blocking(self):
        """Force flag should allow override of non-negotiable blocking."""
        non_negotiables = [
            {"text": "Local only", "status": "active"}
        ]
        is_valid, message, conflicts = validate_decision(
            "Use Firebase for storage",
            "Cloud sync required",
            [],
            non_negotiables=non_negotiables,
            force=True,
        )
        self.assertTrue(is_valid)
        self.assertIn("OVERRIDE", message)
        self.assertGreater(len(conflicts), 0)

    def test_json_storage_passes_validation(self):
        """JSON storage should pass validation under local-only constraint."""
        non_negotiables = [
            {"text": "Local only", "status": "active"},
            {"text": "No cloud services", "status": "active"},
        ]
        is_valid, message, conflicts = validate_decision(
            "Use JSON files for storage",
            "Simple and local",
            [],
            non_negotiables=non_negotiables,
        )
        self.assertTrue(is_valid)
        self.assertEqual(len(conflicts), 0)


class TestLogDecisionWithNonNegotiables(unittest.TestCase):
    """Integration test for log_decision with non-negotiables."""

    def _activate(self, root: Path, memory):
        project_id = "project-constraints"
        project_file = root / f"{project_id}.json"
        project_file.write_text(json.dumps(memory), encoding="utf-8")
        session = server.SessionContext(project_id=project_id, working_dir=str(root))
        session.initialized_at = "2026-06-07T08:00:00"
        patches = [
            patch.object(server, "DATA_DIR", root),
            patch.object(server, "INDEX_FILE", root / "project_index.json"),
            patch.object(server, "_get_session", return_value=session),
            patch.object(server, "_universal_gate", return_value=("", "")),
            patch.object(server, "_require_session", return_value=None),
            patch.object(server, "_intervention_policy_available", False),
            patch.object(server, "_resolve_actor_identity", return_value={
                "editor": "claude",
                "source": "client_actor",
                "confidence": 1.0,
            }),
            patch.object(server, "_load_project_semantic", return_value=None),
            patch.object(server, "_log_mcp_activity", return_value=None),
            patch.object(server, "_track_roi_event", return_value=None),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return project_file

    def test_firebase_decision_blocked_in_log_decision(self):
        """log_decision should block Firebase when local-only non-negotiable exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._activate(root, {
                "decisions": [],
                "live_record": {
                    "vision": {
                        "non_negotiables": [
                            {"text": "Local only", "status": "active"}
                        ]
                    }
                },
            })

            result = server.log_decision(
                "Use Firebase for storage",
                "Better sync capabilities",
            )

        self.assertIn("BLOCKED", result)
        self.assertIn("Decision NOT logged", result)

    def test_postgres_decision_blocked_by_no_database(self):
        """log_decision should block PostgreSQL when no-database non-negotiable exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._activate(root, {
                "decisions": [],
                "live_record": {
                    "vision": {
                        "non_negotiables": [
                            {"text": "No database", "status": "active"}
                        ]
                    }
                },
            })

            result = server.log_decision(
                "Use PostgreSQL for data storage",
                "Relational queries needed",
            )

        self.assertIn("BLOCKED", result)
        self.assertIn("Decision NOT logged", result)

    def test_json_storage_allowed_with_local_only(self):
        """log_decision should allow JSON storage under local-only constraint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, {
                "decisions": [],
                "live_record": {
                    "vision": {
                        "non_negotiables": [
                            {"text": "Local only", "status": "active"},
                            {"text": "No cloud services", "status": "active"},
                        ]
                    }
                },
            })

            result = server.log_decision(
                "Use JSON files for storage",
                "Simple local persistence",
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertIn("Decision recorded", result)
        self.assertEqual(len(saved["decisions"]), 1)

    def test_force_override_records_conflict(self):
        """Force override should record the conflict resolution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, {
                "decisions": [],
                "live_record": {
                    "vision": {
                        "non_negotiables": [
                            {"text": "Local only", "status": "active"}
                        ]
                    }
                },
            })

            result = server.log_decision(
                "Use Firebase for storage",
                "Cloud sync required",
                force=True,
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertIn("Decision recorded", result)
        self.assertEqual(len(saved["decisions"]), 1)
        self.assertTrue(saved["decisions"][0].get("forced"))
        self.assertIn("decision_conflicts", saved)
        self.assertEqual(saved["decision_conflicts"][0]["resolution"]["action"], "accepted_override")


class TestExistingConflictLifecyclePreserved(unittest.TestCase):
    """Verify existing decision conflict behavior is preserved."""

    def _activate(self, root: Path, memory):
        project_id = "project-lifecycle"
        project_file = root / f"{project_id}.json"
        project_file.write_text(json.dumps(memory), encoding="utf-8")
        session = server.SessionContext(project_id=project_id, working_dir=str(root))
        session.initialized_at = "2026-06-07T08:00:00"
        patches = [
            patch.object(server, "DATA_DIR", root),
            patch.object(server, "INDEX_FILE", root / "project_index.json"),
            patch.object(server, "_get_session", return_value=session),
            patch.object(server, "_universal_gate", return_value=("", "")),
            patch.object(server, "_require_session", return_value=None),
            patch.object(server, "_intervention_policy_available", False),
            patch.object(server, "_resolve_actor_identity", return_value={
                "editor": "claude",
                "source": "client_actor",
                "confidence": 1.0,
            }),
            patch.object(server, "_load_project_semantic", return_value=None),
            patch.object(server, "_log_mcp_activity", return_value=None),
            patch.object(server, "_track_roi_event", return_value=None),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return project_file

    def test_decision_contradiction_still_blocked(self):
        """Existing decision contradiction detection should still work."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._activate(root, {
                "decisions": [{
                    "decision": "Always store API data in English",
                    "reason": "Integration consistency",
                    "actor": "claude",
                    "actor_source": "client_actor",
                    "timestamp": "2026-06-01T10:00:00",
                }],
            })

            result = server.log_decision(
                "Never store API data in English",
                "Localization requirement",
            )

        self.assertIn("Decision NOT logged", result)

    def test_warn_level_conflicts_still_logged(self):
        """MEDIUM severity conflicts should still warn but allow logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, {
                "decisions": [{
                    "decision": "Use REST API for auth",
                    "reason": "Conventional API shape",
                }],
            })

            result = server.log_decision(
                "Use REST API for authentication",
                "Keep auth endpoints conventional",
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertIn("Decision recorded", result)
        self.assertEqual(len(saved["decisions"]), 2)

    def test_refine_action_allows_dogfooding_policy_clarification(self):
        """Explicit refinements should not be blocked as contradictions."""
        old_decision = "Dogfooding: AI must use FixOnce MCP tools in real-time to demonstrate the product"
        new_refinement = (
            "FixOnce default behavior is context-before-action, not hard-blocking. "
            "Hard-blocking is reserved for proven-danger protected paths and tool runtimes "
            "that support enforcement. Codex CLI 0.140.0 has a known limitation: "
            "exec_command reads are not caught by PreToolUse hooks."
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, {
                "decisions": [{
                    "decision": old_decision,
                    "reason": (
                        "If the AI doesn't use FixOnce correctly, how can we expect users to? "
                        "Every session = auto_init + update_work_context"
                    ),
                    "timestamp": "2026-03-17T11:35:34.897953",
                }],
            })

            result = server.fo_decide(
                new_refinement,
                "Clarifies dogfooding enforcement scope without replacing the policy.",
                action=f"refine:{old_decision}",
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertIn("Decision recorded", result)
        self.assertNotIn("Decision NOT logged", result)
        self.assertEqual(len(saved["decisions"]), 2)
        recorded = saved["decisions"][1]
        self.assertEqual(recorded["relation"], "refines")
        self.assertEqual(recorded["related_decision"], old_decision)
        self.assertTrue(recorded.get("related_decision_fingerprint"))
        self.assertFalse(recorded.get("forced"))

    def test_refine_action_does_not_bypass_unrelated_contradictions(self):
        """Refine only relaxes conflicts against the explicitly related decision."""
        old_decision = "Dogfooding: AI must use FixOnce MCP tools in real-time to demonstrate the product"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, {
                "decisions": [
                    {
                        "decision": old_decision,
                        "reason": "Existing dogfooding policy",
                    },
                    {
                        "decision": "Always store API data in English",
                        "reason": "Integration consistency",
                    },
                ],
            })

            result = server.fo_decide(
                "Never store API data in English",
                "Localization requirement",
                action=f"refine:{old_decision}",
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertIn("Decision NOT logged", result)
        self.assertEqual(len(saved["decisions"]), 2)


if __name__ == "__main__":
    unittest.main()
