"""
Multi-Project Manager for FixOnce - V2 Only

Canonical storage: data/projects_v2/{project_id}.json
Project ID = {folder_name}_{md5_hash[:12]} derived from working_dir

V1 (data/projects/) is deprecated and ignored.

IMPORTANT: project_id is REQUIRED in load_project_memory and save_project_memory.
Never fall back to active_project.json for routing - only for dashboard display.
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

# Safe file operations (auto-backup, atomic writes)
try:
    from core.safe_file import atomic_json_write, atomic_json_read
    SAFE_FILE_AVAILABLE = True
except ImportError:
    SAFE_FILE_AVAILABLE = False

# Phase 0: Import ProjectContext for consistent ID generation
# Note: We keep local generate_project_id_from_path for backward compatibility
# but new code should use ProjectContext.from_path()

# Ensure src is in path for imports
_SRC_DIR = Path(__file__).parent.parent
_PROJECT_DIR = _SRC_DIR.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

# Context generator for universal AI access (lazy import to avoid circular deps)
_context_generator = None
_committed_knowledge_updater = None

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


def _get_committed_knowledge_updater():
    """Lazy load committed knowledge updater to avoid import issues."""
    global _committed_knowledge_updater
    if _committed_knowledge_updater is None:
        try:
            from src.core.committed_knowledge import update_committed_on_save
            _committed_knowledge_updater = update_committed_on_save
        except ImportError:
            _committed_knowledge_updater = lambda *args, **kwargs: None
    return _committed_knowledge_updater

# Paths
SRC_DIR = Path(__file__).parent.parent
PROJECT_DIR = SRC_DIR.parent

# USER data directory (must match MCP server's DATA_DIR)
# MCP writes to ~/.fixonce/projects_v2/, so we must read from there too
USER_DATA_DIR = Path.home() / ".fixonce"
DATA_DIR = USER_DATA_DIR
PROJECTS_V2_DIR = DATA_DIR / "projects_v2"
GLOBAL_DIR = DATA_DIR / "global"
ACTIVE_PROJECT_FILE = DATA_DIR / "active_project.json"

# Installation data dir (for templates only)
INSTALL_DATA_DIR = PROJECT_DIR / "data"

# Thread lock
_lock = threading.Lock()

# Ensure directories exist
PROJECTS_V2_DIR.mkdir(parents=True, exist_ok=True)
GLOBAL_DIR.mkdir(exist_ok=True)


# ============================================================
# PROJECT ID GENERATION (Canonical: working_dir based)
# ============================================================

def generate_project_id_from_path(working_dir: str, create_if_missing: bool = True) -> str:
    """
    Get or generate project ID from working directory.

    PORTABLE: First checks .fixonce/metadata.json for stored project_id.
    This ensures the same ID is used when project is cloned to another machine.

    Args:
        working_dir: Project root directory
        create_if_missing: If True, creates .fixonce/metadata.json for new projects

    Returns:
        project_id string (stable across machines if .fixonce exists)
    """
    # FIRST: Check for portable project_id in .fixonce/
    try:
        from core.committed_knowledge import get_portable_project_id, get_or_create_project_metadata

        portable_id = get_portable_project_id(working_dir)
        if portable_id:
            return portable_id

        # No .fixonce exists - create one if allowed
        if create_if_missing:
            metadata = get_or_create_project_metadata(working_dir)
            return metadata.get("project_id")
    except ImportError:
        pass  # Fall back to hash-based ID
    except Exception as e:
        print(f"[MultiProject] Warning: Could not access .fixonce: {e}")

    # FALLBACK: Generate hash-based ID (not portable, but works)
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


def get_active_session_id(project_id: str = None) -> Optional[str]:
    """
    Get the current session ID for a project.

    Session ID is derived from project_id + ai_session.started_at.
    Used for command scope validation - commands only execute in
    the session they were queued for.

    Returns:
        Session ID (8-char hash) or None if no active session
    """
    if not project_id:
        project_id = get_active_project_id()
    if not project_id:
        return None

    memory = load_project_memory(project_id)
    if not memory:
        return None

    ai_session = memory.get('ai_session', {})
    started_at = ai_session.get('started_at')

    if not started_at:
        return None

    # Generate session ID same way as MCP server
    session_id = hashlib.md5(f"{project_id}_{started_at}".encode()).hexdigest()[:8]
    return session_id


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

        # Use safe write for active project file
        if SAFE_FILE_AVAILABLE:
            atomic_json_write(str(ACTIVE_PROJECT_FILE), active_info, create_backup=False)
        else:
            with open(ACTIVE_PROJECT_FILE, 'w', encoding='utf-8') as f:
                json.dump(active_info, f, ensure_ascii=False, indent=2)

        print(f"[MultiProject] Switched to: {project_id} (from {detected_from})")
        return active_info


# ============================================================
# PROJECT MEMORY CRUD
# ============================================================

def init_project_memory(project_id: str, display_name: str = None, working_dir: str = None) -> Dict[str, Any]:
    """Initialize memory for a new project. Syncs from .fixonce/ if exists (cloned repo)."""
    now = datetime.now().isoformat()

    # Check if repo has committed knowledge (.fixonce/decisions.json, etc.)
    committed_knowledge = None
    if working_dir:
        try:
            from src.core.committed_knowledge import read_committed_knowledge
            committed_knowledge = read_committed_knowledge(working_dir)
            if committed_knowledge.get("found"):
                print(f"[MultiProject] Found committed knowledge in .fixonce/")
        except ImportError:
            pass

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

    # Merge committed knowledge from .fixonce/ if found (cloned repo scenario)
    if committed_knowledge and committed_knowledge.get("found"):
        for dec in committed_knowledge.get("decisions", []):
            dec["source"] = "repo"  # Mark as from repo
            memory["decisions"].append(dec)
        for avoid in committed_knowledge.get("avoid", []):
            avoid["source"] = "repo"
            memory["avoid"].append(avoid)
        print(f"[MultiProject] Merged {len(memory['decisions'])} decisions, {len(memory['avoid'])} avoid patterns from repo")

    project_path = get_project_path(project_id)

    # Use safe write with auto-backup
    if SAFE_FILE_AVAILABLE:
        atomic_json_write(str(project_path), memory, create_backup=False)  # No backup for new files
    else:
        with open(project_path, 'w', encoding='utf-8') as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)

    print(f"[MultiProject] Initialized: {project_id}")
    return memory


def load_project_memory(project_id: str) -> Dict[str, Any]:
    """
    Load memory for a project.

    IMPORTANT: project_id is REQUIRED.
    Never falls back to active_project.json.

    Args:
        project_id: The project ID (REQUIRED)

    Returns:
        Project memory dict

    Raises:
        ValueError: If project_id is not provided
    """
    if not project_id:
        raise ValueError(
            "project_id is REQUIRED. "
            "Use ProjectContext.from_path(working_dir) to get it. "
            "Never rely on active_project.json for routing."
        )

    project_path = get_project_path(project_id)

    if not project_path.exists():
        # Check for backup before creating new
        if SAFE_FILE_AVAILABLE:
            from core.safe_file import get_latest_backup
            backup = get_latest_backup(str(project_path))
            if backup and backup.exists():
                print(f"[MultiProject] Found backup for missing project: {backup.name}")
                # Auto-recover from backup
                from core.safe_file import restore_from_backup
                if restore_from_backup(str(project_path)):
                    print(f"[MultiProject] Auto-recovered from backup!")
                    return atomic_json_read(str(project_path), default={})
        return init_project_memory(project_id)

    try:
        # Use safe read with auto-recovery
        if SAFE_FILE_AVAILABLE:
            memory = atomic_json_read(str(project_path), default=None, auto_recover=True)
            if memory is None:
                print(f"[MultiProject] Recovery failed, reinitializing {project_id}")
                return init_project_memory(project_id)
            return memory
        else:
            with open(project_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[MultiProject] Error loading {project_id}: {e}")
        return init_project_memory(project_id)


def load_project_from_working_dir(working_dir: str) -> tuple:
    """
    Load project memory from working directory - PRIMARY ENTRY POINT.

    This is the PORTABLE way to load a project:
    1. Checks .fixonce/ in project root FIRST (source of truth)
    2. Falls back to projects_v2/ cache if .fixonce/ missing
    3. Creates new .fixonce/ for new projects

    Args:
        working_dir: Project root directory

    Returns:
        Tuple of (project_id, memory_dict)
    """
    from pathlib import Path

    if not working_dir or not Path(working_dir).is_dir():
        raise ValueError(f"Invalid working_dir: {working_dir}")

    try:
        from core.committed_knowledge import (
            get_project_metadata,
            get_or_create_project_metadata,
            read_committed_knowledge,
            sync_from_committed
        )

        # Step 1: Check if .fixonce/ exists with metadata
        existing_metadata = get_project_metadata(working_dir)

        if existing_metadata and existing_metadata.get("project_id"):
            # EXISTING PROJECT - .fixonce/ is source of truth
            project_id = existing_metadata["project_id"]
            print(f"[MultiProject] Loading from .fixonce/ (portable): {project_id}")

            # Check if we have cached memory in projects_v2/
            cache_path = get_project_path(project_id)
            if cache_path.exists():
                # Load from cache (faster)
                memory = load_project_memory(project_id)
                # Sync any new committed knowledge (in case repo was updated)
                memory = sync_from_committed(working_dir, memory)
            else:
                # No cache - build from .fixonce/
                memory = _build_memory_from_fixonce(working_dir, project_id, existing_metadata)

            return project_id, memory

        else:
            # NEW PROJECT - create .fixonce/
            print(f"[MultiProject] New project, creating .fixonce/")
            metadata = get_or_create_project_metadata(working_dir)
            project_id = metadata["project_id"]

            # Initialize fresh memory
            memory = init_project_memory(project_id, metadata.get("name"), working_dir)

            return project_id, memory

    except ImportError as e:
        print(f"[MultiProject] committed_knowledge not available: {e}")
        # Fallback to legacy behavior
        project_id = generate_project_id_from_path(working_dir, create_if_missing=False)
        return project_id, load_project_memory(project_id)


def _build_memory_from_fixonce(working_dir: str, project_id: str, metadata: dict) -> dict:
    """
    Build complete memory from .fixonce/ files.

    Called when project exists in .fixonce/ but not in local cache.
    (e.g., cloned repo on new machine)
    """
    from core.committed_knowledge import read_committed_knowledge

    committed = read_committed_knowledge(working_dir)

    # Build memory structure
    memory = {
        "project_info": {
            "project_id": project_id,
            "name": metadata.get("name", Path(working_dir).name),
            "working_dir": working_dir,
            "created_at": metadata.get("created_at", datetime.now().isoformat()),
            "source": "fixonce_portable"
        },
        "decisions": committed.get("decisions", []),
        "avoid": committed.get("avoid", []),
        "debug_sessions": committed.get("solutions", []),
        "live_record": {
            "lessons": {
                "insights": committed.get("insights", [])
            },
            "gps": {
                "working_dir": working_dir
            }
        },
        "stats": {
            "created_at": metadata.get("created_at", datetime.now().isoformat()),
            "last_updated": datetime.now().isoformat()
        }
    }

    # Save to cache for future fast access
    cache_path = get_project_path(project_id)
    try:
        if SAFE_FILE_AVAILABLE:
            atomic_json_write(str(cache_path), memory, create_backup=False)
        else:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(memory, f, ensure_ascii=False, indent=2)
        print(f"[MultiProject] Cached project from .fixonce/: {project_id}")
    except Exception as e:
        print(f"[MultiProject] Warning: Could not cache project: {e}")

    return memory


def save_project_memory(project_id: str, memory: Dict[str, Any] = None) -> bool:
    """
    Save memory for a project.

    IMPORTANT: project_id is REQUIRED.
    Never falls back to active_project.json.

    Args:
        project_id: The project ID (REQUIRED)
        memory: The memory dict to save

    Returns:
        True if saved successfully

    Raises:
        ValueError: If project_id is not provided
    """
    if not project_id:
        raise ValueError(
            "project_id is REQUIRED. "
            "Use ProjectContext.from_path(working_dir) to get it. "
            "Never rely on active_project.json for routing."
        )

    if not memory:
        return False

    with _lock:
        memory.setdefault('stats', {})['last_updated'] = datetime.now().isoformat()

        try:
            project_path = get_project_path(project_id)

            # Use atomic write for crash safety
            try:
                from core.safe_file import atomic_json_write
                success = atomic_json_write(str(project_path), memory)
            except ImportError:
                # Fallback to regular write if safe_file not available
                with open(project_path, 'w', encoding='utf-8') as f:
                    json.dump(memory, f, ensure_ascii=False, indent=2)
                success = True

            if not success:
                print(f"[MultiProject] Atomic write failed for {project_id}")
                return False

            # Update universal context file (.fixonce/CONTEXT.md)
            try:
                context_updater = _get_context_generator()
                context_path = context_updater(project_id, memory)
                if context_path:
                    print(f"[ContextGen] Updated: {context_path}")
            except Exception as ctx_err:
                print(f"[ContextGen] Warning: {ctx_err}")

            # Update committed knowledge (.fixonce/decisions.json, avoid.json)
            try:
                committed_updater = _get_committed_knowledge_updater()
                committed_path = committed_updater(project_id, memory)
                if committed_path:
                    print(f"[CommittedKnowledge] Updated: {committed_path}")
            except Exception as ck_err:
                print(f"[CommittedKnowledge] Warning: {ck_err}")

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


def archive_project(project_id: str) -> Dict[str, Any]:
    """Archive a project (hide from active list)."""
    project_path = get_project_path(project_id)

    if not project_path.exists():
        return {"status": "error", "message": "Project not found"}

    try:
        # Use safe read
        if SAFE_FILE_AVAILABLE:
            memory = atomic_json_read(str(project_path), default={})
        else:
            with open(project_path, 'r', encoding='utf-8') as f:
                memory = json.load(f)

        # Set archived flag
        if 'project_info' not in memory:
            memory['project_info'] = {}
        memory['project_info']['archived'] = True

        # Use safe write with auto-backup
        if SAFE_FILE_AVAILABLE:
            atomic_json_write(str(project_path), memory)
        else:
            with open(project_path, 'w', encoding='utf-8') as f:
                json.dump(memory, f, indent=2, ensure_ascii=False)

        return {"status": "ok", "message": f"Archived: {project_id}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def unarchive_project(project_id: str) -> Dict[str, Any]:
    """Unarchive a project (restore to active list)."""
    project_path = get_project_path(project_id)

    if not project_path.exists():
        return {"status": "error", "message": "Project not found"}

    try:
        # Use safe read
        if SAFE_FILE_AVAILABLE:
            memory = atomic_json_read(str(project_path), default={})
        else:
            with open(project_path, 'r', encoding='utf-8') as f:
                memory = json.load(f)

        # Remove archived flag
        if 'project_info' in memory:
            memory['project_info']['archived'] = False

        # Use safe write with auto-backup
        if SAFE_FILE_AVAILABLE:
            atomic_json_write(str(project_path), memory)
        else:
            with open(project_path, 'w', encoding='utf-8') as f:
                json.dump(memory, f, indent=2, ensure_ascii=False)

        return {"status": "ok", "message": f"Unarchived: {project_id}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================
# LIST PROJECTS
# ============================================================

def list_projects() -> List[Dict[str, Any]]:
    """List all projects from V2 storage (deduplicated by working_dir/name)."""
    raw_projects = []

    if not PROJECTS_V2_DIR.exists():
        return raw_projects

    for project_file in PROJECTS_V2_DIR.glob("*.json"):
        try:
            with open(project_file, 'r', encoding='utf-8') as f:
                memory = json.load(f)

            info = memory.get('project_info', {})
            stats = memory.get('stats', {})
            live_record = memory.get('live_record', {})

            raw_projects.append({
                "id": project_file.stem,
                "name": info.get('name', project_file.stem),
                "working_dir": info.get('working_dir', ''),
                "stack": live_record.get('architecture', {}).get('stack', info.get('stack', '')),
                "summary": live_record.get('architecture', {}).get('summary', ''),
                "current_goal": live_record.get('intent', {}).get('current_goal', ''),
                "last_updated": stats.get('last_updated', ''),
                "decisions_count": len(memory.get('decisions', [])),
                "avoid_count": len(memory.get('avoid', [])),
                "issues_count": len(memory.get('active_issues', [])),
                "archived": info.get('archived', False)
            })
        except Exception as e:
            print(f"[MultiProject] Error reading {project_file.name}: {e}")

    def _to_ts(value: str) -> float:
        if not value:
            return 0.0
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt.timestamp()
        except Exception:
            return 0.0

    # Canonicalize duplicates:
    # 1) primary key: working_dir (case-insensitive)
    # 2) fallback key: project name
    # Prefer non-archived + with working_dir + most recently updated.
    names_with_workdir = {
        (p.get("name") or "").strip().lower()
        for p in raw_projects
        if (p.get("working_dir") or "").strip()
    }
    deduped: Dict[str, Dict[str, Any]] = {}
    for project in raw_projects:
        name = (project.get("name") or "").strip()
        workdir = (project.get("working_dir") or "").strip()

        # If a same-name project exists with concrete working_dir, drop the
        # empty-working_dir shadow entry (common duplicate artifact).
        if not workdir and name.lower() in names_with_workdir:
            continue

        key = f"dir:{workdir.lower()}" if workdir else f"name:{name.lower()}"

        current = deduped.get(key)
        if not current:
            deduped[key] = project
            continue

        current_score = (
            1 if not current.get("archived") else 0,
            1 if (current.get("working_dir") or "").strip() else 0,
            _to_ts(current.get("last_updated", "")),
        )
        candidate_score = (
            1 if not project.get("archived") else 0,
            1 if workdir else 0,
            _to_ts(project.get("last_updated", "")),
        )
        if candidate_score > current_score:
            deduped[key] = project

    projects = list(deduped.values())

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
# COMPATIBILITY LAYER (DEPRECATED - for dashboard only)
# ============================================================
#
# IMPORTANT: These functions use active_project.json as fallback.
# This is ONLY acceptable for dashboard UI and backward compatibility.
# MCP tools should NEVER use these - they should use ProjectContext.from_path().

# Guard: Track if we're in dashboard mode
_DASHBOARD_MODE_CALLERS = {'api.memory', 'api.projects', 'api.status', 'project_memory_manager'}


def _is_dashboard_context() -> bool:
    """Check if call is coming from dashboard context (allowed to use active_project.json)."""
    import traceback
    stack = traceback.extract_stack()
    for frame in stack:
        for allowed in _DASHBOARD_MODE_CALLERS:
            if allowed in frame.filename:
                return True
    return False


def get_project_context() -> Dict[str, Any]:
    """
    DEPRECATED: Get context for active project.

    For backward compatibility only. Dashboard can use this.
    MCP tools should use load_project_memory(ProjectContext.from_path(working_dir)).
    """
    project_id = get_active_project_id()  # Dashboard fallback
    if not project_id:
        print("[WARN] get_project_context() called without active project")
        return init_project_memory("default", "")
    return load_project_memory(project_id)


def save_memory(memory: Dict[str, Any]) -> bool:
    """
    DEPRECATED: Save memory for active project.

    For backward compatibility only. Dashboard can use this.
    MCP tools should use save_project_memory(project_id, memory).
    """
    project_id = get_active_project_id()  # Dashboard fallback
    if not project_id:
        print("[WARN] save_memory() called without active project")
        project_id = "default"
    return save_project_memory(project_id, memory)


def migrate_from_flat_memory() -> Dict[str, Any]:
    """Migration from old format - now just returns status."""
    return {"status": "skipped", "message": "V2 is now canonical, no migration needed"}
