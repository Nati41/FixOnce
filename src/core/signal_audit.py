"""
Guardian Signal and Verdict audit trail with in-memory and persistent storage.

Shadow-mode only: signals and verdicts are recorded for audit purposes without
triggering user notifications, approvals, or blocks.

Storage:
- In-memory bounded deque for fast recent inspection
- JSONL append-only file for persistent audit trail
- Single event stream with both signal_created and verdict_created events

Deduplication:
- Signals: project_id + normalized_path + operation + time_bucket
- Verdicts: source_signal_key + policy_version
"""

from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from config import USER_DATA_DIR
from core.guardian_signal import GuardianEvidence, GuardianSignal

if TYPE_CHECKING:
    from core.guardian_policy import GuardianVerdict


# Persistent storage - follows mcp_session_health.py pattern
SIGNAL_LOG_FILE = USER_DATA_DIR / "logs" / "guardian_signals.jsonl"

# In-memory bounded storage for signals
_SIGNAL_AUDIT_LOCK = Lock()
_SIGNAL_AUDIT_LOG: Deque[GuardianSignal] = deque(maxlen=500)

# In-memory bounded storage for verdicts
_VERDICT_AUDIT_LOCK = Lock()
_VERDICT_AUDIT_LOG: Deque["GuardianVerdict"] = deque(maxlen=500)

# Signal deduplication state
_DEDUP_LOCK = Lock()
_DEDUP_SEEN: Set[str] = set()
_DEDUP_MAX_SIZE = 1000
_DEDUP_TIME_BUCKET_SECONDS = 5

# Verdict deduplication state (signal_key + policy_version)
_VERDICT_DEDUP_LOCK = Lock()
_VERDICT_DEDUP_SEEN: Set[str] = set()
_VERDICT_DEDUP_MAX_SIZE = 1000


def _now() -> str:
    return datetime.now().isoformat()


def _time_bucket() -> str:
    """Return a time bucket string for deduplication (5-second windows)."""
    ts = int(datetime.now().timestamp())
    bucket = ts - (ts % _DEDUP_TIME_BUCKET_SECONDS)
    return str(bucket)


def normalize_path(file_path: str) -> str:
    """
    Normalize file path for consistent deduplication across platforms.

    - Converts backslashes to forward slashes
    - Resolves .. and . components
    - Lowercases on Windows for case-insensitive matching
    - Strips trailing slashes
    """
    if not file_path:
        return ""

    # First convert all backslashes to forward slashes
    normalized = file_path.replace("\\", "/")

    # Try to resolve if it's a valid path on this system
    try:
        # Only resolve if the path exists or is absolute
        path_obj = Path(normalized)
        if path_obj.is_absolute() or path_obj.exists():
            normalized = str(path_obj.resolve())
            # Convert back to forward slashes after resolve
            normalized = normalized.replace("\\", "/")
    except (OSError, ValueError):
        pass

    # Case-insensitive on Windows
    if os.name == "nt":
        normalized = normalized.lower()

    return normalized.rstrip("/")


def _make_dedup_key(project_id: str, file_path: str, operation: str) -> str:
    """
    Create a stable deduplication key.

    Format: project_id|normalized_path|operation|time_bucket
    """
    normalized = normalize_path(file_path)
    bucket = _time_bucket()
    return f"{project_id}|{normalized}|{operation}|{bucket}"


def _is_duplicate(dedup_key: str) -> bool:
    """Check if this event was already seen in the current time bucket."""
    with _DEDUP_LOCK:
        if dedup_key in _DEDUP_SEEN:
            return True

        # Prune old entries if too many (simple LRU-ish cleanup)
        if len(_DEDUP_SEEN) >= _DEDUP_MAX_SIZE:
            # Remove roughly half the entries (oldest buckets first)
            # Since we can't track insertion order cheaply, just clear
            _DEDUP_SEEN.clear()

        _DEDUP_SEEN.add(dedup_key)
        return False


def _persist_signal(signal: GuardianSignal, project_id: str, dedup_key: str) -> bool:
    """
    Append signal to JSONL audit file. Silent failure.

    Returns True if persisted successfully, False otherwise.
    """
    try:
        SIGNAL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Extract evidence fields for flat structure
        evidence = signal.evidence

        payload = {
            "event": "signal_created",
            "timestamp": signal.timestamp,
            "project_id": project_id,
            "file_path": evidence.file_path or "",
            "operation": evidence.operation or "",
            "concern": signal.concern,
            "category": signal.category,
            "source": signal.source,
            "severity": signal.severity,
            "confidence": signal.confidence,
            "reason": signal.reason,
            "dedup_key": dedup_key,
        }

        with SIGNAL_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

        return True
    except Exception:
        # Silent failure - must not break caller
        return False


def _make_verdict_dedup_key(source_signal_key: str, policy_version: str) -> str:
    """Create a deduplication key for verdict."""
    return f"{source_signal_key}|{policy_version}"


def _is_verdict_duplicate(verdict_dedup_key: str) -> bool:
    """Check if this verdict was already recorded."""
    with _VERDICT_DEDUP_LOCK:
        if verdict_dedup_key in _VERDICT_DEDUP_SEEN:
            return True

        if len(_VERDICT_DEDUP_SEEN) >= _VERDICT_DEDUP_MAX_SIZE:
            _VERDICT_DEDUP_SEEN.clear()

        _VERDICT_DEDUP_SEEN.add(verdict_dedup_key)
        return False


def _persist_verdict(verdict: "GuardianVerdict") -> bool:
    """
    Append verdict to JSONL audit file. Silent failure.

    Returns True if persisted successfully, False otherwise.
    """
    try:
        SIGNAL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        payload = verdict.to_dict()

        with SIGNAL_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

        return True
    except Exception:
        # Silent failure - must not break caller
        return False


def record_verdict_audit(
    verdict: "GuardianVerdict",
) -> bool:
    """
    Record a GuardianVerdict in shadow mode.

    - Deduplicates using source_signal_key + policy_version
    - Stores in bounded in-memory deque
    - Persists to JSONL file
    - Silent failure on persistence errors

    Returns True if verdict was recorded (not a duplicate), False if deduplicated.
    """
    # Deduplicate by first source signal key + policy version
    if not verdict.source_signal_keys:
        return False

    verdict_dedup_key = _make_verdict_dedup_key(
        verdict.source_signal_keys[0],
        verdict.policy_version,
    )

    if _is_verdict_duplicate(verdict_dedup_key):
        return False

    # Store in memory
    with _VERDICT_AUDIT_LOCK:
        _VERDICT_AUDIT_LOG.append(verdict)

    # Persist to JSONL (silent failure)
    _persist_verdict(verdict)

    return True


def record_signal_audit(
    signal: GuardianSignal,
    project_id: str = "",
    evaluate_policy: bool = True,
) -> Tuple[bool, Optional[str]]:
    """
    Record a GuardianSignal in shadow mode and optionally evaluate policy.

    - Deduplicates using project_id + normalized_path + operation + time_bucket
    - Stores in bounded in-memory deque
    - Persists to JSONL file
    - If evaluate_policy=True, also produces and records a shadow verdict
    - Silent failure on persistence errors

    Returns (recorded: bool, dedup_key: Optional[str]).
    recorded is True if signal was recorded (not a duplicate).
    dedup_key is returned for verdict deduplication.
    """
    # Extract file path and operation from evidence
    file_path = signal.evidence.file_path or ""
    operation = signal.evidence.operation or ""

    # Check for duplicate
    dedup_key = _make_dedup_key(project_id, file_path, operation)
    if _is_duplicate(dedup_key):
        return False, None

    # Store in memory
    with _SIGNAL_AUDIT_LOCK:
        _SIGNAL_AUDIT_LOG.append(signal)

    # Persist to JSONL (silent failure)
    _persist_signal(signal, project_id, dedup_key)

    # Shadow policy evaluation
    if evaluate_policy:
        try:
            from core.guardian_policy import evaluate_guardian_signals

            verdict = evaluate_guardian_signals(
                signals=(signal,),
                project_id=project_id,
                source_signal_keys=(dedup_key,),
            )

            # Only record non-silent verdicts (or all for debugging)
            # For now, record all verdicts for full audit trail
            record_verdict_audit(verdict)
        except Exception:
            # Silent failure - must not break signal recording
            pass

    return True, dedup_key


def get_signal_audit(limit: int = 50) -> List[Dict[str, Any]]:
    """Return the most recent signal audit entries as dictionaries."""
    with _SIGNAL_AUDIT_LOCK:
        entries = list(_SIGNAL_AUDIT_LOG)[-max(0, limit):]
    return [e.to_dict() for e in entries]


def get_verdict_audit(limit: int = 50) -> List[Dict[str, Any]]:
    """Return the most recent verdict audit entries as dictionaries."""
    with _VERDICT_AUDIT_LOCK:
        entries = list(_VERDICT_AUDIT_LOG)[-max(0, limit):]
    return [e.to_dict() for e in entries]


def get_audit_from_file(
    limit: int = 100,
    event_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Read recent entries from the persistent JSONL file.

    Args:
        limit: Maximum entries to return
        event_type: Filter by event type (signal_created, verdict_created, or None for all)

    Returns entries in reverse chronological order (newest first).
    """
    try:
        if not SIGNAL_LOG_FILE.exists():
            return []

        lines = SIGNAL_LOG_FILE.read_text(encoding="utf-8").strip().split("\n")

        entries = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if event_type is None or entry.get("event") == event_type:
                    entries.append(entry)
                    if len(entries) >= limit:
                        break
            except json.JSONDecodeError:
                continue

        return entries
    except Exception:
        return []


def get_signal_audit_from_file(limit: int = 100) -> List[Dict[str, Any]]:
    """Read recent signal entries from the persistent JSONL file."""
    return get_audit_from_file(limit=limit, event_type="signal_created")


def get_verdict_audit_from_file(limit: int = 100) -> List[Dict[str, Any]]:
    """Read recent verdict entries from the persistent JSONL file."""
    return get_audit_from_file(limit=limit, event_type="verdict_created")


def clear_signal_audit_memory() -> None:
    """Clear in-memory signal and verdict audit (for testing). Does NOT clear persistent file."""
    with _SIGNAL_AUDIT_LOCK:
        _SIGNAL_AUDIT_LOG.clear()
    with _VERDICT_AUDIT_LOCK:
        _VERDICT_AUDIT_LOG.clear()
    with _DEDUP_LOCK:
        _DEDUP_SEEN.clear()
    with _VERDICT_DEDUP_LOCK:
        _VERDICT_DEDUP_SEEN.clear()


def produce_destructive_signal(
    file_path: str,
    operation: str,
    project_id: str = "",
) -> Optional[GuardianSignal]:
    """
    Produce a GuardianSignal for a confirmed destructive file operation.

    Only call this for deterministic, confirmed operations (delete, truncate).
    Do NOT infer destructive intent from vague text.

    Also evaluates shadow policy and records the verdict.

    Returns the signal if recorded, None if deduplicated.
    """
    if operation not in {"delete", "truncate"}:
        return None

    evidence = GuardianEvidence(
        file_path=file_path,
        operation=operation,
    )

    signal = GuardianSignal(
        concern="risk",
        source="detector",
        category="risk_destructive_op",
        severity="high",
        confidence=1.0,
        reason=f"A project file was {operation}d",
        evidence=evidence,
    )

    recorded, _ = record_signal_audit(signal, project_id=project_id, evaluate_policy=True)
    return signal if recorded else None
