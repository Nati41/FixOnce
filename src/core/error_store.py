"""
FixOnce Error Store
Per-project in-memory storage for browser console errors.

Phase 0: Added project_id tagging to prevent cross-project leakage.
"""

from collections import deque
from datetime import datetime
import threading
from typing import Dict, List, Optional

from config import MAX_ERROR_LOG_SIZE

# Per-project error logs (Phase 0: tag-based, not file-based)
_error_log: deque = deque(maxlen=MAX_ERROR_LOG_SIZE)
_log_lock = threading.Lock()


def get_error_log() -> deque:
    """Get the error log deque (legacy compatibility)."""
    return _error_log


def get_log_lock() -> threading.Lock:
    """Get the log lock (legacy compatibility)."""
    return _log_lock


def add_error(entry: dict, project_id: str = None) -> None:
    """
    Add an error entry to the log.

    Args:
        entry: Error data dict
        project_id: Optional project ID for attribution
    """
    # Tag entry with project_id for filtering
    entry['_project_id'] = project_id or "__global__"
    entry['_added_at'] = datetime.now().isoformat()

    with _log_lock:
        _error_log.append(entry)


def get_errors(project_id: str = None) -> list:
    """
    Get errors, optionally filtered by project.

    Args:
        project_id: If provided, only return errors for this project

    Returns:
        List of error entries
    """
    with _log_lock:
        if project_id:
            return [e for e in _error_log if e.get('_project_id') == project_id]
        return list(_error_log)


def get_errors_for_project(project_id: str) -> list:
    """Get errors for a specific project only."""
    return get_errors(project_id=project_id)


def get_all_errors() -> list:
    """Get all errors across all projects."""
    with _log_lock:
        return list(_error_log)


def clear_errors(project_id: str = None) -> int:
    """
    Clear errors, optionally only for a specific project.

    Args:
        project_id: If provided, only clear errors for this project

    Returns:
        Number of errors cleared
    """
    with _log_lock:
        if project_id:
            # Keep errors from other projects
            original_len = len(_error_log)
            kept = [e for e in _error_log if e.get('_project_id') != project_id]
            _error_log.clear()
            _error_log.extend(kept)
            return original_len - len(_error_log)
        else:
            count = len(_error_log)
            _error_log.clear()
            return count


def get_error_count(project_id: str = None) -> int:
    """Get count of errors, optionally for a specific project."""
    with _log_lock:
        if project_id:
            return sum(1 for e in _error_log if e.get('_project_id') == project_id)
        return len(_error_log)


def get_recent_errors(project_id: str = None, limit: int = 10) -> list:
    """
    Get most recent errors.

    Args:
        project_id: Optional project filter
        limit: Max errors to return

    Returns:
        List of recent errors (newest first)
    """
    errors = get_errors(project_id)
    # Sort by timestamp descending
    errors.sort(key=lambda e: e.get('_added_at', ''), reverse=True)
    return errors[:limit]
