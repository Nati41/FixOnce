"""
FixOnce Error Store
In-memory storage for browser console errors.
"""

from collections import deque
import threading

from config import MAX_ERROR_LOG_SIZE

# ---------------------------------------------------------------------------
# Shared in-memory store
# ---------------------------------------------------------------------------
_error_log: deque = deque(maxlen=MAX_ERROR_LOG_SIZE)
_log_lock = threading.Lock()


def get_error_log() -> deque:
    """Get the error log deque."""
    return _error_log


def get_log_lock() -> threading.Lock:
    """Get the log lock."""
    return _log_lock


def add_error(entry: dict) -> None:
    """Add an error entry to the log."""
    with _log_lock:
        _error_log.append(entry)


def get_errors() -> list:
    """Get a copy of all errors."""
    with _log_lock:
        return list(_error_log)


def clear_errors() -> None:
    """Clear all errors from the log."""
    with _log_lock:
        _error_log.clear()
