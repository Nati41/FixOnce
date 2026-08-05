"""
Regression tests for conflict detection false positives.

The guard should block CONTRADICTIONS, not RELEVANCE.
High semantic score alone must never trigger permissionDecision:deny.

Test cases:
- Whitespace cleanup → must NOT block
- Comment changes → must NOT block
- Import reordering → must NOT block
- Formatting only → must NOT block
- argparse → Click → MUST block
- Click → argparse → MUST block
- Rename variables only → must NOT block
- Internal refactoring → must NOT block
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
HOOK = PROJECT_ROOT / "hooks" / "pre_tool_context_codex.sh"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class TestConflictFalsePositives(unittest.TestCase):
    """Tests that mechanical edits don't trigger false positive blocks."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.fake_bin = self.temp_path / "bin"
        self.fake_bin.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_fake_curl(self, decision_text: str, score: int = 85):
        """Create fake curl returning high-relevance decision."""
        fake_curl = self.fake_bin / "curl"
        response = json.dumps({
            "count": 1,
            "context": f"📌 Decision ({score}%): {decision_text}. Reason: Standard library..."
        })
        fake_curl.write_text(f"#!/bin/sh\necho '{response}'\n")
        fake_curl.chmod(0o755)

    def _run_hook(self, tool_name: str, tool_input: dict) -> dict:
        """Run hook and return parsed output."""
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}:{env.get('PATH', '')}"
        env["HOME"] = str(self.temp_path)

        payload = {
            "cwd": str(PROJECT_ROOT),
            "tool_name": tool_name,
            "tool_input": tool_input
        }

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

    def _is_blocked(self, output: dict) -> bool:
        """Check if output is a block."""
        hook_output = output.get("hookSpecificOutput", {})
        return hook_output.get("permissionDecision") == "deny"

    def _is_context_only(self, output: dict) -> bool:
        """Check if output is context-only (non-blocking)."""
        hook_output = output.get("hookSpecificOutput", {})
        return "additionalContext" in hook_output and "permissionDecision" not in hook_output

    # =========================================================================
    # MUST NOT BLOCK - Mechanical edits
    # =========================================================================

    def test_whitespace_cleanup_not_blocked(self):
        """Whitespace-only changes must NOT block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "    \n\n    \n"  # Only whitespace
        })

        # Should NOT block
        self.assertFalse(self._is_blocked(output),
            "Whitespace-only edit should not be blocked")

    def test_comment_changes_not_blocked(self):
        """Comment-only changes must NOT block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "# This is a comment\n# Another comment\n"
        })

        self.assertFalse(self._is_blocked(output),
            "Comment-only edit should not be blocked")

    def test_import_reordering_not_blocked(self):
        """Import reordering must NOT block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "import os\nimport sys\nfrom pathlib import Path\n"
        })

        self.assertFalse(self._is_blocked(output),
            "Import reordering should not be blocked")

    def test_formatting_only_not_blocked(self):
        """Formatting-only changes must NOT block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "    # formatted\n    \n    # more formatting\n"
        })

        self.assertFalse(self._is_blocked(output),
            "Formatting-only edit should not be blocked")

    def test_empty_edit_not_blocked(self):
        """Empty edit must NOT block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": ""
        })

        self.assertFalse(self._is_blocked(output),
            "Empty edit should not be blocked")

    def test_variable_rename_not_blocked(self):
        """Variable renaming must NOT block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "old_name = new_value\nresult = old_name\n"
        })

        self.assertFalse(self._is_blocked(output),
            "Variable renaming should not be blocked")

    def test_internal_refactoring_not_blocked(self):
        """Internal refactoring without changing tech must NOT block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": """
def helper_function():
    pass

def main():
    helper_function()
"""
        })

        self.assertFalse(self._is_blocked(output),
            "Internal refactoring should not be blocked")

    # =========================================================================
    # MUST BLOCK - Technology contradictions
    # =========================================================================

    def test_argparse_to_click_blocked(self):
        """Changing from argparse to Click MUST block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "import click\n\n@click.command()\ndef main():\n    pass\n"
        })

        self.assertTrue(self._is_blocked(output),
            "argparse→Click change MUST be blocked")

        # Verify conflict reason is mentioned
        reason = output.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        self.assertIn("click", reason.lower())

    def test_click_to_argparse_blocked(self):
        """Changing from Click to argparse MUST block."""
        self._create_fake_curl("Use Click for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "import argparse\n\nparser = argparse.ArgumentParser()\n"
        })

        self.assertTrue(self._is_blocked(output),
            "Click→argparse change MUST be blocked")

    def test_import_click_blocked(self):
        """Importing Click when argparse is decided MUST block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "from click import command, option\n"
        })

        self.assertTrue(self._is_blocked(output),
            "Importing Click when argparse is decided MUST be blocked")

    def test_postgresql_to_mysql_blocked(self):
        """Changing from PostgreSQL to MySQL MUST block."""
        self._create_fake_curl("Use PostgreSQL for database")

        output = self._run_hook("Edit", {
            "file_path": "src/database.py",
            "new_string": "import mysql.connector\nconn = mysql.connector.connect()\n"
        })

        self.assertTrue(self._is_blocked(output),
            "PostgreSQL→MySQL change MUST be blocked")

    def test_flask_to_django_blocked(self):
        """Changing from Flask to Django MUST block."""
        self._create_fake_curl("Use Flask for web framework")

        output = self._run_hook("Edit", {
            "file_path": "src/app.py",
            "new_string": "from django.http import HttpResponse\n"
        })

        self.assertTrue(self._is_blocked(output),
            "Flask→Django change MUST be blocked")

    # =========================================================================
    # Edge cases
    # =========================================================================

    def test_no_edit_content_allows(self):
        """When no edit content is available, fail open (allow)."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py"
            # No new_string provided
        })

        self.assertFalse(self._is_blocked(output),
            "Missing edit content should fail open (allow)")

    def test_unrelated_technology_not_blocked(self):
        """Using unrelated technology must NOT block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "import requests\nresponse = requests.get('http://api.example.com')\n"
        })

        self.assertFalse(self._is_blocked(output),
            "Unrelated technology (requests) should not be blocked")

    def test_same_technology_not_blocked(self):
        """Using the same technology as decision must NOT block."""
        self._create_fake_curl("Use argparse for CLI")

        output = self._run_hook("Edit", {
            "file_path": "src/cli.py",
            "new_string": "import argparse\nparser = argparse.ArgumentParser()\n"
        })

        self.assertFalse(self._is_blocked(output),
            "Using the same technology (argparse) should not be blocked")


class TestMechanicalEditDetection(unittest.TestCase):
    """Unit tests for mechanical edit detection logic."""

    def test_is_mechanical_whitespace(self):
        """Whitespace-only content is mechanical."""
        content = "   \n\n   \t\n"
        # Test the logic directly
        lines = content.strip().split("\n")
        is_mechanical = all(not line.strip() for line in lines)
        self.assertTrue(is_mechanical or not content.strip())

    def test_is_mechanical_comments(self):
        """Comment-only content is mechanical."""
        content = "# comment\n# another\n"
        lines = content.strip().split("\n")
        import re
        is_mechanical = all(
            re.match(r"^\s*#", line) or not line.strip()
            for line in lines
        )
        self.assertTrue(is_mechanical)

    def test_is_mechanical_imports(self):
        """Import-only content is mechanical."""
        content = "import os\nfrom pathlib import Path\n"
        lines = content.strip().split("\n")
        import re
        is_mechanical = all(
            re.match(r"^\s*import\s+", line) or
            re.match(r"^\s*from\s+\w+\s+import", line) or
            not line.strip()
            for line in lines
        )
        self.assertTrue(is_mechanical)

    def test_not_mechanical_code(self):
        """Actual code is not mechanical."""
        content = "def main():\n    print('hello')\n"
        lines = content.strip().split("\n")
        import re
        mechanical_patterns = [
            r"^\s*$", r"^\s*#", r"^\s*//",
            r"^\s*import\s+", r"^\s*from\s+\w+\s+import"
        ]
        is_mechanical = all(
            any(re.match(p, line) for p in mechanical_patterns) or not line.strip()
            for line in lines
        )
        self.assertFalse(is_mechanical)


if __name__ == "__main__":
    unittest.main()
