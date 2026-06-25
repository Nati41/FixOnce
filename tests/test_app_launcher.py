import json
import os
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
        progress_steps = []
        with patch.object(app_launcher, "discover_running_port", return_value=5003), patch.object(
            app_launcher,
            "endpoint_responds",
            side_effect=lambda port, endpoint, timeout=1.0: port == 5003 and endpoint == "/api/health",
        ), patch.object(app_launcher, "start_server") as start_server:
            self.assertEqual(app_launcher.ensure_server_ready(progress_steps.append), 5003)
            start_server.assert_not_called()
        self.assertEqual(progress_steps, ["checking"])

    def test_ensure_server_ready_reports_starting_server_before_wait(self):
        progress_steps = []
        with patch.object(app_launcher, "discover_running_port", return_value=None), patch.object(
            app_launcher,
            "start_server",
        ) as start_server, patch.object(app_launcher, "wait_for_server", return_value=5000):
            self.assertEqual(app_launcher.ensure_server_ready(progress_steps.append), 5000)

        start_server.assert_called_once()
        self.assertEqual(progress_steps, ["checking", "connecting"])

    def test_launch_app_shows_startup_splash_until_dashboard_ready(self):
        splash = type(
            "Splash",
            (),
            {
                "__init__": lambda self: setattr(self, "steps", []),
                "show_step": lambda self, step: self.steps.append(step),
                "close": lambda self: self.steps.append("closed"),
            },
        )
        created = []

        def make_splash():
            instance = splash()
            created.append(instance)
            return instance

        with patch.object(app_launcher, "StartupSplash", side_effect=make_splash), patch.object(
            app_launcher,
            "ensure_server_ready",
            return_value=5000,
        ) as ensure_ready, patch.object(app_launcher, "open_dashboard") as open_dashboard:
            self.assertTrue(app_launcher.launch_app())

        ensure_ready.assert_called_once_with(created[0].show_step)
        open_dashboard.assert_called_once_with(5000)
        self.assertEqual(created[0].steps, ["opening", "closed"])

    def test_bootstrap_detached_dashboard_launch_starts_normal_launcher(self):
        with patch.object(app_launcher.sys, "platform", "win32"), patch.object(
            app_launcher.sys,
            "executable",
            r"C:\Apps\FixOnce\FixOnce.exe",
        ), patch.object(app_launcher, "is_frozen", return_value=True), patch.object(
            app_launcher,
            "get_packaged_install_dir",
            return_value=Path(r"C:\Apps\FixOnce"),
        ), patch.object(app_launcher, "windows_process_creationflags", return_value=123), patch.object(
            app_launcher.subprocess, "Popen"
        ) as popen:
            self.assertTrue(app_launcher.launch_dashboard_detached())

        args, kwargs = popen.call_args
        self.assertEqual(args[0], [r"C:\Apps\FixOnce\FixOnce.exe"])
        self.assertEqual(kwargs["cwd"], r"C:\Apps\FixOnce")
        self.assertEqual(kwargs["creationflags"], 123)

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

    def test_mcp_mode_writes_startup_diagnostics_before_import(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-mcp-startup-") as temp_dir:
            temp_home = Path(temp_dir)
            log_file = temp_home / ".fixonce" / "logs" / "mcp_startup.log"

            def assert_log_exists_before_import(*args, **kwargs):
                text = log_file.read_text(encoding="utf-8")
                self.assertIn("--mcp startup started", text)
                self.assertIn("executable=", text)
                self.assertIn("cwd=", text)
                self.assertIn("userprofile=", text)
                self.assertIn("home=", text)
                self.assertIn("--mcp entering mcp_server.mcp_memory_server_v2", text)
                raise RuntimeError("stop before MCP import")

            with patch.dict(os.environ, {"USERPROFILE": str(temp_home)}), \
                 patch.object(app_launcher, "LOG_DIR", log_file.parent), \
                 patch.object(app_launcher, "MCP_STARTUP_LOG", log_file), \
                 patch.object(app_launcher.runpy, "run_module", side_effect=assert_log_exists_before_import):
                with self.assertRaisesRegex(RuntimeError, "stop before MCP import"):
                    app_launcher.run_mcp_mode()

    def test_mcp_mode_runs_stdio_module_without_dashboard_or_server(self):
        with patch.object(app_launcher, "is_frozen", return_value=True), \
             patch.object(app_launcher.runpy, "run_module") as run_module, \
             patch.object(app_launcher, "open_dashboard") as open_dashboard, \
             patch.object(app_launcher, "run_server_mode") as run_server_mode, \
             patch.object(app_launcher, "mcp_startup_log") as startup_log:
            app_launcher.run_mcp_mode()

        run_module.assert_called_once_with("mcp_server.mcp_memory_server_v2", run_name="__main__")
        open_dashboard.assert_not_called()
        run_server_mode.assert_not_called()
        startup_messages = [call.args[0] for call in startup_log.call_args_list]
        self.assertTrue(any("--mcp startup started" in message for message in startup_messages))
        self.assertTrue(any("--mcp entering mcp_server.mcp_memory_server_v2" in message for message in startup_messages))

    def test_main_dispatches_mcp_mode_first(self):
        with patch.object(app_launcher, "run_mcp_mode") as run_mcp_mode, \
             patch.object(app_launcher, "run_server_mode") as run_server_mode, \
             patch.object(sys, "argv", ["FixOnce.exe", "--mcp", "--server"]):
            app_launcher.main()

        run_mcp_mode.assert_called_once()
        run_server_mode.assert_not_called()

    def test_mcp_server_semantic_stack_is_lazy_loaded(self):
        source = (PROJECT_ROOT / "src" / "mcp_server" / "mcp_memory_server_v2.py").read_text(encoding="utf-8")
        before_lazy_loader = source.split("def _load_project_semantic", 1)[0]

        self.assertNotIn("from core.project_semantic import", before_lazy_loader)
        self.assertIn("def _load_project_semantic", source)
        self.assertIn("from core.project_semantic import", source)


class TestWebviewRetryFlow(unittest.TestCase):
    """Regression tests for Windows webview ERR_CONNECTION_REFUSED fix."""

    def test_verify_server_reachable_succeeds_on_first_try(self):
        with patch.object(app_launcher, "endpoint_responds", return_value=True) as mock_responds:
            result = app_launcher._verify_server_reachable(5000)

        self.assertTrue(result)
        mock_responds.assert_called_once_with(5000, "/api/health", timeout=2.0)

    def test_verify_server_reachable_retries_on_failure(self):
        call_count = [0]

        def respond_on_third(*args, **kwargs):
            call_count[0] += 1
            return call_count[0] >= 3

        with patch.object(app_launcher, "endpoint_responds", side_effect=respond_on_third), \
             patch.object(app_launcher.time, "sleep") as mock_sleep:
            result = app_launcher._verify_server_reachable(5000, attempts=5)

        self.assertTrue(result)
        self.assertEqual(call_count[0], 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_verify_server_reachable_returns_false_after_exhausted_retries(self):
        with patch.object(app_launcher, "endpoint_responds", return_value=False), \
             patch.object(app_launcher.time, "sleep"):
            result = app_launcher._verify_server_reachable(5000, attempts=3)

        self.assertFalse(result)

    def test_loading_html_contains_retry_javascript(self):
        html = app_launcher._get_loading_html(5000)

        self.assertIn("http://127.0.0.1:5000/", html)
        self.assertIn("api/ping", html)
        self.assertIn("checkServer", html)
        self.assertIn("maxAttempts", html)
        self.assertIn("setTimeout", html)
        self.assertIn("window.location.href", html)

    def test_loading_html_has_graceful_failure_message(self):
        html = app_launcher._get_loading_html(5000)

        self.assertIn("Could not connect", html)
        self.assertIn("Please restart FixOnce", html)

    def test_open_dashboard_windows_uses_loading_html(self):
        mock_webview = type("webview", (), {
            "create_window": lambda *a, **kw: type("Window", (), {})(),
            "start": lambda *a, **kw: None,
        })()

        with patch.object(app_launcher.sys, "platform", "win32"), \
             patch.object(app_launcher, "_verify_server_reachable", return_value=True) as verify, \
             patch.object(app_launcher, "_get_loading_html", return_value="<html>loading</html>") as get_html, \
             patch.dict("sys.modules", {"webview": mock_webview}), \
             patch.object(mock_webview, "create_window", return_value=type("W", (), {})()) as create_window:
            app_launcher.open_dashboard(5000)

        verify.assert_called_once_with(5000)
        get_html.assert_called_once_with(5000)
        args, kwargs = create_window.call_args
        self.assertEqual(kwargs.get("html"), "<html>loading</html>")
        self.assertNotIn("url", kwargs)

    def test_open_dashboard_macos_uses_direct_url(self):
        mock_webview = type("webview", (), {
            "create_window": lambda *a, **kw: type("Window", (), {})(),
            "start": lambda *a, **kw: None,
        })()

        with patch.object(app_launcher.sys, "platform", "darwin"), \
             patch.object(app_launcher, "_verify_server_reachable") as verify, \
             patch.object(app_launcher, "set_dock_icon"), \
             patch.dict("sys.modules", {"webview": mock_webview}), \
             patch.object(mock_webview, "create_window", return_value=type("W", (), {})()) as create_window:
            app_launcher.open_dashboard(5000)

        verify.assert_not_called()
        args, kwargs = create_window.call_args
        self.assertEqual(args[1], "http://127.0.0.1:5000/")
        self.assertNotIn("html", kwargs)


if __name__ == "__main__":
    unittest.main()
