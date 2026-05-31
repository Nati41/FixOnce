import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import core.mcp_session_health as session_health


class TestMcpSessionHealth(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-mcp-session-")
        self.state_file = Path(self.temp_dir.name) / "mcp_session_health.json"
        self.log_file = Path(self.temp_dir.name) / "logs" / "mcp_session_health.jsonl"
        self.state_patch = patch.object(session_health, "STATE_FILE", self.state_file)
        self.log_patch = patch.object(session_health, "LOG_FILE", self.log_file)
        self.state_patch.start()
        self.log_patch.start()

    def tearDown(self):
        self.log_patch.stop()
        self.state_patch.stop()
        self.temp_dir.cleanup()

    def test_one_transport_error_marks_degraded_not_lost(self):
        state = session_health.record_mcp_failure(
            RuntimeError("Transport closed"),
            tool_name="fo_sync",
            actor_identity={"editor": "unknown", "source": "none"},
        )

        self.assertEqual(state["state"], "degraded")
        self.assertEqual(state["consecutive_failures"], 1)
        self.assertFalse(session_health.get_session_health()["is_session_lost"])

    def test_repeated_transport_errors_mark_session_lost(self):
        session_health.record_mcp_failure("Transport closed", tool_name="fo_sync")
        state = session_health.record_mcp_failure("broken pipe", tool_name="fo_search")

        self.assertEqual(state["state"], "session_lost")
        self.assertEqual(state["consecutive_failures"], 2)
        self.assertTrue(session_health.get_session_health()["is_session_lost"])

    def test_success_resets_failure_counter(self):
        session_health.record_mcp_failure("Transport closed", tool_name="fo_sync")
        state = session_health.record_mcp_success(
            tool_name="fo_sync",
            actor_identity={"editor": "codex", "source": "env_var"},
        )

        self.assertEqual(state["state"], "connected")
        self.assertEqual(state["consecutive_failures"], 0)
        self.assertEqual(state["last_actor"], "codex")

    def test_transport_closed_converts_to_friendly_text(self):
        session_health.record_mcp_failure("Transport closed", tool_name="fo_sync")
        state = session_health.record_mcp_failure("Transport closed", tool_name="fo_sync")
        message = session_health.user_message_for_state(state)

        self.assertIn("FixOnce lost the MCP connection", message)
        self.assertIn("open a new ai chat", message.lower())
        self.assertNotEqual(message, "Transport closed")

    def test_unknown_client_gets_generic_recovery_instruction(self):
        session_health.record_mcp_failure(
            "Transport closed",
            actor_identity={"editor": "unknown", "source": "none"},
        )
        state = session_health.record_mcp_failure(
            "Transport closed",
            actor_identity={"editor": "unknown", "source": "none"},
        )

        self.assertIn("restart or reconnect the MCP host", session_health.user_message_for_state(state))

    def test_known_client_gets_optional_hint_without_classifying_by_client(self):
        classified = session_health.classify_mcp_error("Transport closed")
        self.assertTrue(classified.is_transport_failure)

        session_health.record_mcp_failure(
            "Transport closed",
            actor_identity={"editor": "cursor", "source": "env_var"},
        )
        state = session_health.record_mcp_failure(
            "Transport closed",
            actor_identity={"editor": "cursor", "source": "env_var"},
        )

        self.assertIn("For Cursor", session_health.user_message_for_state(state))

    def test_structured_log_written_for_session_lost(self):
        session_health.record_mcp_failure("Transport closed", tool_name="fo_sync")
        session_health.record_mcp_failure("EOF", tool_name="fo_search")

        lines = self.log_file.read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(line)["event"] for line in lines]
        self.assertIn("degraded_state", events)
        self.assertIn("session_lost_state", events)

    def test_process_exit_marks_session_lost(self):
        state = session_health.mark_session_lost(
            "MCP process exited; client transport closed",
            actor_identity={"editor": "unknown", "source": "none"},
        )

        self.assertEqual(state["state"], "session_lost")
        self.assertEqual(state["last_error_category"], "transport")


if __name__ == "__main__":
    unittest.main()
