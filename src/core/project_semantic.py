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
        if decision.get('superseded'):
            continue
        if decision.get('status') not in (None, "", "active"):
            continue
        dec_text = decision.get('decision', '')
        reason = decision.get('reason', '')
        if dec_text:
            try:
                from core.decision_review import decision_id_for
                decision_id = decision_id_for(decision)
            except Exception:
                decision_id = decision.get('id', '')
            index.add("decision", f"{dec_text}. Reason: {reason}", {
                "decision_id": decision_id,
                "decision": dec_text,
                "reason": reason,
                "status": decision.get("status", "active"),
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

    # Index solved bugs (debug_sessions)
    for session in memory.get('debug_sessions', []):
        error = session.get('error', '')
        solution = session.get('solution', '')
        if error and solution:
            # Format: "Error: X. Solution: Y" for semantic matching
            full_text = f"Error: {error}. Solution: {solution}"
            index.add("error", full_text, {
                "error": error,
                "solution": solution,
                "files": session.get('files', ''),
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


# ============================================================
# DECISION LIFECYCLE SUPPORT
# ============================================================

def remove_decision(project_id: str, decision_text: str) -> bool:
    """
    Remove a decision from the semantic index by matching its text.

    Used when a decision is superseded to ensure stale entries
    don't appear in search results.

    Args:
        project_id: Project identifier
        decision_text: The decision text to remove (partial match OK)

    Returns:
        True if removed, False if not found
    """
    index = _get_index(project_id)
    index._ensure_loaded()

    # Find matching decision documents
    removed = False
    for doc in list(index._documents):
        if doc.doc_type != "decision":
            continue
        # Match by decision text in metadata or full text
        doc_decision = doc.metadata.get("decision", "")
        if decision_text in doc_decision or decision_text in doc.text:
            if index.delete(doc.id):
                removed = True
                print(f"[project_semantic] Removed superseded decision: {doc.id}")

    return removed


def remove_decision_by_id(project_id: str, decision_id: str) -> bool:
    """
    Remove a decision from the semantic index by its decision_id.

    Args:
        project_id: Project identifier
        decision_id: The decision_id (e.g., "dec_abc123")

    Returns:
        True if removed, False if not found
    """
    index = _get_index(project_id)
    index._ensure_loaded()

    for doc in list(index._documents):
        if doc.doc_type != "decision":
            continue
        if doc.metadata.get("decision_id") == decision_id:
            if index.delete(doc.id):
                print(f"[project_semantic] Removed decision by ID: {decision_id}")
                return True

    return False


def supersede_decision_in_index(
    project_id: str,
    old_decision_text: str,
    new_decision: str,
    new_reason: str,
    new_decision_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Atomically supersede a decision in the semantic index.

    Removes the old decision and indexes the new one in a single operation.
    If the new indexing fails, the operation is rolled back.

    Args:
        project_id: Project identifier
        old_decision_text: Text of the decision to supersede
        new_decision: New decision text (empty string = deprecate only)
        new_reason: Reason for new decision
        new_decision_id: Optional ID for new decision

    Returns:
        Dict with status, old_removed, new_indexed flags
    """
    index = _get_index(project_id)
    index._ensure_loaded()

    result = {
        "status": "ok",
        "old_removed": False,
        "new_indexed": False,
        "old_doc_id": None,
        "new_doc_id": None,
    }

    # Find and remove old decision
    old_doc = None
    old_doc_idx = None
    old_vector = None

    for i, doc in enumerate(index._documents):
        if doc.doc_type != "decision":
            continue
        doc_decision = doc.metadata.get("decision", "")
        if old_decision_text in doc_decision or old_decision_text in doc.text:
            old_doc = doc
            old_doc_idx = i
            old_vector = index._vectors[i].copy() if len(index._vectors) > i else None
            break

    if old_doc:
        result["old_doc_id"] = old_doc.id
        # Remove from index
        index._documents.pop(old_doc_idx)
        import numpy as np
        index._vectors = np.delete(index._vectors, old_doc_idx, axis=0)
        result["old_removed"] = True

    # Index new decision if provided
    if new_decision:
        try:
            full_text = f"{new_decision}. Reason: {new_reason}"
            meta = {
                "decision": new_decision,
                "reason": new_reason,
                "status": "active",
            }
            if new_decision_id:
                meta["decision_id"] = new_decision_id

            new_doc_id = index.add("decision", full_text, meta)
            result["new_doc_id"] = new_doc_id
            result["new_indexed"] = True
        except Exception as e:
            # Rollback: restore old document
            if old_doc and old_vector is not None:
                import numpy as np
                index._documents.insert(old_doc_idx, old_doc)
                if len(index._vectors) == 0:
                    index._vectors = old_vector.reshape(1, -1)
                else:
                    index._vectors = np.insert(index._vectors, old_doc_idx, old_vector, axis=0)
                index._save_index()
                result["old_removed"] = False  # Rolled back
            result["status"] = "error"
            result["error"] = str(e)
            return result
    else:
        # Just save after removal (deprecate only)
        if result["old_removed"]:
            index._save_index()

    return result


def rebuild_decisions_only(project_id: str) -> Dict[str, Any]:
    """
    Rebuild only decision entries in the semantic index from project memory.

    Preserves non-decision entries (insights, errors, avoid patterns).
    Use this to repair stale decision indexes without losing other data.

    Args:
        project_id: Project identifier

    Returns:
        Stats about the rebuild
    """
    import json
    import numpy as np

    # Load project memory - try multi_project_manager first (handles ~/.fixonce path)
    memory = None
    try:
        from managers.multi_project_manager import load_project_memory
        memory = load_project_memory(project_id)
    except Exception:
        pass

    # Fallback to ProjectContext path
    if not memory:
        from .project_context import ProjectContext
        project_file = ProjectContext.get_project_file(project_id)
        if not project_file.exists():
            return {"status": "error", "message": "Project not found"}
        with open(project_file, 'r', encoding='utf-8') as f:
            memory = json.load(f)

    if not memory:
        return {"status": "error", "message": "Project not found"}

    index = _get_index(project_id)
    index._ensure_loaded()

    # Remove all existing decision documents
    decisions_removed = 0
    non_decision_docs = []
    non_decision_vectors = []

    for i, doc in enumerate(index._documents):
        if doc.doc_type == "decision":
            decisions_removed += 1
        else:
            non_decision_docs.append(doc)
            if len(index._vectors) > i:
                non_decision_vectors.append(index._vectors[i])

    # Keep only non-decision documents
    index._documents = non_decision_docs
    if non_decision_vectors:
        index._vectors = np.array(non_decision_vectors)
    else:
        index._vectors = np.array([]).reshape(0, index.provider.dimension)

    # Re-index active decisions from memory
    decisions_added = 0
    for decision in memory.get('decisions', []):
        # Skip superseded decisions
        if decision.get('superseded'):
            continue
        if decision.get('status') not in (None, "", "active"):
            continue

        dec_text = decision.get('decision', '')
        reason = decision.get('reason', '')
        if not dec_text:
            continue

        try:
            from core.decision_review import decision_id_for
            decision_id = decision_id_for(decision)
        except Exception:
            decision_id = decision.get('id', '')

        full_text = f"{dec_text}. Reason: {reason}"
        index.add("decision", full_text, {
            "decision_id": decision_id,
            "decision": dec_text,
            "reason": reason,
            "status": "active",
        })
        decisions_added += 1

    return {
        "status": "ok",
        "project_id": project_id,
        "decisions_removed": decisions_removed,
        "decisions_added": decisions_added,
        "total_documents": len(index._documents),
        "stats": index.stats()
    }


def search_active_decisions(
    project_id: str,
    query: str,
    k: int = 5,
    min_score: float = 0.3
) -> List[SearchResult]:
    """
    Search for active decisions only (excludes superseded).

    This is the recommended search method for decision conflicts
    because it guarantees no superseded decisions are returned.

    Args:
        project_id: Project identifier
        query: Search query
        k: Number of results
        min_score: Minimum similarity score

    Returns:
        List of SearchResults for active decisions only
    """
    results = search_project(project_id, query, k=k, doc_type="decision", min_score=min_score)

    # Filter out any that might have status != active in metadata
    active_results = []
    for r in results:
        status = r.metadata.get("status", "active")
        if status == "active":
            active_results.append(r)

    return active_results
