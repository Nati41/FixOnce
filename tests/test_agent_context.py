#!/usr/bin/env python3
"""Tests for the Stage 8 agent identity model."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.agent_context import AgentContext


class TestAgentContext(unittest.TestCase):
    def test_agent_context_fields_are_preserved(self):
        ctx = AgentContext(
            actor_name="codex",
            actor_source="session_registry",
            actor_confidence=0.93,
            tool_name="fo_apply",
            intent="close known error path",
            session_id="sess-1",
            project_id="proj-1",
        )

        self.assertEqual(ctx.actor_name, "codex")
        self.assertEqual(ctx.actor_source, "session_registry")
        self.assertEqual(ctx.actor_confidence, 0.93)
        self.assertEqual(ctx.tool_name, "fo_apply")
        self.assertEqual(ctx.intent, "close known error path")
        self.assertEqual(ctx.session_id, "sess-1")
        self.assertEqual(ctx.project_id, "proj-1")


if __name__ == "__main__":
    unittest.main()
