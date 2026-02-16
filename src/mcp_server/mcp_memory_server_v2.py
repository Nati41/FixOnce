"""
MCP Server for FixOnce - V2 (Simplified)

Project ID = Working Directory. That's it.

Phase 0: Thread-safe sessions, no global state leakage.
Phase 1: Boundary detection as single source of truth for project identity.
"""

import sys
import os
import json
import hashlib
import subprocess
import threading
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Add src directory to path
SRC_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SRC_DIR))

from fastmcp import FastMCP

# Phase 1: Boundary detection imports
try:
    from core.boundary_detector import (
        find_project_root,
        detect_boundary_violation,
        handle_boundary_transition,
        is_within_boundary,
        BoundaryEvent
    )
    BOUNDARY_DETECTION_ENABLED = True
except ImportError as e:
    BOUNDARY_DETECTION_ENABLED = False
    print(f"[MCP] Boundary detection not available: {e}")

# Data directory
DATA_DIR = SRC_DIR.parent / "data" / "projects_v2"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Project index file (for caching)
INDEX_FILE = SRC_DIR.parent / "data" / "project_index.json"


# ============================================================
# PHASE 0: Thread-Local Session (No Global State)
# ============================================================

_session_local = threading.local()


class SessionContext:
    """Thread-safe session context with protocol compliance tracking."""

    def __init__(self, project_id: str = None, working_dir: str = None):
        self.project_id = project_id
        self.working_dir = working_dir
        # Protocol compliance tracking
        self.initialized_at = None
        self.decisions_displayed = False
        self.goal_updated = False
        self.tool_calls = []

    def __repr__(self):
        return f"SessionContext(project_id={self.project_id})"

    def is_active(self) -> bool:
        return self.project_id is not None

    def mark_initialized(self):
        self.initialized_at = datetime.now().isoformat()

    def mark_decisions_displayed(self):
        self.decisions_displayed = True
        # Will be synced to global state via _sync_compliance()

    def mark_goal_updated(self):
        self.goal_updated = True
        # Will be synced to global state via _sync_compliance()

    def log_tool_call(self, tool_name: str):
        self.tool_calls.append({
            "tool": tool_name,
            "timestamp": datetime.now().isoformat()
        })
        # Will be synced to global state via _sync_compliance()

    def get_compliance_status(self) -> dict:
        """Get protocol compliance status for dashboard."""
        return {
            "session_initialized": self.is_active(),
            "initialized_at": self.initialized_at,
            "decisions_displayed": self.decisions_displayed,
            "goal_updated": self.goal_updated,
            "tool_calls_count": len(self.tool_calls),
            "last_tool": self.tool_calls[-1] if self.tool_calls else None
        }


# Protocol compliance state (shared across threads for dashboard)
_compliance_state = {
    "last_session_init": None,
    "violations": [],
    "editor": None,
    "session_active": False,
    "initialized_at": None,
    "project_id": None
}


# Session persistence file (survives MCP restarts)
SESSION_FILE = SRC_DIR.parent / "data" / "mcp_session.json"


def _persist_session(project_id: str, working_dir: str):
    """Save current session to file for recovery after restart."""
    try:
        data = {
            "project_id": project_id,
            "working_dir": working_dir,
            "timestamp": datetime.now().isoformat()
        }
        with open(SESSION_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def _recover_session() -> Optional[tuple]:
    """Try to recover session from file. Returns (project_id, working_dir) or None."""
    try:
        if not SESSION_FILE.exists():
            return None

        with open(SESSION_FILE, 'r') as f:
            data = json.load(f)

        # Check if session is recent (within last hour)
        timestamp = datetime.fromisoformat(data.get("timestamp", ""))
        age_hours = (datetime.now() - timestamp).total_seconds() / 3600

        if age_hours < 1 and data.get("project_id") and data.get("working_dir"):
            return (data["project_id"], data["working_dir"])

        return None
    except Exception:
        return None


# ============================================================
# PHASE 2: UNIVERSAL GATE (Inversion of Control)
# ============================================================
# FixOnce is in control. Claude executes.
# - Auto-session: No manual init required
# - Context injection: Every response includes context
# - Error gate: Live errors are always visible
# ============================================================

def _get_active_project_from_api() -> Optional[dict]:
    """Get active project info from Flask API."""
    try:
        res = requests.get('http://localhost:5000/api/projects/active', timeout=2)
        if res.status_code == 200:
            return res.json()
        return None
    except Exception:
        return None


def _auto_create_session() -> bool:
    """
    Automatically create session from active project or last session.
    Returns True if session was created.
    """
    # 1. Try to recover from persisted session
    recovered = _recover_session()
    if recovered:
        project_id, working_dir = recovered
        _set_session(project_id, working_dir)
        session = _get_session()
        session.mark_initialized()
        print(f"[FixOnce] Auto-session from file: {project_id}")
        return True

    # 2. Try to get active project from API
    active = _get_active_project_from_api()
    if active and active.get('project_id'):
        project_id = active['project_id']
        # working_dir is nested in memory.project_info
        working_dir = active.get('memory', {}).get('project_info', {}).get('working_dir', '')
        _set_session(project_id, working_dir)
        session = _get_session()
        session.mark_initialized()
        _persist_session(project_id, working_dir)
        print(f"[FixOnce] Auto-session from API: {project_id}")
        return True

    return False


def _get_live_errors() -> list:
    """Get unacknowledged browser errors."""
    try:
        res = requests.get('http://localhost:5000/api/live-errors?since=600', timeout=2)
        if res.status_code == 200:
            data = res.json()
            return data.get('errors', [])[:5]  # Max 5
        return []
    except Exception:
        return []


def _build_context_header() -> str:
    """
    Build context header that gets injected into EVERY tool response.
    This is the core of "FixOnce in control".
    """
    lines = []
    session = _get_session()

    if not session.is_active():
        return ""

    # Load project data
    memory = _load_project(session.project_id)
    if not memory:
        return ""

    lr = memory.get('live_record', {})

    # 1. LIVE ERRORS (Always first if any)
    errors = _get_live_errors()
    if errors:
        lines.append("═══════════════════════════════════════")
        lines.append(f"⚠️ **{len(errors)} LIVE ERRORS** - FIX BEFORE PROCEEDING")
        lines.append("═══════════════════════════════════════")
        for e in errors[:3]:
            msg = e.get('message', 'Unknown error')[:80]
            lines.append(f"  • {msg}")
        if len(errors) > 3:
            lines.append(f"  • ...and {len(errors) - 3} more")
        lines.append("")

    # 2. Current context (compact)
    project_name = memory.get('project_info', {}).get('name', session.project_id)
    goal = lr.get('intent', {}).get('current_goal', '')

    lines.append(f"📍 **{project_name}**" + (f" | 🎯 {goal}" if goal else ""))

    # 3. Active decisions (compact, one line)
    decisions = memory.get('decisions', [])
    if decisions:
        recent_dec = decisions[-1]  # Most recent
        dec_text = recent_dec.get('decision', '')[:50]
        lines.append(f"🔒 {dec_text}")

    lines.append("───────────────────────────────────────")

    return '\n'.join(lines)


def _universal_gate(tool_name: str) -> tuple:
    """
    Universal gate for all MCP tools.

    Returns: (error_message, context_header)
    - If error_message is not None, tool should return it immediately
    - context_header should be prepended to tool response

    This replaces _require_session with auto-session + context injection.
    """
    session = _get_session()

    # AUTO-SESSION: Create session automatically if not active
    if not session.is_active():
        if _auto_create_session():
            session = _get_session()
        else:
            # Still no session - but don't block, just note it
            return (None, "⚠️ No active project. Use auto_init_session() for full features.\n")

    # Log tool call
    session.log_tool_call(tool_name)
    _sync_compliance()

    # BUILD CONTEXT HEADER (injected into response)
    context = _build_context_header()

    return (None, context)


# Legacy function for backward compatibility
def _require_session(tool_name: str) -> Optional[str]:
    """
    DEPRECATED: Use _universal_gate instead.
    Kept for backward compatibility during transition.
    """
    error, _ = _universal_gate(tool_name)
    return error


def _get_browser_errors_reminder() -> str:
    """Get reminder about browser errors if there are any recent ones."""
    try:
        res = requests.get('http://localhost:5000/api/live-errors?since=300', timeout=2)
        if res.status_code == 200:
            data = res.json()
            count = data.get('count', 0)
            if count > 0:
                return f"""

🚨 BROWSER ERRORS DETECTED: {count} errors!
═══════════════════════════════════════
You MUST call: get_browser_errors()
DO NOT ignore this - the user sees these errors!
═══════════════════════════════════════"""
        return ""
    except Exception:
        return ""


def _get_protocol_reminder() -> str:
    """Get periodic protocol reminder."""
    session = _get_session()
    if not session.is_active():
        return ""

    tool_count = len(session.tool_calls)

    # Every 5 tool calls, remind about browser errors
    if tool_count > 0 and tool_count % 5 == 0:
        return """

📋 PROTOCOL REMINDER (every 5 actions):
• Did you check get_browser_errors()?
• Did you update the goal if task changed?
• Are you using insights from init, not researching again?"""

    return ""


def _track_roi_event(event_type: str):
    """
    Track ROI event via Flask API.

    Events: session_context, solution_reused, decision_used, error_prevented
    """
    try:
        requests.post(
            "http://localhost:5000/api/memory/roi/track",
            json={"event": event_type},
            timeout=2
        )
    except Exception:
        pass  # Silent fail - don't block MCP operations


# ============================================================
# MEMORY DECAY SYSTEM
# ============================================================

def _create_insight(text: str) -> dict:
    """Create a new insight with full metadata for decay tracking."""
    return {
        "text": text,
        "timestamp": datetime.now().isoformat(),
        "use_count": 0,
        "last_used": None,
        "importance": "medium"  # low/medium/high - auto-calculated
    }


def _mark_insight_used(insight: dict) -> dict:
    """Mark an insight as used and update its importance."""
    insight["use_count"] = insight.get("use_count", 0) + 1
    insight["last_used"] = datetime.now().isoformat()

    # Auto-calculate importance based on use_count
    use_count = insight["use_count"]
    if use_count >= 5:
        insight["importance"] = "high"
    elif use_count >= 2:
        insight["importance"] = "medium"
    else:
        insight["importance"] = "low"

    return insight


def _normalize_insight(insight) -> dict:
    """Ensure insight has the new format with metadata."""
    if isinstance(insight, str):
        # Old format: just a string
        return _create_insight(insight)
    elif isinstance(insight, dict):
        # Might be old format with just 'text' or new format
        if "use_count" not in insight:
            # Old format with text/timestamp but no decay metadata
            text = insight.get("text", str(insight))
            new_insight = _create_insight(text)
            # Preserve original timestamp if it exists
            if "timestamp" in insight:
                new_insight["timestamp"] = insight["timestamp"]
            return new_insight
        return insight
    else:
        return _create_insight(str(insight))


def _calculate_insight_score(insight: dict) -> float:
    """
    Calculate a score for ranking insights.
    Higher score = more important/recent.
    """
    score = 0.0

    # Importance weight
    importance = insight.get("importance", "medium")
    if importance == "high":
        score += 100
    elif importance == "medium":
        score += 50
    else:
        score += 10

    # Use count bonus
    use_count = insight.get("use_count", 0)
    score += use_count * 10

    # Recency bonus (insights from last 7 days get boost)
    try:
        timestamp = insight.get("timestamp", "")
        if timestamp:
            created = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if created.tzinfo:
                created = created.replace(tzinfo=None)
            age_days = (datetime.now() - created).days
            if age_days <= 1:
                score += 50  # Today
            elif age_days <= 7:
                score += 30  # This week
            elif age_days <= 30:
                score += 10  # This month
    except Exception:
        pass

    return score


def _get_ranked_insights(insights: list, limit: int = 10) -> list:
    """Get top insights ranked by importance/recency/usage."""
    # Normalize all insights to new format
    normalized = [_normalize_insight(ins) for ins in insights]

    # Sort by score (highest first)
    ranked = sorted(normalized, key=_calculate_insight_score, reverse=True)

    return ranked[:limit]


def _should_archive_insight(insight: dict) -> bool:
    """
    Check if an insight should be archived (moved to cold storage).

    IMPORTANT: Decisions and avoid patterns should NEVER be archived.
    They are stored separately in memory['decisions'] and memory['avoid'],
    but this check ensures they're protected even if accidentally mixed in.
    """
    try:
        # NEVER archive decisions or avoid patterns - they are permanent institutional knowledge
        insight_type = insight.get("type", "insight")
        if insight_type in ("decision", "avoid", "failed_attempt"):
            return False

        # Never archive high-importance insights
        if insight.get("importance") == "high":
            return False

        # Never used and older than 30 days
        use_count = insight.get("use_count", 0)
        timestamp = insight.get("timestamp", "")

        if not timestamp:
            return False

        created = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if created.tzinfo:
            created = created.replace(tzinfo=None)
        age_days = (datetime.now() - created).days

        # Archive if: never used AND older than 30 days AND importance is low
        if use_count == 0 and age_days > 30 and insight.get("importance") == "low":
            return True

        # Archive if: not used in 60 days regardless (but only for low importance)
        last_used = insight.get("last_used")
        if last_used:
            last = datetime.fromisoformat(last_used.replace('Z', '+00:00'))
            if last.tzinfo:
                last = last.replace(tzinfo=None)
            unused_days = (datetime.now() - last).days
            if unused_days > 60 and insight.get("importance") != "medium":
                return True
        elif age_days > 60 and insight.get("importance") == "low":
            # Never used and very old - only for low importance
            return True

        return False
    except Exception:
        return False


def _get_session() -> SessionContext:
    """Get current session for this thread (never returns None)."""
    if not hasattr(_session_local, 'session') or _session_local.session is None:
        _session_local.session = SessionContext()
    return _session_local.session


def _set_session(project_id: str, working_dir: str):
    """Set session for current thread and update global state for dashboard."""
    _session_local.session = SessionContext(project_id, working_dir)
    # Sync to global state for Flask API (different thread)
    _compliance_state["session_active"] = True
    _compliance_state["initialized_at"] = datetime.now().isoformat()
    _compliance_state["project_id"] = project_id
    _compliance_state["last_session_init"] = datetime.now().isoformat()


def _clear_session():
    """Clear session for current thread and global state."""
    _session_local.session = SessionContext()
    # Clear global state
    _compliance_state["session_active"] = False
    _compliance_state["initialized_at"] = None
    _compliance_state["project_id"] = None


def _sync_compliance():
    """Sync session state to global _compliance_state for dashboard API."""
    session = _get_session()
    _compliance_state["decisions_displayed"] = session.decisions_displayed
    _compliance_state["goal_updated"] = session.goal_updated
    _compliance_state["tool_calls_count"] = len(session.tool_calls)


# ============================================================
# GIT UTILITIES
# ============================================================

def _get_git_commit_hash(working_dir: str) -> Optional[str]:
    """Get current git commit hash for a directory."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]  # Short hash
        return None
    except Exception:
        return None


def _is_git_repo(working_dir: str) -> bool:
    """Check if directory is a git repository."""
    git_dir = Path(working_dir) / '.git'
    return git_dir.exists()


# ============================================================
# PROJECT INDEX (Cache with git hash invalidation)
# ============================================================

def _load_index() -> Dict[str, Any]:
    """Load project index from disk."""
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"version": 1, "projects": {}}


def _save_index(index: Dict[str, Any]):
    """Save project index to disk."""
    index["updated_at"] = datetime.now().isoformat()
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _get_cached_snapshot(project_id: str, working_dir: str) -> Optional[Dict[str, Any]]:
    """
    Get cached snapshot if valid.
    Returns None if:
    - Not in cache
    - Git hash changed (code changed)
    """
    index = _load_index()
    snapshot = index.get("projects", {}).get(project_id)

    if not snapshot:
        return None

    # Check git hash if it's a git repo
    if _is_git_repo(working_dir):
        current_hash = _get_git_commit_hash(working_dir)
        cached_hash = snapshot.get("git_commit_hash")

        if current_hash and cached_hash and current_hash != cached_hash:
            # Code changed - invalidate cache
            return None

    return snapshot


def _update_snapshot(project_id: str, working_dir: str, data: Dict[str, Any]):
    """Update project snapshot in index."""
    index = _load_index()

    lr = data.get('live_record', {})

    snapshot = {
        "project_id": project_id,
        "working_dir": working_dir,
        "name": data.get('project_info', {}).get('name', Path(working_dir).name),
        "git_commit_hash": _get_git_commit_hash(working_dir) if _is_git_repo(working_dir) else None,
        "summary": lr.get('architecture', {}).get('summary', ''),
        "stack": lr.get('architecture', {}).get('stack', ''),
        "current_goal": lr.get('intent', {}).get('current_goal', ''),
        "last_insight": (lr.get('lessons', {}).get('insights', []) or [''])[-1] if lr.get('lessons', {}).get('insights') else '',
        "decisions_count": len(data.get('decisions', [])),
        "avoid_count": len(data.get('avoid', [])),
        "indexed_at": datetime.now().isoformat()
    }

    if "projects" not in index:
        index["projects"] = {}

    index["projects"][project_id] = snapshot
    _save_index(index)


# ============================================================
# MCP SERVER
# ============================================================

mcp = FastMCP("fixonce")


def _get_working_dir_from_port(port: int) -> Optional[str]:
    """Detect working directory from a running port using lsof."""
    try:
        # Get PID of process on port
        result = subprocess.run(
            ['lsof', '-i', f':{port}', '-t'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        pid = result.stdout.strip().split('\n')[0]

        # Get cwd of that process
        result = subprocess.run(
            ['lsof', '-p', pid],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None

        # Find cwd line
        for line in result.stdout.split('\n'):
            if ' cwd ' in line:
                # Extract path (last column)
                parts = line.split()
                if len(parts) >= 9:
                    path = parts[-1]
                    # Go up if we're in src/ or similar
                    if Path(path).name in ('src', 'dist', 'build', 'bin'):
                        path = str(Path(path).parent)
                    return path
        return None
    except Exception:
        return None


def _get_project_id(working_dir: str) -> str:
    """Convert working_dir to a safe project ID."""
    # Use hash of path for safe filename
    path_hash = hashlib.md5(working_dir.encode()).hexdigest()[:12]
    # Also keep readable name
    name = Path(working_dir).name
    return f"{name}_{path_hash}"


def _get_project_path(project_id: str) -> Path:
    """Get path to project memory file."""
    return DATA_DIR / f"{project_id}.json"


def _load_project(project_id: str) -> Dict[str, Any]:
    """Load project memory."""
    path = _get_project_path(project_id)
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_project(project_id: str, data: Dict[str, Any]):
    """Save project memory to V2 (canonical storage)."""
    path = _get_project_path(project_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Update index snapshot
    session = _get_session()
    if session.working_dir:
        _update_snapshot(project_id, session.working_dir, data)


def _init_project_memory(working_dir: str) -> Dict[str, Any]:
    """Create empty project memory."""
    return {
        "project_info": {
            "working_dir": working_dir,
            "name": Path(working_dir).name,
            "created_at": datetime.now().isoformat()
        },
        "live_record": {
            "gps": {
                "working_dir": working_dir,
                "active_ports": [],
                "url": "",
                "environment": "dev"
            },
            "architecture": {
                "summary": "",
                "stack": "",
                "key_flows": []
            },
            "intent": {
                "current_goal": "",
                "next_step": "",
                "blockers": []
            },
            "lessons": {
                "insights": [],
                "failed_attempts": []
            }
        },
        "decisions": [],
        "avoid": [],
        "errors": []
    }


def _is_meaningful_project(data: Dict[str, Any]) -> bool:
    """Check if project has meaningful data."""
    lr = data.get('live_record', {})

    # Has architecture info?
    arch = lr.get('architecture', {})
    if arch.get('summary', '').strip() or arch.get('description', '').strip() or arch.get('stack', '').strip():
        return True

    # Has lessons?
    if lr.get('lessons', {}).get('insights', []):
        return True

    # Has decisions?
    if data.get('decisions', []):
        return True

    return False


def _get_recent_activity_summary(working_dir: str, limit: int = 5) -> str:
    """Get recent activity summary for init_session response."""
    activity_file = SRC_DIR.parent / "data" / "activity_log.json"

    if not activity_file.exists():
        return ""

    try:
        with open(activity_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        activities = data.get('activities', [])
        if not activities:
            return ""

        # Filter to current project
        project_activities = []
        for act in activities:
            file_path = act.get('file', '')
            cwd = act.get('cwd', '')
            if working_dir and (file_path.startswith(working_dir) or cwd.startswith(working_dir)):
                project_activities.append(act)

        if not project_activities:
            return ""

        # Take last N
        recent = project_activities[:limit]

        lines = ["**📋 Recent Activity:**"]
        for act in recent:
            human_name = act.get('human_name', '')
            file_path = act.get('file', '')
            file_name = file_path.split('/')[-1] if file_path else ''

            if human_name and file_name:
                lines.append(f"  • {human_name} ({file_name})")
            elif file_name:
                lines.append(f"  • {file_name}")
            elif act.get('command'):
                lines.append(f"  • `{act['command'][:30]}`")

        return '\n'.join(lines)

    except Exception:
        return ""


# ============================================================
# MCP TOOLS
# ============================================================

def _get_active_port_from_dashboard() -> Optional[int]:
    """Read active project port from dashboard."""
    try:
        active_file = DATA_DIR.parent.parent / "data" / "active_project.json"
        if not active_file.exists():
            # Try alternate location
            active_file = SRC_DIR.parent / "data" / "active_project.json"

        if active_file.exists():
            with open(active_file, 'r') as f:
                data = json.load(f)
                # Extract port from "localhost-5000" or "localhost:5000"
                active_id = data.get('active_id', '') or data.get('display_name', '')
                for sep in ['-', ':']:
                    if sep in active_id:
                        try:
                            return int(active_id.split(sep)[-1])
                        except ValueError:
                            pass
        return None
    except Exception:
        return None


@mcp.tool()
def auto_init_session(cwd: str = "") -> str:
    """
    Automatically initialize session for the current project.

    Phase 1: Uses boundary detection as single source of truth.
    - Detects actual project root from cwd (not just uses cwd directly)
    - Compares against active project
    - Triggers boundary transition if needed

    Args:
        cwd: Optional current working directory from Claude Code

    Returns:
        Session info with project details
    """
    working_dir = None
    boundary_triggered = False

    # Phase 1: Use boundary detection to find actual project root
    if BOUNDARY_DETECTION_ENABLED and cwd and os.path.isdir(cwd):
        # Find the actual project root from cwd
        project_root, marker, confidence = find_project_root(cwd)

        if project_root and confidence in ("high", "medium"):
            # We found a valid project root
            # Check if it's different from current active project
            from core.boundary_detector import _load_active_project
            active = _load_active_project()
            active_working_dir = active.get("working_dir")

            if active_working_dir:
                # Compare: is this a different project?
                if not is_within_boundary(project_root, active_working_dir):
                    # Different project! Check if we should switch
                    # Create a synthetic boundary event for the session start
                    print(f"[MCP] Session init boundary check:")
                    print(f"  CWD: {cwd}")
                    print(f"  Detected root: {project_root}")
                    print(f"  Active project: {active_working_dir}")
                    print(f"  Confidence: {confidence}")

                    # Trigger boundary transition
                    from core.boundary_detector import _get_project_id_from_path, _load_boundary_state, _is_cooldown_active

                    state = _load_boundary_state()
                    new_project_id = _get_project_id_from_path(project_root)

                    # Check cooldown and anti-ping-pong
                    if not _is_cooldown_active(state) and state.get("last_switch_from") != new_project_id:
                        event = BoundaryEvent(
                            old_project_id=active.get("active_id", ""),
                            old_working_dir=active_working_dir,
                            new_project_id=new_project_id,
                            new_working_dir=project_root,
                            file_path=cwd,
                            reason="session_init",
                            confidence=confidence,
                            timestamp=datetime.now().isoformat()
                        )
                        handle_boundary_transition(event)
                        boundary_triggered = True
                        print(f"  Action: SWITCH to {project_root}")

            working_dir = project_root
        elif _is_valid_project_dir(cwd):
            # No strong marker but cwd itself is valid
            working_dir = cwd

    # Fallback: Original priority logic if boundary detection didn't find anything
    if not working_dir:
        # Priority 1: Use cwd if provided and valid (but NOT home directory)
        home_dir = str(Path.home())
        if cwd and os.path.isdir(cwd) and cwd != home_dir and _is_valid_project_dir(cwd):
            working_dir = cwd

    if not working_dir:
        # Priority 2: Check dashboard's active project directly
        # This handles the case where Claude sends home dir as cwd
        try:
            from core.boundary_detector import _load_active_project
            active = _load_active_project()
            active_working_dir = active.get("working_dir")
            if active_working_dir and os.path.isdir(active_working_dir):
                print(f"[MCP] Using dashboard's active project: {active_working_dir}")
                working_dir = active_working_dir
        except Exception as e:
            print(f"[MCP] Could not load active project: {e}")

    if not working_dir:
        # Priority 3: Try dashboard's active port
        port = _get_active_port_from_dashboard()
        if port:
            working_dir = _get_working_dir_from_port(port)

    if not working_dir:
        # Priority 4: Get from most recent activity
        working_dir = _get_working_dir_from_recent_activity()

    if working_dir:
        return _do_init_session(working_dir)

    # Priority 5: Ask user
    return """לא מצאתי פרויקט פעיל.

אפשרויות:
1. `init_session(working_dir="/path/to/project")` - עם נתיב
2. `init_session(port=5000)` - עם פורט של שרת רץ
3. פתח פרויקט בדשבורד של FixOnce"""


def _is_valid_project_dir(path: str) -> bool:
    """Check if path is a valid project directory (not home, not root, has project files)."""
    p = Path(path)

    # Reject home directory and root
    if str(p) == str(Path.home()) or str(p) == "/":
        return False

    # Check for common project markers
    project_markers = [
        '.git', 'package.json', 'pyproject.toml', 'Cargo.toml',
        'go.mod', 'pom.xml', 'build.gradle', 'Makefile',
        'requirements.txt', 'setup.py', '.project', 'CLAUDE.md'
    ]

    for marker in project_markers:
        if (p / marker).exists():
            return True

    # Check if it has source files (not just random dir)
    source_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java', '.rb'}
    try:
        for f in p.iterdir():
            if f.is_file() and f.suffix in source_extensions:
                return True
    except PermissionError:
        pass

    return False


def _get_working_dir_from_recent_activity() -> Optional[str]:
    """Get the most recent project directory from activity log."""
    try:
        activity_file = SRC_DIR.parent / "data" / "activity_log.json"
        if not activity_file.exists():
            return None

        with open(activity_file, 'r') as f:
            data = json.load(f)

        activities = data.get('activities', [])
        if not activities:
            return None

        # Find the most recent activity with a valid cwd
        for act in activities:
            cwd = act.get('cwd', '')
            if cwd and os.path.isdir(cwd) and _is_valid_project_dir(cwd):
                return cwd

        return None
    except Exception:
        return None


def _do_init_session(working_dir: str) -> str:
    """Internal init session logic - thread-safe, no global state."""
    if not working_dir or not os.path.isdir(working_dir):
        return f"Error: Invalid working directory: {working_dir}"

    project_id = _get_project_id(working_dir)

    # Set thread-local session
    _set_session(project_id, working_dir)

    # Persist session to file for recovery after MCP restart
    _persist_session(project_id, working_dir)

    # Mark session as initialized for compliance tracking
    session = _get_session()
    session.mark_initialized()
    session.log_tool_call("auto_init_session")

    # Update global compliance state for dashboard
    _compliance_state["last_session_init"] = datetime.now().isoformat()
    _compliance_state["editor"] = "claude"  # Will be detected properly later

    # Track ROI: session with context
    _track_roi_event("session_context")

    # Check cache first (with git hash validation)
    cached = _get_cached_snapshot(project_id, working_dir)
    if cached and _is_meaningful_snapshot(cached):
        return _format_from_snapshot(cached, working_dir)

    # Load or create project
    data = _load_project(project_id)
    if not data:
        data = _init_project_memory(working_dir)
        _save_project(project_id, data)

    # Determine status
    status = "existing" if _is_meaningful_project(data) else "new"

    # Update index
    _update_snapshot(project_id, working_dir, data)

    # Build response
    return _format_init_response(data, status, working_dir)


def _is_meaningful_snapshot(snapshot: Dict[str, Any]) -> bool:
    """Check if snapshot has meaningful data."""
    return bool(
        snapshot.get('summary') or
        snapshot.get('current_goal') or
        snapshot.get('last_insight') or
        snapshot.get('decisions_count', 0) > 0
    )


def _get_browser_errors_summary(limit: int = 3) -> Optional[str]:
    """Get summary of recent browser errors for init response."""
    try:
        res = requests.get('http://localhost:5000/api/live-errors', timeout=2)
        if res.status_code != 200:
            return None

        data = res.json()
        errors = data.get('errors', [])

        if not errors:
            return None

        lines = ["### ⚠️ Browser Errors Detected"]
        for err in errors[:limit]:
            msg = err.get('message', err.get('error', 'Unknown'))[:60]
            source = err.get('source', err.get('url', ''))
            source_short = source.split('/')[-1][:30] if source else 'Browser'
            lines.append(f"• **{source_short}**: {msg}")

        if len(errors) > limit:
            lines.append(f"_...and {len(errors) - limit} more. Use `get_browser_errors()` for full list._")

        return '\n'.join(lines)
    except Exception:
        return None


def _format_from_snapshot(snapshot: Dict[str, Any], working_dir: str) -> str:
    """Format init response from cached snapshot."""
    lines = [
        f"## Project: {snapshot.get('name', Path(working_dir).name)}",
        f"**Status:** EXISTING",
        f"**Path:** `{working_dir}`",
        ""
    ]

    # DECISIONS FIRST - Load from project file (not cached in snapshot)
    project_id = _get_project_id(working_dir)
    data = _load_project(project_id)
    decisions = data.get('decisions', []) if data else []

    if decisions:
        lines.append("---")
        lines.append("## 🚨 ACTIVE DECISIONS - YOU MUST RESPECT THESE")
        lines.append("")
        lines.append("**STOP before any change that contradicts these decisions!**")
        lines.append("**Ask user for explicit override approval if request conflicts.**")
        lines.append("")
        for dec in decisions:
            lines.append(f"🔒 **{dec.get('decision', '')}**")
            lines.append(f"   _Reason: {dec.get('reason', '')}_")
            lines.append("")
        lines.append("---")
        lines.append("")

        # Mark decisions as displayed for compliance tracking
        session = _get_session()
        session.mark_decisions_displayed()
        _sync_compliance()

    # INSIGHTS - Check these BEFORE researching anything!
    # Use Memory Decay ranking to show most important insights
    insights = data.get('live_record', {}).get('lessons', {}).get('insights', []) if data else []
    if insights:
        # Get top 5 ranked insights (by importance, use_count, recency)
        top_insights = _get_ranked_insights(insights, limit=5)

        lines.append("---")
        lines.append("## 🧠 STORED INSIGHTS - CHECK BEFORE RESEARCHING")
        lines.append("")
        lines.append("**YOU ARE FORBIDDEN from external research if relevant insight exists below!**")
        lines.append("**If relevant → use it. If not → proceed with research.**")
        lines.append("")
        for ins in top_insights:
            text = ins.get('text', '')
            importance = ins.get('importance', 'medium')
            use_count = ins.get('use_count', 0)

            # Show importance indicator
            if importance == 'high':
                prefix = "🔥"  # Hot/important
            elif use_count > 0:
                prefix = "✓"   # Used before
            else:
                prefix = "💡"  # Regular

            lines.append(f"{prefix} {text}")

        if len(insights) > 5:
            lines.append(f"_...and {len(insights) - 5} more. Use `search_past_solutions()` to find specific ones._")
        lines.append("")
        lines.append("---")
        lines.append("")

    if snapshot.get('current_goal'):
        lines.append(f"**Last Goal:** {snapshot['current_goal']}")

    if snapshot.get('summary'):
        lines.append(f"**Architecture:** {snapshot['summary']}")

    if snapshot.get('last_insight'):
        lines.append(f"**Last Insight:** {snapshot['last_insight']}")

    # Show git status if available
    if snapshot.get('git_commit_hash'):
        lines.append(f"**Git:** `{snapshot['git_commit_hash']}`")

    lines.append("")
    lines.append("_Ask: 'נמשיך מכאן?'_")

    # Add recent activity
    activity_info = _get_recent_activity_summary(working_dir, limit=5)
    if activity_info:
        lines.append("")
        lines.append(activity_info)

    # Add browser errors if any
    errors_info = _get_browser_errors_summary(limit=3)
    if errors_info:
        lines.append("")
        lines.append(errors_info)

    return '\n'.join(lines)


def _format_init_response(data: Dict[str, Any], status: str, working_dir: str) -> str:
    """Format init session response."""
    project_name = data.get('project_info', {}).get('name', Path(working_dir).name)

    lines = [
        f"## Project: {project_name}",
        f"**Status:** {status.upper()}",
        f"**Path:** `{working_dir}`",
        ""
    ]

    if status == "new":
        lines.append("_This is a new project. Ask: 'רוצה שאסרוק את הפרויקט?'_")
    else:
        # Show existing context
        lr = data.get('live_record', {})

        # DECISIONS FIRST - Most important for respecting past choices
        decisions = data.get('decisions', [])
        if decisions:
            lines.append("---")
            lines.append("## 🚨 ACTIVE DECISIONS - YOU MUST RESPECT THESE")
            lines.append("")
            lines.append("**STOP before any change that contradicts these decisions!**")
            lines.append("**Ask user for explicit override approval if request conflicts.**")
            lines.append("")
            for dec in decisions:
                lines.append(f"🔒 **{dec.get('decision', '')}**")
                lines.append(f"   _Reason: {dec.get('reason', '')}_")
                lines.append("")
            lines.append("---")
            lines.append("")

            # Mark decisions as displayed for compliance tracking
            session = _get_session()
            session.mark_decisions_displayed()
            _sync_compliance()

        # INSIGHTS - Check these BEFORE researching anything!
        # Use Memory Decay ranking to show most important insights
        insights = lr.get('lessons', {}).get('insights', [])
        if insights:
            # Get top 5 ranked insights (by importance, use_count, recency)
            top_insights = _get_ranked_insights(insights, limit=5)

            lines.append("---")
            lines.append("## 🧠 STORED INSIGHTS - CHECK BEFORE RESEARCHING")
            lines.append("")
            lines.append("**YOU ARE FORBIDDEN from external research if relevant insight exists below!**")
            lines.append("**If relevant → use it. If not → proceed with research.**")
            lines.append("")
            for ins in top_insights:
                text = ins.get('text', '')
                importance = ins.get('importance', 'medium')
                use_count = ins.get('use_count', 0)

                # Show importance indicator
                if importance == 'high':
                    prefix = "🔥"  # Hot/important
                elif use_count > 0:
                    prefix = "✓"   # Used before
                else:
                    prefix = "💡"  # Regular

                lines.append(f"{prefix} {text}")

            if len(insights) > 5:
                lines.append(f"_...and {len(insights) - 5} more. Use `search_past_solutions()` to find specific ones._")
            lines.append("")
            lines.append("---")
            lines.append("")

        intent = lr.get('intent', {})
        if intent.get('current_goal'):
            lines.append(f"**Last Goal:** {intent['current_goal']}")

        arch = lr.get('architecture', {})
        if arch.get('summary'):
            lines.append(f"**Architecture:** {arch['summary']}")

        avoid = data.get('avoid', [])
        if avoid:
            lines.append(f"**Avoid:** {avoid[-1].get('what', '')}")

        lines.append("")
        lines.append("_Ask: 'נמשיך מכאן?'_")

    # Add recent activity
    activity_info = _get_recent_activity_summary(working_dir, limit=5)
    if activity_info:
        lines.append("")
        lines.append(activity_info)

    # Add browser errors if any
    errors_info = _get_browser_errors_summary(limit=3)
    if errors_info:
        lines.append("")
        lines.append(errors_info)

    return '\n'.join(lines)


@mcp.tool()
def init_session(working_dir: str = "", port: int = 0) -> str:
    """
    Initialize FixOnce session for the current project.

    Phase 1: Uses boundary detection to find actual project root.

    Args:
        working_dir: The absolute path to the project directory (use cwd)
        port: OR a port number - will auto-detect the working directory from it

    Returns:
        Session info with project_status ('new' or 'existing')
    """
    # If port given, detect working_dir from it
    if port and not working_dir:
        detected = _get_working_dir_from_port(port)
        if detected:
            working_dir = detected
        else:
            return f"Error: Could not detect project directory from port {port}. Is a server running?"

    # Phase 1: Use boundary detection to find actual project root
    if BOUNDARY_DETECTION_ENABLED and working_dir and os.path.isdir(working_dir):
        project_root, marker, confidence = find_project_root(working_dir)
        if project_root and confidence in ("high", "medium"):
            # Use the detected project root instead of raw working_dir
            print(f"[MCP] init_session: {working_dir} → {project_root} ({confidence})")
            working_dir = project_root

    return _do_init_session(working_dir)


@mcp.tool()
def detect_project_from_port(port: int) -> str:
    """
    Detect which project directory is running on a given port.

    Args:
        port: The port number to check (e.g., 5000, 3000)

    Returns:
        The detected project path, or error message
    """
    detected = _get_working_dir_from_port(port)
    if detected:
        return f"Port {port} → `{detected}`"
    else:
        return f"No process found on port {port}"


@mcp.tool()
def scan_project() -> str:
    """
    Scan the current project directory.
    Use this for NEW projects after user approves.

    Returns:
        Scan results (technologies, structure, etc.)
    """
    session = _get_session()
    if not session.is_active():
        return "Error: No active session. Call init_session() first."

    working_dir = session.working_dir

    lines = [f"# Scanning: {Path(working_dir).name}", ""]

    # Detect technologies
    tech_files = {
        'package.json': 'Node.js/JavaScript',
        'requirements.txt': 'Python',
        'pyproject.toml': 'Python',
        'Cargo.toml': 'Rust',
        'go.mod': 'Go',
        'pom.xml': 'Java',
        'Gemfile': 'Ruby',
        'tsconfig.json': 'TypeScript',
        'docker-compose.yml': 'Docker',
        'Dockerfile': 'Docker'
    }

    found_tech = []
    for file, tech in tech_files.items():
        if os.path.exists(os.path.join(working_dir, file)):
            found_tech.append(tech)

    if found_tech:
        lines.append(f"**Stack:** {', '.join(set(found_tech))}")
        lines.append("")

    # List directories
    lines.append("**Structure:**")
    try:
        dirs = sorted([d for d in os.listdir(working_dir)
                      if os.path.isdir(os.path.join(working_dir, d))
                      and not d.startswith('.')])[:10]
        for d in dirs:
            lines.append(f"- 📁 {d}/")
    except Exception as e:
        lines.append(f"_Error reading directory: {e}_")

    lines.append("")

    # Check for README
    for readme in ['README.md', 'README.txt', 'README']:
        readme_path = os.path.join(working_dir, readme)
        if os.path.exists(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read(500)
                lines.append("**README preview:**")
                lines.append(f"```\n{content}\n```")
            except:
                pass
            break

    lines.append("")
    lines.append("---")
    lines.append("Now call `update_live_record()` to save this info.")

    return '\n'.join(lines)


@mcp.tool()
def update_live_record(section: str, data: str) -> str:
    """
    Update a section of the Live Record.

    Args:
        section: One of 'gps', 'architecture', 'intent', 'lessons'
        data: JSON string with the data to update

    For 'lessons', use: {"insight": "..."} or {"failed_attempt": "..."}
    These APPEND to the list.

    For 'architecture', use: {"summary": "...", "stack": "...", "key_flows": [...]}
    - summary: Short description of what this project is
    - stack: Technologies used (e.g., "React, Node.js, MongoDB")
    - key_flows: Main user flows or features

    For other sections, data REPLACES the section.
    """
    error, context = _universal_gate("update_live_record")
    if error:
        return error

    session = _get_session()
    # Track goal updates for compliance
    if section == 'intent':
        session.mark_goal_updated()
        _sync_compliance()

    try:
        update_data = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError:
        return f"Error: Invalid JSON: {data}"

    project_id = session.project_id
    memory = _load_project(project_id)

    if 'live_record' not in memory:
        memory['live_record'] = {}

    lr = memory['live_record']

    # PRE-ACTION INTELLIGENCE: Track any warnings
    pre_action_warning = ""

    if section == 'lessons':
        # APPEND mode with Memory Decay tracking
        if 'lessons' not in lr:
            lr['lessons'] = {'insights': [], 'failed_attempts': [], 'archived': []}

        if 'insight' in update_data:
            # PRE-ACTION: Check for similar existing insights
            new_text = update_data['insight'].lower()
            for existing in lr['lessons'].get('insights', []):
                existing_text = _normalize_insight(existing).get('text', '').lower()
                # Check for significant word overlap
                new_words = set(new_text.split())
                existing_words = set(existing_text.split())
                overlap = new_words & existing_words - {'the', 'a', 'is', 'in', 'to', 'and', 'of'}
                if len(overlap) >= 4:  # At least 4 meaningful words in common
                    pre_action_warning = f"\n💡 **Similar insight exists:** {existing_text[:50]}..."
                    break

            # Create insight with full decay metadata
            new_insight = _create_insight(update_data['insight'])
            lr['lessons']['insights'].append(new_insight)

        if 'failed_attempt' in update_data:
            # Failed attempts also get metadata - marked as type to prevent decay
            new_attempt = _create_insight(update_data['failed_attempt'])
            new_attempt['type'] = 'failed_attempt'  # Will NEVER be archived
            lr['lessons']['failed_attempts'].append(new_attempt)
    elif section == 'intent':
        # INTENT mode - track goal history
        if 'intent' not in lr:
            lr['intent'] = {}

        # Save previous goal to history before replacing
        old_goal = lr['intent'].get('current_goal', '')
        if old_goal and old_goal != update_data.get('current_goal', ''):
            if 'goal_history' not in lr['intent']:
                lr['intent']['goal_history'] = []
            lr['intent']['goal_history'].insert(0, {
                'goal': old_goal,
                'completed_at': datetime.now().isoformat()
            })
            # Keep only last 5 goals
            lr['intent']['goal_history'] = lr['intent']['goal_history'][:5]

        # Update intent with new data
        lr['intent'].update(update_data)
        # Always update timestamp when intent changes
        lr['intent']['updated_at'] = datetime.now().isoformat()
    else:
        # REPLACE mode for other sections
        if section not in lr:
            lr[section] = {}
        lr[section].update(update_data)

    lr['updated_at'] = datetime.now().isoformat()
    _save_project(project_id, memory)

    # Add browser errors reminder if any
    reminder = _get_browser_errors_reminder()
    return f"Updated {section}{pre_action_warning}{reminder}"


@mcp.tool()
def get_live_record() -> str:
    """Get the current Live Record."""
    error, context = _universal_gate("get_live_record")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)
    lr = memory.get('live_record', {})

    # Context header + data
    return context + json.dumps(lr, indent=2, ensure_ascii=False)


@mcp.tool()
def log_decision(decision: str, reason: str) -> str:
    """Log an architectural decision. Decisions NEVER decay - they are permanent."""
    error, context = _universal_gate("log_decision")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    if 'decisions' not in memory:
        memory['decisions'] = []

    # PRE-ACTION INTELLIGENCE: Check for similar/conflicting decisions
    similar_warning = ""
    decision_lower = decision.lower()
    for existing in memory['decisions']:
        existing_text = existing.get('decision', '').lower()
        # Check for similar decisions (simple word overlap)
        decision_words = set(decision_lower.split())
        existing_words = set(existing_text.split())
        overlap = decision_words & existing_words
        if len(overlap) >= 3:  # At least 3 words in common
            similar_warning = f"\n⚠️ **Similar decision exists:** {existing.get('decision', '')[:60]}..."
            break

    memory['decisions'].append({
        "type": "decision",  # Marked as decision - will NEVER be archived
        "decision": decision,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "importance": "permanent"  # Decisions never decay
    })

    _save_project(session.project_id, memory)
    return context + f"Logged decision: {decision}" + similar_warning


@mcp.tool()
def log_avoid(what: str, reason: str) -> str:
    """Log something to avoid. Avoid patterns NEVER decay - they are permanent."""
    error, context = _universal_gate("log_avoid")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    if 'avoid' not in memory:
        memory['avoid'] = []

    memory['avoid'].append({
        "type": "avoid",  # Marked as avoid - will NEVER be archived
        "what": what,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "importance": "permanent"  # Avoid patterns never decay
    })

    _save_project(session.project_id, memory)
    return f"Logged avoid: {what}"


@mcp.tool()
def search_past_solutions(query: str) -> str:
    """Search for past solutions matching the query."""
    error, context = _universal_gate("search_past_solutions")
    if error:
        return error

    session = _get_session()

    memory = _load_project(session.project_id)

    # Search in lessons
    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    failed = lessons.get('failed_attempts', [])

    query_lower = query.lower()

    matches = []
    matched_indices = []  # Track which insights matched for use_count update

    for i, insight in enumerate(insights):
        # Normalize to new format
        normalized = _normalize_insight(insight)
        insight_text = normalized.get('text', '')

        if query_lower in insight_text.lower():
            matches.append(f"💡 Insight: {insight_text}")
            matched_indices.append(i)
            # Mark as used
            _mark_insight_used(normalized)
            insights[i] = normalized  # Update in place

    for attempt in failed:
        # Handle both string and dict formats
        normalized = _normalize_insight(attempt)
        attempt_text = normalized.get('text', '')

        if query_lower in attempt_text.lower():
            matches.append(f"❌ Failed: {attempt_text}")

    # Save updated use counts if we had matches
    if matched_indices:
        _save_project(session.project_id, memory)

    if matches:
        # Track ROI: solution reused
        _track_roi_event("solution_reused")
        return context + "## Found:\n" + '\n'.join(matches)
    else:
        return context + "No matching solutions found."


@mcp.tool()
def get_recent_activity(limit: int = 10) -> str:
    """
    Get recent Claude activity from the dashboard.

    Shows what files were edited, commands run, etc.
    Useful for understanding recent context and what changed.

    Args:
        limit: Max number of activities to return (default 10)

    Returns:
        Recent activity list with timestamps and human-readable names
    """
    session = _get_session()
    activity_file = SRC_DIR.parent / "data" / "activity_log.json"

    if not activity_file.exists():
        return "No activity log found."

    try:
        with open(activity_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        all_activities = data.get('activities', [])

        if not all_activities:
            return "No recent activity."

        # Filter to current project only if session active
        working_dir = session.working_dir if session.is_active() else ""

        if working_dir:
            # Only show activities from current project
            project_activities = []
            for act in all_activities:
                file_path = act.get('file') or ''
                cwd = act.get('cwd') or ''
                if file_path.startswith(working_dir) or cwd.startswith(working_dir):
                    project_activities.append(act)
            activities = project_activities[:limit]
        else:
            activities = all_activities[:limit]

        if not activities:
            return "No recent activity for this project."

        lines = ["## Recent Activity\n"]

        for act in activities:
            file_path = act.get('file', '')
            human_name = act.get('human_name', '')
            tool = act.get('tool', '')
            timestamp = act.get('timestamp', '')[:16].replace('T', ' ')

            # Format the activity
            if file_path:
                file_name = file_path.split('/')[-1]
                display = human_name if human_name else file_name
                lines.append(f"• **{display}** ({file_name}) - {tool} - {timestamp}")
            elif act.get('command'):
                cmd = act.get('command', '')[:40]
                lines.append(f"• `{cmd}` - {timestamp}")

        return '\n'.join(lines)

    except Exception as e:
        return f"Error reading activity: {e}"


@mcp.tool()
def get_browser_errors(limit: int = 10) -> str:
    """
    Get recent browser errors captured by the FixOnce Chrome extension.

    These are JavaScript errors, network errors, and console errors from
    the user's browser. Use this to proactively help fix frontend issues.

    Args:
        limit: Max number of errors to return (default 10)

    Returns:
        Recent browser errors with messages, sources, and timestamps
    """
    # Use universal gate (no context header needed - this IS the error report)
    _universal_gate("get_browser_errors")

    try:
        # Try to fetch from the dashboard API
        res = requests.get('http://localhost:5000/api/live-errors', timeout=3)
        if res.status_code != 200:
            return "No browser errors available (dashboard not running or no errors)."

        data = res.json()
        errors = data.get('errors', [])

        if not errors:
            return "No browser errors captured."

        lines = ["## Browser Errors (from Chrome Extension)\n"]
        lines.append("These errors were captured from the user's browser:\n")

        for err in errors[:limit]:
            msg = err.get('message', err.get('error', 'Unknown error'))
            source = err.get('source', err.get('url', 'Unknown source'))
            timestamp = err.get('timestamp', '')[:16].replace('T', ' ')
            line_no = err.get('lineno', err.get('line', ''))
            col_no = err.get('colno', err.get('column', ''))

            # Format source
            source_short = source.split('/')[-1] if '/' in source else source
            if source_short and len(source_short) > 40:
                source_short = source_short[:40] + '...'

            location = f":{line_no}" if line_no else ""
            if col_no:
                location += f":{col_no}"

            lines.append(f"### Error in {source_short}{location}")
            lines.append(f"**Message:** {msg}")
            if timestamp:
                lines.append(f"**Time:** {timestamp}")
            lines.append("")

        lines.append("\n💡 *Use this information to help debug frontend issues.*")

        return '\n'.join(lines)

    except requests.exceptions.RequestException:
        return "Could not connect to dashboard. Make sure FixOnce server is running on port 5000."
    except Exception as e:
        return f"Error fetching browser errors: {e}"


@mcp.tool()
def get_protocol_compliance() -> str:
    """
    Get current protocol compliance status.

    Use this to check if you're following FixOnce protocol correctly.
    Returns status of: session init, decisions display, goal updates.
    """
    session = _get_session()
    compliance = session.get_compliance_status()

    lines = ["## Protocol Compliance Status\n"]

    # Session
    if compliance["session_initialized"]:
        lines.append(f"✅ Session initialized at {compliance['initialized_at']}")
    else:
        lines.append("❌ Session NOT initialized - MUST call auto_init_session()")

    # Decisions
    if compliance["decisions_displayed"]:
        lines.append("✅ Decisions displayed to user")
    else:
        lines.append("⚠️ Decisions not displayed - Show them on session start")

    # Goal
    if compliance["goal_updated"]:
        lines.append("✅ Goal updated this session")
    else:
        lines.append("⚠️ Goal not updated - Update before starting work")

    # Tool calls
    lines.append(f"\n📊 Tool calls this session: {compliance['tool_calls_count']}")

    # Violations
    if _compliance_state["violations"]:
        lines.append("\n### ⚠️ Recent Violations:")
        for v in _compliance_state["violations"][-5:]:
            lines.append(f"- {v['type']}: {v['tool']} at {v['timestamp']}")

    return '\n'.join(lines)


@mcp.tool()
def run_memory_cleanup() -> str:
    """
    Run memory decay cleanup - archive old/unused insights.

    This tool:
    - Archives low-importance insights not used in 60+ days
    - Archives never-used low-importance insights older than 30 days
    - Shows memory statistics

    PROTECTED (never archived):
    - Decisions (log_decision) - permanent institutional knowledge
    - Avoid patterns (log_avoid) - permanent warnings
    - Failed attempts - prevent repeating mistakes
    - High-importance insights

    Run this periodically to keep memory clean and relevant.
    """
    error = _require_session("run_memory_cleanup")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    archived = lessons.get('archived', [])

    if not insights:
        return "No insights to process."

    # Normalize all insights
    normalized = [_normalize_insight(ins) for ins in insights]

    # Separate active from archived
    still_active = []
    newly_archived = []

    for ins in normalized:
        if _should_archive_insight(ins):
            newly_archived.append(ins)
        else:
            still_active.append(ins)

    # Update memory
    lessons['insights'] = still_active
    lessons['archived'] = archived + newly_archived
    memory['live_record']['lessons'] = lessons

    _save_project(session.project_id, memory)

    # Build stats report
    lines = ["## Memory Cleanup Report\n"]

    # Show protected items count
    decisions_count = len(memory.get('decisions', []))
    avoid_count = len(memory.get('avoid', []))
    failed_count = len(lessons.get('failed_attempts', []))

    lines.append("### 🔒 Protected (Never Archived)")
    lines.append(f"- **Decisions:** {decisions_count}")
    lines.append(f"- **Avoid Patterns:** {avoid_count}")
    lines.append(f"- **Failed Attempts:** {failed_count}")
    lines.append("")

    lines.append("### 📊 Insights")
    lines.append(f"**Active:** {len(still_active)}")
    lines.append(f"**Newly Archived:** {len(newly_archived)}")
    lines.append(f"**Total Archived:** {len(lessons['archived'])}")

    if newly_archived:
        lines.append("\n### Archived Insights:")
        for ins in newly_archived[:5]:
            text = ins.get('text', '')[:50]
            lines.append(f"- {text}...")

    # Show top insights by importance
    if still_active:
        lines.append("\n### Top Active Insights:")
        top = _get_ranked_insights(still_active, limit=3)
        for ins in top:
            text = ins.get('text', '')[:50]
            importance = ins.get('importance', 'medium')
            use_count = ins.get('use_count', 0)
            lines.append(f"- 🔥 [{importance}] (used {use_count}x) {text}...")

    return '\n'.join(lines)


@mcp.tool()
def get_memory_stats() -> str:
    """
    Get memory statistics for the current project.

    Shows:
    - Total insights (active vs archived)
    - Importance distribution
    - Usage statistics
    - Recommendations for cleanup
    """
    error = _require_session("get_memory_stats")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    archived = lessons.get('archived', [])
    failed = lessons.get('failed_attempts', [])
    decisions = memory.get('decisions', [])

    lines = ["## Memory Statistics\n"]

    # Totals
    lines.append(f"**Active Insights:** {len(insights)}")
    lines.append(f"**Archived Insights:** {len(archived)}")
    lines.append(f"**Failed Attempts:** {len(failed)}")
    lines.append(f"**Decisions:** {len(decisions)}")

    if insights:
        # Normalize for stats
        normalized = [_normalize_insight(ins) for ins in insights]

        # Importance distribution
        high = sum(1 for i in normalized if i.get('importance') == 'high')
        medium = sum(1 for i in normalized if i.get('importance') == 'medium')
        low = sum(1 for i in normalized if i.get('importance') == 'low')

        lines.append(f"\n**Importance Distribution:**")
        lines.append(f"- 🔥 High: {high}")
        lines.append(f"- 💡 Medium: {medium}")
        lines.append(f"- ⚪ Low: {low}")

        # Usage stats
        used = sum(1 for i in normalized if i.get('use_count', 0) > 0)
        never_used = len(normalized) - used
        total_uses = sum(i.get('use_count', 0) for i in normalized)

        lines.append(f"\n**Usage Statistics:**")
        lines.append(f"- Used at least once: {used}")
        lines.append(f"- Never used: {never_used}")
        lines.append(f"- Total usage count: {total_uses}")

        # Recommendations
        lines.append(f"\n**Recommendations:**")
        if never_used > 10:
            lines.append(f"⚠️ {never_used} insights never used - consider running `run_memory_cleanup()`")
        if len(insights) > 50:
            lines.append(f"⚠️ Memory growing large ({len(insights)} insights) - consider cleanup")
        if never_used == 0 and len(insights) < 50:
            lines.append("✅ Memory is healthy - no action needed")

    return '\n'.join(lines)


# ============================================================
# COMPLIANCE API (For Dashboard Widget)
# ============================================================

def get_compliance_for_api() -> dict:
    """Get compliance status for dashboard API.

    Uses global _compliance_state since Flask runs in different thread than MCP.
    """
    return {
        "session_initialized": _compliance_state.get("session_active", False),
        "initialized_at": _compliance_state.get("initialized_at"),
        "decisions_displayed": _compliance_state.get("decisions_displayed", False),
        "goal_updated": _compliance_state.get("goal_updated", False),
        "tool_calls_count": _compliance_state.get("tool_calls_count", 0),
        "last_session_init": _compliance_state.get("last_session_init"),
        "violations": _compliance_state.get("violations", [])[-5:],
        "editor": _compliance_state.get("editor"),
        "project_id": _compliance_state.get("project_id")
    }


if __name__ == "__main__":
    mcp.run()
