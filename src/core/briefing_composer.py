"""
Briefing Composer for Project Librarian.

Composes selected knowledge into structured briefings.

This module answers: "How should knowledge be organized and presented?"

Design principles:
1. Tier separation is preserved in output
2. Must-know items never truncated
3. Clear headers distinguish tiers
4. Composable for different consumers (AI, human, dashboard)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

from core.knowledge_model import (
    KnowledgeItem,
    KnowledgeType,
    Criticality,
    get_tier_display,
)
from core.knowledge_selection import KnowledgePackage, RetrievalStrategy
from core.intent_detection import Intent


class OutputFormat(Enum):
    """Output format for the briefing."""
    AI_AGENT = "ai_agent"    # For Claude/AI consumption
    HUMAN = "human"          # For human reading
    DASHBOARD = "dashboard"  # For dashboard display
    COMPACT = "compact"      # Minimal format


@dataclass
class Briefing:
    """
    A composed knowledge briefing ready for presentation.
    """
    # Structured sections (for programmatic access)
    header: str
    must_know_section: str
    should_check_section: str
    may_help_section: str
    continuation: str

    # Full formatted output
    formatted: str

    # Metadata
    total_items: int
    has_must_know: bool
    is_empty: bool

    def __str__(self) -> str:
        return self.formatted


@dataclass
class ComposerConfig:
    """Configuration for briefing composition."""
    format: OutputFormat = OutputFormat.AI_AGENT
    max_text_length: int = 150  # Per item
    show_empty_tiers: bool = False
    show_continuation: bool = True
    include_metadata: bool = False
    subject_summary: bool = True


def compose_briefing(
    package: KnowledgePackage,
    config: Optional[ComposerConfig] = None,
) -> Briefing:
    """
    Compose a knowledge package into a briefing.

    This preserves tier separation and guarantees must-know visibility.

    Args:
        package: Selected knowledge package
        config: Composition configuration

    Returns:
        Composed Briefing ready for presentation
    """
    if config is None:
        config = ComposerConfig()

    # Build sections
    header = _compose_header(package, config)
    must_know = _compose_tier_section(package.must_know, Criticality.MUST_KNOW, config)
    should_check = _compose_tier_section(package.should_check, Criticality.SHOULD_CHECK, config)
    may_help = _compose_tier_section(package.may_help, Criticality.MAY_HELP, config)
    continuation = _compose_continuation(package, config)

    # Assemble formatted output
    sections = [header]

    if must_know:
        sections.append(must_know)
    if should_check:
        sections.append(should_check)
    if may_help and config.format != OutputFormat.COMPACT:
        sections.append(may_help)
    if continuation and config.show_continuation:
        sections.append(continuation)

    formatted = "\n\n".join(s for s in sections if s)

    return Briefing(
        header=header,
        must_know_section=must_know,
        should_check_section=should_check,
        may_help_section=may_help,
        continuation=continuation,
        formatted=formatted,
        total_items=package.total_count(),
        has_must_know=package.has_must_know(),
        is_empty=package.is_empty(),
    )


def _compose_header(package: KnowledgePackage, config: ComposerConfig) -> str:
    """Compose the briefing header."""
    if not config.subject_summary:
        return ""

    if not package.subject_tags:
        return "📚 **Project Knowledge**"

    tags_display = ", ".join(package.subject_tags[:3])
    return f"📚 **Relevant for {tags_display}**"


def _compose_tier_section(
    items: List[KnowledgeItem],
    tier: Criticality,
    config: ComposerConfig,
) -> str:
    """Compose a single tier section."""
    if not items:
        if config.show_empty_tiers:
            icon, label = get_tier_display(tier)
            return f"{icon} **{label}**: (none)"
        return ""

    icon, label = get_tier_display(tier)
    lines = [f"{icon} **{label}**"]

    for item in items:
        line = _format_item(item, config)
        lines.append(line)

    return "\n".join(lines)


def _format_item(item: KnowledgeItem, config: ComposerConfig) -> str:
    """Format a single knowledge item."""
    # Get type-specific icon
    type_icons = {
        KnowledgeType.DECISION: "📌",
        KnowledgeType.AVOID: "⛔",
        KnowledgeType.SOLUTION: "✅",
        KnowledgeType.LESSON: "💡",
        KnowledgeType.INSIGHT: "💭",
        KnowledgeType.HANDOFF: "📍",
        KnowledgeType.CONFLICT: "⚠️",
    }
    icon = type_icons.get(item.type, "•")

    # Truncate text if needed
    text = item.text
    if len(text) > config.max_text_length:
        text = text[:config.max_text_length - 1] + "…"

    # Clean up text (single line for compact formats)
    if config.format in (OutputFormat.COMPACT, OutputFormat.DASHBOARD):
        text = " ".join(text.split())

    # Build the line
    if config.format == OutputFormat.COMPACT:
        return f"  {icon} {text}"
    else:
        return f"  {icon} {text}"


def _compose_continuation(package: KnowledgePackage, config: ComposerConfig) -> str:
    """Compose continuation/next-step section."""
    if not config.show_continuation:
        return ""

    if package.strategy == RetrievalStrategy.ALERT:
        return "→ Address the above before continuing."

    if package.has_must_know():
        return "→ Review the above before proceeding."

    if not package.is_empty():
        return "→ Knowledge available. Continue when ready."

    return ""


def compose_for_init(
    package: KnowledgePackage,
    compact: bool = False,
) -> str:
    """
    Compose briefing for fo_init context.

    Returns formatted string suitable for session opener.
    """
    config = ComposerConfig(
        format=OutputFormat.COMPACT if compact else OutputFormat.AI_AGENT,
        max_text_length=100 if compact else 150,
        show_empty_tiers=False,
        show_continuation=False,
        subject_summary=True,
    )

    briefing = compose_briefing(package, config)

    if briefing.is_empty:
        return ""

    return briefing.formatted


def compose_for_subject_change(
    package: KnowledgePackage,
    old_subject: str,
    new_subject: str,
) -> str:
    """
    Compose briefing for subject/topic change.

    Emphasizes the transition and new context.
    """
    config = ComposerConfig(
        format=OutputFormat.AI_AGENT,
        max_text_length=120,
        show_empty_tiers=False,
        show_continuation=True,
        subject_summary=True,
    )

    briefing = compose_briefing(package, config)

    if briefing.is_empty:
        return f"📚 Switched to **{new_subject}** — no specific knowledge recorded."

    header = f"📚 Switched to **{new_subject}**"
    sections = [header]

    if briefing.must_know_section:
        sections.append(briefing.must_know_section)
    if briefing.should_check_section:
        sections.append(briefing.should_check_section)

    return "\n\n".join(sections)


def compose_for_alert(package: KnowledgePackage) -> str:
    """
    Compose briefing for critical alert.

    Minimal, focused on must-know only.
    """
    if not package.has_must_know():
        return ""

    config = ComposerConfig(
        format=OutputFormat.COMPACT,
        max_text_length=200,
        show_empty_tiers=False,
        show_continuation=True,
        subject_summary=False,
    )

    briefing = compose_briefing(package, config)
    return briefing.formatted


def compose_for_orientation(package: KnowledgePackage) -> str:
    """
    Compose briefing for deep onboarding (fo_brief).

    Exhaustive, all tiers, full detail.
    """
    config = ComposerConfig(
        format=OutputFormat.AI_AGENT,
        max_text_length=300,
        show_empty_tiers=True,
        show_continuation=True,
        subject_summary=True,
        include_metadata=True,
    )

    briefing = compose_briefing(package, config)
    return briefing.formatted


def format_knowledge_stats(package: KnowledgePackage) -> str:
    """
    Format knowledge statistics for display.

    Shows counts per tier.
    """
    must = len(package.must_know)
    check = len(package.should_check)
    help = len(package.may_help)

    parts = []
    if must > 0:
        parts.append(f"{must} must-know")
    if check > 0:
        parts.append(f"{check} to check")
    if help > 0:
        parts.append(f"{help} context")

    if not parts:
        return "No knowledge for this context."

    return f"📊 Knowledge: {' · '.join(parts)}"


def merge_briefings(briefings: List[Briefing]) -> str:
    """
    Merge multiple briefings (e.g., from multiple subjects).

    Preserves tier order across briefings.
    """
    all_must_know = []
    all_should_check = []
    all_may_help = []

    for b in briefings:
        if b.must_know_section:
            all_must_know.append(b.must_know_section)
        if b.should_check_section:
            all_should_check.append(b.should_check_section)
        if b.may_help_section:
            all_may_help.append(b.may_help_section)

    sections = []
    if all_must_know:
        sections.append("\n".join(all_must_know))
    if all_should_check:
        sections.append("\n".join(all_should_check))
    if all_may_help:
        sections.append("\n".join(all_may_help))

    return "\n\n".join(sections)


# =============================================================================
# Reorientation Briefing
# =============================================================================

def compose_for_reorientation(
    memory: Dict[str, Any],
    project_name: str,
    active_goal: str = "",
    knowledge_stats: str = "",
    working_tree: str = "",
) -> str:
    """
    Compose full project reorientation briefing.

    Used when returning after a long break (>7 days) or when user
    explicitly indicates they need reorientation.

    Answers: "What should the engineer know about this project?"
    NOT: "What was the last thing touched?"

    Structure (empty sections hidden):
    1. Project Status (header + knowledge stats)
    2. Current Focus (active goal, blocking items)
    3. Recently Completed (milestones from last 30 days)
    4. Active Decisions
    5. Known Risks (avoid patterns, conflicts)
    6. Working Tree (git status, uncommitted changes)
    7. Suggested Next Step

    Project knowledge comes before git/worktree state.
    """
    sections = []

    # 1. Project Status (header)
    sections.append(f"🧠 **Project Status:** {project_name}")
    if knowledge_stats:
        sections.append(knowledge_stats)
    sections.append("")

    # 2. Current Focus
    focus_items = _extract_focus(memory, active_goal)
    if focus_items:
        sections.append("📍 **Current Focus**")
        for item in focus_items[:2]:
            sections.append(f"  {_truncate(item, 100)}")
        sections.append("")

    # 3. Recently Completed
    milestones = _extract_milestones(memory, days=30)
    if milestones:
        sections.append("✅ **Recently Completed**")
        for m in milestones[:3]:
            sections.append(f"  • {_truncate(m, 100)}")
        sections.append("")

    # 4. Active Decisions
    decisions = _extract_active_decisions(memory, limit=3)
    if decisions:
        sections.append("🔒 **Active Decisions**")
        for d in decisions:
            sections.append(f"  • {_truncate(d, 100)}")
        sections.append("")

    # 5. Known Risks
    risks = _extract_risks(memory, limit=2)
    if risks:
        sections.append("⚠️ **Known Risks**")
        for r in risks:
            sections.append(f"  • {_truncate(r, 100)}")
        sections.append("")

    # 6. Working Tree (git status - optional, should not dominate)
    if working_tree:
        sections.append("📂 **Working Tree**")
        sections.append(f"  {_truncate(working_tree, 120)}")
        sections.append("")

    # 7. Suggested Next Step (at the end)
    next_action = _extract_suggested_next(memory, active_goal)
    if next_action:
        sections.append(f"→ **Next:** {_truncate(next_action, 120)}")
        sections.append("")

    sections.append("Ready.")

    return "\n".join(sections)


def _extract_focus(memory: Dict[str, Any], active_goal: str) -> List[str]:
    """
    Extract current focus: active goal and blocking items.

    Simpler than priorities - focuses on what needs attention NOW.
    """
    focus = []

    if active_goal:
        focus.append(active_goal)

    # Open conflicts are blocking
    conflicts = memory.get("decision_conflicts", [])
    for conflict in conflicts:
        if isinstance(conflict, dict) and conflict.get("status", "open") == "open":
            desc = conflict.get("description", "")
            if desc and desc not in focus:
                focus.append(f"⚠️ {desc}")
                break

    # Blocking decisions
    decisions = memory.get("decisions", [])
    for dec in decisions:
        if isinstance(dec, dict) and not dec.get("superseded"):
            if dec.get("blocking"):
                text = dec.get("decision", "")
                if text and text not in focus:
                    focus.append(f"🔒 {text}")
                    if len(focus) >= 2:
                        break

    return focus[:2]


def _truncate(text: str, limit: int) -> str:
    """Truncate text to limit, adding ellipsis if needed."""
    text = " ".join(str(text).strip().split())
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def _extract_priorities(memory: Dict[str, Any], active_goal: str) -> List[str]:
    """
    Extract top priorities: active goal, open conflicts, blocking decisions.

    Prioritizes project-level importance over recency.
    """
    priorities = []

    # Active goal is always first priority if set
    if active_goal:
        priorities.append(active_goal)

    # Open conflicts are high priority
    conflicts = memory.get("decision_conflicts", [])
    for conflict in conflicts:
        if isinstance(conflict, dict) and conflict.get("status", "open") == "open":
            desc = conflict.get("description", conflict.get("text", ""))
            if desc and desc not in priorities:
                priorities.append(f"Unresolved: {desc}")
                break

    # Blocking/critical decisions
    decisions = memory.get("decisions", [])
    for dec in decisions:
        if isinstance(dec, dict) and not dec.get("superseded"):
            if dec.get("blocking") or dec.get("is_critical"):
                text = dec.get("decision", "")
                if text and text not in priorities:
                    priorities.append(text)
                    if len(priorities) >= 2:
                        break

    return priorities[:2]


def _extract_milestones(memory: Dict[str, Any], days: int = 30) -> List[str]:
    """
    Extract recent milestones: solved bugs, resolved decisions.

    Looks at items completed in the last N days.
    """
    from datetime import datetime, timedelta

    milestones = []
    cutoff = datetime.now() - timedelta(days=days)

    # Solved bugs
    debug_sessions = memory.get("debug_sessions", [])
    for ds in debug_sessions:
        if not isinstance(ds, dict):
            continue
        resolved_at = ds.get("resolved_at") or ds.get("timestamp")
        if resolved_at:
            try:
                ts = datetime.fromisoformat(str(resolved_at).replace('Z', '+00:00'))
                ts = ts.replace(tzinfo=None) if ts.tzinfo else ts
                if ts >= cutoff:
                    problem = ds.get("problem", "")
                    if problem:
                        milestones.append(f"Fixed: {problem}")
            except:
                pass

    # Resolved decisions (look for recent ones)
    decisions = memory.get("decisions", [])
    for dec in decisions:
        if not isinstance(dec, dict):
            continue
        if dec.get("superseded"):
            continue
        created_at = dec.get("created_at") or dec.get("timestamp")
        if created_at:
            try:
                ts = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
                ts = ts.replace(tzinfo=None) if ts.tzinfo else ts
                if ts >= cutoff:
                    text = dec.get("decision", "")
                    if text:
                        milestones.append(f"Decided: {text}")
            except:
                pass

    return milestones[:3]


def _extract_active_decisions(memory: Dict[str, Any], limit: int = 3) -> List[str]:
    """
    Extract active (non-superseded) decisions.

    Sorted by importance markers, not recency.
    """
    decisions = memory.get("decisions", [])
    active = []

    # First pass: blocking/critical decisions
    for dec in decisions:
        if not isinstance(dec, dict):
            continue
        if dec.get("superseded"):
            continue
        if dec.get("blocking") or dec.get("is_critical"):
            text = dec.get("decision", "")
            reason = dec.get("reason", "")
            if text:
                entry = text
                if reason:
                    entry += f" ({reason[:50]}…)" if len(reason) > 50 else f" ({reason})"
                active.append(entry)

    # Second pass: regular decisions (if room)
    if len(active) < limit:
        for dec in decisions:
            if not isinstance(dec, dict):
                continue
            if dec.get("superseded"):
                continue
            if dec.get("blocking") or dec.get("is_critical"):
                continue  # Already added
            text = dec.get("decision", "")
            if text and text not in [a.split(" (")[0] for a in active]:
                active.append(text)
                if len(active) >= limit:
                    break

    return active[:limit]


def _extract_risks(memory: Dict[str, Any], limit: int = 2) -> List[str]:
    """
    Extract known risks: avoid patterns, open conflicts.
    """
    risks = []

    # Avoid patterns
    avoid = memory.get("avoid", [])
    for av in avoid:
        if isinstance(av, dict):
            what = av.get("what", "")
            reason = av.get("reason", "")
            if what:
                entry = f"Avoid: {what}"
                if reason:
                    entry += f" — {reason[:40]}" if len(reason) > 40 else f" — {reason}"
                risks.append(entry)
        elif isinstance(av, str):
            risks.append(f"Avoid: {av}")

    # Open conflicts
    conflicts = memory.get("decision_conflicts", [])
    for conflict in conflicts:
        if isinstance(conflict, dict) and conflict.get("status", "open") == "open":
            desc = conflict.get("description", "")
            if desc:
                risks.append(f"Conflict: {desc}")

    return risks[:limit]


def _extract_suggested_next(memory: Dict[str, Any], active_goal: str) -> str:
    """
    Extract suggested next action.

    Prefers: open conflicts > blocking decisions > active goal continuation.
    """
    # Open conflicts need resolution
    conflicts = memory.get("decision_conflicts", [])
    for conflict in conflicts:
        if isinstance(conflict, dict) and conflict.get("status", "open") == "open":
            return f"Resolve conflict: {conflict.get('description', 'pending decision')}"

    # If there's an active goal, continue it
    if active_goal:
        return f"Continue: {active_goal}"

    # Look for handoff/next_step in live_record
    live_record = memory.get("live_record", {})
    intent = live_record.get("intent", {})
    next_step = intent.get("next_step", "")
    if next_step:
        return next_step

    return ""


def detect_reorientation_hint(task_hint: str) -> bool:
    """
    Detect if task_hint indicates user needs reorientation.

    Triggers on phrases like:
    - "returning after a long break"
    - "forgot where I stopped"
    - "need reorientation"
    - "continue after not working"
    - "been a while"
    - "catch me up"
    """
    if not task_hint:
        return False

    hint_lower = task_hint.lower()

    reorientation_phrases = [
        "long break",
        "forgot where",
        "don't remember",
        "dont remember",
        "need reorientation",
        "reorient",
        "been a while",
        "been away",
        "catch me up",
        "catch up",
        "where were we",
        "where did we",
        "remind me",
        "what were we",
        "haven't worked",
        "havent worked",
        "not worked",
        "returning after",
        "back after",
        "continue after",
        "help me continue",
        "lost track",
        "lost context",
    ]

    return any(phrase in hint_lower for phrase in reorientation_phrases)
