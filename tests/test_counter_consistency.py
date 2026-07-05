#!/usr/bin/env python3
"""Regression tests for live project knowledge counter consistency."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

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

import mcp_memory_server_v2 as mcp_server
from api import status_bp


def _live_memory(working_dir: str) -> dict:
    return {
        "project_info": {
            "name": "FixOnce-QA-Project",
            "working_dir": working_dir,
        },
        "live_record": {
            "gps": {"working_dir": working_dir},
            "intent": {
                "current_goal": "Counter consistency check",
                "updated_at": "2026-07-05T10:00:00",
            },
            "lessons": {"insights": []},
        },
        "decisions": [
            {"decision": f"Live decision {idx}", "reason": "Live memory source"}
            for idx in range(7)
        ],
        "debug_sessions": [
            {"problem": "Bug one", "solution": "Fixed"},
            {"problem": "Bug two", "solution": "Fixed"},
        ],
        "avoid": [
            {"what": "Avoid one", "reason": "Live memory source"},
        ],
    }


def _write_committed_counts(working_dir: str) -> None:
    fixonce_dir = Path(working_dir) / ".fixonce"
    fixonce_dir.mkdir()
    (fixonce_dir / "decisions.json").write_text(
        json.dumps({"count": 0, "decisions": []}),
        encoding="utf-8",
    )
    (fixonce_dir / "solutions.json").write_text(
        json.dumps({
            "count": 2,
            "solutions": [
                {"problem": "Bug one", "solution": "Fixed"},
                {"problem": "Bug two", "solution": "Fixed"},
            ],
        }),
        encoding="utf-8",
    )
    (fixonce_dir / "avoid.json").write_text(
        json.dumps({
            "count": 1,
            "patterns": [{"what": "Avoid one", "reason": "Committed"}],
        }),
        encoding="utf-8",
    )


class TestCounterConsistency(unittest.TestCase):
    def test_fo_init_dashboard_and_tray_use_live_project_counters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            working_dir = str(Path(temp_dir) / "FixOnce-QA-Project")
            Path(working_dir).mkdir()
            _write_committed_counts(working_dir)
            memory = _live_memory(working_dir)

            with patch.object(mcp_server, "_get_project_id", return_value="proj-live"), \
                 patch.object(mcp_server, "_load_project", return_value=memory), \
                 patch.object(mcp_server, "_get_live_errors", return_value=[]), \
                 patch.object(mcp_server, "_resume_state_available", False):
                opener = mcp_server._format_minimal_init(working_dir)

            self.assertIn(
                "📊 Project Knowledge: 7 Decisions · 2 Solved Bugs · 1 Avoid Patterns",
                opener,
            )

            app = Flask(__name__)
            app.register_blueprint(status_bp, url_prefix="/api")

            with app.test_client() as client, \
                 patch("managers.multi_project_manager.get_active_project_id", return_value="proj-live"), \
                 patch("managers.multi_project_manager.load_project_memory", return_value=memory), \
                 patch("managers.multi_project_manager.list_projects", return_value=[]), \
                 patch("core.mcp_session_health.get_session_health", return_value={"state": "connected"}):
                dashboard_payload = client.get("/api/dashboard_snapshot").get_json()
                tray_payload = client.get("/api/tray/status").get_json()

            snapshot = dashboard_payload["snapshot"]
            self.assertEqual(snapshot["knowledge"]["total_decisions"], 7)
            self.assertEqual(snapshot["knowledge"]["solved_bugs"], 2)
            self.assertEqual(snapshot["knowledge"]["total_avoids"], 1)
            self.assertEqual(snapshot["identity"]["counts"]["decisions"], 7)
            self.assertEqual(snapshot["identity"]["counts"]["solved_bugs"], 2)
            self.assertEqual(snapshot["identity"]["counts"]["avoids"], 1)

            self.assertEqual(tray_payload["knowledge"], {"decisions": 7, "solved": 2, "avoid": 1})
            self.assertEqual(tray_payload["memory"], {"decisions": 7, "solved": 2, "avoid": 1})


if __name__ == "__main__":
    unittest.main()
