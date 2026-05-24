"""
Stage 8 foundation: agent identity model.

This is the boundary between agent-aware metadata and Stage 7 policy inputs.
It does not enforce anything by itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentContext:
    actor_name: str
    actor_source: str
    actor_confidence: float
    tool_name: str
    intent: str
    session_id: str
    project_id: str
