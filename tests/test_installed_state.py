import importlib
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

    def test_installer_status_uses_runtime_on_dynamic_port(self):
        with patch.object(install_state_module, "get_runtime_state", return_value={"port": 5001, "pid": 123}):
            response = self.client.get("/api/installer/status", headers={"Host": "localhost:5001"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"installed": True, "state": "READY", "detail": "Canonical runtime is healthy", "runtime_port": 5001},
        )

    def test_installer_status_rejects_runtime_from_other_port(self):
        with patch.object(install_state_module, "get_runtime_state", return_value={"port": 5002, "pid": 123}):
            response = self.client.get("/api/installer/status", headers={"Host": "localhost:5001"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["installed"], False)
        self.assertEqual(response.get_json()["state"], "NOT_INSTALLED")

    def test_ready_install_state_transitions_to_starting_without_runtime(self):
        install_state_module.mark_install_state(
            InstallState.READY,
            data_dir=self.data_dir,
            detail="Previous install finished",
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


if __name__ == "__main__":
    unittest.main()
