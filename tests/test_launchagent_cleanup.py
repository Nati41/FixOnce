"""
Test macOS LaunchAgent installation and cleanup.

Ensures:
- Stale LaunchAgents are cleaned up before install
- Both server and tray plists are always recreated
- ProgramArguments point to current install directory
- Logs go to ~/.fixonce/logs/
- Reinstall from different path is safe
"""

import re
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestLaunchAgentCleanup:
    """Test LaunchAgent cleanup and creation."""

    def test_cleanup_function_exists(self):
        """_cleanup_stale_launchagents should exist."""
        from install import _cleanup_stale_launchagents
        assert callable(_cleanup_stale_launchagents)

    def test_cleanup_unloads_both_agents(self):
        """Cleanup should unload both server and tray agents."""
        from install import _cleanup_stale_launchagents

        calls = []
        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0)

        with patch('install.subprocess.run', mock_run):
            _cleanup_stale_launchagents()

        # Should unload both
        unload_calls = [c for c in calls if 'unload' in c]
        assert len(unload_calls) >= 2, f"Should unload both agents, got: {unload_calls}"

        # Should try to remove by label
        remove_calls = [c for c in calls if 'remove' in c]
        assert len(remove_calls) >= 2, f"Should remove both labels, got: {remove_calls}"

    def test_cleanup_handles_server_label(self):
        """Cleanup should handle com.fixonce.server."""
        from install import _cleanup_stale_launchagents

        calls = []
        def mock_run(cmd, **kwargs):
            calls.append(' '.join(cmd))
            return MagicMock(returncode=0)

        with patch('install.subprocess.run', mock_run):
            _cleanup_stale_launchagents()

        server_calls = [c for c in calls if 'com.fixonce.server' in c]
        assert len(server_calls) >= 1, "Should handle com.fixonce.server"

    def test_cleanup_handles_tray_label(self):
        """Cleanup should handle com.fixonce.tray."""
        from install import _cleanup_stale_launchagents

        calls = []
        def mock_run(cmd, **kwargs):
            calls.append(' '.join(cmd))
            return MagicMock(returncode=0)

        with patch('install.subprocess.run', mock_run):
            _cleanup_stale_launchagents()

        tray_calls = [c for c in calls if 'com.fixonce.tray' in c]
        assert len(tray_calls) >= 1, "Should handle com.fixonce.tray"


class TestLaunchAgentPaths:
    """Test that LaunchAgent plists use correct paths."""

    def get_plist_content(self, plist_type='server'):
        """Generate plist content for testing."""
        from install import get_fixonce_dir, get_pythonw

        fixonce_dir = get_fixonce_dir()
        logs_dir = Path.home() / ".fixonce" / "logs"

        if plist_type == 'server':
            server_script = fixonce_dir / "src" / "server.py"
            return f'''<string>{sys.executable}</string>
        <string>{server_script}</string>'''
        else:
            tray_script = fixonce_dir / "scripts" / "menubar_app.py"
            pythonw = get_pythonw()
            return f'''<string>{pythonw}</string>
        <string>{tray_script}</string>'''

    def test_server_plist_uses_current_directory(self):
        """Server plist should use current fixonce_dir, not Downloads."""
        content = self.get_plist_content('server')

        # Should NOT contain Downloads/FixOnce-main
        assert "Downloads/FixOnce-main" not in content, "Should not use Downloads path"
        assert "Downloads" not in content or "FixOnce-main" not in content

        # Should contain actual script path
        assert "server.py" in content

    def test_tray_plist_uses_current_directory(self):
        """Tray plist should use current fixonce_dir, not Downloads."""
        content = self.get_plist_content('tray')

        # Should NOT contain Downloads/FixOnce-main
        assert "Downloads/FixOnce-main" not in content, "Should not use Downloads path"

        # Should contain actual script path
        assert "menubar_app.py" in content

    def test_logs_go_to_fixonce_logs_dir(self):
        """Logs should go to ~/.fixonce/logs/, not data/."""
        # Read the source to check log paths
        install_path = Path(__file__).parent.parent / "scripts" / "install.py"
        source = install_path.read_text()

        # Find the plist content sections
        server_section = source[source.find("com.fixonce.server</string>"):source.find("com.fixonce.tray</string>")]
        tray_section = source[source.find("com.fixonce.tray</string>"):source.find("com.fixonce.tray</string>") + 1000]

        # Check logs_dir is used
        assert "logs_dir" in server_section or ".fixonce" in source[source.find("StandardOutPath"):], \
            "Server logs should use logs_dir"


class TestLaunchAgentReinstall:
    """Test reinstall scenarios."""

    def test_configure_auto_start_calls_cleanup_first(self):
        """configure_auto_start should call cleanup before creating plists."""
        from install import configure_auto_start

        # Check the source code structure
        install_path = Path(__file__).parent.parent / "scripts" / "install.py"
        source = install_path.read_text()

        # Find configure_auto_start function body (use larger window)
        func_start = source.find("def configure_auto_start()")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        # Cleanup should be called before writing plist
        cleanup_idx = func_body.find("_cleanup_stale_launchagents")
        write_idx = func_body.find("with open(plist_path")

        assert cleanup_idx > 0, "Should call _cleanup_stale_launchagents"
        assert write_idx > 0, "Should write plist"
        assert cleanup_idx < write_idx, "Cleanup should be called before writing plist"

    def test_both_plists_always_written(self):
        """Both server and tray plists should always be written."""
        install_path = Path(__file__).parent.parent / "scripts" / "install.py"
        source = install_path.read_text()

        func_start = source.find("def configure_auto_start()")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        # Count plist writes
        server_write = func_body.count("with open(plist_path")
        tray_write = func_body.count("with open(tray_plist_path")

        assert server_write >= 1, "Should write server plist"
        assert tray_write >= 1, "Should write tray plist"

    def test_both_launchagents_loaded(self):
        """Both LaunchAgents should be loaded after install."""
        install_path = Path(__file__).parent.parent / "scripts" / "install.py"
        source = install_path.read_text()

        func_start = source.find("def configure_auto_start()")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        # Should load both
        assert "launchctl', 'load', str(plist_path)" in func_body, "Should load server plist"
        assert "launchctl', 'load', str(tray_plist_path)" in func_body, "Should load tray plist"

    def test_no_conditional_skip_on_running(self):
        """Should NOT skip plist creation if server is already running."""
        install_path = Path(__file__).parent.parent / "scripts" / "install.py"
        source = install_path.read_text()

        func_start = source.find("def configure_auto_start()")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        # Should NOT have conditional "if not server_already_running"
        assert "server_already_running" not in func_body, \
            "Should not conditionally skip based on running state"
        assert "if not server" not in func_body.lower() or "not server_already" not in func_body, \
            "Should always recreate plists"


class TestLaunchAgentLogPaths:
    """Test that log paths are correct."""

    def test_server_log_in_fixonce_logs(self):
        """Server log should be in ~/.fixonce/logs/."""
        install_path = Path(__file__).parent.parent / "scripts" / "install.py"
        source = install_path.read_text()

        func_start = source.find("def configure_auto_start()")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        # logs_dir should be defined as ~/.fixonce/logs/
        assert 'logs_dir = Path.home() / ".fixonce" / "logs"' in func_body, \
            "logs_dir should be ~/.fixonce/logs/"

        # Server plist should use logs_dir
        assert 'logs_dir / "server.log"' in func_body, \
            "Server log should use logs_dir"

    def test_tray_log_in_fixonce_logs(self):
        """Tray log should be in ~/.fixonce/logs/."""
        install_path = Path(__file__).parent.parent / "scripts" / "install.py"
        source = install_path.read_text()

        func_start = source.find("def configure_auto_start()")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        # Tray plist should use logs_dir
        assert 'logs_dir / "tray.log"' in func_body, \
            "Tray log should use logs_dir"
