#!/usr/bin/env python3
"""
FixOnce File Watcher
Passively watches for file changes and reports to FixOnce API.
Works with ANY tool - Cursor, VS Code, manual edits, etc.
"""

import os
import sys
import json
import time
import requests
import argparse
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


def _get_api_url() -> str:
    """
    Get the API URL from runtime.json.

    Falls back to port 5000 if runtime.json doesn't exist.
    """
    try:
        runtime_file = Path.home() / ".fixonce" / "runtime.json"
        if runtime_file.exists():
            with open(runtime_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            port = state.get("port", 5000)
            return f"http://localhost:{port}/api/activity/log"
    except Exception:
        pass
    return "http://localhost:5000/api/activity/log"


# Configuration - read from runtime.json
API_URL = _get_api_url()
DEBOUNCE_SECONDS = 1.0  # Avoid duplicate events

# Files/folders to ignore
IGNORE_PATTERNS = [
    '.git', 'node_modules', '__pycache__', '.next', '.nuxt',
    'venv', 'env', '.env', 'dist', 'build', '.cache',
    '.DS_Store', 'Thumbs.db', '*.pyc', '*.pyo', '*.log',
    '.idea', '.vscode', '*.swp', '*.swo', '*~',
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    '.fixonce_backups'
]

# File extensions to track
TRACK_EXTENSIONS = [
    '.py', '.js', '.ts', '.tsx', '.jsx', '.vue', '.svelte',
    '.html', '.css', '.scss', '.sass', '.less',
    '.json', '.yaml', '.yml', '.toml', '.md',
    '.go', '.rs', '.java', '.kt', '.swift',
    '.c', '.cpp', '.h', '.hpp', '.cs',
    '.rb', '.php', '.sh', '.bash', '.zsh',
    '.sql', '.graphql', '.prisma'
]


class FixOnceHandler(FileSystemEventHandler):
    """Handles file system events and reports to FixOnce."""

    def __init__(self, project_dir: str, source: str = "file_watcher"):
        self.project_dir = project_dir
        self.source = source
        self.last_events = {}  # For debouncing

    def should_ignore(self, path: str) -> bool:
        """Check if path should be ignored."""
        path_lower = path.lower()

        # Check ignore patterns
        for pattern in IGNORE_PATTERNS:
            if pattern.startswith('*'):
                if path_lower.endswith(pattern[1:]):
                    return True
            elif pattern in path:
                return True

        return False

    def should_track(self, path: str) -> bool:
        """Check if file extension should be tracked."""
        ext = Path(path).suffix.lower()
        return ext in TRACK_EXTENSIONS

    def is_debounced(self, path: str) -> bool:
        """Check if event should be debounced."""
        now = time.time()
        last_time = self.last_events.get(path, 0)

        if now - last_time < DEBOUNCE_SECONDS:
            return True

        self.last_events[path] = now
        return False

    def report_activity(self, path: str, event_type: str):
        """Send activity to FixOnce API."""
        try:
            data = {
                "type": "file_change",
                "tool": self.source,
                "file": path,
                "cwd": self.project_dir,
                "timestamp": datetime.now().isoformat(),
                "event": event_type  # created, modified, deleted
            }

            response = requests.post(API_URL, json=data, timeout=2)

            if response.ok:
                file_name = Path(path).name
                print(f"  📝 {file_name} ({event_type})")
            else:
                print(f"  ⚠️ API error: {response.status_code}")

        except requests.exceptions.ConnectionError:
            print(f"  ❌ FixOnce server not running")
        except Exception as e:
            print(f"  ❌ Error: {e}")

    def process_event(self, event, event_type: str):
        """Process a file system event."""
        if event.is_directory:
            return

        path = event.src_path

        if self.should_ignore(path):
            return

        if not self.should_track(path):
            return

        if self.is_debounced(path):
            return

        self.report_activity(path, event_type)

    def on_created(self, event):
        self.process_event(event, "created")

    def on_modified(self, event):
        self.process_event(event, "modified")

    def on_deleted(self, event):
        self.process_event(event, "deleted")

    def on_moved(self, event):
        # Report as delete + create
        if not event.is_directory:
            if not self.should_ignore(event.src_path):
                self.report_activity(event.src_path, "deleted")
            if not self.should_ignore(event.dest_path) and self.should_track(event.dest_path):
                self.report_activity(event.dest_path, "created")


def watch_directory(path: str, source: str = "file_watcher"):
    """Start watching a directory for changes."""
    path = os.path.abspath(path)

    if not os.path.isdir(path):
        print(f"❌ Directory not found: {path}")
        sys.exit(1)

    project_name = Path(path).name

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  FixOnce File Watcher                                        ║
╠══════════════════════════════════════════════════════════════╣
║  📁 Watching: {project_name:<45} ║
║  🔗 API: {API_URL:<50} ║
║  📝 Source: {source:<47} ║
╠══════════════════════════════════════════════════════════════╣
║  Tracking file changes from ANY tool:                        ║
║  Cursor, VS Code, Vim, manual edits...                       ║
║                                                              ║
║  Press Ctrl+C to stop                                        ║
╚══════════════════════════════════════════════════════════════╝
""")

    event_handler = FixOnceHandler(path, source)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Stopping file watcher...")
        observer.stop()

    observer.join()
    print("✅ File watcher stopped")


def main():
    parser = argparse.ArgumentParser(
        description="FixOnce File Watcher - Track file changes from any tool"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to watch (default: current directory)"
    )
    parser.add_argument(
        "--source",
        default="file_watcher",
        help="Source name for activity log (default: file_watcher)"
    )

    args = parser.parse_args()
    watch_directory(args.path, args.source)


if __name__ == "__main__":
    main()
