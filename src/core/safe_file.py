"""
Safe File Operations for FixOnce.

Provides atomic writes and file locking to prevent:
1. File corruption on crash (atomic write)
2. Race conditions with concurrent access (file locking)
3. Data loss (auto-backup before every write)
4. Corruption (integrity validation)

Usage:
    from core.safe_file import atomic_json_write, atomic_json_read, FileLock

    # Atomic write (crash-safe, auto-backup)
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
import shutil
from pathlib import Path
from typing import Any, Optional, Dict, List
from contextlib import contextmanager
from datetime import datetime

# Configuration
MAX_FILE_SIZE_KB = 500  # Warn if file exceeds this size
MAX_BACKUP_COUNT = 5    # Keep last N backups
BACKUP_DIR_NAME = '.backups'


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


# ============================================================
# BACKUP MANAGEMENT
# ============================================================

def _get_backup_dir(file_path: Path) -> Path:
    """Get backup directory for a file (in same parent directory)."""
    backup_dir = file_path.parent / BACKUP_DIR_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _create_backup(file_path: Path) -> Optional[Path]:
    """
    Create a timestamped backup of a file before writing.

    Returns:
        Path to backup file, or None if file doesn't exist
    """
    if not file_path.exists():
        return None

    try:
        backup_dir = _get_backup_dir(file_path)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = backup_dir / backup_name

        # Copy file to backup
        shutil.copy2(file_path, backup_path)
        print(f"[SAFE_FILE] Backup created: {backup_path.name}")

        # Cleanup old backups (keep only MAX_BACKUP_COUNT)
        _cleanup_old_backups(file_path)

        return backup_path
    except Exception as e:
        print(f"[SAFE_FILE] Backup failed: {e}")
        return None


def _cleanup_old_backups(file_path: Path):
    """Remove old backups, keeping only the most recent MAX_BACKUP_COUNT."""
    backup_dir = _get_backup_dir(file_path)

    # Find all backups for this file
    pattern = f"{file_path.stem}_*{file_path.suffix}"
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    # Remove old backups
    for old_backup in backups[MAX_BACKUP_COUNT:]:
        try:
            old_backup.unlink()
            print(f"[SAFE_FILE] Removed old backup: {old_backup.name}")
        except Exception:
            pass


def get_latest_backup(file_path: str) -> Optional[Path]:
    """
    Get the most recent backup for a file.

    Args:
        file_path: Original file path

    Returns:
        Path to latest backup, or None if no backups exist
    """
    path = Path(file_path)
    backup_dir = _get_backup_dir(path)

    pattern = f"{path.stem}_*{path.suffix}"
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    return backups[0] if backups else None


def restore_from_backup(file_path: str, backup_path: str = None) -> bool:
    """
    Restore a file from backup.

    Args:
        file_path: Target file path
        backup_path: Specific backup to restore (or latest if None)

    Returns:
        True if restored successfully
    """
    path = Path(file_path)

    if backup_path:
        backup = Path(backup_path)
    else:
        backup = get_latest_backup(file_path)

    if not backup or not backup.exists():
        print(f"[SAFE_FILE] No backup found for {path.name}")
        return False

    try:
        shutil.copy2(backup, path)
        print(f"[SAFE_FILE] Restored from backup: {backup.name}")
        return True
    except Exception as e:
        print(f"[SAFE_FILE] Restore failed: {e}")
        return False


# ============================================================
# INTEGRITY VALIDATION
# ============================================================

def validate_json_structure(data: Any, expected_keys: List[str] = None) -> tuple[bool, str]:
    """
    Validate JSON data structure before writing.

    Args:
        data: Data to validate
        expected_keys: Required top-level keys (for dicts)

    Returns:
        (is_valid, error_message)
    """
    # Check if data is JSON-serializable
    try:
        json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        return False, f"Not JSON-serializable: {e}"

    # Check expected keys for dicts
    if expected_keys and isinstance(data, dict):
        missing = [k for k in expected_keys if k not in data]
        if missing:
            return False, f"Missing required keys: {missing}"

    return True, ""


def validate_project_data(data: dict) -> tuple[bool, str]:
    """
    Validate FixOnce project data structure.

    Args:
        data: Project data dict

    Returns:
        (is_valid, error_message)
    """
    if not isinstance(data, dict):
        return False, "Project data must be a dictionary"

    # Check required sections exist
    required_sections = ['gps', 'architecture', 'intent', 'lessons']
    missing = [s for s in required_sections if s not in data]
    if missing:
        return False, f"Missing sections: {missing}"

    # Check lessons structure
    lessons = data.get('lessons', {})
    if not isinstance(lessons, dict):
        return False, "lessons must be a dictionary"

    # Validate array fields
    array_fields = ['insights', 'failed_attempts']
    for field in array_fields:
        if field in lessons and not isinstance(lessons.get(field), list):
            return False, f"lessons.{field} must be a list"

    return True, ""


def check_file_size(path: Path, data: Any = None) -> tuple[bool, int]:
    """
    Check if file size is within acceptable limits.

    Args:
        path: File path
        data: Data to be written (optional, for pre-write check)

    Returns:
        (is_ok, size_kb)
    """
    if data is not None:
        # Estimate size from data
        try:
            size_bytes = len(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        except Exception:
            size_bytes = 0
    elif path.exists():
        size_bytes = path.stat().st_size
    else:
        return True, 0

    size_kb = size_bytes // 1024
    is_ok = size_kb <= MAX_FILE_SIZE_KB

    if not is_ok:
        print(f"[SAFE_FILE] WARNING: File size {size_kb}KB exceeds limit {MAX_FILE_SIZE_KB}KB")

    return is_ok, size_kb


# ============================================================
# EXCEPTIONS
# ============================================================

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


def atomic_json_write(
    path: str,
    data: Any,
    indent: int = 2,
    use_lock: bool = True,
    create_backup: bool = True,
    validate: bool = True,
    expected_keys: List[str] = None
) -> bool:
    """
    Write JSON data atomically (crash-safe) with auto-backup.

    Process:
    1. Validate data structure (optional)
    2. Create backup of existing file
    3. Write to temporary file in same directory
    4. Flush and sync to disk
    5. Atomically replace original file

    This ensures the file is never in a half-written state.

    Args:
        path: Target file path
        data: JSON-serializable data
        indent: JSON indentation (default 2)
        use_lock: Whether to use file locking (default True)
        create_backup: Whether to backup before writing (default True)
        validate: Whether to validate JSON structure (default True)
        expected_keys: Required top-level keys for validation

    Returns:
        True if successful, False otherwise
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Pre-write validation
    if validate:
        is_valid, error = validate_json_structure(data, expected_keys)
        if not is_valid:
            print(f"[SAFE_FILE] Validation failed: {error}")
            return False

    # Check file size
    size_ok, size_kb = check_file_size(path, data)
    if not size_ok:
        print(f"[SAFE_FILE] Proceeding despite large file size ({size_kb}KB)")

    lock = FileLock(path) if use_lock and LOCK_AVAILABLE else None

    try:
        if lock:
            lock.acquire()

        # Create backup BEFORE writing (if file exists)
        if create_backup and path.exists():
            _create_backup(path)

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


def atomic_json_read(
    path: str,
    default: Any = None,
    use_lock: bool = True,
    auto_recover: bool = True
) -> Any:
    """
    Read JSON data with optional locking and auto-recovery.

    Args:
        path: File path to read
        default: Value to return if file doesn't exist or is invalid
        use_lock: Whether to use file locking (default True)
        auto_recover: Whether to auto-recover from backup on error (default True)

    Returns:
        Parsed JSON data, or default if error
    """
    path = Path(path)

    if not path.exists():
        # Check if we can recover from backup
        if auto_recover:
            latest_backup = get_latest_backup(str(path))
            if latest_backup and latest_backup.exists():
                print(f"[SAFE_FILE] File missing, found backup: {latest_backup.name}")
                try:
                    with open(latest_backup, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # Restore the file
                    restore_from_backup(str(path), str(latest_backup))
                    return data
                except Exception:
                    pass
        return default

    lock = FileLock(path) if use_lock and LOCK_AVAILABLE else None

    try:
        if lock:
            lock.acquire()

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for empty or corrupt file
        if not content.strip():
            raise json.JSONDecodeError("Empty file", content, 0)

        data = json.loads(content)

        # Validate it's not a reset/empty project
        if isinstance(data, dict):
            # Check if this looks like a reset project (minimal data)
            lessons = data.get('lessons', {})
            if isinstance(lessons, dict):
                total_items = (
                    len(lessons.get('insights', [])) +
                    len(lessons.get('decisions', [])) +
                    len(lessons.get('failed_attempts', []))
                )
                # If file has almost no data but backup has more, warn
                if total_items == 0 and auto_recover:
                    latest_backup = get_latest_backup(str(path))
                    if latest_backup:
                        try:
                            with open(latest_backup, 'r', encoding='utf-8') as bf:
                                backup_data = json.load(bf)
                            backup_lessons = backup_data.get('lessons', {})
                            backup_items = (
                                len(backup_lessons.get('insights', [])) +
                                len(backup_lessons.get('decisions', [])) +
                                len(backup_lessons.get('failed_attempts', []))
                            )
                            if backup_items > 5:
                                print(f"[SAFE_FILE] WARNING: Current file is empty but backup has {backup_items} items!")
                                print(f"[SAFE_FILE] Consider restore_from_backup('{path}')")
                        except Exception:
                            pass

        return data

    except json.JSONDecodeError as e:
        print(f"[SAFE_FILE] JSON decode error in {path}: {e}")

        if auto_recover:
            # Try timestamped backups first
            latest_backup = get_latest_backup(str(path))
            if latest_backup and latest_backup.exists():
                print(f"[SAFE_FILE] Attempting recovery from {latest_backup.name}")
                try:
                    with open(latest_backup, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # Auto-restore the file
                    restore_from_backup(str(path), str(latest_backup))
                    print(f"[SAFE_FILE] Auto-recovered from backup!")
                    return data
                except Exception as recover_err:
                    print(f"[SAFE_FILE] Recovery failed: {recover_err}")

            # Try legacy .backup file
            legacy_backup = path.with_suffix(path.suffix + '.backup')
            if legacy_backup.exists():
                print(f"[SAFE_FILE] Trying legacy backup")
                try:
                    with open(legacy_backup, 'r', encoding='utf-8') as f:
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


# ============================================================
# DATA SIZE MANAGEMENT
# ============================================================

def trim_array_by_importance(
    items: List[dict],
    max_count: int,
    importance_key: str = 'importance',
    timestamp_key: str = 'timestamp'
) -> List[dict]:
    """
    Trim array by keeping important and recent items.

    Priority: high > medium > low
    Within same priority: newer items kept

    Args:
        items: List of dicts with importance field
        max_count: Maximum items to keep
        importance_key: Key for importance field
        timestamp_key: Key for timestamp field

    Returns:
        Trimmed list
    """
    if len(items) <= max_count:
        return items

    importance_order = {'high': 0, 'medium': 1, 'low': 2}

    def sort_key(item):
        imp = item.get(importance_key, 'medium')
        imp_score = importance_order.get(imp, 1)
        # Newer items have higher timestamps (string comparison works for ISO format)
        ts = item.get(timestamp_key, '1970-01-01')
        return (imp_score, -hash(ts))  # Lower score = keep

    sorted_items = sorted(items, key=sort_key)
    kept = sorted_items[:max_count]

    removed_count = len(items) - len(kept)
    if removed_count > 0:
        print(f"[SAFE_FILE] Trimmed {removed_count} low-priority items")

    return kept


def trim_project_data(data: dict, limits: dict = None) -> dict:
    """
    Trim project data arrays to prevent unlimited growth.

    Args:
        data: Project data dict
        limits: Dict of {field: max_count} limits

    Returns:
        Trimmed data dict
    """
    default_limits = {
        'insights': 100,
        'failed_attempts': 50,
        'debug_sessions': 50
    }
    limits = limits or default_limits

    if 'lessons' in data and isinstance(data['lessons'], dict):
        lessons = data['lessons']

        for field, max_count in limits.items():
            if field in lessons and isinstance(lessons[field], list):
                original_count = len(lessons[field])
                lessons[field] = trim_array_by_importance(
                    lessons[field],
                    max_count,
                    importance_key='importance',
                    timestamp_key='created_at'
                )
                if len(lessons[field]) < original_count:
                    print(f"[SAFE_FILE] Trimmed lessons.{field}: {original_count} -> {len(lessons[field])}")

    return data


def get_data_stats(file_path: str) -> Dict[str, Any]:
    """
    Get statistics about a project data file.

    Args:
        file_path: Path to project JSON file

    Returns:
        Dict with file stats
    """
    path = Path(file_path)

    if not path.exists():
        return {'exists': False}

    stats = {
        'exists': True,
        'size_kb': path.stat().st_size // 1024,
        'modified': datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    }

    try:
        data = atomic_json_read(file_path)
        if isinstance(data, dict):
            lessons = data.get('lessons', {})
            stats['insights_count'] = len(lessons.get('insights', []))
            stats['failed_attempts_count'] = len(lessons.get('failed_attempts', []))
            stats['decisions_count'] = len(lessons.get('decisions', []))

            # Check for backups
            backup_dir = _get_backup_dir(path)
            pattern = f"{path.stem}_*{path.suffix}"
            backups = list(backup_dir.glob(pattern))
            stats['backup_count'] = len(backups)
            if backups:
                latest = max(backups, key=lambda p: p.stat().st_mtime)
                stats['latest_backup'] = latest.name
    except Exception:
        pass

    return stats


def list_backups(file_path: str) -> List[Dict[str, Any]]:
    """
    List all backups for a file.

    Args:
        file_path: Original file path

    Returns:
        List of backup info dicts
    """
    path = Path(file_path)
    backup_dir = _get_backup_dir(path)

    pattern = f"{path.stem}_*{path.suffix}"
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    return [
        {
            'name': b.name,
            'path': str(b),
            'size_kb': b.stat().st_size // 1024,
            'modified': datetime.fromtimestamp(b.stat().st_mtime).isoformat()
        }
        for b in backups
    ]
