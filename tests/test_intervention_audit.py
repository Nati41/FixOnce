#!/usr/bin/env python3
"""Tests for internal intervention audit tracing."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.intervention_audit import clear_intervention_audit, get_intervention_audit
from core.intervention_policy import InterventionContext, evaluate_intervention


class TestInterventionAudit(unittest.TestCase):
    def setUp(self):
        clear_intervention_audit()

    def test_each_gate_writes_a_trace_entry(self):
        evaluate_intervention(
            InterventionContext(
                tool_name="fo_sync",
                auto_fix_ready=True,
                decision_conflict_severity="high",
                lock_violation=True,
                similar_past_solution_found=True,
                bug_fix_completed=True,
                fo_solved_called=False,
            )
        )

        entries = get_intervention_audit(limit=10)
        self.assertEqual(len(entries), 5)
        self.assertEqual(
            [entry["gate"] for entry in entries],
            [
                "error_gate",
                "decision_conflict_gate",
                "risk_gate",
                "repeat_bug_gate",
                "completion_gate",
            ],
        )

    def test_audit_entry_contains_verdict_and_evidence(self):
        evaluate_intervention(InterventionContext(live_errors=2))
        error_entry = get_intervention_audit(limit=5)[0]
        self.assertEqual(error_entry["gate"], "error_gate")
        self.assertEqual(error_entry["verdict"], "warn")
        self.assertEqual(error_entry["evidence"]["live_errors"], 2)


if __name__ == "__main__":
    unittest.main()
