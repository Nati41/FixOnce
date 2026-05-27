import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import app_launcher


class TestAppLauncher(unittest.TestCase):
    def test_read_saved_ports_prefers_runtime_then_config(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-launcher-") as temp_dir:
            temp_home = Path(temp_dir)
            fixonce_dir = temp_home / ".fixonce"
            fixonce_dir.mkdir(parents=True, exist_ok=True)
            runtime = fixonce_dir / "runtime.json"
            config = fixonce_dir / "config.json"

            runtime.write_text(json.dumps({"port": 5002}), encoding="utf-8")
            config.write_text(json.dumps({"port": 5001}), encoding="utf-8")

            with patch.object(app_launcher, "RUNTIME_FILE", runtime), patch.object(app_launcher, "CONFIG_FILE", config):
                self.assertEqual(app_launcher.read_saved_ports(), [5002, 5001])

    def test_discover_running_port_checks_saved_port_first(self):
        with patch.object(app_launcher, "read_saved_ports", return_value=[5004]), patch.object(
            app_launcher,
            "is_current_install_server",
            side_effect=lambda port: port == 5004,
        ):
            self.assertEqual(app_launcher.discover_running_port(), 5004)

    def test_discover_running_port_rejects_other_fixonce_install(self):
        with patch.object(app_launcher, "read_saved_ports", return_value=[5004]), patch.object(
            app_launcher,
            "get_ping_payload",
            side_effect=lambda port: {
                5004: {
                    "service": "fixonce",
                    "install_path": str(PROJECT_ROOT / "other-copy"),
                },
                5005: {
                    "service": "fixonce",
                    "install_path": str(app_launcher.PROJECT_DIR),
                },
            }.get(port, {}),
        ):
            self.assertEqual(app_launcher.discover_running_port(), 5005)

    def test_discover_running_port_rejects_legacy_server_without_install_path(self):
        with patch.object(app_launcher, "read_saved_ports", return_value=[5004]), patch.object(
            app_launcher,
            "get_ping_payload",
            return_value={"service": "fixonce", "status": "ok"},
        ):
            self.assertIsNone(app_launcher.discover_running_port())

    def test_clear_stale_state_removes_dead_runtime_and_lock(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-launcher-") as temp_dir:
            temp_home = Path(temp_dir)
            fixonce_dir = temp_home / ".fixonce"
            fixonce_dir.mkdir(parents=True, exist_ok=True)
            runtime = fixonce_dir / "runtime.json"
            lock_file = fixonce_dir / "server.lock"

            runtime.write_text(json.dumps({"pid": 111, "port": 5001}), encoding="utf-8")
            lock_file.write_text("222", encoding="utf-8")

            with patch.object(app_launcher, "RUNTIME_FILE", runtime), patch.object(app_launcher, "LOCK_FILE", lock_file), patch.object(
                app_launcher,
                "is_pid_running",
                return_value=False,
            ):
                app_launcher.clear_stale_state()

            self.assertFalse(runtime.exists())
            self.assertFalse(lock_file.exists())

    def test_ensure_server_ready_reuses_existing_server(self):
        with patch.object(app_launcher, "discover_running_port", return_value=5003), patch.object(
            app_launcher,
            "endpoint_responds",
            side_effect=lambda port, endpoint, timeout=1.0: port == 5003 and endpoint == "/api/health",
        ), patch.object(app_launcher, "start_server") as start_server:
            self.assertEqual(app_launcher.ensure_server_ready(), 5003)
            start_server.assert_not_called()

    def test_windows_server_launch_uses_detached_process_group(self):
        with patch.object(app_launcher.sys, "platform", "win32"), \
             patch.object(app_launcher, "clear_stale_state"), \
             patch.object(app_launcher, "is_frozen", return_value=False), \
             patch.object(app_launcher, "SERVER_SCRIPT", PROJECT_ROOT / "src" / "server.py"), \
             patch.object(app_launcher, "get_windows_pythonw", return_value="pythonw.exe"), \
             patch.object(app_launcher.subprocess, "DETACHED_PROCESS", 0x8, create=True), \
             patch.object(app_launcher.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True), \
             patch.object(app_launcher.subprocess, "CREATE_NO_WINDOW", 0x8000000, create=True), \
             patch.object(app_launcher.subprocess, "Popen") as popen:
            app_launcher.start_server()

        args, kwargs = popen.call_args
        self.assertEqual(
            args[0],
            ["pythonw.exe", str(PROJECT_ROOT / "src" / "server.py"), "--flask-only", "--quiet", "--strict-port"],
        )
        self.assertEqual(kwargs["creationflags"], 0x8000208)
        self.assertEqual(kwargs["stdout"], app_launcher.subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], app_launcher.subprocess.DEVNULL)

    def test_windows_external_url_uses_shell_not_webbrowser(self):
        with patch.object(app_launcher.sys, "platform", "win32"), \
             patch.object(app_launcher.os, "startfile", create=True) as startfile, \
             patch.object(app_launcher.webbrowser, "open") as browser_open:
            app_launcher.open_external_url("http://127.0.0.1:5000/")

        startfile.assert_called_once_with("http://127.0.0.1:5000/")
        browser_open.assert_not_called()

    def test_main_dispatches_server_mode_without_flag_leak(self):
        with patch.object(app_launcher, "run_server_mode") as run_server_mode, patch.object(sys, "argv", ["app_launcher.py", "--server", "--flask-only", "--quiet"]):
            app_launcher.main()
            run_server_mode.assert_called_once_with(["--flask-only", "--quiet"])


if __name__ == "__main__":
    unittest.main()
