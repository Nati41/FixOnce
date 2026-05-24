#!/usr/bin/env python3
"""Tests for the Stage 8 agent identity model."""

import sys
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
import mcp_memory_server_v2 as server


class TestAgentContext(unittest.TestCase):
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
