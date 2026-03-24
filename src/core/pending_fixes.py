"""
FixOnce Auto-Apply Engine

Manages pending fixes with confidence-based auto-apply logic.
Uses file-based storage for cross-process sharing.

Thresholds:
- confidence >= 90%: AUTO (apply without asking)
- confidence 70-89%: SUGGEST (show to user)
- confidence < 70%: SILENT (don't suggest)
"""

import json
import os
import fcntl
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

# Configuration
AUTO_THRESHOLD = 90      # Auto-apply without asking
SUGGEST_THRESHOLD = 70   # Suggest to user
MAX_PENDING = 50         # Max pending fixes to keep

# File-based storage for cross-process sharing
PENDING_FILE = Path.home() / ".fixonce" / "pending_fixes.json"


def _load_pending() -> List[Dict[str, Any]]:
    """Load pending fixes from file."""
    if not PENDING_FILE.exists():
        return []
    try:
        with open(PENDING_FILE, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return data.get("pending", [])
    except (json.JSONDecodeError, IOError):
        return []


def _save_pending(pending: List[Dict[str, Any]]):
    """Save pending fixes to file."""
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(PENDING_FILE, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            json.dump({"pending": pending[-MAX_PENDING:], "updated": datetime.now().isoformat()}, f, indent=2)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except IOError as e:
        print(f"[pending_fixes] Save error: {e}")


def add_pending_fix(
    error_message: str,
    solution_text: str,
    confidence: int,
    similarity: int,
    source: str = "semantic",
    files: List[str] = None,
    error_id: str = None
) -> Dict[str, Any]:
    """
    Add a fix to the pending queue based on confidence.

    Returns:
        Dict with action taken: "auto", "suggest", or "silent"
    """
    # Determine action based on confidence
    if confidence >= AUTO_THRESHOLD:
        action = "auto"
    elif confidence >= SUGGEST_THRESHOLD:
        action = "suggest"
    else:
        action = "silent"
        return {"action": action, "reason": "confidence too low"}

    fix_entry = {
        "id": error_id or f"fix_{datetime.now().timestamp()}",
        "error_message": error_message[:500],  # Truncate long errors
        "solution_text": solution_text[:1000],  # Truncate long solutions
        "confidence": confidence,
        "similarity": similarity,
        "action": action,
        "source": source,
        "files": files or [],
        "timestamp": datetime.now().isoformat(),
        "status": "pending"  # pending, applied, rejected, expired
    }

    pending = _load_pending()

    # Check for duplicates (same error message)
    for existing in pending:
        if existing["error_message"] == error_message and existing["status"] == "pending":
            return {"action": "duplicate", "existing_id": existing["id"]}

    pending.append(fix_entry)
    _save_pending(pending)

    print(f"[pending_fixes] Added {action} fix: {error_message[:50]}... (confidence: {confidence}%)")

    return {
        "action": action,
        "fix_id": fix_entry["id"],
        "confidence": confidence
    }


def get_pending_fixes(action_filter: str = None) -> List[Dict[str, Any]]:
    """
    Get pending fixes, optionally filtered by action type.

    Args:
        action_filter: "auto", "suggest", or None for all

    Returns:
        List of pending fix entries
    """
    pending = _load_pending()
    fixes = [f for f in pending if f["status"] == "pending"]

    if action_filter:
        fixes = [f for f in fixes if f["action"] == action_filter]

    return fixes


def get_auto_fixes() -> List[Dict[str, Any]]:
    """Get fixes that should be auto-applied (confidence >= 90%)."""
    return get_pending_fixes(action_filter="auto")


def get_suggested_fixes() -> List[Dict[str, Any]]:
    """Get fixes that should be suggested (confidence 70-89%)."""
    return get_pending_fixes(action_filter="suggest")


def mark_fix_applied(fix_id: str, success: bool = True) -> bool:
    """
    Mark a fix as applied.

    Args:
        fix_id: The fix ID to mark
        success: Whether the fix was successful

    Returns:
        True if fix was found and updated
    """
    pending = _load_pending()

    for fix in pending:
        if fix["id"] == fix_id:
            fix["status"] = "applied" if success else "failed"
            fix["applied_at"] = datetime.now().isoformat()
            _save_pending(pending)
            return True

    return False


def mark_fix_rejected(fix_id: str, reason: str = "") -> bool:
    """
    Mark a fix as rejected by user.

    Args:
        fix_id: The fix ID to reject
        reason: Optional reason for rejection

    Returns:
        True if fix was found and updated
    """
    pending = _load_pending()

    for fix in pending:
        if fix["id"] == fix_id:
            fix["status"] = "rejected"
            fix["rejected_at"] = datetime.now().isoformat()
            fix["reject_reason"] = reason
            _save_pending(pending)
            return True

    return False


def clear_pending() -> int:
    """Clear all pending fixes. Returns count cleared."""
    pending = _load_pending()
    count = len([f for f in pending if f["status"] == "pending"])
    _save_pending([])
    return count


def get_stats() -> Dict[str, Any]:
    """Get statistics about pending fixes."""
    pending = _load_pending()

    return {
        "total_pending": len([f for f in pending if f["status"] == "pending"]),
        "auto_ready": len([f for f in pending if f["status"] == "pending" and f["action"] == "auto"]),
        "suggested": len([f for f in pending if f["status"] == "pending" and f["action"] == "suggest"]),
        "applied": len([f for f in pending if f["status"] == "applied"]),
        "rejected": len([f for f in pending if f["status"] == "rejected"]),
    }


# For direct import
__all__ = [
    "add_pending_fix",
    "get_pending_fixes",
    "get_auto_fixes",
    "get_suggested_fixes",
    "mark_fix_applied",
    "mark_fix_rejected",
    "clear_pending",
    "get_stats",
    "AUTO_THRESHOLD",
    "SUGGEST_THRESHOLD"
]
