"""
Intervention Policy Layer for Stage 7.

This module is intentionally isolated from the MCP server. It provides a
central policy model for deciding when FixOnce should stay silent, warn, or
block, without changing any existing runtime behavior yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


InterventionLevel = Literal["silent", "warn", "block"]


@dataclass(frozen=True)
class InterventionGateResult:
    """Single gate evaluation result."""

    gate: str
    level: InterventionLevel
    reason: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggested_action: str = ""


@dataclass(frozen=True)
class InterventionContext:
    """Normalized context for intervention policy evaluation."""

    tool_name: str = ""
    live_errors: int = 0
    auto_fix_ready: bool = False
    decision_conflict_severity: str = ""
    stable_component_touched: bool = False
    blocked_components_relevant: int = 0
    lock_violation: bool = False
    risky_change: bool = False
    repeat_bug_detected: bool = False
    similar_past_solution_found: bool = False
    task_completed: bool = False
    significant_work_completed: bool = False
    sync_recorded: bool = False
    component_changed: bool = False
    component_status_updated: bool = False
    bug_fix_completed: bool = False
    fo_solved_called: bool = False
    completion_gate_required: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


def evaluate_error_gate(ctx: InterventionContext) -> InterventionGateResult:
    """Warn on live errors, block when auto-fix is ready but not being applied."""
    if ctx.auto_fix_ready and ctx.tool_name != "fo_apply":
        return InterventionGateResult(
            gate="error_gate",
            level="block",
            reason="Auto-fix is ready and must be applied before continuing.",
            evidence={"tool_name": ctx.tool_name, "auto_fix_ready": True},
            suggested_action="Call fo_apply()",
        )

    if ctx.live_errors > 0:
        return InterventionGateResult(
            gate="error_gate",
            level="warn",
            reason="Live errors are present.",
            evidence={"live_errors": ctx.live_errors},
            suggested_action="Review fo_errors()",
        )

    return InterventionGateResult(gate="error_gate", level="silent")


def evaluate_decision_conflict_gate(ctx: InterventionContext) -> InterventionGateResult:
    """Block on severe decision conflicts, warn on medium conflicts."""
    severity = (ctx.decision_conflict_severity or "").lower()

    if severity in {"high", "severe", "critical"}:
        return InterventionGateResult(
            gate="decision_conflict_gate",
            level="block",
            reason="A severe conflict with an existing decision was detected.",
            evidence={"severity": severity},
            suggested_action="Resolve or supersede the existing decision first.",
        )

    if severity in {"medium", "moderate", "low"}:
        return InterventionGateResult(
            gate="decision_conflict_gate",
            level="warn",
            reason="A potential conflict with an existing decision was detected.",
            evidence={"severity": severity},
            suggested_action="Review the existing decision for consistency.",
        )

    return InterventionGateResult(gate="decision_conflict_gate", level="silent")


def evaluate_risk_gate(ctx: InterventionContext) -> InterventionGateResult:
    """Block on lock violations, warn on stable/blocked/risky operations."""
    if ctx.lock_violation:
        return InterventionGateResult(
            gate="risk_gate",
            level="block",
            reason="The operation violates a lock or illegal state guard.",
            evidence={"lock_violation": True},
            suggested_action="Resolve the lock state before continuing.",
        )

    if ctx.blocked_components_relevant > 0:
        return InterventionGateResult(
            gate="risk_gate",
            level="warn",
            reason="Blocked components may affect the requested work.",
            evidence={"blocked_components_relevant": ctx.blocked_components_relevant},
            suggested_action="Review blocked components before proceeding.",
        )

    if ctx.risky_change:
        return InterventionGateResult(
            gate="risk_gate",
            level="warn",
            reason="A risky change was detected.",
            evidence={"risky_change": True},
            suggested_action="Review impact before proceeding.",
        )

    if ctx.stable_component_touched:
        return InterventionGateResult(
            gate="risk_gate",
            level="warn",
            reason="A stable component is being modified.",
            evidence={"stable_component_touched": True},
            suggested_action="Consider rollback/checkpoint implications.",
        )

    return InterventionGateResult(gate="risk_gate", level="silent")


def evaluate_repeat_bug_gate(ctx: InterventionContext) -> InterventionGateResult:
    """Warn when a known bug pattern or prior solution match is detected."""
    if ctx.repeat_bug_detected or ctx.similar_past_solution_found:
        return InterventionGateResult(
            gate="repeat_bug_gate",
            level="warn",
            reason="A similar bug appears to have been seen before.",
            evidence={
                "repeat_bug_detected": ctx.repeat_bug_detected,
                "similar_past_solution_found": ctx.similar_past_solution_found,
            },
            suggested_action="Reuse or review the previous solution first.",
        )

    return InterventionGateResult(gate="repeat_bug_gate", level="silent")


def evaluate_completion_gate(ctx: InterventionContext) -> InterventionGateResult:
    """Warn on missing completion bookkeeping. Stage 7 never blocks here."""
    if ctx.bug_fix_completed and not ctx.fo_solved_called:
        return InterventionGateResult(
            gate="completion_gate",
            level="warn",
            reason="A bug fix appears complete but fo_solved() was not recorded.",
            evidence={
                "bug_fix_completed": True,
                "fo_solved_called": False,
            },
            suggested_action="Call fo_solved()",
        )

    if ctx.significant_work_completed and not ctx.sync_recorded:
        return InterventionGateResult(
            gate="completion_gate",
            level="warn",
            reason="Significant work appears complete but fo_sync() was not recorded.",
            evidence={
                "significant_work_completed": True,
                "sync_recorded": False,
            },
            suggested_action="Call fo_sync()",
        )

    if ctx.component_changed and not ctx.component_status_updated:
        return InterventionGateResult(
            gate="completion_gate",
            level="warn",
            reason="Component work appears complete but update_component_status() was not recorded.",
            evidence={
                "component_changed": True,
                "component_status_updated": False,
            },
            suggested_action="Call update_component_status()",
        )

    if ctx.task_completed and ctx.completion_gate_required:
        return InterventionGateResult(
            gate="completion_gate",
            level="warn",
            reason="Task completion should pass a completion gate check.",
            evidence={
                "task_completed": True,
                "completion_gate_required": True,
            },
            suggested_action="Run the required completion checks.",
        )

    return InterventionGateResult(gate="completion_gate", level="silent")


def evaluate_intervention(ctx: InterventionContext) -> List[InterventionGateResult]:
    """Evaluate all Stage 7 intervention gates for a single context."""
    return [
        evaluate_error_gate(ctx),
        evaluate_decision_conflict_gate(ctx),
        evaluate_risk_gate(ctx),
        evaluate_repeat_bug_gate(ctx),
        evaluate_completion_gate(ctx),
    ]
