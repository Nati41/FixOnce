"""
Semantic Indexing Queue - Deferred, best-effort indexing.

Semantic indexing is valuable but NOT authoritative. The JSON/V2 write
is always the source of truth. This module provides:

1. Bounded worker thread (single) for background indexing
2. Job deduplication by (project_id, record_type, record_id)
3. Non-blocking enqueue that never delays memory writes
4. Graceful failure handling (logged, not propagated)

Usage:
    from core.semantic_queue import enqueue_index_job

    # After successful memory write:
    enqueue_index_job("project_123", "decision", "dec_001", "Use PostgreSQL", "Better scale")
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger(__name__)

# Job queue and worker state
_job_queue: queue.Queue["IndexJob"] = queue.Queue(maxsize=1000)
_pending_jobs: Set[str] = set()  # For deduplication
_pending_lock = threading.Lock()
_worker_thread: Optional[threading.Thread] = None
_worker_started = threading.Event()
_shutdown_requested = False

# Provider state - lazy loaded
_provider_ready = threading.Event()
_provider_loading = False
_provider_load_lock = threading.Lock()


@dataclass
class IndexJob:
    """A semantic indexing job."""
    project_id: str
    record_type: str  # "decision", "avoid", "error", "insight"
    record_id: str
    text: str
    reason: str
    metadata: Dict[str, Any]
    timestamp: float

    @property
    def dedup_key(self) -> str:
        """Key for deduplication."""
        return f"{self.project_id}:{self.record_type}:{self.record_id}"


def _get_index_fn(record_type: str) -> Optional[Callable]:
    """Get the indexing function for a record type."""
    try:
        from core.project_semantic import (
            index_decision,
            index_avoid,
            index_error,
            index_insight,
        )
        return {
            "decision": index_decision,
            "avoid": index_avoid,
            "error": index_error,
            "insight": index_insight,
        }.get(record_type)
    except ImportError:
        return None


def _ensure_provider_loaded():
    """Ensure embedding provider is loaded (blocking, for worker thread only)."""
    global _provider_loading

    if _provider_ready.is_set():
        return True

    with _provider_load_lock:
        if _provider_ready.is_set():
            return True

        if _provider_loading:
            # Another thread is loading, wait for it
            _provider_load_lock.release()
            try:
                return _provider_ready.wait(timeout=120)  # 2 min max
            finally:
                _provider_load_lock.acquire()

        _provider_loading = True

    try:
        logger.info("[SemanticQueue] Loading embedding provider...")
        start = time.time()

        from core.project_semantic import _get_provider
        _get_provider()  # This triggers model download/load

        elapsed = time.time() - start
        logger.info(f"[SemanticQueue] Provider loaded in {elapsed:.1f}s")
        _provider_ready.set()
        return True
    except Exception as e:
        logger.error(f"[SemanticQueue] Failed to load provider: {e}")
        return False
    finally:
        with _provider_load_lock:
            _provider_loading = False


def _worker_loop():
    """Background worker that processes indexing jobs."""
    global _shutdown_requested

    logger.info("[SemanticQueue] Worker started")

    while not _shutdown_requested:
        try:
            # Wait for a job with timeout (allows checking shutdown)
            try:
                job = _job_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # Remove from pending set
            with _pending_lock:
                _pending_jobs.discard(job.dedup_key)

            # Ensure provider is loaded (first job triggers load)
            if not _ensure_provider_loaded():
                logger.warning(f"[SemanticQueue] Skipping job {job.dedup_key} - provider unavailable")
                _job_queue.task_done()
                continue

            # Get the indexing function
            index_fn = _get_index_fn(job.record_type)
            if not index_fn:
                logger.warning(f"[SemanticQueue] Unknown record type: {job.record_type}")
                _job_queue.task_done()
                continue

            # Execute indexing
            try:
                if job.record_type == "decision":
                    index_fn(job.project_id, job.text, job.reason, job.metadata)
                elif job.record_type == "avoid":
                    index_fn(job.project_id, job.text, job.reason, job.metadata)
                elif job.record_type == "error":
                    full_text = f"Error: {job.text}. Solution: {job.reason}"
                    index_fn(job.project_id, full_text, job.metadata)
                elif job.record_type == "insight":
                    index_fn(job.project_id, job.text, job.metadata)

                logger.debug(f"[SemanticQueue] Indexed {job.record_type} {job.record_id}")
            except Exception as e:
                logger.error(f"[SemanticQueue] Failed to index {job.dedup_key}: {e}")

            _job_queue.task_done()

        except Exception as e:
            logger.error(f"[SemanticQueue] Worker error: {e}")
            time.sleep(0.5)  # Prevent tight error loop

    logger.info("[SemanticQueue] Worker stopped")


def _ensure_worker_started():
    """Start the worker thread if not already running."""
    global _worker_thread

    if _worker_started.is_set():
        return

    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="SemanticIndexWorker",
        daemon=True,
    )
    _worker_thread.start()
    _worker_started.set()


def enqueue_index_job(
    project_id: str,
    record_type: str,
    record_id: str,
    text: str,
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Enqueue a semantic indexing job (non-blocking).

    This is called AFTER the authoritative JSON/V2 write completes.
    Returns immediately - never blocks memory operations.

    Args:
        project_id: Project identifier
        record_type: "decision", "avoid", "error", "insight"
        record_id: Unique ID for deduplication
        text: Main text to index
        reason: Reason/solution (for decision/avoid/error)
        metadata: Additional metadata

    Returns:
        True if enqueued, False if duplicate or queue full
    """
    job = IndexJob(
        project_id=project_id,
        record_type=record_type,
        record_id=record_id,
        text=text,
        reason=reason,
        metadata=metadata or {},
        timestamp=time.time(),
    )

    # Check for duplicate
    with _pending_lock:
        if job.dedup_key in _pending_jobs:
            logger.debug(f"[SemanticQueue] Skipping duplicate: {job.dedup_key}")
            return False
        _pending_jobs.add(job.dedup_key)

    # Try to enqueue (non-blocking)
    try:
        _job_queue.put_nowait(job)
        _ensure_worker_started()
        return True
    except queue.Full:
        with _pending_lock:
            _pending_jobs.discard(job.dedup_key)
        logger.warning(f"[SemanticQueue] Queue full, dropping: {job.dedup_key}")
        return False


def is_provider_ready() -> bool:
    """Check if the embedding provider is loaded and ready."""
    return _provider_ready.is_set()


def get_queue_stats() -> Dict[str, Any]:
    """Get queue statistics for diagnostics."""
    with _pending_lock:
        pending_count = len(_pending_jobs)

    return {
        "queue_size": _job_queue.qsize(),
        "pending_jobs": pending_count,
        "provider_ready": _provider_ready.is_set(),
        "worker_started": _worker_started.is_set(),
    }


def shutdown():
    """Shutdown the worker thread gracefully."""
    global _shutdown_requested
    _shutdown_requested = True

    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=5.0)


def preload_provider_async():
    """Start loading the embedding provider in background.

    Call this at server startup to warm up the provider
    before the first memory operation needs it.
    """
    def _preload():
        _ensure_provider_loaded()

    thread = threading.Thread(target=_preload, name="SemanticPreload", daemon=True)
    thread.start()
