import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import api.activity as activity
import core.ai_detector as ai_detector
import core.unreported_work as unreported_work
import server as server_module


class TestUnreportedWork(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-unreported-work-")
        self.state_file = Path(self.temp_dir.name) / "unreported_work.json"
        self.state_patch = patch.object(unreported_work, "STATE_FILE", self.state_file)
        self.state_patch.start()
        ai_detector._cache = {"result": None, "timestamp": None}

    def tearDown(self):
        self.state_patch.stop()
        self.temp_dir.cleanup()

    def test_file_write_creates_dirty_state(self):
        unreported_work.mark_work(
            "project-1",
            "claude",
            "file_write",
            file_path="/tmp/project/app.py",
            source="PostToolUse",
        )

        state = unreported_work.get_state("project-1", "claude")
        self.assertTrue(state["dirty"])
        self.assertEqual(state["last_work_kind"], "file_write")
        self.assertEqual(state["files"], ["/tmp/project/app.py"])

    def test_fo_sync_clears_dirty_state(self):
        unreported_work.mark_work("project-1", "codex", "file_write")
        unreported_work.mark_synced("project-1", "codex", "fo_sync")

        state = unreported_work.get_state("project-1", "codex")
        self.assertFalse(state["dirty"])
        self.assertEqual(state["last_sync_tool"], "fo_sync")
        self.assertEqual(state["last_sync_seq"], state["last_work_seq"])

    def test_fo_init_does_not_clear_dirty_state(self):
        unreported_work.mark_work("project-1", "codex", "file_write")
        result = unreported_work.mark_synced("project-1", "codex", "fo_init")

        self.assertIsNone(result)
        self.assertTrue(unreported_work.get_state("project-1", "codex")["dirty"])

    def test_idle_without_work_does_not_become_not_protected(self):
        tool_config = {
            "display_name": "Codex",
            "process_patterns": {"darwin": ["codex"]},
            "install_checks": {"darwin": ["which codex"]},
        }
        with patch.object(ai_detector, "AI_TOOLS", {"codex": tool_config}), \
             patch.object(ai_detector, "_get_platform", return_value="darwin"), \
             patch.object(ai_detector, "_check_installed", return_value=True), \
             patch.object(ai_detector, "_check_process_running", return_value=True), \
             patch.object(ai_detector, "_get_connection_status", return_value={
                 "connected": False,
                 "known_connection": False,
                 "last_seen": None,
                 "age_seconds": None,
                 "project_id": "project-1",
             }):
            result = ai_detector.detect_ai_tools()

        self.assertEqual(result["tools"][0]["status"], "no_activity")
        self.assertFalse(result["has_unprotected"])

    def test_git_commit_creates_dirty_state(self):
        activity._track_unreported_work({
            "type": "command",
            "tool": "Bash",
            "command": "git commit -m 'ship it'",
            "cwd": "/tmp/project",
            "source": "PostToolUse",
        }, "project-1", "codex")

        state = unreported_work.get_state("project-1", "codex")
        self.assertTrue(state["dirty"])
        self.assertEqual(state["last_work_kind"], "git_commit")

    def test_hook_event_and_dashboard_detection_use_canonical_project_id(self):
        project_root = Path(self.temp_dir.name) / "project"
        metadata_dir = project_root / ".fixonce"
        metadata_dir.mkdir(parents=True)
        canonical_project_id = "project-canonical-123"
        (metadata_dir / "metadata.json").write_text(json.dumps({
            "project_id": canonical_project_id,
            "name": "project",
        }), encoding="utf-8")

        client = server_module.flask_app.test_client()
        with patch.object(activity, "ACTIVITY_FILE", Path(self.temp_dir.name) / "activity.json"), \
             patch.object(activity, "BOUNDARY_DETECTION_ENABLED", False), \
             patch.object(activity, "SESSION_REGISTRY_ENABLED", False), \
             patch.object(ai_detector, "AI_TOOLS", {
                 "codex": {
                     "display_name": "Codex",
                     "process_patterns": {"darwin": ["codex"]},
                     "install_checks": {"darwin": ["which codex"]},
                 }
             }), \
             patch.object(ai_detector, "_get_platform", return_value="darwin"), \
             patch.object(ai_detector, "_check_installed", return_value=True), \
             patch.object(ai_detector, "_check_process_running", return_value=True), \
             patch.object(ai_detector, "_get_connection_status", return_value={
                 "connected": True,
                 "known_connection": True,
                 "last_seen": None,
                 "age_seconds": 0,
                 "project_id": canonical_project_id,
             }):
            response = client.post("/api/activity/log", json={
                "type": "file_change",
                "tool": "apply_patch",
                "file": "",
                "cwd": str(project_root),
                "editor": "codex",
                "source": "PostToolUse",
            })
            detection = ai_detector.detect_ai_tools()

        self.assertEqual(response.status_code, 200)
        event = response.get_json()["activity"]
        self.assertEqual(event["project_id"], canonical_project_id)
        self.assertEqual(detection["tools"][0]["work_state"]["project_id"], canonical_project_id)
        self.assertEqual(detection["tools"][0]["status"], "unsynced")

    def test_file_change_endpoint_creates_unreported_work_file(self):
        project_root = Path(self.temp_dir.name) / "project"
        metadata_dir = project_root / ".fixonce"
        metadata_dir.mkdir(parents=True)
        (metadata_dir / "metadata.json").write_text(json.dumps({
            "project_id": "project-canonical-456",
            "name": "project",
        }), encoding="utf-8")

        client = server_module.flask_app.test_client()
        with patch.object(activity, "ACTIVITY_FILE", Path(self.temp_dir.name) / "activity.json"), \
             patch.object(activity, "BOUNDARY_DETECTION_ENABLED", False), \
             patch.object(activity, "SESSION_REGISTRY_ENABLED", False):
            response = client.post("/api/activity/log", json={
                "type": "file_change",
                "tool": "Write",
                "file": str(project_root / "app.py"),
                "cwd": str(project_root),
                "editor": "codex",
                "source": "PostToolUse",
            })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.state_file.exists())
        payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        state = payload["entries"]["project-canonical-456:codex"]
        self.assertTrue(state["dirty"])
        self.assertEqual(state["last_work_kind"], "file_write")


if __name__ == "__main__":
    unittest.main()
