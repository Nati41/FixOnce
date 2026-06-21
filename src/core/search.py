"""
Core search module for FixOnce memory.

Transport-independent search across project memory:
- Semantic search (when available)
- String matching fallback
- Multiple memory types (insights, decisions, solutions, avoid patterns)

This module is the single source of truth for search logic.
MCP, REST API, CLI, and tests are adapters.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from pathlib import Path
import re


@dataclass
class SearchMatch:
    """A single search result."""
    text: str
    match_type: str  # insight, decision, solution, avoid, activity, etc.
    similarity: int  # 0-100
    confidence: int  # 0-100
    metadata: Dict[str, Any] = field(default_factory=dict)
    use_count: int = 0
    files_changed: List[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """Complete search result with matches and navigation."""
    query: str
    matches: List[SearchMatch]
    code_targets: List[Dict[str, Any]] = field(default_factory=list)
    commits: List[Dict[str, Any]] = field(default_factory=list)


# Common noise words to filter from queries
NOISE_WORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
    'it', 'its', 'this', 'that', 'these', 'those', 'error', 'failed',
    'cannot', 'undefined', 'null', 'not', 'file', 'found', 'more'
})


def tokenize(text: str) -> Set[str]:
    """Extract meaningful tokens from text."""
    if not text:
        return set()
    words = set(re.findall(r'\b\w+\b', text.lower()))
    return words - NOISE_WORDS


def calculate_similarity(query: str, text: str) -> int:
    """Calculate similarity score between query and text (0-100)."""
    if not query or not text:
        return 0

    query_words = tokenize(query)
    text_words = tokenize(text)

    if not query_words:
        return 0

    common = query_words & text_words
    base_score = int((len(common) / len(query_words)) * 100)

    # Bonus for exact substring match
    if query.lower() in text.lower():
        base_score = min(100, base_score + 30)

    # Bonus for long unique tokens (likely meaningful)
    for word in common:
        if len(word) > 15:
            base_score = min(100, base_score + 40)
            break

    return base_score


def text_matches(query: str, query_tokens: Set[str], text: str) -> bool:
    """Check if text matches query via token overlap or substring."""
    if not query or not text:
        return False

    text_lower = text.lower()
    query_lower = query.lower()

    # Exact substring match
    if query_lower in text_lower:
        return True

    # Token overlap
    text_tokens = tokenize(text)
    common = query_tokens & text_tokens
    return len(common) >= 2 or (len(common) == 1 and len(query_tokens) == 1)


def search_memory(
    memory: Dict[str, Any],
    query: str,
    semantic_search_fn: Optional[callable] = None,
    project_id: Optional[str] = None,
    include_activity: bool = True,
    limit: int = 10,
) -> SearchResult:
    """
    Search across all memory types.

    Args:
        memory: Project memory dict
        query: Search query
        semantic_search_fn: Optional semantic search function(project_id, query, k, min_score)
        project_id: Project ID for semantic search
        include_activity: Whether to include activity log in search
        limit: Max results per category

    Returns:
        SearchResult with all matches
    """
    matches: List[SearchMatch] = []
    query_tokens = tokenize(query)

    # === Semantic search (if available) ===
    if semantic_search_fn and project_id:
        try:
            semantic_results = semantic_search_fn(project_id, query, k=5, min_score=0.3)
            for result in semantic_results:
                matches.append(SearchMatch(
                    text=result.text,
                    match_type=result.metadata.get('doc_type', 'insight'),
                    similarity=int(result.score * 100),
                    confidence=80,
                    metadata=result.metadata,
                ))
        except Exception:
            pass  # Fall through to string matching

    # === Search insights ===
    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])

    for insight in insights:
        text = _normalize_insight_text(insight)
        if text_matches(query, query_tokens, text):
            matches.append(SearchMatch(
                text=text,
                match_type='insight',
                similarity=calculate_similarity(query, text),
                confidence=75,
                metadata=insight if isinstance(insight, dict) else {},
            ))

    # === Search failed attempts ===
    failed = lessons.get('failed_attempts', [])
    for attempt in failed:
        text = _normalize_insight_text(attempt)
        if text_matches(query, query_tokens, text):
            matches.append(SearchMatch(
                text=f"❌ Failed attempt: {text}",
                match_type='failed_attempt',
                similarity=calculate_similarity(query, text),
                confidence=90,
                metadata=attempt if isinstance(attempt, dict) else {},
            ))

    # === Search debug_sessions (solutions) ===
    debug_sessions = memory.get('debug_sessions', [])
    for ds in debug_sessions:
        problem = ds.get('problem', '')
        solution = ds.get('solution', '')
        root_cause = ds.get('root_cause', '')
        lesson = ds.get('lesson_learned', '')
        symptoms = ds.get('symptoms', [])

        combined = f"{problem} {solution} {root_cause} {lesson} {' '.join(symptoms)}"

        if text_matches(query, query_tokens, combined):
            text = f"🐛 Problem: {problem}"
            if root_cause:
                text += f"\n🧭 Root cause: {root_cause}"
            text += f"\n✅ Solution: {solution}"
            if lesson:
                text += f"\n🧠 Lesson: {lesson}"

            matches.append(SearchMatch(
                text=text,
                match_type='solution',
                similarity=max(calculate_similarity(query, problem),
                             calculate_similarity(query, solution)),
                confidence=90,
                metadata=ds,
                use_count=ds.get('reuse_count', 1),
                files_changed=ds.get('files_changed', []),
            ))

    # === Search decisions ===
    decisions = memory.get('decisions', [])
    for dec in decisions:
        if dec.get('superseded'):
            continue

        dec_text = dec.get('decision', '')
        dec_reason = dec.get('reason', '')
        combined = f"{dec_text} {dec_reason}"

        if text_matches(query, query_tokens, combined):
            matches.append(SearchMatch(
                text=f"🔒 Decision: {dec_text}\n📝 Reason: {dec_reason}",
                match_type='decision',
                similarity=calculate_similarity(query, combined),
                confidence=95,
                metadata=dec,
            ))

    # === Search avoid patterns ===
    avoids = memory.get('avoid', [])
    for av in avoids:
        av_what = av.get('what', '')
        av_reason = av.get('reason', '')
        combined = f"{av_what} {av_reason}"

        if text_matches(query, query_tokens, combined):
            matches.append(SearchMatch(
                text=f"⛔ Avoid: {av_what}\n📝 Reason: {av_reason}",
                match_type='avoid',
                similarity=calculate_similarity(query, combined),
                confidence=95,
                metadata=av,
            ))

    # === Search intent/context ===
    intent = memory.get('live_record', {}).get('intent', {})
    intent_parts = [
        intent.get('current_goal', ''),
        intent.get('work_area', ''),
        intent.get('why', ''),
        intent.get('last_change', ''),
        intent.get('next_step', ''),
    ]
    intent_text = ' '.join(str(p) for p in intent_parts if p)

    if intent_text and text_matches(query, query_tokens, intent_text):
        matches.append(SearchMatch(
            text=f"🎯 Context: {intent_text[:300]}",
            match_type='context',
            similarity=calculate_similarity(query, intent_text),
            confidence=75,
            metadata=intent,
        ))

    # === Search component history ===
    components = memory.get('live_record', {}).get('architecture', {}).get('components', [])
    for comp in components:
        comp_parts = [comp.get('name', ''), comp.get('status', ''), comp.get('desc', '')]
        for hist in comp.get('history', []):
            if isinstance(hist, dict):
                comp_parts.extend([hist.get('action', ''), hist.get('desc', '')])
        comp_text = ' '.join(str(p) for p in comp_parts if p)

        if text_matches(query, query_tokens, comp_text):
            matches.append(SearchMatch(
                text=f"🧩 Component: {comp.get('name', '')}\n{comp.get('desc', '')}",
                match_type='component',
                similarity=calculate_similarity(query, comp_text),
                confidence=80,
                metadata=comp,
            ))

    # === Sort by relevance ===
    matches = _deduplicate_matches(matches)
    matches.sort(key=lambda m: (
        _type_priority(m.match_type),
        m.similarity,
        m.confidence,
    ), reverse=True)

    return SearchResult(
        query=query,
        matches=matches[:limit],
    )


def _normalize_insight_text(insight: Any) -> str:
    """Extract text from insight (string or dict)."""
    if isinstance(insight, str):
        return insight
    if isinstance(insight, dict):
        return insight.get('text', insight.get('insight', ''))
    return ''


def _type_priority(match_type: str) -> int:
    """Priority order for match types."""
    priorities = {
        'avoid': 100,
        'decision': 95,
        'solution': 90,
        'failed_attempt': 85,
        'insight': 80,
        'component': 70,
        'context': 60,
        'activity': 50,
    }
    return priorities.get(match_type, 0)


def _deduplicate_matches(matches: List[SearchMatch]) -> List[SearchMatch]:
    """Remove duplicate matches based on text similarity."""
    seen_texts = set()
    unique = []

    for match in matches:
        # Normalize text for comparison
        normalized = match.text.lower()[:100]
        if normalized not in seen_texts:
            seen_texts.add(normalized)
            unique.append(match)

    return unique
