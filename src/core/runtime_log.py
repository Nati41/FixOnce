"""
Runtime diagnostics that are safe for packaged Windows builds.

Do not write request-time diagnostics to stdout: Windows PowerShell can run
under a legacy code page and fail on Unicode from browser/API payloads.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import traceback


LOG_FILE = Path.home() / ".fixonce" / "logs" / "server.log"


def log_runtime_event(message: str, exc=None) -> None:
    """Append UTF-8 diagnostics to the per-user server log."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
            if exc is not None:
                handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            handle.flush()
    except Exception:
        pass
