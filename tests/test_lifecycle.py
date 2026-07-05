"""
Test FixOnce lifecycle management.

Tests for BUG-000: Lifecycle/stale-server issue.

Ensures:
- Quit action stops Flask server, not just menu bar
- Stale servers from old installs are detected and terminated
- Current install servers are NOT terminated
- User data is NOT deleted
- Only FixOnce-owned processes are affected
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestLifecycleModuleExists:
    """Test that lifecycle module exists and has required functions."""

    def test_module_imports(self):
        """Lifecycle module should be importable."""
        from core.lifecycle import (
            shutdown_fixonce,
            terminate_server_by_runtime,
            ensure_no_stale_servers,
            find_stale_server_port,
            is_pid_running,
            terminate_process,
        )
        assert callable(shutdown_fixonce)
        assert callable(terminate_server_by_runtime)
        assert callable(ensure_no_stale_servers)
        assert callable(find_stale_server_port)

    def test_read_runtime_state(self):
        """Should read runtime state from file."""
        from core.lifecycle import read_runtime_state

        mock_runtime = {"port": 5000, "pid": 12345, "install_path": "/test/path"}

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps(mock_runtime)):
                state = read_runtime_state()

        assert state.get("port") == 5000
        assert state.get("pid") == 12345


class TestIsPidRunning:
    """Test PID running detection."""

    def test_returns_false_for_invalid_pid(self):
        """Should return False for obviously invalid PIDs."""
        from core.lifecycle import is_pid_running

        # PID 0 or negative should never be treated as a process.
        assert is_pid_running(0) is False
        assert is_pid_running(-1) is False

    def test_negative_pid_does_not_call_os_kill(self):
        """PID -1 must not reach os.kill because it can signal all processes."""
        from core.lifecycle import is_pid_running

        with patch("core.lifecycle.os.kill") as mock_kill:
            assert is_pid_running(-1) is False
            mock_kill.assert_not_called()

    def test_returns_true_for_current_process(self):
        """Should return True for current process PID."""
        from core.lifecycle import is_pid_running

        current_pid = os.getpid()
        assert is_pid_running(current_pid) is True


class TestTerminateProcess:
    """Test process termination."""

    def test_returns_true_for_dead_process(self):
        """Should return True when process is already dead."""
        from core.lifecycle import terminate_process

        # Use a very high PID that's unlikely to exist
        result = terminate_process(999999999)
        assert result is True

    def test_does_not_crash_on_invalid_pid(self):
        """Should not crash when given invalid PID."""
        from core.lifecycle import terminate_process

        # Should handle gracefully
        result = terminate_process(-1)
        assert result is True  # Already dead

    def test_negative_pid_does_not_call_os_kill(self):
        """terminate_process(-1) must return without signaling anything."""
        from core.lifecycle import terminate_process

        with patch("core.lifecycle.os.kill") as mock_kill:
            result = terminate_process(-1)

        assert result is True
        mock_kill.assert_not_called()


class TestShutdownFixonce:
    """Test shutdown_fixonce function."""

    def test_returns_true_when_no_server(self):
        """Should return True when no server is running."""
        from core.lifecycle import shutdown_fixonce

        with patch("core.lifecycle.read_runtime_state", return_value={}):
            result = shutdown_fixonce()
        assert result is True

    def test_reads_runtime_for_pid(self):
        """Should read runtime.json to get server PID."""
        from core.lifecycle import shutdown_fixonce

        mock_runtime = {"port": 5000, "pid": 99999999}

        with patch("core.lifecycle.read_runtime_state", return_value=mock_runtime):
            with patch("core.lifecycle.is_pid_running", return_value=False):
                result = shutdown_fixonce()

        assert result is True

    def test_runtime_negative_pid_is_ignored_without_signal(self):
        """runtime.json pid -1 must not be considered a kill target."""
        from core.lifecycle import terminate_server_by_runtime

        with tempfile.TemporaryDirectory(prefix="fixonce-lifecycle-") as temp_dir:
            runtime_file = Path(temp_dir) / "runtime.json"
            runtime_file.write_text(json.dumps({"port": 5000, "pid": -1}), encoding="utf-8")

            with patch("core.lifecycle.RUNTIME_FILE", runtime_file), \
                 patch("core.lifecycle.os.kill") as mock_kill, \
                 patch("core.lifecycle._request_graceful_shutdown") as mock_shutdown:
                result = terminate_server_by_runtime()

            assert result is True
            mock_kill.assert_not_called()
            mock_shutdown.assert_not_called()
            assert not runtime_file.exists()

    def test_malformed_runtime_json_is_ignored_without_signal(self):
        """Non-object runtime.json cannot feed an unsafe PID into shutdown."""
        from core.lifecycle import terminate_server_by_runtime

        with tempfile.TemporaryDirectory(prefix="fixonce-lifecycle-") as temp_dir:
            runtime_file = Path(temp_dir) / "runtime.json"
            runtime_file.write_text(json.dumps([{"pid": -1, "port": 5000}]), encoding="utf-8")

            with patch("core.lifecycle.RUNTIME_FILE", runtime_file), \
                 patch("core.lifecycle.os.kill") as mock_kill, \
                 patch("core.lifecycle._request_graceful_shutdown") as mock_shutdown:
                result = terminate_server_by_runtime()

            assert result is True
            mock_kill.assert_not_called()
            mock_shutdown.assert_not_called()

    def test_stale_runtime_negative_pid_is_cleaned_safely(self):
        """A stale runtime with pid -1 should be removed without process signals."""
        from core.lifecycle import shutdown_fixonce

        with tempfile.TemporaryDirectory(prefix="fixonce-lifecycle-") as temp_dir:
            runtime_file = Path(temp_dir) / "runtime.json"
            lock_file = Path(temp_dir) / "server.lock"
            runtime_file.write_text(json.dumps({"port": 5000, "pid": -1}), encoding="utf-8")

            with patch("core.lifecycle.RUNTIME_FILE", runtime_file), \
                 patch("core.lifecycle.LOCK_FILE", lock_file), \
                 patch("core.lifecycle.os.kill") as mock_kill:
                result = shutdown_fixonce()

            assert result is True
            mock_kill.assert_not_called()
            assert not runtime_file.exists()

    def test_cleans_up_lock_file(self):
        """Should clean up server.lock file."""
        from core.lifecycle import shutdown_fixonce

        with tempfile.TemporaryDirectory(prefix="fixonce-lifecycle-") as temp_dir:
            lock_file = Path(temp_dir) / "server.lock"
            lock_file.write_text("12345", encoding="utf-8")

            with patch("core.lifecycle.read_runtime_state", return_value={}), \
                 patch("core.lifecycle.LOCK_FILE", lock_file):
                shutdown_fixonce()

            assert not lock_file.exists()


class TestFindStaleServerPort:
    """Test stale server detection."""

    def test_returns_none_when_no_server(self):
        """Should return None when no server is running."""
        from core.lifecycle import find_stale_server_port

        current_install = Path("/Users/test/FixOnce")

        with patch("core.lifecycle.read_runtime_state", return_value={}):
            with patch("core.lifecycle._get_ping_payload", return_value={}):
                result = find_stale_server_port(current_install)

        assert result is None

    def test_returns_none_for_current_install_server(self):
        """Should return None if server matches current install."""
        from core.lifecycle import find_stale_server_port

        current_install = Path("/Users/test/FixOnce")

        mock_runtime = {"port": 5000, "pid": 12345}
        mock_ping = {
            "service": "fixonce",
            "install_path": "/Users/test/FixOnce"
        }

        with patch("core.lifecycle.read_runtime_state", return_value=mock_runtime):
            with patch("core.lifecycle.is_pid_running", return_value=True):
                with patch("core.lifecycle._get_ping_payload", return_value=mock_ping):
                    result = find_stale_server_port(current_install)

        assert result is None

    def test_returns_port_pid_for_stale_server(self):
        """Should return (port, pid) for server from different install."""
        from core.lifecycle import find_stale_server_port

        current_install = Path("/Users/test/FixOnce")

        mock_runtime = {"port": 5000, "pid": 12345}
        mock_ping = {
            "service": "fixonce",
            "install_path": "/Users/test/Downloads/FixOnce-old"  # Different path
        }

        with patch("core.lifecycle.read_runtime_state", return_value=mock_runtime):
            with patch("core.lifecycle.is_pid_running", return_value=True):
                with patch("core.lifecycle._get_ping_payload", return_value=mock_ping):
                    result = find_stale_server_port(current_install)

        assert result is not None
        assert result[0] == 5000  # port
        assert result[1] == 12345  # pid


class TestTerminateStaleServers:
    """Test stale server termination."""

    def test_returns_zero_when_no_stale_servers(self):
        """Should return 0 when no stale servers found."""
        from core.lifecycle import terminate_stale_servers

        current_install = Path("/Users/test/FixOnce")

        with patch("core.lifecycle.find_stale_server_port", return_value=None):
            count = terminate_stale_servers(current_install)

        assert count == 0

    def test_terminates_stale_server(self):
        """Should terminate stale server and return count."""
        from core.lifecycle import terminate_stale_servers

        current_install = Path("/Users/test/FixOnce")

        # First call returns stale server, second returns None (no more)
        find_results = [(5000, 12345), None]
        find_idx = [0]

        def mock_find(*args):
            result = find_results[find_idx[0]]
            if find_idx[0] < len(find_results) - 1:
                find_idx[0] += 1
            return result

        with patch("core.lifecycle.find_stale_server_port", side_effect=mock_find):
            with patch("core.lifecycle._request_graceful_shutdown", return_value=False):
                with patch("core.lifecycle.terminate_process", return_value=True):
                    with patch("core.lifecycle.read_runtime_state", return_value={}):
                        count = terminate_stale_servers(current_install)

        assert count == 1


class TestEnsureNoStaleServers:
    """Test ensure_no_stale_servers function."""

    def test_calls_terminate_stale_servers(self):
        """Should call terminate_stale_servers with current install path."""
        from core.lifecycle import ensure_no_stale_servers

        current_install = Path("/Users/test/FixOnce")

        with patch("core.lifecycle.terminate_stale_servers", return_value=0) as mock_term:
            ensure_no_stale_servers(current_install)
            mock_term.assert_called_once_with(current_install)


class TestMenuBarQuitCallsShutdown:
    """Test that menu bar quit action calls shutdown."""

    def test_menubar_quit_imports_lifecycle(self):
        """Menu bar _quit_app should import and call lifecycle shutdown."""
        menubar_path = Path(__file__).parent.parent / "scripts" / "menubar_app.py"
        source = menubar_path.read_text()

        # Find the _quit_app method
        quit_start = source.find("def _quit_app(self, _):")
        quit_end = source.find("\n    def ", quit_start + 1)
        if quit_end == -1:
            quit_end = source.find("\n\n\ndef ", quit_start + 1)
        quit_body = source[quit_start:quit_end]

        assert "shutdown_fixonce" in quit_body, \
            "_quit_app should call shutdown_fixonce"

    def test_menubar_has_path_setup(self):
        """Menu bar should add src to path for lifecycle import."""
        menubar_path = Path(__file__).parent.parent / "scripts" / "menubar_app.py"
        source = menubar_path.read_text()

        assert "SERVER_DIR" in source, "Should define SERVER_DIR"
        assert "sys.path.insert" in source, "Should add path for imports"


class TestWindowsTrayQuitCallsShutdown:
    """Test that Windows tray quit action calls shutdown."""

    def test_tray_quit_imports_lifecycle(self):
        """Windows tray _quit_app should import and call lifecycle shutdown."""
        tray_path = Path(__file__).parent.parent / "scripts" / "tray_app_windows.py"
        source = tray_path.read_text()

        # Find the _quit_app method
        quit_start = source.find("def _quit_app(self, icon=None, item=None):")
        quit_end = source.find("\n    def ", quit_start + 1)
        if quit_end == -1:
            quit_end = source.find("\n\n\ndef ", quit_start + 1)
        quit_body = source[quit_start:quit_end]

        assert "shutdown_fixonce" in quit_body, \
            "_quit_app should call shutdown_fixonce"


class TestAppLauncherStaleServerCheck:
    """Test that app launcher checks for stale servers."""

    def test_ensure_server_ready_calls_stale_check(self):
        """ensure_server_ready should call ensure_no_stale_servers."""
        launcher_path = Path(__file__).parent.parent / "scripts" / "app_launcher.py"
        source = launcher_path.read_text()

        # Find ensure_server_ready function
        func_start = source.find("def ensure_server_ready(")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        assert "ensure_no_stale_servers" in func_body, \
            "ensure_server_ready should call ensure_no_stale_servers"


class TestSafetyGuards:
    """Test that lifecycle operations are safe."""

    def test_does_not_delete_user_data(self):
        """Lifecycle module should never delete user memory data."""
        from core.lifecycle import shutdown_fixonce

        # Check that shutdown_fixonce doesn't delete data files
        import inspect
        source = inspect.getsource(shutdown_fixonce)

        # Should not contain file deletion patterns for data
        dangerous_patterns = [
            "shutil.rmtree",
            "data/",
            ".fixonce/projects",
            "insights.json",
            "decisions",
            "solutions",
        ]

        for pattern in dangerous_patterns:
            assert pattern not in source, \
                f"shutdown_fixonce should not contain '{pattern}'"

    def test_only_cleans_runtime_files(self):
        """Should only clean runtime.json and server.lock."""
        from core.lifecycle import shutdown_fixonce
        import inspect
        source = inspect.getsource(shutdown_fixonce)

        # May reference LOCK_FILE cleanup but not other files
        allowed_files = ["runtime", "lock", "log"]

        # If unlink is used, it should only be for runtime/lock files
        # This is a heuristic check
        if ".unlink" in source:
            for line in source.split("\n"):
                if ".unlink" in line:
                    assert any(f in line.lower() for f in allowed_files), \
                        f"Suspicious unlink call: {line}"


class TestLogFileCreation:
    """Test lifecycle logging."""

    def test_log_lifecycle_creates_log_dir(self):
        """_log_lifecycle should create log directory if needed."""
        from core.lifecycle import _log_lifecycle, USER_DATA_DIR

        with patch.object(Path, "mkdir") as mock_mkdir:
            with patch("builtins.open", mock_open()):
                _log_lifecycle("test message")
                # Should have called mkdir
