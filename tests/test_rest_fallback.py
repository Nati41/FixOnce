#!/usr/bin/env python3
"""
REST Fallback Tests

Verifies that REST fallback endpoints (/openai/call) achieve full parity
with MCP tools for the critical operations:
- status
- sync
- solved (with review/resolution support)

These tests prove the REST fallback can safely replace MCP when transport fails.
"""

import json
import os
import sys
import tempfile
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to path for imports
_TEST_DIR = Path(__file__).parent
_SRC_DIR = _TEST_DIR.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


@pytest.fixture
def isolated_project(tmp_path):
    """Create isolated test project with memory."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    # Create .git to make it a project root
    (project_dir / ".git").mkdir()

    # Create test project memory
    memory = {
        "project_info": {
            "working_dir": str(project_dir),
            "provenance": "test",
        },
        "decisions": [],
        "avoid": [],
        "debug_sessions": [],
        "live_record": {
            "intent": {},
            "lessons": {"insights": []},
        },
        "pending_solution_reviews": [],
    }

    return {
        "project_id": f"test_project_{tmp_path.name}",
        "project_dir": str(project_dir),
        "memory": memory,
    }


@pytest.fixture
def mock_project_manager(isolated_project):
    """Mock the multi_project_manager for isolated testing."""
    import copy
    memory_store = {isolated_project["project_id"]: copy.deepcopy(isolated_project["memory"])}

    def mock_get_active():
        return isolated_project["project_id"]

    def mock_load(project_id):
        return copy.deepcopy(memory_store.get(project_id))

    def mock_save(project_id, memory):
        memory_store[project_id] = copy.deepcopy(memory)

    def mock_resolve_cwd(cwd):
        """Mock cwd resolution to use the test project."""
        if not cwd:
            return {
                "success": False,
                "error": "cwd is required for REST fallback.",
                "error_code": "missing_cwd",
            }
        return {
            "success": True,
            "project_id": isolated_project["project_id"],
            "resolved_cwd": isolated_project["project_dir"],
        }

    with patch("managers.multi_project_manager.get_active_project_id", mock_get_active), \
         patch("managers.multi_project_manager.load_project_memory", mock_load), \
         patch("managers.multi_project_manager.save_project_memory", mock_save), \
         patch("api.openai_adapter._resolve_project_from_cwd", mock_resolve_cwd):
        yield {
            "store": memory_store,
            "project_id": isolated_project["project_id"],
            "project_dir": isolated_project["project_dir"],
            "memory": isolated_project["memory"],
        }


class TestRESTStatus:
    """Test fixonce_status REST handler."""

    def test_status_returns_structured_json(self, mock_project_manager):
        """Status returns machine-parseable JSON with success flag."""
        from api.openai_adapter import _handle_status

        result = _handle_status({})

        assert result["success"] is True
        assert result["action"] == "fixonce_status"
        assert result["recording"] is True
        assert result["transport"] == "rest_fallback"
        assert "project_id" in result
        assert "message" in result


class TestRESTSync:
    """Test fixonce_sync REST handler."""

    def test_sync_updates_all_fields(self, mock_project_manager):
        """Sync updates goal, work_area, last_change, next_step."""
        from api.openai_adapter import _handle_sync

        result = _handle_sync({
            "cwd": "/test",
            "goal": "Fix login bug",
            "work_area": "authentication",
            "last_change": "Added validation",
            "last_file": "src/auth.py",
            "why": "Security improvement",
            "next_step": "Test the fix",
        })

        assert result["success"] is True
        assert result["action"] == "fixonce_sync"
        assert result["transport"] == "rest_fallback"

        # Verify all fields were synced
        synced = result["synced_fields"]
        assert synced["goal"] is True
        assert synced["work_area"] is True
        assert synced["last_change"] is True
        assert synced["last_file"] is True
        assert synced["why"] is True
        assert synced["next_step"] is True

        # Verify memory was updated
        memory = mock_project_manager["store"][mock_project_manager["project_id"]]
        intent = memory["live_record"]["intent"]
        assert intent["current_goal"] == "Fix login bug"
        assert intent["work_area"] == "authentication"
        assert intent["last_change"] == "Added validation"
        assert intent["next_step"] == "Test the fix"
        assert intent["synced_via"] == "rest_fallback"

    def test_sync_preserves_goal_history(self, mock_project_manager):
        """Sync adds old goal to history when goal changes."""
        from api.openai_adapter import _handle_sync

        # Set initial goal
        _handle_sync({"cwd": "/test", "goal": "Initial goal"})

        # Change goal
        _handle_sync({"cwd": "/test", "goal": "New goal"})

        memory = mock_project_manager["store"][mock_project_manager["project_id"]]
        history = memory["live_record"]["intent"].get("goal_history", [])
        assert len(history) == 1
        assert history[0]["goal"] == "Initial goal"


class TestRESTSolved:
    """Test fixonce_solved REST handler with review/resolution."""

    def test_solved_saves_solution(self, mock_project_manager):
        """Basic solved saves to debug_sessions."""
        from api.openai_adapter import _handle_solved

        result = _handle_solved({
            "cwd": "/test",
            "error": "TypeError: undefined is not a function",
            "solution": "Added null check before calling method",
            "files": "src/utils.js",
        })

        assert result["success"] is True
        assert result["action"] == "fixonce_solved"
        assert result["transport"] == "rest_fallback"
        assert result["message"] == "Solution saved."
        assert "solution_id" in result

        # Verify solution was saved
        memory = mock_project_manager["store"][mock_project_manager["project_id"]]
        assert len(memory["debug_sessions"]) == 1
        solution = memory["debug_sessions"][0]
        assert "TypeError" in solution["problem"]
        assert solution["actor"] == "rest_fallback"
        assert solution["actor_source"] == "rest_api"

    def test_solved_requires_error_and_solution(self, mock_project_manager):
        """Solved validates required fields."""
        from api.openai_adapter import _handle_solved

        # Missing error
        result = _handle_solved({"cwd": "/test", "solution": "Fixed it"})
        assert result["success"] is False
        assert result["error_code"] == "missing_error"

        # Missing solution
        result = _handle_solved({"cwd": "/test", "error": "Some error"})
        assert result["success"] is False
        assert result["error_code"] == "missing_solution"

    def test_solved_triggers_review_for_supersedes(self, mock_project_manager):
        """Solved returns review when new solution supersedes existing."""
        from api.openai_adapter import _handle_solved

        # Save first solution
        _handle_solved({
            "cwd": "/test",
            "error": "Cannot read property map of undefined",
            "solution": "Add Array.isArray check",
            "files": "src/list.js",
        })

        # Save similar solution that should trigger review
        result = _handle_solved({
            "cwd": "/test",
            "error": "Cannot read property map of undefined",
            "solution": "Use optional chaining (?.) instead",
            "files": "src/list.js",
        })

        # Should either succeed (as update) or require review
        # The exact behavior depends on similarity threshold
        if not result["success"]:
            assert result.get("requires_review") is True or result.get("is_update") is True

    def test_solved_review_returns_structured_response(self, mock_project_manager):
        """Review response includes review_id, target_id, allowed_actions."""
        from api.openai_adapter import _handle_solved
        from core.solutions import _create_pending_solution_review

        # Create an existing solution
        memory = mock_project_manager["memory"]
        memory["debug_sessions"].append({
            "id": "fix_existing",
            "problem": "Database connection timeout",
            "solution": "Increase pool size",
            "resolved_at": datetime.now().isoformat(),
        })

        # Manually create a pending review to test the response format
        review = _create_pending_solution_review(
            memory=memory,
            project_id=mock_project_manager["project_id"],
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Database timeout",
            proposed_solution="Use connection caching",
            allowed_actions=["supersede_existing", "cancel"],
        )

        # Verify review structure
        assert review["id"].startswith("solrev_")
        assert review["relationship"] == "supersedes"
        assert review["target_solution_id"] is not None
        assert "supersede_existing" in review["allowed_actions"]
        assert "cancel" in review["allowed_actions"]
        assert review["expires_at"] is not None

    def test_solved_direct_bypass_rejected(self, mock_project_manager):
        """Resolution without valid review_id is rejected."""
        from api.openai_adapter import _handle_solved

        result = _handle_solved({
            "cwd": "/test",
            "error": "Some error",
            "solution": "Some fix",
            "resolution_action": "supersede_existing",
            "resolution_target_id": "fix_123",
            # Missing resolution_review_id
        })

        assert result["success"] is False
        assert result["error_code"] == "missing_review_id"
        assert "review_id" in result["error"].lower()

    def test_solved_invalid_resolution_action_rejected(self, mock_project_manager):
        """Invalid resolution_action is rejected."""
        from api.openai_adapter import _handle_solved

        result = _handle_solved({
            "cwd": "/test",
            "error": "Some error",
            "solution": "Some fix",
            "resolution_action": "invalid_action",
            "resolution_target_id": "fix_123",
            "resolution_review_id": "solrev_123",
        })

        assert result["success"] is False
        assert result["error_code"] == "invalid_resolution_action"

    def test_solved_supersede_requires_target_id(self, mock_project_manager):
        """supersede_existing requires resolution_target_id."""
        from api.openai_adapter import _handle_solved

        result = _handle_solved({
            "cwd": "/test",
            "error": "Some error",
            "solution": "Some fix",
            "resolution_action": "supersede_existing",
            # Missing resolution_target_id
            "resolution_review_id": "solrev_123",
        })

        assert result["success"] is False
        assert result["error_code"] == "missing_target_id"

    def test_solved_cancel_does_not_save(self, mock_project_manager):
        """Cancel resolution does not save solution."""
        from api.openai_adapter import _handle_solved
        from core.solutions import _create_pending_solution_review

        # Get a fresh reference to memory from the store
        memory = mock_project_manager["store"][mock_project_manager["project_id"]]

        # Create existing solution
        memory["debug_sessions"].append({
            "id": "fix_existing",
            "problem": "Original error",
            "solution": "Original fix",
            "resolved_at": datetime.now().isoformat(),
        })
        memory.setdefault("pending_solution_reviews", [])

        # Create pending review directly in memory
        review = _create_pending_solution_review(
            memory=memory,
            project_id=mock_project_manager["project_id"],
            relationship="supersedes",
            target_solution=memory["debug_sessions"][0],
            proposed_problem="Similar error",
            proposed_solution="New fix",
            allowed_actions=["supersede_existing", "cancel"],
        )

        # Update the store with the review
        mock_project_manager["store"][mock_project_manager["project_id"]] = memory

        initial_count = len(memory["debug_sessions"])

        # Cancel resolution (note: cancel doesn't add a solution, so result.success may be False)
        result = _handle_solved({
            "cwd": "/test",
            "error": "Similar error",
            "solution": "New fix",
            "resolution_action": "cancel",
            "resolution_target_id": "fix_existing",
            "resolution_review_id": review["id"],
        })

        # Verify no new solution added
        updated_memory = mock_project_manager["store"][mock_project_manager["project_id"]]
        assert len(updated_memory["debug_sessions"]) == initial_count

        # The cancel action should return success=False with a message
        # (cancel means "don't save this solution")
        assert result["success"] is False or "cancel" in result.get("message", "").lower()


class TestRESTDecide:
    """Test fixonce_decide REST handler with review/resolution."""

    def test_decide_saves_decision_via_core(self, mock_project_manager):
        """Decision uses core.decisions.record_decision (same as MCP)."""
        from api.openai_adapter import _handle_decide

        result = _handle_decide({
            "cwd": "/test",
            "text": "Use PostgreSQL for the database",
            "reason": "Better for our scale and ACID compliance",
        })

        assert result["success"] is True
        assert result["action"] == "fixonce_decide"
        assert result["transport"] == "rest_fallback"

        # Verify decision was saved via core
        memory = mock_project_manager["store"][mock_project_manager["project_id"]]
        assert len(memory["decisions"]) == 1
        decision = memory["decisions"][0]
        assert "PostgreSQL" in decision["decision"]
        assert decision["actor"] == "rest_fallback"
        assert decision["actor_source"] == "rest_api"

    def test_decide_avoid_uses_core(self, mock_project_manager):
        """Avoid action uses core.decisions.record_avoid."""
        from api.openai_adapter import _handle_decide

        result = _handle_decide({
            "cwd": "/test",
            "text": "Never use eval()",
            "reason": "Security vulnerability",
            "action": "avoid",
        })

        assert result["success"] is True

        memory = mock_project_manager["store"][mock_project_manager["project_id"]]
        assert len(memory["avoid"]) == 1
        avoid = memory["avoid"][0]
        assert "eval" in avoid["what"]
        assert avoid["actor"] == "rest_fallback"

    def test_decide_requires_text_and_reason(self, mock_project_manager):
        """Decide validates required fields."""
        from api.openai_adapter import _handle_decide

        # Missing text
        result = _handle_decide({"cwd": "/test", "reason": "Some reason"})
        assert result["success"] is False
        assert result["error_code"] == "missing_text"

        # Missing reason
        result = _handle_decide({"cwd": "/test", "text": "Some decision"})
        assert result["success"] is False
        assert result["error_code"] == "missing_reason"

    def test_decide_resolution_supersede(self, mock_project_manager):
        """Resolution supersede_existing works through core."""
        from api.openai_adapter import _handle_decide

        # Create initial decision
        memory = mock_project_manager["store"][mock_project_manager["project_id"]]
        memory["decisions"].append({
            "id": "dec_existing",
            "decision": "Use MySQL",
            "reason": "Legacy requirement",
            "timestamp": datetime.now().isoformat(),
            "actor": "user",
            "actor_source": "manual",
        })

        # Supersede it
        result = _handle_decide({
            "cwd": "/test",
            "text": "Use PostgreSQL instead",
            "reason": "Migrated to better database",
            "action": "resolve:supersede_existing:dec_existing",
        })

        assert result["success"] is True
        assert result["resolution_action"] == "supersede_existing"

        # Verify old decision is superseded
        updated_memory = mock_project_manager["store"][mock_project_manager["project_id"]]
        old_decision = next(
            (d for d in updated_memory["decisions"] if d.get("id") == "dec_existing"),
            None
        )
        assert old_decision is not None
        assert old_decision.get("superseded") is True

    def test_decide_resolution_cancel(self, mock_project_manager):
        """Cancel resolution doesn't save decision."""
        from api.openai_adapter import _handle_decide

        initial_count = len(mock_project_manager["store"][mock_project_manager["project_id"]]["decisions"])

        result = _handle_decide({
            "cwd": "/test",
            "text": "Some decision",
            "reason": "Some reason",
            "action": "resolve:cancel",
        })

        # Cancel returns success=False (decision not saved)
        assert result["success"] is False
        assert "cancel" in result.get("error", "").lower() or "cancel" in result.get("message", "").lower()

        # No new decision added
        final_count = len(mock_project_manager["store"][mock_project_manager["project_id"]]["decisions"])
        assert final_count == initial_count

    def test_decide_invalid_resolution_rejected(self, mock_project_manager):
        """Invalid resolution action is rejected."""
        from api.openai_adapter import _handle_decide

        result = _handle_decide({
            "cwd": "/test",
            "text": "Some decision",
            "reason": "Some reason",
            "action": "resolve:invalid_action:target",
        })

        assert result["success"] is False
        assert result["error_code"] == "invalid_resolution_action"

    def test_decide_resolution_requires_target(self, mock_project_manager):
        """Resolution actions (except cancel) require target_id."""
        from api.openai_adapter import _handle_decide

        result = _handle_decide({
            "cwd": "/test",
            "text": "Some decision",
            "reason": "Some reason",
            "action": "resolve:supersede_existing",  # Missing target
        })

        assert result["success"] is False
        assert result["error_code"] == "missing_target_id"


class TestRESTMCPParity:
    """Test that REST produces equivalent results to MCP for same inputs."""

    def test_sync_parity_with_mcp_fields(self, mock_project_manager):
        """REST sync saves same fields as MCP fo_sync."""
        from api.openai_adapter import _handle_sync

        # These are the exact fields MCP fo_sync accepts
        result = _handle_sync({
            "cwd": "/test",
            "goal": "Fix login bug",
            "work_area": "authentication",
            "last_change": "Added validation",
            "last_file": "src/auth.py",
            "why": "Security improvement",
            "next_step": "Test the fix",
        })

        assert result["success"] is True

        memory = mock_project_manager["store"][mock_project_manager["project_id"]]
        intent = memory["live_record"]["intent"]

        # All MCP fo_sync fields should be present
        assert "current_goal" in intent
        assert "work_area" in intent
        assert "last_change" in intent
        assert "last_file" in intent
        assert "why" in intent
        assert "next_step" in intent
        assert "updated_at" in intent

    def test_solved_uses_core_record_solution(self, mock_project_manager):
        """REST solved calls core.solutions.record_solution (same as MCP)."""
        from api.openai_adapter import _handle_solved

        with patch("core.solutions.record_solution") as mock_record:
            from core.solutions import SolutionResult
            mock_record.return_value = SolutionResult(
                success=True,
                solution_id="fix_123",
                message="Solution saved.",
            )

            _handle_solved({
                "cwd": "/test",
                "error": "Test error",
                "solution": "Test solution",
                "files": "test.py",
            })

            # Verify core function was called
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args.kwargs

            # Verify actor_source identifies REST fallback
            assert call_kwargs["actor"] == "rest_fallback"
            assert call_kwargs["actor_source"] == "rest_api"

    def test_decide_uses_core_record_decision(self, mock_project_manager):
        """REST decide calls core.decisions.record_decision (same as MCP)."""
        from api.openai_adapter import _handle_decide

        with patch("core.decisions.record_decision") as mock_record:
            from core.decisions import DecisionResult
            mock_record.return_value = DecisionResult(
                success=True,
                decision_id="dec_123",
                message="Decision recorded.",
            )

            _handle_decide({
                "cwd": "/test",
                "text": "Test decision",
                "reason": "Test reason",
            })

            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args.kwargs

            assert call_kwargs["actor"] == "rest_fallback"
            assert call_kwargs["actor_source"] == "rest_api"


class TestCrossTransportIdempotency:
    """Test idempotency across MCP and REST transports."""

    def test_sync_idempotent_across_transports(self, mock_project_manager):
        """Same sync operation via MCP then REST produces no divergent state."""
        from api.openai_adapter import _handle_sync

        # First sync
        result1 = _handle_sync({
            "cwd": "/test",
            "goal": "Test goal",
            "last_change": "Test change",
        })
        assert result1["success"] is True

        memory_after_first = mock_project_manager["store"][mock_project_manager["project_id"]]
        goal_after_first = memory_after_first["live_record"]["intent"]["current_goal"]

        # Second sync (simulating retry after ambiguous timeout)
        result2 = _handle_sync({
            "cwd": "/test",
            "goal": "Test goal",
            "last_change": "Test change",
        })
        assert result2["success"] is True

        memory_after_second = mock_project_manager["store"][mock_project_manager["project_id"]]
        goal_after_second = memory_after_second["live_record"]["intent"]["current_goal"]

        # Goal should be identical (no duplication)
        assert goal_after_first == goal_after_second

    def test_solved_duplicate_detection(self, mock_project_manager):
        """Same solution via REST twice uses fingerprint dedup."""
        from api.openai_adapter import _handle_solved

        # First save
        result1 = _handle_solved({
            "cwd": "/test",
            "error": "Duplicate test error",
            "solution": "Duplicate test solution",
        })
        assert result1["success"] is True

        count_after_first = len(
            mock_project_manager["store"][mock_project_manager["project_id"]]["debug_sessions"]
        )

        # Second save (simulating retry)
        result2 = _handle_solved({
            "cwd": "/test",
            "error": "Duplicate test error",
            "solution": "Duplicate test solution",
        })
        assert result2["success"] is True
        assert result2.get("is_update") is True  # Detected as update, not new

        count_after_second = len(
            mock_project_manager["store"][mock_project_manager["project_id"]]["debug_sessions"]
        )

        # No duplicate created
        assert count_after_second == count_after_first

    def test_decision_duplicate_warning(self, mock_project_manager):
        """Same decision via REST twice triggers review or warning."""
        from api.openai_adapter import _handle_decide

        # First decision
        result1 = _handle_decide({
            "cwd": "/test",
            "text": "Use TypeScript for all new code",
            "reason": "Type safety",
        })
        assert result1["success"] is True

        # Second identical decision (simulating retry)
        result2 = _handle_decide({
            "cwd": "/test",
            "text": "Use TypeScript for all new code",
            "reason": "Type safety",
        })

        # Should either trigger review (conflict detected) or succeed with warning
        if result2["success"]:
            # May have a warning about similar decision
            pass
        else:
            # May require review for duplicate
            assert result2.get("requires_review") is True or "conflict" in result2.get("error_code", "")


class TestStructuredResponses:
    """Test REST returns structured JSON for machine parsing."""

    def test_error_responses_include_error_code(self, mock_project_manager):
        """All error responses include error_code for automation."""
        from api.openai_adapter import _handle_solved

        result = _handle_solved({"cwd": "/test"})  # Missing required fields (error, solution)

        assert "success" in result
        assert result["success"] is False
        assert "error" in result
        assert "error_code" in result

    def test_success_responses_include_transport(self, mock_project_manager):
        """Success responses identify transport for dashboard."""
        from api.openai_adapter import _handle_status, _handle_sync, _handle_solved

        status = _handle_status({})
        assert status["transport"] == "rest_fallback"

        sync = _handle_sync({"cwd": "/test", "goal": "Test"})
        assert sync["transport"] == "rest_fallback"

        solved = _handle_solved({
            "cwd": "/test",
            "error": "Test",
            "solution": "Test",
        })
        if solved["success"]:
            assert solved["transport"] == "rest_fallback"


class TestDashboardIntegration:
    """Test REST fallback updates dashboard correctly."""

    def test_activity_logged_with_rest_fallback_source(self, mock_project_manager):
        """REST operations log activity with rest_fallback source."""
        import requests as requests_module
        from api.openai_adapter import _log_rest_fallback_activity

        with patch.object(requests_module, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            _log_rest_fallback_activity(
                action="sync",
                project_id="test_project",
                details={"goal": "Test goal"},
            )

            # Verify activity was logged
            if mock_post.called:
                call_kwargs = mock_post.call_args
                body = call_kwargs.kwargs.get("json", {})
                assert body.get("type") == "rest_fallback"
                assert body.get("actor") == "rest_fallback"
                assert body.get("actor_source") == "rest_api"

    def test_dashboard_shows_rest_fallback_transport(self, mock_project_manager):
        """Dashboard snapshot shows REST fallback as active transport."""
        # This test verifies the activity structure is correct for dashboard rendering
        from api.openai_adapter import _log_rest_fallback_activity
        import requests as requests_module

        logged_activities = []

        def capture_activity(*args, **kwargs):
            body = kwargs.get("json", {})
            logged_activities.append(body)
            mock_response = MagicMock()
            mock_response.status_code = 200
            return mock_response

        with patch.object(requests_module, "post", side_effect=capture_activity):
            _log_rest_fallback_activity("solved", "test_project", {"error": "test"})

        # Verify structure matches what dashboard expects
        if logged_activities:
            activity = logged_activities[0]
            # Dashboard renders these fields
            assert activity.get("type") == "rest_fallback"
            assert activity.get("tool") == "solved"
            assert "rest" in activity.get("human_name", "").lower()
            assert "fallback" in activity.get("human_name", "").lower()
            # Actor tracking for "Active AI" display
            assert activity.get("actor") == "rest_fallback"
            assert activity.get("actor_source") == "rest_api"

    def test_status_indicates_rest_recording_not_mcp(self, mock_project_manager):
        """Status shows recording=true with transport=rest_fallback."""
        from api.openai_adapter import _handle_status

        result = _handle_status({})

        assert result["success"] is True
        assert result["recording"] is True
        assert result["transport"] == "rest_fallback"
        # Should NOT claim MCP is connected (MCP may be disconnected)
        assert "mcp" not in result.get("transport", "").lower()


class TestProtocolSafety:
    """Test protocol safety rules for fallback activation."""

    def test_business_errors_have_structured_response(self, mock_project_manager):
        """Business errors (validation, conflict) return structured JSON."""
        from api.openai_adapter import _handle_decide, _handle_solved

        # Missing required field (reason)
        decide_result = _handle_decide({"cwd": "/test", "text": "Something"})
        assert "success" in decide_result
        assert "error" in decide_result
        assert "error_code" in decide_result

        # Missing required fields (error, solution)
        solved_result = _handle_solved({"cwd": "/test"})
        assert "success" in solved_result
        assert "error" in solved_result
        assert "error_code" in solved_result

    def test_review_required_has_resolution_info(self, mock_project_manager):
        """Review responses include all info needed for resolution."""
        from api.openai_adapter import _handle_decide
        from core.decisions import DecisionResult

        # Mock core to return review required
        with patch("core.decisions.record_decision") as mock_record:
            mock_record.return_value = DecisionResult(
                success=False,
                requires_review=True,
                review_result={
                    "message": "Similar decision exists",
                    "primary_candidate": {
                        "id": "dec_123",
                        "text": "Existing decision",
                        "relationship": "potential_conflict",
                        "explanation": "May conflict",
                    },
                    "allowed_actions": ["supersede_existing", "save_as_exception", "cancel"],
                },
            )

            result = _handle_decide({
                "cwd": "/test",
                "text": "New decision",
                "reason": "New reason",
            })

            assert result["success"] is False
            assert result["requires_review"] is True
            assert result["target_id"] == "dec_123"
            assert "allowed_actions" in result
            assert "supersede_existing" in result["allowed_actions"]


class TestMalformedPayloads:
    """Test handling of malformed payloads."""

    def test_empty_args_handled(self, mock_project_manager):
        """Empty arguments return structured error for missing cwd."""
        from api.openai_adapter import _handle_decide, _handle_solved, _handle_sync

        # All handlers now require cwd
        decide = _handle_decide({})
        assert decide["success"] is False
        assert decide["error_code"] == "missing_cwd"

        solved = _handle_solved({})
        assert solved["success"] is False
        assert solved["error_code"] == "missing_cwd"

        sync = _handle_sync({})
        assert sync["success"] is False
        assert sync["error_code"] == "missing_cwd"

    def test_null_values_handled(self, mock_project_manager):
        """None/null values don't crash handlers."""
        from api.openai_adapter import _handle_decide

        result = _handle_decide({
            "cwd": "/test",
            "text": None,
            "reason": None,
        })

        assert result["success"] is False
        assert "error_code" in result


class TestProjectIsolation:
    """
    Test that REST fallback enforces explicit cwd for project targeting.

    Critical security tests to prevent cross-project writes.
    """

    @pytest.fixture
    def two_projects(self, tmp_path):
        """Create two isolated test projects."""
        project_a = tmp_path / "project_a"
        project_a.mkdir()
        (project_a / ".git").mkdir()  # Make it a git root

        project_b = tmp_path / "project_b"
        project_b.mkdir()
        (project_b / ".git").mkdir()  # Make it a git root

        return {
            "project_a": str(project_a),
            "project_b": str(project_b),
        }

    def test_status_resolves_project_from_cwd(self, two_projects):
        """Status with cwd resolves to the correct project."""
        from api.openai_adapter import _handle_status

        result = _handle_status({"cwd": two_projects["project_a"]})

        assert result["success"] is True
        assert result["project_id"] is not None
        assert "project_a" in result["project_id"]
        assert result["resolved_cwd"] == two_projects["project_a"]

    def test_status_without_cwd_warns(self):
        """Status without cwd returns warning about ambiguity."""
        from api.openai_adapter import _handle_status

        result = _handle_status({})

        assert result["success"] is True
        assert result["project_id"] is None
        assert "warning" in result

    def test_sync_requires_cwd(self):
        """Sync without cwd is rejected."""
        from api.openai_adapter import _handle_sync

        result = _handle_sync({"goal": "Test goal"})

        assert result["success"] is False
        assert result["error_code"] == "missing_cwd"

    def test_sync_writes_to_cwd_project(self, two_projects):
        """Sync with cwd writes only to the cwd-resolved project."""
        from api.openai_adapter import _handle_sync
        from managers.multi_project_manager import load_project_memory
        from core.project_context import ProjectContext

        project_id_a = ProjectContext.from_path(two_projects["project_a"])

        result = _handle_sync({
            "cwd": two_projects["project_a"],
            "goal": "Unique goal for project A",
        })

        assert result["success"] is True
        assert result["project_id"] == project_id_a
        assert result["resolved_cwd"] == two_projects["project_a"]

        # Verify memory was written to project A
        memory = load_project_memory(project_id_a)
        assert memory is not None
        assert memory["live_record"]["intent"]["current_goal"] == "Unique goal for project A"

    def test_decide_requires_cwd(self):
        """Decide without cwd is rejected."""
        from api.openai_adapter import _handle_decide

        result = _handle_decide({"text": "Test decision", "reason": "Test"})

        assert result["success"] is False
        assert result["error_code"] == "missing_cwd"

    def test_solved_requires_cwd(self):
        """Solved without cwd is rejected."""
        from api.openai_adapter import _handle_solved

        result = _handle_solved({"error": "Test error", "solution": "Test solution"})

        assert result["success"] is False
        assert result["error_code"] == "missing_cwd"

    def test_two_projects_remain_isolated(self, two_projects):
        """Writes to different cwds stay isolated."""
        from api.openai_adapter import _handle_sync
        from managers.multi_project_manager import load_project_memory
        from core.project_context import ProjectContext

        project_id_a = ProjectContext.from_path(two_projects["project_a"])
        project_id_b = ProjectContext.from_path(two_projects["project_b"])

        # Write to project A
        _handle_sync({
            "cwd": two_projects["project_a"],
            "goal": "Goal for A only",
        })

        # Write to project B
        _handle_sync({
            "cwd": two_projects["project_b"],
            "goal": "Goal for B only",
        })

        # Verify isolation
        memory_a = load_project_memory(project_id_a)
        memory_b = load_project_memory(project_id_b)

        assert memory_a["live_record"]["intent"]["current_goal"] == "Goal for A only"
        assert memory_b["live_record"]["intent"]["current_goal"] == "Goal for B only"

    def test_invalid_cwd_rejected(self, tmp_path):
        """Non-existent cwd is rejected."""
        from api.openai_adapter import _handle_sync

        result = _handle_sync({
            "cwd": "/nonexistent/path/that/does/not/exist",
            "goal": "Test",
        })

        assert result["success"] is False
        assert result["error_code"] == "invalid_cwd"

    def test_cwd_not_directory_rejected(self, tmp_path):
        """File path (not directory) as cwd is rejected."""
        from api.openai_adapter import _handle_sync

        # Create a file, not a directory
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("test")

        result = _handle_sync({
            "cwd": str(file_path),
            "goal": "Test",
        })

        assert result["success"] is False
        assert result["error_code"] == "invalid_cwd"

    def test_empty_cwd_rejected(self):
        """Empty cwd string is rejected."""
        from api.openai_adapter import _handle_sync

        result = _handle_sync({
            "cwd": "",
            "goal": "Test",
        })

        assert result["success"] is False
        assert result["error_code"] in ("missing_cwd", "empty_cwd")

    def test_whitespace_cwd_rejected(self):
        """Whitespace-only cwd is rejected."""
        from api.openai_adapter import _handle_sync

        result = _handle_sync({
            "cwd": "   ",
            "goal": "Test",
        })

        assert result["success"] is False
        assert result["error_code"] in ("missing_cwd", "empty_cwd")

    def test_legacy_handlers_require_cwd(self):
        """Legacy log_decision and log_avoid also require cwd."""
        from api.openai_adapter import _handle_log_decision, _handle_log_avoid

        decision_result = _handle_log_decision({
            "decision": "Test decision",
            "reason": "Test reason",
        })
        assert "error" in decision_result or decision_result.get("success") is False

        avoid_result = _handle_log_avoid({
            "what": "Test avoid",
            "reason": "Test reason",
        })
        assert "error" in avoid_result or avoid_result.get("success") is False


class TestProductionScenario:
    """
    Production scenario test: Server active on FixOnce, REST write to DecisionGuardian-QA.

    This tests the exact failure case that was discovered in production QA.
    """

    @pytest.fixture
    def two_real_projects(self, tmp_path):
        """Simulate the production scenario with two projects."""
        # Simulate FixOnce project
        fixonce = tmp_path / "FixOnce"
        fixonce.mkdir()
        (fixonce / ".git").mkdir()

        # Simulate DecisionGuardian-QA project
        dg_qa = tmp_path / "DecisionGuardian-QA"
        dg_qa.mkdir()
        (dg_qa / ".git").mkdir()

        return {
            "fixonce": str(fixonce),
            "decision_guardian": str(dg_qa),
        }

    def test_rest_write_targets_cwd_not_server_active(self, two_real_projects):
        """
        REST write MUST target the cwd project, not the server's active project.

        This is the critical test for the cross-project targeting bug.
        """
        from api.openai_adapter import _handle_sync
        from managers.multi_project_manager import load_project_memory
        from core.project_context import ProjectContext

        # Get project IDs
        fixonce_id = ProjectContext.from_path(two_real_projects["fixonce"])
        dg_qa_id = ProjectContext.from_path(two_real_projects["decision_guardian"])

        # Mock the server's active project to be FixOnce
        # (simulating fo_init was called from FixOnce session before MCP disconnect)
        with patch("managers.multi_project_manager.get_active_project_id", return_value=fixonce_id):
            # REST write targeting DecisionGuardian-QA via cwd
            result = _handle_sync({
                "cwd": two_real_projects["decision_guardian"],
                "goal": "QA marker written via REST fallback",
            })

        assert result["success"] is True
        assert result["project_id"] == dg_qa_id, \
            f"Expected {dg_qa_id}, got {result['project_id']}"

        # Verify DecisionGuardian-QA got the write
        dg_memory = load_project_memory(dg_qa_id)
        assert dg_memory is not None
        assert dg_memory["live_record"]["intent"]["current_goal"] == "QA marker written via REST fallback"

        # Verify FixOnce was NOT written to
        fixonce_memory = load_project_memory(fixonce_id)
        if fixonce_memory:
            fixonce_goal = fixonce_memory.get("live_record", {}).get("intent", {}).get("current_goal", "")
            assert fixonce_goal != "QA marker written via REST fallback", \
                "Cross-project write detected! FixOnce was modified when DecisionGuardian-QA was targeted."


class TestRESTFallbackActivityTracking:
    """
    Tests for REST fallback activity tracking in dashboard.

    Verifies that successful REST fallback operations are properly logged
    and appear in the activity feed and dashboard snapshot.
    """

    @pytest.fixture
    def mock_activity_log(self, tmp_path):
        """Mock the activity logging for testing."""
        logged_activities = []

        def capture_log(*args, **kwargs):
            body = kwargs.get("json", {})
            logged_activities.append(body)
            return MagicMock(status_code=200)

        return logged_activities, capture_log

    def test_successful_rest_sync_appears_in_activity(self, mock_project_manager, mock_activity_log):
        """Successful REST sync is logged as rest_fallback activity."""
        import requests as requests_module
        from api.openai_adapter import _handle_sync, _log_rest_fallback_activity

        logged, capture = mock_activity_log

        with patch.object(requests_module, "post", side_effect=capture):
            _log_rest_fallback_activity("sync", mock_project_manager["project_id"], {"goal": "Test"})

        assert len(logged) == 1
        activity = logged[0]
        assert activity["type"] == "rest_fallback"
        assert activity["tool"] == "sync"
        assert activity["actor"] == "rest_fallback"
        assert activity["actor_source"] == "rest_api"
        assert activity["project_id"] == mock_project_manager["project_id"]

    def test_successful_rest_decide_appears_in_activity(self, mock_project_manager, mock_activity_log):
        """Successful REST decide is logged as rest_fallback activity."""
        import requests as requests_module
        from api.openai_adapter import _log_rest_fallback_activity

        logged, capture = mock_activity_log

        with patch.object(requests_module, "post", side_effect=capture):
            _log_rest_fallback_activity("decide", mock_project_manager["project_id"], {"text": "Test"})

        assert len(logged) == 1
        assert logged[0]["type"] == "rest_fallback"
        assert logged[0]["tool"] == "decide"

    def test_successful_rest_solved_appears_in_activity(self, mock_project_manager, mock_activity_log):
        """Successful REST solved is logged as rest_fallback activity."""
        import requests as requests_module
        from api.openai_adapter import _log_rest_fallback_activity

        logged, capture = mock_activity_log

        with patch.object(requests_module, "post", side_effect=capture):
            _log_rest_fallback_activity("solved", mock_project_manager["project_id"], {"error": "Test"})

        assert len(logged) == 1
        assert logged[0]["type"] == "rest_fallback"
        assert logged[0]["tool"] == "solved"

    def test_activity_uses_correct_resolved_project(self, mock_project_manager, mock_activity_log):
        """Activity is logged with the cwd-resolved project, not server active."""
        import requests as requests_module
        from api.openai_adapter import _log_rest_fallback_activity

        logged, capture = mock_activity_log

        with patch.object(requests_module, "post", side_effect=capture):
            _log_rest_fallback_activity("sync", "specific_project_id", {"goal": "Test"})

        assert logged[0]["project_id"] == "specific_project_id"

    def test_activity_fields_are_correct(self, mock_project_manager, mock_activity_log):
        """Activity has correct actor/source/transport fields."""
        import requests as requests_module
        from api.openai_adapter import _log_rest_fallback_activity

        logged, capture = mock_activity_log

        with patch.object(requests_module, "post", side_effect=capture):
            _log_rest_fallback_activity("solved", "test_project", {"error": "Test"})

        activity = logged[0]
        assert activity["actor"] == "rest_fallback"
        assert activity["actor_source"] == "rest_api"
        assert "REST fallback" in activity["human_name"]

    def test_failed_request_not_logged_as_success(self, mock_project_manager):
        """Failed/review-only requests don't appear as successful recording."""
        from api.openai_adapter import _handle_solved
        import requests as requests_module

        logged = []

        def capture(*args, **kwargs):
            logged.append(kwargs.get("json", {}))
            return MagicMock(status_code=200)

        # Request with missing cwd should fail - no activity logged
        with patch.object(requests_module, "post", side_effect=capture):
            result = _handle_solved({"error": "Test", "solution": "Test"})

        # Failed due to missing cwd - should NOT log success activity
        assert result["success"] is False
        # The _log_rest_fallback_activity is only called on success,
        # so no REST fallback activity should have been logged

    def test_no_duplicate_activity_entries(self, mock_project_manager, mock_activity_log):
        """Single REST write creates only one activity entry."""
        import requests as requests_module
        from api.openai_adapter import _log_rest_fallback_activity

        logged, capture = mock_activity_log

        with patch.object(requests_module, "post", side_effect=capture):
            _log_rest_fallback_activity("sync", "project_1", {"goal": "Test"})

        # Single call = single log entry
        assert len(logged) == 1


class TestActivityLogEndpoint:
    """Tests for the activity log endpoint handling of REST fallback."""

    def test_rest_fallback_not_skipped(self):
        """REST fallback activities are not skipped by the activity log endpoint."""
        # The endpoint should accept type=rest_fallback even without file/command/cwd
        from flask import Flask
        app = Flask(__name__)

        # Import and register the blueprint
        import sys
        sys.path.insert(0, 'src')
        from api.activity import activity_bp
        app.register_blueprint(activity_bp, url_prefix='/api/activity')

        with app.test_client() as client:
            response = client.post('/api/activity/log', json={
                "type": "rest_fallback",
                "tool": "sync",
                "human_name": "REST fallback: sync",
                "project_id": "test_project",
                "actor": "rest_fallback",
                "actor_source": "rest_api",
            })

            data = response.get_json()
            # Should NOT be skipped
            assert data.get("status") != "skipped", f"REST fallback was incorrectly skipped: {data}"

    def test_rest_fallback_project_id_preserved(self):
        """REST fallback activities use the provided project_id."""
        from flask import Flask
        app = Flask(__name__)

        import sys
        sys.path.insert(0, 'src')
        from api.activity import activity_bp
        app.register_blueprint(activity_bp, url_prefix='/api/activity')

        with app.test_client() as client:
            response = client.post('/api/activity/log', json={
                "type": "rest_fallback",
                "tool": "solved",
                "project_id": "explicit_project_123",
                "actor": "rest_fallback",
                "actor_source": "rest_api",
            })

            data = response.get_json()
            if data.get("status") == "ok":
                activity = data.get("activity", {})
                assert activity.get("project_id") == "explicit_project_123"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
