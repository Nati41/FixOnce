"""
Stage 8 foundation: agent-aware enforcement bridge.

Stage 7 owns policy evaluation.
Stage 8 consumes those results and produces an agent-aware verdict without
changing any UX or runtime behavior yet.
"""

from __future__ import annotations

from typing import Dict

from core.agent_audit import record_agent_audit
from core.agent_context import AgentContext
from core.intervention_policy import InterventionContext, evaluate_intervention


_SEVERITY_ORDER: Dict[str, int] = {"silent": 0, "warn": 1, "block": 2}


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
    gate_results = evaluate_intervention(intervention_ctx)

    for result in gate_results:
        if _SEVERITY_ORDER[result.level] > _SEVERITY_ORDER[verdict]:
            verdict = result.level

        if result.level != "silent":
            record_agent_audit(
                actor_name=agent_ctx.actor_name,
                actor_source=agent_ctx.actor_source,
                gate=result.gate,
                verdict=result.level,
                metadata={
                    "tool_name": agent_ctx.tool_name,
                    "intent": agent_ctx.intent,
                    "session_id": agent_ctx.session_id,
                    "project_id": agent_ctx.project_id,
                    "actor_confidence": agent_ctx.actor_confidence,
                },
            )

    return verdict
