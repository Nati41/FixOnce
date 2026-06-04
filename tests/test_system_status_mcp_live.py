import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.modules.setdefault("requests", types.SimpleNamespace(RequestException=Exception))


import core.system_status as system_status
from core.system_status import AIClientStatus, MCPStatus, SystemStatus


class TestSystemStatusMcpLive(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-system-status-mcp-")
        self.temp_home = Path(self.temp_dir.name)
        self.temp_data_dir = self.temp_home / ".fixonce"
        self.temp_data_dir.mkdir(parents=True, exist_ok=True)
        self.home_patch = patch("pathlib.Path.home", return_value=self.temp_home)
        self.data_patch = patch.object(system_status, "_get_data_dir", return_value=self.temp_data_dir)
        self.home_patch.start()
        self.data_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        self.data_patch.stop()
        self.temp_dir.cleanup()

    def _write_codex_rules(self):
        path = self.temp_home / ".codex" / "AGENTS.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "<!-- FIXONCE-AUTO-INIT:START -->\nrule\n<!-- FIXONCE-AUTO-INIT:END -->",
            encoding="utf-8",
        )

    def test_check_mcp_uses_live_session_over_stale_runtime(self):
        codex_config = self.temp_home / ".codex" / "config.toml"
        codex_config.parent.mkdir(parents=True, exist_ok=True)
        codex_config.write_text("[mcp_servers.fixonce]\ncommand = \"FixOnce.exe\"\n", encoding="utf-8")

        stale_runtime = {
            "codex": {
                "last_seen": "2026-06-02T17:46:51.653807",
                "actor_source": "client_actor",
                "actor_confidence": 1.0,
            }
        }
        live_session = {
            "actor": "codex",
            "last_seen": datetime.now().isoformat(),
            "actor_source": "client_actor",
            "actor_confidence": 1.0,
        }

        with patch.object(system_status, "_load_runtime_ai_status", return_value=stale_runtime), \
             patch.object(system_status, "_load_live_mcp_session_status", return_value=live_session), \
             patch.object(system_status, "_detect_installed_clients", return_value={"codex": True}):
            status = system_status._check_mcp()

        self.assertTrue(status.clients["codex"].configured)
        self.assertTrue(status.clients["codex"].connected)
        self.assertEqual(status.clients["codex"].last_seen, live_session["last_seen"])

    def test_codex_registered_but_disconnected_shows_restart_guidance(self):
        self._write_codex_rules()
        status = SystemStatus(
            mcp=MCPStatus(
                clients={
                    "codex": AIClientStatus(name="Codex", installed=True, configured=True, connected=False),
                }
            ),
            is_first_launch=False,
        )

        payload = system_status.build_client_onboarding_payload(status, "en")
        codex = next(item for item in payload["clients"] if item["client"] == "codex")

        self.assertEqual(codex["status"], "needs_restart")
        self.assertTrue(codex["needs_restart"])
        self.assertEqual(codex["reason"], "Restart Codex Desktop to establish a new MCP session.")


if __name__ == "__main__":
    unittest.main()
