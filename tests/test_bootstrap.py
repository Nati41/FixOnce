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

    def test_ensure_windows_scheduled_task_uses_server_command(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(
            app_launcher,
            "get_packaged_server_command",
            return_value=[r"C:\Apps\FixOnce\FixOnce.exe", "--server"],
        ), patch.object(app_launcher, "windows_scheduled_task_exists", return_value=False), patch.object(
            app_launcher.subprocess,
            "run",
            return_value=type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        ) as run_task:
            self.assertTrue(app_launcher.ensure_windows_scheduled_task())

        args = run_task.call_args[0][0]
        self.assertEqual(args[0], "schtasks")
        self.assertEqual(args[2], "/tn")
        self.assertEqual(args[3], "FixOnceServer")
        self.assertIn("--server", args[5])

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
        ), patch.object(app_launcher, "ensure_windows_scheduled_task", return_value=True) as ensure_task, patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=5000,
        ) as ensure_server, patch.object(app_launcher, "open_dashboard") as open_dashboard:
            code = app_launcher.run_bootstrap()

        self.assertEqual(code, 0)
        ensure_task.assert_called_once()
        ensure_server.assert_called_once()
        open_dashboard.assert_called_once_with(5000)

        snapshot = load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, InstallState.READY)
        self.assertEqual(snapshot.runtime_port, 5000)
        self.assertEqual(snapshot.runtime_pid, 4242)
        self.assertEqual(snapshot.install_dir, r"C:\Apps\FixOnce")
        self.assertTrue(any("Bootstrap completed successfully" in line for line in self._log_lines()))

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
        ), patch.object(app_launcher, "ensure_windows_scheduled_task", return_value=True) as ensure_task, patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=5000,
        ) as ensure_server, patch.object(app_launcher, "open_dashboard") as open_dashboard:
            first = app_launcher.run_bootstrap()
            second = app_launcher.run_bootstrap()

        self.assertEqual(first, 0)
        self.assertEqual(second, 0)
        self.assertEqual(ensure_task.call_count, 2)
        self.assertEqual(ensure_server.call_count, 2)
        self.assertEqual(open_dashboard.call_count, 2)
        snapshot = load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, InstallState.READY)

    def test_run_bootstrap_fails_when_health_never_ok(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(app_launcher, "ensure_windows_scheduled_task", return_value=True), patch.object(
            app_launcher,
            "ensure_packaged_server_running",
            return_value=None,
        ), patch.object(app_launcher, "open_dashboard") as open_dashboard:
            code = app_launcher.run_bootstrap()

        self.assertEqual(code, 1)
        open_dashboard.assert_not_called()
        snapshot = load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, InstallState.FAILED)
        self.assertIn("health", snapshot.detail.lower())

    def test_main_dispatches_bootstrap(self):
        with patch.object(app_launcher, "run_bootstrap", return_value=0) as run_bootstrap, patch.object(sys, "argv", ["FixOnce.exe", "--bootstrap"]):
            with self.assertRaises(SystemExit) as ctx:
                app_launcher.main()
            self.assertEqual(ctx.exception.code, 0)
        run_bootstrap.assert_called_once()


if __name__ == "__main__":
    unittest.main()
