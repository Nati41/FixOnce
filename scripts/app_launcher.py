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
import shutil
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
BOOTSTRAP_LOG = LOG_DIR / "bootstrap.log"
BOOTSTRAP_TASK_NAME = "FixOnceServer"
BOOTSTRAP_STARTUP_SHORTCUT_NAME = "FixOnceServer.lnk"
AUTOSTART_METHOD_SCHEDULED_TASK = "scheduled_task"
AUTOSTART_METHOD_STARTUP_SHORTCUT = "startup_shortcut"
AUTOSTART_METHOD_NONE = "none"
DEFAULT_PORT = 5000
PORT_RANGE = range(DEFAULT_PORT, DEFAULT_PORT + 10)
START_TIMEOUT_SECONDS = 12.0
BOOTSTRAP_HEALTH_TIMEOUT_SECONDS = 45.0


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def windows_process_creationflags(detached: bool = True) -> int:
    """Return Windows flags that isolate child processes from console control events."""
    if sys.platform != "win32":
        return 0

    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if detached:
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return flags


def log_event(message: str):
    """Append launcher diagnostics to a local log file."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LAUNCHER_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def bootstrap_log(message: str):
    """Append first-run bootstrap diagnostics to ~/.fixonce/logs/bootstrap.log."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with BOOTSTRAP_LOG.open("a", encoding="utf-8") as handle:
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


def wait_for_health(timeout: float = BOOTSTRAP_HEALTH_TIMEOUT_SECONDS, log_fn: Callable[[str], None] | None = None) -> int | None:
    """Wait until /api/health returns OK on a FixOnce server owned by this install."""
    write_log = log_fn or bootstrap_log
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        port = discover_running_port()
        if port is not None and endpoint_responds(port, "/api/health", timeout=1.5):
            write_log(f"Health OK on port {port} (attempt {attempt})")
            return port
        write_log(f"Waiting for /api/health (attempt {attempt})")
        time.sleep(0.5)
    write_log("Timed out waiting for /api/health")
    return None


def get_packaged_install_dir() -> Path:
    """Directory containing the packaged FixOnce.exe."""
    return Path(sys.executable).resolve().parent


def get_packaged_server_command() -> list[str]:
    """Command line used for background server and scheduled-task autostart."""
    return [sys.executable, "--server"]


def _import_install_state_helpers():
    if is_frozen():
        from core.install_state_machine import InstallState, persist_snapshot
    else:
        sys.path.insert(0, str(PROJECT_DIR / "src"))
        from core.install_state_machine import InstallState, persist_snapshot
    return InstallState, persist_snapshot


def _packaged_mcp_server_path() -> Path | None:
    """Return the packaged MCP server source path used by stdio clients."""
    install_dir = get_packaged_install_dir()
    candidates = [
        install_dir / "src" / "mcp_server" / "mcp_memory_server_v2.py",
        install_dir / "_internal" / "src" / "mcp_server" / "mcp_memory_server_v2.py",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.insert(0, Path(meipass) / "src" / "mcp_server" / "mcp_memory_server_v2.py")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _external_python_command() -> str | None:
    """Resolve a user Python command for stdio MCP config."""
    for command in ("python", "python3", "py"):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return None


def configure_packaged_windows_mcp(log_fn: Callable[[str], None] | None = None) -> bool:
    """Register per-user MCP config for packaged Windows installs."""
    write_log = log_fn or bootstrap_log
    if sys.platform != "win32":
        write_log("MCP registration skipped: not Windows")
        return False

    mcp_server = _packaged_mcp_server_path()
    if mcp_server is None:
        write_log("MCP registration skipped: mcp_memory_server_v2.py not found")
        return False

    python_command = _external_python_command()
    if python_command is None:
        write_log("MCP registration skipped: Python command not found")
        return False

    try:
        from core.mcp_config import build_stdio_mcp_config, write_codex_config

        src_path = str(mcp_server.parent.parent)
        stdio_config = build_stdio_mcp_config(mcp_server, src_path)
        stdio_config["command"] = python_command
        codex_config = Path.home() / ".codex" / "config.toml"
        write_codex_config(codex_config, "fixonce", stdio_config)
        write_log(f"MCP registration ready: Codex config {codex_config}")
        return True
    except Exception as exc:
        write_log(f"MCP registration failed: {type(exc).__name__}: {exc}")
        return False


def _read_runtime_pid_port() -> tuple[int | None, int | None]:
    runtime = read_json(RUNTIME_FILE)
    runtime_pid = runtime.get("pid")
    runtime_port = runtime.get("port")
    try:
        runtime_pid = int(runtime_pid) if runtime_pid is not None else None
    except (TypeError, ValueError):
        runtime_pid = None
    try:
        runtime_port = int(runtime_port) if runtime_port is not None else None
    except (TypeError, ValueError):
        runtime_port = None
    return runtime_pid, runtime_port


def _powershell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def windows_scheduled_task_exists(task_name: str = BOOTSTRAP_TASK_NAME) -> bool:
    """Return True when the current user already has the logon task registered."""
    if sys.platform != "win32":
        return False

    ps_script = (
        f"$task = Get-ScheduledTask -TaskName {_powershell_single_quote(task_name)} "
        "-ErrorAction SilentlyContinue; "
        "if ($null -eq $task) { exit 1 } else { exit 0 }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True

    fallback = subprocess.run(
        ["schtasks", "/query", "/tn", task_name],
        capture_output=True,
        text=True,
    )
    return fallback.returncode == 0


def _register_user_logon_task_powershell(
    task_name: str,
    executable: str,
    argument_string: str,
    working_directory: str,
) -> tuple[bool, str]:
    """Register a per-user logon task for the current interactive account (no admin)."""
    ps_script = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction `
  -Execute {_powershell_single_quote(executable)} `
  -Argument {_powershell_single_quote(argument_string)} `
  -WorkingDirectory {_powershell_single_quote(working_directory)}
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal `
  -UserId $env:USERNAME `
  -LogonType Interactive `
  -RunLevel Limited
Register-ScheduledTask `
  -TaskName {_powershell_single_quote(task_name)} `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Force | Out-Null
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, ""
    detail = (result.stderr or result.stdout or "").strip()
    return False, detail or "unknown PowerShell error"


def _register_user_logon_task_schtasks(
    task_name: str,
    command: list[str],
) -> tuple[bool, str]:
    """Fallback per-user task registration without /IT (avoids elevation quirks)."""
    result = subprocess.run(
        [
            "schtasks",
            "/create",
            "/tn",
            task_name,
            "/tr",
            subprocess.list2cmdline(command),
            "/sc",
            "onlogon",
            "/rl",
            "LIMITED",
            "/f",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, ""
    detail = (result.stderr or result.stdout or "").strip()
    return False, detail or "unknown schtasks error"


def ensure_windows_scheduled_task(log_fn: Callable[[str], None] | None = None) -> bool:
    """
    Create or update the FixOnceServer per-user logon task (idempotent).

    Returns False when autostart could not be configured; callers may continue setup.
    """
    write_log = log_fn or bootstrap_log
    if sys.platform != "win32":
        write_log("Scheduled task setup skipped: not Windows")
        return False

    command = get_packaged_server_command()
    executable = command[0]
    argument_string = subprocess.list2cmdline(command[1:]) if len(command) > 1 else ""
    working_directory = str(get_packaged_install_dir())

    write_log(
        f"Configuring per-user scheduled task {BOOTSTRAP_TASK_NAME}: "
        f"execute={executable!r} args={argument_string!r} cwd={working_directory!r}"
    )

    if windows_scheduled_task_exists():
        write_log(f"Scheduled task {BOOTSTRAP_TASK_NAME} already exists; updating")

    ok, detail = _register_user_logon_task_powershell(
        BOOTSTRAP_TASK_NAME,
        executable,
        argument_string,
        working_directory,
    )
    if ok:
        write_log(f"Scheduled task {BOOTSTRAP_TASK_NAME} ready (Register-ScheduledTask)")
        return True

    write_log(f"Register-ScheduledTask failed: {detail}")

    ok, detail = _register_user_logon_task_schtasks(BOOTSTRAP_TASK_NAME, command)
    if ok:
        write_log(f"Scheduled task {BOOTSTRAP_TASK_NAME} ready (schtasks fallback)")
        return True

    write_log(f"WARNING: Scheduled task setup failed (non-fatal): {detail}")
    return False


def get_windows_startup_folder() -> Path:
    """Per-user Startup folder used for logon autostart shortcuts."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def get_windows_startup_shortcut_path() -> Path:
    return get_windows_startup_folder() / BOOTSTRAP_STARTUP_SHORTCUT_NAME


def ensure_windows_startup_shortcut(log_fn: Callable[[str], None] | None = None) -> bool:
    """Create or update the FixOnceServer Startup folder shortcut (idempotent)."""
    write_log = log_fn or bootstrap_log
    if sys.platform != "win32":
        write_log("Startup shortcut setup skipped: not Windows")
        return False

    command = get_packaged_server_command()
    executable = command[0]
    argument_string = subprocess.list2cmdline(command[1:]) if len(command) > 1 else ""
    working_directory = str(get_packaged_install_dir())
    shortcut_path = get_windows_startup_shortcut_path()

    write_log(
        f"Configuring Startup shortcut {shortcut_path}: "
        f"target={executable!r} args={argument_string!r} cwd={working_directory!r}"
    )

    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    ps_script = f"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut({_powershell_single_quote(str(shortcut_path))})
$shortcut.TargetPath = {_powershell_single_quote(executable)}
$shortcut.Arguments = {_powershell_single_quote(argument_string)}
$shortcut.WorkingDirectory = {_powershell_single_quote(working_directory)}
$shortcut.WindowStyle = 7
$iconPath = Join-Path {_powershell_single_quote(working_directory)} 'FixOnce.exe'
if (Test-Path $iconPath) {{ $shortcut.IconLocation = "$iconPath,0" }}
$shortcut.Save()
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and shortcut_path.exists():
        write_log(f"Startup shortcut ready: {shortcut_path}")
        return True

    detail = (result.stderr or result.stdout or "").strip()
    write_log(f"Startup shortcut setup failed: {detail or 'unknown error'}")
    return False


def configure_windows_autostart(log_fn: Callable[[str], None] | None = None) -> str:
    """
    Configure Windows logon autostart (tiered).

    Returns autostart_method: scheduled_task, startup_shortcut, or none.
    """
    write_log = log_fn or bootstrap_log
    if sys.platform != "win32":
        write_log("Autostart setup skipped: not Windows")
        return AUTOSTART_METHOD_NONE

    if ensure_windows_scheduled_task(log_fn=write_log):
        return AUTOSTART_METHOD_SCHEDULED_TASK

    write_log("Scheduled task unavailable; trying Startup folder shortcut fallback")
    if ensure_windows_startup_shortcut(log_fn=write_log):
        return AUTOSTART_METHOD_STARTUP_SHORTCUT

    write_log("WARNING: No autostart method configured (non-fatal)")
    return AUTOSTART_METHOD_NONE


def ensure_packaged_server_running(log_fn: Callable[[str], None] | None = None) -> int | None:
    """Start or reuse the background server; return port when /api/health is OK."""
    write_log = log_fn or bootstrap_log
    clear_stale_state()

    port = discover_running_port()
    if port is not None and endpoint_responds(port, "/api/health", timeout=1.5):
        write_log(f"Reusing running server on port {port}")
        return port

    write_log("Starting background server via FixOnce.exe --server")
    start_server()
    return wait_for_health(log_fn=write_log)


def run_bootstrap() -> int:
    """
    Windows packaged first-run setup: autostart task, server health, READY state, dashboard.
    Idempotent when run multiple times.
    """
    if sys.platform != "win32":
        bootstrap_log("Bootstrap is only supported on Windows")
        return 1

    if not is_frozen():
        bootstrap_log("Bootstrap requires a packaged FixOnce.exe build")
        return 1

    bootstrap_log("Bootstrap started")
    install_dir = str(get_packaged_install_dir())
    InstallState = None
    persist_snapshot = None

    try:
        InstallState, persist_snapshot = _import_install_state_helpers()
        persist_snapshot(
            InstallState.INSTALLING,
            detail="Bootstrap started",
            install_dir=install_dir,
            metadata={"bootstrap": True},
        )
        bootstrap_log("install_state set to INSTALLING")

        autostart_method = configure_windows_autostart()
        bootstrap_metadata = {"bootstrap": True, "autostart_method": autostart_method}
        if autostart_method == AUTOSTART_METHOD_NONE:
            bootstrap_log("WARNING: Autostart was not configured; continuing bootstrap")
        else:
            bootstrap_log(f"Autostart configured via {autostart_method}")

        if configure_packaged_windows_mcp():
            bootstrap_log("MCP registration completed")
        else:
            bootstrap_log("WARNING: MCP registration did not complete")

        persist_snapshot(
            InstallState.STARTING,
            detail="Ensuring background server",
            install_dir=install_dir,
            metadata=bootstrap_metadata,
        )
        bootstrap_log("install_state set to STARTING")

        persist_snapshot(
            InstallState.WAITING_HEALTH,
            detail="Waiting for /api/health",
            install_dir=install_dir,
            metadata=bootstrap_metadata,
        )
        bootstrap_log("install_state set to WAITING_HEALTH")

        port = ensure_packaged_server_running()
        if port is None:
            persist_snapshot(
                InstallState.FAILED,
                detail="/api/health did not return OK",
                install_dir=install_dir,
            )
            bootstrap_log("Bootstrap failed: health check did not pass")
            return 1

        runtime_pid, runtime_port = _read_runtime_pid_port()
        if runtime_port is None:
            runtime_port = port
        persist_snapshot(
            InstallState.READY,
            detail="Bootstrap completed",
            install_dir=install_dir,
            runtime_port=runtime_port,
            runtime_pid=runtime_pid,
            metadata=bootstrap_metadata,
        )
        bootstrap_log("install_state written as READY")

        bootstrap_log("Opening dashboard")
        open_dashboard(port)
        bootstrap_log("Bootstrap completed successfully")
        return 0
    except Exception as exc:
        bootstrap_log(f"Bootstrap failed: {exc}")
        if persist_snapshot is not None and InstallState is not None:
            try:
                persist_snapshot(
                    InstallState.FAILED,
                    detail=f"Bootstrap failed: {exc}",
                    install_dir=install_dir,
                )
            except Exception:
                pass
        return 1


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
        if is_frozen():
            command = [sys.executable, "--server", "--flask-only", "--quiet", "--strict-port"]
        else:
            python_cmd = get_windows_pythonw(sys.executable)
            command = [python_cmd, str(SERVER_SCRIPT), "--flask-only", "--quiet", "--strict-port"]

        subprocess.Popen(
            command,
            cwd=str(PROJECT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=windows_process_creationflags(detached=True),
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


def open_external_url(url: str):
    """Open an external URL without coupling it to the server process group."""
    if sys.platform == "win32":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return
        except Exception:
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=windows_process_creationflags(detached=True),
            )
            return

    webbrowser.open(url)


def open_dashboard(port: int):
    """Open the dashboard in a native window only."""
    set_dock_icon()
    dashboard_url = get_dashboard_url(port)

    class Api:
        def open_url(self, url):
            open_external_url(url)

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

    if "--bootstrap" in sys.argv:
        raise SystemExit(run_bootstrap())

    if "--menubar" in sys.argv or "-m" in sys.argv:
        run_menubar_app()
        return

    if launch_app():
        return

    show_failure_window(launch_app, lambda: run_repair_action() and launch_app())


if __name__ == "__main__":
    main()
