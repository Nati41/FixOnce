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
                    return True
        except (TypeError, ValueError):
            pass

    # Fall back to process termination
    return terminate_process(pid)


def find_stale_server_port(current_install_path: Path) -> Optional[Tuple[int, int]]:
    """Find a stale FixOnce server from a different install path.

    Returns (port, pid) if a stale server is found, None otherwise.
    """
    current_path_resolved = str(current_install_path.resolve())

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

    if runtime_port and runtime_pid and is_pid_running(runtime_pid):
        payload = _get_ping_payload(runtime_port)
        if payload.get("service") == "fixonce":
            install_path = payload.get("install_path", "")
            if install_path and str(Path(install_path).resolve()) != current_path_resolved:
                _log_lifecycle(f"Found stale server: port={runtime_port}, pid={runtime_pid}, path={install_path}")
                return (runtime_port, runtime_pid)

    # Scan port range for stale servers
    for port in PORT_RANGE:
        payload = _get_ping_payload(port)
        if payload.get("service") != "fixonce":
            continue

        install_path = payload.get("install_path", "")
        if not install_path:
            continue

        if str(Path(install_path).resolve()) != current_path_resolved:
            # This is a stale server from a different install
            # Try to get PID from runtime or from the server's user info
            server_pid = None

            # If this matches runtime, use runtime PID
            if runtime_port == port and runtime_pid and is_pid_running(runtime_pid):
                server_pid = runtime_pid

            # Otherwise we don't have the PID, but we have the port
            # We can't safely kill without PID verification
            if server_pid:
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

        # Try graceful shutdown first
        _request_graceful_shutdown(port)
        time.sleep(0.5)

        # Then terminate process
        if terminate_process(pid):
            count += 1
            # Clean up runtime.json if it pointed to this server
            runtime = read_runtime_state()
            if runtime.get("pid") == pid or runtime.get("port") == port:
                try:
                    RUNTIME_FILE.unlink()
                    _log_lifecycle("Cleaned up stale runtime.json")
                except OSError:
                    pass
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

    # Clean up lock file
    if LOCK_FILE.exists():
        try:
            LOCK_FILE.unlink()
            _log_lifecycle("Cleaned up server.lock")
        except OSError:
            pass

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
