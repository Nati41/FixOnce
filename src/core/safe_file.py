"""
Safe File Operations for FixOnce.

Provides atomic writes and file locking to prevent:
1. File corruption on crash (atomic write)
2. Race conditions with concurrent access (file locking)

Usage:
    from core.safe_file import atomic_json_write, atomic_json_read, FileLock

    # Atomic write (crash-safe)
    atomic_json_write(path, data)

    # With explicit locking (for concurrent access)
    with FileLock(path):
        data = atomic_json_read(path)
        data['key'] = 'value'
        atomic_json_write(path, data)
"""

import os
import sys
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from contextlib import contextmanager


# Platform-specific locking
if sys.platform == 'win32':
    import msvcrt
    LOCK_AVAILABLE = True
else:
    try:
        import fcntl
        LOCK_AVAILABLE = True
    except ImportError:
        LOCK_AVAILABLE = False


class FileLockError(Exception):
    """Raised when file lock cannot be acquired."""
    pass


class FileLock:
    """
    Cross-platform file locking.

    Usage:
        with FileLock('/path/to/file.json'):
            # exclusive access to file
            data = json.load(...)
            json.dump(...)

    Or manually:
        lock = FileLock(path)
        lock.acquire()
        try:
            ...
        finally:
            lock.release()
    """

    def __init__(self, path: str, timeout: float = 10.0):
        """
        Args:
            path: Path to the file to lock
            timeout: Maximum seconds to wait for lock (default 10)
        """
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + '.lock')
        self.timeout = timeout
        self._lock_file = None

    def acquire(self) -> bool:
        """
        Acquire the lock. Blocks until lock is available or timeout.

        Returns:
            True if lock acquired, False if timeout
        """
        start_time = time.time()

        # Create lock file if it doesn't exist
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                # Try to create lock file exclusively
                self._lock_file = open(self.lock_path, 'w')

                if sys.platform == 'win32':
                    # Windows locking
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    # Unix locking
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Write PID to lock file for debugging
                self._lock_file.write(str(os.getpid()))
                self._lock_file.flush()
                return True

            except (IOError, OSError):
                # Lock is held by another process
                if self._lock_file:
                    self._lock_file.close()
                    self._lock_file = None

                if time.time() - start_time > self.timeout:
                    return False

                # Wait a bit before retrying
                time.sleep(0.05)

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                if sys.platform == 'win32':
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass

            try:
                self._lock_file.close()
            except Exception:
                pass

            try:
                self.lock_path.unlink()
            except Exception:
                pass

            self._lock_file = None

    def __enter__(self):
        if not self.acquire():
            raise FileLockError(f"Could not acquire lock for {self.path} within {self.timeout}s")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def atomic_json_write(path: str, data: Any, indent: int = 2, use_lock: bool = True) -> bool:
    """
    Write JSON data atomically (crash-safe).

    Process:
    1. Write to temporary file in same directory
    2. Flush and sync to disk
    3. Atomically replace original file

    This ensures the file is never in a half-written state.

    Args:
        path: Target file path
        data: JSON-serializable data
        indent: JSON indentation (default 2)
        use_lock: Whether to use file locking (default True)

    Returns:
        True if successful, False otherwise
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lock = FileLock(path) if use_lock and LOCK_AVAILABLE else None

    try:
        if lock:
            lock.acquire()

        # Create temp file in same directory (for atomic rename)
        fd, temp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=f'.{path.stem}_',
            suffix='.tmp'
        )

        try:
            # Write to temp file
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk

            # Atomic replace (this is atomic on both Windows and Unix)
            os.replace(temp_path, path)
            return True

        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            print(f"[SAFE_FILE] Write error: {e}")
            return False

    finally:
        if lock:
            lock.release()


def atomic_json_read(path: str, default: Any = None, use_lock: bool = True) -> Any:
    """
    Read JSON data with optional locking.

    Args:
        path: File path to read
        default: Value to return if file doesn't exist or is invalid
        use_lock: Whether to use file locking (default True)

    Returns:
        Parsed JSON data, or default if error
    """
    path = Path(path)

    if not path.exists():
        return default

    lock = FileLock(path) if use_lock and LOCK_AVAILABLE else None

    try:
        if lock:
            lock.acquire()

        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    except json.JSONDecodeError as e:
        print(f"[SAFE_FILE] JSON decode error in {path}: {e}")
        # Try to recover from backup if available
        backup_path = path.with_suffix(path.suffix + '.backup')
        if backup_path.exists():
            print(f"[SAFE_FILE] Attempting recovery from backup")
            try:
                with open(backup_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return default

    except Exception as e:
        print(f"[SAFE_FILE] Read error: {e}")
        return default

    finally:
        if lock:
            lock.release()


def safe_json_update(path: str, update_func: callable, default: Any = None) -> bool:
    """
    Safely read, update, and write JSON file.

    This is the recommended way to modify JSON files as it handles
    locking and atomic writes automatically.

    Args:
        path: File path
        update_func: Function that takes current data and returns updated data
        default: Default value if file doesn't exist

    Returns:
        True if successful

    Example:
        def add_item(data):
            data['items'].append('new_item')
            return data

        safe_json_update('data.json', add_item, default={'items': []})
    """
    path = Path(path)

    with FileLock(path) if LOCK_AVAILABLE else nullcontext():
        # Read current data
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = default if default is not None else {}
        else:
            data = default if default is not None else {}

        # Apply update
        updated_data = update_func(data)

        # Write atomically
        return atomic_json_write(path, updated_data, use_lock=False)


@contextmanager
def nullcontext():
    """Null context manager for when locking is not available."""
    yield


# Convenience functions for common operations
def append_to_json_array(path: str, item: Any, array_key: str = None, max_size: int = None) -> bool:
    """
    Append item to a JSON array safely.

    Args:
        path: File path
        item: Item to append
        array_key: If JSON is an object, the key containing the array
        max_size: Maximum array size (oldest items removed if exceeded)

    Returns:
        True if successful
    """
    def updater(data):
        if array_key:
            if not isinstance(data, dict):
                data = {array_key: []}
            arr = data.setdefault(array_key, [])
        else:
            if not isinstance(data, list):
                data = []
            arr = data

        arr.append(item)

        # Trim if max_size specified
        if max_size and len(arr) > max_size:
            if array_key:
                data[array_key] = arr[-max_size:]
            else:
                data = arr[-max_size:]

        return data

    return safe_json_update(path, updater, default={array_key: []} if array_key else [])
