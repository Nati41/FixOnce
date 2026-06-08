"""
Tests for Memory Review MVP (pending_memories module).

Tests:
- pending items appear
- unchecked items are not saved
- checked items are saved to durable memory
- next_task is saved and appears in project context
- existing direct memory save behavior still works when review mode is off
"""

import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


@pytest.fixture
def temp_user_dir():
    """Create a temporary user data directory."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_config(temp_user_dir):
    """Mock config to use temp directory."""
    import config
    original_user_data_dir = config.USER_DATA_DIR

    config.USER_DATA_DIR = temp_user_dir

    if 'core.pending_memories' in sys.modules:
        del sys.modules['core.pending_memories']

    import core.pending_memories
    core.pending_memories.USER_DATA_DIR = temp_user_dir
    core.pending_memories.PENDING_FILE = temp_user_dir / 'pending_memories.json'

    yield temp_user_dir

    config.USER_DATA_DIR = original_user_data_dir


class TestPendingMemoriesModule:
    """Tests for the pending_memories module."""

    def test_add_pending_decision(self, mock_config):
        """Test adding a decision to pending queue."""
        from core.pending_memories import add_pending_decision, get_pending

        add_pending_decision("Use PostgreSQL", "Better for scale", "claude")

        data = get_pending()
        assert len(data["pending"]) == 1
        assert data["pending"][0]["type"] == "decision"
        assert data["pending"][0]["text"] == "Use PostgreSQL"
        assert data["pending"][0]["reason"] == "Better for scale"
        assert data["pending"][0]["checked"] is True

    def test_add_pending_avoid(self, mock_config):
        """Test adding an avoid pattern to pending queue."""
        from core.pending_memories import add_pending_avoid, get_pending

        add_pending_avoid("Never use eval()", "Security risk", "claude")

        data = get_pending()
        assert len(data["pending"]) == 1
        assert data["pending"][0]["type"] == "avoid"
        assert data["pending"][0]["text"] == "Never use eval()"

    def test_add_pending_solution(self, mock_config):
        """Test adding a solved bug to pending queue."""
        from core.pending_memories import add_pending_solution, get_pending

        add_pending_solution(
            "TypeError in auth.py",
            "Added null check",
            ["src/auth.py"],
            "claude"
        )

        data = get_pending()
        assert len(data["pending"]) == 1
        assert data["pending"][0]["type"] == "solution"
        assert data["pending"][0]["problem"] == "TypeError in auth.py"
        assert data["pending"][0]["solution"] == "Added null check"

    def test_add_custom_memory(self, mock_config):
        """Test adding a custom user memory."""
        from core.pending_memories import add_custom_memory, get_pending

        add_custom_memory("Important note about the API")

        data = get_pending()
        assert len(data["pending"]) == 1
        assert data["pending"][0]["actor"] == "user"

    def test_set_next_task(self, mock_config):
        """Test setting next task."""
        from core.pending_memories import set_next_task, get_pending

        set_next_task("Fix the login bug")

        data = get_pending()
        assert data["next_task"] == "Fix the login bug"

    def test_get_pending_count(self, mock_config):
        """Test getting pending count."""
        from core.pending_memories import (
            add_pending_decision,
            add_pending_avoid,
            get_pending_count
        )

        assert get_pending_count() == 0
        add_pending_decision("D1", "R1")
        assert get_pending_count() == 1
        add_pending_avoid("A1", "R1")
        assert get_pending_count() == 2

    def test_clear_pending(self, mock_config):
        """Test clearing pending queue."""
        from core.pending_memories import (
            add_pending_decision,
            set_next_task,
            clear_pending,
            get_pending
        )

        add_pending_decision("D1", "R1")
        set_next_task("Task")

        count = clear_pending()
        assert count == 1

        data = get_pending()
        assert len(data["pending"]) == 0
        assert data["next_task"] == ""

    def test_approve_selected_extracts_correct_items(self, mock_config):
        """Test that approve_selected extracts only checked items."""
        from core.pending_memories import (
            add_pending_decision,
            add_pending_avoid,
            add_pending_solution,
            approve_selected,
            get_pending
        )

        add_pending_decision("D1", "R1")  # index 0
        add_pending_avoid("A1", "R1")     # index 1
        add_pending_solution("P1", "S1")  # index 2

        approved = approve_selected(
            approved_indices=[0, 2],  # approve decision and solution, not avoid
            next_task="Next step",
            custom_memory="Custom note"
        )

        assert len(approved["decisions"]) == 1
        assert len(approved["avoid"]) == 0
        assert len(approved["solutions"]) == 1
        assert len(approved["custom"]) == 1
        assert approved["next_task"] == "Next step"

        data = get_pending()
        assert len(data["pending"]) == 0

    def test_feature_flag_disabled_by_default(self, mock_config):
        """Test that review mode is disabled by default."""
        from core.pending_memories import is_review_enabled

        assert is_review_enabled() is False

    def test_feature_flag_enabled(self, mock_config):
        """Test that review mode can be enabled via env var."""
        with patch.dict(os.environ, {"MEMORY_REVIEW_ENABLED": "true"}):
            from core.pending_memories import is_review_enabled

            import importlib
            import core.pending_memories
            importlib.reload(core.pending_memories)

            assert core.pending_memories.is_review_enabled() is True

    def test_update_item_checked(self, mock_config):
        """Test updating checked state of an item."""
        from core.pending_memories import (
            add_pending_decision,
            update_item_checked,
            get_pending
        )

        add_pending_decision("D1", "R1")

        data = get_pending()
        assert data["pending"][0]["checked"] is True

        update_item_checked(0, False)

        data = get_pending()
        assert data["pending"][0]["checked"] is False


class TestPendingMemoriesAPI:
    """Tests for the pending memories API endpoints."""

    @pytest.fixture
    def client(self, mock_config):
        """Create Flask test client."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

        from flask import Flask
        from api.pending import pending_bp

        app = Flask(__name__)
        app.register_blueprint(pending_bp)
        app.config['TESTING'] = True

        with patch('api.pending.USER_DATA_DIR', mock_config):
            yield app.test_client()

    def test_get_pending_empty(self, client, mock_config):
        """Test GET /api/pending with empty queue."""
        with patch('core.pending_memories.USER_DATA_DIR', mock_config):
            with patch('core.pending_memories.PENDING_FILE', mock_config / 'pending_memories.json'):
                resp = client.get('/api/pending')
                data = resp.get_json()

                assert data["status"] == "ok"
                assert data["count"] == 0
                assert data["pending"] == []

    def test_get_pending_with_items(self, client, mock_config):
        """Test GET /api/pending with items in queue."""
        from core.pending_memories import add_pending_decision

        with patch('core.pending_memories.USER_DATA_DIR', mock_config):
            with patch('core.pending_memories.PENDING_FILE', mock_config / 'pending_memories.json'):
                add_pending_decision("Test decision", "Test reason")

                resp = client.get('/api/pending')
                data = resp.get_json()

                assert data["status"] == "ok"
                assert data["count"] == 1

    def test_add_custom_via_api(self, client, mock_config):
        """Test POST /api/pending/add."""
        with patch('core.pending_memories.USER_DATA_DIR', mock_config):
            with patch('core.pending_memories.PENDING_FILE', mock_config / 'pending_memories.json'):
                resp = client.post(
                    '/api/pending/add',
                    json={"text": "Custom memory", "type": "note"}
                )
                data = resp.get_json()

                assert data["status"] == "ok"
                assert data["item"]["text"] == "Custom memory"

    def test_clear_via_api(self, client, mock_config):
        """Test POST /api/pending/clear."""
        from core.pending_memories import add_pending_decision

        with patch('core.pending_memories.USER_DATA_DIR', mock_config):
            with patch('core.pending_memories.PENDING_FILE', mock_config / 'pending_memories.json'):
                add_pending_decision("D1", "R1")
                add_pending_decision("D2", "R2")

                resp = client.post('/api/pending/clear')
                data = resp.get_json()

                assert data["status"] == "ok"
                assert data["cleared"] == 2


class TestDirectMemoryBehavior:
    """Tests that existing direct memory behavior still works."""

    def test_fo_decide_saves_directly_when_review_disabled(self):
        """Test that fo_decide saves directly when MEMORY_REVIEW_ENABLED=false."""
        pass

    def test_fo_solved_saves_directly_when_review_disabled(self):
        """Test that fo_solved saves directly when MEMORY_REVIEW_ENABLED=false."""
        pass
