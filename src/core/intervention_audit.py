"""
Internal audit trail for Stage 7 intervention policy.

This module is intentionally non-UX-facing. It stores bounded in-memory
records so FixOnce can inspect which gate fired, what verdict was produced,
and what evidence was used.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any, Deque, Dict, List


@dataclass(frozen=True)
class InterventionAuditEntry:
    gate: str
    verdict: str
    reason: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggested_action: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


_AUDIT_LOCK = Lock()
_AUDIT_LOG: Deque[InterventionAuditEntry] = deque(maxlen=500)


def record_intervention_audit(
    gate: str,
    verdict: str,
    reason: str = "",
    evidence: Dict[str, Any] | None = None,
    suggested_action: str = "",
) -> InterventionAuditEntry:
    """Append a gate evaluation record to the bounded audit trail."""
    entry = InterventionAuditEntry(
        gate=gate,
        verdict=verdict,
        reason=reason,
        evidence=dict(evidence or {}),
        suggested_action=suggested_action,
    )
    with _AUDIT_LOCK:
        _AUDIT_LOG.append(entry)
    return entry


def get_intervention_audit(limit: int = 50) -> List[Dict[str, Any]]:
    """Return the most recent intervention audit entries as dictionaries."""
    with _AUDIT_LOCK:
        entries = list(_AUDIT_LOG)[-max(0, limit):]
    return [asdict(entry) for entry in entries]


def clear_intervention_audit() -> None:
    """Clear all in-memory intervention audit records."""
    with _AUDIT_LOCK:
        _AUDIT_LOG.clear()
