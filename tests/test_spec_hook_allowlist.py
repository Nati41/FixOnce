"""Test that PyInstaller spec files include all required hooks."""

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent

REQUIRED_HOOKS_WINDOWS = {
    "hooks/session_start.sh",
    "hooks/session_end.sh",
    "hooks/post_tool_use.sh",
    "hooks/pre_tool_context.sh",
    "hooks/pre_tool_context_codex.sh",
    "hooks/session_start.ps1",
    "hooks/session_end.ps1",
    "hooks/post_tool_use.ps1",
    "hooks/pre_tool_context_codex.ps1",
}

REQUIRED_HOOKS_MACOS = {
    "hooks/session_start.sh",
    "hooks/session_end.sh",
    "hooks/post_tool_use.sh",
    "hooks/pre_tool_context.sh",
    "hooks/pre_tool_context_codex.sh",
}


class TestSpecHookAllowlist(unittest.TestCase):
    def test_windows_spec_includes_required_hooks(self):
        spec_path = PROJECT_ROOT / "fixonce.spec"
        content = spec_path.read_text(encoding="utf-8")

        for hook in REQUIRED_HOOKS_WINDOWS:
            self.assertIn(
                f'"{hook}"',
                content,
                f"fixonce.spec missing required hook: {hook}"
            )

    def test_macos_spec_includes_required_hooks(self):
        spec_path = PROJECT_ROOT / "fixonce_macos.spec"
        content = spec_path.read_text(encoding="utf-8")

        for hook in REQUIRED_HOOKS_MACOS:
            self.assertIn(
                f'"{hook}"',
                content,
                f"fixonce_macos.spec missing required hook: {hook}"
            )

    def test_required_hooks_exist(self):
        all_hooks = REQUIRED_HOOKS_WINDOWS | REQUIRED_HOOKS_MACOS
        for hook in all_hooks:
            hook_path = PROJECT_ROOT / hook
            self.assertTrue(
                hook_path.exists(),
                f"Required hook file does not exist: {hook}"
            )


if __name__ == "__main__":
    unittest.main()
