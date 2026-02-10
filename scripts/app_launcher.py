#!/usr/bin/env python3
"""
FixOnce Desktop App Launcher
Opens the dashboard in a native window using pywebview
"""

import subprocess
import sys
import time
import threading
import requests
import os

def set_dock_icon():
    """Set the dock icon on macOS"""
    try:
        from AppKit import NSApplication, NSImage
        scripts_dir = os.path.dirname(__file__)
        project_dir = os.path.dirname(scripts_dir)
        icon_path = os.path.join(project_dir, "data", "FixOnce-Icon.png")
        if os.path.exists(icon_path):
            app = NSApplication.sharedApplication()
            icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
            app.setApplicationIconImage_(icon)
    except:
        pass  # Not on macOS or pyobjc not installed

def check_server_running(port=5000, timeout=10):
    """Check if server is running, start if not"""
    for _ in range(timeout):
        try:
            r = requests.get(f"http://localhost:{port}/", timeout=1)
            if r.status_code == 200:
                return port
        except:
            pass
        time.sleep(1)
    return None

def start_server():
    """Start the Flask server in background"""
    import os
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(scripts_dir)
    server_path = os.path.join(project_dir, "src", "server.py")

    subprocess.Popen(
        [sys.executable, server_path, "--flask-only"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.path.join(project_dir, "src"),
        start_new_session=True
    )

def launch_app():
    """Launch the desktop app"""
    try:
        import webview
    except ImportError:
        print("Installing pywebview...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pywebview", "-q"])
        import webview

    # Check if server is running
    port = check_server_running(timeout=2)

    if not port:
        print("Starting server...")
        start_server()
        port = check_server_running(timeout=10)

    if not port:
        print("Error: Could not start server")
        return

    # Set dock icon (macOS)
    set_dock_icon()

    # Launch window
    print(f"Opening FixOnce on port {port}...")
    webview.create_window(
        "FixOnce",
        f"http://localhost:{port}/",
        width=450,
        height=800,
        resizable=True,
        min_size=(400, 600)
    )
    webview.start()

if __name__ == "__main__":
    launch_app()
