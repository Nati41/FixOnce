import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import server as server_module
import core.mcp_session_health as session_health


class TestMcpSessionApi(unittest.TestCase):
    def test_mcp_session_endpoint_returns_session_lost_status(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-mcp-session-api-") as temp_dir:
            temp_root = Path(temp_dir)
            state_file = temp_root / "mcp_session_health.json"
            state_file.write_text(json.dumps({
                "state": "session_lost",
                "consecutive_failures": 2,
                "last_error": "Transport closed",
                "last_actor": "unknown",
                "updated_at": "2026-05-31T10:00:00",
            }), encoding="utf-8")

            client = server_module.flask_app.test_client()
            with patch.object(session_health, "STATE_FILE", state_file), \
                 patch.object(session_health, "LOG_FILE", temp_root / "logs" / "mcp_session_health.jsonl"):
                response = client.get("/api/mcp/session")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["state"], "session_lost")
            self.assertIn("FixOnce is running", payload["message"])


if __name__ == "__main__":
    unittest.main()
