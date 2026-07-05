#!/usr/bin/env python3
"""Regression tests for BUG-001 browser error project scoping."""

import sys
import types
import unittest
from pathlib import Path
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


class TestBug001BrowserErrorScope(unittest.TestCase):
    def setUp(self):
        server._clear_session()

    def tearDown(self):
        server._clear_session()

    def _response(self, errors):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "errors": errors,
            "count": len(errors),
        }
        return response

    def test_live_errors_api_filters_by_project_id(self):
        from flask import Flask
        from api import errors_bp
        from core.error_store import add_error, clear_errors

        clear_errors()
        try:
            add_error(
                {"message": "Real FixOnce error", "timestamp": "2026-07-05T10:00:00"},
                project_id="FixOnce_real",
            )
            add_error(
                {"message": "QA project error", "timestamp": "2026-07-05T10:01:00"},
                project_id="FixOnce-QA-Project_qa",
            )

            app = Flask(__name__)
            app.register_blueprint(errors_bp)

            with patch("core.db_solutions.find_solution_hybrid", return_value=None):
                response = app.test_client().get(
                    "/api/live-errors?project_id=FixOnce-QA-Project_qa"
                )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["errors"][0]["message"], "QA project error")
        finally:
            clear_errors()

    def test_fo_init_priority_count_uses_current_project_id(self):
        qa_error = {
            "message": "QA ReferenceError",
            "url": "http://localhost:5001/qa",
            "timestamp": "2026-07-05T10:01:00",
            "_project_id": "FixOnce-QA-Project_qa",
        }
        response = self._response([qa_error])
        requested_urls = []

        def fake_get(url, **_kwargs):
            requested_urls.append(url)
            return response

        gate_result = types.SimpleNamespace(level="warn")

        with patch.object(server, "_get_project_id", return_value="FixOnce-QA-Project_qa"), \
             patch.object(server, "_load_project", return_value={}), \
             patch.object(server, "_get_auto_fixes", return_value=[]), \
             patch.object(server.requests, "get", side_effect=fake_get), \
             patch.object(server, "_evaluate_current_error_gate", return_value=gate_result), \
             patch.object(server, "_resume_state_available", False):
            opener = server._format_minimal_init("/tmp/FixOnce-QA-Project")

        self.assertIn("1 error(s) need attention", opener)
        self.assertIn("fo_errors()", opener)
        self.assertTrue(
            any("project_id=FixOnce-QA-Project_qa" in url for url in requested_urls),
            requested_urls,
        )

    def test_fo_errors_output_uses_session_project_id(self):
        qa_error = {
            "message": "QA ReferenceError",
            "url": "http://localhost:5001/qa",
            "timestamp": "2026-07-05T10:01:00",
            "_project_id": "FixOnce-QA-Project_qa",
        }
        response = self._response([qa_error])
        requested_urls = []

        def fake_get(url, **_kwargs):
            requested_urls.append(url)
            return response

        server._set_session("FixOnce-QA-Project_qa", "/tmp/FixOnce-QA-Project")

        with patch.object(server, "_lightweight_tool_gate", return_value=None), \
             patch.object(server, "_get_auto_fixes", return_value=[]), \
             patch("core.pending_fixes.get_auto_fixes", return_value=[]), \
             patch("core.pending_fixes.get_suggested_fixes", return_value=[], create=True), \
             patch.object(server.requests, "get", side_effect=fake_get):
            output = server.fo_errors()

        self.assertIn("1 browser error(s)", output)
        self.assertIn("QA ReferenceError", output)
        self.assertTrue(
            any("project_id=FixOnce-QA-Project_qa" in url for url in requested_urls),
            requested_urls,
        )


if __name__ == "__main__":
    unittest.main()
