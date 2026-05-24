#!/usr/bin/env python3
"""Runtime wiring tests for Stage 8 agent-aware evaluation."""

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

from core.agent_audit import clear_agent_audit, get_agent_audit
import mcp_memory_server_v2 as server


class TestAgentRuntime(unittest.TestCase):
    def setUp(self):
        clear_agent_audit()

    def test_error_gate_bridge_records_agent_audit_without_changing_level(self):
        with patch.object(server, "_agent_intervention_available", True), \
             patch.object(server, "build_agent_context", return_value=server.AgentContext(
                 actor_name="codex",
                 actor_source="client_actor",
                 actor_confidence=0.9,
                 tool_name="fo_errors",
                 intent="inspect browser failures",
                 session_id="sess-rt-1",
                 project_id="proj-rt-1",
             )):
            result = server._evaluate_current_error_gate(
                tool_name="fo_errors",
                live_errors=2,
                auto_fix_ready=False,
            )

        self.assertEqual(result.level, "warn")
        entries = get_agent_audit(limit=10)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["gate"], "error_gate")
        self.assertEqual(entries[0]["verdict"], "warn")
        self.assertEqual(entries[0]["tool_name"], "fo_errors")

    def test_runtime_gate_stores_last_agent_intervention_snapshot(self):
        with patch.object(server, "_agent_intervention_available", True), \
             patch.object(server, "build_agent_context", return_value=server.AgentContext(
                 actor_name="codex",
                 actor_source="env_var",
                 actor_confidence=0.92,
                 tool_name="fo_sync",
                 intent="sync closure state",
                 session_id="sess-rt-2",
                 project_id="proj-rt-2",
             )):
            result = server._evaluate_current_completion_gate(
                tool_name="fo_sync",
                significant_work_completed=True,
                sync_recorded=False,
            )

        self.assertEqual(result.level, "warn")
        snapshot = server._compliance_state["last_agent_intervention"]
        self.assertEqual(snapshot["tool_name"], "fo_sync")
        self.assertEqual(snapshot["verdict"], "warn")
        self.assertEqual(snapshot["actor_name"], "codex")
        self.assertEqual(snapshot["project_id"], "proj-rt-2")


if __name__ == "__main__":
    unittest.main()
