#!/usr/bin/env python3
"""
FixOnce Menu Bar App
A native macOS menu bar app for FixOnce with quick access to project status.
"""

import subprocess
import threading
import time
import sys
import os
import json
import urllib.request
import urllib.error

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
SERVER_DIR = os.path.join(PROJECT_DIR, 'src')
DATA_DIR = os.path.join(PROJECT_DIR, 'data')

# Try to import rumps for menu bar
try:
    import rumps
    HAS_RUMPS = True
except ImportError:
    HAS_RUMPS = False
    print("rumps not installed. Install with: pip install rumps")


class FixOnceMenuBar(rumps.App):
    def __init__(self):
        super().__init__(
            name="FixOnce",
            title="🧠",
            quit_button=None
        )

        self.server_running = False
        self.current_project = None
        self.current_goal = None
        self.stats = {"decisions": 0, "insights": 0, "avoids": 0}

        # Build menu
        self.menu = [
            rumps.MenuItem("Loading...", callback=None),
            None,  # Separator
            rumps.MenuItem("Open Dashboard", callback=self.open_dashboard),
            rumps.MenuItem("Open Dashboard (vNext)", callback=self.open_dashboard_vnext),
            None,  # Separator
            rumps.MenuItem("Switch Project", callback=self.show_projects),
            None,  # Separator
            rumps.MenuItem("Start Server", callback=self.toggle_server),
            None,  # Separator
            rumps.MenuItem("Quit", callback=self.quit_app)
        ]

        # Start background update thread
        self.update_thread = threading.Thread(target=self.update_loop, daemon=True)
        self.update_thread.start()

    def update_loop(self):
        """Background loop to update status."""
        while True:
            try:
                self.update_status()
            except Exception as e:
                pass
            time.sleep(5)

    def update_status(self):
        """Fetch and update status from server."""
        try:
            url = 'http://localhost:5000/api/dashboard_snapshot'
            with urllib.request.urlopen(url, timeout=2) as response:
                data = json.loads(response.read().decode())
                self.server_running = True

                # Update data
                identity = data.get('identity', {})
                self.current_project = identity.get('project_name', 'Unknown')
                self.current_goal = identity.get('current_goal', '')

                memory = data.get('memory', {})
                self.stats = {
                    "decisions": memory.get('decisions', 0),
                    "insights": memory.get('insights', 0),
                    "avoids": memory.get('avoids', 0)
                }

                # Update menu
                self._update_menu()

        except (urllib.error.URLError, Exception):
            self.server_running = False
            self._update_menu()

    def _update_menu(self):
        """Update the menu with current status."""
        # Clear and rebuild status section
        while len(self.menu) > 0 and self.menu.keys()[0] != "Open Dashboard":
            del self.menu[self.menu.keys()[0]]

        if self.server_running:
            # Project name
            project_item = rumps.MenuItem(
                f"🟢 {self.current_project}",
                callback=None
            )
            self.menu.insert_before("Open Dashboard", project_item)

            # Goal (truncated)
            if self.current_goal:
                goal_short = self.current_goal[:40] + ('...' if len(self.current_goal) > 40 else '')
                goal_item = rumps.MenuItem(f"🎯 {goal_short}", callback=None)
                self.menu.insert_before("Open Dashboard", goal_item)

            # Stats
            stats_text = f"📊 {self.stats['decisions']}D · {self.stats['insights']}I · {self.stats['avoids']}A"
            stats_item = rumps.MenuItem(stats_text, callback=None)
            self.menu.insert_before("Open Dashboard", stats_item)

            # Separator
            self.menu.insert_before("Open Dashboard", None)

            # Update server toggle text
            self.menu["Start Server"].title = "Stop Server"

            # Update title (icon with indicator)
            self.title = "🧠"
        else:
            offline_item = rumps.MenuItem("⚪ Offline", callback=None)
            self.menu.insert_before("Open Dashboard", offline_item)
            self.menu.insert_before("Open Dashboard", None)

            self.menu["Start Server"].title = "Start Server"
            self.title = "🧠"

    @rumps.clicked("Open Dashboard")
    def open_dashboard(self, _):
        """Open the dashboard in browser."""
        import webbrowser
        webbrowser.open("http://localhost:5000/")

    @rumps.clicked("Open Dashboard (vNext)")
    def open_dashboard_vnext(self, _):
        """Open the vNext dashboard."""
        import webbrowser
        webbrowser.open("http://localhost:5000/next")

    @rumps.clicked("Switch Project")
    def show_projects(self, _):
        """Show project switcher (opens dashboard)."""
        import webbrowser
        webbrowser.open("http://localhost:5000/next#projects")

    @rumps.clicked("Start Server")
    def toggle_server(self, sender):
        """Start or stop the server."""
        if self.server_running:
            # Stop server
            try:
                subprocess.run(['pkill', '-f', 'server.py'], capture_output=True)
                rumps.notification(
                    title="FixOnce",
                    subtitle="Server Stopped",
                    message="The FixOnce server has been stopped."
                )
            except:
                pass
        else:
            # Start server
            self.start_server()
            rumps.notification(
                title="FixOnce",
                subtitle="Server Starting",
                message="The FixOnce server is starting..."
            )

    def start_server(self):
        """Start the Flask server."""
        server_script = os.path.join(SERVER_DIR, 'server.py')
        subprocess.Popen(
            [sys.executable, server_script, '--flask-only'],
            cwd=SERVER_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

    @rumps.clicked("Quit")
    def quit_app(self, _):
        """Quit the app."""
        rumps.quit_application()


def main():
    if not HAS_RUMPS:
        print("Error: rumps is required for the menu bar app.")
        print("Install it with: pip install rumps")
        sys.exit(1)

    app = FixOnceMenuBar()
    app.run()


if __name__ == '__main__':
    main()
