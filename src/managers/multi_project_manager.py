"""
Multi-Project Manager for FixOnce - V2 Only

Canonical storage: data/projects_v2/{project_id}.json
Project ID = {folder_name}_{md5_hash[:12]} derived from working_dir

V1 (data/projects/) is deprecated and ignored.
"""

import os
import sys
import json
import hashlib
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Ensure src is in path for imports
_SRC_DIR = Path(__file__).parent.parent
_PROJECT_DIR = _SRC_DIR.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

# Context generator for universal AI access (lazy import to avoid circular deps)
_context_generator = None

def _get_context_generator():
    """Lazy load context generator to avoid import issues."""
    global _context_generator
    if _context_generator is None:
        try:
            from src.core.context_generator import update_context_on_memory_change
            _context_generator = update_context_on_memory_change
        except ImportError:
            _context_generator = lambda *args, **kwargs: None
    return _context_generator

# Paths
SRC_DIR = Path(__file__).parent.parent
PROJECT_DIR = SRC_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
PROJECTS_V2_DIR = DATA_DIR / "projects_v2"
GLOBAL_DIR = DATA_DIR / "global"
ACTIVE_PROJECT_FILE = DATA_DIR / "active_project.json"

# Thread lock
_lock = threading.Lock()

# Ensure directories exist
PROJECTS_V2_DIR.mkdir(parents=True, exist_ok=True)
GLOBAL_DIR.mkdir(exist_ok=True)


# ============================================================
# PROJECT ID GENERATION (Canonical: working_dir based)
# ============================================================

def generate_project_id_from_path(working_dir: str) -> str:
    """
    Generate project ID from working directory.
    This is the ONLY way to generate IDs now.

    Format: {folder_name}_{md5_hash[:12]}
    Example: /Users/x/my-app -> my-app_a1b2c3d4e5f6
    """
    path_hash = hashlib.md5(working_dir.encode()).hexdigest()[:12]
    name = Path(working_dir).name
    return f"{name}_{path_hash}"


def generate_project_id(source: str, source_type: str = "path") -> str:
    """
    Generate project ID. Prefers path-based IDs.

    For backwards compatibility with dashboard URL detection,
    we try to detect working_dir from port if source is URL.
    """
    if source_type == "path":
        return generate_project_id_from_path(source)

    elif source_type == "url":
        # Try to detect working_dir from port
        from urllib.parse import urlparse
        parsed = urlparse(source)
        port = parsed.port

        if port:
            working_dir = _detect_working_dir_from_port(port)
            if working_dir:
                return generate_project_id_from_path(working_dir)

        # Fallback: URL-based ID (legacy, less preferred)
        host = parsed.hostname or "localhost"
        if port and port not in (80, 443):
            return f"{host}-{port}".lower()
        return host.lower()

    else:
        # Manual or other - create safe ID
        import re
        safe = re.sub(r'[^a-zA-Z0-9-_]', '-', source).lower()
        return f"{safe}_{hashlib.md5(source.encode()).hexdigest()[:8]}"


def _detect_working_dir_from_port(port: int) -> Optional[str]:
    """Detect working directory from a running port using lsof."""
    try:
        result = subprocess.run(
            ['lsof', '-i', f':{port}', '-t'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        pid = result.stdout.strip().split('\n')[0]

        result = subprocess.run(
            ['lsof', '-p', pid],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None

        for line in result.stdout.split('\n'):
            if ' cwd ' in line:
                parts = line.split()
                if len(parts) >= 9:
                    path = parts[-1]
                    if Path(path).name in ('src', 'dist', 'build', 'bin'):
                        path = str(Path(path).parent)
                    return path
        return None
    except Exception:
        return None


# ============================================================
# V2 STORAGE FUNCTIONS
# ============================================================

def get_project_path(project_id: str) -> Path:
    """Get path to project JSON file in V2 storage."""
    return PROJECTS_V2_DIR / f"{project_id}.json"


def get_project_dir(project_id: str) -> Path:
    """
    Get project directory (for compatibility).
    In V2, this is just the projects_v2 dir with the file.
    """
    return PROJECTS_V2_DIR


def get_project_memory_path(project_id: str) -> Path:
    """Get memory path (same as project path in V2)."""
    return get_project_path(project_id)


def get_project_solutions_path(project_id: str) -> Path:
    """Get solutions.db path for a project."""
    return PROJECTS_V2_DIR / f"{project_id}_solutions.db"


def get_global_solutions_path() -> Path:
    """Get global solutions.db path."""
    return GLOBAL_DIR / "solutions.db"


def project_exists(project_id: str) -> bool:
    """Check if project exists."""
    return get_project_path(project_id).exists()


# ============================================================
# ACTIVE PROJECT MANAGEMENT
# ============================================================

def get_active_project() -> Optional[Dict[str, Any]]:
    """Get the currently active project info."""
    if not ACTIVE_PROJECT_FILE.exists():
        return None

    try:
        with open(ACTIVE_PROJECT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def get_active_project_id() -> Optional[str]:
    """Get just the active project ID."""
    active = get_active_project()
    return active.get('active_id') if active else None


def set_active_project(
    project_id: str,
    detected_from: str = "manual",
    display_name: str = None,
    create_if_missing: bool = True,
    working_dir: str = None
) -> Dict[str, Any]:
    """
    Set the active project.

    Args:
        project_id: The project ID to activate
        detected_from: How it was detected
        display_name: Optional display name
        create_if_missing: Create project if it doesn't exist
        working_dir: Working directory (for new projects)
    """
    with _lock:
        project_path = get_project_path(project_id)

        if not project_path.exists():
            if create_if_missing:
                init_project_memory(project_id, display_name, working_dir)
            else:
                print(f"[MultiProject] Project '{project_id}' not found")
                return get_active_project() or {"active_id": None, "detected_from": "fallback"}

        # Phase 1: Get working_dir from project memory if not provided
        actual_working_dir = working_dir
        if not actual_working_dir and project_path.exists():
            try:
                with open(project_path, 'r', encoding='utf-8') as f:
                    memory = json.load(f)
                actual_working_dir = (
                    memory.get("project_info", {}).get("working_dir") or
                    memory.get("live_record", {}).get("gps", {}).get("working_dir")
                )
            except Exception:
                pass

        active_info = {
            "active_id": project_id,
            "detected_from": detected_from,
            "detected_at": datetime.now().isoformat(),
            "display_name": display_name or project_id,
            "working_dir": actual_working_dir  # Phase 1: Store for boundary detection
        }

        with open(ACTIVE_PROJECT_FILE, 'w', encoding='utf-8') as f:
            json.dump(active_info, f, ensure_ascii=False, indent=2)

        print(f"[MultiProject] Switched to: {project_id} (from {detected_from})")
        return active_info


# ============================================================
# PROJECT MEMORY CRUD
# ============================================================

def init_project_memory(project_id: str, display_name: str = None, working_dir: str = None) -> Dict[str, Any]:
    """Initialize memory for a new project."""
    now = datetime.now().isoformat()

    memory = {
        "project_info": {
            "name": display_name or project_id.split('_')[0],
            "working_dir": working_dir or "",
            "stack": "",
            "status": "Active",
            "description": "",
            "created_at": now
        },
        "live_record": {
            "gps": {
                "working_dir": working_dir or "",
                "active_ports": [],
                "url": "",
                "environment": "dev",
                "updated_at": now
            },
            "architecture": {
                "summary": "",
                "stack": "",
                "key_flows": [],
                "updated_at": now
            },
            "intent": {
                "current_goal": "",
                "next_step": "",
                "blockers": [],
                "updated_at": now
            },
            "lessons": {
                "insights": [],
                "failed_attempts": [],
                "updated_at": now
            },
            "updated_at": now
        },
        "decisions": [],
        "avoid": [],
        "active_issues": [],
        "solutions_history": [],
        "stats": {
            "total_errors_captured": 0,
            "total_solutions_applied": 0,
            "last_updated": now
        },
        "roi": {
            "solutions_reused": 0,
            "tokens_saved": 0,
            "errors_prevented": 0,
            "decisions_referenced": 0,
            "time_saved_minutes": 0,
            "sessions_with_context": 0
        }
    }

    project_path = get_project_path(project_id)
    with open(project_path, 'w', encoding='utf-8') as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

    print(f"[MultiProject] Initialized: {project_id}")
    return memory


def load_project_memory(project_id: str = None) -> Dict[str, Any]:
    """Load memory for a project."""
    if not project_id:
        project_id = get_active_project_id()

    if not project_id:
        return init_project_memory("default", "Default Project")

    project_path = get_project_path(project_id)

    if not project_path.exists():
        return init_project_memory(project_id)

    try:
        with open(project_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[MultiProject] Error loading {project_id}: {e}")
        return init_project_memory(project_id)


def save_project_memory(project_id: str = None, memory: Dict[str, Any] = None) -> bool:
    """Save memory for a project."""
    if not project_id:
        project_id = get_active_project_id()

    if not project_id:
        project_id = "default"

    if not memory:
        return False

    with _lock:
        memory.setdefault('stats', {})['last_updated'] = datetime.now().isoformat()

        try:
            project_path = get_project_path(project_id)
            with open(project_path, 'w', encoding='utf-8') as f:
                json.dump(memory, f, ensure_ascii=False, indent=2)

            # Update universal context file (.fixonce/CONTEXT.md)
            try:
                context_updater = _get_context_generator()
                context_path = context_updater(project_id, memory)
                if context_path:
                    print(f"[ContextGen] Updated: {context_path}")
            except Exception as ctx_err:
                print(f"[ContextGen] Warning: {ctx_err}")

            return True
        except Exception as e:
            print(f"[MultiProject] Error saving {project_id}: {e}")
            return False


def delete_project(project_id: str) -> Dict[str, Any]:
    """Delete a project."""
    project_path = get_project_path(project_id)

    if not project_path.exists():
        return {"status": "error", "message": "Project not found"}

    try:
        project_path.unlink()

        # Also delete solutions if exists
        solutions_path = get_project_solutions_path(project_id)
        if solutions_path.exists():
            solutions_path.unlink()

        # Clear active if this was it
        if get_active_project_id() == project_id:
            if ACTIVE_PROJECT_FILE.exists():
                ACTIVE_PROJECT_FILE.unlink()

        return {"status": "ok", "message": f"Deleted: {project_id}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================
# LIST PROJECTS
# ============================================================

def list_projects() -> List[Dict[str, Any]]:
    """List all projects from V2 storage."""
    projects = []

    if not PROJECTS_V2_DIR.exists():
        return projects

    for project_file in PROJECTS_V2_DIR.glob("*.json"):
        try:
            with open(project_file, 'r', encoding='utf-8') as f:
                memory = json.load(f)

            info = memory.get('project_info', {})
            stats = memory.get('stats', {})
            live_record = memory.get('live_record', {})

            projects.append({
                "id": project_file.stem,
                "name": info.get('name', project_file.stem),
                "working_dir": info.get('working_dir', ''),
                "stack": live_record.get('architecture', {}).get('stack', info.get('stack', '')),
                "summary": live_record.get('architecture', {}).get('summary', ''),
                "current_goal": live_record.get('intent', {}).get('current_goal', ''),
                "last_updated": stats.get('last_updated', ''),
                "decisions_count": len(memory.get('decisions', [])),
                "avoid_count": len(memory.get('avoid', [])),
                "issues_count": len(memory.get('active_issues', []))
            })
        except Exception as e:
            print(f"[MultiProject] Error reading {project_file.name}: {e}")

    # Sort by last_updated descending
    projects.sort(key=lambda x: x.get('last_updated', ''), reverse=True)
    return projects


# ============================================================
# DETECTION FUNCTIONS
# ============================================================

def detect_project_from_url(url: str) -> Dict[str, Any]:
    """Detect and activate project from URL."""
    if not url:
        return {"error": "No URL provided"}

    from urllib.parse import urlparse
    parsed = urlparse(url)
    port = parsed.port
    host = parsed.hostname or "localhost"

    # Try to get working_dir from port
    working_dir = None
    if port:
        working_dir = _detect_working_dir_from_port(port)

    if working_dir:
        project_id = generate_project_id_from_path(working_dir)
        display_name = Path(working_dir).name
    else:
        # Fallback to URL-based ID
        project_id = f"{host}-{port}" if port else host
        display_name = f"{host}:{port}" if port else host
        working_dir = ""

    result = set_active_project(project_id, "extension", display_name, working_dir=working_dir)

    # Update GPS with URL info
    memory = load_project_memory(project_id)
    if 'live_record' not in memory:
        memory['live_record'] = {}
    if 'gps' not in memory['live_record']:
        memory['live_record']['gps'] = {}

    gps = memory['live_record']['gps']
    gps['url'] = url
    gps['host'] = host
    gps['active_ports'] = [port] if port else []
    gps['environment'] = 'dev' if 'localhost' in host or '127.0.0.1' in host else 'prod'
    gps['updated_at'] = datetime.now().isoformat()
    if working_dir:
        gps['working_dir'] = working_dir

    save_project_memory(project_id, memory)
    return result


def detect_project_from_path(path: str) -> Dict[str, Any]:
    """Detect and activate project from file path."""
    if not path or not os.path.isdir(path):
        return {"error": "Invalid path"}

    project_id = generate_project_id_from_path(path)
    display_name = Path(path).name

    result = set_active_project(project_id, "path", display_name, working_dir=path)

    memory = load_project_memory(project_id)
    memory['project_info']['working_dir'] = path
    if 'live_record' in memory and 'gps' in memory['live_record']:
        memory['live_record']['gps']['working_dir'] = path
    save_project_memory(project_id, memory)

    return result


# ============================================================
# DASHBOARD API HELPERS
# ============================================================

def get_active_project_with_memory() -> Dict[str, Any]:
    """Get active project info with full memory (for dashboard)."""
    active = get_active_project()

    if not active:
        return {
            "active": False,
            "project_id": None,
            "memory": None,
            "projects": list_projects()
        }

    project_id = active.get('active_id', '')
    memory = load_project_memory(project_id)

    return {
        "active": True,
        "project_id": project_id,
        "display_name": active.get('display_name'),
        "detected_from": active.get('detected_from'),
        "memory": memory,
        "projects": list_projects()
    }


# ============================================================
# PROJECT STATUS (Phase 1: Active/Recent grouping)
# ============================================================

def _get_last_activity_for_project(project_id: str, working_dir: str) -> Optional[str]:
    """Get last activity timestamp for a project from activity log."""
    try:
        activity_file = DATA_DIR.parent / "activity_log.json"
        if not activity_file.exists():
            return None

        with open(activity_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        activities = data.get('activities', [])

        # Find most recent activity for this project
        for act in activities:
            act_cwd = act.get('cwd', '')
            act_file = act.get('file', '')
            act_project_id = act.get('project_id', '')

            # Match by project_id, cwd, or file path
            if act_project_id == project_id:
                return act.get('timestamp')
            if working_dir and (act_cwd.startswith(working_dir) or act_file.startswith(working_dir)):
                return act.get('timestamp')

        return None
    except Exception:
        return None


def _compute_project_status(project: Dict[str, Any], active_id: str) -> str:
    """
    Compute project status in real-time.

    Returns:
        'active_now' - Currently being worked on
        'recent' - Worked on recently
        'stale' - Not touched in a while
    """
    project_id = project.get('id', '')
    working_dir = project.get('working_dir', '')

    # Check 1: Is this the active project?
    if project_id == active_id:
        return "active_now"

    # Check 2: Activity in last 10 minutes
    last_activity = _get_last_activity_for_project(project_id, working_dir)
    if last_activity:
        try:
            last_time = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
            now = datetime.now()
            # Handle timezone-naive comparison
            if last_time.tzinfo:
                last_time = last_time.replace(tzinfo=None)

            diff_minutes = (now - last_time).total_seconds() / 60

            if diff_minutes < 10:
                return "active_now"
            elif diff_minutes < 60 * 24:  # Last 24 hours
                return "recent"
            elif diff_minutes < 60 * 24 * 7:  # Last week
                return "recent"
            else:
                return "stale"
        except Exception:
            pass

    # Check 3: Has meaningful data = recent, otherwise stale
    if project.get('decisions_count', 0) > 0 or project.get('current_goal'):
        return "recent"

    return "stale"


def _format_relative_time(timestamp: str) -> str:
    """Format timestamp as relative time in Hebrew."""
    if not timestamp:
        return ""

    try:
        then = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        now = datetime.now()
        if then.tzinfo:
            then = then.replace(tzinfo=None)

        diff = now - then
        minutes = diff.total_seconds() / 60
        hours = minutes / 60
        days = hours / 24

        if minutes < 1:
            return "עכשיו"
        elif minutes < 60:
            return f"לפני {int(minutes)} דקות"
        elif hours < 24:
            return f"לפני {int(hours)} שעות"
        elif days < 2:
            return "אתמול"
        elif days < 7:
            return f"לפני {int(days)} ימים"
        elif days < 30:
            weeks = int(days / 7)
            return f"לפני {weeks} שבועות" if weeks > 1 else "לפני שבוע"
        else:
            return f"לפני {int(days / 30)} חודשים"
    except Exception:
        return ""


def get_projects_by_status() -> Dict[str, Any]:
    """
    Get projects grouped by status.

    Returns:
        {
            "active": {...} or None,
            "recent": [...],
            "stale": [...]
        }
    """
    projects = list_projects()
    active_id = get_active_project_id()

    active = None
    recent = []
    stale = []

    for project in projects:
        project_id = project.get('id', '')
        working_dir = project.get('working_dir', '')

        # Get last activity
        last_activity = _get_last_activity_for_project(project_id, working_dir)
        project['last_activity'] = last_activity
        project['last_activity_relative'] = _format_relative_time(last_activity)

        # Compute status
        status = _compute_project_status(project, active_id)
        project['status'] = status

        if status == "active_now":
            # Load full memory for active project
            memory = load_project_memory(project_id)
            intent = memory.get('live_record', {}).get('intent', {})
            project['current_goal'] = intent.get('current_goal', '')
            project['intent_updated_at'] = intent.get('updated_at', '')
            project['goal_history'] = intent.get('goal_history', [])
            project['open_errors'] = len(memory.get('active_issues', []))
            project['insights_count'] = len(memory.get('live_record', {}).get('lessons', {}).get('insights', []))
            project['ai_session'] = memory.get('ai_session', {})
            project['active_ais'] = memory.get('active_ais', {})
            active = project
        elif status == "recent":
            recent.append(project)
        else:
            stale.append(project)

    # Sort recent by last activity
    recent.sort(key=lambda x: x.get('last_activity') or '', reverse=True)

    return {
        "active": active,
        "recent": recent,
        "stale": stale,
        "total_count": len(projects)
    }


# ============================================================
# COMPATIBILITY LAYER
# ============================================================

def get_project_context() -> Dict[str, Any]:
    """Compatibility: Get context for active project."""
    return load_project_memory()


def save_memory(memory: Dict[str, Any]) -> bool:
    """Compatibility: Save memory for active project."""
    return save_project_memory(None, memory)


def migrate_from_flat_memory() -> Dict[str, Any]:
    """Migration from old format - now just returns status."""
    return {"status": "skipped", "message": "V2 is now canonical, no migration needed"}
