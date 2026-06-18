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

    def test_injects_warning_for_protected_file(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Read",
                "tool_input": {"file_path": "src/core/project_context.py"},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_PROTECTED_FILE\nscope: src/core/project_context.py\nhistory: Critical file",
            },
        )

        self.assertTrue(output["continue"])
        hook_output = output["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "PreToolUse")
        self.assertIn("FIXONCE_PROTECTED_FILE", hook_output["additionalContext"])
        self.assertIn("src/core/project_context.py", hook_output["additionalContext"])
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

    def test_warns_bash_cat_on_protected_file(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "cat src/core/project_context.py"},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_PROTECTED_FILE\nscope: src/core/project_context.py",
            },
        )

        self.assertTrue(output["continue"])
        hook_output = output["hookSpecificOutput"]
        self.assertIn("FIXONCE_PROTECTED_FILE", hook_output["additionalContext"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_warns_bash_head_with_flags_on_protected_file(self):
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "head -n 10 src/core/project_context.py"},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_PROTECTED_FILE\nscope: project_context.py",
            },
        )

        self.assertTrue(output["continue"])
        hook_output = output["hookSpecificOutput"]
        self.assertIn("FIXONCE_PROTECTED_FILE", hook_output["additionalContext"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_allows_bash_non_read_commands(self):
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["HOME"] = str(self.temp_path)

        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps({
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
            }),
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
        )
        output = json.loads(result.stdout)
        self.assertTrue(output["continue"])

    def test_warns_python_open_read_on_protected_file(self):
        """Python one-liner with open().read() gets warning on protected files."""
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": 'python3 -c "print(open(\'/Users/haimdayan/Desktop/FixOnce/src/core/project_context.py\').read())"'},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_PROTECTED_FILE\nscope: src/core/project_context.py",
            },
        )

        self.assertTrue(output["continue"])
        hook_output = output["hookSpecificOutput"]
        self.assertIn("FIXONCE_PROTECTED_FILE", hook_output["additionalContext"])
        self.assertIn("project_context.py", curl_args)

    def test_warns_python_pathlib_read_on_protected_file(self):
        """Python one-liner with Path().read_text() gets warning on protected files."""
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -c \"from pathlib import Path; print(Path('/Users/haimdayan/Desktop/FixOnce/src/core/project_context.py').read_text())\""},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_PROTECTED_FILE\nscope: src/core/project_context.py",
            },
        )

        self.assertTrue(output["continue"])
        hook_output = output["hookSpecificOutput"]
        self.assertIn("FIXONCE_PROTECTED_FILE", hook_output["additionalContext"])
        self.assertIn("project_context.py", curl_args)

    def test_allows_python_command_without_file_read(self):
        """Python commands without file reads should be allowed."""
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["HOME"] = str(self.temp_path)

        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps({
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -c \"print('hello world')\""},
            }),
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
        )
        output = json.loads(result.stdout)
        self.assertTrue(output["continue"])


    def test_warns_git_show_head_on_protected_file(self):
        """git show HEAD:path gets warning on protected files."""
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "git show HEAD:src/core/project_context.py"},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_PROTECTED_FILE\nscope: src/core/project_context.py",
            },
        )

        self.assertTrue(output["continue"])
        hook_output = output["hookSpecificOutput"]
        self.assertIn("FIXONCE_PROTECTED_FILE", hook_output["additionalContext"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_warns_git_show_index_on_protected_file(self):
        """git show :path (index version) gets warning on protected files."""
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "git show :src/core/project_context.py"},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_PROTECTED_FILE\nscope: project_context.py",
            },
        )

        self.assertTrue(output["continue"])
        hook_output = output["hookSpecificOutput"]
        self.assertIn("FIXONCE_PROTECTED_FILE", hook_output["additionalContext"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_warns_git_show_commit_on_protected_file(self):
        """git show <commit>:path gets warning on protected files."""
        output, curl_args = self.run_hook(
            {
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "git show abc123def:src/core/project_context.py"},
            },
            {
                "count": 0,
                "warnings_count": 1,
                "context": "FIXONCE_PROTECTED_FILE\nscope: project_context.py",
            },
        )

        self.assertTrue(output["continue"])
        hook_output = output["hookSpecificOutput"]
        self.assertIn("FIXONCE_PROTECTED_FILE", hook_output["additionalContext"])
        self.assertIn("path=src/core/project_context.py", curl_args)

    def test_allows_git_status(self):
        """Normal git commands like git status should be allowed."""
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["HOME"] = str(self.temp_path)

        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps({
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
            }),
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
        )
        output = json.loads(result.stdout)
        self.assertTrue(output["continue"])

    def test_allows_git_log(self):
        """git log commands should be allowed."""
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["HOME"] = str(self.temp_path)

        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps({
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "git log --oneline -10"},
            }),
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
        )
        output = json.loads(result.stdout)
        self.assertTrue(output["continue"])

    def test_allows_git_diff_stat(self):
        """git diff --stat should be allowed."""
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["HOME"] = str(self.temp_path)

        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps({
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "git diff --stat"},
            }),
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
        )
        output = json.loads(result.stdout)
        self.assertTrue(output["continue"])


if __name__ == "__main__":
    unittest.main()
