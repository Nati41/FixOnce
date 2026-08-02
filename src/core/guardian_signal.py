"""
Guardian Signal - Structured signals for Guardian intervention decisions.

This module defines the data contracts for signals that inform the Guardian's
intervention policy. Signals can come from various sources (agent, LLM, detector)
and represent different concerns (risk, conflict, opportunity, compliance, error).

Architecture:
- GuardianSignal is the unit of detection output
- InterventionContext.guardian_signals collects signals for evaluation
- Aggregation and policy evaluation happen in separate layers (not here)

Note on severity:
  Severity represents the INTENSITY OF INTERVENTION needed from the Guardian,
  NOT the "severity of risk" or "severity of error". For example:
  - An opportunity signal with severity="high" means the Guardian should
    strongly encourage using the available solution, not that something is wrong.
  - A compliance signal with severity="medium" means a gentle reminder is needed.
  This distinction is critical for non-risk concerns like opportunity and compliance.

Phase 1: Infrastructure only - no producers, no aggregation, no policy changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional, Tuple
import json


# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

# Who detected or raised the signal
GuardianSource = Literal[
    "agent",      # The AI agent explicitly declared this
    "llm",        # LLM evaluation determined this
    "detector",   # Automated detection (pattern, heuristic, rule)
    "user",       # User explicitly flagged this
]

# What type of concern this signal represents
GuardianConcern = Literal[
    "error",       # Something is broken NOW (live errors, failed state)
    "conflict",    # This contradicts existing knowledge (decisions, patterns)
    "risk",        # This action might cause damage (destructive, protected area)
    "opportunity", # There's knowledge worth reusing (past solution, similar bug)
    "compliance",  # Process/bookkeeping is required (sync, fo_solved)
]

# Specific category within each concern - closed set, extend gradually
# Format: concern_specific_category
GuardianCategory = Literal[
    # Error categories
    "error_live_browser",        # Live browser errors detected
    "error_auto_fix_ready",      # Auto-fix is available and should be applied
    "error_build_failure",       # Build or compilation failed

    # Conflict categories
    "conflict_decision",         # Conflicts with existing decision
    "conflict_avoid_pattern",    # Matches an avoid pattern
    "conflict_semantic",         # Semantic conflict detected by LLM

    # Risk categories
    "risk_destructive_op",       # Delete, overwrite, truncate
    "risk_protected_area",       # Modifying protected path/component
    "risk_unknown_impact",       # Can't predict the impact
    "risk_agent_declared",       # Agent declared this is risky

    # Opportunity categories
    "opportunity_past_solution", # Similar bug was solved before
    "opportunity_reuse",         # Knowledge can be reused

    # Compliance categories
    "compliance_sync_needed",    # fo_sync should be called
    "compliance_solved_needed",  # fo_solved should be called
    "compliance_review_needed",  # Review/approval is pending
]

# Intensity of intervention needed from the Guardian
# NOT "severity of risk" - see module docstring
GuardianSeverity = Literal["low", "medium", "high", "critical"]


# =============================================================================
# EVIDENCE
# =============================================================================

@dataclass(frozen=True)
class GuardianEvidence:
    """
    Structured evidence supporting a GuardianSignal.

    All fields are optional - include only what's relevant.
    This structure is designed for stable serialization and audit.
    """
    # Location context
    file_path: Optional[str] = None
    line_number: Optional[int] = None

    # Action context
    operation: Optional[str] = None  # read, write, delete, etc.
    tool_name: Optional[str] = None

    # Knowledge context
    matched_pattern: Optional[str] = None      # Pattern that matched
    related_decision_id: Optional[str] = None  # Related decision ID
    related_solution_id: Optional[str] = None  # Related solution ID

    # Detection context
    similarity_score: Optional[float] = None   # 0.0-1.0 if similarity-based
    context_snippet: Optional[str] = None      # Max 200 chars of context

    def to_dict(self) -> dict:
        """Serialize to dict, excluding None values."""
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "GuardianEvidence":
        """Deserialize from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "GuardianEvidence":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


# =============================================================================
# SIGNAL
# =============================================================================

@dataclass(frozen=True)
class GuardianSignal:
    """
    A single signal indicating the Guardian should consider intervening.

    Signals are immutable facts produced by detection layers. They do NOT
    determine the intervention level directly - that's the job of aggregation
    and policy layers.

    Attributes:
        concern: What type of concern this represents (error, conflict, risk, etc.)
        source: Who/what detected this signal
        category: Specific category within the concern (closed set)
        severity: Intensity of intervention needed (NOT severity of risk)
        confidence: How certain is this detection (0.0-1.0)
        reason: Human-readable explanation
        evidence: Structured supporting data
        timestamp: When the signal was created
    """
    concern: GuardianConcern
    source: GuardianSource
    category: GuardianCategory
    severity: GuardianSeverity
    confidence: float  # 0.0-1.0
    reason: str
    evidence: GuardianEvidence = field(default_factory=GuardianEvidence)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        """Validate signal on creation."""
        # Validate confidence range
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got {self.confidence}")

        # Validate category matches concern
        if not self.category.startswith(self.concern + "_"):
            raise ValueError(
                f"category '{self.category}' must start with concern '{self.concern}_'"
            )

        # Validate reason is not empty
        if not self.reason.strip():
            raise ValueError("reason cannot be empty")

    def to_dict(self) -> dict:
        """Serialize to dict for JSON/audit."""
        return {
            "concern": self.concern,
            "source": self.source,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence.to_dict(),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GuardianSignal":
        """Deserialize from dict."""
        evidence_data = data.get("evidence", {})
        evidence = GuardianEvidence.from_dict(evidence_data) if evidence_data else GuardianEvidence()
        return cls(
            concern=data["concern"],
            source=data["source"],
            category=data["category"],
            severity=data["severity"],
            confidence=data["confidence"],
            reason=data["reason"],
            evidence=evidence,
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "GuardianSignal":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


# =============================================================================
# HELPERS
# =============================================================================

def validate_category_for_concern(category: GuardianCategory, concern: GuardianConcern) -> bool:
    """Check if a category is valid for a given concern."""
    return category.startswith(concern + "_")


def get_categories_for_concern(concern: GuardianConcern) -> Tuple[GuardianCategory, ...]:
    """Get all valid categories for a concern."""
    prefix = concern + "_"
    # Get all values from GuardianCategory type
    all_categories = GuardianCategory.__args__  # type: ignore
    return tuple(c for c in all_categories if c.startswith(prefix))
