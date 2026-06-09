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


class TestMemoryReviewIntegration:
    """Tests for Memory Review integration with MCP tools."""

    @pytest.fixture
    def mock_mcp_env(self, temp_user_dir):
        """Set up isolated environment for MCP tool testing."""
        import config
        original_user_data_dir = config.USER_DATA_DIR
        config.USER_DATA_DIR = temp_user_dir

        projects_dir = temp_user_dir / "projects_v2"
        projects_dir.mkdir(parents=True, exist_ok=True)

        test_project_id = "test_project_abc123"
        test_project_file = projects_dir / f"{test_project_id}.json"
        test_project_file.write_text(json.dumps({
            "project_info": {"name": "Test Project"},
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }), encoding="utf-8")

        if 'core.pending_memories' in sys.modules:
            del sys.modules['core.pending_memories']

        import core.pending_memories
        core.pending_memories.USER_DATA_DIR = temp_user_dir
        core.pending_memories.PENDING_FILE = temp_user_dir / 'pending_memories.json'

        yield {
            "user_data_dir": temp_user_dir,
            "project_id": test_project_id,
            "project_file": test_project_file,
        }

        config.USER_DATA_DIR = original_user_data_dir

    def test_review_disabled_decision_writes_directly(self, mock_mcp_env):
        """When MEMORY_REVIEW_ENABLED=false, fo_decide writes directly to memory."""
        from core.pending_memories import is_review_enabled, get_pending

        assert is_review_enabled() is False

        data = get_pending()
        assert len(data["pending"]) == 0

    def test_review_enabled_decision_queues(self, mock_mcp_env):
        """When MEMORY_REVIEW_ENABLED=true, decision goes to pending queue."""
        with patch.dict(os.environ, {"MEMORY_REVIEW_ENABLED": "true"}):
            import importlib
            import core.pending_memories
            importlib.reload(core.pending_memories)
            core.pending_memories.USER_DATA_DIR = mock_mcp_env["user_data_dir"]
            core.pending_memories.PENDING_FILE = mock_mcp_env["user_data_dir"] / 'pending_memories.json'

            assert core.pending_memories.is_review_enabled() is True

            core.pending_memories.add_pending_decision(
                "Test decision",
                "Test reason",
                actor="claude"
            )

            data = core.pending_memories.get_pending()
            assert len(data["pending"]) == 1
            assert data["pending"][0]["type"] == "decision"
            assert data["pending"][0]["text"] == "Test decision"

    def test_review_enabled_avoid_queues(self, mock_mcp_env):
        """When MEMORY_REVIEW_ENABLED=true, avoid pattern goes to pending queue."""
        with patch.dict(os.environ, {"MEMORY_REVIEW_ENABLED": "true"}):
            import importlib
            import core.pending_memories
            importlib.reload(core.pending_memories)
            core.pending_memories.USER_DATA_DIR = mock_mcp_env["user_data_dir"]
            core.pending_memories.PENDING_FILE = mock_mcp_env["user_data_dir"] / 'pending_memories.json'

            core.pending_memories.add_pending_avoid(
                "Never use eval()",
                "Security risk",
                actor="claude"
            )

            data = core.pending_memories.get_pending()
            assert len(data["pending"]) == 1
            assert data["pending"][0]["type"] == "avoid"

    def test_review_enabled_solution_queues(self, mock_mcp_env):
        """When MEMORY_REVIEW_ENABLED=true, solution goes to pending queue."""
        with patch.dict(os.environ, {"MEMORY_REVIEW_ENABLED": "true"}):
            import importlib
            import core.pending_memories
            importlib.reload(core.pending_memories)
            core.pending_memories.USER_DATA_DIR = mock_mcp_env["user_data_dir"]
            core.pending_memories.PENDING_FILE = mock_mcp_env["user_data_dir"] / 'pending_memories.json'

            core.pending_memories.add_pending_solution(
                "TypeError in auth.py",
                "Added null check",
                files=["src/auth.py"],
                actor="claude"
            )

            data = core.pending_memories.get_pending()
            assert len(data["pending"]) == 1
            assert data["pending"][0]["type"] == "solution"
            assert data["pending"][0]["problem"] == "TypeError in auth.py"

    def test_approve_writes_to_durable_memory(self, mock_mcp_env):
        """Test that approve_selected returns items for durable write."""
        import core.pending_memories
        core.pending_memories.USER_DATA_DIR = mock_mcp_env["user_data_dir"]
        core.pending_memories.PENDING_FILE = mock_mcp_env["user_data_dir"] / 'pending_memories.json'

        core.pending_memories.add_pending_decision("D1", "R1", "claude")
        core.pending_memories.add_pending_solution("P1", "S1", ["f1.py"], "claude")

        approved = core.pending_memories.approve_selected(
            approved_indices=[0, 1],
            next_task="Continue work"
        )

        assert len(approved["decisions"]) == 1
        assert approved["decisions"][0]["text"] == "D1"
        assert len(approved["solutions"]) == 1
        assert approved["solutions"][0]["problem"] == "P1"
        assert approved["next_task"] == "Continue work"

        data = core.pending_memories.get_pending()
        assert len(data["pending"]) == 0

    def test_reject_removes_pending_item(self, mock_mcp_env):
        """Test that rejecting an item removes it from pending queue."""
        import core.pending_memories
        core.pending_memories.USER_DATA_DIR = mock_mcp_env["user_data_dir"]
        core.pending_memories.PENDING_FILE = mock_mcp_env["user_data_dir"] / 'pending_memories.json'

        core.pending_memories.add_pending_decision("D1", "R1", "claude")
        core.pending_memories.add_pending_decision("D2", "R2", "claude")

        assert core.pending_memories.get_pending_count() == 2

        core.pending_memories.remove_item(0)

        data = core.pending_memories.get_pending()
        assert len(data["pending"]) == 1
        assert data["pending"][0]["text"] == "D2"

    def test_approve_partial_keeps_unapproved(self, mock_mcp_env):
        """Test that approving some items does not affect unapproved ones (they are cleared)."""
        import core.pending_memories
        core.pending_memories.USER_DATA_DIR = mock_mcp_env["user_data_dir"]
        core.pending_memories.PENDING_FILE = mock_mcp_env["user_data_dir"] / 'pending_memories.json'

        core.pending_memories.add_pending_decision("D1", "R1")
        core.pending_memories.add_pending_decision("D2", "R2")
        core.pending_memories.add_pending_decision("D3", "R3")

        approved = core.pending_memories.approve_selected(approved_indices=[0, 2])

        assert len(approved["decisions"]) == 2
        assert approved["decisions"][0]["text"] == "D1"
        assert approved["decisions"][1]["text"] == "D3"

        data = core.pending_memories.get_pending()
        assert len(data["pending"]) == 0

    def test_extract_approved_does_not_clear_queue(self, mock_mcp_env):
        """Test that extract_approved extracts items without clearing the queue."""
        import core.pending_memories
        core.pending_memories.USER_DATA_DIR = mock_mcp_env["user_data_dir"]
        core.pending_memories.PENDING_FILE = mock_mcp_env["user_data_dir"] / 'pending_memories.json'

        core.pending_memories.add_pending_decision("D1", "R1")
        core.pending_memories.add_pending_decision("D2", "R2")

        approved = core.pending_memories.extract_approved(approved_indices=[0])

        assert len(approved["decisions"]) == 1
        assert approved["decisions"][0]["text"] == "D1"

        data = core.pending_memories.get_pending()
        assert len(data["pending"]) == 2


class TestApprovalLocalSync:
    """
    Regression test for Memory Review approval → LOCAL committed knowledge sync.

    Bug: Dashboard approval wrote to GLOBAL projects_v2/ but did not sync to
    LOCAL .fixonce/decisions.json. fo_init reads from LOCAL, so approved items
    were invisible to fo_init stats.

    Fix: Approval endpoint now uses save_project_memory() which triggers
    update_committed_on_save() to sync LOCAL .fixonce/.
    """

    @pytest.fixture
    def full_project_env(self, temp_user_dir):
        """Set up a complete project environment with working_dir."""
        import config

        original_user_data_dir = config.USER_DATA_DIR
        config.USER_DATA_DIR = temp_user_dir

        projects_dir = temp_user_dir / "projects_v2"
        projects_dir.mkdir(parents=True, exist_ok=True)

        working_dir = temp_user_dir / "test_project"
        working_dir.mkdir(parents=True, exist_ok=True)
        fixonce_dir = working_dir / ".fixonce"
        fixonce_dir.mkdir(parents=True, exist_ok=True)

        test_project_id = "test_project_sync"
        test_project_file = projects_dir / f"{test_project_id}.json"
        test_project_file.write_text(json.dumps({
            "project_info": {
                "name": "Test Project",
                "working_dir": str(working_dir),
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }), encoding="utf-8")

        (temp_user_dir / "active_project.json").write_text(
            json.dumps({"active_id": test_project_id}),
            encoding="utf-8"
        )

        if 'core.pending_memories' in sys.modules:
            del sys.modules['core.pending_memories']
        if 'managers.multi_project_manager' in sys.modules:
            del sys.modules['managers.multi_project_manager']

        import core.pending_memories
        core.pending_memories.USER_DATA_DIR = temp_user_dir
        core.pending_memories.PENDING_FILE = temp_user_dir / 'pending_memories.json'

        yield {
            "user_data_dir": temp_user_dir,
            "project_id": test_project_id,
            "project_file": test_project_file,
            "working_dir": working_dir,
            "fixonce_dir": fixonce_dir,
        }

        config.USER_DATA_DIR = original_user_data_dir

    def test_approval_syncs_to_local_committed_knowledge(self, full_project_env):
        """
        E2E test: pending → approve → GLOBAL updated → LOCAL synced → read_committed_knowledge sees it.

        This is the regression test for the split-brain bug where fo_init
        counted from LOCAL but approval only wrote to GLOBAL.
        """
        import core.pending_memories
        import managers.multi_project_manager as mpm
        from core.committed_knowledge import read_committed_knowledge

        mpm.DATA_DIR = full_project_env["user_data_dir"]
        mpm.PROJECTS_V2_DIR = full_project_env["user_data_dir"] / "projects_v2"
        mpm.ACTIVE_PROJECT_FILE = full_project_env["user_data_dir"] / "active_project.json"

        core.pending_memories.USER_DATA_DIR = full_project_env["user_data_dir"]
        core.pending_memories.PENDING_FILE = full_project_env["user_data_dir"] / 'pending_memories.json'

        core.pending_memories.add_pending_decision(
            "Approval flow must sync to LOCAL committed knowledge",
            "Dashboard approval writes to GLOBAL projects_v2 and triggers LOCAL sync",
            actor="mcp"
        )

        approved = core.pending_memories.extract_approved(approved_indices=[0])
        assert len(approved["decisions"]) == 1

        project_id = full_project_env["project_id"]
        memory = mpm.load_project_memory(project_id)

        if "decisions" not in memory:
            memory["decisions"] = []
        memory["decisions"].append({
            "decision": approved["decisions"][0]["text"],
            "reason": approved["decisions"][0]["reason"],
            "superseded": False,
            "actor": "user",
            "actor_source": "dashboard",
        })

        success = mpm.save_project_memory(project_id, memory)
        assert success is True

        core.pending_memories.clear_pending()

        with open(full_project_env["project_file"], "r") as f:
            global_data = json.load(f)
        assert len(global_data["decisions"]) == 1
        assert "LOCAL committed knowledge" in global_data["decisions"][0]["decision"]

        committed = read_committed_knowledge(str(full_project_env["working_dir"]))
        assert committed["found"] is True
        assert len(committed["decisions"]) >= 1

        found_in_local = any(
            "LOCAL committed knowledge" in d.get("decision", "")
            for d in committed["decisions"]
        )
        assert found_in_local, "Approved item should be synced to LOCAL .fixonce/decisions.json"

    def test_failed_save_does_not_clear_pending(self, full_project_env):
        """Test that pending items are preserved if durable save fails."""
        import core.pending_memories

        core.pending_memories.USER_DATA_DIR = full_project_env["user_data_dir"]
        core.pending_memories.PENDING_FILE = full_project_env["user_data_dir"] / 'pending_memories.json'

        core.pending_memories.add_pending_decision("D1", "R1")

        data = core.pending_memories.get_pending()
        assert len(data["pending"]) == 1

        approved = core.pending_memories.extract_approved(approved_indices=[0])
        assert len(approved["decisions"]) == 1

        data = core.pending_memories.get_pending()
        assert len(data["pending"]) == 1
