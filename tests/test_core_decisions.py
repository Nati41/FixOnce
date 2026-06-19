"""
Tests for core decision recording logic.

These tests verify that decisions can be recorded WITHOUT MCP.
This proves the architecture rule: core logic is transport-independent.
"""

import json
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to path
TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))


class TestRecordDecisionCore(unittest.TestCase):
    """Test record_decision without MCP."""

    def setUp(self):
        """Create temp directory for test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_project_id = "test_core_decision_project"
        self.projects_dir = Path(self.temp_dir) / "projects"
        self.projects_dir.mkdir(parents=True)

        # Create project memory file
        self.project_file = self.projects_dir / f"{self.test_project_id}.json"
        self.project_file.write_text(json.dumps({
            "decisions": [],
            "avoid": [],
        }))

        # Patch V2 directory
        self.v2_dir = Path(self.temp_dir) / "projects_v2" / self.test_project_id
        self.v2_patcher = patch(
            "core.knowledge_objects._get_v2_dir",
            return_value=self.v2_dir
        )
        self.v2_patcher.start()

    def tearDown(self):
        self.v2_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _patch_project_path(self):
        """Patch get_project_path to use temp directory."""
        return patch(
            "managers.multi_project_manager.get_project_path",
            return_value=self.project_file
        )

    def test_record_decision_success(self):
        """Decision can be recorded through core function without MCP."""
        from core.decisions import record_decision

        with self._patch_project_path():
            result = record_decision(
                project_id=self.test_project_id,
                text="Use PostgreSQL for database",
                reason="Better scalability",
                actor="test_user",
                actor_source="unit_test",
            )

        self.assertTrue(result.success)
        self.assertIn("Decision recorded", result.message)
        self.assertEqual(result.conflicts, [])

        # Verify V1 was updated
        memory = json.loads(self.project_file.read_text())
        self.assertEqual(len(memory['decisions']), 1)
        self.assertEqual(memory['decisions'][0]['decision'], "Use PostgreSQL for database")
        self.assertEqual(memory['decisions'][0]['actor'], "test_user")

    def test_record_decision_creates_v2_pending(self):
        """Decision creates V2 knowledge object in pending."""
        from core.decisions import record_decision
        from core.knowledge_objects import _ensure_v2_structure, get_pending_changes

        _ensure_v2_structure(self.test_project_id)

        with self._patch_project_path():
            result = record_decision(
                project_id=self.test_project_id,
                text="Core architecture test decision",
                reason="Testing V2 pending creation without MCP",
                actor="dashboard",
                actor_source="rest_api",
            )

        self.assertTrue(result.success)
        self.assertIsNotNone(result.decision_id)
        self.assertTrue(result.decision_id.startswith("dec_"))

        # Verify V2 pending has the decision
        pending = get_pending_changes(self.test_project_id)
        self.assertIn(result.decision_id, pending['decisions'])

    def test_record_decision_requires_project_id(self):
        """Decision recording fails without project_id."""
        from core.decisions import record_decision

        result = record_decision(
            project_id="",
            text="Some decision",
            reason="Some reason",
        )

        self.assertFalse(result.success)
        self.assertIn("project_id is required", result.message)

    def test_record_decision_requires_text(self):
        """Decision recording fails without text."""
        from core.decisions import record_decision

        with self._patch_project_path():
            result = record_decision(
                project_id=self.test_project_id,
                text="",
                reason="Some reason",
            )

        self.assertFalse(result.success)
        self.assertIn("text is required", result.message)

    def test_record_decision_with_relation(self):
        """Decision can have relation to existing decision."""
        from core.decisions import record_decision

        with self._patch_project_path():
            # First decision
            record_decision(
                project_id=self.test_project_id,
                text="Use REST API",
                reason="Standard approach",
                actor="user",
                actor_source="test",
            )

            # Related decision
            result = record_decision(
                project_id=self.test_project_id,
                text="Use REST API with versioning",
                reason="Better backwards compatibility",
                actor="user",
                actor_source="test",
                relation="refines",
                related_decision="Use REST API",
            )

        self.assertTrue(result.success)

        memory = json.loads(self.project_file.read_text())
        refined = memory['decisions'][1]
        self.assertEqual(refined['relation'], "refines")
        self.assertEqual(refined['related_decision'], "Use REST API")


class TestRecordAvoidCore(unittest.TestCase):
    """Test record_avoid without MCP."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_project_id = "test_core_avoid_project"
        self.projects_dir = Path(self.temp_dir) / "projects"
        self.projects_dir.mkdir(parents=True)

        self.project_file = self.projects_dir / f"{self.test_project_id}.json"
        self.project_file.write_text(json.dumps({
            "decisions": [],
            "avoid": [],
        }))

        self.v2_dir = Path(self.temp_dir) / "projects_v2" / self.test_project_id
        self.v2_patcher = patch(
            "core.knowledge_objects._get_v2_dir",
            return_value=self.v2_dir
        )
        self.v2_patcher.start()

    def tearDown(self):
        self.v2_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _patch_project_path(self):
        return patch(
            "managers.multi_project_manager.get_project_path",
            return_value=self.project_file
        )

    def test_record_avoid_success(self):
        """Avoid pattern can be recorded through core function without MCP."""
        from core.decisions import record_avoid

        with self._patch_project_path():
            result = record_avoid(
                project_id=self.test_project_id,
                text="Never use eval()",
                reason="Security risk",
                actor="test_user",
                actor_source="unit_test",
            )

        self.assertTrue(result.success)
        self.assertIn("Avoid pattern recorded", result.message)

        # Verify V1 was updated
        memory = json.loads(self.project_file.read_text())
        self.assertEqual(len(memory['avoid']), 1)
        self.assertEqual(memory['avoid'][0]['what'], "Never use eval()")

    def test_record_avoid_creates_v2_pending(self):
        """Avoid creates V2 knowledge object in pending."""
        from core.decisions import record_avoid
        from core.knowledge_objects import _ensure_v2_structure, get_pending_changes

        _ensure_v2_structure(self.test_project_id)

        with self._patch_project_path():
            result = record_avoid(
                project_id=self.test_project_id,
                text="Avoid mocking database in integration tests",
                reason="Previous incident with divergence",
                actor="user",
                actor_source="rest_api",
            )

        self.assertTrue(result.success)
        self.assertIsNotNone(result.decision_id)
        self.assertTrue(result.decision_id.startswith("avoid_"))

        # Verify V2 pending has the avoid
        pending = get_pending_changes(self.test_project_id)
        self.assertIn(result.decision_id, pending['avoids'])


class TestPendingKnowledgeWithoutMCP(unittest.TestCase):
    """
    Test that pending knowledge can be created and committed without MCP.

    This is the key architectural proof: the full flow works without MCP.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_project_id = "test_pending_no_mcp"
        self.projects_dir = Path(self.temp_dir) / "projects"
        self.projects_dir.mkdir(parents=True)

        self.project_file = self.projects_dir / f"{self.test_project_id}.json"
        self.project_file.write_text(json.dumps({
            "decisions": [],
            "avoid": [],
        }))

        self.v2_dir = Path(self.temp_dir) / "projects_v2" / self.test_project_id
        self.v2_patcher = patch(
            "core.knowledge_objects._get_v2_dir",
            return_value=self.v2_dir
        )
        self.v2_patcher.start()

    def tearDown(self):
        self.v2_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _patch_project_path(self):
        return patch(
            "managers.multi_project_manager.get_project_path",
            return_value=self.project_file
        )

    def test_full_flow_without_mcp(self):
        """
        Full decision → pending → commit flow without MCP.

        This test proves the architecture rule is working:
        1. record_decision (core) creates V2 object
        2. V2 object appears in pending
        3. create_commit clears pending and creates commit
        """
        from core.decisions import record_decision
        from core.knowledge_objects import (
            _ensure_v2_structure,
            get_pending_objects,
            create_commit,
            get_commit,
        )

        _ensure_v2_structure(self.test_project_id)

        # Step 1: Record decision via core (no MCP)
        with self._patch_project_path():
            result = record_decision(
                project_id=self.test_project_id,
                text="Architecture: MCP is adapter only",
                reason="Core logic must be transport-independent",
                actor="user",
                actor_source="architecture_rule",
            )

        self.assertTrue(result.success)
        dec_id = result.decision_id

        # Step 2: Verify pending has the decision
        pending = get_pending_objects(self.test_project_id)
        self.assertEqual(len(pending['decisions']), 1)
        self.assertEqual(pending['decisions'][0]['text'], "Architecture: MCP is adapter only")

        # Step 3: Commit (simulating dashboard commit button)
        commit = create_commit(
            self.test_project_id,
            message="Architecture decision",
            actor="dashboard",
        )

        self.assertIsNotNone(commit)
        self.assertEqual(commit['id'], "fo_commit_001")
        self.assertIn(dec_id, commit['changes']['decisions'])

        # Step 4: Verify pending is cleared
        pending_after = get_pending_objects(self.test_project_id)
        self.assertEqual(len(pending_after['decisions']), 0)

        # Step 5: Verify commit is persisted
        loaded_commit = get_commit(self.test_project_id, "fo_commit_001")
        self.assertEqual(loaded_commit['message'], "Architecture decision")


if __name__ == "__main__":
    unittest.main()
