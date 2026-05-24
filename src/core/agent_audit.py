"""
Internal audit trail for Stage 8 agent-aware intervention decisions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any, Deque, Dict, List


@dataclass(frozen=True)
class AgentAuditEntry:
    actor_name: str
    actor_source: str
    gate: str
    verdict: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


_AGENT_AUDIT_LOCK = Lock()
_AGENT_AUDIT_LOG: Deque[AgentAuditEntry] = deque(maxlen=500)


def record_agent_audit(
    actor_name: str,
    actor_source: str,
    gate: str,
    verdict: str,
    metadata: Dict[str, Any] | None = None,
) -> AgentAuditEntry:
    """Append an agent-aware intervention record to the bounded audit trail."""
    entry = AgentAuditEntry(
        actor_name=actor_name,
        actor_source=actor_source,
        gate=gate,
        verdict=verdict,
        metadata=dict(metadata or {}),
    )
    with _AGENT_AUDIT_LOCK:
        _AGENT_AUDIT_LOG.append(entry)
    return entry


def get_agent_audit(limit: int = 50) -> List[Dict[str, Any]]:
    """Return the most recent agent audit entries as dictionaries."""
    with _AGENT_AUDIT_LOCK:
        entries = list(_AGENT_AUDIT_LOG)[-max(0, limit):]
    return [asdict(entry) for entry in entries]


def clear_agent_audit() -> None:
    """Clear all in-memory agent audit records."""
    with _AGENT_AUDIT_LOCK:
        _AGENT_AUDIT_LOG.clear()
