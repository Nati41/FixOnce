import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import server as server_module
import api.installer as installer_module
import core.install_state as install_state_module
from core.install_state_machine import InstallState


class TestInstalledState(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-installed-state-")
        self.data_dir = Path(self.temp_dir.name)
        self.client = server_module.flask_app.test_client()
        self.server_data_patch = patch.object(server_module, "DATA_DIR", self.data_dir)
        self.installer_data_patch = patch.object(installer_module, "DATA_DIR", self.data_dir)
        self.install_state_data_patch = patch.object(install_state_module, "DATA_DIR", self.data_dir)
        self.server_data_patch.start()
        self.installer_data_patch.start()
        self.install_state_data_patch.start()

    def tearDown(self):
        self.server_data_patch.stop()
        self.installer_data_patch.stop()
        self.install_state_data_patch.stop()
        self.temp_dir.cleanup()

    def test_dashboard_uses_runtime_when_install_state_missing(self):
        with patch.object(install_state_module, "get_runtime_state", return_value={"port": 5001, "pid": 123}):
            response = self.client.get("/", headers={"Host": "localhost:5001"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<!DOCTYPE html>", response.data)

    def test_packaged_windows_current_server_counts_as_installed_for_fresh_user(self):
        with patch.object(install_state_module, "get_runtime_state", return_value=None), \
             patch.object(server_module.sys, "platform", "win32"), \
             patch.object(server_module.sys, "frozen", True, create=True), \
             patch.object(server_module, "ACTUAL_PORT", 5000):
            response = self.client.get("/", headers={"Host": "localhost:5000"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<!DOCTYPE html>", response.data)

    def test_packaged_windows_other_port_does_not_count_as_installed_for_fresh_user(self):
        with patch.object(install_state_module, "get_runtime_state", return_value=None), \
             patch.object(server_module.sys, "platform", "win32"), \
             patch.object(server_module.sys, "frozen", True, create=True), \
             patch.object(server_module, "ACTUAL_PORT", 5000):
            response = self.client.get("/", headers={"Host": "localhost:5001"}, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/install")

    def test_dashboard_allows_degraded_extension_case_via_runtime(self):
        with patch.object(install_state_module, "get_runtime_state", return_value={"port": 5001, "pid": 123}):
            response = self.client.get("/", headers={"Host": "localhost:5001"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"/install", response.headers.get("Location", "").encode())

    def test_dashboard_redirects_when_not_installed(self):
        with patch.object(install_state_module, "get_runtime_state", return_value=None):
            response = self.client.get("/", headers={"Host": "localhost:5001"}, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/install")

    def test_installer_route_serves_packaged_internal_data_path(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-packaged-install-") as temp_dir:
            app_dir = Path(temp_dir)
            installer_html = app_dir / "_internal" / "data" / "installer.html"
            installer_html.parent.mkdir(parents=True, exist_ok=True)
            installer_html.write_text("<!DOCTYPE html><title>Installer</title>", encoding="utf-8")

            with patch.object(installer_module, "_installer_html_candidates", return_value=[installer_html]), \
                 patch.object(installer_module, "_write_installer_discovery_diagnostics"):
                response = self.client.get("/install", headers={"Host": "localhost:5001"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<title>Installer</title>", response.data)

    def test_installer_discovery_diagnostics_print_checked_paths(self):
        existing_path = self.data_dir / "installer.html"
        missing_path = self.data_dir / "missing.html"
        existing_path.write_text("<!DOCTYPE html>", encoding="utf-8")
        stderr = io.StringIO()

        with patch.object(installer_module.sys, "executable", str(self.data_dir / "FixOnce.exe")), \
             patch.object(installer_module.sys, "stderr", stderr):
            installer_module._write_installer_discovery_diagnostics([existing_path, missing_path])

        output = stderr.getvalue()
        self.assertIn("sys.executable=", output)
        self.assertIn("__file__=", output)
        self.assertIn("resolved_app_directory=", output)
        self.assertIn("installer_html_paths_checked:", output)
        self.assertIn(f"{existing_path} exists=True", output)
        self.assertIn(f"{missing_path} exists=False", output)
        self.assertIn("installer_entrypoint_paths_checked:", output)

    def test_dashboard_does_not_redirect_when_legacy_install_state_is_installed(self):
        (self.data_dir / "install_state.json").write_text(json.dumps({
            "installed": True,
            "version": "1.0.12",
            "installer": "cli",
        }), encoding="utf-8")

        with patch.object(install_state_module, "get_runtime_state", return_value=None):
            response = self.client.get("/", headers={"Host": "localhost:5001"}, follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.headers.get("Location"), "/install")
        self.assertIn(b"<!DOCTYPE html>", response.data)

    def test_installer_status_uses_runtime_on_dynamic_port(self):
        with patch.object(install_state_module, "get_runtime_state", return_value={"port": 5001, "pid": 123}):
            response = self.client.get("/api/installer/status", headers={"Host": "localhost:5001"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "installed": True,
                "state": "READY",
                "detail": "Canonical runtime is healthy",
                "runtime_port": 5001,
                "runtime_pid": 123,
                "metadata": {},
            },
        )

    def test_installer_status_includes_defender_failure_metadata(self):
        install_state_module.mark_install_state(
            InstallState.FAILED,
            data_dir=self.data_dir,
            detail="Windows Defender appears to have blocked FixOnce.exe.",
            metadata={
                "defender_diagnostics": {
                    "blocked_likely": True,
                    "disposition": "quarantined_or_deleted",
                }
            },
        )

        with patch.object(install_state_module, "get_runtime_state", return_value=None):
            response = self.client.get("/api/installer/status", headers={"Host": "localhost:5001"})

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["state"], "FAILED")
        self.assertTrue(payload["metadata"]["defender_diagnostics"]["blocked_likely"])
        self.assertEqual(payload["metadata"]["defender_diagnostics"]["disposition"], "quarantined_or_deleted")

    def test_installer_status_rejects_runtime_from_other_port(self):
        with patch.object(install_state_module, "get_runtime_state", return_value={"port": 5002, "pid": 123}):
            response = self.client.get("/api/installer/status", headers={"Host": "localhost:5001"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["installed"], False)
        self.assertEqual(response.get_json()["state"], "NOT_INSTALLED")

    def test_ready_install_state_stays_installed_without_runtime(self):
        install_state_module.mark_install_state(
            InstallState.READY,
            data_dir=self.data_dir,
            detail="Previous install finished",
        )

        with patch.object(install_state_module, "get_runtime_state", return_value=None):
            snapshot = install_state_module.get_install_snapshot(request_port=5001, data_dir=self.data_dir)

        self.assertEqual(snapshot.state, InstallState.READY)
        self.assertTrue(snapshot.installed)

    def test_active_install_flow_can_show_starting_without_runtime(self):
        install_state_module.mark_install_state(
            InstallState.READY,
            data_dir=self.data_dir,
            detail="Runtime startup in progress",
            metadata={"active_install_flow": True},
        )

        with patch.object(install_state_module, "get_runtime_state", return_value=None):
            snapshot = install_state_module.get_install_snapshot(request_port=5001, data_dir=self.data_dir)

        self.assertEqual(snapshot.state, InstallState.STARTING)
        self.assertFalse(snapshot.installed)

    def test_install_state_file_still_counts_as_installed(self):
        install_state_module.mark_install_state(
            InstallState.READY,
            data_dir=self.data_dir,
            detail="Install completed",
        )

        with patch.object(install_state_module, "get_runtime_state", return_value={"port": 5001, "pid": 321}):
            response = self.client.get("/", headers={"Host": "localhost:5001"})

        self.assertEqual(response.status_code, 200)

    def test_installer_configure_mcp_writes_json_clients(self):
        temp_home_dir = tempfile.TemporaryDirectory(prefix="fixonce-installer-home-")
        temp_home = Path(temp_home_dir.name)

        def fake_run(cmd, capture_output=False, text=False, timeout=None):
            class Result:
                returncode = 1
                stdout = ""
                stderr = ""
            return Result()

        try:
            with patch("pathlib.Path.home", return_value=temp_home), \
                 patch.object(installer_module.subprocess, "run", side_effect=fake_run):
                response = self.client.post("/api/installer/configure-mcp")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["status"], "ok")
            self.assertIn("Claude Code", payload["configured"])
            self.assertIn("Cursor", payload["configured"])
            self.assertIn("Windsurf", payload["configured"])

            claude_config = json.loads((temp_home / ".claude.json").read_text(encoding="utf-8"))
            cursor_config = json.loads((temp_home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            windsurf_config = json.loads((temp_home / ".codeium" / "windsurf" / "mcp_config.json").read_text(encoding="utf-8"))

            self.assertIn("fixonce", claude_config["mcpServers"])
            self.assertIn("fixonce", cursor_config["mcpServers"])
            self.assertIn("fixonce", windsurf_config["mcpServers"])
        finally:
            temp_home_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
