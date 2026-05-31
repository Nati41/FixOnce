#!/usr/bin/env python3
"""
Regression tests for FixOnce session opener formatting.
"""

import sys
import types
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

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


class TestInitOpening(unittest.TestCase):
    def test_format_minimal_init_returns_final_opener(self):
        with patch.object(server, "_get_project_id", return_value="proj-1"), \
             patch.object(server, "_load_project", return_value={
                 "live_record": {
                     "intent": {
                         "current_goal": "Harden FixOnce session opener fallback and project root guard",
                         "work_area": "session init / project context",
                         "last_change": "Updated opener instructions and added home/root guard",
                         "next_step": "Verify a fresh session from a real project folder stays grounded",
                         "updated_at": "2026-05-24T10:00:00+00:00",
                     }
                 }
             }), \
             patch.object(server, "_get_live_errors", return_value=[]), \
             patch.object(server, "_resume_state_available", False):
            opener = server._format_minimal_init("/tmp/FixOnce")

        expected = (
            "🧠 Back to FixOnce\n\n"
            "Harden FixOnce session opener fallback and project root guard\n"
            "Area: session init / project context\n\n"
            "Last:\n"
            "Updated opener instructions and added home/root guard.\n"
            "Next:\n"
            "Verify a fresh session from a real project folder stays grounded.\n\n"
            "Ready."
        )
        self.assertEqual(opener, expected)

    def test_format_minimal_init_includes_ready_for_action_required(self):
        with patch.object(server, "_get_project_id", return_value="proj-1"), \
             patch.object(server, "_load_project", return_value={}), \
             patch.object(server, "_get_live_errors", return_value=["ReferenceError"]), \
             patch.object(server, "_resume_state_available", False):
            opener = server._format_minimal_init("/tmp/FixOnce")

        self.assertEqual(opener, "🧠 Back to FixOnce\n\nACTION_REQUIRED: fo_errors\n\nReady.")

    def test_format_minimal_init_uses_error_gate_for_auto_fix_ready(self):
        gate_result = types.SimpleNamespace(level="block")
        with patch.object(server, "_get_project_id", return_value="proj-1"), \
             patch.object(server, "_load_project", return_value={}), \
             patch.object(server, "_get_auto_fixes", return_value=[{"id": "fix-1"}]), \
             patch.object(server, "_get_live_errors", return_value=[]), \
             patch.object(server, "_resume_state_available", False), \
             patch.object(server, "_evaluate_current_error_gate", return_value=gate_result) as gate_mock:
            opener = server._format_minimal_init("/tmp/FixOnce")

        gate_mock.assert_called_once_with(
            tool_name="fo_init",
            live_errors=0,
            auto_fix_ready=True,
        )
        self.assertEqual(opener, "🧠 Back to FixOnce\n\nACTION_REQUIRED: fo_apply\n\nReady.")

    def test_browser_errors_reminder_uses_error_gate(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"count": 2}
        gate_result = types.SimpleNamespace(level="warn")

        with patch.object(server.requests, "get", return_value=response), \
             patch.object(server, "_get_auto_fixes", return_value=[]), \
             patch.object(server, "_evaluate_current_error_gate", return_value=gate_result) as gate_mock:
            reminder = server._get_browser_errors_reminder()

        gate_mock.assert_called_once_with(
            tool_name="update_live_record",
            live_errors=2,
            auto_fix_ready=False,
        )
        self.assertIn("You MUST call: fo_errors()", reminder)

    def test_fo_apply_keeps_completion_reminder_via_gate(self):
        completion_result = types.SimpleNamespace(level="warn")

        with patch.object(server, "_universal_gate", return_value=(None, "")), \
             patch.dict(sys.modules, {}, clear=False), \
             patch("mcp_memory_server_v2._evaluate_current_repeat_bug_gate", return_value=types.SimpleNamespace(level="warn")), \
             patch("mcp_memory_server_v2._evaluate_current_completion_gate", return_value=completion_result) as completion_mock:
            with patch("core.pending_fixes.get_auto_fixes", return_value=[{
                "id": "fix-1",
                "solution_text": "Apply known fix",
                "files": ["src/app.js"],
            }]), patch("core.pending_fixes.mark_fix_applied", return_value=None):
                result = server.fo_apply()

        completion_mock.assert_called_once_with(
            tool_name="fo_apply",
            bug_fix_completed=True,
            fo_solved_called=False,
        )
        self.assertIn("Run `fo_solved(error, solution)` when done.", result)

    def test_completion_gate_drives_compliance_flags_without_changing_rule_names(self):
        session = server.SessionContext(project_id="proj-1", working_dir="/tmp/demo")
        session.mark_initialized()

        score = session.get_compliance_score()
        rule_names = [rule["name"] for rule in score["rules"]]
        advisory_ids = {rule["id"] for rule in score["advisory"]}

        self.assertIn("Goal updated", rule_names)
        self.assertNotIn("Component status updated", rule_names)
        self.assertIn("search_first", advisory_ids)
        self.assertIn("component_status", advisory_ids)
