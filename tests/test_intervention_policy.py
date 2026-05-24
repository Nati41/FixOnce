#!/usr/bin/env python3
"""Unit tests for Stage 7 intervention policy skeleton."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.intervention_policy import (
    InterventionContext,
    evaluate_completion_gate,
    evaluate_decision_conflict_gate,
    evaluate_error_gate,
    evaluate_intervention,
    evaluate_repeat_bug_gate,
    evaluate_risk_gate,
)
from core.policy_engine import validate_decision


class TestInterventionPolicy(unittest.TestCase):
    def test_default_policy_is_silent(self):
        results = evaluate_intervention(InterventionContext())
        self.assertEqual([result.level for result in results], ["silent"] * 5)

    def test_live_error_returns_warn(self):
        result = evaluate_error_gate(InterventionContext(live_errors=1))
        self.assertEqual(result.level, "warn")

    def test_auto_fix_ready_blocks_non_fo_apply_tools(self):
        result = evaluate_error_gate(
            InterventionContext(tool_name="fo_sync", auto_fix_ready=True)
        )
        self.assertEqual(result.level, "block")

    def test_severe_decision_conflict_blocks(self):
        result = evaluate_decision_conflict_gate(
            InterventionContext(decision_conflict_severity="high")
        )
        self.assertEqual(result.level, "block")

    def test_touching_stable_component_warns(self):
        result = evaluate_risk_gate(
            InterventionContext(stable_component_touched=True)
        )
        self.assertEqual(result.level, "warn")

    def test_lock_violation_blocks(self):
        result = evaluate_risk_gate(
            InterventionContext(lock_violation=True)
        )
        self.assertEqual(result.level, "block")

    def test_blocked_component_warns(self):
        result = evaluate_risk_gate(
            InterventionContext(blocked_components_relevant=1)
        )
        self.assertEqual(result.level, "warn")

    def test_similar_past_solution_warns(self):
        result = evaluate_repeat_bug_gate(
            InterventionContext(similar_past_solution_found=True)
        )
        self.assertEqual(result.level, "warn")

    def test_no_repeat_history_is_silent(self):
        result = evaluate_repeat_bug_gate(InterventionContext())
        self.assertEqual(result.level, "silent")

    def test_completion_missing_fo_solved_warns_not_blocks(self):
        result = evaluate_completion_gate(
            InterventionContext(bug_fix_completed=True, fo_solved_called=False)
        )
        self.assertEqual(result.level, "warn")

    def test_significant_work_without_sync_warns(self):
        result = evaluate_completion_gate(
            InterventionContext(significant_work_completed=True, sync_recorded=False)
        )
        self.assertEqual(result.level, "warn")

    def test_component_changed_without_status_update_warns(self):
        result = evaluate_completion_gate(
            InterventionContext(component_changed=True, component_status_updated=False)
        )
        self.assertEqual(result.level, "warn")

    def test_validate_decision_blocks_high_severity_conflict(self):
        is_valid, message, conflicts = validate_decision(
            "Always store data in Hebrew",
            "Testing contradiction behavior",
            [
                {
                    "decision": "Always store data in English",
                    "reason": "Consistency",
                }
            ],
        )

        self.assertFalse(is_valid)
        self.assertTrue(conflicts)
        self.assertIn("BLOCKED", message)

    def test_validate_decision_warns_on_similar_conflict(self):
        is_valid, message, conflicts = validate_decision(
            "Use REST API for authentication",
            "Keep auth endpoints conventional",
            [
                {
                    "decision": "Use REST API for auth",
                    "reason": "Conventional API shape",
                }
            ],
        )

        self.assertTrue(is_valid)
        self.assertTrue(conflicts)
        self.assertIn("WARNING", message)


if __name__ == "__main__":
    unittest.main()
