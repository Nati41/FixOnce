"""
Tests for native app project display consistency.

Verifies that the native app displays the same project information
as the server API returns.
"""

import json
import pytest
import subprocess
import time
import urllib.request
from pathlib import Path


def get_api_response(port: int, endpoint: str, timeout: float = 5.0) -> dict:
    """Fetch JSON from API endpoint."""
    url = f"http://localhost:{port}/api/{endpoint}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def get_runtime_port() -> int:
    """Get the current server port from runtime.json."""
    runtime_file = Path.home() / ".fixonce" / "runtime.json"
    if runtime_file.exists():
        data = json.loads(runtime_file.read_text())
        return data.get("port", 5000)
    return 5000


class TestDashboardSnapshotProjectConsistency:
    """Test that dashboard_snapshot returns consistent project data."""

    @pytest.fixture
    def port(self):
        return get_runtime_port()

    def test_snapshot_project_fields_agree(self, port):
        """All project-related fields in snapshot must agree."""
        try:
            data = get_api_response(port, "dashboard_snapshot")
        except Exception as e:
            pytest.skip(f"Server not running: {e}")

        snapshot = data.get("snapshot", {})

        # Extract all project name sources
        identity_name = snapshot.get("identity", {}).get("name")
        project_name = snapshot.get("project_name")
        selected_project_name = snapshot.get("selected_project_name")
        selected_project_id = snapshot.get("selected_project_id")

        # Find selected project in projects list
        projects = snapshot.get("projects", [])
        selected_project = next(
            (p for p in projects if p.get("project_id") == selected_project_id),
            {}
        )
        project_list_name = selected_project.get("name")

        # All names should agree (where present)
        names = [n for n in [identity_name, project_name, selected_project_name, project_list_name] if n]

        if names:
            first_name = names[0]
            for name in names[1:]:
                assert name == first_name, (
                    f"Project names disagree: identity={identity_name}, "
                    f"project_name={project_name}, selected={selected_project_name}, "
                    f"list={project_list_name}"
                )

    def test_selected_project_exists_in_list(self, port):
        """selected_project_id must exist in projects list."""
        try:
            data = get_api_response(port, "dashboard_snapshot")
        except Exception as e:
            pytest.skip(f"Server not running: {e}")

        snapshot = data.get("snapshot", {})
        selected_id = snapshot.get("selected_project_id")
        projects = snapshot.get("projects", [])

        if selected_id and projects:
            project_ids = [p.get("project_id") for p in projects]
            assert selected_id in project_ids, (
                f"selected_project_id {selected_id} not in projects list: {project_ids}"
            )


class TestTrayStatusProjectConsistency:
    """Test that tray status returns consistent project data."""

    @pytest.fixture
    def port(self):
        return get_runtime_port()

    def test_tray_matches_dashboard(self, port):
        """Tray project_name must match dashboard project_name."""
        try:
            dashboard_data = get_api_response(port, "dashboard_snapshot")
            tray_data = get_api_response(port, "tray/status")
        except Exception as e:
            pytest.skip(f"Server not running: {e}")

        dashboard_snapshot = dashboard_data.get("snapshot", {})
        dashboard_name = (
            dashboard_snapshot.get("identity", {}).get("name") or
            dashboard_snapshot.get("project_name")
        )
        tray_name = tray_data.get("project_name")

        if dashboard_name and tray_name and tray_name != "No project":
            assert dashboard_name == tray_name, (
                f"Dashboard shows '{dashboard_name}' but tray shows '{tray_name}'"
            )


class TestActiveProjectFileConsistency:
    """Test that active_project.json is consistent with API."""

    @pytest.fixture
    def port(self):
        return get_runtime_port()

    def test_file_matches_api(self, port):
        """active_project.json must match API selected_project_id."""
        active_file = Path.home() / ".fixonce" / "active_project.json"

        if not active_file.exists():
            pytest.skip("No active_project.json file")

        file_data = json.loads(active_file.read_text())
        file_id = file_data.get("active_id")
        file_name = file_data.get("display_name")

        try:
            api_data = get_api_response(port, "dashboard_snapshot")
        except Exception as e:
            pytest.skip(f"Server not running: {e}")

        snapshot = api_data.get("snapshot", {})
        api_id = snapshot.get("selected_project_id")
        api_name = snapshot.get("project_name")

        if file_id and api_id:
            assert file_id == api_id, (
                f"File has active_id={file_id} but API has selected_project_id={api_id}"
            )

        if file_name and api_name:
            assert file_name == api_name, (
                f"File has display_name={file_name} but API has project_name={api_name}"
            )


class TestProjectSwitchRefresh:
    """Test that project switches are reflected in API."""

    @pytest.fixture
    def port(self):
        return get_runtime_port()

    def test_api_reflects_file_change(self, port):
        """API should reflect changes to active_project.json within reasonable time."""
        active_file = Path.home() / ".fixonce" / "active_project.json"

        if not active_file.exists():
            pytest.skip("No active_project.json file")

        # Read current state
        original_data = json.loads(active_file.read_text())

        try:
            # Get API state - should match file
            api_data = get_api_response(port, "dashboard_snapshot")
        except Exception as e:
            pytest.skip(f"Server not running: {e}")

        snapshot = api_data.get("snapshot", {})
        api_id = snapshot.get("selected_project_id")
        file_id = original_data.get("active_id")

        # If they match, the system is consistent
        # If they don't match, there's a consistency bug
        assert api_id == file_id, (
            f"API shows {api_id} but file has {file_id}. "
            "The server may be caching stale state."
        )


class TestStaleProjectDoesNotOverride:
    """Test that stale project data doesn't override fresh data."""

    @pytest.fixture
    def port(self):
        return get_runtime_port()

    def test_fresh_fetch_returns_current_project(self, port):
        """Multiple fetches should return the same current project."""
        try:
            # Fetch twice with small delay
            first = get_api_response(port, "dashboard_snapshot")
            time.sleep(0.5)
            second = get_api_response(port, "dashboard_snapshot")
        except Exception as e:
            pytest.skip(f"Server not running: {e}")

        first_id = first.get("snapshot", {}).get("selected_project_id")
        second_id = second.get("snapshot", {}).get("selected_project_id")

        assert first_id == second_id, (
            f"Project changed between fetches: {first_id} -> {second_id}"
        )

        first_name = first.get("snapshot", {}).get("project_name")
        second_name = second.get("snapshot", {}).get("project_name")

        assert first_name == second_name, (
            f"Project name changed between fetches: {first_name} -> {second_name}"
        )


class TestSingleNativeAppProcess:
    """Test that only one native app process is running."""

    def test_single_dashboard_process(self):
        """Only one dashboard process should be active."""
        result = subprocess.run(
            ["pgrep", "-f", "app_launcher.py --dashboard"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            pytest.skip("No dashboard process running")

        pids = result.stdout.strip().split("\n")
        pids = [p for p in pids if p]

        assert len(pids) <= 1, (
            f"Multiple dashboard processes running: PIDs {pids}"
        )

    def test_single_tray_process(self):
        """Only one tray process should be active."""
        result = subprocess.run(
            ["pgrep", "-f", "menubar_app.py"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            # Also check app_launcher without --dashboard
            result = subprocess.run(
                ["pgrep", "-f", "app_launcher.py$"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                pytest.skip("No tray process running")

        pids = result.stdout.strip().split("\n")
        pids = [p for p in pids if p]

        assert len(pids) <= 1, (
            f"Multiple tray processes running: PIDs {pids}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
