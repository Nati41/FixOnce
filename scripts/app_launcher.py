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
import runpy
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# ============================================================
# Path detection: bundle mode vs dev mode
# ============================================================

def _detect_run_mode() -> tuple[str, Path, Path]:
    """
    Detect whether running from:
    - 'frozen': PyInstaller bundle (Windows exe or macOS app)
    - 'macos_app': macOS app bundle in /Applications
    - 'dev': Development/repo mode

    Returns (mode, project_dir, src_dir)
    """
    if getattr(sys, "frozen", False):
        # PyInstaller frozen mode
        if sys.platform == "darwin":
            # macOS: executable is in FixOnce.app/Contents/MacOS/
            exe_path = Path(sys.executable).resolve()
            app_bundle = exe_path.parent.parent.parent  # .app directory
            resources = app_bundle / "Contents" / "Resources"
            return "frozen", resources, resources / "src"
        else:
            # Windows: executable is in dist/FixOnce/
            exe_dir = Path(sys.executable).resolve().parent
            return "frozen", exe_dir, exe_dir / "src"

    # Script mode - check if inside a macOS app bundle
    script_path = Path(__file__).resolve()

    # Check if we're inside /Applications/FixOnce.app
    if sys.platform == "darwin":
        path_str = str(script_path)
        if "/Applications/FixOnce.app/" in path_str:
            # Running from installed app
            app_match = path_str.split("/Applications/FixOnce.app/")[0]
            app_bundle = Path(app_match) / "Applications" / "FixOnce.app"
            resources = app_bundle / "Contents" / "Resources"
            return "macos_app", resources, resources / "src"

    # Dev/repo mode: script is in scripts/, project is parent
    script_dir = script_path.parent
    project_dir = script_dir.parent
    return "dev", project_dir, project_dir / "src"


# Initialize paths based on run mode
_RUN_MODE, PROJECT_DIR, SRC_DIR = _detect_run_mode()
# Scripts are always in a 'scripts' subdirectory, even in frozen mode
SCRIPT_DIR = PROJECT_DIR / "scripts"
SERVER_SCRIPT = SRC_DIR / "server.py"

# Add src to path for imports
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.windows_subprocess import no_window_creationflags

USER_DATA_DIR = Path.home() / ".fixonce"
RUNTIME_FILE = USER_DATA_DIR / "runtime.json"
CONFIG_FILE = USER_DATA_DIR / "config.json"
LOCK_FILE = USER_DATA_DIR / "server.lock"
LOG_DIR = USER_DATA_DIR / "logs"
LAUNCHER_LOG = LOG_DIR / "app_launcher.log"
BOOTSTRAP_LOG = LOG_DIR / "bootstrap.log"
MCP_STARTUP_LOG = LOG_DIR / "mcp_startup.log"
BOOTSTRAP_TASK_NAME = "FixOnceServer"
BOOTSTRAP_STARTUP_SHORTCUT_NAME = "FixOnceServer.lnk"
AUTOSTART_METHOD_SCHEDULED_TASK = "scheduled_task"
AUTOSTART_METHOD_STARTUP_SHORTCUT = "startup_shortcut"
AUTOSTART_METHOD_NONE = "none"
DEFAULT_PORT = 5000
PORT_RANGE = range(DEFAULT_PORT, DEFAULT_PORT + 10)
START_TIMEOUT_SECONDS = 12.0
BOOTSTRAP_HEALTH_TIMEOUT_SECONDS = 45.0
AUTOSTART_SUBPROCESS_TIMEOUT_SECONDS = 30.0
SPLASH_STEPS = {
    "starting": "Starting FixOnce...",
    "checking": "Checking server...",
    "connecting": "Starting server...",
    "opening": "Opening dashboard...",
}
DEFENDER_BLOCKED_DETAIL = (
    "Windows Defender appears to have blocked FixOnce.exe. "
    "Open Windows Security > Virus & threat protection > Protection history, "
    "then allow or restore FixOnce if you trust this installer."
)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_bundle_mode() -> bool:
    """Check if running from installed bundle (not dev/repo mode)."""
    return _RUN_MODE in ("frozen", "macos_app")


def get_macos_app_path() -> Path:
    """Get the path to the installed macOS app bundle."""
    return Path("/Applications/FixOnce.app")


def windows_process_creationflags(detached: bool = True) -> int:
    """Return Windows flags that isolate child processes from console control events."""
    if sys.platform != "win32":
        return 0

    flags = no_window_creationflags()
    if detached:
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
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


def _run_windows_powershell_json(script: str, timeout: float = 4.0) -> tuple[Any, str]:
    if sys.platform != "win32":
        return None, "not Windows"

    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=no_window_creationflags(),
        )
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    output = (result.stdout or "").strip()
    if result.returncode != 0:
        return None, (result.stderr or output or f"PowerShell exited {result.returncode}").strip()
    if not output:
        return None, ""
    try:
        return json.loads(output), ""
    except json.JSONDecodeError as exc:
        return None, f"Invalid PowerShell JSON: {exc}"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _stringify_resources(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _detect_windows_server_processes() -> list[dict[str, Any]]:
    if sys.platform != "win32":
        return []

    script = """
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -ieq 'FixOnce.exe' -and $_.CommandLine -like '*--server*' } |
  Select-Object ProcessId, Name, CommandLine |
  ConvertTo-Json -Compress
"""
    payload, error = _run_windows_powershell_json(script)
    if error:
        bootstrap_log(f"Defender diagnostic process probe failed: {error}")
        return []
    return [item for item in _as_list(payload) if isinstance(item, dict)]


def _get_windows_defender_diagnostics(executable: Path | None = None) -> dict[str, Any]:
    """
    Best-effort Defender signal for startup failures.

    This is diagnostic only: it does not alter Defender policy, restore files,
    or add exclusions.
    """
    if sys.platform != "win32":
        return {"available": False, "reason": "not_windows"}

    exe_path = executable or Path(sys.executable)
    install_dir = exe_path.resolve().parent if exe_path else get_packaged_install_dir()
    exe_exists = exe_path.exists()
    server_processes = _detect_windows_server_processes()

    status_script = """
$ErrorActionPreference = 'SilentlyContinue'
Get-MpComputerStatus |
  Select-Object AMRunningMode, AMServiceEnabled, AntivirusEnabled, RealTimeProtectionEnabled, AntivirusSignatureVersion |
  ConvertTo-Json -Compress
"""
    status_payload, status_error = _run_windows_powershell_json(status_script)

    detections_script = """
$ErrorActionPreference = 'SilentlyContinue'
$threats = @(Get-MpThreat | Select-Object ThreatName, ThreatID, SeverityID, DidThreatExecute, IsActive, Resources)
$detections = @(Get-MpThreatDetection | Select-Object ThreatName, ThreatID, ActionSuccess, InitialDetectionTime, LastThreatStatusChangeTime, Resources)
[PSCustomObject]@{
  Threats = $threats
  Detections = $detections
} | ConvertTo-Json -Compress -Depth 5
"""
    detections_payload, detections_error = _run_windows_powershell_json(detections_script)

    needle_paths = {
        str(exe_path).lower(),
        str(install_dir).lower(),
        "fixonce.exe",
        "fixonce",
    }

    relevant: list[dict[str, Any]] = []
    for source_name, items in (
        ("Get-MpThreat", _as_list((detections_payload or {}).get("Threats") if isinstance(detections_payload, dict) else None)),
        ("Get-MpThreatDetection", _as_list((detections_payload or {}).get("Detections") if isinstance(detections_payload, dict) else None)),
    ):
        for item in items:
            if not isinstance(item, dict):
                continue
            haystack = " ".join(
                [
                    str(item.get("ThreatName") or ""),
                    _stringify_resources(item.get("Resources")),
                ]
            ).lower()
            if any(needle in haystack for needle in needle_paths):
                relevant.append({"source": source_name, **item})

    blocked = bool(relevant) and (not exe_exists or not server_processes)
    if blocked:
        disposition = "quarantined_or_deleted" if not exe_exists else "terminated_or_blocked"
    elif relevant:
        disposition = "defender_detection_present"
    else:
        disposition = "not_detected"

    return {
        "available": True,
        "executable": str(exe_path),
        "install_dir": str(install_dir),
        "executable_exists": exe_exists,
        "server_process_count": len(server_processes),
        "server_processes": server_processes[:5],
        "defender_status": status_payload if isinstance(status_payload, dict) else {},
        "defender_status_error": status_error,
        "defender_detection_error": detections_error,
        "relevant_detections": relevant[:10],
        "blocked_likely": blocked,
        "disposition": disposition,
    }


def log_windows_defender_diagnostics(reason: str, executable: Path | None = None) -> dict[str, Any]:
    diagnostics = _get_windows_defender_diagnostics(executable)
    try:
        bootstrap_log(f"Defender diagnostics ({reason}): {json.dumps(diagnostics, default=str)}")
    except Exception:
        bootstrap_log(f"Defender diagnostics ({reason}): unavailable")
    return diagnostics


def mcp_startup_log(message: str):
    """Append packaged MCP startup diagnostics without touching stdout."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with MCP_STARTUP_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
        print(f"[FixOnce MCP] {message}", file=sys.stderr, flush=True)
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
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
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


def _positive_pid(pid: Any) -> int | None:
    """Return pid as a positive integer, or None when unsafe/invalid."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def is_pid_running(pid: int) -> bool:
    """Check if a process with given PID is running.

    Windows does not support POSIX signal 0 semantics. Calling os.kill(pid, 0)
    can terminate the process, so use WinAPI for a non-destructive liveness
    check there.

    CRITICAL: PIDs <= 0 are special in Unix (0 = process group, -1 = all processes).
    We must reject them to avoid dangerous signal operations.
    """
    pid = _positive_pid(pid)
    if pid is None:
        return False

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False

        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, SystemError):
        return False


def clear_stale_state():
    """Remove stale runtime and lock files that point to dead processes."""
    runtime = read_json(RUNTIME_FILE)
    runtime_pid = _positive_pid(runtime.get("pid"))
    if runtime.get("pid") is not None and runtime_pid is None:
        try:
            RUNTIME_FILE.unlink()
            log_event("Removed invalid runtime.json")
        except OSError:
            pass
    elif runtime_pid and not is_pid_running(runtime_pid):
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
    """Find a healthy FixOnce server, preferring saved canonical ports.

    Before checking saved ports, validates that the runtime PID is actually
    running. If stale, clears runtime.json and server.lock to avoid trusting
    dead state.
    """
    # Validate runtime PID before trusting saved ports
    runtime = read_json(RUNTIME_FILE)
    raw_runtime_pid = runtime.get("pid")
    runtime_pid = _positive_pid(raw_runtime_pid)
    if raw_runtime_pid is not None and runtime_pid is None:
        log_event(f"Runtime PID {raw_runtime_pid} is invalid, clearing stale state")
        clear_stale_state()
    elif runtime_pid and not is_pid_running(runtime_pid):
        log_event(f"Runtime PID {runtime_pid} is dead, clearing stale state")
        clear_stale_state()

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


def configure_packaged_windows_mcp(log_fn: Callable[[str], None] | None = None) -> bool:
    """Register per-user MCP config for packaged Windows installs."""
    write_log = log_fn or bootstrap_log
    if sys.platform != "win32":
        write_log("MCP registration skipped: not Windows")
        return False

    home_dir = Path.home()
    fixonce_exe = Path(sys.executable)
    user_name = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    user_profile = os.environ.get("USERPROFILE") or str(home_dir)
    codex_config = home_dir / ".codex" / "config.toml"
    write_log("MCP registration started")
    write_log(f"MCP registration user/profile: user={user_name}; home={home_dir}; USERPROFILE={user_profile}")
    write_log(f"MCP registration Codex config path: {codex_config}")
    write_log(f"MCP registration installed exe path: {fixonce_exe}")

    try:
        from core.agent_mcp_registration import register_windows_mcp_clients

        config_paths = register_windows_mcp_clients(home_dir, fixonce_exe)
        write_log(f"MCP registration result: success; paths={', '.join(str(path) for path in config_paths)}")
        return True
    except Exception as exc:
        write_log(f"MCP registration result: failed; error={type(exc).__name__}: {exc}")
        return False


def _read_runtime_pid_port() -> tuple[int | None, int | None]:
    runtime = read_json(RUNTIME_FILE)
    runtime_pid = _positive_pid(runtime.get("pid"))
    runtime_port = runtime.get("port")
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
        creationflags=no_window_creationflags(),
    )
    if result.returncode == 0:
        return True

    fallback = subprocess.run(
        ["schtasks", "/query", "/tn", task_name],
        capture_output=True,
        text=True,
        creationflags=no_window_creationflags(),
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
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=AUTOSTART_SUBPROCESS_TIMEOUT_SECONDS,
            creationflags=no_window_creationflags(),
        )
    except subprocess.TimeoutExpired:
        return False, f"PowerShell timed out after {AUTOSTART_SUBPROCESS_TIMEOUT_SECONDS}s"
    if result.returncode == 0:
        return True, ""
    detail = (result.stderr or result.stdout or "").strip()
    return False, detail or "unknown PowerShell error"


def _register_user_logon_task_schtasks(
    task_name: str,
    command: list[str],
) -> tuple[bool, str]:
    """Fallback per-user task registration without /IT (avoids elevation quirks)."""
    try:
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
            timeout=AUTOSTART_SUBPROCESS_TIMEOUT_SECONDS,
            creationflags=no_window_creationflags(),
        )
    except subprocess.TimeoutExpired:
        return False, f"schtasks timed out after {AUTOSTART_SUBPROCESS_TIMEOUT_SECONDS}s"
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
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=AUTOSTART_SUBPROCESS_TIMEOUT_SECONDS,
            creationflags=no_window_creationflags(),
        )
    except subprocess.TimeoutExpired:
        write_log(f"Startup shortcut setup timed out after {AUTOSTART_SUBPROCESS_TIMEOUT_SECONDS}s")
        return False
    if result.returncode == 0 and shortcut_path.exists():
        write_log(f"Startup shortcut ready: {shortcut_path}")
        return True

    detail = (result.stderr or result.stdout or "").strip()
    write_log(f"Startup shortcut setup failed: {detail or 'unknown error'}")
    return False


def remove_windows_startup_shortcut(log_fn: Callable[[str], None] | None = None) -> bool:
    """Remove legacy Startup folder autostart shortcut if present."""
    write_log = log_fn or bootstrap_log
    if sys.platform != "win32":
        write_log("Startup shortcut cleanup skipped: not Windows")
        return False

    shortcut_path = get_windows_startup_shortcut_path()
    if not shortcut_path.exists():
        write_log(f"Startup shortcut not present: {shortcut_path}")
        return False

    try:
        shortcut_path.unlink()
        write_log(f"Removed Startup shortcut: {shortcut_path}")
        return True
    except OSError as exc:
        write_log(f"WARNING: Could not remove Startup shortcut {shortcut_path}: {exc}")
        return False


def configure_windows_autostart(log_fn: Callable[[str], None] | None = None) -> str:
    """
    Keep Windows logon autostart disabled.

    Returns autostart_method: none.
    """
    write_log = log_fn or bootstrap_log
    if sys.platform != "win32":
        write_log("Autostart setup skipped: not Windows")
        return AUTOSTART_METHOD_NONE

    remove_windows_startup_shortcut(log_fn=write_log)
    write_log("Windows login autostart disabled")
    return AUTOSTART_METHOD_NONE


def ensure_packaged_server_running(log_fn: Callable[[str], None] | None = None) -> int | None:
    """Start or reuse the background server; return port when /api/health is OK."""
    write_log = log_fn or bootstrap_log
    clear_stale_state()

    runtime_pid, runtime_port = _read_runtime_pid_port()
    if runtime_pid and runtime_port and is_pid_running(runtime_pid):
        write_log(
            f"Runtime PID {runtime_pid} is alive on port {runtime_port}; "
            "waiting for health instead of starting another server"
        )
        return wait_for_health(log_fn=write_log)

    port = discover_running_port()
    if port is not None and endpoint_responds(port, "/api/health", timeout=1.5):
        write_log(f"Reusing running server on port {port}")
        return port
    if port is not None:
        write_log(f"Server discovered on port {port}; waiting for health")
        return wait_for_health(log_fn=write_log)

    write_log("Starting background server via FixOnce.exe --server")
    try:
        start_server()
    except Exception as exc:
        write_log(f"Background server start failed: {type(exc).__name__}: {exc}")
        log_windows_defender_diagnostics("start_server_failed")
        raise

    port = wait_for_health(log_fn=write_log)
    if port is None:
        log_windows_defender_diagnostics("health_timeout")
    return port


def launch_dashboard_detached(log_fn: Callable[[str], None] | None = None) -> bool:
    """Start the normal app launcher in a separate process and return immediately."""
    write_log = log_fn or bootstrap_log
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                [sys.executable],
                cwd=str(get_packaged_install_dir() if is_frozen() else PROJECT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=windows_process_creationflags(detached=True),
            )
        else:
            subprocess.Popen(
                [sys.executable, str(SCRIPT_DIR / "app_launcher.py")],
                cwd=str(PROJECT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        write_log("Dashboard launcher started detached")
        return True
    except Exception as exc:
        write_log(f"Detached dashboard launcher failed: {type(exc).__name__}: {exc}")
        return False


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
            defender_diagnostics = log_windows_defender_diagnostics("bootstrap_health_failed")
            defender_blocked = bool(defender_diagnostics.get("blocked_likely"))
            detail = DEFENDER_BLOCKED_DETAIL if defender_blocked else "/api/health did not return OK"
            metadata = {**bootstrap_metadata, "defender_diagnostics": defender_diagnostics}
            persist_snapshot(
                InstallState.FAILED,
                detail=detail,
                install_dir=install_dir,
                metadata=metadata,
            )
            if defender_blocked:
                bootstrap_log(f"Bootstrap failed: Defender likely blocked startup ({defender_diagnostics.get('disposition')})")
            else:
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
        if not launch_dashboard_detached():
            bootstrap_log("Detached dashboard launch failed; dashboard will open on next app launch")
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


LOADING_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>FixOnce</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            background: #f5f5f5;
            color: #333;
        }
        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid #e0e0e0;
            border-top-color: #3b82f6;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 16px;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .message {
            font-size: 14px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="spinner"></div>
    <div class="message">Connecting to FixOnce...</div>
</body>
</html>"""


def _navigate_when_ready(window, port: int, dashboard_url: str):
    """Wait for server health then navigate webview. Runs in background thread."""
    log_event(f"_navigate_when_ready called: port={port} url={dashboard_url}")
    for attempt in range(30):
        if endpoint_responds(port, "/api/health", timeout=2.0):
            log_event(f"_navigate_when_ready: health OK at attempt {attempt}, calling load_url")
            window.load_url(dashboard_url)
            log_event(f"_navigate_when_ready: load_url called successfully")
            return
        time.sleep(0.5)
    log_event(f"_navigate_when_ready: server not reachable after 30 attempts, port {port}")


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

    # On Windows, redirect stderr to a log file to capture crash diagnostics
    server_stderr_log = LOG_DIR / "server_stderr.log"
    stderr_handle = None
    if sys.platform == "win32":
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            stderr_handle = open(server_stderr_log, "a", encoding="utf-8")
            stderr_handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Server starting\n")
            stderr_handle.flush()
        except Exception as e:
            log_event(f"Could not open server stderr log: {e}")
            stderr_handle = None

    if sys.platform == "win32":
        if is_frozen():
            command = [sys.executable, "--server", "--flask-only", "--quiet", "--strict-port"]
        else:
            python_cmd = get_windows_pythonw(sys.executable)
            command = [python_cmd, str(SERVER_SCRIPT), "--flask-only", "--quiet", "--strict-port"]

        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle if stderr_handle else subprocess.DEVNULL,
            creationflags=windows_process_creationflags(detached=True),
        )
        log_event(f"Requested background server start: pid={process.pid} command={subprocess.list2cmdline(command)}")
    else:
        process = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT), "--flask-only", "--quiet"],
            cwd=str(PROJECT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        log_event(f"Requested background server start: pid={process.pid}")


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
    log_event(f"open_dashboard: port={port} platform={sys.platform} deferred={sys.platform == 'win32'}")
    set_dock_icon()
    dashboard_url = get_dashboard_url(port)

    class Api:
        def open_url(self, url):
            open_external_url(url)

    # On Windows, create webview with loading HTML first, then navigate via
    # Python after confirming server health. This avoids ERR_CONNECTION_REFUSED
    # being cached by EdgeChromium if the initial URL load fails.
    use_deferred_navigation = sys.platform == "win32"

    try:
        import webview

        if use_deferred_navigation:
            log_event("open_dashboard: DEFERRED path - creating with LOADING_HTML")
            window = webview.create_window(
                "FixOnce",
                html=LOADING_HTML,
                width=480,
                height=800,
                resizable=True,
                min_size=(400, 650),
                js_api=Api(),
            )
            log_event("open_dashboard: calling webview.start with _navigate_when_ready callback")
            webview.start(func=_navigate_when_ready, args=(window, port, dashboard_url))
        else:
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


class StartupSplash:
    """Lightweight progress window shown while the app waits for the server."""

    def __init__(self):
        self.root = None
        self.message = None
        try:
            import tkinter as tk
            from tkinter import ttk

            root = tk.Tk()
            root.title("FixOnce")
            root.resizable(False, False)
            root.attributes("-topmost", True)

            width = 340
            height = 150
            x = max(0, int((root.winfo_screenwidth() - width) / 2))
            y = max(0, int((root.winfo_screenheight() - height) / 2))
            root.geometry(f"{width}x{height}+{x}+{y}")

            frame = ttk.Frame(root, padding=22)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text="FixOnce", font=("Segoe UI", 16, "bold")).pack(anchor="w")
            self.message = ttk.Label(frame, text=SPLASH_STEPS["starting"], font=("Segoe UI", 10))
            self.message.pack(anchor="w", pady=(10, 14))
            progress = ttk.Progressbar(frame, mode="indeterminate")
            progress.pack(fill="x")
            progress.start(12)

            self.root = root
            self.show_step("starting")
        except Exception as exc:
            log_event(f"Startup splash unavailable: {exc}")

    def show_step(self, step: str):
        if self.root is None or self.message is None:
            return
        try:
            self.message.configure(text=SPLASH_STEPS.get(step, step))
            self.root.update_idletasks()
            self.root.update()
        except Exception as exc:
            log_event(f"Startup splash update failed: {exc}")
            self.close()

    def close(self):
        if self.root is None:
            return
        try:
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.root = None
            self.message = None


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
    defender_diagnostics = log_windows_defender_diagnostics("launch_failure_window")
    if defender_diagnostics.get("blocked_likely"):
        disposition = defender_diagnostics.get("disposition") or "blocked"
        message = (
            "FixOnce couldn't open because Windows Defender appears to have blocked FixOnce.exe.\n\n"
            "Open Windows Security > Virus & threat protection > Protection history, then allow or restore FixOnce if you trust this installer.\n\n"
            f"Diagnostic result: {disposition}."
        )
    else:
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


def ensure_server_ready(progress: Callable[[str], None] | None = None) -> int:
    """Reuse an existing server or start one quietly in the background."""
    if progress:
        progress("checking")

    # Terminate any stale servers from old installs before proceeding
    try:
        sys.path.insert(0, str(SRC_DIR))
        from core.lifecycle import ensure_no_stale_servers
        ensure_no_stale_servers(PROJECT_DIR)
    except Exception as exc:
        log_event(f"Stale server check failed (non-fatal): {exc}")

    port = discover_running_port()
    if port is not None and endpoint_responds(port, "/api/health", timeout=1.5):
        log_event("Reused existing server")
        return port

    if progress:
        progress("connecting")
    start_server()
    port = wait_for_server()
    if port is None:
        raise RuntimeError("FixOnce background service did not become ready.")

    log_event("Background server became ready")
    return port


def launch_app() -> bool:
    """Launch the user experience end-to-end."""
    splash = StartupSplash()
    try:
        port = ensure_server_ready(splash.show_step)
    except Exception as exc:
        log_event(f"Initial launch failed: {exc}")
        splash.close()
        return False

    splash.show_step("opening")
    splash.close()
    open_dashboard(port)
    return True


def run_menubar_app(explicit_request: bool = False):
    """
    macOS menu bar mode.

    Args:
        explicit_request: True if user explicitly requested tray mode via --tray flag.
                         If True and rumps is unavailable, show error instead of fallback.
    """
    try:
        import rumps
    except ImportError:
        if explicit_request:
            log_event("rumps not available, --tray explicitly requested, showing error")
            print("Error: Tray mode requires 'rumps' package.")
            print("Install with: pip install rumps")
            print("")
            print("Alternatively, run without --tray to use dashboard mode.")
            return
        else:
            log_event("rumps not available, falling back to dashboard")
            if not launch_app():
                show_failure_window(launch_app, lambda: run_repair_action() and launch_app())
            return

    sys.path.insert(0, str(SCRIPT_DIR))
    from menubar_app import FixOnceMenuBar

    app = FixOnceMenuBar()
    app.run()


def run_tray_app(explicit_request: bool = False):
    """
    Windows system tray mode.

    Args:
        explicit_request: True if user explicitly requested tray mode via --tray flag.
                         If True and dependencies unavailable, show error instead of fallback.
    """
    try:
        import pystray
        from PIL import Image
    except ImportError:
        if explicit_request:
            log_event("pystray/Pillow not available, --tray explicitly requested, showing error")
            print("Error: Tray mode requires 'pystray' and 'Pillow' packages.")
            print("Install with: pip install pystray pillow")
            print("")
            print("Alternatively, run without --tray to use dashboard mode.")
            return
        else:
            log_event("pystray/Pillow not available, falling back to dashboard")
            if not launch_app():
                show_failure_window(launch_app, lambda: run_repair_action() and launch_app())
            return

    sys.path.insert(0, str(SCRIPT_DIR))
    from tray_app_windows import FixOnceTray

    app = FixOnceTray()
    app.run()


def get_launch_mode() -> str:
    """Get configured launch mode from user config."""
    config_file = USER_DATA_DIR / "config.json"
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        mode = config.get("launch_mode", "tray")
        if mode in ("dashboard", "tray", "auto"):
            return mode
    except Exception:
        pass
    return "tray"


def can_run_tray() -> bool:
    """Check if tray mode is available on this platform."""
    if sys.platform == "darwin":
        try:
            import rumps
            return True
        except ImportError:
            return False
    elif sys.platform == "win32":
        try:
            import pystray
            from PIL import Image
            return True
        except ImportError:
            return False
    return False


def run_tray_mode(explicit_request: bool = False):
    """
    Run in tray-first mode.

    - macOS: uses rumps menu bar app
    - Windows: uses pystray system tray app
    - Fallback: opens dashboard if tray not available (unless explicit_request)

    Args:
        explicit_request: True if user explicitly requested tray mode via --tray flag.
    """
    log_event(f"Tray mode requested on platform {sys.platform}")

    if sys.platform == "darwin":
        run_menubar_app(explicit_request=explicit_request)
    elif sys.platform == "win32":
        run_tray_app(explicit_request=explicit_request)
    else:
        if explicit_request:
            log_event("Tray mode not supported on this platform")
            print(f"Error: Tray mode is not supported on {sys.platform}.")
            print("Run without --tray to use dashboard mode.")
            return
        else:
            log_event("Tray mode not supported on this platform, falling back to dashboard")
            if not launch_app():
                show_failure_window(launch_app, lambda: run_repair_action() and launch_app())


def run_server_mode(argv: list[str]):
    """Run the bundled Flask server without opening the app window."""
    if is_frozen():
        from server import main as server_main
    else:
        sys.path.insert(0, str(PROJECT_DIR / "src"))
        from server import main as server_main

    server_main(argv)


def run_mcp_mode():
    """Run the bundled FixOnce MCP stdio server."""
    started_at = time.monotonic()
    mcp_startup_log(
        f"--mcp startup started; frozen={is_frozen()}; executable={sys.executable}; "
        f"argv={sys.argv}; cwd={os.getcwd()}; userprofile={os.environ.get('USERPROFILE', '')}; home={Path.home()}"
    )
    if not is_frozen():
        sys.path.insert(0, str(PROJECT_DIR / "src"))

    try:
        mcp_startup_log("--mcp entering mcp_server.mcp_memory_server_v2")
        runpy.run_module("mcp_server.mcp_memory_server_v2", run_name="__main__")
        elapsed = time.monotonic() - started_at
        mcp_startup_log(f"--mcp run_module returned after {elapsed:.3f}s")
    except BaseException as exc:
        elapsed = time.monotonic() - started_at
        mcp_startup_log(f"--mcp startup failed after {elapsed:.3f}s: {type(exc).__name__}: {exc}")
        raise


def main():
    if "--mcp" in sys.argv:
        run_mcp_mode()
        return

    if "--server" in sys.argv:
        server_args = [arg for arg in sys.argv[1:] if arg != "--server"]
        run_server_mode(server_args)
        return

    if "--bootstrap" in sys.argv:
        raise SystemExit(run_bootstrap())

    # Explicit tray mode flags (backward compatible)
    if "--menubar" in sys.argv or "-m" in sys.argv or "--tray" in sys.argv:
        run_tray_mode(explicit_request=True)
        return

    # Explicit dashboard mode flag
    if "--dashboard" in sys.argv:
        if launch_app():
            return
        show_failure_window(launch_app, lambda: run_repair_action() and launch_app())
        return

    # Check launch_mode configuration
    launch_mode = get_launch_mode()
    log_event(f"Launch mode from config: {launch_mode}")

    if launch_mode == "tray":
        # Tray-first mode (new behavior, opt-in)
        run_tray_mode()
        return

    if launch_mode == "auto":
        # Auto mode: try tray if available, otherwise dashboard
        if can_run_tray():
            run_tray_mode()
            return
        # Fall through to dashboard mode

    # Default: dashboard mode (current behavior preserved)
    if launch_app():
        return

    show_failure_window(launch_app, lambda: run_repair_action() and launch_app())


if __name__ == "__main__":
    main()
