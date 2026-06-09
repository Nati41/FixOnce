"""
Pending memories queue for user review (Memory Review MVP).

Stores proposed memories from agents for user approval before
committing to durable project memory.

DATA INTEGRITY GUARANTEES:
1. All operations use file locking (no concurrent write loss)
2. All writes are atomic (temp file + rename)
3. Each item has stable ID and project_id (no cross-project contamination)
4. Corrupted JSON is backed up, not silently overwritten
5. Partial approval removes only processed items

Feature flag: MEMORY_REVIEW_ENABLED (default: False)
When disabled, fo_decide/fo_solved write directly as before.
When enabled, writes go to pending queue first.
"""

import json
import os
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from config import USER_DATA_DIR

# Import safe file operations
try:
    from core.safe_file import FileLock, atomic_json_write, atomic_json_read, LOCK_AVAILABLE
    SAFE_FILE_AVAILABLE = True
except ImportError:
    SAFE_FILE_AVAILABLE = False
    LOCK_AVAILABLE = False


PENDING_FILE = USER_DATA_DIR / "pending_memories.json"
PENDING_BACKUP_DIR = USER_DATA_DIR / ".backups"


class PendingQueueError(Exception):
    """Raised when pending queue operations fail."""
    pass


class PendingQueueCorruptedError(PendingQueueError):
    """Raised when pending queue JSON is corrupted."""
    def __init__(self, message: str, backup_path: Optional[Path] = None):
        super().__init__(message)
        self.backup_path = backup_path


def is_review_enabled() -> bool:
    """Check if memory review mode is enabled via env var."""
    return os.environ.get("MEMORY_REVIEW_ENABLED", "").lower() in ("1", "true", "yes")


def _generate_item_id() -> str:
    """Generate a stable unique ID for a pending item."""
    return f"pending_{uuid.uuid4().hex[:12]}"


def _backup_corrupted_file(file_path: Path, error: str) -> Optional[Path]:
    """
    Backup a corrupted file instead of silently overwriting.

    Returns:
        Path to backup file, or None if backup failed
    """
    if not file_path.exists():
        return None

    try:
        PENDING_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"corrupted_{file_path.stem}_{timestamp}.json"
        backup_path = PENDING_BACKUP_DIR / backup_name

        # Copy the corrupted file
        shutil.copy2(file_path, backup_path)

        # Write error info
        error_file = backup_path.with_suffix('.error.txt')
        error_file.write_text(f"Corrupted at: {datetime.now().isoformat()}\nError: {error}\n")

        print(f"[PENDING] Corrupted file backed up: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"[PENDING] Failed to backup corrupted file: {e}")
        return None


def _get_lock() -> 'FileLock':
    """Get a file lock for the pending file."""
    if SAFE_FILE_AVAILABLE and LOCK_AVAILABLE:
        return FileLock(str(PENDING_FILE))
    return None


def _load_unlocked() -> Tuple[Dict[str, Any], Optional[Path]]:
    """
    Load pending memories WITHOUT acquiring lock (caller must hold lock).

    Returns:
        Tuple of (data dict, backup_path if corrupted)

    Raises:
        PendingQueueCorruptedError if JSON is invalid (after backing up)
    """
    backup_path = None

    if not PENDING_FILE.exists():
        return {"pending": [], "next_task": "", "updated_at": None, "version": 1}, None

    content = PENDING_FILE.read_text(encoding='utf-8')

    # Handle empty file
    if not content.strip():
        return {"pending": [], "next_task": "", "updated_at": None, "version": 1}, None

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        # CRITICAL: Don't silently overwrite - backup first
        backup_path = _backup_corrupted_file(PENDING_FILE, str(e))
        raise PendingQueueCorruptedError(
            f"Pending queue JSON is corrupted: {e}. Backup created at {backup_path}",
            backup_path=backup_path
        )

    # Validate structure
    if not isinstance(data, dict):
        backup_path = _backup_corrupted_file(PENDING_FILE, "Root is not a dict")
        raise PendingQueueCorruptedError(
            f"Pending queue has invalid structure. Backup created at {backup_path}",
            backup_path=backup_path
        )

    if not isinstance(data.get("pending"), list):
        data["pending"] = []

    # Ensure version field
    if "version" not in data:
        data["version"] = 1

    return data, None


def _save_unlocked(data: Dict[str, Any]) -> bool:
    """
    Save pending memories WITHOUT acquiring lock (caller must hold lock).

    Returns:
        True if saved successfully
    """
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    data["version"] = data.get("version", 1)

    try:
        # Write to temp file first, then rename (atomic on POSIX)
        import tempfile
        fd, temp_path = tempfile.mkstemp(
            dir=PENDING_FILE.parent,
            prefix='.pending_',
            suffix='.tmp'
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # Atomic rename
            os.replace(temp_path, PENDING_FILE)
            return True
        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as e:
        print(f"[PENDING] Save failed: {e}")
        return False


def _load_with_lock() -> Tuple[Dict[str, Any], Optional[Path]]:
    """
    Load pending memories with file locking.

    Returns:
        Tuple of (data dict, backup_path if corrupted)

    Raises:
        PendingQueueCorruptedError if JSON is invalid (after backing up)
    """
    lock = _get_lock()

    try:
        if lock:
            lock.acquire()
        return _load_unlocked()
    finally:
        if lock:
            lock.release()


def _save_with_lock(data: Dict[str, Any]) -> bool:
    """
    Save pending memories with file locking and atomic write.

    Returns:
        True if saved successfully
    """
    lock = _get_lock()

    try:
        if lock:
            lock.acquire()
        return _save_unlocked(data)
    finally:
        if lock:
            lock.release()


def _atomic_modify(modify_fn) -> Any:
    """
    Atomically modify the pending queue.

    Holds the lock for the entire load → modify → save cycle.

    Args:
        modify_fn: Function that takes data dict and returns (modified_data, result)

    Returns:
        The result from modify_fn
    """
    lock = _get_lock()

    try:
        if lock:
            lock.acquire()

        # Load while holding lock
        try:
            data, _ = _load_unlocked()
        except PendingQueueCorruptedError:
            data = {"pending": [], "next_task": "", "updated_at": None, "version": 1}

        # Modify
        modified_data, result = modify_fn(data)

        # Save while still holding lock
        _save_unlocked(modified_data)

        return result

    finally:
        if lock:
            lock.release()


def _load() -> Dict[str, Any]:
    """
    Load pending memories (legacy compatibility wrapper).

    For new code, use _load_with_lock() directly to handle corruption.
    """
    try:
        data, _ = _load_with_lock()
        return data
    except PendingQueueCorruptedError:
        # Return empty state after corruption is backed up
        return {"pending": [], "next_task": "", "updated_at": None, "version": 1}


def _save(data: Dict[str, Any]) -> None:
    """Save pending memories (legacy compatibility wrapper)."""
    _save_with_lock(data)


def add_pending_decision(
    text: str,
    reason: str,
    actor: str = "unknown",
    project_id: str = None,
    project_path: str = None
) -> Dict[str, Any]:
    """
    Add a decision to the pending queue.

    Thread-safe: holds lock for entire load → append → save cycle.

    Args:
        text: Decision text
        reason: Why this decision was made
        actor: Who made the decision (claude, codex, user, etc.)
        project_id: Project this belongs to (REQUIRED for cross-project safety)
        project_path: Working directory path (optional)
    """
    item = {
        "id": _generate_item_id(),
        "type": "decision",
        "text": text,
        "reason": reason,
        "actor": actor,
        "project_id": project_id,
        "project_path": project_path,
        "checked": True,
        "created_at": datetime.now().isoformat(),
        "timestamp": datetime.now().isoformat(),  # Legacy compatibility
    }

    def modify(data):
        data["pending"].append(item)
        return data, item

    return _atomic_modify(modify)


def add_pending_avoid(
    what: str,
    reason: str,
    actor: str = "unknown",
    project_id: str = None,
    project_path: str = None
) -> Dict[str, Any]:
    """Add an avoid pattern to the pending queue. Thread-safe."""
    item = {
        "id": _generate_item_id(),
        "type": "avoid",
        "text": what,
        "reason": reason,
        "actor": actor,
        "project_id": project_id,
        "project_path": project_path,
        "checked": True,
        "created_at": datetime.now().isoformat(),
        "timestamp": datetime.now().isoformat(),
    }

    def modify(data):
        data["pending"].append(item)
        return data, item

    return _atomic_modify(modify)


def add_pending_solution(
    problem: str,
    solution: str,
    files: Optional[List[str]] = None,
    actor: str = "unknown",
    project_id: str = None,
    project_path: str = None
) -> Dict[str, Any]:
    """Add a solved bug to the pending queue. Thread-safe."""
    item = {
        "id": _generate_item_id(),
        "type": "solution",
        "problem": problem,
        "solution": solution,
        "files": files or [],
        "actor": actor,
        "project_id": project_id,
        "project_path": project_path,
        "checked": True,
        "created_at": datetime.now().isoformat(),
        "timestamp": datetime.now().isoformat(),
    }

    def modify(data):
        data["pending"].append(item)
        return data, item

    return _atomic_modify(modify)


def add_custom_memory(
    text: str,
    memory_type: str = "note",
    project_id: str = None,
    project_path: str = None
) -> Dict[str, Any]:
    """Add a custom user-created memory to the pending queue. Thread-safe."""
    item = {
        "id": _generate_item_id(),
        "type": memory_type,
        "text": text,
        "reason": "User added",
        "actor": "user",
        "project_id": project_id,
        "project_path": project_path,
        "checked": True,
        "created_at": datetime.now().isoformat(),
        "timestamp": datetime.now().isoformat(),
    }

    def modify(data):
        data["pending"].append(item)
        return data, item

    return _atomic_modify(modify)


def set_next_task(task: str) -> None:
    """Set the proposed next task. Thread-safe."""
    def modify(data):
        data["next_task"] = task
        return data, None

    _atomic_modify(modify)


def get_pending() -> Dict[str, Any]:
    """Get all pending memories and next task."""
    return _load()


def get_pending_safe() -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Get pending memories with error information.

    Returns:
        Tuple of (data dict, error message or None)
    """
    try:
        data, _ = _load_with_lock()
        return data, None
    except PendingQueueCorruptedError as e:
        return {"pending": [], "next_task": "", "updated_at": None, "version": 1}, str(e)


def get_pending_count() -> int:
    """Get count of pending items."""
    data = _load()
    return len(data.get("pending", []))


def get_item_by_id(item_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific pending item by ID."""
    data = _load()
    for item in data.get("pending", []):
        if item.get("id") == item_id:
            return item
    return None


def get_items_by_project(project_id: str) -> List[Dict[str, Any]]:
    """Get all pending items for a specific project."""
    data = _load()
    return [item for item in data.get("pending", []) if item.get("project_id") == project_id]


def clear_pending() -> int:
    """
    Clear the pending queue. Returns count cleared. Thread-safe.

    WARNING: This clears ALL items. For partial clearing, use remove_items_by_ids().
    """
    def modify(data):
        count = len(data.get("pending", []))
        data["pending"] = []
        data["next_task"] = ""
        return data, count

    return _atomic_modify(modify)


def remove_item(index: int) -> bool:
    """
    Remove a single item by index. Thread-safe.

    DEPRECATED: Use remove_items_by_ids() for safer operation.
    """
    def modify(data):
        if 0 <= index < len(data.get("pending", [])):
            data["pending"].pop(index)
            return data, True
        return data, False

    return _atomic_modify(modify)


def remove_items_by_ids(item_ids: List[str]) -> Tuple[int, List[str]]:
    """
    Remove specific items by their IDs. Thread-safe.

    This is the SAFE way to remove items - only removes exact matches.

    Args:
        item_ids: List of item IDs to remove

    Returns:
        Tuple of (count removed, list of IDs that were not found)
    """
    def modify(data):
        pending = data.get("pending", [])
        existing_ids = {item.get("id") for item in pending}

        not_found = [id for id in item_ids if id not in existing_ids]

        # Remove only matching items
        original_count = len(pending)
        data["pending"] = [item for item in pending if item.get("id") not in item_ids]
        removed_count = original_count - len(data["pending"])

        return data, (removed_count, not_found)

    return _atomic_modify(modify)


def update_item_checked(index: int, checked: bool) -> bool:
    """Update the checked state of an item. Thread-safe."""
    def modify(data):
        if 0 <= index < len(data.get("pending", [])):
            data["pending"][index]["checked"] = checked
            return data, True
        return data, False

    return _atomic_modify(modify)


def extract_approved_by_ids(
    approved_ids: List[str],
    next_task: str = "",
    custom_memory: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract approved items by ID WITHOUT clearing the queue.

    This is the SAFE extraction method that:
    1. Uses stable IDs, not indices
    2. Does NOT modify the pending queue
    3. Groups items by project_id for proper routing

    Args:
        approved_ids: List of item IDs to extract
        next_task: The next task text (may be edited by user)
        custom_memory: Optional custom memory text to add

    Returns:
        Dict with approved items grouped by project_id:
        {
            "by_project": {
                "ProjectA_123": {"decisions": [...], "avoid": [...], ...},
                "ProjectB_456": {"decisions": [...], ...},
            },
            "next_task": "...",
            "approved_ids": [...]
        }
    """
    data = _load()
    pending = data.get("pending", [])

    # Build lookup by ID
    by_id = {item.get("id"): item for item in pending if item.get("id")}

    # Group approved items by project_id
    by_project: Dict[str, Dict[str, List]] = {}
    approved_found = []

    for item_id in approved_ids:
        item = by_id.get(item_id)
        if not item:
            continue

        approved_found.append(item_id)
        project_id = item.get("project_id") or "_unknown_"

        if project_id not in by_project:
            by_project[project_id] = {
                "decisions": [],
                "avoid": [],
                "solutions": [],
                "custom": [],
            }

        item_type = item.get("type", "")
        if item_type == "decision":
            by_project[project_id]["decisions"].append(item)
        elif item_type == "avoid":
            by_project[project_id]["avoid"].append(item)
        elif item_type == "solution":
            by_project[project_id]["solutions"].append(item)
        else:
            by_project[project_id]["custom"].append(item)

    # Add custom memory if provided
    if custom_memory and custom_memory.strip():
        # Custom memories go to "_unknown_" project (dashboard will assign)
        if "_unknown_" not in by_project:
            by_project["_unknown_"] = {"decisions": [], "avoid": [], "solutions": [], "custom": []}
        by_project["_unknown_"]["custom"].append({
            "id": _generate_item_id(),
            "type": "note",
            "text": custom_memory.strip(),
            "actor": "user",
            "created_at": datetime.now().isoformat(),
        })

    return {
        "by_project": by_project,
        "next_task": next_task,
        "approved_ids": approved_found,
    }


def extract_approved(
    approved_indices: List[int],
    next_task: str = "",
    custom_memory: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract approved items WITHOUT clearing the queue.

    DEPRECATED: Use extract_approved_by_ids() for safer operation.
    This is kept for backward compatibility.

    Args:
        approved_indices: List of indices to extract
        next_task: The next task text (may be edited by user)
        custom_memory: Optional custom memory text to add

    Returns:
        Dict with approved items by type (legacy format)
    """
    data = _load()
    pending = data.get("pending", [])

    approved = {
        "decisions": [],
        "avoid": [],
        "solutions": [],
        "custom": [],
        "next_task": next_task,
    }

    for idx in approved_indices:
        if 0 <= idx < len(pending):
            item = pending[idx]
            item_type = item.get("type", "")
            if item_type == "decision":
                approved["decisions"].append(item)
            elif item_type == "avoid":
                approved["avoid"].append(item)
            elif item_type == "solution":
                approved["solutions"].append(item)
            else:
                approved["custom"].append(item)

    if custom_memory and custom_memory.strip():
        approved["custom"].append({
            "id": _generate_item_id(),
            "type": "note",
            "text": custom_memory.strip(),
            "actor": "user",
            "timestamp": datetime.now().isoformat(),
        })

    return approved


def approve_selected(
    approved_indices: List[int],
    next_task: str = "",
    custom_memory: Optional[str] = None,
) -> Dict[str, Any]:
    """
    DEPRECATED: Use extract_approved_by_ids() + remove_items_by_ids() instead.

    Extract approved items AND clear the queue (legacy behavior).
    This clears the queue before the caller saves, which can lose items if save fails.
    """
    approved = extract_approved(approved_indices, next_task, custom_memory)
    clear_pending()
    return approved


__all__ = [
    "is_review_enabled",
    "add_pending_decision",
    "add_pending_avoid",
    "add_pending_solution",
    "add_custom_memory",
    "set_next_task",
    "get_pending",
    "get_pending_safe",
    "get_pending_count",
    "get_item_by_id",
    "get_items_by_project",
    "clear_pending",
    "remove_item",
    "remove_items_by_ids",
    "update_item_checked",
    "extract_approved",
    "extract_approved_by_ids",
    "approve_selected",
    "PendingQueueError",
    "PendingQueueCorruptedError",
]
