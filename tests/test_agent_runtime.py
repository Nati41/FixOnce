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
                 intent="read",
                 session_id="sess-rt-1",
                 project_id="proj-rt-1",
                 intent_detail="inspect browser failures",
                 flow_classification="migrated",
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
        self.assertEqual(entries[0]["intent"], "read")
        self.assertEqual(entries[0]["flow_classification"], "migrated")

    def test_runtime_gate_stores_last_agent_intervention_snapshot(self):
        with patch.object(server, "_agent_intervention_available", True), \
             patch.object(server, "build_agent_context", return_value=server.AgentContext(
                 actor_name="codex",
                 actor_source="env_var",
                 actor_confidence=0.92,
                 tool_name="fo_sync",
                 intent="sync",
                 session_id="sess-rt-2",
                 project_id="proj-rt-2",
                 intent_detail="sync closure state",
                 flow_classification="migrated",
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
        self.assertEqual(snapshot["intent"], "sync")
        self.assertEqual(snapshot["flow_classification"], "migrated")

    def test_decision_conflict_runtime_flow_is_migrated(self):
        with patch.object(server, "_agent_intervention_available", True), \
             patch.object(server, "build_agent_context", return_value=server.AgentContext(
                 actor_name="claude",
                 actor_source="client_actor",
                 actor_confidence=0.95,
                 tool_name="log_decision",
                 intent="decision",
                 session_id="sess-rt-3",
                 project_id="proj-rt-3",
                 intent_detail="conflicting decision",
                 flow_classification="migrated",
             )):
            result = server._evaluate_current_decision_conflict_gate(
                tool_name="log_decision",
                decision_conflict_severity="high",
                conflicts=[{"severity": "high"}],
                intent="conflicting decision",
            )

        self.assertEqual(result.level, "block")
        entries = get_agent_audit(limit=5)
        self.assertEqual(entries[0]["gate"], "decision_conflict_gate")
        self.assertEqual(entries[0]["intent"], "decision")
        self.assertEqual(entries[0]["flow_classification"], "migrated")

    def test_repeat_bug_runtime_flow_uses_search_intent(self):
        with patch.object(server, "_agent_intervention_available", True), \
             patch.object(server, "build_agent_context", return_value=server.AgentContext(
                 actor_name="codex",
                 actor_source="parent_process",
                 actor_confidence=0.9,
                 tool_name="fo_search",
                 intent="search",
                 session_id="sess-rt-4",
                 project_id="proj-rt-4",
                 intent_detail="find prior solution",
                 flow_classification="migrated",
             )):
            result = server._evaluate_current_repeat_bug_gate(
                tool_name="fo_search",
                similar_past_solution_found=True,
            )

        self.assertEqual(result.level, "warn")
        entry = get_agent_audit(limit=5)[0]
        self.assertEqual(entry["gate"], "repeat_bug_gate")
        self.assertEqual(entry["intent"], "search")

    def test_apply_fix_completion_runtime_flow_records_completion_gate(self):
        with patch.object(server, "_agent_intervention_available", True), \
             patch.object(server, "build_agent_context", return_value=server.AgentContext(
                 actor_name="codex",
                 actor_source="client_actor",
                 actor_confidence=0.93,
                 tool_name="fo_apply",
                 intent="apply_fix",
                 session_id="sess-rt-5",
                 project_id="proj-rt-5",
                 intent_detail="apply_fix",
                 flow_classification="migrated",
             )):
            result = server._evaluate_current_completion_gate(
                tool_name="fo_apply",
                bug_fix_completed=True,
                fo_solved_called=False,
            )

        self.assertEqual(result.level, "warn")
        entry = get_agent_audit(limit=5)[0]
        self.assertEqual(entry["gate"], "completion_gate")
        self.assertEqual(entry["tool_name"], "fo_apply")
        self.assertEqual(entry["intent"], "apply_fix")

    def test_runtime_flow_audit_marks_all_gates_migrated(self):
        audit = server.get_agent_evaluation_flow_audit()

        self.assertEqual(audit["error_gate"]["classification"], "migrated")
        self.assertEqual(audit["decision_conflict_gate"]["classification"], "migrated")
        self.assertEqual(audit["risk_gate"]["classification"], "migrated")
        self.assertEqual(audit["repeat_bug_gate"]["classification"], "migrated")
        self.assertEqual(audit["completion_gate"]["classification"], "migrated")
        self.assertEqual(audit["standalone_bridge"]["classification"], "partial")
        self.assertEqual(audit["legacy_bypasses"]["bypasses"], [])

    def test_log_decision_policy_validation_uses_agent_aware_gate(self):
        session = server.SessionContext(project_id="proj-rt-decision", working_dir="/tmp/demo")
        session.initialized_at = "2026-05-27T16:00:00"
        memory = {
            "decisions": [
                {
                    "decision": "Always use SQLite for local storage",
                    "reason": "Existing architecture decision",
                }
            ]
        }

        def fake_validate(_decision, _reason, _active_decisions, force=False, gate_evaluator=None):
            self.assertFalse(force)
            self.assertTrue(callable(gate_evaluator))
            gate_result = gate_evaluator(server.InterventionContext(
                tool_name="log_decision",
                decision_conflict_severity="high",
                extra={"conflicts": [{"severity": "high"}]},
            ))
            self.assertEqual(gate_result.level, "block")
            return False, "blocked by policy", [{"severity": "high"}]

        with patch.object(server, "_universal_gate", return_value=("", "")), \
             patch.object(server, "_get_session", return_value=session), \
             patch.object(server, "_load_project", return_value=memory), \
             patch.object(server, "_save_project") as save_project, \
             patch.object(server, "_policy_available", True), \
             patch.object(server, "_intervention_policy_available", True), \
             patch.object(server, "_agent_intervention_available", True), \
             patch.object(server, "validate_decision", side_effect=fake_validate), \
             patch.object(server, "build_agent_context", return_value=server.AgentContext(
                 actor_name="codex",
                 actor_source="client_actor",
                 actor_confidence=0.97,
                 tool_name="log_decision",
                 intent="decision",
                 session_id="sess-rt-decision",
                 project_id="proj-rt-decision",
                 intent_detail="Never use SQLite for local storage",
                 flow_classification="migrated",
             )):
            result = server.log_decision(
                "Never use SQLite for local storage",
                "Requirements changed",
            )

        self.assertIn("Decision NOT logged", result)
        # Pre-save review must not persist either the proposed decision or a
        # conflict record until the user chooses a resolution action.
        save_project.assert_not_called()
        self.assertEqual(len(memory["decisions"]), 1)
        self.assertEqual(memory.get("decision_conflicts", []), [])


if __name__ == "__main__":
    unittest.main()
