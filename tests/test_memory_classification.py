#!/usr/bin/env python3
"""Regression tests for solved bug classification and category-agnostic recall."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
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


class TestMemoryClassification(unittest.TestCase):
    def _activate_temp_session(self, temp_root: Path, memory=None):
        projects_dir = temp_root / "projects_v2"
        projects_dir.mkdir()
        project_id = "proj-memory-classification"
        project_file = projects_dir / f"{project_id}.json"
        project_file.write_text(json.dumps(memory or {
            "project_info": {"name": "Memory Classification", "working_dir": str(temp_root)},
            "live_record": {
                "intent": {},
                "architecture": {"summary": "Test project", "components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }), encoding="utf-8")

        patches = [
            patch.object(server, "DATA_DIR", projects_dir),
            patch.object(server, "USER_DATA_DIR", temp_root),
            patch.object(server, "SESSION_FILE", temp_root / "mcp_session.json"),
            patch.object(server, "COMPLIANCE_FILE", temp_root / "mcp_compliance.json"),
            patch.object(server, "AI_CONNECTIONS_FILE", temp_root / "ai_connections.json"),
            patch.object(server, "INDEX_FILE", temp_root / "project_index.json"),
            patch.object(server, "_session_registry_available", False),
            patch.object(server, "_load_project_semantic", return_value=None),
            patch.object(server, "_track_roi_event", return_value=None),
            patch.object(server, "_log_mcp_activity", return_value=None),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        server._set_session(project_id, str(temp_root))
        server._persist_session(project_id, str(temp_root))
        server._mark_session_initialized()
        return project_file

    def test_search_finds_solved_bug_stored_as_insight(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {
                    "insights": [{
                        "text": "Windows TestUser login crash was fixed by removing login auto-start and requiring manual open.",
                        "timestamp": "2026-06-01T10:00:00",
                        "use_count": 0,
                    }],
                    "failed_attempts": [],
                },
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("TestUser login crash")

        self.assertIn("Found 1 match", result)
        self.assertIn("TestUser login crash", result)

    def test_search_finds_solved_bug_stored_as_decision(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "Preserve Codex TOML sections during MCP registration repair.",
                "reason": "This fixed Codex MCP reconnect failures without overwriting user config.",
                "timestamp": "2026-06-01T10:00:00",
            }],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("Codex TOML repair")

        self.assertIn("Found 1 match", result)
        self.assertIn("Decision", result)

    def test_search_works_across_component_history(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": [{
                    "name": "MCP reconnect action",
                    "status": "done",
                    "desc": "Committed MCP reconnect console flash fix for packaged Windows startup.",
                    "updated_at": "2026-06-01T10:00:00",
                }]},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("MCP reconnect")

        self.assertIn("Found 1 match", result)
        self.assertIn("Component history", result)

    def test_avoid_patterns_remain_searchable(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [{
                "what": "Do not edit project_context.py without full test cycle",
                "reason": "It previously caused memory context regressions.",
                "timestamp": "2026-06-01T10:00:00",
            }],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("project_context test cycle")

        self.assertIn("Found 1 match", result)
        self.assertIn("Avoid", result)

    def test_normal_context_update_does_not_create_fake_solved_bug(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = self._activate_temp_session(Path(temp_dir))

            result = server.fo_sync(
                goal="Prepare release notes",
                work_area="release docs",
                last_change="Updated dashboard wording",
                next_step="Review copy",
            )

            memory = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertEqual(result, "Synced.")
        self.assertEqual(memory.get("debug_sessions", []), [])

    def test_solved_insight_is_auto_classified_as_debug_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = self._activate_temp_session(Path(temp_dir))

            server.update_live_record("lessons", json.dumps({
                "insight": "NoneType.buffer startup crash was fixed by guarding stdio stream access."
            }))
            memory = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertEqual(len(memory.get("debug_sessions", [])), 1)
        self.assertEqual(memory["debug_sessions"][0]["source"], "auto_classified:insight")

    def test_done_component_fix_is_auto_classified_as_debug_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = self._activate_temp_session(Path(temp_dir))

            server.update_component_status(
                "MCP reconnect",
                "done",
                "Fixed packaged MCP reconnect timeout during Windows startup.",
            )
            memory = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertEqual(len(memory.get("debug_sessions", [])), 1)
        self.assertEqual(memory["debug_sessions"][0]["source"], "auto_classified:component_status")


if __name__ == "__main__":
    unittest.main()
