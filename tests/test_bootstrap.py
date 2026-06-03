import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import app_launcher
from core.install_state_machine import InstallState, load_snapshot


class TestBootstrap(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-bootstrap-")
        self.data_dir = Path(self.temp_dir.name) / ".fixonce"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir = self.data_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.bootstrap_log = self.logs_dir / "bootstrap.log"
        self.runtime_file = self.data_dir / "runtime.json"
        self.install_state_file = self.data_dir / "install_state.json"

        self.env_patch = patch.object(app_launcher, "USER_DATA_DIR", self.data_dir)
        self.log_dir_patch = patch.object(app_launcher, "LOG_DIR", self.logs_dir)
        self.bootstrap_log_patch = patch.object(app_launcher, "BOOTSTRAP_LOG", self.bootstrap_log)
        self.runtime_patch = patch.object(app_launcher, "RUNTIME_FILE", self.runtime_file)
        self.env_patch.start()
        self.log_dir_patch.start()
        self.bootstrap_log_patch.start()
        self.runtime_patch.start()

        self.data_dir_patch = patch("core.install_state_machine.DATA_DIR", self.data_dir)
        self.data_dir_patch.start()

    def tearDown(self):
        self.data_dir_patch.stop()
        self.runtime_patch.stop()
        self.bootstrap_log_patch.stop()
        self.log_dir_patch.stop()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def _log_lines(self) -> list[str]:
        if not self.bootstrap_log.exists():
            return []
        return self.bootstrap_log.read_text(encoding="utf-8").splitlines()

    def test_run_bootstrap_rejects_non_windows(self):
        with patch.object(app_launcher.sys, "platform", "darwin"), patch.object(app_launcher, "is_frozen", return_value=True):
            code = app_launcher.run_bootstrap()
        self.assertEqual(code, 1)
        self.assertTrue(any("only supported on Windows" in line for line in self._log_lines()))

    def test_run_bootstrap_rejects_non_packaged(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher, "is_frozen", return_value=False):
            code = app_launcher.run_bootstrap()
        self.assertEqual(code, 1)
        self.assertTrue(any("packaged FixOnce.exe" in line for line in self._log_lines()))

    def test_ensure_windows_scheduled_task_uses_powershell_register(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(
            app_launcher,
            "get_packaged_server_command",
            return_value=[r"C:\Apps\FixOnce\FixOnce.exe", "--server"],
        ), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(app_launcher, "windows_scheduled_task_exists", return_value=False), patch.object(
            app_launcher,
            "_register_user_logon_task_powershell",
            return_value=(True, ""),
        ) as register_task:
            self.assertTrue(app_launcher.ensure_windows_scheduled_task())

        register_task.assert_called_once_with(
            "FixOnceServer",
            r"C:\Apps\FixOnce\FixOnce.exe",
            "--server",
            r"C:\Apps\FixOnce",
        )

    def test_ensure_windows_scheduled_task_falls_back_to_schtasks_without_it(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(
            app_launcher,
            "get_packaged_server_command",
            return_value=[r"C:\Apps\FixOnce\FixOnce.exe", "--server"],
        ), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(app_launcher, "windows_scheduled_task_exists", return_value=False), patch.object(
            app_launcher,
            "_register_user_logon_task_powershell",
            return_value=(False, "Access is denied."),
        ), patch.object(
            app_launcher,
            "_register_user_logon_task_schtasks",
            return_value=(True, ""),
        ) as schtasks_register:
            self.assertTrue(app_launcher.ensure_windows_scheduled_task())

        schtasks_register.assert_called_once()

    def test_schtasks_fallback_does_not_use_interactive_only_flag(self):
        with patch.object(app_launcher.subprocess, "run", return_value=type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()) as run_task:
            ok, _ = app_launcher._register_user_logon_task_schtasks(
                "FixOnceServer",
                [r"C:\Apps\FixOnce\FixOnce.exe", "--server"],
            )

        self.assertTrue(ok)
        args = [part.lower() for part in run_task.call_args[0][0]]
        self.assertEqual(args[0], "schtasks")
        self.assertNotIn("/it", args)

    def test_configure_autostart_prefers_scheduled_task(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(
            app_launcher, "ensure_windows_scheduled_task", return_value=True
        ) as ensure_task, patch.object(app_launcher, "ensure_windows_startup_shortcut") as ensure_shortcut:
            method = app_launcher.configure_windows_autostart()

        self.assertEqual(method, app_launcher.AUTOSTART_METHOD_SCHEDULED_TASK)
        ensure_task.assert_called_once()
        ensure_shortcut.assert_not_called()

    def test_configure_autostart_uses_startup_shortcut_when_task_fails(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(
            app_launcher, "ensure_windows_scheduled_task", return_value=False
        ), patch.object(app_launcher, "ensure_windows_startup_shortcut", return_value=True) as ensure_shortcut:
            method = app_launcher.configure_windows_autostart()

        self.assertEqual(method, app_launcher.AUTOSTART_METHOD_STARTUP_SHORTCUT)
        ensure_shortcut.assert_called_once()

    def test_configure_autostart_none_when_all_methods_fail(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(
            app_launcher, "ensure_windows_scheduled_task", return_value=False
        ), patch.object(app_launcher, "ensure_windows_startup_shortcut", return_value=False):
            method = app_launcher.configure_windows_autostart()

        self.assertEqual(method, app_launcher.AUTOSTART_METHOD_NONE)

    def test_ensure_windows_startup_shortcut_uses_server_command(self):
        startup_dir = Path(self.temp_dir.name) / "Startup"
        shortcut_path = startup_dir / "FixOnceServer.lnk"

        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(
            app_launcher,
            "get_packaged_server_command",
            return_value=[r"C:\Apps\FixOnce\FixOnce.exe", "--server"],
        ), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(app_launcher, "get_windows_startup_shortcut_path", return_value=shortcut_path):
            def fake_run(*_args, **_kwargs):
                shortcut_path.parent.mkdir(parents=True, exist_ok=True)
                shortcut_path.touch()
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch.object(app_launcher.subprocess, "run", side_effect=fake_run) as run_ps:
                self.assertTrue(app_launcher.ensure_windows_startup_shortcut())

        script = run_ps.call_args[0][0][-1]
        self.assertIn("WScript.Shell", script)
        self.assertIn("--server", script)
        self.assertIn(r"C:\Apps\FixOnce\FixOnce.exe", script)

    def test_run_bootstrap_uses_startup_shortcut_when_scheduled_task_fails(self):
        self.runtime_file.write_text(
            json.dumps({"port": 5000, "pid": 4242}),
            encoding="utf-8",
        )

        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(
            app_launcher,
            "configure_windows_autostart",
            return_value=app_launcher.AUTOSTART_METHOD_STARTUP_SHORTCUT,
        ), patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=5000,
        ), patch.object(app_launcher, "open_dashboard") as open_dashboard:
            code = app_launcher.run_bootstrap()

        self.assertEqual(code, 0)
        open_dashboard.assert_called_once_with(5000)
        snapshot = load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, InstallState.READY)
        self.assertEqual(snapshot.metadata.get("autostart_method"), "startup_shortcut")

    def test_run_bootstrap_continues_when_autostart_unavailable(self):
        self.runtime_file.write_text(
            json.dumps({"port": 5000, "pid": 4242}),
            encoding="utf-8",
        )

        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(
            app_launcher,
            "configure_windows_autostart",
            return_value=app_launcher.AUTOSTART_METHOD_NONE,
        ), patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=5000,
        ), patch.object(app_launcher, "open_dashboard") as open_dashboard:
            code = app_launcher.run_bootstrap()

        self.assertEqual(code, 0)
        open_dashboard.assert_called_once_with(5000)
        snapshot = load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, InstallState.READY)
        self.assertEqual(snapshot.metadata.get("autostart_method"), "none")
        self.assertTrue(any("continuing bootstrap" in line.lower() for line in self._log_lines()))

    def test_run_bootstrap_success_writes_ready_and_opens_dashboard(self):
        self.runtime_file.write_text(
            json.dumps({"port": 5000, "pid": 4242, "install_path": r"C:\Apps\FixOnce"}),
            encoding="utf-8",
        )
        log_messages: list[str] = []

        def capture_log(message: str):
            log_messages.append(message)
            app_launcher.bootstrap_log(message)

        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(
            app_launcher,
            "configure_windows_autostart",
            return_value=app_launcher.AUTOSTART_METHOD_SCHEDULED_TASK,
        ) as configure_autostart, patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=5000,
        ) as ensure_server, patch.object(app_launcher, "open_dashboard") as open_dashboard:
            code = app_launcher.run_bootstrap()

        self.assertEqual(code, 0)
        configure_autostart.assert_called_once()
        ensure_server.assert_called_once()
        open_dashboard.assert_called_once_with(5000)

        snapshot = load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, InstallState.READY)
        self.assertEqual(snapshot.runtime_port, 5000)
        self.assertEqual(snapshot.runtime_pid, 4242)
        self.assertEqual(snapshot.install_dir, r"C:\Apps\FixOnce")
        self.assertTrue(any("Bootstrap completed successfully" in line for line in self._log_lines()))

    def test_run_bootstrap_registers_mcp_clients_for_fresh_windows_user(self):
        home_dir = Path(self.temp_dir.name) / "home"
        install_dir = Path(self.temp_dir.name) / "FixOnce"
        self.runtime_file.write_text(
            json.dumps({"port": 5000, "pid": 4242, "install_path": str(install_dir)}),
            encoding="utf-8",
        )

        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher.sys, "executable", str(install_dir / "FixOnce.exe")), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=install_dir,
        ), patch.object(
            app_launcher,
            "configure_windows_autostart",
            return_value=app_launcher.AUTOSTART_METHOD_SCHEDULED_TASK,
        ), patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=5000,
        ), patch("pathlib.Path.home", return_value=home_dir), patch.object(app_launcher, "open_dashboard"):
            first = app_launcher.run_bootstrap()
            second = app_launcher.run_bootstrap()

        self.assertEqual(first, 0)
        self.assertEqual(second, 0)
        codex_config = home_dir / ".codex" / "config.toml"
        claude_config = home_dir / ".claude.json"
        cursor_config = home_dir / ".cursor" / "mcp.json"
        windsurf_config = home_dir / ".codeium" / "windsurf" / "mcp_config.json"
        self.assertTrue(codex_config.exists())
        text = codex_config.read_text(encoding="utf-8")
        self.assertEqual(text.count("[mcp_servers.fixonce]"), 1)
        self.assertIn("FixOnce.exe", text)
        self.assertIn('args = ["--mcp"]', text)
        self.assertNotIn("PYTHONPATH", text)
        self.assertIn('FIXONCE_ACTOR = "codex"', text)
        for path, actor in (
            (claude_config, "claude"),
            (cursor_config, "cursor"),
            (windsurf_config, "windsurf"),
        ):
            self.assertTrue(path.exists())
            server = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["fixonce"]
            self.assertEqual(server["command"], str(install_dir / "FixOnce.exe"))
            self.assertEqual(server["args"], ["--mcp"])
            self.assertEqual(server["env"], {"FIXONCE_ACTOR": actor})
            self.assertNotIn("PYTHONPATH", json.dumps(server))
        self.assertTrue(any("MCP registration completed" in line for line in self._log_lines()))

    def test_run_bootstrap_repairs_legacy_mcp_configs(self):
        home_dir = Path(self.temp_dir.name) / "home"
        install_dir = Path(self.temp_dir.name) / "FixOnce"
        codex_config = home_dir / ".codex" / "config.toml"
        codex_config.parent.mkdir(parents=True)
        claude_config = home_dir / ".claude.json"
        cursor_config = home_dir / ".cursor" / "mcp.json"
        windsurf_config = home_dir / ".codeium" / "windsurf" / "mcp_config.json"
        legacy_command = str(install_dir / "FixOnce.exe").replace("\\", "\\\\")
        legacy_mcp_server = str(install_dir / "src" / "mcp_server" / "mcp_memory_server_v2.py").replace("\\", "\\\\")
        legacy_src = str(install_dir / "src").replace("\\", "\\\\")
        codex_config.write_text(
            "\n".join(
                [
                    "[mcp_servers.fixonce]",
                    f'command = "{legacy_command}"',
                    f'args = ["{legacy_mcp_server}"]',
                    "",
                    "[mcp_servers.fixonce.env]",
                    f'PYTHONPATH = "{legacy_src}"',
                    'FIXONCE_ACTOR = "codex"',
                    "",
                    "[profiles.default]",
                    'model = "gpt-5"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        for path in (claude_config, cursor_config, windsurf_config):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "fixonce": {
                                "command": str(install_dir / "FixOnce.exe"),
                                "args": [str(install_dir / "src" / "mcp_server" / "mcp_memory_server_v2.py")],
                                "env": {"PYTHONPATH": str(install_dir / "src")},
                            },
                            "other": {"command": "node"},
                        },
                        "theme": "dark",
                    }
                ),
                encoding="utf-8",
            )
        self.runtime_file.write_text(
            json.dumps({"port": 5000, "pid": 4242, "install_path": str(install_dir)}),
            encoding="utf-8",
        )

        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher.sys, "executable", str(install_dir / "FixOnce.exe")), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=install_dir,
        ), patch.object(
            app_launcher,
            "configure_windows_autostart",
            return_value=app_launcher.AUTOSTART_METHOD_SCHEDULED_TASK,
        ), patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=5000,
        ), patch("pathlib.Path.home", return_value=home_dir), patch.object(app_launcher, "open_dashboard"):
            code = app_launcher.run_bootstrap()

        self.assertEqual(code, 0)
        text = codex_config.read_text(encoding="utf-8")
        self.assertEqual(text.count("[mcp_servers.fixonce]"), 1)
        self.assertIn("FixOnce.exe", text)
        self.assertIn('args = ["--mcp"]', text)
        self.assertIn("startup_timeout_sec = 60", text)
        self.assertIn("[mcp_servers.fixonce.env]", text)
        self.assertNotIn("PYTHONPATH", text)
        self.assertIn('FIXONCE_ACTOR = "codex"', text)
        self.assertNotIn("mcp_memory_server_v2.py", text)
        self.assertIn('[profiles.default]\nmodel = "gpt-5"', text)
        for path, actor in (
            (claude_config, "claude"),
            (cursor_config, "cursor"),
            (windsurf_config, "windsurf"),
        ):
            config = json.loads(path.read_text(encoding="utf-8"))
            server = config["mcpServers"]["fixonce"]
            self.assertEqual(server["command"], str(install_dir / "FixOnce.exe"))
            self.assertEqual(server["args"], ["--mcp"])
            self.assertEqual(server["env"], {"FIXONCE_ACTOR": actor})
            self.assertEqual(config["mcpServers"]["other"], {"command": "node"})
            self.assertEqual(config["theme"], "dark")
            self.assertNotIn("PYTHONPATH", json.dumps(server))
            self.assertNotIn("mcp_memory_server_v2.py", json.dumps(server))

    def test_run_bootstrap_idempotent_second_run(self):
        self.install_state_file.write_text(
            json.dumps(
                {
                    "state": "READY",
                    "updated_at": "2026-01-01T00:00:00",
                    "detail": "Bootstrap completed",
                    "install_dir": r"C:\Apps\FixOnce",
                    "runtime_port": 5000,
                    "runtime_pid": 4242,
                    "metadata": {"bootstrap": True},
                }
            ),
            encoding="utf-8",
        )
        self.runtime_file.write_text(
            json.dumps({"port": 5000, "pid": 4242}),
            encoding="utf-8",
        )

        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(
            app_launcher,
            "configure_windows_autostart",
            return_value=app_launcher.AUTOSTART_METHOD_SCHEDULED_TASK,
        ) as configure_autostart, patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=5000,
        ) as ensure_server, patch.object(app_launcher, "open_dashboard") as open_dashboard:
            first = app_launcher.run_bootstrap()
            second = app_launcher.run_bootstrap()

        self.assertEqual(first, 0)
        self.assertEqual(second, 0)
        self.assertEqual(configure_autostart.call_count, 2)
        self.assertEqual(ensure_server.call_count, 2)
        self.assertEqual(open_dashboard.call_count, 2)
        snapshot = load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, InstallState.READY)

    def test_run_bootstrap_fails_when_health_never_ok(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(
            app_launcher,
            "configure_windows_autostart",
            return_value=app_launcher.AUTOSTART_METHOD_SCHEDULED_TASK,
        ), patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=None,
        ), patch.object(
            app_launcher,
            "log_windows_defender_diagnostics",
            return_value={"blocked_likely": False},
        ), patch.object(app_launcher, "open_dashboard") as open_dashboard:
            code = app_launcher.run_bootstrap()

        self.assertEqual(code, 1)
        open_dashboard.assert_not_called()
        snapshot = load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, InstallState.FAILED)
        self.assertIn("health", snapshot.detail.lower())

    def test_run_bootstrap_reports_defender_block_when_health_never_ok(self):
        diagnostics = {
            "blocked_likely": True,
            "disposition": "terminated_or_blocked",
            "executable_exists": True,
            "relevant_detections": [{"ThreatName": "Trojan:Win32/Bearfoos.A!ml"}],
        }

        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(
            app_launcher,
            "configure_windows_autostart",
            return_value=app_launcher.AUTOSTART_METHOD_STARTUP_SHORTCUT,
        ), patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=None,
        ), patch.object(
            app_launcher,
            "log_windows_defender_diagnostics",
            return_value=diagnostics,
        ), patch.object(app_launcher, "open_dashboard") as open_dashboard:
            code = app_launcher.run_bootstrap()

        self.assertEqual(code, 1)
        open_dashboard.assert_not_called()
        snapshot = load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, InstallState.FAILED)
        self.assertIn("Windows Defender", snapshot.detail)
        self.assertEqual(snapshot.metadata["defender_diagnostics"]["disposition"], "terminated_or_blocked")

    def test_uninstall_script_removes_startup_shortcut(self):
        uninstall_text = (PROJECT_ROOT / "uninstall.ps1").read_text(encoding="utf-8")
        self.assertIn("FixOnceServer.lnk", uninstall_text)
        self.assertIn("Programs\\Startup", uninstall_text)

    def test_main_dispatches_bootstrap(self):
        with patch.object(app_launcher, "run_bootstrap", return_value=0) as run_bootstrap, patch.object(sys, "argv", ["FixOnce.exe", "--bootstrap"]):
            with self.assertRaises(SystemExit) as ctx:
                app_launcher.main()
            self.assertEqual(ctx.exception.code, 0)
        run_bootstrap.assert_called_once()

    def test_main_dispatches_mcp_mode(self):
        with patch.object(app_launcher, "run_mcp_mode") as run_mcp_mode, patch.object(sys, "argv", ["FixOnce.exe", "--mcp"]):
            app_launcher.main()
        run_mcp_mode.assert_called_once()


if __name__ == "__main__":
    unittest.main()
