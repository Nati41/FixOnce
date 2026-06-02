import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class TestMcpStartupTimeout(unittest.TestCase):
    def test_safe_tool_handler_uses_timeout_runner(self):
        module = importlib.import_module("mcp_server.mcp_memory_server_v2")

        def sample_tool():
            return "ok"

        with patch.object(module, "_run_tool_with_timeout", return_value="wrapped") as run_tool:
            wrapped = module._safe_tool_handler(sample_tool)
            result = wrapped()

        self.assertEqual(result, "wrapped")
        run_tool.assert_called_once()
        self.assertEqual(run_tool.call_args[0][0], "sample_tool")

    def test_fo_init_success_recording_failure_does_not_block_return(self):
        module = importlib.import_module("mcp_server.mcp_memory_server_v2")

        with patch.object(module._mcp_health_executor, "submit", side_effect=RuntimeError("slow health path")):
            result = module._run_tool_body("fo_init", lambda: "opener")

        self.assertEqual(result, "opener")

    def test_fo_init_success_recording_future_is_not_waited(self):
        module = importlib.import_module("mcp_server.mcp_memory_server_v2")

        class SlowFuture:
            def result(self, timeout=None):
                raise AssertionError("fo_init waited for health recording")

        with patch.object(module._mcp_health_executor, "submit", return_value=SlowFuture()) as submit:
            result = module._run_tool_body("fo_init", lambda: "opener")

        self.assertEqual(result, "opener")
        submit.assert_called_once()
