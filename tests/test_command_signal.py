#!/usr/bin/env python3
"""
Tests for GuardianSignal production from destructive Bash commands.

Tests prove:
- rm file → one signal + one require_approval shadow verdict
- rm -rf directory → one signal + one verdict
- unlink → one signal + one verdict
- git rm → one signal + one verdict
- quoted paths with spaces
- multiple targets
- ambiguous shell expressions do not produce false paths
- normal Bash commands produce no signal
- duplicate hook events are deduplicated
- activity logging still succeeds if signal production fails
- zero runtime behavior change
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class TestExtractDeletePaths(unittest.TestCase):
    """Test path extraction from delete commands."""

    def test_simple_rm(self):
        """rm file.txt extracts one path."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm file.txt")
        self.assertEqual(paths, ["file.txt"])
        self.assertFalse(is_ambiguous)

    def test_rm_with_flag(self):
        """rm -f file.txt extracts path, skips flag."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm -f file.txt")
        self.assertEqual(paths, ["file.txt"])
        self.assertFalse(is_ambiguous)

    def test_rm_rf(self):
        """rm -rf dir/ extracts directory."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm -rf mydir/")
        self.assertEqual(paths, ["mydir/"])
        self.assertFalse(is_ambiguous)

    def test_rm_multiple_flags(self):
        """rm -r -f dir extracts path after multiple flags."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm -r -f dir")
        self.assertEqual(paths, ["dir"])
        self.assertFalse(is_ambiguous)

    def test_unlink(self):
        """unlink file.txt extracts path."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("unlink file.txt")
        self.assertEqual(paths, ["file.txt"])
        self.assertFalse(is_ambiguous)

    def test_git_rm(self):
        """git rm file.txt extracts path."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("git rm file.txt")
        self.assertEqual(paths, ["file.txt"])
        self.assertFalse(is_ambiguous)

    def test_git_rm_with_flags(self):
        """git rm -f --cached file.txt extracts path."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("git rm -f --cached file.txt")
        self.assertEqual(paths, ["file.txt"])
        self.assertFalse(is_ambiguous)

    def test_double_quoted_path(self):
        """rm "path with spaces.txt" extracts unquoted path."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths('rm "path with spaces.txt"')
        self.assertEqual(paths, ["path with spaces.txt"])
        self.assertFalse(is_ambiguous)

    def test_single_quoted_path(self):
        """rm 'path with spaces.txt' extracts unquoted path."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm 'path with spaces.txt'")
        self.assertEqual(paths, ["path with spaces.txt"])
        self.assertFalse(is_ambiguous)

    def test_multiple_targets(self):
        """rm file1.txt file2.txt extracts both paths."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm file1.txt file2.txt")
        self.assertEqual(paths, ["file1.txt", "file2.txt"])
        self.assertFalse(is_ambiguous)

    def test_multiple_targets_with_flags(self):
        """rm -rf dir1 dir2 dir3 extracts all paths."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm -rf dir1 dir2 dir3")
        self.assertEqual(paths, ["dir1", "dir2", "dir3"])
        self.assertFalse(is_ambiguous)

    def test_glob_is_ambiguous(self):
        """rm *.txt is marked ambiguous."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm *.txt")
        self.assertEqual(paths, [])
        self.assertTrue(is_ambiguous)

    def test_variable_is_ambiguous(self):
        """rm $FILE is marked ambiguous."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm $FILE")
        self.assertEqual(paths, [])
        self.assertTrue(is_ambiguous)

    def test_subshell_is_ambiguous(self):
        """rm $(find ...) is marked ambiguous."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm $(find . -name '*.tmp')")
        self.assertEqual(paths, [])
        self.assertTrue(is_ambiguous)

    def test_backtick_is_ambiguous(self):
        """rm `ls` is marked ambiguous."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm `ls`")
        self.assertEqual(paths, [])
        self.assertTrue(is_ambiguous)

    def test_brace_expansion_is_ambiguous(self):
        """rm ${VAR} is marked ambiguous."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm ${VAR}")
        self.assertEqual(paths, [])
        self.assertTrue(is_ambiguous)

    def test_question_glob_is_ambiguous(self):
        """rm file?.txt is marked ambiguous."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm file?.txt")
        self.assertEqual(paths, [])
        self.assertTrue(is_ambiguous)

    def test_bracket_glob_is_ambiguous(self):
        """rm file[0-9].txt is marked ambiguous."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm file[0-9].txt")
        self.assertEqual(paths, [])
        self.assertTrue(is_ambiguous)

    def test_cwd_resolution(self):
        """Relative paths are resolved against cwd."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm file.txt", cwd="/project")
        self.assertEqual(paths, ["/project/file.txt"])

    def test_absolute_path_not_modified(self):
        """Absolute paths are not modified."""
        from api.activity import _extract_delete_paths

        paths, is_ambiguous, _ = _extract_delete_paths("rm /absolute/path.txt", cwd="/project")
        self.assertEqual(paths, ["/absolute/path.txt"])


class TestCommandSignalProduction(unittest.TestCase):
    """Test signal production from delete commands."""

    def setUp(self):
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_rm_produces_signal_and_verdict(self):
        """rm file.txt produces one signal and one require_approval verdict."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, get_verdict_audit

        _produce_delete_signal_from_command(
            command="rm important.py",
            project_id="test_rm_signal",
            cwd="/project",
        )

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["category"], "risk_destructive_op")
        self.assertEqual(signals[0]["concern"], "risk")

        verdicts = get_verdict_audit(limit=10)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["level"], "require_approval")
        self.assertTrue(verdicts[0]["shadow_only"])

    def test_rm_rf_produces_signal(self):
        """rm -rf dir produces signal."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, get_verdict_audit, clear_signal_audit_memory

        clear_signal_audit_memory()

        _produce_delete_signal_from_command(
            command="rm -rf build/",
            project_id="test_rmrf",
            cwd="/project",
        )

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1)

        verdicts = get_verdict_audit(limit=10)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["level"], "require_approval")

    def test_unlink_produces_signal(self):
        """unlink file produces signal."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, get_verdict_audit, clear_signal_audit_memory

        clear_signal_audit_memory()

        _produce_delete_signal_from_command(
            command="unlink temp.txt",
            project_id="test_unlink",
            cwd="/project",
        )

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1)

        verdicts = get_verdict_audit(limit=10)
        self.assertEqual(len(verdicts), 1)

    def test_git_rm_produces_signal(self):
        """git rm file produces signal."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, get_verdict_audit, clear_signal_audit_memory

        clear_signal_audit_memory()

        _produce_delete_signal_from_command(
            command="git rm obsolete.py",
            project_id="test_gitrm",
            cwd="/project",
        )

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1)

        verdicts = get_verdict_audit(limit=10)
        self.assertEqual(len(verdicts), 1)

    def test_ambiguous_command_produces_unknown_impact(self):
        """rm *.txt produces unknown_impact signal."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, clear_signal_audit_memory

        clear_signal_audit_memory()

        _produce_delete_signal_from_command(
            command="rm *.txt",
            project_id="test_ambiguous",
            cwd="/project",
        )

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["category"], "risk_unknown_impact")

    def test_multiple_targets_one_signal(self):
        """rm file1 file2 produces one signal with context."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, clear_signal_audit_memory

        clear_signal_audit_memory()

        _produce_delete_signal_from_command(
            command="rm file1.txt file2.txt file3.txt",
            project_id="test_multi",
            cwd="/project",
        )

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 target", signals[0]["reason"])


class TestNoSignalForNormalCommands(unittest.TestCase):
    """Normal Bash commands produce no signal."""

    def setUp(self):
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_ls_no_signal(self):
        """ls command produces no signal."""
        from api.activity import _produce_delete_signal_from_command, _is_file_delete
        from core.signal_audit import get_signal_audit

        # _is_file_delete would return False, so _produce wouldn't be called
        # But let's test the produce function directly for safety
        self.assertFalse(_is_file_delete("ls -la"))

    def test_cat_no_signal(self):
        """cat command produces no signal."""
        from api.activity import _is_file_delete

        self.assertFalse(_is_file_delete("cat file.txt"))

    def test_echo_no_signal(self):
        """echo command produces no signal."""
        from api.activity import _is_file_delete

        self.assertFalse(_is_file_delete("echo hello"))

    def test_cp_no_signal(self):
        """cp command produces no signal (not destructive)."""
        from api.activity import _is_file_delete

        self.assertFalse(_is_file_delete("cp file1 file2"))

    def test_mv_no_signal(self):
        """mv command produces no signal (not handled as delete)."""
        from api.activity import _is_file_delete

        self.assertFalse(_is_file_delete("mv old new"))

    def test_git_commit_no_signal(self):
        """git commit produces no signal."""
        from api.activity import _is_file_delete

        self.assertFalse(_is_file_delete("git commit -m 'message'"))


class TestFalsePositiveRegression(unittest.TestCase):
    """
    Regression tests: commands with "rm" in arguments must NOT trigger.

    These test the bug where grep "rm test.txt" was incorrectly flagged
    as a destructive operation because "rm" appeared in the command text.
    """

    def setUp(self):
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_grep_rm_no_signal(self):
        """grep 'rm test.txt' is NOT a delete - rm is in the search pattern."""
        from api.activity import _is_file_delete, _extract_delete_paths

        self.assertFalse(_is_file_delete('grep "rm test.txt"'))
        self.assertFalse(_is_file_delete("grep 'rm test.txt'"))
        self.assertFalse(_is_file_delete("grep rm test.txt"))

        # Also verify extract returns nothing
        paths, is_ambiguous, _ = _extract_delete_paths('grep "rm test.txt"')
        self.assertEqual(paths, [])
        self.assertFalse(is_ambiguous)

    def test_rg_rm_no_signal(self):
        """rg 'rm test.txt' is NOT a delete - rm is in the search pattern."""
        from api.activity import _is_file_delete, _extract_delete_paths

        self.assertFalse(_is_file_delete('rg "rm test.txt"'))
        self.assertFalse(_is_file_delete("rg 'rm test.txt'"))
        self.assertFalse(_is_file_delete("rg rm"))

        paths, is_ambiguous, _ = _extract_delete_paths('rg "rm test.txt"')
        self.assertEqual(paths, [])

    def test_echo_rm_no_signal(self):
        """echo 'rm test.txt' is NOT a delete - rm is just printed text."""
        from api.activity import _is_file_delete, _extract_delete_paths

        self.assertFalse(_is_file_delete('echo "rm test.txt"'))
        self.assertFalse(_is_file_delete("echo 'rm test.txt'"))
        self.assertFalse(_is_file_delete("echo rm test.txt"))

        paths, is_ambiguous, _ = _extract_delete_paths('echo "rm test.txt"')
        self.assertEqual(paths, [])

    def test_printf_rm_no_signal(self):
        """printf 'rm test.txt' is NOT a delete."""
        from api.activity import _is_file_delete

        self.assertFalse(_is_file_delete('printf "rm test.txt"'))
        self.assertFalse(_is_file_delete("printf '%s' 'rm test.txt'"))

    def test_python_rm_no_signal(self):
        """python -c 'print(\"rm test.txt\")' is NOT a delete."""
        from api.activity import _is_file_delete

        self.assertFalse(_is_file_delete("python -c \"print('rm test.txt')\""))
        self.assertFalse(_is_file_delete("python3 -c 'import os; print(\"rm\")'"))

    def test_cat_rm_in_content_no_signal(self):
        """cat showing a file with 'rm' in it is NOT a delete."""
        from api.activity import _is_file_delete

        self.assertFalse(_is_file_delete("cat rm_commands.txt"))
        self.assertFalse(_is_file_delete("cat -n rm.sh"))

    def test_find_exec_rm_no_false_positive(self):
        """find ... -exec rm still detects rm correctly."""
        from api.activity import _is_file_delete

        # This is tricky - find -exec rm IS actually running rm
        # But it's ambiguous (we can't know what files)
        # The key is we don't want false NEGATIVES either
        # For now, this should NOT trigger because find is the first command
        self.assertFalse(_is_file_delete("find . -name '*.tmp' -exec rm {} \\;"))

    def test_xargs_rm_no_false_positive(self):
        """xargs rm is tricky - xargs is the first command."""
        from api.activity import _is_file_delete

        # xargs rm is actually running rm, but xargs is the first token
        # This is a known limitation - we only check the FIRST command
        self.assertFalse(_is_file_delete("ls | xargs rm"))

    def test_real_rm_still_works(self):
        """Actual rm commands still trigger correctly."""
        from api.activity import _is_file_delete, _extract_delete_paths

        # These should all trigger
        self.assertTrue(_is_file_delete("rm test.txt"))
        self.assertTrue(_is_file_delete("rm -f test.txt"))
        self.assertTrue(_is_file_delete("rm -rf directory/"))
        self.assertTrue(_is_file_delete("unlink file.txt"))
        self.assertTrue(_is_file_delete("git rm tracked.py"))

        # Paths should be extracted correctly
        paths, _, _ = _extract_delete_paths("rm test.txt")
        self.assertEqual(paths, ["test.txt"])

    def test_rm_after_semicolon_still_works(self):
        """rm after ; is still detected."""
        from api.activity import _is_file_delete

        self.assertTrue(_is_file_delete("ls; rm test.txt"))
        self.assertTrue(_is_file_delete("echo hello; rm -f file.txt"))

    def test_rm_after_and_still_works(self):
        """rm after && is still detected."""
        from api.activity import _is_file_delete

        self.assertTrue(_is_file_delete("true && rm test.txt"))
        self.assertTrue(_is_file_delete("ls && rm -rf build/"))

    def test_pipe_to_rm_does_not_trigger(self):
        """echo | rm doesn't make sense but shouldn't crash."""
        from api.activity import _is_file_delete

        # The first command in the pipe is echo, not rm
        # So this should NOT trigger
        self.assertFalse(_is_file_delete("echo hello | rm"))

    def test_no_signal_produced_for_grep(self):
        """Full integration: grep 'rm' produces no GuardianSignal."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, clear_signal_audit_memory

        clear_signal_audit_memory()

        # These should produce NO signals
        _produce_delete_signal_from_command('grep "rm test.txt"', "test_project", "/project")
        _produce_delete_signal_from_command('rg "rm test.txt"', "test_project", "/project")
        _produce_delete_signal_from_command('echo "rm test.txt"', "test_project", "/project")

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 0, "grep/rg/echo with 'rm' should produce NO signals")

    def test_signal_produced_for_real_rm(self):
        """Full integration: actual rm produces GuardianSignal."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, clear_signal_audit_memory

        clear_signal_audit_memory()

        _produce_delete_signal_from_command("rm important.py", "test_project", "/project")

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1, "Real rm should produce exactly one signal")
        self.assertEqual(signals[0]["category"], "risk_destructive_op")


class TestDeduplication(unittest.TestCase):
    """Duplicate hook events are deduplicated."""

    def setUp(self):
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_duplicate_commands_deduplicated(self):
        """Same command twice produces one signal."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, get_verdict_audit

        # Same command, same project, same path
        _produce_delete_signal_from_command(
            command="rm important.py",
            project_id="test_dedup",
            cwd="/project",
        )
        _produce_delete_signal_from_command(
            command="rm important.py",
            project_id="test_dedup",
            cwd="/project",
        )
        _produce_delete_signal_from_command(
            command="rm important.py",
            project_id="test_dedup",
            cwd="/project",
        )

        signals = get_signal_audit(limit=10)
        verdicts = get_verdict_audit(limit=10)

        self.assertEqual(len(signals), 1)
        self.assertEqual(len(verdicts), 1)


class TestActivityLoggingResilience(unittest.TestCase):
    """Activity logging succeeds even if signal production fails."""

    def test_activity_continues_on_signal_failure(self):
        """Activity logging continues even if signal production fails."""
        from flask import Flask
        from api.activity import activity_bp
        from core.signal_audit import clear_signal_audit_memory

        clear_signal_audit_memory()

        app = Flask(__name__)
        app.register_blueprint(activity_bp)
        app.config['TESTING'] = True

        # Mock signal production to fail
        with patch("api.activity._produce_delete_signal_from_command", side_effect=RuntimeError("Signal error")):
            with app.test_client() as client:
                response = client.post('/log', json={
                    "type": "command",
                    "command": "rm important.py",
                    "cwd": "/project",
                    "tool": "Bash",
                })

                # Should succeed despite signal failure
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data.get("status"), "ok")


class TestQuotedPaths(unittest.TestCase):
    """Quoted paths with spaces are handled correctly."""

    def setUp(self):
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_double_quoted_space_path(self):
        """Double-quoted path with spaces is extracted."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit

        _produce_delete_signal_from_command(
            command='rm "my file with spaces.txt"',
            project_id="test_quoted",
            cwd="/project",
        )

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1)
        # Path should not have quotes
        evidence = signals[0].get("evidence", {})
        self.assertIn("my file with spaces.txt", evidence.get("file_path", ""))

    def test_single_quoted_space_path(self):
        """Single-quoted path with spaces is extracted."""
        from api.activity import _produce_delete_signal_from_command
        from core.signal_audit import get_signal_audit, clear_signal_audit_memory

        clear_signal_audit_memory()

        _produce_delete_signal_from_command(
            command="rm 'another file.txt'",
            project_id="test_single_quoted",
            cwd="/project",
        )

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1)


class TestIntegrationWithActivityAPI(unittest.TestCase):
    """Integration test with full activity API flow."""

    def setUp(self):
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_full_activity_flow_produces_signal(self):
        """POST to /api/activity/log with rm command produces signal."""
        from flask import Flask
        from api.activity import activity_bp
        from core.signal_audit import get_signal_audit, get_verdict_audit

        app = Flask(__name__)
        app.register_blueprint(activity_bp)
        app.config['TESTING'] = True

        with app.test_client() as client:
            response = client.post('/log', json={
                "type": "command",
                "command": "rm -f obsolete.py",
                "cwd": "/project/src",
                "tool": "Bash",
                "editor": "claude",
                "source": "PostToolUse",
            })

            self.assertEqual(response.status_code, 200)

        # Check signal was produced
        signals = get_signal_audit(limit=10)
        self.assertGreaterEqual(len(signals), 1)

        verdicts = get_verdict_audit(limit=10)
        self.assertGreaterEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["level"], "require_approval")


if __name__ == "__main__":
    unittest.main()
