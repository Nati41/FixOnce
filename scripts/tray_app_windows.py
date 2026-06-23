#!/usr/bin/env python3
"""
FixOnce System Tray App (Windows)
A native Windows system tray app for FixOnce with quick access to project status.

This is the tray-first interface for FixOnce. The browser dashboard
becomes "Full View" accessible from the tray menu.

Uses the FixOnce app icon with status overlay:
- Connected: green dot
- Pending: blue dot with count badge
- Problem: red dot
- Disconnected: gray appearance

Requires: pystray, pillow
"""

import threading
import time
import sys
import os
import json
import urllib.request
import urllib.error
import webbrowser
import subprocess
from datetime import datetime
from pathlib import Path
from io import BytesIO

# Get directories
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
SERVER_DIR = PROJECT_DIR / "src"
DATA_DIR = PROJECT_DIR / "data"
USER_DATA_DIR = Path.home() / ".fixonce"
ASSETS_DIR = PROJECT_DIR / "assets"

# Icon paths
ICON_ICO = PROJECT_DIR / "FixOnce.ico"
ICON_PNG = ASSETS_DIR / "FixOnce.iconset" / "icon_64x64@2x.png"
ICON_FALLBACK = ASSETS_DIR / "FixOnce.png"

# Try to import pystray and PIL
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False
    print("pystray or Pillow not installed. Install with: pip install pystray pillow")


def load_base_icon() -> "Image.Image":
    """Load the FixOnce app icon from available sources."""
    # Try ICO first (best for Windows)
    if ICON_ICO.exists():
        try:
            img = Image.open(str(ICON_ICO))
            # ICO files may have multiple sizes, get largest
            if hasattr(img, 'n_frames') and img.n_frames > 1:
                sizes = []
                for i in range(img.n_frames):
                    img.seek(i)
                    sizes.append((img.size[0], i))
                sizes.sort(reverse=True)
                img.seek(sizes[0][1])
            return img.convert("RGBA")
        except Exception:
            pass

    # Try PNG from iconset
    if ICON_PNG.exists():
        try:
            return Image.open(str(ICON_PNG)).convert("RGBA")
        except Exception:
            pass

    # Try fallback PNG
    if ICON_FALLBACK.exists():
        try:
            return Image.open(str(ICON_FALLBACK)).convert("RGBA")
        except Exception:
            pass

    # Last resort: create a simple placeholder
    size = 64
    img = Image.new("RGBA", (size, size), (59, 130, 246, 255))
    draw = ImageDraw.Draw(img)
    draw.text((size//4, size//4), "FO", fill=(255, 255, 255, 255))
    return img


def create_icon_image(status: str = "disconnected", pending_count: int = 0) -> "Image.Image":
    """
    Create a system tray icon based on status.

    Uses the actual FixOnce app icon with status overlay:
    - connected: green status dot
    - pending: blue dot with count badge
    - problem: red status dot
    - disconnected: grayscale icon
    """
    # Load base icon
    base = load_base_icon()

    # Resize to standard tray size (64x64 works well)
    size = 64
    img = base.resize((size, size), Image.Resampling.LANCZOS)

    # For disconnected state, convert to grayscale
    if status == "disconnected":
        # Convert to grayscale while preserving alpha
        r, g, b, a = img.split()
        gray = Image.merge("RGB", (r, g, b)).convert("L")
        img = Image.merge("RGBA", (gray, gray, gray, a))

    draw = ImageDraw.Draw(img)

    # Status indicator dot in bottom-right corner
    dot_radius = 8
    dot_x = size - dot_radius - 2
    dot_y = size - dot_radius - 2

    # Draw white outline for visibility
    draw.ellipse(
        [dot_x - dot_radius - 2, dot_y - dot_radius - 2,
         dot_x + dot_radius + 2, dot_y + dot_radius + 2],
        fill=(255, 255, 255, 255)
    )

    # Draw status dot
    if status == "connected":
        dot_color = (34, 197, 94, 255)  # Green
    elif status == "pending":
        dot_color = (59, 130, 246, 255)  # Blue
    elif status == "problem":
        dot_color = (239, 68, 68, 255)  # Red
    else:
        dot_color = (156, 163, 175, 255)  # Gray

    draw.ellipse(
        [dot_x - dot_radius, dot_y - dot_radius,
         dot_x + dot_radius, dot_y + dot_radius],
        fill=dot_color
    )

    # Add pending count badge if needed
    if pending_count > 0:
        badge_radius = 10
        badge_x = size - badge_radius - 2
        badge_y = badge_radius + 2

        # White outline
        draw.ellipse(
            [badge_x - badge_radius - 2, badge_y - badge_radius - 2,
             badge_x + badge_radius + 2, badge_y + badge_radius + 2],
            fill=(255, 255, 255, 255)
        )

        # Red badge background
        draw.ellipse(
            [badge_x - badge_radius, badge_y - badge_radius,
             badge_x + badge_radius, badge_y + badge_radius],
            fill=(239, 68, 68, 255)
        )

        # Badge text
        count_text = str(pending_count) if pending_count < 10 else "9+"
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), count_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        draw.text(
            (badge_x - text_width // 2, badge_y - text_height // 2 - 1),
            count_text,
            fill=(255, 255, 255, 255),
            font=font
        )

    return img


class FixOnceTray:
    """
    FixOnce system tray application for Windows.

    Provides quick status visibility and actions without opening the full dashboard.
    """

    DEFAULT_PORT = 5000
    PORT_RANGE = range(5000, 5010)
    UPDATE_INTERVAL = 5  # seconds

    def __init__(self):
        # State
        self.server_running = False
        self.server_port = self.DEFAULT_PORT
        self.is_paused = False
        self.is_running = True

        # Data from tray API
        self.status = "disconnected"
        self.pending_count = 0
        self.project_name = "No project"
        self.ai_client = None
        self.memory_stats = {"decisions": 0, "solved": 0, "avoid": 0}
        self.last_sync = None
        self.needs_attention = False
        self.attention_reason = None

        # Create initial icon
        self.icon = pystray.Icon(
            "FixOnce",
            create_icon_image("disconnected"),
            "FixOnce - Connecting...",
            menu=self._create_menu()
        )

    def _create_menu(self) -> pystray.Menu:
        """Create the tray menu."""
        return pystray.Menu(
            pystray.MenuItem(
                lambda text: self._get_status_text(),
                None,
                enabled=False
            ),
            pystray.MenuItem(
                lambda text: self._get_project_text(),
                None,
                enabled=False
            ),
            pystray.MenuItem(
                lambda text: self._get_ai_text(),
                None,
                enabled=False
            ),
            pystray.MenuItem(
                lambda text: self._get_sync_text(),
                None,
                enabled=False
            ),
            pystray.MenuItem(
                lambda text: self._get_memory_text(),
                None,
                enabled=False
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Full View", self._open_full_view),
            pystray.MenuItem(
                lambda text: f"Commit Knowledge ({self.pending_count})" if self.pending_count > 0 else "Commit Knowledge",
                self._commit_knowledge,
                visible=lambda item: self.pending_count > 0
            ),
            pystray.MenuItem(
                "Repair",
                self._repair,
                visible=lambda item: self.needs_attention
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda text: "Resume" if self.is_paused else "Pause",
                self._toggle_pause
            ),
            pystray.MenuItem("Switch Project", pystray.Menu(
                pystray.MenuItem("Open in Full View", self._open_projects)
            )),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings", self._open_settings),
            pystray.MenuItem("Quit FixOnce", self._quit_app)
        )

    def _get_status_text(self) -> str:
        """Get status line text."""
        if self.is_paused:
            return "⏸ Paused"
        elif self.status == "connected":
            return "● Connected"
        elif self.status == "pending":
            return f"● {self.pending_count} pending"
        elif self.status == "problem":
            reason = self.attention_reason or "Unknown issue"
            return f"⚠ {reason[:30]}"
        else:
            return "○ Disconnected"

    def _get_project_text(self) -> str:
        """Get project line text."""
        if self.project_name and self.project_name != "No project":
            return f"📁 {self.project_name}"
        return "📁 No project"

    def _get_ai_text(self) -> str:
        """Get AI client line text."""
        if self.ai_client:
            return f"🤖 {self.ai_client}"
        return "🤖 No AI connected"

    def _get_sync_text(self) -> str:
        """Get last sync line text."""
        if self.last_sync:
            try:
                sync_dt = datetime.fromisoformat(self.last_sync.replace("Z", "+00:00"))
                now = datetime.now(sync_dt.tzinfo) if sync_dt.tzinfo else datetime.now()
                diff = now - sync_dt
                if diff.total_seconds() < 60:
                    return "🔄 Synced just now"
                elif diff.total_seconds() < 3600:
                    mins = int(diff.total_seconds() / 60)
                    return f"🔄 Synced {mins}m ago"
                else:
                    hours = int(diff.total_seconds() / 3600)
                    return f"🔄 Synced {hours}h ago"
            except Exception:
                pass
        return "🔄 Never synced"

    def _get_memory_text(self) -> str:
        """Get memory stats line text."""
        d = self.memory_stats.get("decisions", 0)
        s = self.memory_stats.get("solved", 0)
        a = self.memory_stats.get("avoid", 0)
        return f"📊 {d}D · {s}B · {a}A"

    def _discover_port(self) -> int | None:
        """Find which port FixOnce server is running on."""
        # Try runtime.json first
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

    def _check_port(self, port: int) -> bool:
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
            self._update_icon()
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

        self._update_icon()

    def _update_icon(self):
        """Update tray icon based on current status."""
        status = "disconnected"
        if self.is_paused:
            status = "disconnected"
        elif self.status == "problem" or self.needs_attention:
            status = "problem"
        elif self.pending_count > 0:
            status = "pending"
        elif self.status == "connected":
            status = "connected"

        # Update icon image
        self.icon.icon = create_icon_image(status, self.pending_count)

        # Update tooltip
        tooltip_parts = ["FixOnce"]
        if self.project_name and self.project_name != "No project":
            tooltip_parts.append(self.project_name)
        if self.status == "connected":
            tooltip_parts.append("Connected")
        elif self.status == "pending":
            tooltip_parts.append(f"{self.pending_count} pending")
        elif self.status == "problem":
            tooltip_parts.append("Needs attention")
        else:
            tooltip_parts.append("Disconnected")

        self.icon.title = " - ".join(tooltip_parts)

        # Force menu refresh
        self.icon.update_menu()

    def _update_loop(self):
        """Background update loop."""
        while self.is_running:
            if not self.is_paused:
                try:
                    self._update_status()
                except Exception:
                    pass
            time.sleep(self.UPDATE_INTERVAL)

    def _open_full_view(self, icon=None, item=None):
        """Open the full dashboard in browser."""
        if self.server_running:
            webbrowser.open(f"http://localhost:{self.server_port}/")
        else:
            self._start_server()
            time.sleep(2)
            port = self._discover_port()
            if port:
                webbrowser.open(f"http://localhost:{port}/")

    def _commit_knowledge(self, icon=None, item=None):
        """Open commit knowledge in dashboard."""
        if self.server_running and self.pending_count > 0:
            webbrowser.open(f"http://localhost:{self.server_port}/#commit")

    def _repair(self, icon=None, item=None):
        """Attempt to repair connection."""
        try:
            url = f"http://localhost:{self.server_port}/api/setup/repair-mcp"
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception:
            pass

    def _toggle_pause(self, icon=None, item=None):
        """Toggle pause state."""
        self.is_paused = not self.is_paused
        self._update_icon()

    def _open_projects(self, icon=None, item=None):
        """Open projects view in dashboard."""
        if self.server_running:
            webbrowser.open(f"http://localhost:{self.server_port}/#projects")

    def _open_settings(self, icon=None, item=None):
        """Open settings in dashboard."""
        if self.server_running:
            webbrowser.open(f"http://localhost:{self.server_port}/#settings")

    def _start_server(self):
        """Start the Flask server."""
        server_script = SERVER_DIR / "server.py"

        # Use no-window flags on Windows
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW

        subprocess.Popen(
            [sys.executable, str(server_script), "--flask-only"],
            cwd=str(SERVER_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags
        )

    def _quit_app(self, icon=None, item=None):
        """Quit the tray app."""
        self.is_running = False
        self.icon.stop()

    def run(self):
        """Run the tray application."""
        # Start update thread
        update_thread = threading.Thread(target=self._update_loop, daemon=True)
        update_thread.start()

        # Run icon (blocking)
        self.icon.run()


def main():
    """Entry point for Windows tray app."""
    if not HAS_PYSTRAY:
        print("Error: pystray and Pillow are required for the system tray app.")
        print("Install with: pip install pystray pillow")
        sys.exit(1)

    app = FixOnceTray()
    app.run()


if __name__ == "__main__":
    main()
