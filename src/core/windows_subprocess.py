"""Windows subprocess helpers for customer-facing runtime paths."""

from __future__ import annotations

import subprocess
import sys


def no_window_creationflags() -> int:
    """Return flags that keep console subprocesses hidden on Windows."""
    if sys.platform != "win32":
        return 0

    return (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
