"""Durable lifecycle helpers for decision conflicts."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.durable_memory import normalize_attribution


TERMINAL_CONFLICT_LIMIT = 200
VALID_CONFLICT_STATUSES = {"open", "resolved", "superseded"}


def _normalize_text(value: Any) -> str:
    return " ".join(re.findall(r"\w+", str(value or "").lower()))


def decision_fingerprint(decision: Any, reason: str = "") -> str:
    """Return a stable content fingerprint for a decision."""
    if isinstance(decision, dict):
        text = decision.get("decision", "")
        reason = decision.get("reason", reason)
    else:
        text = decision
    payload = f"{_normalize_text(text)}|{_normalize_text(reason)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def conflict_id(
    existing_decision: Dict[str, Any],
    proposed_decision: Dict[str, Any],
    conflict_type: str,
) -> str:
    payload = "|".join((
        decision_fingerprint(existing_decision),
        decision_fingerprint(proposed_decision),
        str(conflict_type or "CONFLICT").upper(),
    ))
    return f"conflict_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _decision_side(
    decision: str,
    reason: str = "",
    actor: str = "unknown",
    actor_source: str = "none",
    timestamp: str = "",
) -> Dict[str, Any]:
    return {
        "decision": decision or "",
        "reason": reason or "",
        "fingerprint": decision_fingerprint(decision, reason),
        "actor": actor or "unknown",
        "actor_source": actor_source or "none",
        "timestamp": timestamp or "",
    }


def bound_conflicts(
    conflicts: Iterable[Dict[str, Any]],
    terminal_limit: int = TERMINAL_CONFLICT_LIMIT,
) -> List[Dict[str, Any]]:
    """Keep every open conflict and only the newest bounded terminal records."""
    items = [item for item in conflicts if isinstance(item, dict)]
    open_items = [item for item in items if item.get("status", "open") == "open"]
    terminal = [item for item in items if item.get("status", "open") != "open"]
    terminal.sort(
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )
    return open_items + terminal[:terminal_limit]


def upsert_decision_conflicts(
    memory: Dict[str, Any],
    evidence: Iterable[Dict[str, Any]],
    proposed_text: str,
    proposed_reason: str,
    attribution: Optional[Dict[str, Any]] = None,
    now: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Create or refresh durable open conflict records."""
    timestamp = now or datetime.now().isoformat()
    provenance = normalize_attribution(attribution, "fo_decide")
    proposed = _decision_side(
        proposed_text,
        proposed_reason,
        provenance["actor"],
        provenance["actor_source"],
        timestamp,
    )
    records = list(memory.get("decision_conflicts", []))
    indexes = {
        item.get("id"): index
        for index, item in enumerate(records)
        if isinstance(item, dict) and item.get("id")
    }
    touched_ids: List[str] = []

    for item in evidence:
        if not isinstance(item, dict):
            continue
        existing = _decision_side(
            item.get("existing_decision", ""),
            item.get("existing_reason", ""),
            item.get("existing_actor", "unknown"),
            item.get("existing_actor_source", "none"),
            item.get("timestamp", ""),
        )
        record_id = conflict_id(existing, proposed, item.get("type", "CONFLICT"))
        touched_ids.append(record_id)
        if record_id in indexes:
            record = records[indexes[record_id]]
            record["last_seen"] = timestamp
            record["updated_at"] = timestamp
            record["seen_count"] = int(record.get("seen_count", 1) or 1) + 1
            if record.get("status") not in VALID_CONFLICT_STATUSES:
                record["status"] = "open"
            continue

        record = {
            "id": record_id,
            "status": "open",
            "type": item.get("type", "CONFLICT"),
            "severity": str(item.get("severity", "MEDIUM")).upper(),
            "existing_decision": existing,
            "proposed_decision": proposed,
            "topics": list(item.get("topics", [])),
            "message": item.get("message", ""),
            "created_at": timestamp,
            "updated_at": timestamp,
            "last_seen": timestamp,
            "seen_count": 1,
            "resolution": None,
            **provenance,
        }
        records.append(record)
        indexes[record_id] = len(records) - 1

    memory["decision_conflicts"] = bound_conflicts(records)
    return memory, touched_ids


def resolve_decision_conflicts(
    memory: Dict[str, Any],
    *,
    status: str,
    action: str,
    reason: str,
    attribution: Optional[Dict[str, Any]] = None,
    conflict_ids: Optional[Iterable[str]] = None,
    existing_decision_text: str = "",
    now: Optional[str] = None,
) -> Tuple[Dict[str, Any], int]:
    """Resolve matching open conflicts and preserve resolution provenance."""
    if status not in {"resolved", "superseded"}:
        raise ValueError("Conflict status must be resolved or superseded")

    timestamp = now or datetime.now().isoformat()
    provenance = normalize_attribution(attribution, "fo_decide")
    wanted_ids = set(conflict_ids or [])
    normalized_existing = _normalize_text(existing_decision_text)
    resolved = 0

    for record in memory.get("decision_conflicts", []):
        if not isinstance(record, dict) or record.get("status", "open") != "open":
            continue
        id_match = bool(wanted_ids and record.get("id") in wanted_ids)
        existing_text = record.get("existing_decision", {}).get("decision", "")
        normalized_record_existing = _normalize_text(existing_text)
        text_match = bool(
            normalized_existing
            and (
                normalized_record_existing == normalized_existing
                or normalized_existing in normalized_record_existing
                or normalized_record_existing in normalized_existing
            )
        )
        if not id_match and not text_match:
            continue
        record["status"] = status
        record["updated_at"] = timestamp
        record["resolution"] = {
            "action": action,
            "reason": reason or "",
            "actor": provenance["actor"],
            "actor_source": provenance["actor_source"],
            "actor_confidence": provenance["actor_confidence"],
            "session_id": provenance["session_id"],
            "tool_name": provenance["tool_name"],
            "timestamp": timestamp,
        }
        resolved += 1

    memory["decision_conflicts"] = bound_conflicts(
        memory.get("decision_conflicts", [])
    )
    return memory, resolved
