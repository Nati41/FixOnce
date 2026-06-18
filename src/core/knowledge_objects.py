"""
Knowledge Objects - Immutable knowledge storage for FixOnce V2.

This module implements the foundation for Git-style knowledge version control:
- Immutable objects (decisions, bugs, avoids, questions)
- Sequential IDs (dec_001, bug_001, etc.)
- Pending changes tracking (for future fo_commit)

Architecture Decision:
Objects are stored as individual JSON files, not in a single DB.
This enables:
1. Git-friendly diffs (each object is a separate file)
2. Easy inspection and debugging
3. No corruption risk from partial writes
4. Future: portable .fixonce/ directory

Objects are NEVER modified after creation.
Superseding creates a NEW object with a link to the old one.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Literal, List
from dataclasses import dataclass, asdict
from filelock import FileLock

# Object types
ObjectType = Literal["decision", "bug", "avoid", "question"]

# Type prefixes for IDs
TYPE_PREFIXES = {
    "decision": "dec",
    "bug": "bug",
    "avoid": "avoid",
    "question": "q",
}


@dataclass
class KnowledgeObject:
    """Immutable knowledge object."""
    id: str
    type: ObjectType
    text: str
    reason: str
    created_at: str
    actor: str
    actor_source: str
    links: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _get_v2_dir(project_id: str) -> Path:
    """Get the V2 directory for a project."""
    src_dir = Path(__file__).parent.parent
    project_dir = src_dir.parent
    data_dir = project_dir / "data" / "projects_v2"
    return data_dir / project_id


def _ensure_v2_structure(project_id: str) -> Path:
    """
    Ensure V2 directory structure exists.

    Creates:
        data/projects_v2/{project_id}/
        ├── objects/
        ├── pending/
        └── index.json
    """
    v2_dir = _get_v2_dir(project_id)
    objects_dir = v2_dir / "objects"
    pending_dir = v2_dir / "pending"

    objects_dir.mkdir(parents=True, exist_ok=True)
    pending_dir.mkdir(parents=True, exist_ok=True)

    index_path = v2_dir / "index.json"
    if not index_path.exists():
        index = {
            "version": 2,
            "created_at": datetime.now().isoformat(),
            "counters": {
                "decision": 0,
                "bug": 0,
                "avoid": 0,
                "question": 0,
            },
            "objects": [],
        }
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    pending_path = pending_dir / "pending_changes.json"
    if not pending_path.exists():
        pending = {
            "decisions": [],
            "bugs": [],
            "avoids": [],
            "questions": [],
            "updated_at": datetime.now().isoformat(),
        }
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)

    return v2_dir


def _load_index(project_id: str) -> Dict[str, Any]:
    """Load the project index."""
    v2_dir = _get_v2_dir(project_id)
    index_path = v2_dir / "index.json"

    if not index_path.exists():
        _ensure_v2_structure(project_id)

    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(project_id: str, index: Dict[str, Any]) -> None:
    """Save the project index atomically."""
    v2_dir = _get_v2_dir(project_id)
    index_path = v2_dir / "index.json"
    lock_path = v2_dir / "index.json.lock"

    with FileLock(lock_path, timeout=5):
        temp_path = index_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        temp_path.replace(index_path)


def _next_id(project_id: str, obj_type: ObjectType) -> str:
    """
    Generate the next sequential ID for an object type.

    Format: {prefix}_{sequence:03d}
    Example: dec_001, bug_042, avoid_007
    """
    index = _load_index(project_id)
    counter = index["counters"].get(obj_type, 0) + 1
    index["counters"][obj_type] = counter
    _save_index(project_id, index)

    prefix = TYPE_PREFIXES[obj_type]
    return f"{prefix}_{counter:03d}"


def create_object(
    project_id: str,
    obj_type: ObjectType,
    text: str,
    reason: str,
    actor: str = "unknown",
    actor_source: str = "unknown",
    links: Optional[Dict[str, Any]] = None,
) -> KnowledgeObject:
    """
    Create an immutable knowledge object.

    This function:
    1. Generates a sequential ID
    2. Creates the object file
    3. Updates the index
    4. Adds to pending changes

    The object is NEVER modified after creation.
    """
    _ensure_v2_structure(project_id)

    obj_id = _next_id(project_id, obj_type)
    created_at = datetime.now().isoformat()

    obj = KnowledgeObject(
        id=obj_id,
        type=obj_type,
        text=text,
        reason=reason,
        created_at=created_at,
        actor=actor,
        actor_source=actor_source,
        links=links or {},
    )

    # Save object file
    v2_dir = _get_v2_dir(project_id)
    obj_path = v2_dir / "objects" / f"{obj_id}.json"

    with open(obj_path, "w", encoding="utf-8") as f:
        json.dump(obj.to_dict(), f, ensure_ascii=False, indent=2)

    # Update index
    index = _load_index(project_id)
    index["objects"].append({
        "id": obj_id,
        "type": obj_type,
        "created_at": created_at,
    })
    _save_index(project_id, index)

    # Add to pending changes
    _add_to_pending(project_id, obj_type, obj_id)

    return obj


def _add_to_pending(project_id: str, obj_type: ObjectType, obj_id: str) -> None:
    """Add an object ID to pending changes."""
    v2_dir = _get_v2_dir(project_id)
    pending_path = v2_dir / "pending" / "pending_changes.json"
    lock_path = pending_path.with_suffix(".lock")

    with FileLock(lock_path, timeout=5):
        with open(pending_path, "r", encoding="utf-8") as f:
            pending = json.load(f)

        # Map object type to pending key
        key_map = {
            "decision": "decisions",
            "bug": "bugs",
            "avoid": "avoids",
            "question": "questions",
        }
        key = key_map[obj_type]

        if obj_id not in pending[key]:
            pending[key].append(obj_id)
            pending["updated_at"] = datetime.now().isoformat()

        temp_path = pending_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
        temp_path.replace(pending_path)


def get_pending_changes(project_id: str) -> Dict[str, List[str]]:
    """Get all pending (uncommitted) changes."""
    v2_dir = _get_v2_dir(project_id)
    pending_path = v2_dir / "pending" / "pending_changes.json"

    if not pending_path.exists():
        return {
            "decisions": [],
            "bugs": [],
            "avoids": [],
            "questions": [],
        }

    with open(pending_path, "r", encoding="utf-8") as f:
        pending = json.load(f)

    return {
        "decisions": pending.get("decisions", []),
        "bugs": pending.get("bugs", []),
        "avoids": pending.get("avoids", []),
        "questions": pending.get("questions", []),
    }


def load_object(project_id: str, obj_id: str) -> Optional[Dict[str, Any]]:
    """Load a knowledge object by ID."""
    v2_dir = _get_v2_dir(project_id)
    obj_path = v2_dir / "objects" / f"{obj_id}.json"

    if not obj_path.exists():
        return None

    with open(obj_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_pending_objects(project_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get all pending objects with their full data.

    Returns:
        {
            "decisions": [{"id": "dec_001", "text": "...", ...}, ...],
            "bugs": [...],
            "avoids": [...],
            "questions": [...],
        }
    """
    pending = get_pending_changes(project_id)
    result = {
        "decisions": [],
        "bugs": [],
        "avoids": [],
        "questions": [],
    }

    for key in result.keys():
        for obj_id in pending.get(key, []):
            obj = load_object(project_id, obj_id)
            if obj:
                result[key].append(obj)

    return result


def clear_pending(project_id: str) -> None:
    """
    Clear pending changes (called after commit).

    NOTE: This does NOT delete objects. Objects are immutable.
    This only clears the pending list.
    """
    v2_dir = _get_v2_dir(project_id)
    pending_path = v2_dir / "pending" / "pending_changes.json"

    if not pending_path.exists():
        return

    pending = {
        "decisions": [],
        "bugs": [],
        "avoids": [],
        "questions": [],
        "updated_at": datetime.now().isoformat(),
        "last_cleared_at": datetime.now().isoformat(),
    }

    with open(pending_path, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


def get_object_count(project_id: str) -> Dict[str, int]:
    """Get count of objects by type."""
    v2_dir = _get_v2_dir(project_id)
    index_path = v2_dir / "index.json"

    if not index_path.exists():
        return {"decision": 0, "bug": 0, "avoid": 0, "question": 0}

    index = _load_index(project_id)
    return index.get("counters", {})
