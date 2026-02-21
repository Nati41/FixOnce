#!/usr/bin/env python3
"""
FixOnce - Native App Launcher
Opens the dashboard in a native window using pywebview
"""

import subprocess
import time
import sys
import os

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
SERVER_DIR = os.path.join(PROJECT_DIR, 'src')

def set_dock_icon():
    """Set the Dock icon on macOS."""
    try:
        from AppKit import NSApplication, NSImage
        icon_path = os.path.join(PROJECT_DIR, 'FixOnce.app', 'Contents', 'Resources', 'AppIcon.icns')
        if os.path.exists(icon_path):
            app = NSApplication.sharedApplication()
            icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
            app.setApplicationIconImage_(icon)
    except:
        pass

def wait_for_server(port=5000, timeout=10):
    """Wait for the server to be ready."""
    import urllib.request
    start = time.time()

    while time.time() - start < timeout:
        try:
            url = f'http://localhost:{port}/'
            urllib.request.urlopen(url, timeout=1)
            return port
        except:
            pass
        time.sleep(0.5)
    return None

def start_server():
    """Start the Flask server in background."""
    server_script = os.path.join(SERVER_DIR, 'server.py')

    subprocess.Popen(
        [sys.executable, server_script, '--flask-only'],
        cwd=SERVER_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

def main():
    # Set Dock icon on macOS
    set_dock_icon()

    # Check if server is running
    port = wait_for_server(timeout=2)

    if not port:
        print("Starting server...")
        start_server()
        port = wait_for_server(timeout=10)

    if not port:
        print("Error: Could not start server")
        return

    dashboard_url = f'http://localhost:{port}/app'

    # API for JavaScript to call
    class Api:
        def open_url(self, url):
            import webbrowser
            webbrowser.open(url)

    # Try native window first, fall back to browser
    try:
        import webview
        api = Api()
        window = webview.create_window(
            'FixOnce',
            dashboard_url,
            width=380,
            height=620,
            resizable=True,
            min_size=(320, 500),
            js_api=api
        )
        webview.start()
    except Exception as e:
        print(f"Native window failed: {e}")
        print("Opening in browser...")
        import webbrowser
        webbrowser.open(dashboard_url)

if __name__ == '__main__':
    main()
