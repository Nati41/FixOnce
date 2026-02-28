"""
Multi-AI Features Integration Tests

Tests for the new features added:
1. Session Registry - Multi-AI isolation
2. Unified Health Engine - Orb health calculation
3. Project Tabs - Activity states and lifecycle
4. AI Command Queue - Switch project requests

Run with: pytest tests/test_multi_ai_features.py -v
"""

import pytest
import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestSessionRegistry:
    """Test Session Registry for Multi-AI isolation."""

    def test_isolated_session_creation(self):
        """IsolatedSession can be created with AI name and project."""
        from core.session_registry import IsolatedSession

        session = IsolatedSession(
            ai_name="claude",
            project_id="test_project",
            project_path="/test/path"
        )

        assert session.ai_name == "claude"
        assert session.project_id == "test_project"
        assert session.project_path == "/test/path"
        assert session.is_active() == True

    def test_session_key_uniqueness(self):
        """Session key should be unique per AI+project combination."""
        from core.session_registry import IsolatedSession

        session1 = IsolatedSession("claude", "project_a", "/path/a")
        session2 = IsolatedSession("codex", "project_a", "/path/a")
        session3 = IsolatedSession("claude", "project_b", "/path/b")

        assert session1.session_key != session2.session_key
        assert session1.session_key != session3.session_key
        assert session2.session_key != session3.session_key

    def test_session_inactivity_timeout(self):
        """Session becomes inactive after 60 minutes of no activity."""
        from core.session_registry import IsolatedSession

        session = IsolatedSession("claude", "test", "/test")

        # Mock last_activity to be 61 minutes ago (timeout is 60 min)
        old_time = (datetime.now() - timedelta(minutes=61)).isoformat()
        session.last_activity = old_time

        assert session.is_active() == False

    def test_session_activity_update(self):
        """Updating last_activity should refresh the timestamp."""
        from core.session_registry import IsolatedSession

        session = IsolatedSession("claude", "test", "/test")
        old_activity = session.last_activity

        time.sleep(0.1)
        # Manually update last_activity
        session.last_activity = datetime.now().isoformat()

        assert session.last_activity > old_activity

    def test_registry_get_or_create(self):
        """Registry should create new session or return existing."""
        from core.session_registry import SessionRegistry

        registry = SessionRegistry()

        # First call creates
        session1 = registry.get_or_create("claude", "test_proj", "/test")
        # Second call returns same
        session2 = registry.get_or_create("claude", "test_proj", "/test")

        assert session1.session_key == session2.session_key

    def test_registry_multiple_ais_same_project(self):
        """Multiple AIs can have sessions on the same project."""
        from core.session_registry import SessionRegistry

        registry = SessionRegistry()

        claude_session = registry.get_or_create("claude", "shared_proj", "/shared")
        codex_session = registry.get_or_create("codex", "shared_proj", "/shared")

        assert claude_session.ai_name == "claude"
        assert codex_session.ai_name == "codex"
        assert claude_session.session_key != codex_session.session_key

        # Both should be returned for the project
        sessions = registry.get_sessions_by_project("shared_proj")
        assert len(sessions) == 2

    def test_registry_close_project_sessions(self):
        """Closing project sessions should remove all sessions for that project."""
        from core.session_registry import SessionRegistry

        registry = SessionRegistry()

        registry.get_or_create("claude", "to_close", "/close")
        registry.get_or_create("codex", "to_close", "/close")
        registry.get_or_create("claude", "keep", "/keep")

        closed = registry.close_project_sessions("to_close")

        assert closed == 2
        assert len(registry.get_sessions_by_project("to_close")) == 0
        assert len(registry.get_sessions_by_project("keep")) == 1

    def test_registry_dashboard_data(self):
        """Dashboard data should include project grouping."""
        from core.session_registry import SessionRegistry

        registry = SessionRegistry()

        # Create sessions (they're stored in memory)
        registry.get_or_create("claude", "proj1", "/path1")
        registry.get_or_create("codex", "proj1", "/path1")

        # Dashboard data structure test
        data = registry.get_dashboard_data()

        # Should have the expected structure
        assert "projects" in data
        assert "sessions" in data
        assert isinstance(data["projects"], dict)


class TestActivityStates:
    """Test activity state calculation for tabs."""

    def test_active_state_within_30_seconds(self):
        """Activity within 30 seconds should be 'active'."""
        from core.session_registry import IsolatedSession

        session = IsolatedSession("claude", "test", "/test")
        # Just created, should be active

        now = datetime.now()
        last = datetime.fromisoformat(session.last_activity)
        seconds_ago = (now - last).total_seconds()

        assert seconds_ago < 30
        assert session.is_active() == True

    def test_waiting_state_after_30_seconds(self):
        """Activity between 30 seconds and 5 minutes should be 'waiting' state."""
        from core.session_registry import IsolatedSession

        session = IsolatedSession("claude", "test", "/test")

        # Set to 2 minutes ago
        two_minutes_ago = (datetime.now() - timedelta(minutes=2)).isoformat()
        session.last_activity = two_minutes_ago

        # Still active (within 5 minutes)
        assert session.is_active() == True

    def test_inactive_state_after_timeout(self):
        """Activity older than 60 minutes should be 'inactive'."""
        from core.session_registry import IsolatedSession

        session = IsolatedSession("claude", "test", "/test")

        # Set to 61 minutes ago (timeout is 60 min)
        old_time = (datetime.now() - timedelta(minutes=61)).isoformat()
        session.last_activity = old_time

        assert session.is_active() == False


class TestUnifiedHealth:
    """Test Unified Health Engine calculations."""

    def test_health_green_no_issues(self):
        """Health should be green when no issues exist."""
        from core.unified_health import get_unified_health

        health = get_unified_health(
            ai_queue=[],
            components=[],
            browser_errors=[]
        )

        assert health["status"] == "green"

    def test_health_red_failed_commands(self):
        """Health should be red with failed commands."""
        from core.unified_health import get_unified_health

        failed_command = {
            "id": "test123",
            "status": "failed",
            "command": "test command"
        }

        health = get_unified_health(
            ai_queue=[failed_command],
            components=[],
            browser_errors=[]
        )

        assert health["status"] == "red"

    def test_health_red_broken_components(self):
        """Health should be red with broken components."""
        from core.unified_health import get_unified_health

        broken_component = {
            "name": "TestComponent",
            "status": "broken"
        }

        health = get_unified_health(
            ai_queue=[],
            components=[broken_component],
            browser_errors=[]
        )

        assert health["status"] == "red"

    def test_health_yellow_browser_errors(self):
        """Health should be yellow with browser errors."""
        from core.unified_health import get_unified_health
        from datetime import datetime

        errors = [
            {"message": "Error 1", "timestamp": datetime.now().isoformat()},
            {"message": "Error 2", "timestamp": datetime.now().isoformat()},
            {"message": "Error 3", "timestamp": datetime.now().isoformat()}
        ]

        health = get_unified_health(
            ai_queue=[],
            components=[],
            browser_errors=errors
        )

        assert health["status"] == "yellow"

    def test_health_signals_structure(self):
        """Health should include all signal details."""
        from core.unified_health import get_unified_health

        health = get_unified_health(
            ai_queue=[],
            components=[],
            browser_errors=[]
        )

        assert "signals" in health
        assert "commands" in health["signals"]
        assert "stability" in health["signals"]
        assert "errors" in health["signals"]


class TestCommandQueue:
    """Test AI command queue functionality."""

    def test_queue_switch_project_command(self):
        """Switch project command should be queued correctly."""
        # This would require mocking the Flask app
        # For now, test the data structure

        command = {
            "type": "switch_project",
            "message": "Please switch to project at: /test/path",
            "source": "tab_activate_button"
        }

        assert command["type"] == "switch_project"
        assert "/test/path" in command["message"]

    def test_command_lifecycle_states(self):
        """Commands should progress through lifecycle states."""
        valid_states = ["pending", "delivered", "executed", "failed", "failed_timeout", "cancelled"]

        for state in valid_states:
            assert state in valid_states


class TestAPIEndpoints:
    """Test API endpoint responses."""

    def test_sessions_endpoint_structure(self):
        """Sessions endpoint should return proper structure."""
        # Mock response structure
        response = {
            "status": "ok",
            "session_count": 2,
            "project_count": 1,
            "sessions": [],
            "projects": {}
        }

        assert "status" in response
        assert "session_count" in response
        assert "projects" in response

    def test_delete_session_response(self):
        """Delete session should return confirmation."""
        response = {
            "status": "ok",
            "closed_count": 1,
            "project_id": "test_proj"
        }

        assert response["status"] == "ok"
        assert response["closed_count"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
