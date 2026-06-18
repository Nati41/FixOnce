"""
Tests for Knowledge V2 API endpoints.
"""

import json
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))


class TestKnowledgeAPI(unittest.TestCase):
    """Test /api/knowledge/* endpoints."""

    def setUp(self):
        """Set up Flask test client."""
        self.temp_dir = tempfile.mkdtemp()

        # Patch knowledge_objects to use temp directory
        def mock_get_v2_dir(project_id):
            return Path(self.temp_dir) / project_id

        self.v2_patcher = patch(
            "core.knowledge_objects._get_v2_dir",
            side_effect=mock_get_v2_dir
        )
        self.v2_patcher.start()

        # Import after patching
        from server import flask_app
        self.app = flask_app
        self.client = self.app.test_client()

    def tearDown(self):
        self.v2_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pending_accepts_project_id_param(self):
        """GET /api/knowledge/pending should accept project_id query param."""
        # Create some test data
        from core.knowledge_objects import create_object, _ensure_v2_structure

        project_id = "test_project_abc"
        _ensure_v2_structure(project_id)
        create_object(project_id, "decision", "Test decision", "Test reason")

        # Call API with project_id param
        response = self.client.get(
            f"/api/knowledge/pending?project_id={project_id}",
            headers={"X-Dashboard": "true"}
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["project_id"], project_id)
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["pending"]["decisions"]), 1)

    def test_pending_returns_no_project_when_missing(self):
        """GET /api/knowledge/pending should return no_project when no project_id and no active project."""
        with patch("managers.multi_project_manager.get_active_project", return_value=None):
            response = self.client.get(
                "/api/knowledge/pending",
                headers={"X-Dashboard": "true"}
            )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data["status"], "no_project")

    def test_stats_accepts_project_id_param(self):
        """GET /api/knowledge/stats should accept project_id query param."""
        from core.knowledge_objects import create_object, _ensure_v2_structure

        project_id = "stats_test_project"
        _ensure_v2_structure(project_id)
        create_object(project_id, "decision", "D1", "R1")
        create_object(project_id, "bug", "B1", "S1")

        response = self.client.get(
            f"/api/knowledge/stats?project_id={project_id}",
            headers={"X-Dashboard": "true"}
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["project_id"], project_id)
        self.assertEqual(data["total_objects"], 2)
        self.assertEqual(data["pending_count"], 2)


if __name__ == "__main__":
    unittest.main()
