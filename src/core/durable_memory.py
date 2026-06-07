"""Canonical durable project-memory writes.

All future project-memory mutations should pass through this module so they
share attribution defaults and one atomic read-modify-write transaction.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple

from core.safe_file import atomic_json_update


PathSpec = Tuple[str, ...]

DEFAULT_COLLECTION_PATHS: Tuple[PathSpec, ...] = (
    ("decisions",),
    ("avoid",),
    ("debug_sessions",),
    ("ai_handoffs",),
    ("agent_audit",),
    ("command_audit",),
    ("active_issues",),
    ("solutions_history",),
    ("resume_state_history",),
    ("live_record", "lessons", "insights"),
    ("live_record", "lessons", "failed_attempts"),
    ("live_record", "architecture", "components"),
    ("live_record", "intent", "goal_history"),
    ("live_record", "vision", "*"),
)

DEFAULT_STATE_PATHS: Tuple[PathSpec, ...] = (
    ("live_record", "intent"),
    ("resume_state",),
    ("ai_session",),
)


def normalize_attribution(
    attribution: Optional[Dict[str, Any]] = None,
    tool_name: str = "memory_write",
) -> Dict[str, Any]:
    """Return complete provenance without inventing an actor identity."""
    source = dict(attribution or {})
    try:
        confidence = float(
            source.get("actor_confidence", source.get("confidence", 0.0)) or 0.0
        )
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "actor": (
            source.get("actor")
            or source.get("actor_name")
            or source.get("editor")
            or "unknown"
        ),
        "actor_source": source.get("actor_source") or source.get("source") or "none",
        "actor_confidence": confidence,
        "session_id": source.get("session_id") or "unknown-session",
        "tool_name": source.get("tool_name") or tool_name or "memory_write",
    }


def durable_record(
    record: Dict[str, Any],
    attribution: Optional[Dict[str, Any]] = None,
    tool_name: str = "memory_write",
    timestamp: Optional[str] = None,
    status: str = "active",
) -> Dict[str, Any]:
    """Apply canonical defaults to a newly durable record."""
    result = dict(record)
    for field, value in normalize_attribution(attribution, tool_name).items():
        result.setdefault(field, value)
    result.setdefault("timestamp", timestamp or datetime.now().isoformat())
    result.setdefault("status", status)
    return result


def merge_concurrent_value(base: Any, current: Any, updated: Any) -> Any:
    """Three-way merge preserving independent additions."""
    if updated == base:
        return current
    if current == base:
        return updated
    if isinstance(current, dict) and isinstance(updated, dict):
        base_dict = base if isinstance(base, dict) else {}
        merged = {}
        for key in set(base_dict) | set(current) | set(updated):
            merged[key] = merge_concurrent_value(
                base_dict.get(key),
                current.get(key),
                updated.get(key),
            )
        return merged
    if isinstance(current, list) and isinstance(updated, list):
        base_list = base if isinstance(base, list) else []
        if current[:len(base_list)] == base_list and updated[:len(base_list)] == base_list:
            merged = list(base_list)
            for item in current[len(base_list):] + updated[len(base_list):]:
                if item not in merged:
                    merged.append(item)
            return merged
    return updated


def _record_identity(item: Dict[str, Any]) -> str:
    for field in (
        "id", "decision", "what", "problem", "text", "name",
        "timestamp", "updated_at",
    ):
        value = item.get(field)
        if value:
            return f"{field}:{value}"
    return json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)


def _merge_forward_value(current: Any, updated: Any) -> Any:
    """Merge a snapshot without deleting durable records absent from it."""
    if isinstance(current, dict) and isinstance(updated, dict):
        merged = copy.deepcopy(current)
        for key, value in updated.items():
            merged[key] = _merge_forward_value(current.get(key), value)
        return merged
    if isinstance(current, list) and isinstance(updated, list):
        merged = copy.deepcopy(current)
        identity_indexes = {
            _record_identity(item): index
            for index, item in enumerate(merged)
            if isinstance(item, dict)
        }
        for item in updated:
            if isinstance(item, dict):
                identity = _record_identity(item)
                if identity in identity_indexes:
                    index = identity_indexes[identity]
                    merged[index] = _merge_forward_value(merged[index], item)
                    continue
                identity_indexes[identity] = len(merged)
            if item not in merged:
                merged.append(copy.deepcopy(item))
        return merged
    return copy.deepcopy(updated)


def _value_pairs_at_path(current: Any, updated: Any, path: PathSpec) -> Iterable[Tuple[Any, Any]]:
    if not path:
        yield current, updated
        return
    if not isinstance(updated, dict):
        return
    current_dict = current if isinstance(current, dict) else {}
    key, *remaining = path
    if key == "*":
        for child_key, updated_child in updated.items():
            yield from _value_pairs_at_path(
                current_dict.get(child_key),
                updated_child,
                tuple(remaining),
            )
        return
    if key in updated:
        yield from _value_pairs_at_path(
            current_dict.get(key),
            updated[key],
            tuple(remaining),
        )


def apply_new_record_defaults(
    current: Dict[str, Any],
    updated: Dict[str, Any],
    attribution: Optional[Dict[str, Any]] = None,
    tool_name: str = "memory_write",
    collection_paths: Sequence[PathSpec] = DEFAULT_COLLECTION_PATHS,
    state_paths: Sequence[PathSpec] = DEFAULT_STATE_PATHS,
) -> Dict[str, Any]:
    """Annotate only records or state created/changed by this write."""
    normalized = normalize_attribution(attribution, tool_name)

    for path in collection_paths:
        for current_value, updated_value in _value_pairs_at_path(current, updated, path):
            if not isinstance(updated_value, list):
                continue
            current_ids = {
                _record_identity(item)
                for item in current_value
                if isinstance(item, dict)
            } if isinstance(current_value, list) else set()
            for item_index, item in enumerate(updated_value):
                if not isinstance(item, dict) or _record_identity(item) in current_ids:
                    continue
                updated_value[item_index] = durable_record(
                    item,
                    attribution=normalized,
                    tool_name=tool_name,
                )

    for path in state_paths:
        for current_value, updated_value in _value_pairs_at_path(current, updated, path):
            if not isinstance(updated_value, dict) or updated_value == current_value:
                continue
            for field, value in normalized.items():
                updated_value.setdefault(field, value)
            updated_value.setdefault("timestamp", datetime.now().isoformat())
            updated_value.setdefault("status", "active")
    return updated


def durable_memory_write(
    path: str | Path,
    *,
    mutator: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
    updated: Optional[Dict[str, Any]] = None,
    base: Optional[Dict[str, Any]] = None,
    attribution: Optional[Dict[str, Any]] = None,
    tool_name: str = "memory_write",
    default: Optional[Dict[str, Any]] = None,
    create_backup: bool = True,
    require_existing: bool = False,
    annotate_new: bool = True,
) -> Optional[Dict[str, Any]]:
    """Atomically mutate project memory and apply forward-only defaults."""
    if (mutator is None) == (updated is None):
        raise ValueError("Provide exactly one of mutator or updated")

    path_obj = Path(path)
    if require_existing and not path_obj.exists():
        return None

    base_provided = base is not None
    base_snapshot = copy.deepcopy(base or {})
    updated_snapshot = copy.deepcopy(updated) if updated is not None else None

    def transaction(current_value: Any) -> Dict[str, Any]:
        current = copy.deepcopy(current_value) if isinstance(current_value, dict) else {}
        if updated_snapshot is not None:
            if base_provided:
                candidate = merge_concurrent_value(base_snapshot, current, updated_snapshot)
            else:
                candidate = _merge_forward_value(current, updated_snapshot)
        else:
            candidate = mutator(copy.deepcopy(current))
            if candidate is None:
                candidate = current
        if not isinstance(candidate, dict):
            raise TypeError("Durable project memory must remain a dictionary")
        if annotate_new:
            return apply_new_record_defaults(
                current,
                candidate,
                attribution=attribution,
                tool_name=tool_name,
            )
        return candidate

    return atomic_json_update(
        str(path_obj),
        transaction,
        default=default or {},
        create_backup=create_backup,
    )
