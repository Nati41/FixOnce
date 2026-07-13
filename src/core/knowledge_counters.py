"""Shared live project knowledge counters for UI/session display."""

from typing import Any, Dict


def get_live_project_counters(memory: Dict[str, Any] | None) -> Dict[str, int]:
    """Return counters from live project memory, not committed/exported files."""
    memory = memory or {}
    # Count only active (non-superseded) decisions and solutions
    decisions = [d for d in (memory.get("decisions", []) or []) if not d.get("superseded")]
    solved = [s for s in (memory.get("debug_sessions", []) or []) if not s.get("superseded")]
    return {
        "decisions": len(decisions),
        "solved": len(solved),
        "avoid": len(memory.get("avoid", []) or []),
    }


def format_project_knowledge_line(counters: Dict[str, int]) -> str:
    """Format the compact Project Knowledge display line."""
    return (
        f"📊 Project Knowledge: {counters.get('decisions', 0)} Decisions · "
        f"{counters.get('solved', 0)} Solved Bugs · "
        f"{counters.get('avoid', 0)} Avoid Patterns"
    )
