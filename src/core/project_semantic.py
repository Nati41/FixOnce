"""
Project Semantic Integration

Connects SemanticIndex to project memory operations.
Automatically indexes insights, decisions, and errors.

Usage:
    from core.project_semantic import index_project_insight, search_project

    # Auto-index when adding insight
    index_project_insight(project_id, "Always validate input")

    # Search across project memory
    results = search_project(project_id, "validation")
"""

from typing import List, Optional, Dict, Any
from pathlib import Path

from .project_context import ProjectContext
from .semantic_index import SemanticIndex, SearchResult, get_project_index
from .embeddings import get_best_provider, EmbeddingProvider


# Cache for project indices
_index_cache: Dict[str, SemanticIndex] = {}

# Shared provider (loaded once)
_provider: Optional[EmbeddingProvider] = None


def _get_provider() -> EmbeddingProvider:
    """Get shared embedding provider."""
    global _provider
    if _provider is None:
        _provider = get_best_provider()
    return _provider


def _get_index(project_id: str) -> SemanticIndex:
    """Get or create index for project."""
    if project_id not in _index_cache:
        _index_cache[project_id] = SemanticIndex(project_id, _get_provider())
    return _index_cache[project_id]


# ============================================================
# PUBLIC API
# ============================================================

def index_insight(project_id: str, text: str, metadata: Optional[Dict] = None) -> str:
    """
    Index an insight for semantic search.

    Args:
        project_id: Project identifier
        text: Insight text
        metadata: Optional additional metadata

    Returns:
        Document ID
    """
    index = _get_index(project_id)
    return index.add("insight", text, metadata)


def index_decision(project_id: str, decision: str, reason: str, metadata: Optional[Dict] = None) -> str:
    """
    Index a decision for semantic search.

    Args:
        project_id: Project identifier
        decision: Decision text
        reason: Reason for decision
        metadata: Optional additional metadata

    Returns:
        Document ID
    """
    index = _get_index(project_id)
    full_text = f"{decision}. Reason: {reason}"
    meta = {"decision": decision, "reason": reason, **(metadata or {})}
    return index.add("decision", full_text, meta)


def index_error(project_id: str, error_message: str, metadata: Optional[Dict] = None) -> str:
    """
    Index an error for semantic search.

    Args:
        project_id: Project identifier
        error_message: Error message
        metadata: Optional additional metadata (file, line, etc.)

    Returns:
        Document ID
    """
    index = _get_index(project_id)
    return index.add("error", error_message, metadata)


def index_avoid(project_id: str, what: str, reason: str, metadata: Optional[Dict] = None) -> str:
    """
    Index an avoid pattern for semantic search.

    Args:
        project_id: Project identifier
        what: What to avoid
        reason: Why to avoid it
        metadata: Optional additional metadata

    Returns:
        Document ID
    """
    index = _get_index(project_id)
    full_text = f"Avoid: {what}. Reason: {reason}"
    meta = {"what": what, "reason": reason, **(metadata or {})}
    return index.add("avoid", full_text, meta)


def search_project(
    project_id: str,
    query: str,
    k: int = 5,
    doc_type: Optional[str] = None,
    min_score: float = 0.3
) -> List[SearchResult]:
    """
    Semantic search across project memory.

    Args:
        project_id: Project identifier
        query: Search query
        k: Number of results
        doc_type: Filter by type ("insight", "decision", "error", "avoid")
        min_score: Minimum similarity score

    Returns:
        List of SearchResults
    """
    index = _get_index(project_id)
    return index.search(query, k=k, doc_type=doc_type, min_score=min_score)


def search_similar_errors(project_id: str, error_message: str, k: int = 3) -> List[SearchResult]:
    """
    Find similar errors that were seen before.

    Args:
        project_id: Project identifier
        error_message: Current error message
        k: Number of results

    Returns:
        List of similar errors with solutions
    """
    index = _get_index(project_id)
    return index.search(error_message, k=k, doc_type="error", min_score=0.5)


def rebuild_project_index(project_id: str) -> Dict[str, Any]:
    """
    Rebuild semantic index for a project from its memory.

    Loads all insights, decisions, errors from project memory
    and indexes them.

    Args:
        project_id: Project identifier

    Returns:
        Stats about the rebuild
    """
    from .project_context import ProjectContext
    import json

    # Load project memory
    project_file = ProjectContext.get_project_file(project_id)
    if not project_file.exists():
        return {"status": "error", "message": "Project not found"}

    with open(project_file, 'r', encoding='utf-8') as f:
        memory = json.load(f)

    index = _get_index(project_id)
    index.clear()

    docs_added = 0

    # Index insights
    live_record = memory.get('live_record', {})
    lessons = live_record.get('lessons', {})
    insights = lessons.get('insights', [])

    for insight in insights:
        if isinstance(insight, str):
            text = insight
        elif isinstance(insight, dict):
            text = insight.get('text', insight.get('insight', ''))
        else:
            continue

        if text:
            index.add("insight", text)
            docs_added += 1

    # Index decisions
    for decision in memory.get('decisions', []):
        dec_text = decision.get('decision', '')
        reason = decision.get('reason', '')
        if dec_text:
            index.add("decision", f"{dec_text}. Reason: {reason}", {
                "decision": dec_text,
                "reason": reason
            })
            docs_added += 1

    # Index avoid patterns
    for avoid in memory.get('avoid', []):
        what = avoid.get('what', '')
        reason = avoid.get('reason', '')
        if what:
            index.add("avoid", f"Avoid: {what}. Reason: {reason}", {
                "what": what,
                "reason": reason
            })
            docs_added += 1

    return {
        "status": "ok",
        "project_id": project_id,
        "documents_indexed": docs_added,
        "stats": index.stats()
    }


def get_project_index_stats(project_id: str) -> Dict[str, Any]:
    """Get statistics for project's semantic index."""
    index = _get_index(project_id)
    return index.stats()


def clear_cache():
    """Clear index cache (for testing)."""
    global _index_cache, _provider
    _index_cache.clear()
    _provider = None
