"""
Knowledge Model for Project Librarian.

Defines the attributes that every piece of project knowledge carries.

This module answers: "What properties does this knowledge have?"

The model supports:
- Criticality tiers (must_know, should_check, may_help)
- Scope rules (universal, subject_bound, intent_bound)
- Trust levels (verified, active, experimental, historical)

Design principles:
1. Every knowledge item can be classified
2. Classification is deterministic given the item
3. The model is extensible for new knowledge types
4. No ranking scores here - just classification
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from enum import Enum
from datetime import datetime


class KnowledgeType(Enum):
    """Types of knowledge that can be stored."""
    DECISION = "decision"
    SOLUTION = "solution"
    AVOID = "avoid"
    INSIGHT = "insight"
    HANDOFF = "handoff"
    LESSON = "lesson"
    CONFLICT = "conflict"


class Criticality(Enum):
    """How critical is this knowledge for the engineer to see?"""
    MUST_KNOW = "must_know"      # Cannot proceed safely without this
    SHOULD_CHECK = "should_check"  # High value for this context
    MAY_HELP = "may_help"        # Relevant but not critical


class Scope(Enum):
    """When should this knowledge be surfaced?"""
    UNIVERSAL = "universal"        # Always, regardless of subject
    SUBJECT_BOUND = "subject_bound"  # When subject matches
    INTENT_BOUND = "intent_bound"    # When subject AND intent match


class Trust(Enum):
    """How reliable is this knowledge?"""
    VERIFIED = "verified"        # Proven correct over time
    ACTIVE = "active"            # Current belief
    EXPERIMENTAL = "experimental"  # Recent, untested
    HISTORICAL = "historical"      # Superseded or aged out


@dataclass
class KnowledgeItem:
    """
    A single piece of project knowledge with all its attributes.

    This is the canonical representation that flows through the librarian.
    """
    # Content
    id: str
    text: str
    type: KnowledgeType

    # Classification
    criticality: Criticality
    scope: Scope
    trust: Trust

    # Subject binding
    subjects: List[str] = field(default_factory=list)

    # Intent binding (for INTENT_BOUND scope)
    intents: List[str] = field(default_factory=list)

    # Original metadata (preserved from source)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Usage tracking
    reuse_count: int = 0
    last_surfaced: Optional[datetime] = None

    def is_must_know(self) -> bool:
        """Check if this is must-know criticality."""
        return self.criticality == Criticality.MUST_KNOW

    def matches_subject(self, subject_tags: List[str]) -> bool:
        """Check if item matches any of the given subject tags."""
        if self.scope == Scope.UNIVERSAL:
            return True
        if not self.subjects:
            return False
        return any(s in subject_tags for s in self.subjects)

    def matches_intent(self, intent: str) -> bool:
        """Check if item matches the given intent."""
        if self.scope != Scope.INTENT_BOUND:
            return True  # Not intent-restricted
        if not self.intents:
            return True  # No intent restriction specified
        return intent in self.intents


# Default criticality by type
DEFAULT_CRITICALITY: Dict[KnowledgeType, Criticality] = {
    KnowledgeType.DECISION: Criticality.MUST_KNOW,
    KnowledgeType.AVOID: Criticality.MUST_KNOW,
    KnowledgeType.CONFLICT: Criticality.MUST_KNOW,
    KnowledgeType.SOLUTION: Criticality.SHOULD_CHECK,
    KnowledgeType.LESSON: Criticality.SHOULD_CHECK,
    KnowledgeType.HANDOFF: Criticality.SHOULD_CHECK,
    KnowledgeType.INSIGHT: Criticality.MAY_HELP,
}

# Default scope by type
DEFAULT_SCOPE: Dict[KnowledgeType, Scope] = {
    KnowledgeType.DECISION: Scope.SUBJECT_BOUND,
    KnowledgeType.AVOID: Scope.SUBJECT_BOUND,
    KnowledgeType.CONFLICT: Scope.UNIVERSAL,
    KnowledgeType.SOLUTION: Scope.SUBJECT_BOUND,
    KnowledgeType.LESSON: Scope.SUBJECT_BOUND,
    KnowledgeType.HANDOFF: Scope.SUBJECT_BOUND,
    KnowledgeType.INSIGHT: Scope.SUBJECT_BOUND,
}

# Default trust by type
DEFAULT_TRUST: Dict[KnowledgeType, Trust] = {
    KnowledgeType.DECISION: Trust.ACTIVE,
    KnowledgeType.AVOID: Trust.ACTIVE,
    KnowledgeType.CONFLICT: Trust.ACTIVE,
    KnowledgeType.SOLUTION: Trust.ACTIVE,
    KnowledgeType.LESSON: Trust.ACTIVE,
    KnowledgeType.HANDOFF: Trust.ACTIVE,
    KnowledgeType.INSIGHT: Trust.ACTIVE,
}


def classify_knowledge(
    raw_item: Dict[str, Any],
    item_type: str,
) -> KnowledgeItem:
    """
    Classify a raw memory item into a KnowledgeItem with full attributes.

    This is the bridge between existing memory format and the knowledge model.

    Args:
        raw_item: Raw memory dict from storage
        item_type: Type string ('decision', 'solution', 'avoid', etc.)

    Returns:
        Fully classified KnowledgeItem
    """
    # Map type string to enum
    type_map = {
        'decision': KnowledgeType.DECISION,
        'solution': KnowledgeType.SOLUTION,
        'avoid': KnowledgeType.AVOID,
        'insight': KnowledgeType.INSIGHT,
        'handoff': KnowledgeType.HANDOFF,
        'lesson': KnowledgeType.LESSON,
        'failed_attempt': KnowledgeType.AVOID,  # Treat as avoid
        'conflict': KnowledgeType.CONFLICT,
    }
    knowledge_type = type_map.get(item_type, KnowledgeType.INSIGHT)

    # Extract text based on type
    text = _extract_text(raw_item, item_type)

    # Generate ID
    item_id = raw_item.get('id', _generate_id(text))

    # Determine criticality (can be overridden by explicit marker)
    criticality = _determine_criticality(raw_item, knowledge_type)

    # Determine scope
    scope = _determine_scope(raw_item, knowledge_type)

    # Determine trust
    trust = _determine_trust(raw_item, knowledge_type)

    # Extract subjects (tags)
    subjects = raw_item.get('tags', [])
    if not subjects and raw_item.get('subjects'):
        subjects = raw_item['subjects']

    # Extract intent bindings
    intents = raw_item.get('intents', [])

    # Parse timestamps
    created_at = _parse_timestamp(raw_item.get('created_at') or raw_item.get('timestamp'))
    updated_at = _parse_timestamp(raw_item.get('updated_at') or raw_item.get('resolved_at'))

    return KnowledgeItem(
        id=item_id,
        text=text,
        type=knowledge_type,
        criticality=criticality,
        scope=scope,
        trust=trust,
        subjects=subjects,
        intents=intents,
        metadata=raw_item,
        created_at=created_at,
        updated_at=updated_at,
        reuse_count=raw_item.get('reuse_count', 0),
    )


def _extract_text(item: Dict[str, Any], item_type: str) -> str:
    """Extract display text from raw item."""
    if item_type == 'decision':
        dec = item.get('decision', '')
        reason = item.get('reason', '')
        return f"{dec}" + (f" (Reason: {reason})" if reason else "")

    elif item_type == 'solution':
        problem = item.get('problem', '')
        solution = item.get('solution', '')
        return f"Problem: {problem}\nSolution: {solution}"

    elif item_type in ('avoid', 'failed_attempt'):
        what = item.get('what', '')
        reason = item.get('reason', '')
        return f"{what}" + (f" (Reason: {reason})" if reason else "")

    elif item_type == 'handoff':
        return item.get('next_step', '') or item.get('text', '')

    else:
        return item.get('text', str(item))


def _determine_criticality(item: Dict[str, Any], knowledge_type: KnowledgeType) -> Criticality:
    """Determine criticality for an item."""
    # Check for explicit criticality marker
    if item.get('criticality') == 'must_know' or item.get('critical'):
        return Criticality.MUST_KNOW
    if item.get('criticality') == 'should_check':
        return Criticality.SHOULD_CHECK
    if item.get('criticality') == 'may_help':
        return Criticality.MAY_HELP

    # Check for markers that elevate criticality
    if item.get('is_critical') or item.get('blocking'):
        return Criticality.MUST_KNOW

    # High reuse count elevates insights to should_check
    if knowledge_type == KnowledgeType.INSIGHT and item.get('reuse_count', 0) >= 3:
        return Criticality.SHOULD_CHECK

    # Use default for type
    return DEFAULT_CRITICALITY.get(knowledge_type, Criticality.MAY_HELP)


def _determine_scope(item: Dict[str, Any], knowledge_type: KnowledgeType) -> Scope:
    """Determine scope for an item."""
    # Check for explicit scope marker
    if item.get('scope') == 'universal':
        return Scope.UNIVERSAL
    if item.get('scope') == 'intent_bound':
        return Scope.INTENT_BOUND

    # Unresolved conflicts are universal
    if knowledge_type == KnowledgeType.CONFLICT:
        if item.get('status', 'open') == 'open':
            return Scope.UNIVERSAL

    # Use default for type
    return DEFAULT_SCOPE.get(knowledge_type, Scope.SUBJECT_BOUND)


def _determine_trust(item: Dict[str, Any], knowledge_type: KnowledgeType) -> Trust:
    """Determine trust level for an item."""
    # Check for explicit trust marker
    if item.get('trust'):
        trust_map = {
            'verified': Trust.VERIFIED,
            'active': Trust.ACTIVE,
            'experimental': Trust.EXPERIMENTAL,
            'historical': Trust.HISTORICAL,
        }
        return trust_map.get(item['trust'], Trust.ACTIVE)

    # Superseded items are historical
    if item.get('superseded'):
        return Trust.HISTORICAL

    # High reuse count indicates verified
    if item.get('reuse_count', 0) >= 5:
        return Trust.VERIFIED

    # Use default
    return DEFAULT_TRUST.get(knowledge_type, Trust.ACTIVE)


def _generate_id(text: str) -> str:
    """Generate a stable ID from text."""
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """Parse timestamp from various formats."""
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except:
        return None


def get_tier_display(criticality: Criticality) -> tuple:
    """Get display info for a criticality tier."""
    displays = {
        Criticality.MUST_KNOW: ("🔴", "MUST KNOW"),
        Criticality.SHOULD_CHECK: ("🟡", "CHECK FIRST"),
        Criticality.MAY_HELP: ("🔵", "CONTEXT"),
    }
    return displays.get(criticality, ("❓", "UNKNOWN"))
