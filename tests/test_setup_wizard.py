import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import server as server_module
import api.setup as setup_api
import core.system_status as system_status
from core.system_status import AIClientStatus, MCPStatus, SystemStatus


class TestSetupWizard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-setup-wizard-")
        self.temp_home = Path(self.temp_dir.name)
        self.temp_data_dir = self.temp_home / ".fixonce"
        self.temp_data_dir.mkdir(parents=True, exist_ok=True)
        self.client = server_module.flask_app.test_client()
        self.home_patch = patch("pathlib.Path.home", return_value=self.temp_home)
        self.data_patch = patch.object(system_status, "_get_data_dir", return_value=self.temp_data_dir)
        self.home_patch.start()
        self.data_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        self.data_patch.stop()
        self.temp_dir.cleanup()

    def _write_rules(self, client: str):
        if client == "claude":
            path = self.temp_home / ".claude" / "CLAUDE.md"
        elif client == "cursor":
            path = self.temp_home / "Library" / "Application Support" / "Cursor" / "User" / "settings.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"cursor.general.aiRules": "Call fo_init"}), encoding="utf-8")
            return
        elif client == "codex":
            path = self.temp_home / ".codex" / "AGENTS.md"
        else:
            path = self.temp_home / ".codeium" / "windsurf" / "memories" / "global_rules.md"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<!-- FIXONCE-AUTO-INIT:START -->\nrule\n<!-- FIXONCE-AUTO-INIT:END -->", encoding="utf-8")

    def test_build_client_onboarding_payload_maps_product_states(self):
        for client in ("claude", "cursor", "codex", "windsurf"):
            self._write_rules(client)

        status = SystemStatus(
            mcp=MCPStatus(
                clients={
                    "claude": AIClientStatus(name="Claude", installed=True, configured=True, connected=True),
                    "cursor": AIClientStatus(name="Cursor", installed=True, configured=True, connected=False),
                    "codex": AIClientStatus(name="Codex", installed=False, configured=False, connected=False),
                    "windsurf": AIClientStatus(name="Windsurf", installed=True, configured=False, connected=False),
                }
            )
        )

        payload = system_status.build_client_onboarding_payload(status, "en")
        states = {item["client"]: item for item in payload["clients"]}

        self.assertEqual(states["claude"]["status"], "connected")
        self.assertEqual(states["cursor"]["status"], "needs_restart")
        self.assertEqual(states["codex"]["status"], "not_installed")
        self.assertEqual(states["windsurf"]["status"], "failed")
        self.assertTrue(states["windsurf"]["retry_available"])
        self.assertFalse(states["codex"]["retry_available"])
        self.assertEqual(payload["flow_state"], "connected")
        self.assertEqual(payload["primary_client"], "claude")
        self.assertTrue(payload["onboarding_completed"])
        self.assertFalse(payload["should_show_onboarding"])

    def test_connected_onboarding_persists_completed_hidden_state(self):
        self._write_rules("codex")

        connected = SystemStatus(
            mcp=MCPStatus(
                clients={
                    "codex": AIClientStatus(name="Codex", installed=True, configured=True, connected=True),
                }
            ),
            is_first_launch=False,
        )
        first_payload = system_status.build_client_onboarding_payload(connected, "en")
        self.assertEqual(first_payload["flow_state"], "connected")
        self.assertEqual(first_payload["primary_client"], "codex")
        self.assertTrue(first_payload["onboarding_completed"])

        disconnected = SystemStatus(
            mcp=MCPStatus(
                clients={
                    "codex": AIClientStatus(name="Codex", installed=True, configured=True, connected=False),
                }
            ),
            is_first_launch=False,
        )
        second_payload = system_status.build_client_onboarding_payload(disconnected, "en")
        self.assertEqual(second_payload["flow_state"], "completed_hidden")
        self.assertFalse(second_payload["should_show_onboarding"])
        self.assertEqual(second_payload["primary_client"], "codex")

    def test_first_launch_without_supported_clients_requires_temporary_onboarding(self):
        status = SystemStatus(
            mcp=MCPStatus(clients={}),
            is_first_launch=True,
        )

        payload = system_status.build_client_onboarding_payload(status, "en")
        self.assertEqual(payload["flow_state"], "fresh_install")
        self.assertFalse(payload["onboarding_completed"])
        self.assertTrue(payload["should_show_onboarding"])

    def test_retry_ai_endpoint_retries_single_client(self):
        fake_install = SimpleNamespace(
            get_fixonce_dir=lambda: PROJECT_ROOT,
            detect_editors=lambda: {"claude_code": True, "cursor": True, "codex": True, "windsurf": True},
            build_install_stdio_config=lambda fixonce_dir=None: {"command": "python", "args": ["server.py"]},
            configure_client_mcp=lambda client, stdio_config=None, editors=None: client == "cursor",
            sync_client_rules=lambda client, fixonce_dir=None: client == "cursor",
        )

        refreshed = {
            "flow_state": "needs_restart",
            "primary_client": "cursor",
            "onboarding_completed": False,
            "should_show_onboarding": True,
            "clients": [
                {
                    "client": "cursor",
                    "status": "needs_restart",
                    "reason": "Close and reopen this app to finish connecting it.",
                    "retry_available": False,
                    "installed": True,
                    "needs_restart": True,
                }
            ]
        }

        with patch.object(setup_api, "_load_install_module", return_value=fake_install), \
             patch.object(system_status, "get_client_onboarding_status", return_value=refreshed):
            response = self.client.post("/api/setup/retry-ai/cursor", headers={"Accept-Language": "en"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["client"]["client"], "cursor")
        self.assertEqual(payload["client"]["status"], "needs_restart")

    def test_repair_mcp_endpoint_avoids_external_editor_probes(self):
        calls = {
            "build_probe_fastmcp": None,
            "editors": [],
            "configured": [],
            "rules": [],
        }

        def detect_editors():
            raise AssertionError("repair-mcp should not run editor discovery probes")

        def build_install_stdio_config(fixonce_dir=None, probe_fastmcp=True):
            calls["build_probe_fastmcp"] = probe_fastmcp
            return {"command": "python", "args": ["server.py"]}

        def configure_client_mcp(client, stdio_config=None, editors=None):
            calls["configured"].append(client)
            calls["editors"].append(editors)
            return True

        def sync_client_rules(client, fixonce_dir=None):
            calls["rules"].append(client)
            return True

        fake_install = SimpleNamespace(
            get_fixonce_dir=lambda: PROJECT_ROOT,
            detect_editors=detect_editors,
            build_install_stdio_config=build_install_stdio_config,
            configure_client_mcp=configure_client_mcp,
            sync_client_rules=sync_client_rules,
        )

        with patch.object(setup_api, "_load_install_module", return_value=fake_install), \
             patch("core.mcp_health.get_mcp_health_for_dashboard", return_value={"state": "configured", "session": {"state": "unknown"}}), \
             patch("core.mcp_session_health.mark_recovery_attempt"), \
             patch("core.mcp_session_health.record_mcp_success"):
            response = self.client.post("/api/setup/repair-mcp", headers={"Accept-Language": "en"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertFalse(calls["build_probe_fastmcp"])
        self.assertEqual(calls["configured"], ["claude", "cursor", "codex", "windsurf"])
        self.assertEqual(calls["rules"], ["claude", "cursor", "codex", "windsurf"])
        for editors in calls["editors"]:
            self.assertEqual(editors["claude_code"], False)
            self.assertEqual(editors["cursor"], False)
            self.assertEqual(editors["codex"], False)
            self.assertEqual(editors["windsurf"], False)


if __name__ == "__main__":
    unittest.main()
