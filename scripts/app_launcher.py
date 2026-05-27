#!/usr/bin/env python3
"""
FixOnce - Official end-user launcher.

This launcher is the only user-facing entry point. It reuses an existing
background server when available, starts one quietly when needed, and opens the
dashboard without exposing implementation details.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Callable

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
SERVER_SCRIPT = PROJECT_DIR / "src" / "server.py"
USER_DATA_DIR = Path.home() / ".fixonce"
RUNTIME_FILE = USER_DATA_DIR / "runtime.json"
CONFIG_FILE = USER_DATA_DIR / "config.json"
LOCK_FILE = USER_DATA_DIR / "server.lock"
LOG_DIR = USER_DATA_DIR / "logs"
LAUNCHER_LOG = LOG_DIR / "app_launcher.log"
DEFAULT_PORT = 5000
PORT_RANGE = range(DEFAULT_PORT, DEFAULT_PORT + 10)
START_TIMEOUT_SECONDS = 12.0


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def log_event(message: str):
    """Append launcher diagnostics to a local log file."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LAUNCHER_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def set_dock_icon():
    """Set the Dock icon on macOS."""
    try:
        from AppKit import NSApplication, NSImage

        icon_path = PROJECT_DIR / "FixOnce.app" / "Contents" / "Resources" / "AppIcon.icns"
        if icon_path.exists():
            app = NSApplication.sharedApplication()
            icon = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
            app.setApplicationIconImage_(icon)
    except Exception:
        pass


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_saved_ports() -> list[int]:
    """Return candidate ports from canonical runtime.json and fallback config.json."""
    candidates: list[int] = []
    for path in (RUNTIME_FILE, CONFIG_FILE):
        data = read_json(path)
        port = data.get("port")
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            continue
        if port_int not in candidates:
            candidates.append(port_int)
    return candidates


def is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def clear_stale_state():
    """Remove stale runtime and lock files that point to dead processes."""
    runtime = read_json(RUNTIME_FILE)
    runtime_pid = runtime.get("pid")
    if runtime_pid:
        try:
            runtime_pid = int(runtime_pid)
        except (TypeError, ValueError):
            runtime_pid = None
    if runtime_pid and not is_pid_running(runtime_pid):
        try:
            RUNTIME_FILE.unlink()
            log_event("Removed stale runtime.json")
        except OSError:
            pass

    if LOCK_FILE.exists():
        try:
            lock_pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
        except Exception:
            lock_pid = None

        if lock_pid is None or not is_pid_running(lock_pid):
            try:
                LOCK_FILE.unlink()
                log_event("Removed stale server.lock")
            except OSError:
                pass


def endpoint_responds(port: int, endpoint: str, timeout: float = 1.0) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{endpoint}", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def get_ping_payload(port: int, timeout: float = 1.0) -> dict:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as response:
            if response.status != 200:
                return {}
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def is_current_install_server(port: int) -> bool:
    """Return True only for a FixOnce server owned by this launcher install."""
    payload = get_ping_payload(port)
    if payload.get("service") != "fixonce":
        return False

    # Older servers did not publish install_path. Rejecting them prevents this
    # launcher from reusing stale servers from another FixOnce copy.
    install_path = payload.get("install_path")
    if not install_path or is_frozen():
        return bool(install_path or is_frozen())

    try:
        return Path(install_path).resolve() == PROJECT_DIR.resolve()
    except Exception:
        return False


def discover_running_port() -> int | None:
    """Find a healthy FixOnce server, preferring saved canonical ports."""
    checked: list[int] = []
    for port in read_saved_ports():
        checked.append(port)
        if is_current_install_server(port):
            return port

    for port in PORT_RANGE:
        if port in checked:
            continue
        if is_current_install_server(port):
            return port
    return None


def wait_for_server(timeout: float = START_TIMEOUT_SECONDS) -> int | None:
    """Wait for the background server to become healthy."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        port = discover_running_port()
        if port is not None and endpoint_responds(port, "/api/health", timeout=1.5):
            return port
        time.sleep(0.5)
    return None


def get_dashboard_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def get_windows_pythonw(executable: str) -> str:
    """Best-effort resolve pythonw.exe path from current Python executable."""
    exe = Path(executable)
    if exe.name.lower() == "pythonw.exe":
        return str(exe)

    candidates = [
        exe.with_name("pythonw.exe"),
        Path(sys.prefix) / "pythonw.exe",
        Path(sys.base_prefix) / "pythonw.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return executable


def start_server():
    """Start the background server quietly."""
    clear_stale_state()
    if not is_frozen() and not SERVER_SCRIPT.exists():
        raise FileNotFoundError("FixOnce is missing required files.")

    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if is_frozen():
            command = [sys.executable, "--server", "--flask-only", "--quiet"]
        else:
            python_cmd = get_windows_pythonw(sys.executable)
            command = [python_cmd, str(SERVER_SCRIPT), "--flask-only", "--quiet"]

        subprocess.Popen(
            command,
            cwd=str(PROJECT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    else:
        subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT), "--flask-only", "--quiet"],
            cwd=str(PROJECT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    log_event("Requested background server start")


def open_dashboard(port: int):
    """Open the dashboard in a native window only."""
    set_dock_icon()
    dashboard_url = get_dashboard_url(port)

    class Api:
        def open_url(self, url):
            webbrowser.open(url)

    try:
        import webview

        window = webview.create_window(
            "FixOnce",
            dashboard_url,
            width=480,
            height=800,
            resizable=True,
            min_size=(400, 650),
            js_api=Api(),
        )
        webview.start()
        return
    except Exception as exc:
        log_event(f"Native window unavailable: {exc}")
        raise RuntimeError("FixOnce could not open its app window.") from exc


def open_logs_folder():
    """Open the FixOnce log directory for support scenarios."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    target = str(LOG_DIR)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        log_event(f"Failed to open logs folder: {exc}")


def run_repair_action() -> bool:
    """Attempt a quiet self-repair by clearing stale state and restarting."""
    clear_stale_state()
    try:
        start_server()
    except Exception as exc:
        log_event(f"Repair start failed: {exc}")
        return False
    return wait_for_server(timeout=START_TIMEOUT_SECONDS) is not None


def show_failure_window(retry_callback: Callable[[], bool], repair_callback: Callable[[], bool]):
    """Show a friendly no-terminal failure window."""
    message = (
        "FixOnce couldn't open right now.\n\n"
        "You can try again, run a quick repair, or open diagnostics."
    )

    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()

        while True:
            choice = messagebox.askquestion(
                "FixOnce needs attention",
                message,
                icon="warning",
                type="yesnocancel",
                default="yes",
                detail="Yes = Retry    No = Repair    Cancel = Close",
            )

            if choice == "yes":
                if retry_callback():
                    root.destroy()
                    return
                message = "FixOnce still isn't ready. You can retry, repair, or open diagnostics."
                continue

            if choice == "no":
                if repair_callback():
                    root.destroy()
                    return
                open_logs = messagebox.askyesno(
                    "FixOnce still needs help",
                    "Repair didn't finish successfully.\n\nOpen diagnostics now?",
                    icon="warning",
                )
                if open_logs:
                    open_logs_folder()
                continue

            root.destroy()
            return

    except Exception as exc:
        log_event(f"Failure window unavailable: {exc}")
        open_logs_folder()


def ensure_server_ready() -> int:
    """Reuse an existing server or start one quietly in the background."""
    port = discover_running_port()
    if port is not None and endpoint_responds(port, "/api/health", timeout=1.5):
        log_event("Reused existing server")
        return port

    start_server()
    port = wait_for_server()
    if port is None:
        raise RuntimeError("FixOnce background service did not become ready.")

    log_event("Background server became ready")
    return port


def launch_app() -> bool:
    """Launch the user experience end-to-end."""
    try:
        port = ensure_server_ready()
    except Exception as exc:
        log_event(f"Initial launch failed: {exc}")
        return False

    open_dashboard(port)
    return True


def run_menubar_app():
    """Optional menu bar mode for advanced users."""
    try:
        import rumps
    except ImportError:
        if not launch_app():
            show_failure_window(launch_app, lambda: run_repair_action() and launch_app())
        return

    sys.path.insert(0, str(SCRIPT_DIR))
    from menubar_app import FixOnceMenuBar

    app = FixOnceMenuBar()
    app.run()


def run_server_mode(argv: list[str]):
    """Run the bundled Flask server without opening the app window."""
    if is_frozen():
        from server import main as server_main
    else:
        sys.path.insert(0, str(PROJECT_DIR / "src"))
        from server import main as server_main

    server_main(argv)


def main():
    if "--server" in sys.argv:
        server_args = [arg for arg in sys.argv[1:] if arg != "--server"]
        run_server_mode(server_args)
        return

    if "--menubar" in sys.argv or "-m" in sys.argv:
        run_menubar_app()
        return

    if launch_app():
        return

    show_failure_window(launch_app, lambda: run_repair_action() and launch_app())


if __name__ == "__main__":
    main()
