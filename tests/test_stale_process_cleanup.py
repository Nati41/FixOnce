"""
Test stale FixOnce process cleanup during reinstall.

Ensures:
- Stale processes from old install paths are killed
- Current install processes are NOT killed
- Only FixOnce scripts are targeted
- Only current user processes are affected
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestStaleProcessCleanup:
    """Test _kill_stale_fixonce_processes function."""

    def test_function_exists(self):
        """_kill_stale_fixonce_processes should exist."""
        from install import _kill_stale_fixonce_processes
        assert callable(_kill_stale_fixonce_processes)

    def test_kills_old_menubar_process(self):
        """Should kill menubar_app.py from old install path."""
        from install import _kill_stale_fixonce_processes

        current_dir = Path("/Users/testuser/FixOnce")
        old_path = "/Users/testuser/Downloads/FixOnce-main"

        # Mock ps output with stale process
        ps_output = f"""  PID COMMAND
12345 /usr/bin/python3 {old_path}/scripts/menubar_app.py
"""
        killed_pids = []

        def mock_kill(pid, sig):
            killed_pids.append(pid)

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ps_output
            return result

        with patch('install.subprocess.run', mock_run):
            with patch('os.kill', mock_kill):
                with patch.dict(os.environ, {"USER": "testuser"}):
                    result = _kill_stale_fixonce_processes(current_dir)

        assert 12345 in killed_pids, f"Should kill PID 12345, killed: {killed_pids}"

    def test_kills_old_server_process(self):
        """Should kill server.py from old install path."""
        from install import _kill_stale_fixonce_processes

        current_dir = Path("/Users/testuser/FixOnce")

        ps_output = """  PID COMMAND
12346 /usr/bin/python3 /Users/testuser/Downloads/FixOnce-main/src/server.py --flask-only
"""
        killed_pids = []

        def mock_kill(pid, sig):
            killed_pids.append(pid)

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ps_output
            return result

        with patch('install.subprocess.run', mock_run):
            with patch('os.kill', mock_kill):
                with patch.dict(os.environ, {"USER": "testuser"}):
                    result = _kill_stale_fixonce_processes(current_dir)

        assert 12346 in killed_pids, "Should kill server.py from old path"

    def test_does_not_kill_current_install_process(self):
        """Should NOT kill processes from current install directory."""
        from install import _kill_stale_fixonce_processes

        current_dir = Path("/Users/testuser/FixOnce")

        # Process is from CURRENT install path
        ps_output = """  PID COMMAND
12347 /usr/bin/python3 /Users/testuser/FixOnce/scripts/menubar_app.py
"""
        killed_pids = []

        def mock_kill(pid, sig):
            killed_pids.append(pid)

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ps_output
            return result

        with patch('install.subprocess.run', mock_run):
            with patch('os.kill', mock_kill):
                with patch.dict(os.environ, {"USER": "testuser"}):
                    result = _kill_stale_fixonce_processes(current_dir)

        assert 12347 not in killed_pids, "Should NOT kill process from current install"

    def test_does_not_kill_unrelated_python_process(self):
        """Should NOT kill Python processes that aren't FixOnce scripts."""
        from install import _kill_stale_fixonce_processes

        current_dir = Path("/Users/testuser/FixOnce")

        # Unrelated Python process
        ps_output = """  PID COMMAND
12348 /usr/bin/python3 /Users/testuser/some_other_app/main.py
"""
        killed_pids = []

        def mock_kill(pid, sig):
            killed_pids.append(pid)

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ps_output
            return result

        with patch('install.subprocess.run', mock_run):
            with patch('os.kill', mock_kill):
                with patch.dict(os.environ, {"USER": "testuser"}):
                    result = _kill_stale_fixonce_processes(current_dir)

        assert 12348 not in killed_pids, "Should NOT kill unrelated Python process"

    def test_case_insensitive_path_matching(self):
        """Should match FixOnce path case-insensitively."""
        from install import _kill_stale_fixonce_processes

        current_dir = Path("/Users/testuser/FixOnce")

        # Process path has different case
        ps_output = """  PID COMMAND
12349 /usr/bin/python3 /Users/testuser/Downloads/FIXONCE-main/scripts/menubar_app.py
"""
        killed_pids = []

        def mock_kill(pid, sig):
            killed_pids.append(pid)

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ps_output
            return result

        with patch('install.subprocess.run', mock_run):
            with patch('os.kill', mock_kill):
                with patch.dict(os.environ, {"USER": "testuser"}):
                    result = _kill_stale_fixonce_processes(current_dir)

        assert 12349 in killed_pids, "Should match FixOnce case-insensitively"

    def test_kills_app_launcher_process(self):
        """Should kill app_launcher.py from old install path."""
        from install import _kill_stale_fixonce_processes

        current_dir = Path("/Users/testuser/FixOnce")

        ps_output = """  PID COMMAND
12350 /usr/bin/python3 /Users/testuser/Downloads/FixOnce-main/scripts/app_launcher.py --dashboard
"""
        killed_pids = []

        def mock_kill(pid, sig):
            killed_pids.append(pid)

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ps_output
            return result

        with patch('install.subprocess.run', mock_run):
            with patch('os.kill', mock_kill):
                with patch.dict(os.environ, {"USER": "testuser"}):
                    result = _kill_stale_fixonce_processes(current_dir)

        assert 12350 in killed_pids, "Should kill app_launcher.py from old path"


class TestCleanupCallsProcessKill:
    """Test that _cleanup_stale_launchagents calls process cleanup."""

    def test_cleanup_calls_process_killer(self):
        """_cleanup_stale_launchagents should call _kill_stale_fixonce_processes."""
        install_path = Path(__file__).parent.parent / "scripts" / "install.py"
        source = install_path.read_text()

        func_start = source.find("def _cleanup_stale_launchagents")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        assert "_kill_stale_fixonce_processes" in func_body, \
            "_cleanup_stale_launchagents should call _kill_stale_fixonce_processes"

    def test_process_kill_before_launchctl_unload(self):
        """Process killing should happen before launchctl unload."""
        install_path = Path(__file__).parent.parent / "scripts" / "install.py"
        source = install_path.read_text()

        func_start = source.find("def _cleanup_stale_launchagents")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        kill_idx = func_body.find("_kill_stale_fixonce_processes")
        unload_idx = func_body.find("launchctl', 'unload'")

        assert kill_idx > 0, "Should call _kill_stale_fixonce_processes"
        assert unload_idx > 0, "Should call launchctl unload"
        assert kill_idx < unload_idx, "Process kill should happen before launchctl unload"


class TestTargetedScripts:
    """Test that only specific scripts are targeted."""

    def test_targets_menubar_app(self):
        """Should target menubar_app.py."""
        from install import _kill_stale_fixonce_processes
        import inspect
        source = inspect.getsource(_kill_stale_fixonce_processes)
        assert "menubar_app.py" in source

    def test_targets_app_launcher(self):
        """Should target app_launcher.py."""
        from install import _kill_stale_fixonce_processes
        import inspect
        source = inspect.getsource(_kill_stale_fixonce_processes)
        assert "app_launcher.py" in source

    def test_targets_server(self):
        """Should target server.py."""
        from install import _kill_stale_fixonce_processes
        import inspect
        source = inspect.getsource(_kill_stale_fixonce_processes)
        assert "server.py" in source
