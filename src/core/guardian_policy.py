"""
Guardian Policy - Evaluate GuardianSignals and produce GuardianVerdicts.

This module is responsible for policy evaluation only. It does NOT:
- Persist signals or verdicts (signal_audit.py does that)
- Modify Stage 7 intervention policy
- Trigger user notifications or blocks

Phase 2: Shadow mode only - verdicts are recorded but not enforced.

Supported signal patterns (Phase 2):
- concern="risk" + category="risk_destructive_op" + source="detector" + confidence=1.0
  → require_approval

All unsupported signals return silent, not a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional, Tuple
import uuid

from core.guardian_signal import GuardianSignal


# Policy version - increment when evaluation logic changes
POLICY_VERSION = "1.0.0"

# Verdict levels - separate from InterventionLevel to avoid coupling
GuardianVerdictLevel = Literal["silent", "warn", "require_approval", "block"]


@dataclass(frozen=True)
class GuardianVerdict:
    """
    Result of evaluating one or more GuardianSignals through policy.

    Attributes:
        verdict_id: Unique identifier for this verdict
        level: Policy decision (silent, warn, require_approval, block)
        reason: Human-readable explanation of why this verdict was reached
        policy_version: Version of policy rules that produced this verdict
        shadow_only: True if verdict is recorded but not enforced
        timestamp: When the verdict was created
        project_id: Project this verdict applies to
        source_signal_keys: Dedup keys of signals that led to this verdict
        evidence_summary: Brief summary of evidence for audit
    """
    verdict_id: str
    level: GuardianVerdictLevel
    reason: str
    policy_version: str
    shadow_only: bool
    timestamp: str
    project_id: str
    source_signal_keys: Tuple[str, ...]
    evidence_summary: str

    def to_dict(self) -> dict:
        """Serialize for JSONL persistence."""
        return {
            "event": "verdict_created",
            "verdict_id": self.verdict_id,
            "level": self.level,
            "reason": self.reason,
            "policy_version": self.policy_version,
            "shadow_only": self.shadow_only,
            "timestamp": self.timestamp,
            "project_id": self.project_id,
            "source_signal_keys": list(self.source_signal_keys),
            "evidence_summary": self.evidence_summary,
        }


def _generate_verdict_id() -> str:
    """Generate a unique verdict ID."""
    return f"vrd_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now().isoformat()


def _evaluate_single_signal(signal: GuardianSignal) -> Optional[GuardianVerdictLevel]:
    """
    Evaluate a single signal against Phase 2 policy rules.

    Returns the verdict level if the signal matches a known pattern,
    or None if the signal is not supported (will default to silent).
    """
    # Phase 2: Only support deterministic destructive operation signals
    if (
        signal.concern == "risk"
        and signal.category == "risk_destructive_op"
        and signal.source == "detector"
        and signal.confidence == 1.0
    ):
        return "require_approval"

    # All other signals: not supported in Phase 2
    return None


def _build_evidence_summary(signals: Tuple[GuardianSignal, ...]) -> str:
    """Build a brief evidence summary from signals."""
    if not signals:
        return ""

    parts = []
    for sig in signals[:3]:  # Limit to first 3
        file_path = sig.evidence.file_path or "unknown"
        operation = sig.evidence.operation or "unknown"
        parts.append(f"{operation}:{file_path}")

    summary = "; ".join(parts)
    if len(signals) > 3:
        summary += f" (+{len(signals) - 3} more)"

    return summary[:200]  # Limit length


def evaluate_guardian_signals(
    signals: Tuple[GuardianSignal, ...],
    project_id: str,
    source_signal_keys: Tuple[str, ...],
) -> GuardianVerdict:
    """
    Evaluate a tuple of GuardianSignals and produce a single GuardianVerdict.

    Phase 2 policy:
    - risk_destructive_op with confidence=1.0 → require_approval
    - All other signals → silent

    The verdict is always shadow_only=True in Phase 2 (not enforced).

    Args:
        signals: Tuple of signals to evaluate (typically one signal)
        project_id: Project ID for the verdict
        source_signal_keys: Dedup keys of the source signals

    Returns:
        GuardianVerdict with the policy decision
    """
    if not signals:
        return GuardianVerdict(
            verdict_id=_generate_verdict_id(),
            level="silent",
            reason="No signals to evaluate",
            policy_version=POLICY_VERSION,
            shadow_only=True,
            timestamp=_now(),
            project_id=project_id,
            source_signal_keys=source_signal_keys,
            evidence_summary="",
        )

    # Evaluate each signal and collect results
    evaluated_levels = []
    for signal in signals:
        level = _evaluate_single_signal(signal)
        if level is not None:
            evaluated_levels.append(level)

    # If no signals matched known patterns, return silent
    if not evaluated_levels:
        return GuardianVerdict(
            verdict_id=_generate_verdict_id(),
            level="silent",
            reason="No supported signal patterns matched",
            policy_version=POLICY_VERSION,
            shadow_only=True,
            timestamp=_now(),
            project_id=project_id,
            source_signal_keys=source_signal_keys,
            evidence_summary=_build_evidence_summary(signals),
        )

    # For Phase 2, we only have require_approval, but prepare for escalation
    # Priority: block > require_approval > warn > silent
    level_priority = {"block": 4, "require_approval": 3, "warn": 2, "silent": 1}
    highest_level = max(evaluated_levels, key=lambda l: level_priority.get(l, 0))

    # Build reason based on what triggered
    if highest_level == "require_approval":
        reason = "High-confidence destructive operation requires approval"
    elif highest_level == "block":
        reason = "Operation blocked by policy"
    elif highest_level == "warn":
        reason = "Policy warning triggered"
    else:
        reason = "No action required"

    return GuardianVerdict(
        verdict_id=_generate_verdict_id(),
        level=highest_level,
        reason=reason,
        policy_version=POLICY_VERSION,
        shadow_only=True,
        timestamp=_now(),
        project_id=project_id,
        source_signal_keys=source_signal_keys,
        evidence_summary=_build_evidence_summary(signals),
    )
