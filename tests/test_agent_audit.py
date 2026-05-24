#!/usr/bin/env python3
"""Tests for Stage 8 agent audit records."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.agent_audit import clear_agent_audit, get_agent_audit, record_agent_audit


class TestAgentAudit(unittest.TestCase):
    def setUp(self):
        clear_agent_audit()

    def test_agent_audit_entry_contains_runtime_identity_fields(self):
        record_agent_audit(
            actor_name="codex",
            actor_source="client_actor",
            actor_confidence=0.97,
            tool_name="fo_sync",
            intent="sync",
            gate="completion_gate",
            verdict="warn",
            evidence={"sync_recorded": False},
            project_id="proj-1",
            session_id="sess-1",
            flow_classification="migrated",
            metadata={"intent": "Close runtime wiring"},
        )

        entry = get_agent_audit(limit=1)[0]
        self.assertEqual(entry["actor_name"], "codex")
        self.assertEqual(entry["actor_source"], "client_actor")
        self.assertEqual(entry["actor_confidence"], 0.97)
        self.assertEqual(entry["tool_name"], "fo_sync")
        self.assertEqual(entry["intent"], "sync")
        self.assertEqual(entry["gate"], "completion_gate")
        self.assertEqual(entry["verdict"], "warn")
        self.assertEqual(entry["evidence"]["sync_recorded"], False)
        self.assertEqual(entry["project_id"], "proj-1")
        self.assertEqual(entry["session_id"], "sess-1")
        self.assertEqual(entry["flow_classification"], "migrated")
        self.assertIn("timestamp", entry)


if __name__ == "__main__":
    unittest.main()
