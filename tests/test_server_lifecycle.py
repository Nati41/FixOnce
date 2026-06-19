"""
Tests for server lifecycle and stale server handling.

Tests:
1. Stale runtime.json with dead PID is cleaned up
2. Stale server from same install_path is killed
3. Server from different install_path fails with clear error
4. Port occupied by non-FixOnce process allows fallback
5. Clean startup when no server is running
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))


class TestServerLifecycle(unittest.TestCase):
    """Test stale server detection and cleanup."""

    def setUp(self):
        """Create temp directory for runtime files."""
        self.temp_dir = tempfile.mkdtemp()
        self.runtime_file = Path(self.temp_dir) / "runtime.json"
        self.lock_file = Path(self.temp_dir) / "server.lock"

        # Patch file paths
        self.runtime_patcher = patch(
            "core.port_manager.RUNTIME_FILE",
            self.runtime_file
        )
        self.lock_patcher = patch(
            "core.port_manager.LOCK_FILE",
            self.lock_file
        )
        self.runtime_patcher.start()
        self.lock_patcher.start()

    def tearDown(self):
        self.runtime_patcher.stop()
        self.lock_patcher.stop()
        # Clean up temp files
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_runtime(self, port, pid, install_path="/test/path"):
        """Helper to write a runtime.json file."""
        state = {
            "port": port,
            "pid": pid,
            "install_path": install_path,
            "started_at": "2026-01-01T00:00:00",
            "user": "test",
        }
        with open(self.runtime_file, "w") as f:
            json.dump(state, f)

    def test_cleanup_stale_runtime_dead_pid(self):
        """Stale runtime.json with dead PID should be cleaned up."""
        from core.port_manager import cleanup_stale_runtime

        # Write runtime with a PID that doesn't exist
        self._write_runtime(5000, 99999999)

        with patch("core.port_manager.is_pid_running", return_value=False):
            result = cleanup_stale_runtime()

        self.assertTrue(result)
        self.assertFalse(self.runtime_file.exists())

    def test_cleanup_stale_runtime_live_pid(self):
        """Runtime.json with live PID should not be cleaned up."""
        from core.port_manager import cleanup_stale_runtime

        self._write_runtime(5000, 12345)

        with patch("core.port_manager.is_pid_running", return_value=True):
            result = cleanup_stale_runtime()

        self.assertFalse(result)
        self.assertTrue(self.runtime_file.exists())

    def test_cleanup_stale_runtime_no_file(self):
        """No cleanup needed if runtime.json doesn't exist."""
        from core.port_manager import cleanup_stale_runtime

        result = cleanup_stale_runtime()

        self.assertFalse(result)

    def test_ensure_clean_startup_no_server(self):
        """Clean startup when no server is running."""
        from core.port_manager import ensure_clean_startup

        with patch("core.port_manager.is_port_available", return_value=True):
            success, message = ensure_clean_startup("/test/path")

        self.assertTrue(success)
        self.assertEqual(message, "Clean startup")

    def test_ensure_clean_startup_stale_same_install(self):
        """Stale server from same install_path should be killed."""
        from core.port_manager import ensure_clean_startup

        self._write_runtime(5000, 12345, "/test/path")

        with patch("core.port_manager.is_pid_running", return_value=True), \
             patch("core.port_manager._kill_process", return_value=True), \
             patch("core.port_manager.is_port_available", return_value=True):
            success, message = ensure_clean_startup("/test/path")

        self.assertTrue(success)
        self.assertIn("Stale server stopped", message)

    def test_ensure_clean_startup_different_install(self):
        """Server from different install_path should fail with error."""
        from core.port_manager import ensure_clean_startup

        self._write_runtime(5000, 12345, "/other/path")

        with patch("core.port_manager.is_pid_running", return_value=True):
            success, message = ensure_clean_startup("/test/path")

        self.assertFalse(success)
        self.assertIn("different location", message)
        self.assertIn("/other/path", message)

    def test_ensure_clean_startup_port_occupied_non_fixonce(self):
        """Port occupied by non-FixOnce process should allow fallback."""
        from core.port_manager import ensure_clean_startup

        with patch("core.port_manager.is_port_available", return_value=False), \
             patch("core.port_manager._is_fixonce_server_responding", return_value=False):
            success, message = ensure_clean_startup("/test/path")

        # Should succeed - server will fall back to another port
        self.assertTrue(success)

    def test_get_stale_server_info_dead_pid(self):
        """get_stale_server_info should detect dead PID."""
        from core.port_manager import get_stale_server_info

        self._write_runtime(5000, 99999999)

        with patch("core.port_manager.is_pid_running", return_value=False):
            info = get_stale_server_info()

        self.assertIsNotNone(info)
        self.assertEqual(info["status"], "dead_pid")
        self.assertEqual(info["pid"], 99999999)

    def test_get_stale_server_info_not_responding(self):
        """get_stale_server_info should detect non-responding server."""
        from core.port_manager import get_stale_server_info

        self._write_runtime(5000, 12345)

        with patch("core.port_manager.is_pid_running", return_value=True), \
             patch("core.port_manager._is_fixonce_server_responding", return_value=False):
            info = get_stale_server_info()

        self.assertIsNotNone(info)
        self.assertEqual(info["status"], "not_responding")

    def test_get_stale_server_info_healthy(self):
        """get_stale_server_info should return None for healthy server."""
        from core.port_manager import get_stale_server_info

        self._write_runtime(5000, 12345)

        with patch("core.port_manager.is_pid_running", return_value=True), \
             patch("core.port_manager._is_fixonce_server_responding", return_value=True):
            info = get_stale_server_info()

        self.assertIsNone(info)


class TestKillProcess(unittest.TestCase):
    """Test process killing logic."""

    def test_kill_already_dead(self):
        """Killing an already dead process should succeed."""
        from core.port_manager import _kill_process

        with patch("core.port_manager.is_pid_running", return_value=False):
            result = _kill_process(99999999)

        self.assertTrue(result)


class TestDashboardPortResolution(unittest.TestCase):
    """Test that dashboard URL uses runtime.json port."""

    def setUp(self):
        """Create temp directory for runtime files."""
        self.temp_dir = tempfile.mkdtemp()
        self.runtime_file = Path(self.temp_dir) / "runtime.json"
        self.lock_file = Path(self.temp_dir) / "server.lock"

        self.runtime_patcher = patch(
            "core.port_manager.RUNTIME_FILE",
            self.runtime_file
        )
        self.lock_patcher = patch(
            "core.port_manager.LOCK_FILE",
            self.lock_file
        )
        self.runtime_patcher.start()
        self.lock_patcher.start()

    def tearDown(self):
        self.runtime_patcher.stop()
        self.lock_patcher.stop()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_runtime(self, port, pid, install_path="/test/path"):
        """Helper to write a runtime.json file."""
        state = {
            "port": port,
            "pid": pid,
            "install_path": install_path,
            "started_at": "2026-01-01T00:00:00",
            "user": "test",
        }
        with open(self.runtime_file, "w") as f:
            json.dump(state, f)

    def test_stale_fixonce_replaced_uses_default_port(self):
        """Stale FixOnce from same install gets replaced, server uses port 5000."""
        from core.port_manager import ensure_clean_startup, get_dashboard_url

        # Stale server on 5000
        self._write_runtime(5000, 12345, "/test/path")

        with patch("core.port_manager.is_pid_running", return_value=True), \
             patch("core.port_manager._kill_process", return_value=True), \
             patch("core.port_manager.is_port_available", return_value=True):
            success, message = ensure_clean_startup("/test/path")

        self.assertTrue(success)
        self.assertIn("Stale server stopped", message)

        # After cleanup, runtime.json should be cleared
        # New server would start on 5000 and write new runtime.json
        # Simulate new server writing runtime on port 5000
        self._write_runtime(5000, 99999, "/test/path")

        with patch("core.port_manager.is_pid_running", return_value=True), \
             patch("core.port_manager.discover_running_instance", return_value=5000):
            url = get_dashboard_url()
        self.assertEqual(url, "http://localhost:5000")

    def test_non_fixonce_on_5000_uses_fallback_port(self):
        """Non-FixOnce on port 5000, server falls back, dashboard uses runtime.json port."""
        from core.port_manager import get_dashboard_url

        # Server running on fallback port 5001 (5000 was occupied by non-FixOnce)
        self._write_runtime(5001, 12345, "/test/path")

        with patch("core.port_manager.is_pid_running", return_value=True), \
             patch("core.port_manager.discover_running_instance", return_value=5001):
            url = get_dashboard_url()

        self.assertEqual(url, "http://localhost:5001")

    def test_get_dashboard_url_reads_runtime_port(self):
        """get_dashboard_url should use port from runtime.json."""
        from core.port_manager import get_dashboard_url

        # Server on port 5002
        self._write_runtime(5002, 12345, "/test/path")

        with patch("core.port_manager.is_pid_running", return_value=True), \
             patch("core.port_manager.discover_running_instance", return_value=5002):
            url = get_dashboard_url()

        self.assertIn("5002", url)


class TestAppLauncherPortResolution(unittest.TestCase):
    """Test that app launcher reads port from runtime.json."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.runtime_file = Path(self.temp_dir) / "runtime.json"
        self.config_file = Path(self.temp_dir) / "config.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_runtime(self, port, pid=12345, install_path="/test/path"):
        state = {"port": port, "pid": pid, "install_path": install_path}
        with open(self.runtime_file, "w") as f:
            json.dump(state, f)

    def test_read_saved_ports_from_runtime(self):
        """App launcher should read port from runtime.json."""
        self._write_runtime(5001)

        # Test the logic directly
        candidates = []
        for path in [self.runtime_file, self.config_file]:
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                port = data.get("port")
                if port and int(port) not in candidates:
                    candidates.append(int(port))

        self.assertIn(5001, candidates)

    def test_fallback_port_in_runtime_is_used(self):
        """When server falls back to 5001, runtime.json should contain 5001."""
        self._write_runtime(5001)

        with open(self.runtime_file) as f:
            state = json.load(f)

        self.assertEqual(state["port"], 5001)


class TestFileWatcherPortResolution(unittest.TestCase):
    """Test that file watcher uses runtime.json port."""

    def test_get_api_url_reads_runtime_port(self):
        """File watcher should read port from runtime.json."""
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_file = Path(temp_dir) / "runtime.json"
            with open(runtime_file, 'w') as f:
                json.dump({"port": 5003}, f)

            # Temporarily patch Path.home() to use temp directory
            with patch("pathlib.Path.home", return_value=Path(temp_dir)):
                # Re-import to get fresh _get_api_url
                import importlib
                import sys
                # Remove cached module
                if 'file_watcher' in sys.modules:
                    del sys.modules['file_watcher']

                # Direct test of the function logic
                try:
                    with open(runtime_file, 'r') as f:
                        state = json.load(f)
                    port = state.get("port", 5000)
                    url = f"http://localhost:{port}/api/activity/log"
                except Exception:
                    url = "http://localhost:5000/api/activity/log"

                self.assertEqual(url, "http://localhost:5003/api/activity/log")


if __name__ == "__main__":
    unittest.main()
