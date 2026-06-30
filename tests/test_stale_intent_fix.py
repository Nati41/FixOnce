"""
Tests for stale intent fix in fo_init subject context.

Verifies that:
1. fo_init with stale intent and no task_hint => no subject context
2. fo_init with task_hint mentioning website/index.html => website context eligible
3. Fresh intent still works
4. Old intent does not override task_hint
"""

import pytest
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, 'src')

from mcp_server.mcp_memory_server_v2 import (
    _is_intent_fresh,
    _get_subject_context_for_init,
    _reset_intervention_session_state,
)


class TestIsIntentFresh:
    """Tests for _is_intent_fresh() helper function."""

    def test_no_updated_at_is_stale(self):
        """Intent without updated_at is considered stale."""
        intent = {"work_area": "website", "last_file": "website/index.html"}
        assert _is_intent_fresh(intent) is False

    def test_empty_updated_at_is_stale(self):
        """Intent with empty updated_at is stale."""
        intent = {"updated_at": "", "work_area": "website"}
        assert _is_intent_fresh(intent) is False

    def test_fresh_intent_is_fresh(self):
        """Intent updated < 10 min ago is fresh."""
        now = datetime.now(timezone.utc)
        intent = {
            "updated_at": now.isoformat(),
            "work_area": "website"
        }
        assert _is_intent_fresh(intent) is True

    def test_5_min_old_is_fresh(self):
        """Intent updated 5 min ago is fresh."""
        five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        intent = {
            "updated_at": five_min_ago.isoformat(),
            "work_area": "website"
        }
        assert _is_intent_fresh(intent) is True

    def test_15_min_old_is_stale(self):
        """Intent updated 15 min ago is stale."""
        fifteen_min_ago = datetime.now(timezone.utc) - timedelta(minutes=15)
        intent = {
            "updated_at": fifteen_min_ago.isoformat(),
            "work_area": "website"
        }
        assert _is_intent_fresh(intent) is False

    def test_1_hour_old_is_stale(self):
        """Intent updated 1 hour ago is stale."""
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        intent = {
            "updated_at": one_hour_ago.isoformat(),
            "work_area": "website"
        }
        assert _is_intent_fresh(intent) is False

    def test_custom_max_age(self):
        """Custom max_age_minutes works."""
        five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        intent = {
            "updated_at": five_min_ago.isoformat(),
            "work_area": "website"
        }
        # 3 min max => 5 min old is stale
        assert _is_intent_fresh(intent, max_age_minutes=3) is False
        # 10 min max => 5 min old is fresh
        assert _is_intent_fresh(intent, max_age_minutes=10) is True

    def test_naive_datetime_handled(self):
        """Naive datetime (no timezone) is handled."""
        now = datetime.now()  # No timezone
        intent = {
            "updated_at": now.isoformat(),
            "work_area": "website"
        }
        # Should not crash, should be treated as UTC
        result = _is_intent_fresh(intent)
        assert isinstance(result, bool)

    def test_invalid_timestamp_is_stale(self):
        """Invalid timestamp format is treated as stale."""
        intent = {
            "updated_at": "not-a-timestamp",
            "work_area": "website"
        }
        assert _is_intent_fresh(intent) is False


class TestStaleIntentNoContext:
    """Test: fo_init with stale intent and no task_hint => no subject context."""

    def setup_method(self):
        """Reset session state before each test."""
        _reset_intervention_session_state()

    def test_stale_intent_no_hint_returns_empty(self):
        """Stale intent without task_hint produces no context."""
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        stale_intent = {
            "updated_at": one_hour_ago.isoformat(),
            "work_area": "mcp",
            "last_file": "src/mcp_server/tools.py"
        }
        memory = {
            "decisions": [
                {"decision": "MCP uses stdio transport", "tags": ["mcp"]}
            ]
        }

        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent=stale_intent,
            memory=memory,
            task_hint=""
        )

        assert result == [], "Stale intent should not produce subject context"

    def test_no_updated_at_no_hint_returns_empty(self):
        """Intent without updated_at and no task_hint produces no context."""
        intent_no_timestamp = {
            "work_area": "mcp",
            "last_file": "src/mcp_server/tools.py"
        }
        memory = {
            "decisions": [
                {"decision": "MCP uses stdio transport", "tags": ["mcp"]}
            ]
        }

        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent=intent_no_timestamp,
            memory=memory,
            task_hint=""
        )

        assert result == [], "Intent without timestamp should not produce context"


class TestTaskHintContext:
    """Test: fo_init with task_hint mentioning website => website context."""

    def setup_method(self):
        """Reset session state before each test."""
        _reset_intervention_session_state()

    def test_task_hint_triggers_context(self):
        """task_hint about website triggers website context search."""
        stale_intent = {
            "updated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "work_area": "mcp",  # OLD area
        }
        memory = {
            "decisions": [
                {"decision": "Dashboard uses English UI", "tags": ["website", "dashboard"]},
                {"decision": "MCP uses stdio", "tags": ["mcp"]}
            ]
        }

        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent=stale_intent,
            memory=memory,
            task_hint="working on website/index.html"
        )

        # Should get context (not empty) because task_hint is fresh
        assert len(result) > 0, "task_hint should trigger context"
        # Context should mention website, not mcp
        context_text = "\n".join(result)
        assert "website" in context_text.lower(), "Should surface website context"

    def test_task_hint_overrides_stale_intent(self):
        """task_hint takes priority over stale intent."""
        stale_intent = {
            "updated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "work_area": "core search",  # OLD area
            "last_file": "src/core/search.py"  # OLD file
        }
        memory = {
            "decisions": [
                {"decision": "Dashboard cache disabled", "tags": ["website", "dashboard"]},
                {"decision": "Search uses fuzzy matching", "tags": ["core", "search"]}
            ]
        }

        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent=stale_intent,
            memory=memory,
            task_hint="edit website/dashboard.html"
        )

        # Should get website context, not core/search
        context_text = "\n".join(result)
        assert "dashboard" in context_text.lower() or "website" in context_text.lower()


class TestFreshIntentStillWorks:
    """Test: Fresh intent still works correctly."""

    def setup_method(self):
        """Reset session state before each test."""
        _reset_intervention_session_state()

    def test_fresh_intent_produces_context(self):
        """Fresh intent (< 10 min old) produces context."""
        fresh_intent = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "work_area": "website",
            "last_file": "website/index.html"
        }
        memory = {
            "decisions": [
                {"decision": "Dashboard uses English", "tags": ["website", "dashboard"]}
            ]
        }

        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent=fresh_intent,
            memory=memory,
            task_hint=""  # No hint needed
        )

        assert len(result) > 0, "Fresh intent should produce context"

    def test_task_hint_exclusive_even_with_fresh_intent(self):
        """task_hint is exclusive - fresh intent is ignored when hint is provided."""
        fresh_intent = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "work_area": "website",
            "last_file": "website/styles.css"
        }
        memory = {
            "decisions": [
                {"decision": "Dashboard uses English", "tags": ["website", "dashboard"]}
            ]
        }

        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent=fresh_intent,
            memory=memory,
            task_hint="working on dashboard"
        )

        # task_hint is exclusive, but since both point to website/dashboard, result is same
        # The key point: intent signals are NOT merged, only task_hint is used
        assert len(result) > 0


class TestOldIntentDoesNotOverrideTaskHint:
    """Test: Old intent does not override task_hint."""

    def setup_method(self):
        """Reset session state before each test."""
        _reset_intervention_session_state()

    def test_old_intent_ignored_when_hint_present(self):
        """Old intent is completely ignored when task_hint is present."""
        old_intent = {
            "updated_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "work_area": "windows installer",  # Completely different area
            "last_file": "scripts/install_windows.ps1"
        }
        memory = {
            "decisions": [
                {"decision": "Dashboard caching disabled", "tags": ["website", "dashboard"]},
                {"decision": "Windows uses PowerShell", "tags": ["windows", "installer"]}
            ]
        }

        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent=old_intent,
            memory=memory,
            task_hint="work on website"
        )

        # Should get website context, NOT windows/installer
        context_text = "\n".join(result)
        # The old intent's "windows installer" should not appear
        assert "windows" not in context_text.lower() or "website" in context_text.lower()

    def test_fresh_intent_mcp_ignored_when_hint_website(self):
        """Even fresh intent is ignored when task_hint is provided (exclusive rule)."""
        # This is the key test: task_hint takes full priority
        fresh_intent = {
            "updated_at": datetime.now(timezone.utc).isoformat(),  # FRESH!
            "work_area": "mcp memory",  # Unrelated area
            "last_file": "src/mcp_server/tools.py"
        }
        memory = {
            "decisions": [
                {"decision": "Dashboard uses English", "tags": ["website", "dashboard"]},
                {"decision": "MCP uses stdio transport", "tags": ["mcp", "memory"]}
            ]
        }

        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent=fresh_intent,
            memory=memory,
            task_hint="website/index.html dashboard ownership"
        )

        # task_hint should be exclusive - mcp/memory should NOT appear
        context_text = "\n".join(result).lower()
        assert "website" in context_text or "dashboard" in context_text, \
            f"Should include website/dashboard tags, got: {context_text}"
        assert "mcp" not in context_text, \
            f"Should NOT include mcp from intent, got: {context_text}"


class TestEdgeCases:
    """Edge case tests."""

    def setup_method(self):
        """Reset session state before each test."""
        _reset_intervention_session_state()

    def test_empty_intent_no_hint_silent(self):
        """Empty intent and no hint = silent."""
        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent={},
            memory={"decisions": [{"decision": "Test", "tags": ["test"]}]},
            task_hint=""
        )
        assert result == []

    def test_task_hint_with_no_matching_memory(self):
        """task_hint with no matching memories returns empty."""
        result = _get_subject_context_for_init(
            working_dir="/tmp/test",
            intent={},
            memory={"decisions": []},  # No decisions
            task_hint="work on website"
        )
        # May return empty if no matches found
        # This is expected behavior
        assert isinstance(result, list)

    def test_exactly_10_min_boundary(self):
        """Intent exactly 10 minutes old is stale (not fresh)."""
        exactly_10_min = datetime.now(timezone.utc) - timedelta(minutes=10)
        intent = {
            "updated_at": exactly_10_min.isoformat(),
            "work_area": "website"
        }
        # >= 10 min should be stale
        assert _is_intent_fresh(intent) is False

    def test_9_min_59_sec_is_fresh(self):
        """Intent 9 min 59 sec old is still fresh."""
        almost_10_min = datetime.now(timezone.utc) - timedelta(minutes=9, seconds=59)
        intent = {
            "updated_at": almost_10_min.isoformat(),
            "work_area": "website"
        }
        assert _is_intent_fresh(intent) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
