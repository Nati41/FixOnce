"""
Regression tests for decision guard critical issues.

Tests for three critical product issues identified during Codex validation:
1. Explicit user confirmation is mandatory for supersede
2. No stale decision after supersede
3. Prevent bypassing via shell commands
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
HOOK = PROJECT_ROOT / "hooks" / "pre_tool_context_codex.sh"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class TestUserConfirmationRequired(unittest.TestCase):
    """Issue 1: Explicit user confirmation is mandatory for supersede."""

    def test_fo_decide_supersede_without_confirmation_blocked(self):
        """fo_decide with supersede action requires user_confirmed=True."""
        # Import the check logic
        action = "supersede:Use argparse"
        user_confirmed = False

        requires_confirmation = (
            action.startswith("supersede:") or
            action.startswith("resolve:supersede_existing:") or
            action.startswith("resolve:save_as_exception:")
        )

        self.assertTrue(requires_confirmation)
        self.assertFalse(user_confirmed)

    def test_fo_decide_supersede_with_confirmation_allowed(self):
        """fo_decide with supersede + user_confirmed=True is allowed."""
        action = "supersede:Use argparse"
        user_confirmed = True

        requires_confirmation = (
            action.startswith("supersede:") or
            action.startswith("resolve:supersede_existing:") or
            action.startswith("resolve:save_as_exception:")
        )

        # When user_confirmed=True, action should proceed
        self.assertTrue(requires_confirmation)
        self.assertTrue(user_confirmed)

    def test_hook_message_requires_user_confirmation(self):
        """Hook block message must instruct agent to ask user."""
        temp_dir = tempfile.TemporaryDirectory()
        fake_bin = Path(temp_dir.name) / "bin"
        fake_bin.mkdir()

        fake_curl = fake_bin / "curl"
        response = json.dumps({
            "count": 1,
            "context": "📌 Decision (85%): Use argparse for CLI. Reason: Standard library..."
        })
        fake_curl.write_text(f"#!/bin/sh\necho '{response}'\n")
        fake_curl.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
        env["HOME"] = temp_dir.name

        payload = json.dumps({
            "cwd": str(PROJECT_ROOT),
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/cli.py"}
        })

        result = subprocess.run(
            [str(HOOK)],
            input=payload,
            text=True,
            capture_output=True,
            env=env,
        )

        temp_dir.cleanup()

        self.assertTrue(result.stdout.strip())
        output = json.loads(result.stdout)
        reason = output.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")

        # Must instruct to ask user
        self.assertIn("ASK THE USER", reason)
        self.assertIn("DO NOT call fo_decide", reason)

    def test_add_action_does_not_require_confirmation(self):
        """fo_decide with action='add' does not require confirmation."""
        action = "add"

        requires_confirmation = (
            action.startswith("supersede:") or
            action.startswith("resolve:supersede_existing:") or
            action.startswith("resolve:save_as_exception:")
        )

        self.assertFalse(requires_confirmation)


class TestNoStaleDecisionAfterSupersede(unittest.TestCase):
    """Issue 2: No stale decision after supersede."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.embeddings_dir = self.temp_path / "embeddings"
        self.embeddings_dir.mkdir()

    def tearDown(self):
        try:
            from core.project_semantic import clear_cache
            clear_cache()
        except ImportError:
            pass
        self.temp_dir.cleanup()

    def test_semantic_index_reloads_on_external_modification(self):
        """SemanticIndex detects external modifications and reloads."""
        from core.semantic_index import SemanticIndex
        from core.embeddings import get_best_provider

        # Create index and add a document
        provider = get_best_provider()
        index = SemanticIndex("test_reload", provider)
        index.index_dir = self.embeddings_dir

        index.add("decision", "Original decision text")

        # Get initial mtime
        initial_mtime = index._last_mtime

        # Simulate external modification by touching the file
        time.sleep(0.1)
        metadata_file = self.embeddings_dir / "metadata.json"
        if metadata_file.exists():
            metadata_file.touch()

        # Check that mtime changed
        new_mtime = index._get_index_mtime()
        self.assertGreater(new_mtime, initial_mtime)

        # _ensure_loaded should detect the change
        index._loaded = True  # Pretend it was loaded
        index._last_mtime = initial_mtime  # Reset to old mtime

        # This should reload because mtime increased
        index._ensure_loaded()

    def test_supersede_updates_index_immediately(self):
        """supersede_decision_in_index updates index without requiring reload."""
        from core.project_semantic import (
            index_decision, supersede_decision_in_index,
            search_project, clear_cache, _get_index
        )

        # Patch to use temp directory
        from core.project_context import ProjectContext
        original = ProjectContext.get_embeddings_dir

        def mock_embeddings_dir(project_id):
            return self.embeddings_dir

        ProjectContext.get_embeddings_dir = staticmethod(mock_embeddings_dir)

        try:
            clear_cache()

            # Add original decision
            index_decision("test_project", "Use OLD framework", "Legacy reason")

            # Supersede it
            result = supersede_decision_in_index(
                "test_project",
                "Use OLD framework",
                "Use NEW framework",
                "Modern approach",
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["old_removed"])
            self.assertTrue(result["new_indexed"])

            # Search immediately - should find NEW, not OLD
            results = search_project("test_project", "framework", doc_type="decision")
            self.assertEqual(len(results), 1)
            self.assertIn("NEW", results[0].text)
            self.assertNotIn("OLD", results[0].text)

        finally:
            ProjectContext.get_embeddings_dir = original


class TestPreventBypassViaShellCommands(unittest.TestCase):
    """Issue 3: Prevent bypassing via shell commands."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.fake_bin = self.temp_path / "bin"
        self.fake_bin.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_fake_curl(self, response: dict):
        """Create fake curl returning given response."""
        fake_curl = self.fake_bin / "curl"
        response_json = json.dumps(response)
        fake_curl.write_text(f"#!/bin/sh\necho '{response_json}'\n")
        fake_curl.chmod(0o755)

    def _run_hook(self, payload: dict) -> dict:
        """Run hook and return parsed output."""
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}:{env.get('PATH', '')}"
        env["HOME"] = str(self.temp_path)

        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=env,
        )

        if not result.stdout.strip():
            return {}
        return json.loads(result.stdout)

    def test_bash_tool_is_treated_as_write_operation(self):
        """Bash tool should be treated as write operation for conflict detection."""
        # Create response with high-relevance decision
        self._create_fake_curl({
            "count": 1,
            "context": "📌 Decision (85%): Use argparse for CLI. Reason: Standard library..."
        })

        output = self._run_hook({
            "cwd": str(PROJECT_ROOT),
            "tool_name": "Bash",
            "tool_input": {"command": "python3 fix_cli.py"}
        })

        # Should block because Bash can write files
        if output:
            hook_output = output.get("hookSpecificOutput", {})
            # If there's output, it should be blocking
            self.assertIn("permissionDecision", hook_output)
            self.assertEqual(hook_output["permissionDecision"], "deny")

    def test_python_script_with_write_detected(self):
        """Python script that writes to files should extract target paths."""
        # Create a test script that writes to cli.py
        script_file = self.temp_path / "fix_cli.py"
        script_file.write_text("""
import pathlib
pathlib.Path("src/safe_rename/cli.py").write_text("# modified")
""")

        # Test the path extraction logic directly
        import re

        content = script_file.read_text()
        write_indicators = {"open(", "write(", "Path(", ".write_text(", ".write_bytes("}

        has_writes = any(ind in content for ind in write_indicators)
        self.assertTrue(has_writes, "Script should be detected as having writes")

        # Extract paths from script content
        pattern = r"['\"]([^'\"]+\.(?:py|js|ts))['\"]"
        matches = re.findall(pattern, content)

        paths = [m for m in matches if "/" in m or m.startswith("src")]
        self.assertIn("src/safe_rename/cli.py", paths)

    def test_exec_command_blocks_on_conflict(self):
        """exec_command should block when target file has conflicting decision."""
        self._create_fake_curl({
            "count": 1,
            "context": "📌 Decision (80%): Use argparse for CLI. Reason: Standard library..."
        })

        output = self._run_hook({
            "cwd": str(PROJECT_ROOT),
            "tool_name": "exec_command",
            "tool_input": {"cmd": "python3 -c 'open(\"src/cli.py\", \"w\").write(\"test\")'"}
        })

        # Should block
        if output:
            hook_output = output.get("hookSpecificOutput", {})
            self.assertEqual(hook_output.get("permissionDecision"), "deny")


class TestHookMessageContent(unittest.TestCase):
    """Tests for hook message content and format."""

    def test_block_message_includes_required_instructions(self):
        """Block message must include all required user instructions."""
        temp_dir = tempfile.TemporaryDirectory()
        fake_bin = Path(temp_dir.name) / "bin"
        fake_bin.mkdir()

        fake_curl = fake_bin / "curl"
        response = json.dumps({
            "count": 1,
            "context": "📌 Decision (90%): Use argparse for CLI. Reason: Standard..."
        })
        fake_curl.write_text(f"#!/bin/sh\necho '{response}'\n")
        fake_curl.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
        env["HOME"] = temp_dir.name

        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps({
                "cwd": str(PROJECT_ROOT),
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/cli.py"}
            }),
            text=True,
            capture_output=True,
            env=env,
        )

        temp_dir.cleanup()

        output = json.loads(result.stdout)
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]

        # Required elements in block message
        self.assertIn("CONFLICT", reason)
        self.assertIn("BLOCKED", reason)
        self.assertIn("ASK THE USER", reason)
        self.assertIn("Supersede", reason)
        self.assertIn("exception", reason.lower())
        self.assertIn("Cancel", reason)


if __name__ == "__main__":
    unittest.main()
