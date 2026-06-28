"""Windows subprocess helpers for customer-facing runtime paths."""

from __future__ import annotations

import subprocess
import sys
import threading
from typing import List, Optional, Tuple


def no_window_creationflags() -> int:
    """Return flags that keep console subprocesses hidden on Windows."""
    if sys.platform != "win32":
        return 0

    return (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )


def _create_no_window_only() -> int:
    """Return only CREATE_NO_WINDOW without CREATE_NEW_PROCESS_GROUP.

    CREATE_NEW_PROCESS_GROUP can cause subprocess.run() timeout to hang
    forever on Windows because grandchild processes inherit pipe handles.
    When the timeout fires, subprocess.run() calls communicate() again
    after kill(), and that blocks waiting for EOF on pipes held by
    grandchildren that weren't killed.
    """
    if sys.platform != "win32":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_git_command_safe(
    args: list[str],
    cwd: str,
    timeout_seconds: float = 5.0,
) -> Tuple[Optional[str], bool]:
    """Run a git command with guaranteed timeout - never hangs.

    This avoids the subprocess.run() timeout bug on Windows where
    communicate() is called twice (once with timeout, once without)
    and the second call can block forever if grandchildren hold pipes.

    Args:
        args: Command arguments (e.g., ['git', 'rev-parse', '--show-toplevel'])
        cwd: Working directory
        timeout_seconds: Maximum time to wait

    Returns:
        (stdout_stripped, success) - stdout is None on failure/timeout
    """
    stdout_result: Optional[str] = None
    success = False
    process: Optional[subprocess.Popen] = None

    def run_in_thread():
        nonlocal stdout_result, success, process
        try:
            # Use only CREATE_NO_WINDOW, not CREATE_NEW_PROCESS_GROUP
            creationflags = _create_no_window_only()

            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creationflags,
            )

            # Wait for completion with our own timeout
            # This is the ONLY communicate() call - no second one after kill
            try:
                stdout, _ = process.communicate(timeout=timeout_seconds)
                if process.returncode == 0 and stdout:
                    stdout_result = stdout.strip()
                    success = True
            except subprocess.TimeoutExpired:
                # Timeout - kill and abandon (don't call communicate again!)
                try:
                    process.kill()
                except Exception:
                    pass
                # Do NOT call communicate() again - that's what causes the hang
                success = False
                stdout_result = None
        except Exception:
            success = False
            stdout_result = None

    # Run in a thread with hard timeout
    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds + 1.0)  # Extra second for cleanup

    if thread.is_alive():
        # Thread is stuck - abandon it (daemon thread will die with process)
        # Try to kill the subprocess if we have a reference
        if process is not None:
            try:
                process.kill()
            except Exception:
                pass
        return (None, False)

    return (stdout_result, success)


def get_running_process_names() -> List[str]:
    """Get list of running process names on Windows using native WinAPI.

    Uses EnumProcesses + OpenProcess + GetModuleBaseName to enumerate
    processes without spawning any subprocess (no console flash).

    Returns lowercase process names (e.g., ['chrome.exe', 'explorer.exe']).
    Returns empty list on non-Windows or on error.
    """
    if sys.platform != "win32":
        return []

    try:
        import ctypes
        from ctypes import wintypes

        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # EnumProcesses
        psapi.EnumProcesses.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        psapi.EnumProcesses.restype = wintypes.BOOL

        # OpenProcess
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE

        # GetModuleBaseNameW
        psapi.GetModuleBaseNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.HMODULE,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        psapi.GetModuleBaseNameW.restype = wintypes.DWORD

        # CloseHandle
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010

        # Get list of PIDs
        max_pids = 4096
        pids = (wintypes.DWORD * max_pids)()
        bytes_returned = wintypes.DWORD()

        if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(bytes_returned)):
            return []

        num_pids = bytes_returned.value // ctypes.sizeof(wintypes.DWORD)

        process_names = []
        for i in range(num_pids):
            pid = pids[i]
            if pid == 0:
                continue

            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if not handle:
                continue

            try:
                name_buffer = ctypes.create_unicode_buffer(260)
                length = psapi.GetModuleBaseNameW(handle, None, name_buffer, 260)
                if length > 0:
                    process_names.append(name_buffer.value.lower())
            finally:
                kernel32.CloseHandle(handle)

        return process_names

    except Exception:
        return []


def is_process_running(process_name: str) -> bool:
    """Check if a process with given name is running on Windows.

    Uses native WinAPI - no subprocess, no console flash.
    Case-insensitive comparison.

    Args:
        process_name: Process name to check (e.g., 'claude.exe', 'Cursor.exe')

    Returns:
        True if process is running, False otherwise.
    """
    if sys.platform != "win32":
        return False

    running = get_running_process_names()
    return process_name.lower() in running
