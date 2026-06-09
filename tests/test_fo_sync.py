#!/usr/bin/env python3
"""Regression tests for the fo_sync wrapper bug."""

import sys
import types
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "mcp_server"))


class _FakeFastMCP:
    def __init__(self, *_args, **_kwargs):
        pass

    def tool(self, *_args, **_kwargs):
        def decorator(func):
            return func
        return decorator


sys.modules.setdefault("fastmcp", types.SimpleNamespace(FastMCP=_FakeFastMCP))

import mcp_memory_server_v2 as server
import core.unreported_work as unreported_work


class TestFoSync(unittest.TestCase):
    def _activate_temp_session(self, temp_root: Path, project_id: str = "proj-diet"):
        projects_dir = temp_root / "projects_v2"
        projects_dir.mkdir()
        project_file = projects_dir / f"{project_id}.json"
        project_file.write_text(json.dumps({
            "project_info": {"name": "Diet Test"},
            "live_record": {
                "intent": {"current_goal": "Keep MCP concise"},
                "architecture": {"summary": "Test project", "components": []},
                "lessons": {
                    "insights": [{"text": "MCP Diet v2 kept get_live_record concise"}],
                    "failed_attempts": [],
                },
            },
            "decisions": [],
        }), encoding="utf-8")

        patches = [
            patch.object(server, "DATA_DIR", projects_dir),
            patch.object(server, "SESSION_FILE", temp_root / "mcp_session.json"),
            patch.object(server, "COMPLIANCE_FILE", temp_root / "mcp_compliance.json"),
            patch.object(server, "AI_CONNECTIONS_FILE", temp_root / "ai_connections.json"),
            patch.object(server, "_session_registry_available", False),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        server._set_session(project_id, str(temp_root))
        server._persist_session(project_id, str(temp_root))
        server._mark_session_initialized()
        return project_file

    def test_fo_sync_uses_lightweight_impl_not_decorated_tool_object(self):
        with patch.object(server, "update_work_context", object()), \
             patch.object(server, "_update_work_context_lightweight", return_value="Synced.") as impl_mock:
            result = server.fo_sync(
                goal="Close Stage 8 runtime wiring",
                work_area="agent runtime",
                last_change="Connected runtime audit",
                last_file="src/mcp_server/mcp_memory_server_v2.py",
                why="Keep agent state grounded",
                next_step="Run regression tests",
            )

        impl_mock.assert_called_once_with(
            tool_name="fo_sync",
            current_goal="Close Stage 8 runtime wiring",
            work_area="agent runtime",
            last_change="Connected runtime audit",
            last_file="src/mcp_server/mcp_memory_server_v2.py",
            why="Keep agent state grounded",
            next_step="Run regression tests",
        )
        self.assertEqual(result, "Synced.")

    def test_fo_sync_result_stays_tiny(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))

            result = server.fo_sync(goal="Tiny sync", next_step="Continue")

        self.assertEqual(result, "Synced.")
        self.assertLessEqual(len(result), 16)

    def test_fo_sync_clears_unreported_work_for_current_actor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            self._activate_temp_session(temp_path, project_id="project-1")

            with patch.object(unreported_work, "STATE_FILE", temp_path / "unreported_work.json"), \
                 patch.object(server, "_resolve_actor_identity", return_value={
                     "editor": "codex",
                     "source": "client_actor",
                     "confidence": 1.0,
                 }):
                unreported_work.mark_work("project-1", "codex", "file_write")
                result = server.fo_sync(goal="Sync work", next_step="Continue")
                state = unreported_work.get_state("project-1", "codex")

        self.assertEqual(result, "Synced.")
        self.assertFalse(state["dirty"])
        self.assertEqual(state["last_sync_tool"], "fo_sync")

    def test_fo_search_returns_concise_result_without_status_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))

            with patch.object(server, "_semantic_available", False):
                result = server.fo_search("MCP Diet v2")

        self.assertIn("Found 1 match(es). Best", result)
        self.assertNotIn("📍 **", result)
        self.assertNotIn("────────────────", result)
        self.assertLess(len(result), 320)

    def test_repeated_tool_gate_omits_context_header_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))

            with patch.object(server, "_build_context_header", return_value="HEADER\n") as header_mock:
                error, context = server._universal_gate("update_component_status")

        self.assertIsNone(error)
        self.assertEqual(context, "")
        header_mock.assert_not_called()

    def test_deep_resume_tool_keeps_explicit_context_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))

            with patch.object(server, "_build_context_header", return_value="HEADER\n"):
                result = server.get_live_record()

        self.assertTrue(result.startswith("HEADER\n"))
        self.assertIn('"intent"', result)

    def test_fo_sync_updates_ai_connection_last_seen(self):
        """Regression test: fo_sync must update last_seen for dashboard activity."""
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))

            persist_calls = []

            def track_persist(actor_identity, project_id=None):
                persist_calls.append({
                    "actor": actor_identity,
                    "project_id": project_id,
                })

            with patch.object(server, "_persist_ai_connection", side_effect=track_persist), \
                 patch.object(server, "_resolve_actor_identity", return_value={"editor": "claude"}):
                result = server.fo_sync(goal="Test goal", next_step="Test next")

            self.assertEqual(result, "Synced.")
            # fo_sync may be called through wrapper which can invoke multiple times
            self.assertGreaterEqual(len(persist_calls), 1, "fo_sync must call _persist_ai_connection")
            # Verify at least one call had correct actor
            actors = [c["actor"] for c in persist_calls]
            self.assertIn({"editor": "claude"}, actors)

    def test_fo_sync_enables_dashboard_activity_tracking(self):
        """Verify fo_sync writes data that dashboard can read for activity display."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ai_connections_file = temp_path / "ai_connections.json"

            self._activate_temp_session(temp_path)

            with patch.object(server, "AI_CONNECTIONS_FILE", ai_connections_file), \
                 patch.object(server, "_resolve_actor_identity", return_value={"editor": "test_agent"}):
                server.fo_sync(goal="Dashboard test", last_change="Updated code", next_step="Verify")

            # Verify AI connection file was updated
            self.assertTrue(ai_connections_file.exists(), "AI connections file must be created")
            connections = json.loads(ai_connections_file.read_text())

            # AI connections file uses "clients" key
            self.assertIn("clients", connections)

            # Find our connection
            clients = connections["clients"]
            self.assertIn("test_agent", clients, "fo_sync must update connection for current actor")
            self.assertIn("last_seen", clients["test_agent"])


class TestProtocolReminder(unittest.TestCase):
    def _activate_temp_session(self, temp_root: Path, project_id: str = "proj-reminder"):
        projects_dir = temp_root / "projects_v2"
        projects_dir.mkdir()
        project_file = projects_dir / f"{project_id}.json"
        project_file.write_text(json.dumps({
            "project_info": {"name": "Reminder Test"},
            "live_record": {"intent": {}},
            "decisions": [],
        }), encoding="utf-8")

        patches = [
            patch.object(server, "DATA_DIR", projects_dir),
            patch.object(server, "SESSION_FILE", temp_root / "mcp_session.json"),
            patch.object(server, "COMPLIANCE_FILE", temp_root / "mcp_compliance.json"),
            patch.object(server, "AI_CONNECTIONS_FILE", temp_root / "ai_connections.json"),
            patch.object(server, "_session_registry_available", False),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        server._set_session(project_id, str(temp_root))
        server._persist_session(project_id, str(temp_root))
        server._mark_session_initialized()

    def test_protocol_reminder_appears_at_10_calls(self):
        """Reminder must appear exactly at tool call 10."""
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))
            session = server._get_session()

            # Simulate 9 prior tool calls
            session.tool_calls = ["call"] * 9
            reminder = server._get_protocol_reminder()
            self.assertEqual(reminder, "", "No reminder at 9 calls")

            # 10th call
            session.tool_calls = ["call"] * 10
            reminder = server._get_protocol_reminder()
            self.assertIn("fo_sync()", reminder)
            self.assertIn("fo_solved()", reminder)
            self.assertIn("💾", reminder)

    def test_protocol_reminder_appears_at_20_calls(self):
        """Reminder must appear at multiples of 10."""
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))
            session = server._get_session()

            session.tool_calls = ["call"] * 20
            reminder = server._get_protocol_reminder()
            self.assertIn("fo_sync()", reminder)

    def test_protocol_reminder_absent_at_non_multiples(self):
        """Reminder must NOT appear at non-multiples of 10."""
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))
            session = server._get_session()

            for count in [1, 5, 7, 11, 15, 19, 21, 25]:
                session.tool_calls = ["call"] * count
                reminder = server._get_protocol_reminder()
                self.assertEqual(reminder, "", f"Should be empty at {count} calls")

    def test_protocol_reminder_injected_via_universal_gate(self):
        """Universal gate must inject reminder at 10th call."""
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))
            session = server._get_session()

            # Set to 9 calls, gate will log the 10th
            session.tool_calls = ["call"] * 9

            with patch.object(server, "_resolve_actor_identity", return_value={"editor": "test"}), \
                 patch.object(server, "_persist_ai_connection"):
                error, context = server._universal_gate("fo_search")

            self.assertIsNone(error)
            self.assertIn("fo_sync()", context)
            self.assertIn("fo_solved()", context)

    def test_protocol_reminder_absent_at_9th_call_via_gate(self):
        """Universal gate must NOT inject reminder before 10th call."""
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir))
            session = server._get_session()

            # Set to 8 calls, gate will log the 9th
            session.tool_calls = ["call"] * 8

            with patch.object(server, "_resolve_actor_identity", return_value={"editor": "test"}), \
                 patch.object(server, "_persist_ai_connection"):
                error, context = server._universal_gate("fo_search")

            self.assertIsNone(error)
            self.assertNotIn("fo_sync()", context)


class TestActivityLogPathConsistency(unittest.TestCase):
    """Regression test: activity log writer and dashboard reader must use the same file."""

    def test_activity_writer_and_dashboard_reader_use_same_path(self):
        """
        Verify api/activity.py writes to the same file that api/status.py reads.

        Bug context: activity.py was writing to /FixOnce/data/activity_log.json
        while status.py (dashboard) was reading from ~/.fixonce/activity_log.json.
        This caused dashboard activity to never show up.
        """
        from config import USER_DATA_DIR, DATA_DIR

        # Read activity.py source to verify ACTIVITY_FILE definition
        activity_source = (PROJECT_ROOT / "src" / "api" / "activity.py").read_text()

        # Verify activity.py uses USER_DATA_DIR (not hardcoded path)
        self.assertIn(
            "from config import USER_DATA_DIR",
            activity_source,
            "activity.py must import USER_DATA_DIR from config"
        )
        self.assertIn(
            "ACTIVITY_FILE = USER_DATA_DIR",
            activity_source,
            "activity.py must define ACTIVITY_FILE using USER_DATA_DIR"
        )

        # Verify it does NOT use hardcoded project path
        self.assertNotIn(
            'DATA_DIR = Path(__file__)',
            activity_source,
            "activity.py must NOT use hardcoded DATA_DIR"
        )

        # Dashboard reads from DATA_DIR / "activity_log.json" (see status.py line 1123)
        # config.py sets DATA_DIR = USER_DATA_DIR, so both paths are the same
        self.assertEqual(
            DATA_DIR.resolve(),
            USER_DATA_DIR.resolve(),
            "config.DATA_DIR must equal USER_DATA_DIR for path consistency"
        )

    def test_mcp_server_reads_from_canonical_path(self):
        """Verify MCP server activity log reads use USER_DATA_DIR."""
        canonical = server.USER_DATA_DIR / "activity_log.json"

        # Verify USER_DATA_DIR is the user home .fixonce directory
        self.assertTrue(
            str(server.USER_DATA_DIR).endswith(".fixonce"),
            f"USER_DATA_DIR should end with .fixonce, got {server.USER_DATA_DIR}"
        )

        # Verify canonical path exists or can be created
        self.assertTrue(
            server.USER_DATA_DIR.exists() or server.USER_DATA_DIR.parent.exists(),
            "USER_DATA_DIR parent must exist"
        )


if __name__ == "__main__":
    unittest.main()
