"""
Shared live project knowledge counters for UI/session display.

This is the SINGLE SOURCE OF TRUTH for all knowledge counting in FixOnce.
All counter logic MUST live here. MCP, Dashboard, Tray, and API must call
these functions instead of computing counts inline.

Counter types:
- decisions: Active (non-superseded) decisions
- solved: Active (non-superseded) solutions/debug_sessions
- avoid: Avoid patterns (never superseded)
- insights: Active insights (not archived)
- archived_insights: Archived insights
- failed_attempts: Failed attempt records
"""

from typing import Any, Dict, Optional
from pathlib import Path


def get_live_project_counters(memory: Dict[str, Any] | None) -> Dict[str, int]:
    """
    Return counters from live project memory.

    Filters superseded decisions and solutions. This is the canonical
    counter function for dashboard/session display.

    Args:
        memory: Project memory dict (from load_project_memory)

    Returns:
        Dict with keys: decisions, solved, avoid
    """
    memory = memory or {}
    # Count only active (non-superseded) decisions and solutions
    decisions = [d for d in (memory.get("decisions", []) or []) if not d.get("superseded")]
    solved = [s for s in (memory.get("debug_sessions", []) or []) if not s.get("superseded")]
    return {
        "decisions": len(decisions),
        "solved": len(solved),
        "avoid": len(memory.get("avoid", []) or []),
    }


def get_full_knowledge_counters(
    memory: Dict[str, Any] | None,
    working_dir: Optional[str] = None,
    use_committed: bool = True,
) -> Dict[str, int]:
    """
    Return comprehensive counters for all knowledge types.

    Optionally uses committed_knowledge as primary source (for consistency
    with fo_init), falling back to project memory if unavailable.

    Args:
        memory: Project memory dict
        working_dir: Working directory for committed_knowledge lookup
        use_committed: If True, try committed_knowledge first

    Returns:
        Dict with keys: decisions, solved, avoid, insights, archived_insights, failed_attempts
    """
    memory = memory or {}

    # Try committed_knowledge first if requested and working_dir available
    if use_committed and working_dir:
        try:
            from core.committed_knowledge import read_committed_knowledge
            ck = read_committed_knowledge(working_dir)
            if ck:
                return _count_from_committed_knowledge(ck, memory)
        except Exception:
            pass  # Fall through to memory-based counting

    return _count_from_memory(memory)


def _count_from_committed_knowledge(
    ck: Dict[str, Any],
    memory: Dict[str, Any]
) -> Dict[str, int]:
    """
    Count from committed_knowledge with memory fallback for insights.

    Committed knowledge has: decisions, solutions, avoid
    Memory has: live_record.lessons.insights, archived, failed_attempts
    """
    # Decisions - filter superseded
    decisions = [d for d in (ck.get("decisions", []) or []) if not d.get("superseded")]

    # Solutions - use active_count if available, otherwise filter superseded
    solutions_list = ck.get("solutions", []) or []
    active_count = ck.get("active_count")
    if active_count is not None:
        solved = active_count
    else:
        solved = len([s for s in solutions_list if not s.get("superseded")])

    # Avoid patterns - never superseded
    avoid = len(ck.get("avoid", []) or [])

    # Insights and failed_attempts come from memory.live_record.lessons
    lessons = memory.get("live_record", {}).get("lessons", {})
    insights = len(lessons.get("insights", []) or [])
    archived = len(lessons.get("archived", []) or [])
    failed = len(lessons.get("failed_attempts", []) or [])

    return {
        "decisions": len(decisions),
        "solved": solved,
        "avoid": avoid,
        "insights": insights,
        "archived_insights": archived,
        "failed_attempts": failed,
    }


def _count_from_memory(memory: Dict[str, Any]) -> Dict[str, int]:
    """
    Count all knowledge types from project memory.

    Used when committed_knowledge is unavailable.
    """
    # Decisions - filter superseded
    decisions = [d for d in (memory.get("decisions", []) or []) if not d.get("superseded")]

    # Solutions/debug_sessions - filter superseded
    solved = [s for s in (memory.get("debug_sessions", []) or []) if not s.get("superseded")]

    # Avoid patterns - never superseded
    avoid = len(memory.get("avoid", []) or [])

    # Insights and failed_attempts from live_record.lessons
    lessons = memory.get("live_record", {}).get("lessons", {})
    insights = len(lessons.get("insights", []) or [])
    archived = len(lessons.get("archived", []) or [])
    failed = len(lessons.get("failed_attempts", []) or [])

    return {
        "decisions": len(decisions),
        "solved": len(solved),
        "avoid": avoid,
        "insights": insights,
        "archived_insights": archived,
        "failed_attempts": failed,
    }


def get_raw_counts(memory: Dict[str, Any] | None) -> Dict[str, int]:
    """
    Return raw counts WITHOUT superseded filtering.

    Used for index snapshots and reports where total counts are needed.
    This includes superseded items.

    Args:
        memory: Project memory dict

    Returns:
        Dict with keys: decisions_total, avoid_total
    """
    memory = memory or {}
    return {
        "decisions_total": len(memory.get("decisions", []) or []),
        "avoid_total": len(memory.get("avoid", []) or []),
    }


def format_project_knowledge_line(counters: Dict[str, int]) -> str:
    """Format the compact Project Knowledge display line."""
    return (
        f"📊 Project Knowledge: {counters.get('decisions', 0)} Decisions · "
        f"{counters.get('solved', 0)} Solved Bugs · "
        f"{counters.get('avoid', 0)} Avoid Patterns"
    )


def format_memory_stats_block(
    counters: Dict[str, int],
    include_insights: bool = True,
    source_note: Optional[str] = None,
) -> str:
    """
    Format the full memory statistics block for get_memory_stats.

    Args:
        counters: Full counters from get_full_knowledge_counters
        include_insights: Whether to include insight counts
        source_note: Optional note about data source

    Returns:
        Formatted markdown block
    """
    lines = ["## Project Knowledge Statistics\n"]

    lines.append(f"**Decisions:** {counters.get('decisions', 0)}")
    lines.append(f"**Solved Bugs:** {counters.get('solved', 0)}")
    lines.append(f"**Avoid Patterns:** {counters.get('avoid', 0)}")

    if include_insights:
        lines.append(f"**Active Insights:** {counters.get('insights', 0)}")
        lines.append(f"**Archived Insights:** {counters.get('archived_insights', 0)}")
        lines.append(f"**Failed Attempts:** {counters.get('failed_attempts', 0)}")

    if source_note:
        lines.append(f"\n_{source_note}_")

    return "\n".join(lines)


def format_cleanup_report_counts(
    memory: Dict[str, Any] | None,
    newly_archived: list,
    still_active: list,
) -> str:
    """
    Format the protected items section of the cleanup report.

    Uses raw counts (including superseded) for "protected" display
    since the cleanup report shows total items, not just active.

    Args:
        memory: Project memory dict
        newly_archived: List of newly archived insights
        still_active: List of still-active insights

    Returns:
        Formatted markdown block for cleanup report
    """
    memory = memory or {}

    # For cleanup report, we show TOTAL counts (including superseded)
    # because this is about what's "protected" from archival
    decisions_count = len(memory.get('decisions', []) or [])
    avoid_count = len(memory.get('avoid', []) or [])

    lessons = memory.get('live_record', {}).get('lessons', {})
    failed_count = len(lessons.get('failed_attempts', []) or [])

    lines = ["### 🔒 Protected (Never Archived)"]
    lines.append(f"- **Decisions:** {decisions_count}")
    lines.append(f"- **Avoid Patterns:** {avoid_count}")
    lines.append(f"- **Failed Attempts:** {failed_count}")
    lines.append("")

    lines.append("### 📊 Insights")
    lines.append(f"**Active:** {len(still_active)}")
    lines.append(f"**Newly Archived:** {len(newly_archived)}")
    lines.append(f"**Total Archived:** {len(lessons.get('archived', []) or [])}")

    return "\n".join(lines)
