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
SERVER_DIR = os.path.join(SCRIPT_DIR, 'server')

def set_dock_icon():
    """Set the Dock icon on macOS."""
    try:
        from AppKit import NSApplication, NSImage
        icon_path = os.path.join(SCRIPT_DIR, 'FixOnce.app', 'Contents', 'Resources', 'AppIcon.icns')
        if os.path.exists(icon_path):
            app = NSApplication.sharedApplication()
            icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
            app.setApplicationIconImage_(icon)
    except ImportError:
        pass  # PyObjC not installed
    except Exception:
        pass

def kill_port_5000():
    """Kill any process using port 5000."""
    try:
        result = subprocess.run(['lsof', '-ti', ':5000'], capture_output=True, text=True)
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                subprocess.run(['kill', '-9', pid], capture_output=True)
            time.sleep(1)
    except:
        pass

def start_server():
    """Start the Flask server in background."""
    server_script = os.path.join(SERVER_DIR, 'server.py')
    log_file = os.path.join(SCRIPT_DIR, 'server.log')

    # Server needs stdin open (for MCP stdio), so use PIPE
    # Log file for stdout/stderr
    log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)

    subprocess.Popen(
        [sys.executable, server_script],
        cwd=SERVER_DIR,
        stdin=subprocess.PIPE,  # Keep stdin open for MCP
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True
    )

    os.close(log_fd)

def wait_for_server(timeout=15):
    """Wait for the server to be ready and return the port."""
    import urllib.request
    start = time.time()

    # Check port file first
    port_file = os.path.join(SERVER_DIR, 'current_port.txt')

    while time.time() - start < timeout:
        # Try to read port from file
        if os.path.exists(port_file):
            try:
                port = int(open(port_file).read().strip())
                url = f'http://localhost:{port}/api/ping'
                urllib.request.urlopen(url, timeout=1)
                return port
            except:
                pass

        # Fallback: scan ports
        for port in [5000, 5001, 5002, 5003, 5004, 5005]:
            try:
                url = f'http://localhost:{port}/api/ping'
                urllib.request.urlopen(url, timeout=1)
                return port
            except:
                pass

        time.sleep(0.5)

    return None

def main():
    # Set Dock icon on macOS
    set_dock_icon()

    print("🚀 FixOnce - Starting...")
    print("   Never debug the same bug twice")
    print()

    # Kill existing server on port 5000
    kill_port_5000()

    # Start server in background
    print("[1/3] Starting server...")
    start_server()

    # Wait for server
    print("[2/3] Waiting for server...")
    port = wait_for_server()
    if not port:
        print("❌ Server failed to start!")
        print("   Try running manually: cd server && python3 server.py")
        return

    dashboard_url = f'http://localhost:{port}/brain'
    print(f"[3/3] Opening FixOnce Workspace on port {port}...")
    print()

    # Try native window first, fall back to browser
    native_window = False
    try:
        import webview
        print("Opening native window...")
        window = webview.create_window(
            'FixOnce Workspace',
            dashboard_url,
            width=420,
            height=750,
            resizable=True,
            on_top=False
        )
        native_window = True
        webview.start()
    except Exception as e:
        if not native_window:
            print(f"⚠️  Native window failed: {e}")
            print("   Opening in browser instead...")
            import webbrowser
            webbrowser.open(dashboard_url)

            print()
            print("✅ FixOnce is running!")
            print(f"   Dashboard: {dashboard_url}")
            print("   Press Ctrl+C to stop")
            print()

            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n👋 FixOnce stopped")

if __name__ == '__main__':
    main()
