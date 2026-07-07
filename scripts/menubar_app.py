#!/usr/bin/env python3
"""
FixOnce Menu Bar App (macOS)
A native macOS menu bar app for FixOnce with quick access to project status.

This is the tray-first interface for FixOnce. The browser dashboard
becomes "Full View" accessible from the menu.

Status is shown via title text next to the icon:
  (icon)         Connected, synced
  (icon) 3       3 memories waiting to save
  (icon) !       Needs attention
  (icon) -       Disconnected
"""

import subprocess
import threading
import time
import sys
import os
import json
import urllib.request
import urllib.error
import webbrowser
from datetime import datetime
from pathlib import Path

# ============================================================
# Path detection: bundle mode vs dev mode
# ============================================================

def _detect_run_mode() -> tuple[str, Path, Path]:
    """
    Detect whether running from:
    - 'frozen': PyInstaller bundle
    - 'macos_app': macOS app bundle in /Applications
    - 'dev': Development/repo mode

    Returns (mode, project_dir, src_dir)
    """
    if getattr(sys, "frozen", False):
        # PyInstaller frozen mode
        exe_path = Path(sys.executable).resolve()
        app_bundle = exe_path.parent.parent.parent  # .app directory
        resources = app_bundle / "Contents" / "Resources"
        return "frozen", resources, resources / "src"

    # Script mode - check if inside a macOS app bundle
    script_path = Path(__file__).resolve()

    # Check if we're inside /Applications/FixOnce.app
    path_str = str(script_path)
    if "/Applications/FixOnce.app/" in path_str:
        app_match = path_str.split("/Applications/FixOnce.app/")[0]
        app_bundle = Path(app_match) / "Applications" / "FixOnce.app"
        resources = app_bundle / "Contents" / "Resources"
        return "macos_app", resources, resources / "src"

    # Dev/repo mode: script is in scripts/, project is parent
    script_dir = script_path.parent
    project_dir = script_dir.parent
    return "dev", project_dir, project_dir / "src"


# Initialize paths based on run mode
_RUN_MODE, PROJECT_DIR, SERVER_DIR = _detect_run_mode()
# Scripts are always in a 'scripts' subdirectory, even in frozen mode
SCRIPT_DIR = PROJECT_DIR / "scripts"
DATA_DIR = PROJECT_DIR / "data"
USER_DATA_DIR = Path.home() / ".fixonce"
ASSETS_DIR = PROJECT_DIR / "assets"


def is_bundle_mode() -> bool:
    """Check if running from installed bundle (not dev/repo mode)."""
    return _RUN_MODE in ("frozen", "macos_app")


# Add src to path for lifecycle import
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# Menu bar icon path (color version for branding visibility)
MENUBAR_ICON = ASSETS_DIR / "menubar" / "icon_18x18@2x.png"
MENUBAR_ICON_TEMPLATE = ASSETS_DIR / "menubar" / "icon_18x18@2x_template.png"

# Try to import rumps for menu bar
try:
    import rumps
    from PyObjCTools import AppHelper
    HAS_RUMPS = True
except ImportError:
    HAS_RUMPS = False
    print("rumps not installed. Install with: pip install rumps")


class FixOnceMenuBar(rumps.App):
    """
    FixOnce menu bar application.

    Provides quick status visibility and actions without opening the full dashboard.
    The AI conversation remains the primary interface; this is the trust indicator.
    """

    DEFAULT_PORT = 5000
    PORT_RANGE = range(5000, 5010)
    UPDATE_INTERVAL = 5  # seconds

    def __init__(self):
        # Determine icon path - prefer color icon for branding
        icon_path = None
        if MENUBAR_ICON.exists():
            icon_path = str(MENUBAR_ICON)
        elif MENUBAR_ICON_TEMPLATE.exists():
            icon_path = str(MENUBAR_ICON_TEMPLATE)

        super().__init__(
            name="FixOnce",
            title="-",  # Start disconnected (shown next to icon)
            icon=icon_path,
            quit_button=None
        )

        # State
        self.server_running = False
        self.server_port = self.DEFAULT_PORT
        self.is_paused = False

        # Data from tray API
        self.status = "disconnected"
        self.pending_count = 0
        self.project_name = "No project"
        self.ai_client = None
        self.memory_stats = {"decisions": 0, "solved": 0, "avoid": 0}
        self.last_sync = None
        self.needs_attention = False
        self.attention_reason = None

        # Build initial menu
        self._build_menu()

        # Start background update thread
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()

    def _noop(self, _):
        """No-op callback for info items (makes them appear non-grayed)."""
        pass

    def _build_menu(self):
        """Build the menu structure."""
        self.menu.clear()

        # Status section - use _noop callback so items appear normal (not grayed)
        self.status_item = rumps.MenuItem("○ Connecting...", callback=self._noop)
        self.menu.add(self.status_item)

        self.project_item = rumps.MenuItem("", callback=self._noop)
        self.menu.add(self.project_item)

        self.ai_item = rumps.MenuItem("", callback=self._noop)
        self.menu.add(self.ai_item)

        self.sync_item = rumps.MenuItem("", callback=self._noop)
        self.menu.add(self.sync_item)

        self.memory_item = rumps.MenuItem("", callback=self._noop)
        self.menu.add(self.memory_item)

        self.menu.add(None)  # Separator

        # Quick actions
        self.expand_item = rumps.MenuItem("Expand", callback=self._expand_app)
        self.menu.add(self.expand_item)

        self.commit_item = rumps.MenuItem("Save", callback=self._commit_knowledge)
        self.commit_item.set_callback(None)  # Disabled until pending > 0
        self.menu.add(self.commit_item)

        self.menu.add(None)  # Separator

        # Pause/Resume
        self.pause_item = rumps.MenuItem("Pause", callback=self._toggle_pause)
        self.menu.add(self.pause_item)

        self.menu.add(None)  # Separator

        # Quit
        self.quit_item = rumps.MenuItem("Quit FixOnce", callback=self._quit_app)
        self.menu.add(self.quit_item)

    def _update_loop(self):
        """Background loop to update status."""
        while True:
            if not self.is_paused:
                try:
                    self._update_status()
                except Exception as e:
                    pass
            time.sleep(self.UPDATE_INTERVAL)

    def _discover_port(self):
        """Find which port FixOnce server is running on."""
        # First try runtime.json for canonical port
        runtime_file = USER_DATA_DIR / "runtime.json"
        if runtime_file.exists():
            try:
                runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
                hint_port = int(runtime.get("port", 0))
                if hint_port and self._check_port(hint_port):
                    return hint_port
            except Exception:
                pass

        # Try current_port.txt
        port_file = DATA_DIR / "current_port.txt"
        if port_file.exists():
            try:
                hint_port = int(port_file.read_text().strip())
                if self._check_port(hint_port):
                    return hint_port
            except Exception:
                pass

        # Scan port range
        for port in self.PORT_RANGE:
            if self._check_port(port):
                return port

        return None

    def _check_port(self, port):
        """Check if FixOnce is running on this port."""
        try:
            url = f"http://localhost:{port}/api/ping"
            with urllib.request.urlopen(url, timeout=1) as resp:
                data = json.loads(resp.read().decode())
                return data.get("service") == "fixonce"
        except Exception:
            return False

    def _update_status(self):
        """Fetch status from tray API and update display."""
        discovered = self._discover_port()

        if not discovered:
            self.server_running = False
            self.status = "disconnected"
            # Dispatch UI update to main thread
            AppHelper.callAfter(self._update_display)
            return

        self.server_port = discovered
        self.server_running = True

        try:
            url = f"http://localhost:{self.server_port}/api/tray/status"
            with urllib.request.urlopen(url, timeout=2) as response:
                data = json.loads(response.read().decode())

                self.status = data.get("status", "disconnected")
                self.pending_count = data.get("pending_count", 0)
                self.project_name = data.get("project_name", "No project")
                self.ai_client = data.get("ai_client")
                self.memory_stats = data.get("memory", {})
                self.last_sync = data.get("last_sync")
                self.needs_attention = data.get("needs_attention", False)
                self.attention_reason = data.get("attention_reason")

        except Exception as e:
            self.status = "problem"
            self.needs_attention = True
            self.attention_reason = str(e)

        # Dispatch UI update to main thread
        AppHelper.callAfter(self._update_display)

    def _update_display(self):
        """Update menu bar title and menu items."""
        # Update title with status indicator (shown next to icon)
        # Keep it minimal: empty when OK, number for pending, symbols for states
        if self.is_paused:
            self.title = "⏸"
        elif self.status == "disconnected":
            self.title = "-"
        elif self.status == "problem" or self.needs_attention:
            self.title = "!"
        elif self.pending_count > 0:
            self.title = str(self.pending_count)
        else:
            self.title = ""  # Clean look when everything is OK

        # Update status item
        if self.is_paused:
            self.status_item.title = "⏸ Paused"
        elif self.status == "connected":
            self.status_item.title = "● Connected"
        elif self.status == "pending":
            self.status_item.title = f"● {self.pending_count} pending"
        elif self.status == "problem":
            reason = self.attention_reason or "Unknown issue"
            self.status_item.title = f"⚠ {reason[:30]}"
        else:
            self.status_item.title = "○ Disconnected"

        # Update project
        if self.project_name and self.project_name != "No project":
            self.project_item.title = f"📁 {self.project_name}"
        else:
            self.project_item.title = "📁 No project"

        # Update AI client
        if self.ai_client:
            self.ai_item.title = f"🤖 {self.ai_client}"
        else:
            self.ai_item.title = "🤖 No AI connected"

        # Update last sync
        if self.last_sync:
            try:
                sync_dt = datetime.fromisoformat(self.last_sync.replace("Z", "+00:00"))
                now = datetime.now(sync_dt.tzinfo) if sync_dt.tzinfo else datetime.now()
                diff = now - sync_dt
                if diff.total_seconds() < 60:
                    sync_text = "just now"
                elif diff.total_seconds() < 3600:
                    mins = int(diff.total_seconds() / 60)
                    sync_text = f"{mins}m ago"
                else:
                    hours = int(diff.total_seconds() / 3600)
                    sync_text = f"{hours}h ago"
                self.sync_item.title = f"🔄 Synced {sync_text}"
            except Exception:
                self.sync_item.title = "🔄 Last sync unknown"
        else:
            self.sync_item.title = "🔄 Never synced"

        # Update memory stats
        d = self.memory_stats.get("decisions", 0)
        s = self.memory_stats.get("solved", 0)
        a = self.memory_stats.get("avoid", 0)
        self.memory_item.title = f"📊 {d}D · {s}B · {a}A"

        # Show/hide conditional items
        if self.pending_count > 0:
            self.commit_item.title = f"Save ({self.pending_count})"
            self.commit_item.set_callback(self._commit_knowledge)
        else:
            self.commit_item.title = "Save"
            self.commit_item.set_callback(None)

        # Update pause item text
        self.pause_item.title = "Resume" if self.is_paused else "Pause"

    def _open_dashboard_url(self, path=""):
        """Open dashboard URL, reusing existing tab if possible (macOS)."""
        base_url = f"http://localhost:{self.server_port}"
        full_url = f"{base_url}/{path}" if path else base_url

        # Try AppleScript to reuse existing Chrome tab
        applescript = f'''
        tell application "Google Chrome"
            set found to false
            repeat with w in windows
                repeat with t in tabs of w
                    if URL of t starts with "{base_url}" then
                        set URL of t to "{full_url}"
                        set active tab index of w to index of t
                        set index of w to 1
                        activate
                        set found to true
                        exit repeat
                    end if
                end repeat
                if found then exit repeat
            end repeat
            if not found then
                open location "{full_url}"
                activate
            end if
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", applescript],
                          capture_output=True, timeout=3)
        except Exception:
            # Fallback to standard webbrowser
            webbrowser.open(full_url)

    def _expand_app(self, _):
        """Open the native FixOnce app in dashboard mode."""
        # Refresh status immediately so tray reflects latest state
        try:
            self._update_status()
        except Exception:
            pass

        # Run app_launcher.py directly with --dashboard flag
        launcher_path = PROJECT_DIR / "scripts" / "app_launcher.py"
        subprocess.Popen(
            [sys.executable, str(launcher_path), "--dashboard"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

    def _open_full_view(self, _):
        """Open the full dashboard in browser."""
        # Refresh status immediately so tray reflects latest state
        try:
            self._update_status()
        except Exception:
            pass

        if self.server_running:
            self._open_dashboard_url()
        else:
            rumps.notification(
                title="FixOnce",
                subtitle="Server not running",
                message="Starting server..."
            )
            self._start_server()
            time.sleep(2)
            port = self._discover_port()
            if port:
                self.server_port = port
                self._open_dashboard_url()

    def _commit_knowledge(self, _):
        """Save all pending memories directly via API."""
        if not self.server_running or self.pending_count == 0:
            return

        try:
            # Get all pending item IDs
            pending_url = f"http://localhost:{self.server_port}/api/pending"
            with urllib.request.urlopen(pending_url, timeout=5) as resp:
                pending_data = json.loads(resp.read().decode())
                pending_ids = [item["id"] for item in pending_data.get("pending", [])]

            if not pending_ids:
                return

            # Approve all pending items
            approve_url = f"http://localhost:{self.server_port}/api/pending/approve"
            payload = json.dumps({"approved_ids": pending_ids}).encode()
            req = urllib.request.Request(
                approve_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())

            # Show result notification
            saved = result.get("saved", {})
            total = sum(saved.values())
            if result.get("status") == "ok":
                rumps.notification(
                    title="FixOnce",
                    subtitle="Memories saved",
                    message=f"Saved {total} memories"
                )
            else:
                rumps.notification(
                    title="FixOnce",
                    subtitle="Partial save",
                    message=f"Saved {total}, some failed"
                )

            # Trigger immediate status update
            self._update_status()

        except Exception as e:
            rumps.notification(
                title="FixOnce",
                subtitle="Save failed",
                message=str(e)[:50]
            )

    def _repair(self, _):
        """Attempt to repair connection."""
        rumps.notification(
            title="FixOnce",
            subtitle="Repairing...",
            message="Attempting to fix connection"
        )

        try:
            url = f"http://localhost:{self.server_port}/api/setup/repair-mcp"
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                if result.get("status") == "ok":
                    rumps.notification(
                        title="FixOnce",
                        subtitle="Repair complete",
                        message="Connection restored"
                    )
                else:
                    rumps.notification(
                        title="FixOnce",
                        subtitle="Repair incomplete",
                        message="Please check Full View for details"
                    )
        except Exception as e:
            rumps.notification(
                title="FixOnce",
                subtitle="Repair failed",
                message=str(e)[:50]
            )

    def _toggle_pause(self, _):
        """Toggle pause state."""
        self.is_paused = not self.is_paused
        self._update_display()

        state = "paused" if self.is_paused else "resumed"
        rumps.notification(
            title="FixOnce",
            subtitle=f"Updates {state}",
            message=""
        )

    def _open_settings(self, _):
        """Open settings (redirects to dashboard settings for now)."""
        if self.server_running:
            self._open_dashboard_url("#settings")
        else:
            rumps.notification(
                title="FixOnce",
                subtitle="Server not running",
                message="Cannot open settings"
            )

    def _start_server(self):
        """Start the Flask server."""
        server_script = SERVER_DIR / "server.py"
        subprocess.Popen(
            [sys.executable, str(server_script), "--flask-only"],
            cwd=str(SERVER_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

    def _quit_app(self, _):
        """Quit FixOnce completely - stops Flask server and menu bar app."""
        try:
            from core.lifecycle import shutdown_fixonce
            shutdown_fixonce(PROJECT_DIR)
        except Exception as e:
            pass
        rumps.quit_application()


def main():
    """Entry point for menu bar app."""
    if not HAS_RUMPS:
        print("Error: rumps is required for the menu bar app.")
        print("Install it with: pip install rumps")
        sys.exit(1)

    # Set activation policy to Accessory (no Dock icon, menu bar only)
    # This prevents "Python" from appearing in the Dock
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except ImportError:
        pass  # AppKit not available, continue anyway

    app = FixOnceMenuBar()
    app.run()


if __name__ == "__main__":
    main()
