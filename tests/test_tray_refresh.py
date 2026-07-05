"""
Tests for tray status refresh behavior.

Verifies that user actions (Expand, Open Full View) trigger immediate status refresh
before performing their primary action.

These tests verify the code structure rather than full integration, since the tray apps
depend on platform-specific GUI libraries (rumps for macOS, pystray for Windows).
"""

import ast
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


class TestMacOSMenuBarRefreshCodeStructure(unittest.TestCase):
    """Verify macOS menubar code structure includes refresh calls."""

    def setUp(self):
        """Parse the menubar_app.py source."""
        self.source_path = SCRIPTS_DIR / "menubar_app.py"
        self.source = self.source_path.read_text()
        self.tree = ast.parse(self.source)

    def _get_method_body(self, class_name: str, method_name: str) -> list:
        """Extract method body AST nodes."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == method_name:
                        return item.body
        return []

    def _has_update_status_call(self, body: list) -> bool:
        """Check if method body contains self._update_status() call."""
        for node in body:
            # Check for try/except wrapping _update_status
            if isinstance(node, ast.Try):
                for stmt in node.body:
                    if self._is_update_status_call(stmt):
                        return True
            if self._is_update_status_call(node):
                return True
        return False

    def _is_update_status_call(self, node) -> bool:
        """Check if a node is a call to self._update_status()."""
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute):
                if call.func.attr == "_update_status":
                    if isinstance(call.func.value, ast.Name) and call.func.value.id == "self":
                        return True
        return False

    def _update_status_before_action(self, body: list, action_attr: str) -> bool:
        """Verify _update_status is called before the main action."""
        found_refresh = False
        for node in body:
            # Track if we've seen the refresh call
            if isinstance(node, ast.Try):
                for stmt in node.body:
                    if self._is_update_status_call(stmt):
                        found_refresh = True
            if self._is_update_status_call(node):
                found_refresh = True

            # Check if this is the main action (subprocess.Popen or _open_dashboard_url)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute) and call.func.attr == action_attr:
                    # Found the action - refresh should have been called before
                    return found_refresh
            if isinstance(node, ast.If):
                # Check inside if blocks
                for stmt in node.body:
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                        call = stmt.value
                        if isinstance(call.func, ast.Attribute) and call.func.attr == action_attr:
                            return found_refresh
        return False

    def test_expand_app_has_update_status_call(self):
        """Verify _expand_app contains _update_status call."""
        body = self._get_method_body("FixOnceMenuBar", "_expand_app")
        self.assertTrue(body, "_expand_app method not found")
        self.assertTrue(
            self._has_update_status_call(body),
            "_expand_app should call self._update_status() for immediate refresh"
        )

    def test_open_full_view_has_update_status_call(self):
        """Verify _open_full_view contains _update_status call."""
        body = self._get_method_body("FixOnceMenuBar", "_open_full_view")
        self.assertTrue(body, "_open_full_view method not found")
        self.assertTrue(
            self._has_update_status_call(body),
            "_open_full_view should call self._update_status() for immediate refresh"
        )

    def test_expand_app_refresh_wrapped_in_try_except(self):
        """Verify _expand_app refresh is wrapped in try/except for resilience."""
        body = self._get_method_body("FixOnceMenuBar", "_expand_app")
        has_try_wrapped_refresh = False
        for node in body:
            if isinstance(node, ast.Try):
                for stmt in node.body:
                    if self._is_update_status_call(stmt):
                        has_try_wrapped_refresh = True
                        # Verify except clause exists and has pass/continue
                        self.assertTrue(node.handlers, "try block should have except handler")
        self.assertTrue(
            has_try_wrapped_refresh,
            "_update_status call should be wrapped in try/except"
        )


class TestWindowsTrayRefreshCodeStructure(unittest.TestCase):
    """Verify Windows tray code structure includes refresh calls."""

    def setUp(self):
        """Parse the tray_app_windows.py source."""
        self.source_path = SCRIPTS_DIR / "tray_app_windows.py"
        self.source = self.source_path.read_text()
        self.tree = ast.parse(self.source)

    def _get_method_body(self, class_name: str, method_name: str) -> list:
        """Extract method body AST nodes."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == method_name:
                        return item.body
        return []

    def _has_update_status_call(self, body: list) -> bool:
        """Check if method body contains self._update_status() call."""
        for node in body:
            if isinstance(node, ast.Try):
                for stmt in node.body:
                    if self._is_update_status_call(stmt):
                        return True
            if self._is_update_status_call(node):
                return True
        return False

    def _is_update_status_call(self, node) -> bool:
        """Check if a node is a call to self._update_status()."""
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute):
                if call.func.attr == "_update_status":
                    if isinstance(call.func.value, ast.Name) and call.func.value.id == "self":
                        return True
        return False

    def test_open_full_view_has_update_status_call(self):
        """Verify _open_full_view contains _update_status call."""
        body = self._get_method_body("FixOnceTray", "_open_full_view")
        self.assertTrue(body, "_open_full_view method not found")
        self.assertTrue(
            self._has_update_status_call(body),
            "_open_full_view should call self._update_status() for immediate refresh"
        )

    def test_open_full_view_refresh_wrapped_in_try_except(self):
        """Verify _open_full_view refresh is wrapped in try/except for resilience."""
        body = self._get_method_body("FixOnceTray", "_open_full_view")
        has_try_wrapped_refresh = False
        for node in body:
            if isinstance(node, ast.Try):
                for stmt in node.body:
                    if self._is_update_status_call(stmt):
                        has_try_wrapped_refresh = True
                        self.assertTrue(node.handlers, "try block should have except handler")
        self.assertTrue(
            has_try_wrapped_refresh,
            "_update_status call should be wrapped in try/except"
        )


if __name__ == "__main__":
    unittest.main()
