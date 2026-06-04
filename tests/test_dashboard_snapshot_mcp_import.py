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
import core.mcp_health as mcp_health
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
            self.assertEqual(snapshot["active_ai"], "codex")
            self.assertEqual(snapshot["active_ais"][0]["editor"], "codex")

    def test_dashboard_snapshot_uses_mcp_session_actor_when_active_ai_missing(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-mcp-session-actor-") as temp_dir:
            user_data_dir = Path(temp_dir)
            state_file = user_data_dir / "mcp_session_health.json"
            state_file.write_text(json.dumps({
                "state": "connected",
                "consecutive_failures": 0,
                "last_error": None,
                "last_actor": "codex",
                "last_actor_source": "client_actor",
                "updated_at": "2026-05-31T10:00:00",
            }), encoding="utf-8")

            client = server_module.flask_app.test_client()
            with patch.object(status_module, "USER_DATA_DIR", user_data_dir), \
                 patch.object(status_module, "_detect_running_editors", return_value=[]), \
                 patch.object(session_health, "STATE_FILE", state_file), \
                 patch.object(session_health, "LOG_FILE", user_data_dir / "logs" / "mcp_session_health.jsonl"):
                response = client.get("/api/dashboard_snapshot")

            self.assertEqual(response.status_code, 200)
            snapshot = response.get_json()["snapshot"]
            self.assertEqual(snapshot["active_ai"], "codex")
            self.assertEqual(snapshot["active_ais"][0]["editor"], "codex")
            self.assertEqual(snapshot["system_status"]["ai"]["name"], "codex")

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

    def test_dashboard_snapshot_uses_last_intervention_as_agent_context(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-agent-context-") as temp_dir:
            user_data_dir = Path(temp_dir)
            (user_data_dir / "mcp_compliance.json").write_text(json.dumps({
                "session_active": True,
                "project_id": "FixOnce_34592c5b",
                "agent_context": {},
                "last_agent_intervention": {
                    "tool_name": "fo_init",
                    "actor_name": "codex",
                    "actor_source": "client_actor",
                    "actor_confidence": 1.0,
                    "project_id": "FixOnce_34592c5b",
                    "session_id": "abc123",
                },
            }), encoding="utf-8")

            client = server_module.flask_app.test_client()
            with patch.object(status_module, "USER_DATA_DIR", user_data_dir), \
                 patch.object(session_health, "STATE_FILE", user_data_dir / "mcp_session_health.json"), \
                 patch.object(session_health, "LOG_FILE", user_data_dir / "logs" / "mcp_session_health.jsonl"):
                response = client.get("/api/dashboard_snapshot")

            self.assertEqual(response.status_code, 200)
            snapshot = response.get_json()["snapshot"]
            self.assertEqual(snapshot["agent_context"]["actor_name"], "codex")
            self.assertEqual(snapshot["agent_context"]["tool_name"], "fo_init")

    def test_recent_session_success_marks_mcp_health_active(self):
        with patch.object(mcp_health, "check_mcp_health", return_value=mcp_health.MCPHealthResult(
            state="configured",
            reason="MCP configured but inactive",
            last_tool_call="2026-06-02T19:20:27",
            config_path="C:\\Users\\nati3\\.codex\\config.toml",
        )), patch.object(session_health, "get_session_health", return_value={
            "state": "connected",
            "last_success_at": "2026-06-03T13:17:04",
            "last_actor": "codex",
            "last_actor_source": "client_actor",
        }), patch.object(mcp_health, "datetime") as fake_datetime:
            from datetime import datetime
            fake_datetime.now.return_value = datetime(2026, 6, 3, 13, 17, 14)
            fake_datetime.fromisoformat.side_effect = datetime.fromisoformat

            health = mcp_health.get_mcp_health_for_dashboard()

            self.assertEqual(health["state"], "active")
            self.assertEqual(health["status"], "active")
            self.assertEqual(health["session"]["last_actor"], "codex")


if __name__ == "__main__":
    unittest.main()
