#!/usr/bin/env python3
"""
FixOnce - Native App Launcher
Supports two modes:
- Default: Menu bar app (always visible in menu bar)
- --window: Opens dashboard in a native window
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


def wait_for_server(start_port=5000, timeout=10):
    """Wait for the server to be ready. Tries multiple ports."""
    import urllib.request
    start = time.time()
    ports_to_try = [start_port + i for i in range(10)]  # Try 5000-5009

    while time.time() - start < timeout:
        for port in ports_to_try:
            try:
                url = f'http://localhost:{port}/api/health'
                req = urllib.request.urlopen(url, timeout=1)
                if req.status == 200:
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


def run_menubar_app():
    """Run the menu bar app."""
    try:
        import rumps
    except ImportError:
        print("Menu bar mode requires 'rumps'. Install with: pip install rumps")
        print("Falling back to window mode...")
        run_window_mode()
        return

    # Import and run the menu bar app
    sys.path.insert(0, SCRIPT_DIR)
    from menubar_app import FixOnceMenuBar
    app = FixOnceMenuBar()
    app.run()


def run_window_mode():
    """Run in window mode (opens dashboard in native window)."""
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

    dashboard_url = f'http://localhost:{port}/next'

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
            width=480,
            height=800,
            resizable=True,
            min_size=(400, 650),
            js_api=api
        )
        webview.start()
    except Exception as e:
        print(f"Native window failed: {e}")
        print("Opening in browser...")
        import webbrowser
        webbrowser.open(dashboard_url)


def main():
    """Main entry point."""
    # Parse arguments
    if '--menubar' in sys.argv or '-m' in sys.argv:
        run_menubar_app()
    elif '--help' in sys.argv or '-h' in sys.argv:
        print("FixOnce App Launcher")
        print("")
        print("Usage: python app_launcher.py [OPTIONS]")
        print("")
        print("Options:")
        print("  (default)    Run in window mode (dashboard)")
        print("  --menubar, -m Run as menu bar app")
        print("  --help, -h   Show this help")
    else:
        # Default: window mode
        run_window_mode()


if __name__ == '__main__':
    main()
