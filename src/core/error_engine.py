"""
FixOnce Error Engine - "Git for debugging history"

Transport-independent error matching system.
Makes developers feel: "I've seen this error before."

Core responsibilities:
- Normalize errors (extract patterns, remove noise)
- Find similar solved bugs (across all sources)
- Rank matches (by similarity, recency, success rate)
- Select auto-fix candidates (high-confidence matches)

This module is the single source of truth for error matching.
MCP, REST API, Dashboard, CLI, and tests are adapters.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import re


@dataclass
class NormalizedError:
    """An error normalized for matching."""
    original: str
    normalized: str
    error_type: Optional[str] = None
    file_reference: Optional[str] = None
    line_number: Optional[int] = None
    key_tokens: List[str] = field(default_factory=list)


@dataclass
class ErrorMatch:
    """A matched solution for an error."""
    error_text: str
    solution_text: str
    similarity: int  # 0-100
    confidence: int  # 0-100
    source: str  # "debug_session", "semantic", "db", "exact"
    files_changed: List[str] = field(default_factory=list)
    root_cause: Optional[str] = None
    lesson_learned: Optional[str] = None
    reuse_count: int = 0
    resolved_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorAnalysis:
    """Complete analysis of an error."""
    error: NormalizedError
    matches: List[ErrorMatch]
    auto_fix_ready: bool = False
    suggested_fix: Optional[ErrorMatch] = None
    diagnostic: Optional[str] = None


# Confidence thresholds (aligned with pending_fixes.py)
AUTO_FIX_THRESHOLD = 90
SUGGEST_THRESHOLD = 70

# Error type patterns
ERROR_TYPE_PATTERNS = [
    (r'TypeError', 'type_error'),
    (r'ReferenceError', 'reference_error'),
    (r'SyntaxError', 'syntax_error'),
    (r'NetworkError|Failed to fetch|CORS', 'network_error'),
    (r'null|undefined|Cannot read|is not defined', 'null_reference'),
    (r'ModuleNotFoundError|ImportError', 'import_error'),
    (r'KeyError|IndexError', 'key_error'),
    (r'TimeoutError|timeout', 'timeout'),
]

# File reference patterns
FILE_PATTERNS = [
    r'at\s+(\S+\.(?:js|ts|jsx|tsx|py|rb|go)):(\d+)',
    r'File "([^"]+)", line (\d+)',
    r'in\s+(\S+\.(?:js|ts|jsx|tsx|py|rb|go)):(\d+)',
    r'(\S+\.(?:js|ts|jsx|tsx|py|rb|go)):(\d+):\d+',
]

# Noise words to filter from matching
NOISE_WORDS = frozenset({
    'error', 'failed', 'cannot', 'undefined', 'null', 'is', 'not',
    'the', 'a', 'an', 'to', 'of', 'in', 'at', 'on', 'for', 'with',
    'was', 'been', 'has', 'have', 'from', 'be', 'are', 'were',
})


def normalize_error(error_text: str) -> NormalizedError:
    """
    Normalize an error message for matching.

    Extracts:
    - Error type (TypeError, ReferenceError, etc.)
    - File reference and line number
    - Key tokens for matching
    """
    if not error_text:
        return NormalizedError(original="", normalized="")

    original = str(error_text)
    text = original

    # Extract error type
    error_type = None
    for pattern, etype in ERROR_TYPE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            error_type = etype
            break

    # Extract file reference
    file_ref = None
    line_num = None
    for pattern in FILE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            file_ref = match.group(1)
            line_num = int(match.group(2))
            break

    # Normalize text
    normalized = text.lower()
    normalized = re.sub(r'at\s+\S+:\d+:\d+', '', normalized)  # Remove stack traces
    normalized = re.sub(r'0x[0-9a-f]+', '', normalized)  # Remove hex addresses
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}', '', normalized)  # Remove dates
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    # Extract key tokens
    words = set(re.findall(r'\b[a-z]{3,}\b', normalized))
    key_tokens = sorted(words - NOISE_WORDS)

    return NormalizedError(
        original=original,
        normalized=normalized,
        error_type=error_type,
        file_reference=file_ref,
        line_number=line_num,
        key_tokens=key_tokens[:10],
    )


def calculate_error_similarity(error1: str, error2: str) -> int:
    """
    Calculate similarity between two error messages.
    Returns 0-100.
    """
    if not error1 or not error2:
        return 0

    norm1 = normalize_error(error1)
    norm2 = normalize_error(error2)

    # Exact match
    if norm1.normalized == norm2.normalized:
        return 100

    # Token overlap
    tokens1 = set(norm1.key_tokens)
    tokens2 = set(norm2.key_tokens)

    if not tokens1 or not tokens2:
        return 0

    common = tokens1 & tokens2
    union = tokens1 | tokens2

    jaccard = len(common) / len(union) if union else 0
    base_score = int(jaccard * 80)

    # Bonus for same error type
    if norm1.error_type and norm1.error_type == norm2.error_type:
        base_score = min(100, base_score + 15)

    # Bonus for same file
    if norm1.file_reference and norm1.file_reference == norm2.file_reference:
        base_score = min(100, base_score + 10)

    return base_score


def find_matching_solutions(
    error_text: str,
    debug_sessions: List[Dict[str, Any]],
    semantic_search_fn: Optional[callable] = None,
    project_id: Optional[str] = None,
    limit: int = 5,
) -> List[ErrorMatch]:
    """
    Find solutions that match an error.

    Searches:
    1. debug_sessions (project memory)
    2. Semantic index (if available)

    Args:
        error_text: The error message to match
        debug_sessions: List of past debug sessions with solutions
        semantic_search_fn: Optional semantic search function
        project_id: Project ID for semantic search
        limit: Max matches to return

    Returns:
        List of ErrorMatch sorted by confidence (highest first)
    """
    matches: List[ErrorMatch] = []
    normalized = normalize_error(error_text)

    # Search debug_sessions
    for ds in debug_sessions:
        problem = ds.get('problem', '')
        solution = ds.get('solution', '')

        if not problem or not solution:
            continue

        similarity = calculate_error_similarity(error_text, problem)

        # Also check symptoms
        symptoms = ds.get('symptoms', [])
        for symptom in symptoms:
            symptom_sim = calculate_error_similarity(error_text, symptom)
            similarity = max(similarity, symptom_sim)

        if similarity >= 30:  # Minimum threshold to include
            confidence = _calculate_confidence(similarity, ds)

            matches.append(ErrorMatch(
                error_text=problem,
                solution_text=solution,
                similarity=similarity,
                confidence=confidence,
                source="debug_session",
                files_changed=ds.get('files_changed', []),
                root_cause=ds.get('root_cause'),
                lesson_learned=ds.get('lesson_learned'),
                reuse_count=ds.get('reuse_count', 0),
                resolved_at=ds.get('resolved_at'),
                metadata=ds,
            ))

    # Semantic search if available
    if semantic_search_fn and project_id:
        try:
            results = semantic_search_fn(project_id, error_text, k=3, doc_type="error", min_score=0.5)
            for r in results:
                matches.append(ErrorMatch(
                    error_text=r.text,
                    solution_text=r.metadata.get('solution', ''),
                    similarity=int(r.score * 100),
                    confidence=int(r.score * 100),
                    source="semantic",
                    metadata=r.metadata,
                ))
        except Exception:
            pass

    # Deduplicate and sort
    matches = _deduplicate_matches(matches)
    matches.sort(key=lambda m: (m.confidence, m.similarity, m.reuse_count), reverse=True)

    return matches[:limit]


def analyze_error(
    error_text: str,
    debug_sessions: List[Dict[str, Any]],
    semantic_search_fn: Optional[callable] = None,
    project_id: Optional[str] = None,
) -> ErrorAnalysis:
    """
    Complete analysis of an error.

    Returns:
    - Normalized error
    - All matching solutions
    - Whether auto-fix is ready
    - Suggested fix (if any)
    - Diagnostic hint
    """
    normalized = normalize_error(error_text)
    matches = find_matching_solutions(
        error_text,
        debug_sessions,
        semantic_search_fn,
        project_id,
    )

    # Determine auto-fix and suggestion
    auto_fix_ready = False
    suggested_fix = None

    if matches:
        best = matches[0]
        if best.confidence >= AUTO_FIX_THRESHOLD:
            auto_fix_ready = True
            suggested_fix = best
        elif best.confidence >= SUGGEST_THRESHOLD:
            suggested_fix = best

    # Generate diagnostic
    diagnostic = _generate_diagnostic(normalized)

    return ErrorAnalysis(
        error=normalized,
        matches=matches,
        auto_fix_ready=auto_fix_ready,
        suggested_fix=suggested_fix,
        diagnostic=diagnostic,
    )


def select_auto_fix_candidates(
    errors: List[str],
    debug_sessions: List[Dict[str, Any]],
    semantic_search_fn: Optional[callable] = None,
    project_id: Optional[str] = None,
) -> List[Tuple[str, ErrorMatch]]:
    """
    From a list of errors, select those with auto-fix candidates.

    Returns list of (error_text, best_match) tuples for errors
    where confidence >= AUTO_FIX_THRESHOLD.
    """
    candidates = []

    for error in errors:
        analysis = analyze_error(
            error,
            debug_sessions,
            semantic_search_fn,
            project_id,
        )

        if analysis.auto_fix_ready and analysis.suggested_fix:
            candidates.append((error, analysis.suggested_fix))

    return candidates


def _calculate_confidence(similarity: int, debug_session: Dict[str, Any]) -> int:
    """
    Calculate confidence score based on similarity and solution history.
    """
    confidence = similarity

    # Bonus for reuse count (proven solution)
    reuse_count = debug_session.get('reuse_count', 0)
    if reuse_count >= 3:
        confidence = min(100, confidence + 15)
    elif reuse_count >= 1:
        confidence = min(100, confidence + 10)

    # Bonus for having root cause (well-understood fix)
    if debug_session.get('root_cause'):
        confidence = min(100, confidence + 5)

    # Bonus for having files_changed (concrete fix)
    if debug_session.get('files_changed'):
        confidence = min(100, confidence + 5)

    return confidence


def _generate_diagnostic(error: NormalizedError) -> Optional[str]:
    """Generate a diagnostic hint based on error type."""
    diagnostics = {
        'type_error': "Check: null/undefined value, wrong argument type",
        'reference_error': "Check: variable defined? typo in name?",
        'syntax_error': "Check: missing bracket, quote, or comma",
        'network_error': "Check: server running? CORS? endpoint exists?",
        'null_reference': "Check: value exists before accessing property",
        'import_error': "Check: module installed? path correct?",
        'key_error': "Check: key exists in dict/object?",
        'timeout': "Check: operation taking too long? increase timeout?",
    }
    return diagnostics.get(error.error_type)


def _deduplicate_matches(matches: List[ErrorMatch]) -> List[ErrorMatch]:
    """Remove duplicate matches based on solution text."""
    seen = set()
    unique = []

    for match in matches:
        key = match.solution_text[:100].lower()
        if key not in seen:
            seen.add(key)
            unique.append(match)

    return unique
