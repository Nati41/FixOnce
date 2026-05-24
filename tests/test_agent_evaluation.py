#!/usr/bin/env python3
"""Stage 8 evaluation path tests for intent and audit coverage."""

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

from core.agent_context import classify_agent_intent
import mcp_memory_server_v2 as server


class TestAgentEvaluation(unittest.TestCase):
    def test_intent_classification_covers_stage8_examples(self):
        self.assertEqual(classify_agent_intent("fo_errors", "inspect runtime")[0], "read")
        self.assertEqual(classify_agent_intent("log_decision", "architecture choice")[0], "decision")
        self.assertEqual(classify_agent_intent("fo_search", "find prior fix")[0], "search")
        self.assertEqual(classify_agent_intent("fo_sync", "persist current state")[0], "sync")
        self.assertEqual(classify_agent_intent("fo_apply", "patch known issue")[0], "apply_fix")
        self.assertEqual(classify_agent_intent("custom_writer", "edit source")[0], "write")
        self.assertEqual(classify_agent_intent("fo_component", "close component work")[0], "completion")

    def test_build_agent_context_uses_intervention_context_for_completion_intent(self):
        session = server.SessionContext(project_id="proj-eval-1", working_dir="/tmp/demo")
        session.initialized_at = "2026-05-24T12:00:00"

        with patch.object(server, "_get_session", return_value=session), \
             patch.object(server, "_resolve_actor_identity", return_value={
                 "editor": "codex",
                 "source": "parent_process",
                 "confidence": 0.9,
             }):
            ctx = server.build_agent_context(
                "fo_apply",
                intervention_ctx=server.InterventionContext(
                    tool_name="fo_apply",
                    bug_fix_completed=True,
                    fo_solved_called=False,
                ),
                flow_classification="migrated",
            )

        self.assertEqual(ctx.intent, "apply_fix")
        self.assertEqual(ctx.flow_classification, "migrated")

    def test_risk_gate_runtime_flow_records_codex_write_intent(self):
        with patch.object(server, "_agent_intervention_available", True), \
             patch.object(server, "build_agent_context", return_value=server.AgentContext(
                 actor_name="codex",
                 actor_source="parent_process",
                 actor_confidence=0.9,
                 tool_name="update_live_record",
                 intent="write",
                 session_id="sess-eval-2",
                 project_id="proj-eval-2",
                 intent_detail="update goal despite blocked component",
                 flow_classification="migrated",
             )):
            result = server._evaluate_current_risk_gate(
                tool_name="update_live_record",
                blocked_components_relevant=1,
            )

        self.assertEqual(result.level, "warn")


if __name__ == "__main__":
    unittest.main()
