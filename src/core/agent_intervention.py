"""
Stage 8 foundation: agent-aware enforcement bridge.

Stage 7 owns policy evaluation.
Stage 8 consumes those results and produces an agent-aware verdict without
changing any UX or runtime behavior yet.
"""

from __future__ import annotations

from typing import Dict, List

from core.agent_audit import record_agent_audit
from core.agent_context import AgentContext
from core.intervention_policy import (
    InterventionContext,
    InterventionGateResult,
    evaluate_intervention,
)


_SEVERITY_ORDER: Dict[str, int] = {"silent": 0, "warn": 1, "block": 2}


def _resolve_gate_results(
    intervention_ctx: InterventionContext,
) -> List[InterventionGateResult]:
    """Reuse precomputed gate results when runtime already evaluated a gate."""
    gate_results = intervention_ctx.extra.get("gate_results")
    if gate_results:
        return list(gate_results)
    return evaluate_intervention(intervention_ctx)


def evaluate_agent_intervention(
    agent_ctx: AgentContext,
    intervention_ctx: InterventionContext,
) -> str:
    """
    Bridge Stage 7 policy evaluation into an agent-aware verdict.

    This does not perform any runtime enforcement. It only aggregates the
    existing gate results and records internal audit entries.
    """
    verdict = "silent"
    gate_results = _resolve_gate_results(intervention_ctx)

    for result in gate_results:
        if _SEVERITY_ORDER[result.level] > _SEVERITY_ORDER[verdict]:
            verdict = result.level

        record_agent_audit(
            actor_name=agent_ctx.actor_name,
            actor_source=agent_ctx.actor_source,
            actor_confidence=agent_ctx.actor_confidence,
            tool_name=agent_ctx.tool_name,
            intent=agent_ctx.intent,
            gate=result.gate,
            verdict=result.level,
            evidence=result.evidence,
            project_id=agent_ctx.project_id,
            session_id=agent_ctx.session_id,
            flow_classification=agent_ctx.flow_classification,
            metadata={
                "intent_detail": agent_ctx.intent_detail,
                "reason": result.reason,
                "evidence": result.evidence,
                "suggested_action": result.suggested_action,
            },
        )

    return verdict
