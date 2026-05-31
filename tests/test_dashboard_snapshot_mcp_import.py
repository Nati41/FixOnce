import builtins
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import server as server_module
import api.status as status_module
import core.mcp_session_health as session_health


class TestDashboardSnapshotMcpImport(unittest.TestCase):
    def test_dashboard_snapshot_reads_compliance_without_importing_mcp_server(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-compliance-") as temp_dir:
            user_data_dir = Path(temp_dir)
            (user_data_dir / "mcp_compliance.json").write_text(json.dumps({
                "session_active": True,
                "decisions_displayed": True,
                "goal_updated": False,
                "tool_calls_count": 2,
                "editor": "codex",
                "agent_context": {"tool_name": "fo_sync"},
                "last_agent_intervention": {"tool_name": "fo_sync"},
            }), encoding="utf-8")

            imported_mcp_server = []
            original_import = builtins.__import__

            def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "mcp_server.mcp_memory_server_v2":
                    imported_mcp_server.append(name)
                return original_import(name, globals, locals, fromlist, level)

            sys.modules.pop("mcp_server.mcp_memory_server_v2", None)
            client = server_module.flask_app.test_client()

            with patch.object(status_module, "USER_DATA_DIR", user_data_dir), \
                 patch.object(session_health, "STATE_FILE", user_data_dir / "mcp_session_health.json"), \
                 patch.object(session_health, "LOG_FILE", user_data_dir / "logs" / "mcp_session_health.jsonl"), \
                 patch.object(builtins, "__import__", side_effect=tracking_import):
                response = client.get("/api/dashboard_snapshot")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(imported_mcp_server, [])

            payload = response.get_json()
            snapshot = payload["snapshot"]
            self.assertEqual(snapshot["compliance"]["editor"], "codex")
            self.assertEqual(snapshot["agent_context"]["tool_name"], "fo_sync")
            self.assertTrue(snapshot["agent_audit_active"])

    def test_dashboard_snapshot_returns_mcp_session_status(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-mcp-session-api-") as temp_dir:
            user_data_dir = Path(temp_dir)
            state_file = user_data_dir / "mcp_session_health.json"
            state_file.write_text(json.dumps({
                "state": "session_lost",
                "consecutive_failures": 2,
                "last_error": "Transport closed",
                "last_actor": "unknown",
                "updated_at": "2026-05-31T10:00:00",
            }), encoding="utf-8")

            client = server_module.flask_app.test_client()
            with patch.object(status_module, "USER_DATA_DIR", user_data_dir), \
                 patch.object(session_health, "STATE_FILE", state_file), \
                 patch.object(session_health, "LOG_FILE", user_data_dir / "logs" / "mcp_session_health.jsonl"):
                response = client.get("/api/dashboard_snapshot")

            self.assertEqual(response.status_code, 200)
            snapshot = response.get_json()["snapshot"]
            self.assertEqual(snapshot["mcp_health"]["session"]["state"], "session_lost")
            self.assertIn("FixOnce is running", snapshot["mcp_health"]["session"]["message"])


if __name__ == "__main__":
    unittest.main()
