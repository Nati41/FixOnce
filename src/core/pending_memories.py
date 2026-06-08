"""
Pending memories queue for user review (Memory Review MVP).

Stores proposed memories from agents for user approval before
committing to durable project memory.

Feature flag: MEMORY_REVIEW_ENABLED (default: False)
When disabled, fo_decide/fo_solved write directly as before.
When enabled, writes go to pending queue first.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import USER_DATA_DIR


PENDING_FILE = USER_DATA_DIR / "pending_memories.json"


def is_review_enabled() -> bool:
    """Check if memory review mode is enabled via env var."""
    return os.environ.get("MEMORY_REVIEW_ENABLED", "").lower() in ("1", "true", "yes")


def _load() -> Dict[str, Any]:
    """Load pending memories from file."""
    if not PENDING_FILE.exists():
        return {"pending": [], "next_task": "", "updated_at": None}
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("pending"), list):
            data["pending"] = []
        return data
    except (json.JSONDecodeError, IOError):
        return {"pending": [], "next_task": "", "updated_at": None}


def _save(data: Dict[str, Any]) -> None:
    """Save pending memories to file."""
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, ensure_ascii=False, indent=2, fp=f)


def add_pending_decision(text: str, reason: str, actor: str = "unknown") -> Dict[str, Any]:
    """Add a decision to the pending queue."""
    item = {
        "type": "decision",
        "text": text,
        "reason": reason,
        "actor": actor,
        "checked": True,
        "timestamp": datetime.now().isoformat(),
    }
    data = _load()
    data["pending"].append(item)
    _save(data)
    return item


def add_pending_avoid(what: str, reason: str, actor: str = "unknown") -> Dict[str, Any]:
    """Add an avoid pattern to the pending queue."""
    item = {
        "type": "avoid",
        "text": what,
        "reason": reason,
        "actor": actor,
        "checked": True,
        "timestamp": datetime.now().isoformat(),
    }
    data = _load()
    data["pending"].append(item)
    _save(data)
    return item


def add_pending_solution(
    problem: str,
    solution: str,
    files: Optional[List[str]] = None,
    actor: str = "unknown",
) -> Dict[str, Any]:
    """Add a solved bug to the pending queue."""
    item = {
        "type": "solution",
        "problem": problem,
        "solution": solution,
        "files": files or [],
        "actor": actor,
        "checked": True,
        "timestamp": datetime.now().isoformat(),
    }
    data = _load()
    data["pending"].append(item)
    _save(data)
    return item


def add_custom_memory(text: str, memory_type: str = "note") -> Dict[str, Any]:
    """Add a custom user-created memory to the pending queue."""
    item = {
        "type": memory_type,
        "text": text,
        "reason": "User added",
        "actor": "user",
        "checked": True,
        "timestamp": datetime.now().isoformat(),
    }
    data = _load()
    data["pending"].append(item)
    _save(data)
    return item


def set_next_task(task: str) -> None:
    """Set the proposed next task."""
    data = _load()
    data["next_task"] = task
    _save(data)


def get_pending() -> Dict[str, Any]:
    """Get all pending memories and next task."""
    return _load()


def get_pending_count() -> int:
    """Get count of pending items."""
    data = _load()
    return len(data.get("pending", []))


def clear_pending() -> int:
    """Clear the pending queue. Returns count cleared."""
    data = _load()
    count = len(data.get("pending", []))
    data["pending"] = []
    data["next_task"] = ""
    _save(data)
    return count


def remove_item(index: int) -> bool:
    """Remove a single item by index."""
    data = _load()
    if 0 <= index < len(data.get("pending", [])):
        data["pending"].pop(index)
        _save(data)
        return True
    return False


def update_item_checked(index: int, checked: bool) -> bool:
    """Update the checked state of an item."""
    data = _load()
    if 0 <= index < len(data.get("pending", [])):
        data["pending"][index]["checked"] = checked
        _save(data)
        return True
    return False


def approve_selected(
    approved_indices: List[int],
    next_task: str = "",
    custom_memory: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Approve selected items and return them for saving to durable memory.

    Does NOT actually save to durable memory - caller must do that.
    This just extracts the approved items and clears the queue.

    Args:
        approved_indices: List of indices to approve
        next_task: The next task text (may be edited by user)
        custom_memory: Optional custom memory text to add

    Returns:
        Dict with approved items by type and next_task
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
            "type": "note",
            "text": custom_memory.strip(),
            "actor": "user",
            "timestamp": datetime.now().isoformat(),
        })

    data["pending"] = []
    data["next_task"] = ""
    _save(data)

    return approved


__all__ = [
    "is_review_enabled",
    "add_pending_decision",
    "add_pending_avoid",
    "add_pending_solution",
    "add_custom_memory",
    "set_next_task",
    "get_pending",
    "get_pending_count",
    "clear_pending",
    "remove_item",
    "update_item_checked",
    "approve_selected",
]
