#!/usr/bin/env python3
"""Integration tests for Stage 7 intervention policy."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.intervention_policy import InterventionContext, evaluate_intervention


class TestInterventionIntegration(unittest.TestCase):
    def test_all_gates_default_to_silent(self):
        results = {
            result.gate: result.level
            for result in evaluate_intervention(InterventionContext())
        }

        self.assertEqual(results["error_gate"], "silent")
        self.assertEqual(results["decision_conflict_gate"], "silent")
        self.assertEqual(results["risk_gate"], "silent")
        self.assertEqual(results["repeat_bug_gate"], "silent")
        self.assertEqual(results["completion_gate"], "silent")

    def test_all_gates_surface_expected_levels_together(self):
        results = {
            result.gate: result.level
            for result in evaluate_intervention(
                InterventionContext(
                    tool_name="fo_sync",
                    live_errors=1,
                    auto_fix_ready=True,
                    decision_conflict_severity="high",
                    stable_component_touched=True,
                    lock_violation=True,
                    similar_past_solution_found=True,
                    bug_fix_completed=True,
                    fo_solved_called=False,
                )
            )
        }

        self.assertEqual(results["error_gate"], "block")
        self.assertEqual(results["decision_conflict_gate"], "block")
        self.assertEqual(results["risk_gate"], "block")
        self.assertEqual(results["repeat_bug_gate"], "warn")
        self.assertEqual(results["completion_gate"], "warn")

    def test_mixed_warn_and_silent_states(self):
        results = {
            result.gate: result.level
            for result in evaluate_intervention(
                InterventionContext(
                    live_errors=2,
                    decision_conflict_severity="medium",
                    stable_component_touched=True,
                    similar_past_solution_found=False,
                    significant_work_completed=True,
                    sync_recorded=False,
                )
            )
        }

        self.assertEqual(results["error_gate"], "warn")
        self.assertEqual(results["decision_conflict_gate"], "warn")
        self.assertEqual(results["risk_gate"], "warn")
        self.assertEqual(results["repeat_bug_gate"], "silent")
        self.assertEqual(results["completion_gate"], "warn")

    def test_closed_workflow_returns_silent_completion(self):
        results = {
            result.gate: result.level
            for result in evaluate_intervention(
                InterventionContext(
                    significant_work_completed=True,
                    sync_recorded=True,
                    component_changed=True,
                    component_status_updated=True,
                    bug_fix_completed=True,
                    fo_solved_called=True,
                )
            )
        }

        self.assertEqual(results["completion_gate"], "silent")


if __name__ == "__main__":
    unittest.main()
