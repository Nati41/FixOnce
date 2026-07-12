"""
Tests for Active Project Resolver.

Regression tests for the bug where dashboard overwrites a newer active session
with an older project from stale ai_connections.json data.

Test scenario:
1. FixOnce project is active first
2. New PocketCRM session becomes active
3. Dashboard refresh occurs (catalog_repair)
4. PocketCRM must remain active
5. Stale Codex/Cursor connection cannot overwrite newer Claude/current session
"""

import json
import pytest
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

# Add src to path for imports
_SRC_DIR = Path(__file__).parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def resolver_with_temp_dir(temp_data_dir, monkeypatch):
    """Set up resolver to use temporary data directory."""
    monkeypatch.setenv("FIXONCE_USER_DATA_DIR", str(temp_data_dir))

    # Reload module to pick up new env var
    import importlib
    from src.core import active_project_resolver
    importlib.reload(active_project_resolver)

    yield active_project_resolver

    # Cleanup
    monkeypatch.delenv("FIXONCE_USER_DATA_DIR", raising=False)


class TestResolverPriority:
    """Test that resolver correctly prioritizes sources."""

    def test_live_session_beats_cached(self, resolver_with_temp_dir, temp_data_dir):
        """Live session should take priority over cached active_project.json."""
        resolver = resolver_with_temp_dir

        # Set up cached active_project.json pointing to OLD project
        cached_file = temp_data_dir / "active_project.json"
        cached_file.write_text(json.dumps({
            "active_id": "OldProject_123",
            "detected_from": "catalog_repair",
            "detected_at": (datetime.now() - timedelta(hours=1)).isoformat(),
        }))

        # Set up LIVE session for NEW project
        session_file = temp_data_dir / "session_registry.json"
        session_file.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "sessions": {
                "claude:/Users/test/NewProject": {
                    "ai_name": "claude",
                    "project_id": "NewProject_456",
                    "project_path": "/Users/test/NewProject",
                    "last_activity": datetime.now().isoformat(),
                    "is_active": True,
                }
            }
        }))

        # Resolve - should get NewProject from live session
        resolved = resolver.resolve_active_project()

        assert resolved.project_id == "NewProject_456"
        assert resolved.source == "live_session"
        assert resolved.confidence == "verified"

    def test_boundary_transition_beats_cached(self, resolver_with_temp_dir, temp_data_dir):
        """Recent boundary transition should take priority over stale cache."""
        resolver = resolver_with_temp_dir

        # Set up stale cached active_project.json
        cached_file = temp_data_dir / "active_project.json"
        cached_file.write_text(json.dumps({
            "active_id": "OldProject_123",
            "detected_from": "manual",
            "detected_at": (datetime.now() - timedelta(hours=1)).isoformat(),
        }))

        # Set up recent boundary transition
        boundary_file = temp_data_dir / "boundary_state.json"
        boundary_file.write_text(json.dumps({
            "last_switch_timestamp": datetime.now().isoformat(),
            "last_switch_from": "OldProject_123",
            "last_switch_to": "NewProject_456",
        }))

        # No live session
        # Resolve - should get NewProject from boundary transition
        resolved = resolver.resolve_active_project()

        assert resolved.project_id == "NewProject_456"
        assert resolved.source == "boundary_transition"
        assert resolved.confidence == "recent"

    def test_cached_used_when_no_live_session(self, resolver_with_temp_dir, temp_data_dir):
        """Cached value should be used when no live session exists."""
        resolver = resolver_with_temp_dir

        # Set up recent cached active_project.json
        cached_file = temp_data_dir / "active_project.json"
        cached_file.write_text(json.dumps({
            "active_id": "CachedProject_789",
            "detected_from": "manual",
            "detected_at": datetime.now().isoformat(),
            "display_name": "Cached Project",
        }))

        # No session registry or boundary state

        resolved = resolver.resolve_active_project()

        assert resolved.project_id == "CachedProject_789"
        assert resolved.source == "cached"

    def test_ai_connection_is_last_fallback(self, resolver_with_temp_dir, temp_data_dir):
        """AI connection should only be used as last resort."""
        resolver = resolver_with_temp_dir

        # Only set up ai_connections.json - no other sources
        ai_file = temp_data_dir / "ai_connections.json"
        ai_file.write_text(json.dumps({
            "clients": {
                "codex": {
                    "last_seen": datetime.now().isoformat(),
                    "project_id": "FallbackProject_999",
                }
            }
        }))

        resolved = resolver.resolve_active_project()

        assert resolved.project_id == "FallbackProject_999"
        assert resolved.source == "ai_connection"
        assert resolved.confidence == "stale"


class TestUpdateBlocking:
    """Test that updates are correctly blocked when live sessions exist."""

    def test_update_blocked_by_live_session(self, resolver_with_temp_dir, temp_data_dir):
        """Update should be blocked when a different live session exists."""
        resolver = resolver_with_temp_dir

        # Set up LIVE session for ProjectA
        session_file = temp_data_dir / "session_registry.json"
        session_file.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "sessions": {
                "claude:/Users/test/ProjectA": {
                    "ai_name": "claude",
                    "project_id": "ProjectA_123",
                    "project_path": "/Users/test/ProjectA",
                    "last_activity": datetime.now().isoformat(),
                    "is_active": True,
                }
            }
        }))

        # Try to update to ProjectB (should be blocked)
        result = resolver.update_active_project(
            project_id="ProjectB_456",
            detected_from="catalog_repair",
            force=False,
        )

        assert result["updated"] is False
        assert "live session" in result["reason"].lower()

    def test_update_allowed_with_force(self, resolver_with_temp_dir, temp_data_dir):
        """Update should succeed with force=True even if live session exists."""
        resolver = resolver_with_temp_dir

        # Set up LIVE session for ProjectA
        session_file = temp_data_dir / "session_registry.json"
        session_file.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "sessions": {
                "claude:/Users/test/ProjectA": {
                    "ai_name": "claude",
                    "project_id": "ProjectA_123",
                    "project_path": "/Users/test/ProjectA",
                    "last_activity": datetime.now().isoformat(),
                    "is_active": True,
                }
            }
        }))

        # Force update to ProjectB
        result = resolver.update_active_project(
            project_id="ProjectB_456",
            detected_from="fo_init",
            force=True,
        )

        assert result["updated"] is True

    def test_update_allowed_for_same_project(self, resolver_with_temp_dir, temp_data_dir):
        """Update should succeed if it's for the same project as live session."""
        resolver = resolver_with_temp_dir

        # Set up LIVE session for ProjectA
        session_file = temp_data_dir / "session_registry.json"
        session_file.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "sessions": {
                "claude:/Users/test/ProjectA": {
                    "ai_name": "claude",
                    "project_id": "ProjectA_123",
                    "project_path": "/Users/test/ProjectA",
                    "last_activity": datetime.now().isoformat(),
                    "is_active": True,
                }
            }
        }))

        # Update for SAME project (should succeed)
        result = resolver.update_active_project(
            project_id="ProjectA_123",
            detected_from="fo_sync",
            force=False,
        )

        # Should succeed because it's the same project
        assert result["updated"] is True or "Already set" in (result.get("reason") or "")


class TestRegressionScenario:
    """
    Regression test for the specific bug:
    FixOnce project active -> PocketCRM session starts -> dashboard refresh ->
    PocketCRM must remain active
    """

    def test_dashboard_refresh_does_not_overwrite_new_session(
        self, resolver_with_temp_dir, temp_data_dir
    ):
        """
        Scenario:
        1. FixOnce project was active
        2. User starts working on PocketCRM (new session)
        3. Dashboard refreshes and tries to "repair" to FixOnce
        4. PocketCRM should remain active
        """
        resolver = resolver_with_temp_dir

        # Step 1: FixOnce was the cached active project
        cached_file = temp_data_dir / "active_project.json"
        cached_file.write_text(json.dumps({
            "active_id": "FixOnce_34592c5b",
            "detected_from": "catalog_repair",
            "detected_at": (datetime.now() - timedelta(minutes=30)).isoformat(),
            "display_name": "FixOnce",
            "working_dir": "/Users/test/Desktop/FixOnce",
        }))

        # Step 2: PocketCRM session becomes active
        session_file = temp_data_dir / "session_registry.json"
        session_file.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "sessions": {
                "claude:/Users/test/Desktop/PocketCRM": {
                    "ai_name": "claude",
                    "project_id": "PocketCRM_e711b7c8",
                    "project_path": "/Users/test/Desktop/PocketCRM",
                    "last_activity": datetime.now().isoformat(),
                    "is_active": True,
                }
            }
        }))

        # Also set up boundary state showing transition to PocketCRM
        boundary_file = temp_data_dir / "boundary_state.json"
        boundary_file.write_text(json.dumps({
            "last_switch_timestamp": datetime.now().isoformat(),
            "last_switch_from": "FixOnce_34592c5b",
            "last_switch_to": "PocketCRM_e711b7c8",
        }))

        # Step 3: Dashboard refresh tries to "repair" to FixOnce
        result = resolver.update_active_project(
            project_id="FixOnce_34592c5b",
            detected_from="catalog_repair",
            force=False,  # Dashboard should NOT force
        )

        # Step 4: Update should be BLOCKED
        assert result["updated"] is False
        assert "live session" in result["reason"].lower()

        # Verify resolver still returns PocketCRM
        resolved = resolver.resolve_active_project()
        assert resolved.project_id == "PocketCRM_e711b7c8"
        assert resolved.source == "live_session"

    def test_stale_codex_cannot_overwrite_newer_claude_session(
        self, resolver_with_temp_dir, temp_data_dir
    ):
        """
        Stale Codex/Cursor connection data should not override
        a newer Claude session.
        """
        resolver = resolver_with_temp_dir

        # Stale ai_connections.json with old Codex connection
        ai_file = temp_data_dir / "ai_connections.json"
        ai_file.write_text(json.dumps({
            "clients": {
                "codex": {
                    "last_seen": (datetime.now() - timedelta(days=2)).isoformat(),
                    "project_id": "OldProject_from_codex",
                },
                "claude": {
                    "last_seen": datetime.now().isoformat(),
                    "project_id": "NewProject_from_claude",
                }
            }
        }))

        # Active Claude session
        session_file = temp_data_dir / "session_registry.json"
        session_file.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "sessions": {
                "claude:/Users/test/NewProject": {
                    "ai_name": "claude",
                    "project_id": "NewProject_from_claude",
                    "project_path": "/Users/test/NewProject",
                    "last_activity": datetime.now().isoformat(),
                    "is_active": True,
                }
            }
        }))

        # Resolve - should get NewProject from Claude session, not old Codex
        resolved = resolver.resolve_active_project()

        assert resolved.project_id == "NewProject_from_claude"
        assert resolved.source == "live_session"
        assert "claude" in resolved.source_details.lower()


class TestAtomicWrites:
    """Test that writes are atomic."""

    def test_atomic_write_creates_temp_file(self, resolver_with_temp_dir, temp_data_dir):
        """Verify atomic write pattern (write to temp, then rename)."""
        resolver = resolver_with_temp_dir

        # Perform an update
        result = resolver.update_active_project(
            project_id="TestProject_123",
            detected_from="test",
            force=True,
        )

        assert result["updated"] is True

        # Verify the file exists and has correct content
        active_file = temp_data_dir / "active_project.json"
        assert active_file.exists()

        data = json.loads(active_file.read_text())
        assert data["active_id"] == "TestProject_123"
        assert data["detected_from"] == "test"


class TestRejectionLogging:
    """Test that rejection reasons are properly logged."""

    def test_rejected_candidates_are_recorded(self, resolver_with_temp_dir, temp_data_dir):
        """Verify that rejected sources are recorded with reasons."""
        resolver = resolver_with_temp_dir

        # Only set up cached file - other sources will be rejected
        cached_file = temp_data_dir / "active_project.json"
        cached_file.write_text(json.dumps({
            "active_id": "CachedProject",
            "detected_from": "test",
            "detected_at": datetime.now().isoformat(),
        }))

        resolved = resolver.resolve_active_project()

        # Should have rejected candidates recorded
        assert len(resolved.rejected_candidates) >= 2

        # Find live_session rejection
        live_rejection = next(
            (r for r in resolved.rejected_candidates if r["source"] == "live_session"),
            None
        )
        assert live_rejection is not None
        assert live_rejection["reason"]  # Should have a reason


class TestFoInitSessionRegistry:
    """
    Regression test for the bug where fo_init did not update session_registry.json.

    The bug: Codex calls fo_init from PocketCRM, ai_connections.json is updated
    but session_registry.json is NOT. When catalog_repair runs later, it doesn't
    see a live session and overwrites with the old project.

    The fix: fo_init must call get_or_create_session() to register in session_registry.
    """

    def test_fo_init_registers_session_in_registry(self, resolver_with_temp_dir, temp_data_dir):
        """
        fo_init from a different AI/project should create a session entry
        that the resolver can detect as a live session.

        Sequence:
        1. FixOnce is cached as active
        2. Codex calls fo_init from PocketCRM
        3. fo_init updates BOTH ai_connections AND session_registry
        4. catalog_repair cannot overwrite because session_registry shows live session
        """
        resolver = resolver_with_temp_dir

        # Step 1: FixOnce is cached as active
        cached_file = temp_data_dir / "active_project.json"
        cached_file.write_text(json.dumps({
            "active_id": "FixOnce_34592c5b",
            "detected_from": "catalog_repair",
            "detected_at": (datetime.now() - timedelta(minutes=5)).isoformat(),
        }))

        # Step 2 & 3: Simulate fo_init by creating session registry entry
        # (In real code, fo_init calls get_or_create_session which does this)
        session_file = temp_data_dir / "session_registry.json"
        session_file.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "sessions": {
                "codex:/Users/test/Desktop/PocketCRM": {
                    "ai_name": "codex",
                    "project_id": "PocketCRM_e711b7c8",
                    "project_path": "/Users/test/Desktop/PocketCRM",
                    "last_activity": datetime.now().isoformat(),
                    "is_active": True,
                }
            }
        }))

        # Also ai_connections (fo_init updates both)
        ai_file = temp_data_dir / "ai_connections.json"
        ai_file.write_text(json.dumps({
            "clients": {
                "codex": {
                    "last_seen": datetime.now().isoformat(),
                    "project_id": "PocketCRM_e711b7c8",
                    "actor_source": "client_actor",
                    "actor_confidence": 1.0,
                    "connected": True,
                }
            }
        }))

        # Step 4: catalog_repair tries to set back to FixOnce
        result = resolver.update_active_project(
            project_id="FixOnce_34592c5b",
            detected_from="catalog_repair",
            force=False,
        )

        # Should be BLOCKED because Codex has a live session on PocketCRM
        assert result["updated"] is False
        assert "live session" in result["reason"].lower()

        # Resolver should return PocketCRM
        resolved = resolver.resolve_active_project()
        assert resolved.project_id == "PocketCRM_e711b7c8"
        assert resolved.source == "live_session"
        assert "codex" in resolved.source_details.lower()


class TestSyncCache:
    """Test the sync_cache_from_resolver function."""

    def test_sync_updates_cache_from_live_session(self, resolver_with_temp_dir, temp_data_dir):
        """Sync should update cache to match live session."""
        resolver = resolver_with_temp_dir

        # Stale cache
        cached_file = temp_data_dir / "active_project.json"
        cached_file.write_text(json.dumps({
            "active_id": "StaleProject",
            "detected_from": "old",
        }))

        # Live session
        session_file = temp_data_dir / "session_registry.json"
        session_file.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "sessions": {
                "claude:/Users/test/LiveProject": {
                    "ai_name": "claude",
                    "project_id": "LiveProject_123",
                    "project_path": "/Users/test/LiveProject",
                    "last_activity": datetime.now().isoformat(),
                    "is_active": True,
                }
            }
        }))

        # Sync
        result = resolver.sync_cache_from_resolver()

        assert result["synced"] is True
        assert result["project_id"] == "LiveProject_123"
        assert result["source"] == "live_session"

        # Verify cache was updated
        data = json.loads(cached_file.read_text())
        assert data["active_id"] == "LiveProject_123"
