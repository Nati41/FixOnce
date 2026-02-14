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
    """Thread-safe session context."""

    def __init__(self, project_id: str = None, working_dir: str = None):
        self.project_id = project_id
        self.working_dir = working_dir

    def __repr__(self):
        return f"SessionContext(project_id={self.project_id})"

    def is_active(self) -> bool:
        return self.project_id is not None


def _get_session() -> SessionContext:
    """Get current session for this thread (never returns None)."""
    if not hasattr(_session_local, 'session') or _session_local.session is None:
        _session_local.session = SessionContext()
    return _session_local.session


def _set_session(project_id: str, working_dir: str):
    """Set session for current thread."""
    _session_local.session = SessionContext(project_id, working_dir)


def _clear_session():
    """Clear session for current thread."""
    _session_local.session = SessionContext()


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

        intent = lr.get('intent', {})
        if intent.get('current_goal'):
            lines.append(f"**Last Goal:** {intent['current_goal']}")

        arch = lr.get('architecture', {})
        if arch.get('summary'):
            lines.append(f"**Architecture:** {arch['summary']}")

        lessons = lr.get('lessons', {}).get('insights', [])
        if lessons:
            last_insight = lessons[-1]
            # Handle both string and dict formats
            if isinstance(last_insight, dict):
                last_insight = last_insight.get('text', str(last_insight))
            lines.append(f"**Last Insight:** {last_insight}")

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
    session = _get_session()
    if not session.is_active():
        return "Error: No active session. Call init_session() first."

    try:
        update_data = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError:
        return f"Error: Invalid JSON: {data}"

    project_id = session.project_id
    memory = _load_project(project_id)

    if 'live_record' not in memory:
        memory['live_record'] = {}

    lr = memory['live_record']

    if section == 'lessons':
        # APPEND mode
        if 'lessons' not in lr:
            lr['lessons'] = {'insights': [], 'failed_attempts': []}

        if 'insight' in update_data:
            lr['lessons']['insights'].append(update_data['insight'])
        if 'failed_attempt' in update_data:
            lr['lessons']['failed_attempts'].append(update_data['failed_attempt'])
    else:
        # REPLACE mode
        if section not in lr:
            lr[section] = {}
        lr[section].update(update_data)

    lr['updated_at'] = datetime.now().isoformat()
    _save_project(project_id, memory)

    return f"Updated {section}"


@mcp.tool()
def get_live_record() -> str:
    """Get the current Live Record."""
    session = _get_session()
    if not session.is_active():
        return "Error: No active session. Call init_session() first."

    memory = _load_project(session.project_id)
    lr = memory.get('live_record', {})

    return json.dumps(lr, indent=2, ensure_ascii=False)


@mcp.tool()
def log_decision(decision: str, reason: str) -> str:
    """Log an architectural decision."""
    session = _get_session()
    if not session.is_active():
        return "Error: No active session."

    memory = _load_project(session.project_id)

    if 'decisions' not in memory:
        memory['decisions'] = []

    memory['decisions'].append({
        "decision": decision,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })

    _save_project(session.project_id, memory)
    return f"Logged decision: {decision}"


@mcp.tool()
def log_avoid(what: str, reason: str) -> str:
    """Log something to avoid."""
    session = _get_session()
    if not session.is_active():
        return "Error: No active session."

    memory = _load_project(session.project_id)

    if 'avoid' not in memory:
        memory['avoid'] = []

    memory['avoid'].append({
        "what": what,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })

    _save_project(session.project_id, memory)
    return f"Logged avoid: {what}"


@mcp.tool()
def search_past_solutions(query: str) -> str:
    """Search for past solutions matching the query."""
    session = _get_session()
    if not session.is_active():
        return "Error: No active session."

    memory = _load_project(session.project_id)

    # Search in lessons
    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    failed = lessons.get('failed_attempts', [])

    query_lower = query.lower()

    matches = []
    for insight in insights:
        # Handle both string and dict formats
        insight_text = insight.get('text', str(insight)) if isinstance(insight, dict) else str(insight)
        if query_lower in insight_text.lower():
            matches.append(f"💡 Insight: {insight_text}")

    for attempt in failed:
        # Handle both string and dict formats
        attempt_text = attempt.get('text', str(attempt)) if isinstance(attempt, dict) else str(attempt)
        if query_lower in attempt_text.lower():
            matches.append(f"❌ Failed: {attempt_text}")

    if matches:
        return "## Found:\n" + '\n'.join(matches)
    else:
        return "No matching solutions found."


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


if __name__ == "__main__":
    mcp.run()
