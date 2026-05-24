#!/usr/bin/env python3
"""
Regression tests for FixOnce session opener formatting.
"""

import sys
import types
from pathlib import Path
import unittest
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
