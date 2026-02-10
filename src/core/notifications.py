"""
FixOnce Desktop Notifications
macOS desktop notification support.
"""

import subprocess


def send_desktop_notification(title: str, message: str, sound: bool = False):
    """Send a macOS desktop notification."""
    try:
        # Escape quotes for AppleScript
        title = title.replace('"', '\\"')
        message = message.replace('"', '\\"')

        script = f'display notification "{message}" with title "{title}"'
        if sound:
            script += ' sound name "Basso"'

        subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            timeout=2
        )
    except Exception:
        pass  # Silent fail - notifications are optional
