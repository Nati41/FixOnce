import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from src.core.agent_mcp_registration import (
    WINDOWS_MCP_CLIENT_ADAPTERS,
    build_packaged_stdio_config,
    register_claude_mcp,
    register_codex_mcp,
    register_cursor_mcp,
    register_windsurf_mcp,
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

    def _json_config(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _assert_json_client_config(self, path: Path, actor: str):
        config = self._json_config(path)
        server = config["mcpServers"]["fixonce"]
        self.assertEqual(server["command"], str(self.fixonce_exe))
        self.assertEqual(server["args"], ["--mcp"])
        self.assertEqual(server["env"], {"FIXONCE_ACTOR": actor})
        self.assertNotIn("PYTHONPATH", json.dumps(server))

    def test_codex_missing_config_creates_section(self):
        path = register_codex_mcp(self.home, self.fixonce_exe)

        self.assertEqual(path, self.home / ".codex" / "config.toml")
        text = self._codex_config_text()
        self.assertIn("[mcp_servers.fixonce]", text)
        self.assertIn('command = "C:\\\\Program Files\\\\FixOnce\\\\FixOnce.exe"', text)
        self.assertIn('args = ["--mcp"]', text)
        self.assertIn("startup_timeout_sec = 60", text)
        self.assertIn("[mcp_servers.fixonce.env]", text)
        self.assertIn('FIXONCE_ACTOR = "codex"', text)

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
        self.assertIn("startup_timeout_sec = 60", text)
        self.assertIn("[mcp_servers.fixonce.env]", text)
        self.assertIn('FIXONCE_ACTOR = "codex"', text)
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
        self.assertIn("[mcp_servers.fixonce.env]", text)
        self.assertNotIn("PYTHONPATH", text)
        self.assertIn('FIXONCE_ACTOR = "codex"', text)
        self.assertNotIn("mcp_memory_server_v2.py", text)
        self.assertIn('[profiles.default]\nmodel = "gpt-5"', text)

    def test_codex_real_qa_config_shape_remains_valid_toml(self):
        config_path = self.home / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "\n".join(
                [
                    "[projects.'c:\\users\\testuser']",
                    'trust_level = "trusted"',
                    "",
                    "[projects.'c:\\testproject']",
                    'trust_level = "trusted"',
                    "",
                    "[tui.model_availability_nux]",
                    '"gpt-5.5" = 4',
                    "",
                    "[windows]",
                    'sandbox = "elevated"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        register_codex_mcp(self.home, self.fixonce_exe)

        text = self._codex_config_text()
        self.assertIn("[projects.'c:\\users\\testuser']\ntrust_level = \"trusted\"", text)
        self.assertIn("[projects.'c:\\testproject']\ntrust_level = \"trusted\"", text)
        self.assertIn('[tui.model_availability_nux]\n"gpt-5.5" = 4', text)
        self.assertIn('[windows]\nsandbox = "elevated"', text)
        self.assertEqual(text.count('trust_level = "trusted"'), 2)
        self.assertEqual(text.count('sandbox = "elevated"'), 1)
        self.assertIn("[mcp_servers.fixonce]", text)
        self.assertIn('command = "C:\\\\Program Files\\\\FixOnce\\\\FixOnce.exe"', text)
        self.assertIn('args = ["--mcp"]', text)
        self.assertIn("startup_timeout_sec = 60", text)

        parsed = tomllib.loads(text)
        self.assertEqual(parsed["projects"]["c:\\users\\testuser"]["trust_level"], "trusted")
        self.assertEqual(parsed["projects"]["c:\\testproject"]["trust_level"], "trusted")
        self.assertEqual(parsed["windows"]["sandbox"], "elevated")
        self.assertEqual(parsed["mcp_servers"]["fixonce"]["args"], ["--mcp"])
        self.assertEqual(parsed["mcp_servers"]["fixonce"]["startup_timeout_sec"], 60)

    def test_codex_packaged_repair_replaces_legacy_python_mcp_command(self):
        config_path = self.home / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "\n".join(
                [
                    "[mcp_servers.fixonce]",
                    'command = "C:\\\\Users\\\\nati3\\\\AppData\\\\Local\\\\Python\\\\pythoncore-3.14-64\\\\python.exe"',
                    'args = ["--mcp"]',
                    "startup_timeout_sec = 60",
                    "",
                    "[desktop]",
                    'conversationDetailMode = "STEPS_COMMANDS"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        register_codex_mcp(self.home, self.fixonce_exe)

        text = self._codex_config_text()
        self.assertEqual(text.count("[mcp_servers.fixonce]"), 1)
        self.assertNotIn("pythoncore-3.14-64", text)
        self.assertIn('command = "C:\\\\Program Files\\\\FixOnce\\\\FixOnce.exe"', text)
        self.assertIn('args = ["--mcp"]', text)
        self.assertIn("startup_timeout_sec = 60", text)
        self.assertIn('FIXONCE_ACTOR = "codex"', text)
        self.assertIn('[desktop]\nconversationDetailMode = "STEPS_COMMANDS"', text)

    def test_codex_packaged_repair_removes_duplicate_fixonce_blocks(self):
        config_path = self.home / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "\n".join(
                [
                    "[projects.'c:\\\\fixonce']",
                    'trust_level = "trusted"',
                    "",
                    "[mcp_servers.fixonce]",
                    'command = "python.exe"',
                    'args = ["--mcp"]',
                    "",
                    "[mcp_servers.fixonce.env]",
                    'PYTHONPATH = "C:\\\\old\\\\src"',
                    "",
                    "[mcp_servers.node_repl]",
                    "args = []",
                    'command = "node_repl.exe"',
                    "",
                    "[mcp_servers.fixonce]",
                    'command = "C:\\\\old\\\\FixOnce.exe"',
                    'args = ["C:\\\\old\\\\src\\\\mcp_server\\\\mcp_memory_server_v2.py"]',
                    "",
                    "[features]",
                    "js_repl = false",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        register_codex_mcp(self.home, self.fixonce_exe)

        text = self._codex_config_text()
        self.assertEqual(text.count("[mcp_servers.fixonce]"), 1)
        self.assertEqual(text.count("[mcp_servers.fixonce.env]"), 1)
        self.assertNotIn("C:\\\\old", text)
        self.assertNotIn("mcp_memory_server_v2.py", text)
        self.assertIn("[mcp_servers.node_repl]\nargs = []", text)
        self.assertIn("[features]\njs_repl = false", text)
        self.assertIn("[projects.'c:\\\\fixonce']\ntrust_level = \"trusted\"", text)

    def test_codex_packaged_repair_removes_malformed_windows_path_block(self):
        config_path = self.home / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            "\n".join(
                [
                    "[mcp_servers.fixonce]",
                    'command = "C:\\Users\\nati3\\AppData\\Local\\Programs\\FixOnce\\FixOnce.exe"',
                    'args = ["C:\\Users\\nati3\\AppData\\Local\\Programs\\FixOnce\\src\\mcp_server\\mcp_memory_server_v2.py"]',
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
        self.assertNotIn("C:\\Users\\nati3", text)
        self.assertNotIn("mcp_memory_server_v2.py", text)
        self.assertIn('command = "C:\\\\Program Files\\\\FixOnce\\\\FixOnce.exe"', text)
        self.assertIn("startup_timeout_sec = 60", text)
        self.assertIn('FIXONCE_ACTOR = "codex"', text)
        self.assertIn('[profiles.default]\nmodel = "gpt-5"', text)

    def test_packaged_config_rejects_python_interpreter(self):
        with self.assertRaisesRegex(ValueError, "requires FixOnce.exe"):
            build_packaged_stdio_config(Path(r"C:\Python314\python.exe"), "codex")

    def test_packaged_config_uses_mcp_companion_when_present(self):
        install_dir = Path(self.temp_dir.name) / "Program Files" / "FixOnce"
        install_dir.mkdir(parents=True)
        fixonce_exe = install_dir / "FixOnce.exe"
        mcp_exe = install_dir / "FixOnceMCP.exe"
        fixonce_exe.write_text("", encoding="utf-8")
        mcp_exe.write_text("", encoding="utf-8")

        config = build_packaged_stdio_config(fixonce_exe, "codex")

        self.assertEqual(config["command"], str(mcp_exe))
        self.assertEqual(config["args"], ["--mcp"])
        self.assertEqual(config["env"], {"FIXONCE_ACTOR": "codex"})

    def test_packaged_config_falls_back_to_app_exe_without_mcp_companion(self):
        install_dir = Path(self.temp_dir.name) / "Program Files" / "FixOnce"
        install_dir.mkdir(parents=True)
        fixonce_exe = install_dir / "FixOnce.exe"
        fixonce_exe.write_text("", encoding="utf-8")

        config = build_packaged_stdio_config(fixonce_exe, "codex")

        self.assertEqual(config["command"], str(fixonce_exe))
        self.assertEqual(config["args"], ["--mcp"])

    def test_json_client_missing_config_creates_section(self):
        cases = [
            (register_claude_mcp, self.home / ".claude.json", "claude"),
            (register_cursor_mcp, self.home / ".cursor" / "mcp.json", "cursor"),
            (register_windsurf_mcp, self.home / ".codeium" / "windsurf" / "mcp_config.json", "windsurf"),
        ]

        for register, path, actor in cases:
            with self.subTest(actor=actor):
                self.assertEqual(register(self.home, self.fixonce_exe), path)
                self._assert_json_client_config(path, actor)

    def test_json_client_existing_config_is_preserved(self):
        config_path = self.home / ".cursor" / "mcp.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps({"ui": {"theme": "dark"}, "mcpServers": {"other": {"command": "node"}}}),
            encoding="utf-8",
        )

        register_cursor_mcp(self.home, self.fixonce_exe)

        config = self._json_config(config_path)
        self.assertEqual(config["ui"], {"theme": "dark"})
        self.assertEqual(config["mcpServers"]["other"], {"command": "node"})
        self._assert_json_client_config(config_path, "cursor")

    def test_json_client_packaged_repair_removes_legacy_env_and_script_args(self):
        config_path = self.home / ".claude.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "fixonce": {
                            "command": str(self.fixonce_exe),
                            "args": [r"C:\Program Files\FixOnce\src\mcp_server\mcp_memory_server_v2.py"],
                            "env": {"PYTHONPATH": r"C:\Program Files\FixOnce\src"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        register_claude_mcp(self.home, self.fixonce_exe)

        self._assert_json_client_config(config_path, "claude")
        self.assertNotIn("mcp_memory_server_v2.py", config_path.read_text(encoding="utf-8"))

    def test_windows_registration_uses_agent_adapter_layer(self):
        self.assertIn(register_codex_mcp, WINDOWS_MCP_CLIENT_ADAPTERS)
        self.assertIn(register_claude_mcp, WINDOWS_MCP_CLIENT_ADAPTERS)
        self.assertIn(register_cursor_mcp, WINDOWS_MCP_CLIENT_ADAPTERS)
        self.assertIn(register_windsurf_mcp, WINDOWS_MCP_CLIENT_ADAPTERS)

        paths = register_windows_mcp_clients(self.home, self.fixonce_exe)

        self.assertEqual(
            paths,
            [
                self.home / ".codex" / "config.toml",
                self.home / ".claude.json",
                self.home / ".cursor" / "mcp.json",
                self.home / ".codeium" / "windsurf" / "mcp_config.json",
            ],
        )
        text = self._codex_config_text()
        self.assertIn("[mcp_servers.fixonce]", text)
        self.assertIn("startup_timeout_sec = 60", text)
        self.assertNotIn("PYTHONPATH", text)
        self.assertIn('FIXONCE_ACTOR = "codex"', text)
        self._assert_json_client_config(self.home / ".claude.json", "claude")
        self._assert_json_client_config(self.home / ".cursor" / "mcp.json", "cursor")
        self._assert_json_client_config(self.home / ".codeium" / "windsurf" / "mcp_config.json", "windsurf")


if __name__ == "__main__":
    unittest.main()
