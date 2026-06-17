import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
HOOK = PROJECT_ROOT / "hooks" / "pre_tool_context_codex.sh"


class TestCodexPreToolHook(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-codex-hook-")
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

    def run_hook(self, payload, response, curl_exit=0):
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["HOME"] = str(self.temp_path)
        env["CURL_ARGS_FILE"] = str(self.args_file)
        env["FAKE_CURL_RESPONSE"] = response if isinstance(response, str) else json.dumps(response)
        env["FAKE_CURL_EXIT"] = str(curl_exit)

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

    def test_protected_file_blocks_when_curl_fails(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Read",
                "tool_input": {"file_path": "src/core/project_context.py"},
            },
            "",
            curl_exit=7,
        )

        self.assertEqual(output["decision"], "block")
        self.assertEqual(
            output["reason"],
            "FIXONCE_BLOCKING_WARNING FixOnce context server is unavailable; refusing to read protected file before context is checked.",
        )
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_protected_file_blocks_on_empty_response(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Read",
                "tool_input": {"file_path": "src/core/project_context.py"},
            },
            "",
        )

        self.assertEqual(output["decision"], "block")
        self.assertIn("context server is unavailable", output["reason"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_normal_file_approves_when_curl_fails(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Read",
                "tool_input": {"file_path": "src/core/windows_subprocess.py"},
            },
            "",
            curl_exit=7,
        )

        self.assertEqual(output["decision"], "approve")
        self.assertNotIn("reason", output)
        self.assertIn("path=src/core/windows_subprocess.py", curl_args)

    def test_protected_file_approves_with_valid_no_warning_response(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Read",
                "tool_input": {"file_path": "src/core/project_context.py"},
            },
            {
                "count": 1,
                "context": "Area: core recent context",
            },
        )

        self.assertEqual(output["decision"], "approve")
        self.assertIn("Area: core recent context", output["message"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_exec_command_sed_path_blocks_on_fixonce_warning(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "exec_command",
                "tool_input": {
                    "cmd": "sed -n '1,20p' src/core/project_context.py",
                },
            },
            {
                "count": 1,
                "context": "FIXONCE_BLOCKING_WARNING\nseverity: blocking",
            },
        )

        self.assertEqual(output["decision"], "block")
        self.assertIn("FIXONCE_BLOCKING_WARNING", output["reason"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_direct_file_path_payload_injects_context(self):
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

        self.assertEqual(output["decision"], "approve")
        self.assertIn("WINDOWS SUBPROCESS RISK", output["message"])
        self.assertIn("path=src/core/windows_subprocess.py", curl_args)

    def test_direct_file_path_blocks_on_warning_even_when_count_is_zero(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Read",
                "tool_input": {"file_path": "src/core/project_context.py"},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_BLOCKING_WARNING\nscope: src/core/project_context.py",
            },
        )

        self.assertEqual(output["decision"], "block")
        self.assertIn("FIXONCE_BLOCKING_WARNING", output["reason"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_python_one_liner_path_blocks_on_fixonce_warning(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "exec_command",
                "tool_input": {
                    "cmd": "python3 -c 'open(\"src/core/project_context.py\").read()'",
                },
            },
            {
                "count": 1,
                "context": "FIXONCE_BLOCKING_WARNING\nscope: src/core/project_context.py",
            },
        )

        self.assertEqual(output["decision"], "block")
        self.assertIn("src/core/project_context.py", output["reason"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_shell_wrapped_rg_command_extracts_target_path(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "exec_command",
                "tool_input": {
                    "cmd": "zsh -lc 'rg ProjectContext src/core/project_context.py'",
                },
            },
            {
                "count": 1,
                "context": "FIXONCE_BLOCKING_WARNING\nscope: src/core/project_context.py",
            },
        )

        self.assertEqual(output["decision"], "block")
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_apply_patch_command_extracts_unquoted_patch_path(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Begin Patch\n"
                    "*** Update File: src/core/project_context.py\n"
                    "@@\n"
                    "+# temporary\n"
                    "*** End Patch\n",
                },
            },
            {
                "count": 1,
                "context": "FIXONCE_BLOCKING_WARNING\nscope: src/core/project_context.py",
            },
        )

        self.assertEqual(output["decision"], "block")
        self.assertIn("path=src/core/project_context.py", curl_args)


if __name__ == "__main__":
    unittest.main()
