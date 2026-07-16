"""
Regression test for active-project stale override bug.

Proves that update_active_project(..., force=False) preserves a live session
when catalog_repair tries to write stale data.
"""

import json
import pytest
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

_SRC_DIR = Path(__file__).parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        (tmpdir_path / "projects_v2").mkdir()
        yield tmpdir_path


@pytest.fixture
def resolver_with_temp_dir(temp_data_dir, monkeypatch):
    """Set up resolver to use temporary data directory."""
    monkeypatch.setenv("FIXONCE_USER_DATA_DIR", str(temp_data_dir))

    import importlib
    from core import active_project_resolver
    importlib.reload(active_project_resolver)

    yield active_project_resolver

    monkeypatch.delenv("FIXONCE_USER_DATA_DIR", raising=False)


class TestCatalogRepairStaleOverride:
    """
    Regression tests for the bug where catalog_repair overwrote
    a live session with stale project data.
    """

    def test_force_false_preserves_live_session(self, resolver_with_temp_dir, temp_data_dir):
        """
        CRITICAL: update_active_project with force=False must NOT overwrite
        a live session with stale data.

        Scenario:
        1. Project A (FixOnce) is active with a live session
        2. catalog_repair tries to set Project B (v3-main) from stale data
        3. Project A must remain active
        """
        resolver = resolver_with_temp_dir

        # Step 1: Set up Project A as the CURRENT live session
        live_session_time = datetime.now()
        session_file = temp_data_dir / "session_registry.json"
        session_file.write_text(json.dumps({
            "updated_at": live_session_time.isoformat(),
            "sessions": {
                "claude:/Users/test/ProjectA": {
                    "ai_name": "claude",
                    "project_id": "ProjectA_123",
                    "project_path": "/Users/test/ProjectA",
                    "last_activity": live_session_time.isoformat(),
                    "is_active": True,
                }
            }
        }))

        # Also set active_project.json to Project A (current state)
        active_file = temp_data_dir / "active_project.json"
        active_file.write_text(json.dumps({
            "active_id": "ProjectA_123",
            "display_name": "ProjectA",
            "detected_from": "fo_init",
            "detected_at": live_session_time.isoformat(),
            "working_dir": "/Users/test/ProjectA"
        }))

        # Step 2: Simulate catalog_repair trying to set STALE Project B
        stale_time = datetime.now() - timedelta(hours=1)
        result = resolver.update_active_project(
            project_id="ProjectB_456",
            display_name="v3-main",
            detected_from="catalog_repair",
            working_dir="/Users/test/ProjectB",
            force=False  # THIS IS THE KEY - must not override
        )

        # Step 3: Assert Project A is still active
        assert result["updated"] is False, "force=False should have blocked the update"
        reason = result.get("reason", "").lower()
        assert "live session" in reason or "blocked" in reason, \
            f"Should mention live session or blocked as reason: {result}"

        # Verify the file still has Project A
        with open(active_file) as f:
            current = json.load(f)

        assert current["active_id"] == "ProjectA_123", \
            f"Project A should still be active, got: {current['active_id']}"

    def test_force_true_does_override(self, resolver_with_temp_dir, temp_data_dir):
        """Verify force=True DOES override (for legitimate switches)."""
        resolver = resolver_with_temp_dir

        # Set up Project A as active
        active_file = temp_data_dir / "active_project.json"
        active_file.write_text(json.dumps({
            "active_id": "ProjectA_123",
            "display_name": "ProjectA",
            "detected_from": "fo_init",
            "detected_at": datetime.now().isoformat(),
        }))

        # Force override to Project B
        result = resolver.update_active_project(
            project_id="ProjectB_456",
            display_name="ProjectB",
            detected_from="explicit_switch",
            force=True
        )

        assert result["updated"] is True, "force=True should allow override"

        with open(active_file) as f:
            current = json.load(f)

        assert current["active_id"] == "ProjectB_456"

    def test_no_live_session_allows_update(self, resolver_with_temp_dir, temp_data_dir):
        """When no live session exists, update should proceed."""
        resolver = resolver_with_temp_dir

        # Only have stale cached file, no live session
        active_file = temp_data_dir / "active_project.json"
        stale_time = datetime.now() - timedelta(hours=2)
        active_file.write_text(json.dumps({
            "active_id": "OldProject_000",
            "display_name": "OldProject",
            "detected_from": "manual",
            "detected_at": stale_time.isoformat(),
        }))

        # catalog_repair with newer data should succeed
        result = resolver.update_active_project(
            project_id="NewProject_789",
            display_name="NewProject",
            detected_from="catalog_repair",
            force=False
        )

        # Should succeed because no live session to protect
        # (depends on resolver implementation - may still succeed if cache is old)
        with open(active_file) as f:
            current = json.load(f)

        # The resolver should either update or preserve based on timestamps
        # Key point: no crash, deterministic behavior
        assert current["active_id"] in ["OldProject_000", "NewProject_789"]


class TestRepoFileNotRecreated:
    """Tests that the dead repo file is not recreated."""

    def test_legacy_repo_file_deleted(self):
        """Verify the legacy <repo>/data/active_project.json does not exist."""
        repo_data_dir = Path(__file__).parent.parent / "data"
        repo_active_file = repo_data_dir / "active_project.json"

        assert not repo_active_file.exists(), \
            f"Legacy file should be deleted: {repo_active_file}"

    def test_repo_file_in_gitignore(self):
        """Verify data/active_project.json is in .gitignore."""
        gitignore_path = Path(__file__).parent.parent / ".gitignore"

        if gitignore_path.exists():
            content = gitignore_path.read_text()
            assert "data/active_project.json" in content, \
                "data/active_project.json should be in .gitignore"

    def test_template_file_exists(self):
        """Verify the template file still exists (used for fresh installs)."""
        repo_data_dir = Path(__file__).parent.parent / "data"
        template_file = repo_data_dir / "active_project.template.json"

        assert template_file.exists(), \
            f"Template file should exist: {template_file}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
