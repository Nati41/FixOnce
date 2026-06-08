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


if __name__ == "__main__":
    unittest.main()
