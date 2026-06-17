import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
HOOK = PROJECT_ROOT / "hooks" / "pre_tool_context.sh"


class TestClaudePreToolHook(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-claude-hook-")
        self.temp_path = Path(self.temp_dir.name)
        self.args_file = self.temp_path / "curl_args.txt"
        self.fake_bin = self.temp_path / "bin"
        self.fake_bin.mkdir()
        fake_curl = self.fake_bin / "curl"
        fake_curl.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" > \"$CURL_ARGS_FILE\"\n"
            "printf '%s' \"$FAKE_CURL_RESPONSE\"\n"
            "exit \"${FAKE_CURL_EXIT:-0}\"\n",
            encoding="utf-8",
        )
        fake_curl.chmod(0o755)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_hook(self, payload, response):
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["HOME"] = str(self.temp_path)
        env["CURL_ARGS_FILE"] = str(self.args_file)
        env["FAKE_CURL_RESPONSE"] = response if isinstance(response, str) else json.dumps(response)

        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
        )
        return json.loads(result.stdout), self.args_file.read_text(encoding="utf-8")

    def test_blocks_on_fixonce_warning_even_when_count_is_zero(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Read",
                "tool_input": {"file_path": "src/core/project_context.py"},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_BLOCKING_WARNING\nseverity: blocking\nscope: src/core/project_context.py",
            },
        )

        hook_output = output["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "PreToolUse")
        self.assertEqual(hook_output["permissionDecision"], "deny")
        self.assertIn("FIXONCE_BLOCKING_WARNING", hook_output["permissionDecisionReason"])
        self.assertIn("src/core/project_context.py", hook_output["permissionDecisionReason"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_injects_context_for_normal_area_context(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Read",
                "tool_input": {"file_path": "src/core/windows_subprocess.py"},
            },
            {
                "count": 1,
                "context": "WINDOWS SUBPROCESS RISK",
            },
        )

        self.assertTrue(output["continue"])
        hook_output = output["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "PreToolUse")
        self.assertIn("WINDOWS SUBPROCESS RISK", hook_output["additionalContext"])
        self.assertIn("path=src/core/windows_subprocess.py", curl_args)


if __name__ == "__main__":
    unittest.main()
