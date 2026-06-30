"""
Knowledge Selection for Project Librarian.

Selects what the engineer must know before continuing.

This module answers: "What knowledge is relevant AND important for this context?"

Core guarantee: If must-know items exist for the current context, they appear.

Design principles:
1. Relevance first, then importance
2. Tiered selection, never flat ranking
3. Guaranteed representation per tier
4. No cross-tier competition
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from enum import Enum

from core.knowledge_model import (
    KnowledgeItem,
    KnowledgeType,
    Criticality,
    Scope,
    Trust,
    classify_knowledge,
)
from core.intent_detection import Intent
from core.subject_detection import extract_subject_tags_from_path


PLATFORM_SUBJECT_TAGS = {"windows", "macos", "linux"}


class RetrievalStrategy(Enum):
    """Different strategies for different use cases."""
    BRIEFING = "briefing"        # Session start, topic switch
    SEARCH = "search"            # Explicit query
    ORIENTATION = "orientation"  # Deep onboarding
    ALERT = "alert"              # Critical new information


@dataclass
class KnowledgePackage:
    """
    Selected knowledge organized by tier.

    Tiers never merge. Must-know always precedes should-check.
    """
    must_know: List[KnowledgeItem] = field(default_factory=list)
    should_check: List[KnowledgeItem] = field(default_factory=list)
    may_help: List[KnowledgeItem] = field(default_factory=list)

    # Metadata
    subject_tags: List[str] = field(default_factory=list)
    intent: Optional[Intent] = None
    strategy: RetrievalStrategy = RetrievalStrategy.BRIEFING

    def is_empty(self) -> bool:
        """Check if package has any knowledge."""
        return not (self.must_know or self.should_check or self.may_help)

    def has_must_know(self) -> bool:
        """Check if must-know tier has items."""
        return len(self.must_know) > 0

    def total_count(self) -> int:
        """Total items across all tiers."""
        return len(self.must_know) + len(self.should_check) + len(self.may_help)

    def get_all_items(self) -> List[KnowledgeItem]:
        """Get all items in tier order (never for ranking, only for iteration)."""
        return self.must_know + self.should_check + self.may_help


@dataclass
class SelectionContext:
    """Context for knowledge selection."""
    subject_tags: List[str]
    intent: Intent
    strategy: RetrievalStrategy
    max_per_tier: int = 5
    include_may_help: bool = True


def select_knowledge(
    memory: Dict[str, Any],
    context: SelectionContext,
) -> KnowledgePackage:
    """
    Select knowledge for the given context.

    Pipeline:
    1. Extract all knowledge items from memory
    2. Filter by relevance (subject, intent, scope)
    3. Classify into tiers
    4. Rank within each tier
    5. Apply limits per tier

    Args:
        memory: Project memory dict
        context: Selection context with subject, intent, strategy

    Returns:
        KnowledgePackage with tiered, relevant knowledge
    """
    # Step 1: Extract all knowledge items
    all_items = _extract_all_knowledge(memory)

    # Step 2: Filter by relevance
    relevant_items = _filter_relevant(all_items, context)

    # Step 3: Separate into tiers (never merge)
    tiered = _separate_into_tiers(relevant_items)

    # Step 4: Rank within each tier
    ranked = _rank_within_tiers(tiered, context)

    # Step 5: Apply limits
    limited = _apply_limits(ranked, context)

    return KnowledgePackage(
        must_know=limited[Criticality.MUST_KNOW],
        should_check=limited[Criticality.SHOULD_CHECK],
        may_help=limited[Criticality.MAY_HELP] if context.include_may_help else [],
        subject_tags=context.subject_tags,
        intent=context.intent,
        strategy=context.strategy,
    )


def _extract_all_knowledge(memory: Dict[str, Any]) -> List[KnowledgeItem]:
    """Extract all knowledge items from memory dict."""
    items = []

    # Extract decisions
    for dec in memory.get('decisions', []):
        if dec.get('superseded'):
            continue  # Skip superseded
        items.append(classify_knowledge(dec, 'decision'))

    # Extract solutions (debug_sessions)
    for ds in memory.get('debug_sessions', []):
        items.append(classify_knowledge(ds, 'solution'))

    # Extract avoid patterns
    for av in memory.get('avoid', []):
        items.append(classify_knowledge(av, 'avoid'))

    # Extract insights
    lessons = memory.get('live_record', {}).get('lessons', {})
    for insight in lessons.get('insights', []):
        if isinstance(insight, str):
            insight = {'text': insight}
        items.append(classify_knowledge(insight, 'insight'))

    # Extract failed attempts as avoid
    for failed in lessons.get('failed_attempts', []):
        if isinstance(failed, str):
            failed = {'what': failed}
        items.append(classify_knowledge(failed, 'failed_attempt'))

    # Extract unresolved conflicts
    for conflict in memory.get('decision_conflicts', []):
        if isinstance(conflict, dict) and conflict.get('status', 'open') == 'open':
            items.append(classify_knowledge(conflict, 'conflict'))

    return items


def _filter_relevant(
    items: List[KnowledgeItem],
    context: SelectionContext,
) -> List[KnowledgeItem]:
    """
    Filter items by relevance to context.

    Relevance is determined by:
    1. Scope rules (universal, subject_bound, intent_bound)
    2. Subject tag matching (explicit or derived)
    3. Intent matching (for intent_bound)
    4. Text-based matching as fallback

    Items without explicit tags are matched via text content.
    """
    relevant = []

    for item in items:
        # Universal scope: always relevant
        if item.scope == Scope.UNIVERSAL:
            relevant.append(item)
            continue

        # Check if item matches subject
        matches_subject = _item_matches_subject(item, context.subject_tags)

        # Subject-bound: check subject match
        if item.scope == Scope.SUBJECT_BOUND:
            if matches_subject:
                relevant.append(item)
            continue

        # Intent-bound: check both subject and intent
        if item.scope == Scope.INTENT_BOUND:
            if matches_subject and item.matches_intent(context.intent.value):
                relevant.append(item)
            continue

    return relevant


def _item_matches_subject(item: KnowledgeItem, subject_tags: List[str]) -> bool:
    """
    Check if item matches subject tags.

    Matching is done via:
    1. Explicit tags on the item
    2. Text content matching (for items without tags)
    """
    # If no subject tags to match, everything matches
    if not subject_tags:
        return True

    subject_tag_set = {t.lower() for t in subject_tags}

    # Check explicit tags first
    if item.subjects:
        item_subjects = {s.lower() for s in item.subjects}

        # Platform-bound knowledge must not leak across platform subjects via
        # generic tags like "installer".
        current_platforms = subject_tag_set & PLATFORM_SUBJECT_TAGS
        item_platforms = item_subjects & PLATFORM_SUBJECT_TAGS
        if current_platforms and item_platforms and not (current_platforms & item_platforms):
            return False

        return bool(item_subjects & subject_tag_set)

    # Fallback: check text content for subject keywords
    text_lower = item.text.lower()
    for tag in subject_tags:
        tag_lower = tag.lower()
        if tag_lower in text_lower:
            return True

    # Also check metadata for file references
    files = item.metadata.get('files_changed', [])
    for f in files:
        for tag in subject_tags:
            if tag.lower() in f.lower():
                return True

    return False


def _separate_into_tiers(items: List[KnowledgeItem]) -> Dict[Criticality, List[KnowledgeItem]]:
    """
    Separate items into criticality tiers.

    Tiers never merge. This is a fundamental invariant.
    """
    tiers = {
        Criticality.MUST_KNOW: [],
        Criticality.SHOULD_CHECK: [],
        Criticality.MAY_HELP: [],
    }

    for item in items:
        tiers[item.criticality].append(item)

    return tiers


def _rank_within_tiers(
    tiers: Dict[Criticality, List[KnowledgeItem]],
    context: SelectionContext,
) -> Dict[Criticality, List[KnowledgeItem]]:
    """
    Rank items within each tier.

    Ranking factors (applied ONLY within a tier):
    1. Trust level (verified > active > experimental > historical)
    2. Recency (newer items slightly preferred)
    3. Reuse count (more reused = more valuable)
    4. Intent alignment (items matching intent ranked higher)
    """
    ranked = {}

    for criticality, items in tiers.items():
        ranked[criticality] = sorted(items, key=lambda x: _item_score(x, context), reverse=True)

    return ranked


def _item_score(item: KnowledgeItem, context: SelectionContext) -> float:
    """
    Calculate score for ranking WITHIN a tier.

    This is NOT cross-tier ranking. A must-know item with score 10
    is never compared to a should-check item with score 100.
    """
    score = 0.0

    # Trust level (primary within-tier signal)
    trust_scores = {
        Trust.VERIFIED: 100,
        Trust.ACTIVE: 80,
        Trust.EXPERIMENTAL: 50,
        Trust.HISTORICAL: 20,
    }
    score += trust_scores.get(item.trust, 50)

    # Intent alignment bonus
    if item.matches_intent(context.intent.value):
        # Bonus based on intent
        if context.intent == Intent.DEBUGGING and item.type == KnowledgeType.SOLUTION:
            score += 30
        elif context.intent == Intent.DESIGNING and item.type == KnowledgeType.DECISION:
            score += 30
        elif context.intent == Intent.REVIEWING and item.type == KnowledgeType.AVOID:
            score += 30

    # Reuse count bonus (capped)
    score += min(item.reuse_count * 5, 25)

    # Recency bonus (if we have timestamp)
    if item.updated_at or item.created_at:
        # Recent items get small boost (not dominant)
        from datetime import datetime, timedelta
        ts = item.updated_at or item.created_at
        now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
        age = now - ts
        if age < timedelta(days=1):
            score += 15
        elif age < timedelta(days=7):
            score += 10
        elif age < timedelta(days=30):
            score += 5

    return score


def _apply_limits(
    tiers: Dict[Criticality, List[KnowledgeItem]],
    context: SelectionContext,
) -> Dict[Criticality, List[KnowledgeItem]]:
    """Apply per-tier limits."""
    limited = {}

    for criticality, items in tiers.items():
        # Strategy-specific limits
        if context.strategy == RetrievalStrategy.ALERT:
            # Alert: only must-know, minimal
            if criticality == Criticality.MUST_KNOW:
                limited[criticality] = items[:3]
            else:
                limited[criticality] = []

        elif context.strategy == RetrievalStrategy.ORIENTATION:
            # Orientation: exhaustive, higher limits
            limited[criticality] = items[:10]

        elif context.strategy == RetrievalStrategy.SEARCH:
            # Search: flat behavior handled elsewhere
            limited[criticality] = items[:context.max_per_tier]

        else:
            # Briefing: balanced limits
            limited[criticality] = items[:context.max_per_tier]

    return limited


def select_for_briefing(
    memory: Dict[str, Any],
    subject_tags: List[str],
    intent: Intent,
    max_per_tier: int = 3,
) -> KnowledgePackage:
    """
    Convenience function for briefing selection (fo_init, topic switch).

    This is the primary librarian behavior.
    """
    context = SelectionContext(
        subject_tags=subject_tags,
        intent=intent,
        strategy=RetrievalStrategy.BRIEFING,
        max_per_tier=max_per_tier,
        include_may_help=True,
    )
    return select_knowledge(memory, context)


def select_for_alert(
    memory: Dict[str, Any],
    subject_tags: List[str],
    intent: Intent,
) -> KnowledgePackage:
    """
    Selection for alert/interrupt (critical new information).

    Only returns must-know items, minimal count.
    """
    context = SelectionContext(
        subject_tags=subject_tags,
        intent=intent,
        strategy=RetrievalStrategy.ALERT,
        max_per_tier=3,
        include_may_help=False,
    )
    return select_knowledge(memory, context)


def select_for_orientation(
    memory: Dict[str, Any],
    subject_tags: List[str],
    intent: Intent,
) -> KnowledgePackage:
    """
    Selection for deep onboarding (fo_brief).

    Returns exhaustive knowledge across all tiers.
    """
    context = SelectionContext(
        subject_tags=subject_tags,
        intent=intent,
        strategy=RetrievalStrategy.ORIENTATION,
        max_per_tier=10,
        include_may_help=True,
    )
    return select_knowledge(memory, context)


def has_relevant_knowledge(
    memory: Dict[str, Any],
    subject_tags: List[str],
) -> bool:
    """
    Quick check if any relevant knowledge exists.

    Used by intervention check before full selection.
    """
    all_items = _extract_all_knowledge(memory)
    context = SelectionContext(
        subject_tags=subject_tags,
        intent=Intent.UNKNOWN,
        strategy=RetrievalStrategy.BRIEFING,
    )
    relevant = _filter_relevant(all_items, context)
    return len(relevant) > 0


def count_by_tier(
    memory: Dict[str, Any],
    subject_tags: List[str],
) -> Dict[str, int]:
    """
    Count items per tier for a subject.

    Useful for summary stats without full selection.
    """
    all_items = _extract_all_knowledge(memory)
    context = SelectionContext(
        subject_tags=subject_tags,
        intent=Intent.UNKNOWN,
        strategy=RetrievalStrategy.BRIEFING,
    )
    relevant = _filter_relevant(all_items, context)
    tiers = _separate_into_tiers(relevant)

    return {
        "must_know": len(tiers[Criticality.MUST_KNOW]),
        "should_check": len(tiers[Criticality.SHOULD_CHECK]),
        "may_help": len(tiers[Criticality.MAY_HELP]),
    }
