"""Windows subprocess helpers for customer-facing runtime paths."""

from __future__ import annotations

import subprocess
import sys
import threading
from typing import Optional, Tuple


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
