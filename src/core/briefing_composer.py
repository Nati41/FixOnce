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
