import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import install
import core.system_status as system_status


class TestClientOnboarding(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-client-onboarding-")
        self.temp_home = Path(self.temp_dir.name)
        self.detect_patch = patch.object(install, "get_fixonce_dir", return_value=PROJECT_ROOT)
        self.home_patch = patch("pathlib.Path.home", return_value=self.temp_home)
        self.detect_patch.start()
        self.home_patch.start()

    def tearDown(self):
        self.detect_patch.stop()
        self.home_patch.stop()
        self.temp_dir.cleanup()

    def test_configure_mcp_writes_all_supported_client_configs(self):
        def fake_run(cmd, capture_output=False, text=False, timeout=None):
            class Result:
                returncode = 1
                stdout = ""
                stderr = ""
            return Result()

        editors = {
            "claude_code": True,
            "cursor": True,
            "codex": True,
            "windsurf": True,
        }

        with patch.object(install.subprocess, "run", side_effect=fake_run), \
             patch.object(install, "get_platform", return_value="mac"):
            success = install.configure_mcp(editors)

        self.assertTrue(success)

        claude_config = self.temp_home / ".claude.json"
        cursor_config = self.temp_home / ".cursor" / "mcp.json"
        codex_config = self.temp_home / ".codex" / "config.toml"
        windsurf_config = self.temp_home / ".codeium" / "windsurf" / "mcp_config.json"

        self.assertTrue(claude_config.exists())
        self.assertTrue(cursor_config.exists())
        self.assertTrue(codex_config.exists())
        self.assertTrue(windsurf_config.exists())

        claude_server = json.loads(claude_config.read_text(encoding="utf-8"))["mcpServers"]["fixonce"]
        cursor_server = json.loads(cursor_config.read_text(encoding="utf-8"))["mcpServers"]["fixonce"]
        windsurf_server = json.loads(windsurf_config.read_text(encoding="utf-8"))["mcpServers"]["fixonce"]
        self.assertEqual(claude_server["env"]["FIXONCE_ACTOR"], "claude")
        self.assertEqual(cursor_server["env"]["FIXONCE_ACTOR"], "cursor")
        self.assertEqual(windsurf_server["env"]["FIXONCE_ACTOR"], "windsurf")
        self.assertIn("[mcp_servers.fixonce]", codex_config.read_text(encoding="utf-8"))
        self.assertIn('FIXONCE_ACTOR = "codex"', codex_config.read_text(encoding="utf-8"))

    def test_windows_packaged_config_uses_fixonce_exe_for_all_clients(self):
        def fake_run(cmd, capture_output=False, text=False, timeout=None):
            class Result:
                returncode = 1
                stdout = ""
                stderr = ""
            return Result()

        install_root = self.temp_home / "PackagedFixOnce"
        install_root.mkdir()
        packaged_exe = install_root / "FixOnce.exe"
        packaged_exe.write_text("", encoding="utf-8")

        editors = {
            "claude_code": False,
            "cursor": True,
            "codex": True,
            "windsurf": True,
        }

        with patch.object(install.subprocess, "run", side_effect=fake_run), \
             patch.object(install, "get_fixonce_dir", return_value=install_root), \
             patch.object(install, "get_platform", return_value="windows"):
            success = install.configure_mcp(editors)

        self.assertTrue(success)
        for path, actor in (
            (self.temp_home / ".claude.json", "claude"),
            (self.temp_home / ".cursor" / "mcp.json", "cursor"),
            (self.temp_home / ".codeium" / "windsurf" / "mcp_config.json", "windsurf"),
        ):
            server = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["fixonce"]
            self.assertEqual(server["command"], str(packaged_exe))
            self.assertEqual(server["args"], ["--mcp"])
            self.assertEqual(server["env"], {"FIXONCE_ACTOR": actor})
            self.assertNotIn("PYTHONPATH", json.dumps(server))

        codex_text = (self.temp_home / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn(str(packaged_exe).replace("\\", "\\\\"), codex_text)
        self.assertIn('args = ["--mcp"]', codex_text)
        self.assertIn('FIXONCE_ACTOR = "codex"', codex_text)
        self.assertNotIn("PYTHONPATH", codex_text)

    def test_windows_installer_codex_block_sets_actor(self):
        installer_text = (PROJECT_ROOT / "install.ps1").read_text(encoding="utf-8")

        self.assertIn('FIXONCE_ACTOR = "codex"', installer_text)

    def test_configure_mcp_writes_global_configs_even_when_editors_not_detected(self):
        def fake_run(cmd, capture_output=False, text=False, timeout=None):
            class Result:
                returncode = 1
                stdout = ""
                stderr = ""
            return Result()

        editors = {
            "claude_code": False,
            "cursor": False,
            "codex": False,
            "windsurf": False,
        }

        with patch.object(install.subprocess, "run", side_effect=fake_run), \
             patch.object(install, "get_platform", return_value="mac"):
            success = install.configure_mcp(editors)

        self.assertTrue(success)
        self.assertTrue((self.temp_home / ".claude.json").exists())
        self.assertTrue((self.temp_home / ".codex" / "config.toml").exists())
        self.assertTrue((self.temp_home / ".codeium" / "windsurf" / "mcp_config.json").exists())
        self.assertIn("[mcp_servers.fixonce]", (self.temp_home / ".codex" / "config.toml").read_text(encoding="utf-8"))

    def test_configure_mcp_does_not_write_codex_only_under_project_dir(self):
        def fake_run(cmd, capture_output=False, text=False, timeout=None):
            class Result:
                returncode = 1
                stdout = ""
                stderr = ""
            return Result()

        temp_install_root = self.temp_home / "FixOnceInstall"
        (temp_install_root / "src" / "mcp_server").mkdir(parents=True, exist_ok=True)
        (temp_install_root / "src" / "mcp_server" / "mcp_memory_server_v2.py").write_text("# test server\n", encoding="utf-8")

        project_codex = temp_install_root / ".codex" / "config.toml"
        project_codex.parent.mkdir(parents=True, exist_ok=True)
        project_codex.write_text("", encoding="utf-8")

        editors = {
            "claude_code": False,
            "cursor": False,
            "codex": False,
            "windsurf": False,
        }

        with patch.object(install.subprocess, "run", side_effect=fake_run), \
             patch.object(install, "get_fixonce_dir", return_value=temp_install_root), \
             patch.object(install, "get_platform", return_value="mac"):
            install.configure_mcp(editors)

        global_codex = self.temp_home / ".codex" / "config.toml"
        self.assertTrue(global_codex.exists())
        self.assertIn("[mcp_servers.fixonce]", global_codex.read_text(encoding="utf-8"))

    def test_sync_rules_writes_global_rules_without_duplication(self):
        with patch.object(install, "configure_claude_hooks", return_value=True), \
             patch.object(install, "configure_codex_hooks", return_value=True), \
             patch.object(install, "get_platform", return_value="mac"):
            first = install.sync_rules()
            second = install.sync_rules()

        self.assertTrue(first)
        self.assertTrue(second)

        claude_rules = (self.temp_home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        codex_rules = (self.temp_home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
        windsurf_rules = (self.temp_home / ".codeium" / "windsurf" / "memories" / "global_rules.md").read_text(encoding="utf-8")
        cursor_settings = json.loads((self.temp_home / "Library" / "Application Support" / "Cursor" / "User" / "settings.json").read_text(encoding="utf-8"))

        self.assertEqual(claude_rules.count(install.FIXONCE_RULES_START), 1)
        self.assertEqual(codex_rules.count(install.FIXONCE_RULES_START), 1)
        self.assertEqual(windsurf_rules.count(install.FIXONCE_RULES_START), 1)
        self.assertIn("fo_init", cursor_settings["cursor.general.aiRules"])
        self.assertIn("Call it once per session", cursor_settings["cursor.general.aiRules"])

    def test_configure_claude_hooks_skips_missing_hook_files(self):
        missing_hooks_dir = self.temp_home / "missing-fixonce"
        missing_hooks_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(install, "get_platform", return_value="mac"):
            success = install.configure_claude_hooks(missing_hooks_dir)

        self.assertFalse(success)
        settings_path = self.temp_home / ".claude" / "settings.json"
        if settings_path.exists():
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertNotIn("hooks", settings)

    def test_configure_codex_hooks_adds_pre_and_post_tool_use_without_duplication(self):
        with patch.object(install, "get_platform", return_value="mac"):
            first = install.configure_codex_hooks(PROJECT_ROOT)
            second = install.configure_codex_hooks(PROJECT_ROOT)

        self.assertTrue(first)
        self.assertTrue(second)
        hooks_path = self.temp_home / ".codex" / "hooks.json"
        payload = json.loads(hooks_path.read_text(encoding="utf-8"))
        groups = payload["hooks"]["PostToolUse"]
        fixonce_handlers = [
            handler
            for group in groups
            for handler in group["hooks"]
            if "FIXONCE_ACTOR=codex" in handler["command"]
        ]
        self.assertEqual(len(fixonce_handlers), 1)

        pre_groups = payload["hooks"]["PreToolUse"]
        pre_handlers = [
            handler
            for group in pre_groups
            for handler in group["hooks"]
            if "pre_tool_context_codex.sh" in handler["command"]
        ]
        self.assertEqual(len(pre_handlers), 1)
        self.assertIn("exec", pre_groups[0]["matcher"])
        self.assertIn("exec_command", pre_groups[0]["matcher"])
        self.assertIn("apply_patch", pre_groups[0]["matcher"])

    def test_system_status_detects_windsurf_configuration(self):
        windsurf_config = self.temp_home / ".codeium" / "windsurf" / "mcp_config.json"
        windsurf_config.parent.mkdir(parents=True, exist_ok=True)
        windsurf_config.write_text(json.dumps({"mcpServers": {"fixonce": {"command": "python"}}}), encoding="utf-8")

        with patch.object(system_status, "_load_runtime_ai_status", return_value={}), \
             patch.object(system_status, "_detect_installed_clients", return_value={
                 "codex": False,
                 "claude": False,
                 "cursor": False,
                 "windsurf": True,
             }):
            status = system_status._check_mcp()

        self.assertTrue(status.windsurf)
        self.assertTrue(status.clients["windsurf"].configured)
        self.assertEqual(status.clients["windsurf"].config_scope, "global")


if __name__ == "__main__":
    unittest.main()
