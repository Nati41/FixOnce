import tempfile
import unittest
from pathlib import Path

from src.core.agent_mcp_registration import (
    WINDOWS_MCP_CLIENT_ADAPTERS,
    register_codex_mcp,
    register_windows_mcp_clients,
)


class TestAgentMcpRegistration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-agent-mcp-")
        self.home = Path(self.temp_dir.name) / "home"
        self.fixonce_exe = Path(r"C:\Program Files\FixOnce\FixOnce.exe")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _codex_config_text(self) -> str:
        return (self.home / ".codex" / "config.toml").read_text(encoding="utf-8")

    def test_codex_missing_config_creates_section(self):
        path = register_codex_mcp(self.home, self.fixonce_exe)

        self.assertEqual(path, self.home / ".codex" / "config.toml")
        text = self._codex_config_text()
        self.assertIn("[mcp_servers.fixonce]", text)
        self.assertIn('command = "C:\\\\Program Files\\\\FixOnce\\\\FixOnce.exe"', text)
        self.assertIn('args = ["--mcp"]', text)
        self.assertIn("startup_timeout_sec = 60", text)

    def test_codex_existing_config_is_preserved(self):
        config_path = self.home / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text('[profiles.default]\nmodel = "gpt-5"\n', encoding="utf-8")

        register_codex_mcp(self.home, self.fixonce_exe)

        text = self._codex_config_text()
        self.assertIn('[profiles.default]\nmodel = "gpt-5"', text)
        self.assertIn("[mcp_servers.fixonce]", text)

    def test_codex_existing_fixonce_section_is_updated(self):
        config_path = self.home / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "\n".join(
                [
                    "[mcp_servers.fixonce]",
                    'command = "python"',
                    'args = ["old.py"]',
                    "",
                    "[mcp_servers.fixonce.env]",
                    'PYTHONPATH = "C:\\\\repo\\\\src"',
                    "",
                    "[profiles.default]",
                    'model = "gpt-5"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        register_codex_mcp(self.home, self.fixonce_exe)

        text = self._codex_config_text()
        self.assertEqual(text.count("[mcp_servers.fixonce]"), 1)
        self.assertNotIn('command = "python"', text)
        self.assertNotIn("PYTHONPATH", text)
        self.assertIn('command = "C:\\\\Program Files\\\\FixOnce\\\\FixOnce.exe"', text)
        self.assertIn('args = ["--mcp"]', text)
        self.assertNotIn("[mcp_servers.fixonce.env]", text)
        self.assertIn('[profiles.default]\nmodel = "gpt-5"', text)

    def test_codex_packaged_repair_removes_legacy_env_and_script_args(self):
        config_path = self.home / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "\n".join(
                [
                    "[mcp_servers.fixonce]",
                    'command = "C:\\\\Program Files\\\\FixOnce\\\\FixOnce.exe"',
                    'args = ["C:\\\\Program Files\\\\FixOnce\\\\src\\\\mcp_server\\\\mcp_memory_server_v2.py"]',
                    "",
                    "[mcp_servers.fixonce.env]",
                    'PYTHONPATH = "C:\\\\Program Files\\\\FixOnce\\\\src"',
                    'FIXONCE_ACTOR = "codex"',
                    "",
                    "[profiles.default]",
                    'model = "gpt-5"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        register_codex_mcp(self.home, self.fixonce_exe)

        text = self._codex_config_text()
        self.assertEqual(text.count("[mcp_servers.fixonce]"), 1)
        self.assertIn('command = "C:\\\\Program Files\\\\FixOnce\\\\FixOnce.exe"', text)
        self.assertIn('args = ["--mcp"]', text)
        self.assertIn("startup_timeout_sec = 60", text)
        self.assertNotIn("[mcp_servers.fixonce.env]", text)
        self.assertNotIn("PYTHONPATH", text)
        self.assertNotIn("FIXONCE_ACTOR", text)
        self.assertNotIn("mcp_memory_server_v2.py", text)
        self.assertIn('[profiles.default]\nmodel = "gpt-5"', text)

    def test_windows_registration_uses_agent_adapter_layer(self):
        self.assertIn(register_codex_mcp, WINDOWS_MCP_CLIENT_ADAPTERS)

        paths = register_windows_mcp_clients(self.home, self.fixonce_exe)

        self.assertEqual(paths, [self.home / ".codex" / "config.toml"])
        text = self._codex_config_text()
        self.assertIn("[mcp_servers.fixonce]", text)
        self.assertNotIn("PYTHONPATH", text)


if __name__ == "__main__":
    unittest.main()
