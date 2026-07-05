"""
FixOnce Lifecycle Management

Centralized process lifecycle control for FixOnce components.
Handles:
- Terminating Flask server on Quit
- Detecting and terminating stale servers from old installs
- Clean shutdown of all FixOnce-owned processes

IMPORTANT: Only terminates processes that belong to FixOnce.
Never kills unrelated Python processes or user data.
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

# Runtime state file location
USER_DATA_DIR = Path.home() / ".fixonce"
RUNTIME_FILE = USER_DATA_DIR / "runtime.json"
LOCK_FILE = USER_DATA_DIR / "server.lock"

# Port range used by FixOnce
DEFAULT_PORT = 5000
PORT_RANGE = range(DEFAULT_PORT, DEFAULT_PORT + 10)

# Timeout for graceful shutdown
GRACEFUL_SHUTDOWN_TIMEOUT = 3.0

# FixOnce scripts that may be spawned as child/background helpers.
FIXONCE_CHILD_SCRIPT_NAMES = (
    "server.py",
    "file_watcher.py",
    "mcp_memory_server_v2.py",
)


def _log_lifecycle(message: str):
    """Log lifecycle events to file for diagnostics."""
    try:
        log_dir = USER_DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "lifecycle.log"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def read_runtime_state() -> Dict[str, Any]:
    """Read canonical runtime state from ~/.fixonce/runtime.json."""
    if not RUNTIME_FILE.exists():
        return {}
    try:
        state = json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _positive_pid(pid: Any) -> Optional[int]:
    """Return pid as a positive integer, or None when unsafe/invalid."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _cleanup_runtime_file() -> None:
    try:
        RUNTIME_FILE.unlink()
    except OSError:
        pass


def _cleanup_runtime_state() -> None:
    _cleanup_runtime_file()
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass


def is_pid_running(pid: int) -> bool:
    """Check if a process with given PID is running.

    Uses platform-appropriate method to avoid terminating processes on Windows.
    CRITICAL: PIDs <= 0 are special in Unix (0 = process group, -1 = all processes).
    We must reject them to avoid killing unrelated processes.
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


def _get_ping_payload(port: int, timeout: float = 1.0) -> Dict[str, Any]:
    """Get /api/ping response from a FixOnce server."""
    try:
        url = f"http://127.0.0.1:{port}/api/ping"
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return {}
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def _request_graceful_shutdown(port: int, timeout: float = 2.0) -> bool:
    """Request graceful shutdown via /api/shutdown endpoint."""
    try:
        url = f"http://127.0.0.1:{port}/api/shutdown"
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _is_fixonce_payload(payload: Dict[str, Any]) -> bool:
    return payload.get("service") == "fixonce"


def _same_install_path(candidate: Any, current_install_path: Path) -> bool:
    if not candidate:
        return False
    try:
        return str(Path(str(candidate)).resolve()) == str(current_install_path.resolve())
    except Exception:
        return False


def _wait_for_fixonce_server_to_stop(port: int, timeout: float = GRACEFUL_SHUTDOWN_TIMEOUT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_fixonce_payload(_get_ping_payload(port, timeout=0.5)):
            return True
        time.sleep(0.1)
    return not _is_fixonce_payload(_get_ping_payload(port, timeout=0.5))


def terminate_process(pid: int, graceful_timeout: float = GRACEFUL_SHUTDOWN_TIMEOUT) -> bool:
    """Terminate a process by PID with graceful fallback.

    First sends SIGTERM (graceful), waits, then SIGKILL if needed.
    On Windows, uses TerminateProcess.

    Returns True if process was terminated or already dead.
    """
    # CRITICAL: PIDs <= 0 are special in Unix and must NEVER be used with os.kill()
    # PID 0 = current process group, PID -1 = ALL processes user can signal
    raw_pid = pid
    pid = _positive_pid(pid)
    if pid is None:
        _log_lifecycle(f"BLOCKED: Refusing to terminate invalid PID {raw_pid}")
        return True

    if not is_pid_running(pid):
        return True

    _log_lifecycle(f"Terminating PID {pid}")

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        process_terminate = 0x0001
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        handle = kernel32.OpenProcess(process_terminate, False, int(pid))
        if not handle:
            _log_lifecycle(f"Could not open process {pid}")
            return not is_pid_running(pid)

        try:
            kernel32.TerminateProcess(handle, 1)
        finally:
            kernel32.CloseHandle(handle)

        # Wait for termination
        deadline = time.time() + graceful_timeout
        while time.time() < deadline and is_pid_running(pid):
            time.sleep(0.1)

        return not is_pid_running(pid)

    # Unix: SIGTERM first, then SIGKILL
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return True

    # Wait for graceful shutdown
    deadline = time.time() + graceful_timeout
    while time.time() < deadline:
        if not is_pid_running(pid):
            _log_lifecycle(f"PID {pid} terminated gracefully")
            return True
        time.sleep(0.1)

    # Force kill if still running
    try:
        os.kill(pid, signal.SIGKILL)
        _log_lifecycle(f"PID {pid} force-killed")
    except (OSError, ProcessLookupError):
        pass

    return not is_pid_running(pid)


def terminate_server_by_runtime() -> bool:
    """Terminate the Flask server recorded in runtime.json.

    Returns True if server was terminated or no server was running.
    """
    runtime = read_runtime_state()
    raw_pid = runtime.get("pid")
    pid = raw_pid
    port = runtime.get("port")

    if not pid:
        _log_lifecycle("No server PID in runtime.json")
        return True

    pid = _positive_pid(pid)
    if pid is None:
        _log_lifecycle(f"Invalid PID in runtime.json: {raw_pid}")
        _cleanup_runtime_file()
        return True

    if not is_pid_running(pid):
        _log_lifecycle(f"Server PID {pid} already dead")
        # Clean up stale runtime file
        _cleanup_runtime_file()
        return True

    # Try graceful shutdown via API first
    if port:
        try:
            port = int(port)
            _log_lifecycle(f"Requesting graceful shutdown on port {port}")
            if _request_graceful_shutdown(port):
                # Wait for server to stop
                deadline = time.time() + GRACEFUL_SHUTDOWN_TIMEOUT
                while time.time() < deadline and is_pid_running(pid):
                    time.sleep(0.1)
                if not is_pid_running(pid):
                    _log_lifecycle(f"Server shut down gracefully")
                    _cleanup_runtime_file()
                    return True
        except (TypeError, ValueError):
            pass

    # Fall back to process termination
    success = terminate_process(pid)
    if success:
        _cleanup_runtime_file()
    return success


def _default_install_path() -> Path:
    return Path(__file__).resolve().parents[2]


def _iter_fixonce_process_pids(
    current_install_path: Path,
    *,
    direct_children_only: bool = False,
    server_only: bool = False,
) -> List[int]:
    """Return PIDs that are clearly FixOnce-owned processes for this install."""
    if sys.platform == "win32":
        return []

    current_pid = os.getpid()
    install_path = str(current_install_path.resolve()).lower()
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,command="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    pids: List[int] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        if pid <= 0 or pid == current_pid:
            continue
        if direct_children_only and ppid != current_pid:
            continue

        command = parts[2]
        command_lower = command.lower()
        if install_path not in command_lower:
            continue
        if server_only:
            if "server.py" not in command or "--flask-only" not in command:
                continue
        elif not any(script in command for script in FIXONCE_CHILD_SCRIPT_NAMES):
            continue
        pids.append(pid)

    return pids


def _iter_fixonce_child_pids(current_install_path: Path) -> List[int]:
    """Return direct child PIDs that are clearly FixOnce-owned helpers."""
    return _iter_fixonce_process_pids(current_install_path, direct_children_only=True)


def _iter_fixonce_server_pids(current_install_path: Path) -> List[int]:
    """Return Flask server PIDs for this install even if runtime.json is missing."""
    return _iter_fixonce_process_pids(current_install_path, server_only=True)


def terminate_child_processes(current_install_path: Optional[Path] = None) -> int:
    """Terminate FixOnce-owned direct child helper processes."""
    install_path = current_install_path or _default_install_path()
    count = 0
    for pid in _iter_fixonce_child_pids(install_path):
        if terminate_process(pid):
            count += 1
    if count:
        _log_lifecycle(f"Terminated {count} FixOnce child process(es)")
    return count


def terminate_servers_for_install(current_install_path: Path) -> int:
    """Terminate FixOnce servers that /api/ping identifies as this install."""
    count = 0
    terminated_pids = set()
    for port in PORT_RANGE:
        payload = _get_ping_payload(port)
        if not _is_fixonce_payload(payload):
            continue
        if not _same_install_path(payload.get("install_path"), current_install_path):
            continue

        _log_lifecycle(f"Terminating current install server on port {port}")
        stopped = _request_graceful_shutdown(port) and _wait_for_fixonce_server_to_stop(port)
        if not stopped:
            for pid in _iter_fixonce_server_pids(current_install_path):
                if pid in terminated_pids:
                    continue
                if terminate_process(pid):
                    terminated_pids.add(pid)
                    stopped = _wait_for_fixonce_server_to_stop(port, timeout=1.0)
                    if stopped:
                        break
        if stopped:
            count += 1

    if count == 0:
        for pid in _iter_fixonce_server_pids(current_install_path):
            if pid in terminated_pids:
                continue
            if terminate_process(pid):
                terminated_pids.add(pid)
                count += 1

    if count:
        _log_lifecycle(f"Terminated {count} current install server(s)")
    return count


def find_stale_server_port(current_install_path: Path) -> Optional[Tuple[int, Optional[int]]]:
    """Find a stale FixOnce server from a different install path.

    Returns (port, pid) if a stale server is found, None otherwise.
    """
    # Check runtime.json first
    runtime = read_runtime_state()
    runtime_port = runtime.get("port")
    runtime_pid = runtime.get("pid")

    if runtime_port and runtime_pid:
        try:
            runtime_port = int(runtime_port)
            runtime_pid = _positive_pid(runtime_pid)
        except (TypeError, ValueError):
            runtime_port = None
            runtime_pid = None

    if runtime_port:
        payload = _get_ping_payload(runtime_port)
        if _is_fixonce_payload(payload):
            install_path = payload.get("install_path", "")
            if not _same_install_path(install_path, current_install_path):
                _log_lifecycle(f"Found stale server: port={runtime_port}, pid={runtime_pid}, path={install_path}")
                return (runtime_port, runtime_pid)
        elif runtime_pid and not is_pid_running(runtime_pid):
            _log_lifecycle(f"Cleaning stale runtime for dead PID {runtime_pid}")
            _cleanup_runtime_state()

    # Scan port range for stale servers
    for port in PORT_RANGE:
        payload = _get_ping_payload(port)
        if not _is_fixonce_payload(payload):
            continue

        install_path = payload.get("install_path", "")

        if not _same_install_path(install_path, current_install_path):
            # This is a stale server from a different install
            # Try to get PID from runtime or from the server's user info
            server_pid = None

            # If this matches runtime, use runtime PID
            if runtime_port == port and runtime_pid and is_pid_running(runtime_pid):
                server_pid = runtime_pid

            _log_lifecycle(f"Found stale server on port {port}: install_path={install_path}")
            return (port, server_pid)

    return None


def terminate_stale_servers(current_install_path: Path) -> int:
    """Find and terminate any stale FixOnce servers from old installs.

    Only terminates servers where:
    - The server responds to /api/ping with service=fixonce
    - The install_path does NOT match current_install_path
    - We have a valid PID (from runtime.json or the same port)

    Returns number of stale servers terminated.
    """
    count = 0

    while True:
        stale = find_stale_server_port(current_install_path)
        if not stale:
            break

        port, pid = stale
        _log_lifecycle(f"Terminating stale server: port={port}, pid={pid}")

        # Try graceful shutdown first after validating /api/ping identified FixOnce.
        graceful_requested = _request_graceful_shutdown(port)
        stopped = _wait_for_fixonce_server_to_stop(port) if graceful_requested else False

        # Then terminate process, but only count success after the port stops
        # answering as FixOnce. A stale/dead runtime PID alone is not enough.
        if not stopped and pid is not None and terminate_process(pid):
            stopped = _wait_for_fixonce_server_to_stop(port, timeout=1.0)

        if stopped:
            count += 1
            # Clean up runtime.json if it pointed to this server
            runtime = read_runtime_state()
            if runtime.get("pid") == pid or runtime.get("port") == port:
                _cleanup_runtime_state()
                _log_lifecycle("Cleaned up stale runtime state")
        else:
            _log_lifecycle(f"Failed to terminate stale server pid={pid}")
            break  # Avoid infinite loop

    return count


def shutdown_fixonce(current_install_path: Optional[Path] = None) -> bool:
    """Shutdown all FixOnce processes for the current install.

    Used by Quit menu action. Only terminates:
    - Flask server (from runtime.json)
    - Does NOT terminate other users' servers
    - Does NOT delete user memory

    Returns True if shutdown completed successfully.
    """
    _log_lifecycle("Shutdown requested")

    # Terminate server by runtime.json
    success = terminate_server_by_runtime()

    install_path = current_install_path or _default_install_path()

    # Catch current-install servers that are alive but missing/bypassing runtime.
    terminate_servers_for_install(install_path)

    # Terminate direct FixOnce helper children if any are still attached.
    terminate_child_processes(install_path)

    # Clean up runtime/lock files after quit, even if the server already stopped.
    _cleanup_runtime_state()
    _log_lifecycle("Cleaned up runtime state")

    _log_lifecycle(f"Shutdown complete: success={success}")
    return success


def ensure_no_stale_servers(current_install_path: Path) -> None:
    """Ensure no stale servers are running before starting a new one.

    Called during app launch to clean up servers from old installs.
    This prevents reusing a stale Flask with outdated state.
    """
    count = terminate_stale_servers(current_install_path)
    if count > 0:
        _log_lifecycle(f"Terminated {count} stale server(s) before launch")
