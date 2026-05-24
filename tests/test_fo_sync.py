#!/usr/bin/env python3
"""Regression tests for the fo_sync wrapper bug."""

import sys
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


class TestFoSync(unittest.TestCase):
    def test_fo_sync_uses_internal_impl_not_decorated_tool_object(self):
        with patch.object(server, "update_work_context", object()), \
             patch.object(server, "_update_work_context_impl", return_value="Synced.") as impl_mock:
            result = server.fo_sync(
                goal="Close Stage 8 runtime wiring",
                work_area="agent runtime",
                last_change="Connected runtime audit",
                last_file="src/mcp_server/mcp_memory_server_v2.py",
                why="Keep agent state grounded",
                next_step="Run regression tests",
            )

        impl_mock.assert_called_once_with(
            tool_name="fo_sync",
            current_goal="Close Stage 8 runtime wiring",
            work_area="agent runtime",
            last_change="Connected runtime audit",
            last_file="src/mcp_server/mcp_memory_server_v2.py",
            why="Keep agent state grounded",
            next_step="Run regression tests",
        )
        self.assertEqual(result, "Synced.")


if __name__ == "__main__":
    unittest.main()
