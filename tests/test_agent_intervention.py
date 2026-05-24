#!/usr/bin/env python3
"""Tests for the Stage 8 agent-aware intervention bridge."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.agent_audit import clear_agent_audit, get_agent_audit
from core.agent_context import AgentContext
from core.agent_intervention import evaluate_agent_intervention
from core.intervention_policy import InterventionContext


class TestAgentIntervention(unittest.TestCase):
    def setUp(self):
        clear_agent_audit()

    def test_agent_bridge_returns_highest_severity(self):
        verdict = evaluate_agent_intervention(
            AgentContext(
                actor_name="codex",
                actor_source="session_registry",
                actor_confidence=0.88,
                tool_name="fo_sync",
                intent="sync",
                session_id="sess-2",
                project_id="proj-1",
                intent_detail="continue despite pending auto-fix",
            ),
            InterventionContext(
                tool_name="fo_sync",
                auto_fix_ready=True,
                similar_past_solution_found=True,
            ),
        )

        self.assertEqual(verdict, "block")

    def test_agent_bridge_writes_audit_entries_for_all_gate_verdicts(self):
        evaluate_agent_intervention(
            AgentContext(
                actor_name="codex",
                actor_source="session_registry",
                actor_confidence=0.88,
                tool_name="fo_sync",
                intent="sync",
                session_id="sess-3",
                project_id="proj-1",
                intent_detail="continue despite pending auto-fix",
            ),
            InterventionContext(
                tool_name="fo_sync",
                live_errors=1,
                similar_past_solution_found=True,
            ),
        )

        entries = get_agent_audit(limit=10)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[0]["actor_name"], "codex")
        self.assertEqual(entries[0]["actor_source"], "session_registry")
        self.assertEqual(entries[0]["actor_confidence"], 0.88)
        self.assertEqual(entries[0]["tool_name"], "fo_sync")
        self.assertEqual(entries[0]["intent"], "sync")
        self.assertEqual(entries[0]["project_id"], "proj-1")
        self.assertEqual(entries[0]["session_id"], "sess-3")
        self.assertEqual(entries[0]["flow_classification"], "partial")
        self.assertEqual(entries[0]["gate"], "error_gate")
        self.assertEqual(entries[0]["verdict"], "warn")
        self.assertEqual(entries[1]["gate"], "decision_conflict_gate")
        self.assertEqual(entries[2]["gate"], "risk_gate")
        self.assertEqual(entries[3]["gate"], "repeat_bug_gate")
        self.assertEqual(entries[4]["gate"], "completion_gate")

    def test_claude_decision_conflict_audit_includes_evidence(self):
        verdict = evaluate_agent_intervention(
            AgentContext(
                actor_name="claude",
                actor_source="client_actor",
                actor_confidence=0.91,
                tool_name="log_decision",
                intent="decision",
                session_id="sess-4",
                project_id="proj-2",
                intent_detail="Introduce a conflicting architecture choice",
            ),
            InterventionContext(
                tool_name="log_decision",
                decision_conflict_severity="high",
            ),
        )

        self.assertEqual(verdict, "block")
        entry = get_agent_audit(limit=5)[0]
        self.assertEqual(entry["actor_name"], "claude")
        self.assertEqual(entry["intent"], "decision")
        self.assertEqual(entry["gate"], "error_gate")
        decision_entry = get_agent_audit(limit=5)[1]
        self.assertEqual(decision_entry["gate"], "decision_conflict_gate")
        self.assertEqual(decision_entry["verdict"], "block")
        self.assertEqual(decision_entry["evidence"]["severity"], "high")

    def test_unknown_agent_can_stay_silent(self):
        verdict = evaluate_agent_intervention(
            AgentContext(
                actor_name="unknown",
                actor_source="none",
                actor_confidence=0.0,
                tool_name="fo_errors",
                intent="read",
                session_id="sess-5",
                project_id="proj-3",
            ),
            InterventionContext(tool_name="fo_errors"),
        )

        self.assertEqual(verdict, "silent")
        entries = get_agent_audit(limit=5)
        self.assertEqual(len(entries), 5)
        self.assertTrue(all(entry["verdict"] == "silent" for entry in entries))


if __name__ == "__main__":
    unittest.main()
