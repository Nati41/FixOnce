"""
Test install end flow behavior.

Ensures install success path:
- Does NOT prompt for Y/n
- Does NOT call app_launcher or open_dashboard
- Ends with clear message only
"""

import ast
import sys
from pathlib import Path


def get_install_source():
    """Read install.py source code."""
    install_path = Path(__file__).parent.parent / "scripts" / "install.py"
    return install_path.read_text()


class TestInstallEndFlow:
    """Test that install end flow is clean (no prompts, no auto-open)."""

    def test_no_yn_prompt_in_success_path(self):
        """Install success should not prompt user with Y/n."""
        source = get_install_source()

        # The success message section should not have input() for Y/n
        # Find the success message section
        success_idx = source.find("FixOnce installed successfully")
        assert success_idx > 0, "Should have success message"

        # Get the code after the success message until end of function
        after_success = source[success_idx:success_idx + 500]

        # Should NOT have Y/n prompt
        assert "Y/n" not in after_success, "Should not prompt for Y/n after success"
        assert "input(" not in after_success, "Should not call input() after success"

    def test_no_app_launcher_call_in_success_path(self):
        """Install success should not auto-launch app."""
        source = get_install_source()

        success_idx = source.find("FixOnce installed successfully")
        after_success = source[success_idx:success_idx + 500]

        # Should NOT launch app_launcher
        assert "app_launcher" not in after_success, "Should not call app_launcher after success"
        assert "--dashboard" not in after_success, "Should not pass --dashboard after success"

    def test_no_open_dashboard_in_success_path(self):
        """Install success should not open dashboard/browser."""
        source = get_install_source()

        success_idx = source.find("FixOnce installed successfully")
        after_success = source[success_idx:success_idx + 500]

        # Should NOT open browser/dashboard
        assert "webbrowser" not in after_success, "Should not use webbrowser after success"
        assert "open_dashboard" not in after_success, "Should not call open_dashboard after success"

    def test_success_message_mentions_menu_bar(self):
        """Install success should mention menu bar tray."""
        source = get_install_source()

        success_idx = source.find("FixOnce installed successfully")
        after_success = source[success_idx:success_idx + 300]

        assert "menu bar" in after_success, "Should mention menu bar"
        assert "Expand" in after_success, "Should mention Expand action"

    def test_success_path_returns_immediately(self):
        """After success message, should return True without prompts."""
        source = get_install_source()

        success_idx = source.find("FixOnce installed successfully")
        after_success = source[success_idx:success_idx + 500]

        # Should have return True relatively soon after success message
        return_idx = after_success.find("return True")
        assert return_idx > 0, "Should return True after success"
        assert return_idx < 300, f"return True should be within 300 chars of success message, found at {return_idx}"

        # Nothing between success message and return except prints
        between = after_success[:return_idx]
        # Should only have print statements, no subprocess or input
        assert "subprocess" not in between, "Should not call subprocess between success and return"
        assert "input(" not in between, "Should not call input() between success and return"
