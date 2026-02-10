"""
Multi-Project Manager for FixOnce
Handles multiple projects with automatic detection and switching.

Architecture:
- data/projects/{project_id}/memory.json - per-project memory
- data/projects/{project_id}/solutions.db - per-project solutions
- data/global/solutions.db - shared solutions across all projects
- data/active_project.json - current active project pointer
"""

import os
import json
import hashlib
import threading
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

# Paths
SRC_DIR = Path(__file__).parent.parent
PROJECT_DIR = SRC_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
PROJECTS_V2_DIR = DATA_DIR / "projects_v2"
GLOBAL_DIR = DATA_DIR / "global"
ACTIVE_PROJECT_FILE = DATA_DIR / "active_project.json"

# Thread lock
_lock = threading.Lock()

# Ensure directories exist
PROJECTS_DIR.mkdir(exist_ok=True)
PROJECTS_V2_DIR.mkdir(exist_ok=True)
GLOBAL_DIR.mkdir(exist_ok=True)


def _get_v2_project_by_port(port: int) -> Optional[Dict[str, Any]]:
    """
    Find and load v2 project data by detecting working dir from port.
    """
    import subprocess

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
        working_dir = None
        for line in result.stdout.split('\n'):
            if ' cwd ' in line:
                parts = line.split()
                if len(parts) >= 9:
                    path = parts[-1]
                    # Go up if we're in src/ or similar
                    if Path(path).name in ('src', 'dist', 'build', 'bin'):
                        path = str(Path(path).parent)
                    working_dir = path
                    break

        if not working_dir:
            return None

        # Generate v2 project ID
        path_hash = hashlib.md5(working_dir.encode()).hexdigest()[:12]
        name = Path(working_dir).name
        project_id = f"{name}_{path_hash}"

        # Load v2 project file
        v2_path = PROJECTS_V2_DIR / f"{project_id}.json"
        if v2_path.exists():
            with open(v2_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        return None
    except Exception as e:
        print(f"[MultiProject] Error loading v2 project: {e}")
        return None


def _merge_v2_into_memory(memory: Dict[str, Any], v2_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge v2 project data into v1 memory structure.
    """
    if not v2_data:
        return memory

    # Merge live_record
    v2_live = v2_data.get('live_record', {})
    if 'live_record' not in memory:
        memory['live_record'] = {}

    for section in ['gps', 'architecture', 'intent', 'lessons']:
        if section in v2_live and v2_live[section]:
            if section not in memory['live_record']:
                memory['live_record'][section] = {}
            # Merge non-empty values
            for key, value in v2_live[section].items():
                if value:  # Only merge non-empty values
                    memory['live_record'][section][key] = value

    # Merge decisions
    if v2_data.get('decisions'):
        if 'decisions' not in memory:
            memory['decisions'] = []
        memory['decisions'].extend(v2_data['decisions'])

    # Merge avoid
    if v2_data.get('avoid'):
        if 'avoid' not in memory:
            memory['avoid'] = []
        memory['avoid'].extend(v2_data['avoid'])

    return memory


def generate_project_id(source: str, source_type: str = "url") -> str:
    """
    Generate a clean project ID from various sources.

    Args:
        source: URL, path, or identifier
        source_type: "url", "path", "git", "manual"

    Returns:
        Clean project ID like "tofesly-localhost-3000"
    """
    if source_type == "url":
        parsed = urlparse(source)
        host = parsed.hostname or "localhost"
        port = parsed.port

        # Clean the host
        host = host.replace("www.", "")

        if port and port not in (80, 443):
            return f"{host}-{port}".lower()
        return host.lower()

    elif source_type == "path":
        # Get the folder name from path
        path = Path(source)
        name = path.name or path.parent.name
        # Clean it
        name = re.sub(r'[^a-zA-Z0-9-_]', '-', name)
        return name.lower()

    elif source_type == "git":
        # Extract repo name from git URL
        # git@github.com:user/repo.git -> repo
        # https://github.com/user/repo.git -> repo
        match = re.search(r'/([^/]+?)(?:\.git)?$', source)
        if match:
            return match.group(1).lower()
        return hashlib.md5(source.encode()).hexdigest()[:8]

    else:
        # Manual - just clean it
        return re.sub(r'[^a-zA-Z0-9-_]', '-', source).lower()


def get_project_dir(project_id: str) -> Path:
    """Get the directory path for a project."""
    return PROJECTS_DIR / project_id


def get_project_memory_path(project_id: str) -> Path:
    """Get the memory.json path for a project."""
    return get_project_dir(project_id) / "memory.json"


def get_project_solutions_path(project_id: str) -> Path:
    """Get the solutions.db path for a project."""
    return get_project_dir(project_id) / "solutions.db"


def get_global_solutions_path() -> Path:
    """Get the global solutions.db path."""
    return GLOBAL_DIR / "solutions.db"


def list_projects() -> List[Dict[str, Any]]:
    """
    List all projects with basic info.

    Returns:
        List of project summaries
    """
    projects = []

    if not PROJECTS_DIR.exists():
        return projects

    for project_dir in PROJECTS_DIR.iterdir():
        if project_dir.is_dir():
            memory_path = project_dir / "memory.json"
            if memory_path.exists():
                try:
                    with open(memory_path, 'r', encoding='utf-8') as f:
                        memory = json.load(f)

                    info = memory.get('project_info', {})
                    stats = memory.get('stats', {})

                    projects.append({
                        "id": project_dir.name,
                        "name": info.get('name', project_dir.name),
                        "stack": info.get('stack', ''),
                        "root_path": info.get('root_path', ''),
                        "last_updated": stats.get('last_updated', ''),
                        "issues_count": len(memory.get('active_issues', [])),
                        "solutions_count": len(memory.get('solutions_history', []))
                    })
                except Exception as e:
                    print(f"[MultiProject] Error reading {project_dir.name}: {e}")

    # Sort by last_updated descending
    projects.sort(key=lambda x: x.get('last_updated', ''), reverse=True)

    return projects


def get_active_project() -> Optional[Dict[str, Any]]:
    """
    Get the currently active project info.

    Returns:
        Active project dict or None
    """
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
    create_if_missing: bool = False
) -> Dict[str, Any]:
    """
    Set the active project.

    Args:
        project_id: The project ID to activate
        detected_from: How it was detected (extension, server, editor, manual)
        display_name: Optional display name
        create_if_missing: If False, won't create new project (default: False)

    Returns:
        Active project info
    """
    with _lock:
        project_dir = get_project_dir(project_id)
        memory_path = get_project_memory_path(project_id)

        # Only create project if explicitly allowed
        if not memory_path.exists():
            if create_if_missing:
                project_dir.mkdir(exist_ok=True)
                init_project_memory(project_id, display_name)
            else:
                # Project doesn't exist and auto-create is disabled
                # Fall back to 'fixonce' project
                print(f"[MultiProject] Project '{project_id}' not found, staying on current project")
                return get_active_project() or {"active_id": "fixonce", "detected_from": "fallback"}

        # Update active project file
        active_info = {
            "active_id": project_id,
            "detected_from": detected_from,
            "detected_at": datetime.now().isoformat(),
            "display_name": display_name or project_id
        }

        with open(ACTIVE_PROJECT_FILE, 'w', encoding='utf-8') as f:
            json.dump(active_info, f, ensure_ascii=False, indent=2)

        print(f"[MultiProject] Switched to: {project_id} (from {detected_from})")

        return active_info


def detect_project_from_url(url: str) -> Dict[str, Any]:
    """
    Detect and activate project from URL.

    Args:
        url: The URL from browser extension

    Returns:
        Active project info
    """
    if not url:
        return {"error": "No URL provided"}

    project_id = generate_project_id(url, "url")

    # Create display name
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port
    path = parsed.path or ""
    display_name = f"{host}:{port}" if port else host

    # Set active project
    result = set_active_project(project_id, "extension", display_name)

    # Update Live Record GPS with URL info
    memory = load_project_memory(project_id)
    if 'live_record' not in memory:
        memory['live_record'] = {}
    if 'gps' not in memory['live_record']:
        memory['live_record']['gps'] = {}

    gps = memory['live_record']['gps']
    gps['url'] = url
    gps['host'] = host
    gps['active_ports'] = [port] if port else []
    gps['path'] = path
    gps['environment'] = 'dev' if 'localhost' in host or '127.0.0.1' in host else 'prod'
    gps['updated_at'] = datetime.now().isoformat()

    save_project_memory(project_id, memory)

    return result


def detect_project_from_path(path: str) -> Dict[str, Any]:
    """
    Detect and activate project from file path.

    Args:
        path: Project root path

    Returns:
        Active project info
    """
    if not path or not os.path.isdir(path):
        return {"error": "Invalid path"}

    project_id = generate_project_id(path, "path")
    display_name = Path(path).name

    result = set_active_project(project_id, "path", display_name)

    # Also set the root_path in memory
    memory = load_project_memory(project_id)
    memory['project_info']['root_path'] = path
    save_project_memory(project_id, memory)

    return result


def init_project_memory(project_id: str, display_name: str = None) -> Dict[str, Any]:
    """
    Initialize memory for a new project.

    Args:
        project_id: The project ID
        display_name: Optional display name

    Returns:
        New memory dict
    """
    now = datetime.now().isoformat()

    memory = {
        "project_info": {
            "name": display_name or project_id,
            "stack": "",
            "status": "Active",
            "description": "",
            "root_path": "",
            "created_at": now
        },
        "active_issues": [],
        "solutions_history": [],
        "ai_context_snapshot": "",
        "decisions": [],
        "avoid": [],
        "handover": {},
        "stats": {
            "total_errors_captured": 0,
            "total_solutions_applied": 0,
            "last_updated": now
        },
        "ai_session": {},
        "live_record": {
            "gps": {
                "active_ports": [],
                "entry_points": [],
                "environment": "dev",
                "working_dir": "",
                "updated_at": now
            },
            "architecture": {
                "summary": "",
                "key_flows": [],
                "updated_at": now
            },
            "lessons": {
                "insights": [],
                "failed_attempts": [],
                "updated_at": now
            },
            "intent": {
                "current_goal": "",
                "last_milestone": "",
                "next_step": "",
                "blockers": [],
                "updated_at": now
            },
            "updated_at": now
        },
        "roi": {
            "solutions_reused": 0,
            "tokens_saved": 0,
            "errors_prevented": 0,
            "decisions_referenced": 0,
            "time_saved_minutes": 0,
            "sessions_with_context": 0
        },
        "safety": {
            "enabled": True,
            "auto_backup": True,
            "require_approval": True,
            "changes_history": [],
            "backups_dir": ".fixonce_backups"
        }
    }

    memory_path = get_project_memory_path(project_id)
    memory_path.parent.mkdir(exist_ok=True)

    with open(memory_path, 'w', encoding='utf-8') as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

    print(f"[MultiProject] Initialized new project: {project_id}")

    return memory


def load_project_memory(project_id: str = None) -> Dict[str, Any]:
    """
    Load memory for a project.

    Args:
        project_id: Project ID (uses active if None)

    Returns:
        Memory dict
    """
    if not project_id:
        project_id = get_active_project_id()

    if not project_id:
        # No active project - return empty default
        return init_project_memory("default", "Default Project")

    memory_path = get_project_memory_path(project_id)

    if not memory_path.exists():
        return init_project_memory(project_id)

    try:
        with open(memory_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[MultiProject] Error loading {project_id}: {e}")
        return init_project_memory(project_id)


def save_project_memory(project_id: str = None, memory: Dict[str, Any] = None) -> bool:
    """
    Save memory for a project.

    Args:
        project_id: Project ID (uses active if None)
        memory: Memory dict to save

    Returns:
        Success boolean
    """
    if not project_id:
        project_id = get_active_project_id()

    if not project_id:
        project_id = "default"

    if not memory:
        return False

    with _lock:
        memory_path = get_project_memory_path(project_id)
        memory_path.parent.mkdir(exist_ok=True)

        # Update timestamp
        memory.setdefault('stats', {})['last_updated'] = datetime.now().isoformat()

        try:
            with open(memory_path, 'w', encoding='utf-8') as f:
                json.dump(memory, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[MultiProject] Error saving {project_id}: {e}")
            return False


def delete_project(project_id: str) -> Dict[str, Any]:
    """
    Delete a project and all its data.

    Args:
        project_id: Project to delete

    Returns:
        Status dict
    """
    import shutil

    project_dir = get_project_dir(project_id)

    if not project_dir.exists():
        return {"status": "error", "message": "Project not found"}

    try:
        shutil.rmtree(project_dir)

        # If this was the active project, clear it
        active = get_active_project_id()
        if active == project_id:
            if ACTIVE_PROJECT_FILE.exists():
                ACTIVE_PROJECT_FILE.unlink()

        return {"status": "ok", "message": f"Deleted project: {project_id}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def migrate_from_flat_memory() -> Dict[str, Any]:
    """
    Migrate from the old flat project_memory.json to multi-project structure.

    Returns:
        Migration status
    """
    old_memory_path = DATA_DIR / "project_memory.json"

    if not old_memory_path.exists():
        return {"status": "skipped", "message": "No old memory file found"}

    try:
        with open(old_memory_path, 'r', encoding='utf-8') as f:
            old_memory = json.load(f)

        # Determine project ID from old data
        project_info = old_memory.get('project_info', {})
        name = project_info.get('name', 'migrated')
        root_path = project_info.get('root_path', '')

        if root_path:
            project_id = generate_project_id(root_path, "path")
        else:
            project_id = generate_project_id(name, "manual")

        # Create project directory
        project_dir = get_project_dir(project_id)
        project_dir.mkdir(exist_ok=True)

        # Save memory to new location
        new_memory_path = get_project_memory_path(project_id)
        with open(new_memory_path, 'w', encoding='utf-8') as f:
            json.dump(old_memory, f, ensure_ascii=False, indent=2)

        # Set as active
        set_active_project(project_id, "migration", name)

        # Rename old file as backup
        backup_path = DATA_DIR / "project_memory.json.migrated"
        old_memory_path.rename(backup_path)

        # Move solutions.db to project folder
        old_solutions = DATA_DIR / "personal_solutions.db"
        if old_solutions.exists():
            import shutil
            # Copy to project (keep original as global)
            shutil.copy(old_solutions, get_project_solutions_path(project_id))
            # Also copy to global
            shutil.copy(old_solutions, get_global_solutions_path())

        return {
            "status": "ok",
            "project_id": project_id,
            "message": f"Migrated to project: {project_id}"
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


# === Compatibility layer for existing code ===

def get_project_context() -> Dict[str, Any]:
    """
    Compatibility: Get context for active project.
    Maps to old API signature.
    """
    return load_project_memory()


def save_memory(memory: Dict[str, Any]) -> bool:
    """
    Compatibility: Save memory for active project.
    Maps to old API signature.
    """
    return save_project_memory(None, memory)


def get_active_project_with_memory() -> Dict[str, Any]:
    """
    Get active project info with full memory.
    Used by dashboard.
    """
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

    # Try to get v2 data and merge it
    # Extract port from project_id (e.g., "localhost-5000" -> 5000)
    port = None
    for sep in ['-', ':']:
        if sep in project_id:
            try:
                port = int(project_id.split(sep)[-1])
                break
            except ValueError:
                pass

    if port:
        v2_data = _get_v2_project_by_port(port)
        if v2_data:
            memory = _merge_v2_into_memory(memory, v2_data)

    return {
        "active": True,
        "project_id": project_id,
        "display_name": active.get('display_name'),
        "detected_from": active.get('detected_from'),
        "memory": memory,
        "projects": list_projects()
    }
