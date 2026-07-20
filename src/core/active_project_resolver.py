"""
Active Project Resolver - Single Source of Truth

This module provides the ONLY way to determine and update the active project.
All code paths that read or write active_project.json MUST go through here.

Priority order (highest to lowest):
1. Verified live session from session_registry.json
2. Latest explicit project transition from boundary_state.json
3. active_project.json as cached snapshot
4. Stale ai_connections.json last_seen as final fallback

The dashboard must NEVER overwrite a newer active session with an older project.
"""

import json
import os
import threading
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List, Tuple

# Configure logging
logger = logging.getLogger("fixonce.active_project_resolver")

# Data paths
DATA_DIR = Path(
    os.environ.get("FIXONCE_USER_DATA_DIR", "").strip()
    or (Path.home() / ".fixonce")
).expanduser()

ACTIVE_PROJECT_FILE = DATA_DIR / "active_project.json"
SESSION_REGISTRY_FILE = DATA_DIR / "session_registry.json"
BOUNDARY_STATE_FILE = DATA_DIR / "boundary_state.json"
AI_CONNECTIONS_FILE = DATA_DIR / "ai_connections.json"

# Lock for atomic operations
_lock = threading.Lock()

# Session considered live if activity within this window
LIVE_SESSION_THRESHOLD_SECONDS = 300  # 5 minutes


@dataclass
class ResolvedProject:
    """Result of active project resolution."""
    project_id: Optional[str]
    display_name: Optional[str]
    working_dir: Optional[str]
    source: str  # "live_session", "boundary_transition", "cached", "ai_connection", "none"
    source_details: str  # Human-readable explanation
    confidence: str  # "verified", "recent", "stale"
    rejected_candidates: List[Dict[str, Any]] = field(default_factory=list)
    resolved_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_recent(timestamp: Optional[str], threshold_seconds: int = LIVE_SESSION_THRESHOLD_SECONDS) -> bool:
    """Check if timestamp is within threshold."""
    if not timestamp:
        return False
    try:
        ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if ts.tzinfo:
            ts = ts.replace(tzinfo=None)
        age = (datetime.now() - ts).total_seconds()
        return age <= threshold_seconds
    except Exception:
        return False


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Safely load JSON file."""
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {path.name}: {e}")
        return None


def _get_live_session() -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Get the most recent live session from session_registry.json.

    Returns:
        (session_data, rejection_reason) - session_data is None if no live session
    """
    data = _load_json_safe(SESSION_REGISTRY_FILE)
    if not data:
        return None, "session_registry.json not found"

    sessions = data.get("sessions", {})
    if not sessions:
        return None, "no sessions in registry"

    # Find most recent active session
    best_session = None
    best_activity = None

    for key, session in sessions.items():
        is_active = session.get("is_active", False)
        last_activity = session.get("last_activity")

        if not is_active:
            continue

        if not _is_recent(last_activity):
            continue

        if best_activity is None or last_activity > best_activity:
            best_session = session
            best_activity = last_activity

    if best_session:
        return best_session, ""

    return None, "no active sessions within threshold"


def _get_boundary_transition() -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Get the latest boundary transition from boundary_state.json.

    Returns:
        (transition_data, rejection_reason)
    """
    data = _load_json_safe(BOUNDARY_STATE_FILE)
    if not data:
        return None, "boundary_state.json not found"

    last_switch_to = data.get("last_switch_to")
    last_switch_timestamp = data.get("last_switch_timestamp")

    if not last_switch_to:
        return None, "no last_switch_to in boundary_state"

    if not _is_recent(last_switch_timestamp, threshold_seconds=600):  # 10 min for transitions
        return None, f"boundary transition too old: {last_switch_timestamp}"

    return {
        "project_id": last_switch_to,
        "timestamp": last_switch_timestamp,
        "from_project": data.get("last_switch_from"),
    }, ""


def _get_cached_active() -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Get cached active project from active_project.json.

    Returns:
        (cached_data, rejection_reason)
    """
    data = _load_json_safe(ACTIVE_PROJECT_FILE)
    if not data:
        return None, "active_project.json not found"

    active_id = data.get("active_id")
    if not active_id:
        return None, "no active_id in cached file"

    return data, ""


def _get_ai_connection_fallback() -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Get most recent AI connection as fallback.

    Returns:
        (connection_data, rejection_reason)
    """
    data = _load_json_safe(AI_CONNECTIONS_FILE)
    if not data:
        return None, "ai_connections.json not found"

    clients = data.get("clients", {})
    if not clients:
        return None, "no clients in ai_connections"

    # Find most recently seen client
    best_client = None
    best_seen = None

    for name, client in clients.items():
        last_seen = client.get("last_seen")
        project_id = client.get("project_id")

        if not project_id:
            continue

        if best_seen is None or (last_seen and last_seen > best_seen):
            best_client = {"name": name, **client}
            best_seen = last_seen

    if best_client:
        return best_client, ""

    return None, "no clients with project_id"


def resolve_active_project() -> ResolvedProject:
    """
    Resolve the active project using priority order.

    Priority:
    1. Verified live session from session_registry.json
    2. Latest explicit project transition from boundary_state.json
    3. active_project.json as cached snapshot
    4. Stale ai_connections.json last_seen as final fallback

    Returns:
        ResolvedProject with full resolution details
    """
    rejected = []

    # Priority 1: Live session
    session, reason = _get_live_session()
    if session:
        logger.info(f"Resolved from live_session: {session.get('project_id')} ({session.get('ai_name')})")
        return ResolvedProject(
            project_id=session.get("project_id"),
            display_name=Path(session.get("project_path", "")).name or session.get("project_id"),
            working_dir=session.get("project_path"),
            source="live_session",
            source_details=f"Active {session.get('ai_name')} session, last activity: {session.get('last_activity')}",
            confidence="verified",
            rejected_candidates=rejected,
        )
    else:
        rejected.append({"source": "live_session", "reason": reason})

    # Priority 2: Boundary transition
    transition, reason = _get_boundary_transition()
    if transition:
        logger.info(f"Resolved from boundary_transition: {transition.get('project_id')}")
        return ResolvedProject(
            project_id=transition.get("project_id"),
            display_name=None,  # Will be filled from project memory
            working_dir=None,
            source="boundary_transition",
            source_details=f"Recent transition from {transition.get('from_project')} at {transition.get('timestamp')}",
            confidence="recent",
            rejected_candidates=rejected,
        )
    else:
        rejected.append({"source": "boundary_transition", "reason": reason})

    # Priority 3: Cached active_project.json
    cached, reason = _get_cached_active()
    if cached:
        detected_at = cached.get("detected_at", "")
        logger.info(f"Resolved from cached: {cached.get('active_id')}")
        return ResolvedProject(
            project_id=cached.get("active_id"),
            display_name=cached.get("display_name"),
            working_dir=cached.get("working_dir"),
            source="cached",
            source_details=f"Cached from {cached.get('detected_from', 'unknown')} at {detected_at}",
            confidence="recent" if _is_recent(detected_at, 600) else "stale",
            rejected_candidates=rejected,
        )
    else:
        rejected.append({"source": "cached", "reason": reason})

    # Priority 4: AI connection fallback
    connection, reason = _get_ai_connection_fallback()
    if connection:
        logger.info(f"Resolved from ai_connection fallback: {connection.get('project_id')}")
        return ResolvedProject(
            project_id=connection.get("project_id"),
            display_name=None,
            working_dir=None,
            source="ai_connection",
            source_details=f"Fallback from {connection.get('name')} last seen: {connection.get('last_seen')}",
            confidence="stale",
            rejected_candidates=rejected,
        )
    else:
        rejected.append({"source": "ai_connection", "reason": reason})

    # No active project found
    logger.info("No active project resolved")
    return ResolvedProject(
        project_id=None,
        display_name=None,
        working_dir=None,
        source="none",
        source_details="No active project found from any source",
        confidence="stale",
        rejected_candidates=rejected,
    )


def update_active_project(
    project_id: str,
    detected_from: str,
    display_name: Optional[str] = None,
    working_dir: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Update the active project cache (active_project.json).

    IMPORTANT: This will NOT overwrite a newer live session unless force=True.

    Args:
        project_id: Project ID to set as active
        detected_from: Source of detection (e.g., "fo_init", "dashboard", "boundary")
        display_name: Optional display name
        working_dir: Optional working directory
        force: If True, skip live session check and force update

    Returns:
        Dict with update result including whether update was applied
    """
    with _lock:
        result = {
            "updated": False,
            "project_id": project_id,
            "previous_id": None,
            "reason": None,
        }

        # Check if there's a newer live session we shouldn't override
        if not force:
            resolved = resolve_active_project()

            if resolved.source == "live_session" and resolved.project_id != project_id:
                result["reason"] = (
                    f"Blocked: live session exists for {resolved.project_id} "
                    f"({resolved.source_details}). Use force=True to override."
                )
                logger.warning(f"Update blocked: {result['reason']}")
                return result

        # Load current for comparison
        current = _load_json_safe(ACTIVE_PROJECT_FILE) or {}
        result["previous_id"] = current.get("active_id")

        # Skip if already set to this project (unless forcing)
        if not force and current.get("active_id") == project_id:
            result["reason"] = "Already set to this project"
            result["updated"] = True  # Technically correct state
            return result

        # Prepare new data
        new_data = {
            "active_id": project_id,
            "detected_from": detected_from,
            "detected_at": datetime.now().isoformat(),
            "display_name": display_name or project_id,
            "working_dir": working_dir,
        }

        # Atomic write
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            temp_file = ACTIVE_PROJECT_FILE.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)
            temp_file.replace(ACTIVE_PROJECT_FILE)

            result["updated"] = True
            result["reason"] = f"Updated from {detected_from}"
            logger.info(
                f"Active project updated: {result['previous_id']} -> {project_id} "
                f"(from {detected_from})"
            )
        except Exception as e:
            result["reason"] = f"Write failed: {e}"
            logger.error(f"Failed to update active project: {e}")

        return result


def get_active_project_for_dashboard() -> Dict[str, Any]:
    """
    Get active project info formatted for dashboard display.

    This is the ONLY function the dashboard should use to determine
    which project to show.
    """
    resolved = resolve_active_project()

    # If we have a project, enrich with memory data
    memory_data = {}
    if resolved.project_id:
        try:
            project_file = DATA_DIR / "projects_v2" / f"{resolved.project_id}.json"
            if project_file.exists():
                with open(project_file, 'r', encoding='utf-8') as f:
                    memory = json.load(f)
                working_dir = (
                    memory.get("project_info", {}).get("working_dir") or
                    memory.get("live_record", {}).get("gps", {}).get("working_dir")
                )
                # Use CANONICAL provider for consistent counts
                if working_dir:
                    from core.knowledge_counters import get_canonical_knowledge_counts
                    canonical = get_canonical_knowledge_counts(working_dir)
                    decisions_count = canonical.decisions
                    avoid_count = canonical.avoid
                else:
                    decisions_count = len(memory.get("decisions", []))
                    avoid_count = len(memory.get("avoid", []))
                memory_data = {
                    "name": memory.get("project_info", {}).get("name"),
                    "working_dir": working_dir,
                    "decisions_count": decisions_count,
                    "avoid_count": avoid_count,
                }
        except Exception as e:
            logger.warning(f"Failed to load project memory: {e}")

    return {
        "active_id": resolved.project_id,
        "display_name": resolved.display_name or memory_data.get("name") or resolved.project_id,
        "working_dir": resolved.working_dir or memory_data.get("working_dir"),
        "source": resolved.source,
        "source_details": resolved.source_details,
        "confidence": resolved.confidence,
        "resolved_at": resolved.resolved_at,
        "rejected_candidates": resolved.rejected_candidates,
        "decisions_count": memory_data.get("decisions_count", 0),
        "avoid_count": memory_data.get("avoid_count", 0),
    }


def sync_cache_from_resolver() -> Dict[str, Any]:
    """
    Sync active_project.json cache from the resolver's determination.

    Call this when:
    - Dashboard starts
    - After major state changes
    - As part of catalog repair

    This ensures the cache reflects reality without overwriting live sessions.
    """
    resolved = resolve_active_project()

    if not resolved.project_id:
        return {"synced": False, "reason": "No active project to sync"}

    # Only sync if resolved from something other than cached
    # (if it came from cache, no sync needed)
    if resolved.source == "cached":
        return {"synced": False, "reason": "Already in sync (source was cache)"}

    # Update cache to match resolver's determination
    result = update_active_project(
        project_id=resolved.project_id,
        detected_from=f"sync_from_{resolved.source}",
        display_name=resolved.display_name,
        working_dir=resolved.working_dir,
        force=True,  # We trust the resolver
    )

    return {
        "synced": result["updated"],
        "project_id": resolved.project_id,
        "source": resolved.source,
        "reason": result.get("reason"),
    }
