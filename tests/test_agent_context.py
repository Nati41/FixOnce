#!/usr/bin/env python3
"""Tests for the Stage 8 agent identity model."""

import sys
import os
import json
import tempfile
import contextlib
import io
import time
import types
import unittest
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

from core.agent_context import AgentContext
import core.mcp_session_health as session_health
import mcp_memory_server_v2 as server


class TestAgentContext(unittest.TestCase):
    def test_fixonce_actor_env_resolves_codex_client_actor(self):
        with patch.dict(os.environ, {"FIXONCE_ACTOR": "codex"}, clear=True):
            identity = server._resolve_actor_identity()

        self.assertEqual(identity["editor"], "codex")
        self.assertEqual(identity["source"], "client_actor")
        self.assertEqual(identity["confidence"], 1.0)

    def test_windows_like_no_env_no_parent_probe_resolves_unknown(self):
        with tempfile.TemporaryDirectory() as temp_home:
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(server, "_get_parent_process_command", return_value=""), \
                 patch.object(server.Path, "home", return_value=Path(temp_home)):
                identity = server._resolve_actor_identity()

        self.assertEqual(identity["editor"], "unknown")
        self.assertEqual(identity["source"], "none")
        self.assertEqual(identity["confidence"], 0.0)

    def test_unknown_actor_connection_does_not_fallback_to_claude(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            connections_file = Path(temp_dir) / "ai_connections.json"

            with patch.object(server, "AI_CONNECTIONS_FILE", connections_file):
                server._persist_ai_connection({
                    "editor": "unknown",
                    "source": "none",
                    "confidence": 0.0,
                }, project_id="proj-unknown")

            data = json.loads(connections_file.read_text(encoding="utf-8"))

        self.assertIn("unknown", data["clients"])
        self.assertNotIn("claude", data["clients"])
        self.assertEqual(data["clients"]["unknown"]["actor_source"], "none")

    def test_safe_tool_handler_returns_error_instead_of_raising(self):
        def boom():
            raise RuntimeError("transport should stay open")

        result = server._run_tool_body("boom_tool", boom)

        self.assertIn("FixOnce MCP tool error in boom_tool", result)
        self.assertIn("RuntimeError", result)

    def test_safe_tool_handler_returns_friendly_text_after_transport_loss_threshold(self):
        def transport_closed():
            raise RuntimeError("Transport closed")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "mcp_session_health.json"
            log_file = Path(temp_dir) / "logs" / "mcp_session_health.jsonl"
            with patch.object(session_health, "STATE_FILE", state_file), \
                 patch.object(session_health, "LOG_FILE", log_file), \
                 patch.object(server, "_mcp_actor_for_health", return_value={"editor": "unknown", "source": "none"}):
                server._run_tool_body("lost_tool", transport_closed)
                result = server._run_tool_body("lost_tool", transport_closed)

        self.assertIn("FixOnce lost the MCP connection", result)
        self.assertNotEqual(result, "Transport closed")

    def test_safe_tool_handler_redirects_stdout_to_stderr(self):
        def noisy():
            print("stdout pollution")
            return "ok"

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = server._run_tool_body("noisy_tool", noisy)

        self.assertEqual(result, "ok")
        self.assertEqual(stdout.getvalue(), "")

    def test_successful_shortcut_tool_refreshes_project_agent_presence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            connections_file = temp_root / "ai_connections.json"
            state_file = temp_root / "mcp_session_health.json"
            log_file = temp_root / "logs" / "mcp_session_health.jsonl"
            session = server.SessionContext(project_id="proj-shortcut", working_dir=temp_dir)
            session.mark_initialized()

            with patch.object(server, "AI_CONNECTIONS_FILE", connections_file), \
                 patch.object(session_health, "STATE_FILE", state_file), \
                 patch.object(session_health, "LOG_FILE", log_file), \
                 patch.object(server, "_get_session", return_value=session), \
                 patch.object(server, "_mcp_actor_for_health", return_value={
                     "editor": "codex",
                     "source": "client_actor",
                     "confidence": 1.0,
                 }):
                server._record_mcp_tool_success("fo_search", wait_seconds=1)

            connection = json.loads(connections_file.read_text(encoding="utf-8"))["clients"]["codex"]
            health = json.loads(state_file.read_text(encoding="utf-8"))

        self.assertEqual(connection["project_id"], "proj-shortcut")
        self.assertEqual(connection["actor_confidence"], 1.0)
        self.assertEqual(health["last_tool"], "fo_search")
        self.assertEqual(health["last_actor"], "codex")

    def test_tool_timeout_returns_structured_error_quickly(self):
        def slow():
            time.sleep(0.2)
            return "late"

        started = time.monotonic()
        result = server._run_tool_with_timeout("slow_tool", slow, 0.01)
        elapsed = time.monotonic() - started

        self.assertIn("FixOnce MCP tool timeout in slow_tool", result)
        self.assertLess(elapsed, 0.15)

    def test_fo_sync_lightweight_updates_project_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            projects_dir = temp_root / "projects_v2"
            projects_dir.mkdir()
            project_id = "proj_sync"
            project_file = projects_dir / f"{project_id}.json"
            project_file.write_text(json.dumps({"live_record": {"intent": {}}}), encoding="utf-8")
            session_file = temp_root / "mcp_session.json"
            compliance_file = temp_root / "mcp_compliance.json"

            with patch.object(server, "DATA_DIR", projects_dir), \
                 patch.object(server, "SESSION_FILE", session_file), \
                 patch.object(server, "COMPLIANCE_FILE", compliance_file), \
                 patch.object(server, "_resolve_actor_identity", return_value={
                     "editor": "codex",
                     "source": "client_actor",
                     "confidence": 1.0,
                 }):
                server._set_session(project_id, temp_dir)
                server._persist_session(project_id, temp_dir)
                server._mark_session_initialized()

                result = server.fo_sync(goal="בדיקת סנכרון", next_step="המשך בדיקה")

            data = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertTrue(
            result.startswith("✓ Context synced"),
            f"fo_sync should return rich feedback starting with '✓ Context synced', got: {result[:50]}"
        )
        self.assertEqual(data["live_record"]["intent"]["current_goal"], "בדיקת סנכרון")
        self.assertEqual(data["live_record"]["intent"]["next_step"], "המשך בדיקה")
        self.assertEqual(data["live_record"]["intent"]["actor"], "codex")
        self.assertEqual(data["live_record"]["intent"]["actor_source"], "client_actor")
        self.assertEqual(data["live_record"]["intent"]["actor_confidence"], 1.0)
        self.assertEqual(data["live_record"]["intent"]["tool_name"], "fo_sync")

    def test_agent_context_fields_are_preserved(self):
        ctx = AgentContext(
            actor_name="codex",
            actor_source="session_registry",
            actor_confidence=0.93,
            tool_name="fo_apply",
            intent="apply_fix",
            session_id="sess-1",
            project_id="proj-1",
            intent_detail="close known error path",
            flow_classification="migrated",
        )

        self.assertEqual(ctx.actor_name, "codex")
        self.assertEqual(ctx.actor_source, "session_registry")
        self.assertEqual(ctx.actor_confidence, 0.93)
        self.assertEqual(ctx.tool_name, "fo_apply")
        self.assertEqual(ctx.intent, "apply_fix")
        self.assertEqual(ctx.intent_detail, "close known error path")
        self.assertEqual(ctx.session_id, "sess-1")
        self.assertEqual(ctx.project_id, "proj-1")
        self.assertEqual(ctx.flow_classification, "migrated")

    def test_build_agent_context_uses_detected_actor(self):
        session = server.SessionContext(project_id="proj-1", working_dir="/tmp/demo")
        session.initialized_at = "2026-05-24T10:00:00"

        with patch.object(server, "_get_session", return_value=session), \
             patch.object(server, "_resolve_actor_identity", return_value={
                 "editor": "codex",
                 "source": "env_var",
                 "confidence": 0.95,
             }), \
             patch.object(server, "_load_project", return_value={
                 "live_record": {"intent": {"current_goal": "Test runtime wiring"}}
             }):
            ctx = server.build_agent_context("fo_apply", flow_classification="migrated")

        self.assertEqual(ctx.actor_name, "codex")
        self.assertEqual(ctx.actor_source, "env_var")
        self.assertEqual(ctx.actor_confidence, 0.95)
        self.assertEqual(ctx.tool_name, "fo_apply")
        self.assertEqual(ctx.intent, "apply_fix")
        self.assertEqual(ctx.intent_detail, "Test runtime wiring")
        self.assertEqual(ctx.project_id, "proj-1")
        self.assertNotEqual(ctx.session_id, "unknown-session")
        self.assertEqual(ctx.flow_classification, "migrated")

    def test_build_agent_context_uses_unknown_when_actor_missing(self):
        session = server.SessionContext(project_id="proj-2", working_dir="/tmp/demo")
        session.initialized_at = "2026-05-24T11:00:00"

        with patch.object(server, "_get_session", return_value=session), \
             patch.object(server, "_resolve_actor_identity", return_value={
                 "editor": "unknown",
                 "source": "none",
                 "confidence": 0.0,
             }), \
             patch.object(server, "_load_project", return_value={}):
            ctx = server.build_agent_context("fo_sync", intent="Explicit intent", flow_classification="migrated")

        self.assertEqual(ctx.actor_name, "unknown")
        self.assertEqual(ctx.actor_source, "none")
        self.assertEqual(ctx.actor_confidence, 0.0)
        self.assertEqual(ctx.tool_name, "fo_sync")
        self.assertEqual(ctx.intent, "sync")
        self.assertEqual(ctx.intent_detail, "Explicit intent")
        self.assertEqual(ctx.project_id, "proj-2")
        self.assertNotEqual(ctx.session_id, "unknown-session")
        self.assertEqual(ctx.flow_classification, "migrated")


if __name__ == "__main__":
    unittest.main()
