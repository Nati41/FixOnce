"""
Tests for Knowledge Objects V2 module.

Tests:
1. Object creation creates immutable file
2. Sequential IDs are generated correctly
3. Pending changes are tracked
4. Objects are never modified
5. Index is maintained
"""

import json
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

# Add src to path
TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from core.knowledge_objects import (
    create_object,
    load_object,
    get_pending_changes,
    get_pending_objects,
    clear_pending,
    get_object_count,
    _ensure_v2_structure,
    _get_v2_dir,
)


class TestKnowledgeObjects(unittest.TestCase):
    """Test immutable knowledge objects."""

    def setUp(self):
        """Create temp directory for test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_project_id = "test_project_123"

        # Patch _get_v2_dir to use temp directory
        self.original_get_v2_dir = _get_v2_dir.__code__

        def mock_get_v2_dir(project_id):
            return Path(self.temp_dir) / project_id

        self.patcher = patch(
            "core.knowledge_objects._get_v2_dir",
            side_effect=mock_get_v2_dir
        )
        self.patcher.start()

    def tearDown(self):
        """Clean up temp directory."""
        self.patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ensure_v2_structure_creates_directories(self):
        """V2 structure should create objects/, pending/, and index.json."""
        _ensure_v2_structure(self.test_project_id)

        v2_dir = Path(self.temp_dir) / self.test_project_id
        self.assertTrue((v2_dir / "objects").is_dir())
        self.assertTrue((v2_dir / "pending").is_dir())
        self.assertTrue((v2_dir / "index.json").is_file())
        self.assertTrue((v2_dir / "pending" / "pending_changes.json").is_file())

    def test_create_object_generates_sequential_id(self):
        """Objects should get sequential IDs: dec_001, dec_002, etc."""
        obj1 = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="First decision",
            reason="Test reason",
            actor="test_user",
        )
        self.assertEqual(obj1.id, "dec_001")

        obj2 = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Second decision",
            reason="Test reason",
            actor="test_user",
        )
        self.assertEqual(obj2.id, "dec_002")

    def test_create_object_different_types(self):
        """Different object types should have different ID prefixes."""
        dec = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Decision",
            reason="Reason",
        )
        self.assertTrue(dec.id.startswith("dec_"))

        bug = create_object(
            project_id=self.test_project_id,
            obj_type="bug",
            text="Bug",
            reason="Solution",
        )
        self.assertTrue(bug.id.startswith("bug_"))

        avoid = create_object(
            project_id=self.test_project_id,
            obj_type="avoid",
            text="Avoid",
            reason="Why",
        )
        self.assertTrue(avoid.id.startswith("avoid_"))

        question = create_object(
            project_id=self.test_project_id,
            obj_type="question",
            text="Question",
            reason="Context",
        )
        self.assertTrue(question.id.startswith("q_"))

    def test_create_object_saves_file(self):
        """Created object should be saved as JSON file."""
        obj = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Test decision",
            reason="Test reason",
            actor="claude",
        )

        obj_path = Path(self.temp_dir) / self.test_project_id / "objects" / f"{obj.id}.json"
        self.assertTrue(obj_path.exists())

        with open(obj_path) as f:
            saved = json.load(f)

        self.assertEqual(saved["id"], obj.id)
        self.assertEqual(saved["type"], "decision")
        self.assertEqual(saved["text"], "Test decision")
        self.assertEqual(saved["reason"], "Test reason")
        self.assertEqual(saved["actor"], "claude")

    def test_load_object_returns_data(self):
        """load_object should return the saved object data."""
        obj = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Test decision",
            reason="Test reason",
        )

        loaded = load_object(self.test_project_id, obj.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["id"], obj.id)
        self.assertEqual(loaded["text"], "Test decision")

    def test_load_object_nonexistent_returns_none(self):
        """load_object should return None for nonexistent objects."""
        _ensure_v2_structure(self.test_project_id)
        loaded = load_object(self.test_project_id, "dec_999")
        self.assertIsNone(loaded)

    def test_create_object_adds_to_pending(self):
        """Created objects should be added to pending changes."""
        _ensure_v2_structure(self.test_project_id)

        # Initially empty
        pending = get_pending_changes(self.test_project_id)
        self.assertEqual(len(pending["decisions"]), 0)

        # Create object
        obj = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Pending decision",
            reason="Reason",
        )

        # Should be in pending
        pending = get_pending_changes(self.test_project_id)
        self.assertIn(obj.id, pending["decisions"])

    def test_get_pending_objects_returns_full_data(self):
        """get_pending_objects should return full object data."""
        obj = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Full data decision",
            reason="Full reason",
        )

        pending = get_pending_objects(self.test_project_id)
        self.assertEqual(len(pending["decisions"]), 1)
        self.assertEqual(pending["decisions"][0]["text"], "Full data decision")

    def test_clear_pending_removes_ids_but_keeps_objects(self):
        """clear_pending should remove IDs from pending but NOT delete objects."""
        obj = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="To be cleared",
            reason="Reason",
        )

        # Verify in pending
        pending = get_pending_changes(self.test_project_id)
        self.assertIn(obj.id, pending["decisions"])

        # Clear pending
        clear_pending(self.test_project_id)

        # Pending should be empty
        pending = get_pending_changes(self.test_project_id)
        self.assertEqual(len(pending["decisions"]), 0)

        # But object should still exist (immutable!)
        loaded = load_object(self.test_project_id, obj.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["text"], "To be cleared")

    def test_get_object_count(self):
        """get_object_count should return counts by type."""
        create_object(self.test_project_id, "decision", "D1", "R1")
        create_object(self.test_project_id, "decision", "D2", "R2")
        create_object(self.test_project_id, "bug", "B1", "S1")

        counts = get_object_count(self.test_project_id)
        self.assertEqual(counts.get("decision"), 2)
        self.assertEqual(counts.get("bug"), 1)
        self.assertEqual(counts.get("avoid"), 0)

    def test_object_has_created_at_timestamp(self):
        """Objects should have a created_at timestamp."""
        obj = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Timestamped",
            reason="Reason",
        )

        self.assertIsNotNone(obj.created_at)
        self.assertIn("T", obj.created_at)  # ISO format

    def test_object_links_are_preserved(self):
        """Object links should be saved correctly."""
        obj = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Linked decision",
            reason="Reason",
            links={"supersedes": "dec_001", "related_to": ["bug_002"]},
        )

        loaded = load_object(self.test_project_id, obj.id)
        self.assertEqual(loaded["links"]["supersedes"], "dec_001")
        self.assertEqual(loaded["links"]["related_to"], ["bug_002"])


class TestKnowledgeObjectsImmutability(unittest.TestCase):
    """Test that objects are truly immutable."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_project_id = "immutable_test"

        def mock_get_v2_dir(project_id):
            return Path(self.temp_dir) / project_id

        self.patcher = patch(
            "core.knowledge_objects._get_v2_dir",
            side_effect=mock_get_v2_dir
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_object_file_not_modified_by_second_create(self):
        """Creating another object should not modify existing objects."""
        obj1 = create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Original",
            reason="Reason",
        )

        # Get file modification time
        obj1_path = Path(self.temp_dir) / self.test_project_id / "objects" / f"{obj1.id}.json"
        mtime1 = obj1_path.stat().st_mtime

        # Create another object
        create_object(
            project_id=self.test_project_id,
            obj_type="decision",
            text="Another",
            reason="Reason",
        )

        # First object should not be modified
        mtime2 = obj1_path.stat().st_mtime
        self.assertEqual(mtime1, mtime2)

        # Content should be unchanged
        loaded = load_object(self.test_project_id, obj1.id)
        self.assertEqual(loaded["text"], "Original")


if __name__ == "__main__":
    unittest.main()
