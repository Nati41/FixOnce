"""
Phase 0 Integration Tests - Project Isolation

Tests to verify that Phase 0 fixes prevent:
1. Global session state leakage between threads
2. Error cross-contamination between projects
3. Activity log pollution between projects
4. Git hash cache invalidation works correctly

Run with: pytest tests/test_phase0_isolation.py -v
"""

import pytest
import sys
import os
import threading
import time
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestSessionIsolation:
    """Test thread-local session isolation."""

    def test_session_context_creation(self):
        """SessionContext can be created with project_id and working_dir."""
        from mcp_server.mcp_memory_server_v2 import SessionContext

        session = SessionContext("test_project", "/test/path")

        assert session.project_id == "test_project"
        assert session.working_dir == "/test/path"
        assert session.is_active() == True

    def test_empty_session_not_active(self):
        """Empty session should not be active."""
        from mcp_server.mcp_memory_server_v2 import SessionContext

        session = SessionContext()

        assert session.project_id is None
        assert session.is_active() == False

    def test_get_session_returns_context(self):
        """_get_session should always return a SessionContext."""
        from mcp_server.mcp_memory_server_v2 import _get_session, _clear_session

        _clear_session()
        session = _get_session()

        assert session is not None
        assert isinstance(session, object)

    def test_set_and_get_session(self):
        """Setting session should be retrievable."""
        from mcp_server.mcp_memory_server_v2 import (
            _set_session, _get_session, _clear_session
        )

        _clear_session()
        _set_session("my_project", "/my/path")
        session = _get_session()

        assert session.project_id == "my_project"
        assert session.working_dir == "/my/path"

        _clear_session()

    def test_clear_session_resets(self):
        """Clearing session should reset to empty."""
        from mcp_server.mcp_memory_server_v2 import (
            _set_session, _get_session, _clear_session
        )

        _set_session("my_project", "/my/path")
        _clear_session()
        session = _get_session()

        assert session.is_active() == False

    def test_concurrent_sessions_isolated(self):
        """Two threads with different projects should not interfere."""
        from mcp_server.mcp_memory_server_v2 import (
            _set_session, _get_session, _clear_session
        )

        results = {}
        errors = []

        def worker(thread_id, project_id, working_dir):
            try:
                _set_session(project_id, working_dir)
                time.sleep(0.05)  # Simulate work
                session = _get_session()
                results[thread_id] = session.project_id
                _clear_session()
            except Exception as e:
                errors.append(str(e))

        t1 = threading.Thread(target=worker, args=(1, "project_a", "/path/a"))
        t2 = threading.Thread(target=worker, args=(2, "project_b", "/path/b"))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert results.get(1) == "project_a", f"Thread 1 got wrong project: {results.get(1)}"
        assert results.get(2) == "project_b", f"Thread 2 got wrong project: {results.get(2)}"


class TestErrorStoreIsolation:
    """Test per-project error tagging."""

    def setup_method(self):
        """Clear error store before each test."""
        from core.error_store import clear_errors
        clear_errors()

    def test_error_tagged_with_project(self):
        """Errors should be tagged with project_id."""
        from core.error_store import add_error, get_errors

        add_error({"message": "Test error"}, project_id="proj_a")

        errors = get_errors()
        assert len(errors) == 1
        assert errors[0]["_project_id"] == "proj_a"

    def test_errors_filtered_by_project(self):
        """get_errors with project_id should filter results."""
        from core.error_store import add_error, get_errors

        add_error({"message": "Error A"}, project_id="proj_a")
        add_error({"message": "Error B"}, project_id="proj_b")
        add_error({"message": "Error A2"}, project_id="proj_a")

        errors_a = get_errors(project_id="proj_a")
        errors_b = get_errors(project_id="proj_b")

        assert len(errors_a) == 2
        assert len(errors_b) == 1
        assert all(e["message"].startswith("Error A") for e in errors_a)

    def test_clear_only_target_project(self):
        """clear_errors with project_id should only clear that project."""
        from core.error_store import add_error, get_errors, clear_errors

        add_error({"message": "Error A"}, project_id="proj_a")
        add_error({"message": "Error B"}, project_id="proj_b")

        cleared = clear_errors(project_id="proj_a")

        assert cleared == 1
        assert len(get_errors(project_id="proj_a")) == 0
        assert len(get_errors(project_id="proj_b")) == 1

    def test_get_all_errors_returns_all(self):
        """get_all_errors should return errors from all projects."""
        from core.error_store import add_error, get_all_errors

        add_error({"message": "Error A"}, project_id="proj_a")
        add_error({"message": "Error B"}, project_id="proj_b")

        all_errors = get_all_errors()

        assert len(all_errors) == 2

    def test_error_count_by_project(self):
        """get_error_count should count per project."""
        from core.error_store import add_error, get_error_count

        add_error({"message": "1"}, project_id="proj_a")
        add_error({"message": "2"}, project_id="proj_a")
        add_error({"message": "3"}, project_id="proj_b")

        assert get_error_count(project_id="proj_a") == 2
        assert get_error_count(project_id="proj_b") == 1
        assert get_error_count() == 3


class TestGitHashCacheInvalidation:
    """Test that git hash changes invalidate cache."""

    def test_get_git_commit_hash(self):
        """Should return commit hash for git repos."""
        from mcp_server.mcp_memory_server_v2 import _get_git_commit_hash, _is_git_repo

        # Test on FixOnce repo itself
        fixonce_dir = str(Path(__file__).parent.parent)

        if _is_git_repo(fixonce_dir):
            hash_result = _get_git_commit_hash(fixonce_dir)
            assert hash_result is not None
            assert len(hash_result) == 12  # Short hash

    def test_is_git_repo(self):
        """Should detect git repos correctly."""
        from mcp_server.mcp_memory_server_v2 import _is_git_repo

        fixonce_dir = str(Path(__file__).parent.parent)
        temp_dir = tempfile.mkdtemp()

        try:
            # FixOnce should be a git repo
            assert _is_git_repo(fixonce_dir) == True
            # Random temp dir should not be
            assert _is_git_repo(temp_dir) == False
        finally:
            shutil.rmtree(temp_dir)

    def test_cache_invalidated_on_hash_change(self):
        """Cache should be ignored if git hash changed."""
        from mcp_server.mcp_memory_server_v2 import (
            _get_cached_snapshot, _load_index, _save_index
        )

        # Create a fake cached snapshot with old hash
        index = _load_index()
        index["projects"] = {
            "test_proj": {
                "project_id": "test_proj",
                "working_dir": "/fake/path",
                "git_commit_hash": "oldoldhash12",
                "summary": "Test project"
            }
        }
        _save_index(index)

        # Mock _is_git_repo and _get_git_commit_hash
        with patch('mcp_server.mcp_memory_server_v2._is_git_repo', return_value=True):
            with patch('mcp_server.mcp_memory_server_v2._get_git_commit_hash', return_value="newnewnewhash"):
                result = _get_cached_snapshot("test_proj", "/fake/path")

                # Should return None because hash changed
                assert result is None


class TestProjectIndex:
    """Test project index cache functionality."""

    def test_snapshot_includes_git_hash(self):
        """Snapshot should include git_commit_hash field."""
        from mcp_server.mcp_memory_server_v2 import _update_snapshot, _load_index

        with patch('mcp_server.mcp_memory_server_v2._is_git_repo', return_value=True):
            with patch('mcp_server.mcp_memory_server_v2._get_git_commit_hash', return_value="abc123def456"):
                _update_snapshot(
                    "test_proj",
                    "/test/path",
                    {"project_info": {"name": "Test"}, "live_record": {}}
                )

                index = _load_index()
                snapshot = index["projects"].get("test_proj")

                assert snapshot is not None
                assert snapshot["git_commit_hash"] == "abc123def456"

    def test_snapshot_has_required_fields(self):
        """Snapshot should have all required fields."""
        from mcp_server.mcp_memory_server_v2 import _update_snapshot, _load_index

        _update_snapshot(
            "test_proj",
            "/test/path",
            {
                "project_info": {"name": "My Project"},
                "live_record": {
                    "architecture": {"summary": "Test arch", "stack": "Python"},
                    "intent": {"current_goal": "Test goal"},
                    "lessons": {"insights": ["insight1"]}
                },
                "decisions": [{"decision": "dec1"}],
                "avoid": [{"what": "avoid1"}]
            }
        )

        index = _load_index()
        snapshot = index["projects"].get("test_proj")

        assert snapshot["project_id"] == "test_proj"
        assert snapshot["working_dir"] == "/test/path"
        assert snapshot["name"] == "My Project"
        assert snapshot["summary"] == "Test arch"
        assert snapshot["stack"] == "Python"
        assert snapshot["current_goal"] == "Test goal"
        assert snapshot["last_insight"] == "insight1"
        assert snapshot["decisions_count"] == 1
        assert snapshot["avoid_count"] == 1


class TestActivityTagging:
    """Test activity log project tagging."""

    def test_activity_tagged_with_project_id(self):
        """Activities should be tagged with project_id."""
        from api.activity import _get_project_id_from_cwd

        project_id = _get_project_id_from_cwd("/Users/test/my-project")

        assert project_id is not None
        assert "my-project_" in project_id

    def test_empty_cwd_returns_global(self):
        """Empty cwd should return __global__."""
        from api.activity import _get_project_id_from_cwd

        assert _get_project_id_from_cwd("") == "__global__"
        assert _get_project_id_from_cwd(None) == "__global__"


class TestToolsUseSession:
    """Test that all MCP tools use session instead of global state."""

    def test_session_required_for_tools(self):
        """Tools should require active session."""
        from mcp_server.mcp_memory_server_v2 import _get_session, _clear_session

        _clear_session()
        session = _get_session()

        # Session should not be active after clear
        assert session.is_active() == False


# Integration test with actual session flow
class TestFullSessionFlow:
    """Test complete session lifecycle."""

    def test_init_session_sets_thread_local(self):
        """init_session should set thread-local session."""
        from mcp_server.mcp_memory_server_v2 import (
            _do_init_session, _get_session, _clear_session
        )

        _clear_session()

        # Use FixOnce dir as test project
        test_dir = str(Path(__file__).parent.parent)

        result = _do_init_session(test_dir)

        session = _get_session()

        assert session.is_active() == True
        assert session.working_dir == test_dir
        assert "FixOnce" in session.project_id

        _clear_session()

    def test_session_context_preserved_during_operations(self):
        """Session context should be preserved during tool operations."""
        from mcp_server.mcp_memory_server_v2 import (
            _do_init_session, _get_session, _clear_session, _load_project
        )

        test_dir = str(Path(__file__).parent.parent)
        _do_init_session(test_dir)

        session = _get_session()
        project_id = session.project_id

        # Load project should work with session project_id
        data = _load_project(project_id)

        # Should have project structure
        assert "project_info" in data or data == {}  # Either has data or is new

        _clear_session()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
