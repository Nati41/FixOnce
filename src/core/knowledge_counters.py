"""Shared live project knowledge counters for UI/session display."""

from typing import Any, Dict


def get_live_project_counters(memory: Dict[str, Any] | None) -> Dict[str, int]:
    """Return counters from live project memory, not committed/exported files."""
    memory = memory or {}
    return {
        "decisions": len(memory.get("decisions", []) or []),
        "solved": len(memory.get("debug_sessions", []) or []),
        "avoid": len(memory.get("avoid", []) or []),
    }


def format_project_knowledge_line(counters: Dict[str, int]) -> str:
    """Format the compact Project Knowledge display line."""
    return (
        f"📊 Project Knowledge: {counters.get('decisions', 0)} Decisions · "
        f"{counters.get('solved', 0)} Solved Bugs · "
        f"{counters.get('avoid', 0)} Avoid Patterns"
    )
