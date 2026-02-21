"""
Project Boundary Detection System for FixOnce.
Detects when file operations occur outside the active project and handles transitions.

MVP Rules:
- Only auto-switch INTO new projects (not back)
- Require strong markers (.git, package.json, pyproject.toml, requirements.txt)
- Confidence levels: high (git), medium (marker), low (no switch)
- Cooldown between switches to prevent loops
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

# Strong project markers (in priority order)
STRONG_MARKERS = [
    '.git',              # Git root - highest confidence
    'package.json',      # Node.js
    'pyproject.toml',    # Python (modern)
    'requirements.txt',  # Python (classic)
]

# Paths to skip (never create projects for these)
SKIP_PATHS = [
    '/tmp',
    '/var',
    '/private/tmp',
    '/private/var',
]

# Folder name patterns that indicate a build/output folder (not a real project)
BUILD_FOLDER_PATTERNS = [
    '-build',
    '-dist',
    '-output',
    '-release',
    '-package',
    '_build',
    '_dist',
    '_output',
]

# Cooldown between switches (seconds)
SWITCH_COOLDOWN_SECONDS = 5

# Data paths
DATA_DIR = Path(__file__).parent.parent.parent / 'data'
BOUNDARY_STATE_FILE = DATA_DIR / 'boundary_state.json'
ACTIVE_PROJECT_FILE = DATA_DIR / 'active_project.json'


@dataclass
class BoundaryEvent:
    """Represents a detected boundary violation."""
    old_project_id: str
    old_working_dir: str
    new_project_id: str
    new_working_dir: str
    file_path: str
    reason: str  # "git_root", "strong_marker", "no_marker"
    confidence: str  # "high", "medium", "low"
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _get_project_id_from_path(working_dir: str) -> str:
    """
    Generate project ID from path.

    IMPORTANT: Delegates to ProjectContext.from_path() which is the
    SINGLE SOURCE OF TRUTH for project ID generation.

    Uses hybrid strategy: Git Remote > Git Local > UUID
    """
    try:
        # Try relative import first (when running as part of package)
        from .project_context import ProjectContext
    except ImportError:
        # Fallback for absolute import (when running standalone)
        from core.project_context import ProjectContext
    return ProjectContext.from_path(working_dir)


def _load_active_project() -> Dict[str, Any]:
    """Load current active project info, including working_dir from project memory if needed."""
    try:
        if ACTIVE_PROJECT_FILE.exists():
            with open(ACTIVE_PROJECT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # If working_dir not in active_project.json, try to get from project memory
            if not data.get("working_dir") and data.get("active_id"):
                project_file = DATA_DIR / 'projects_v2' / f"{data['active_id']}.json"
                if project_file.exists():
                    try:
                        with open(project_file, 'r', encoding='utf-8') as pf:
                            memory = json.load(pf)
                        data["working_dir"] = (
                            memory.get("project_info", {}).get("working_dir") or
                            memory.get("live_record", {}).get("gps", {}).get("working_dir")
                        )
                    except Exception:
                        pass

            return data
    except Exception as e:
        print(f"[BOUNDARY] Error loading active project: {e}")
    return {}


def _load_boundary_state() -> Dict[str, Any]:
    """Load boundary state for cooldown tracking."""
    try:
        if BOUNDARY_STATE_FILE.exists():
            with open(BOUNDARY_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "last_switch_timestamp": None,
        "last_switch_from": None,
        "last_switch_to": None,
        "cooldown_seconds": SWITCH_COOLDOWN_SECONDS
    }


def _save_boundary_state(state: Dict[str, Any]):
    """Save boundary state."""
    try:
        with open(BOUNDARY_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[BOUNDARY] Error saving state: {e}")


def _is_skip_path(path: str) -> bool:
    """Check if path should be skipped."""
    for skip in SKIP_PATHS:
        if path.startswith(skip):
            return True
    # Also skip home directory directly (not subdirs)
    home = os.path.expanduser('~')
    if path == home:
        return True
    return False


def _is_build_or_derivative_folder(new_folder: str, active_folder: str) -> bool:
    """
    Check if new_folder is likely a build/derivative of active_folder.

    Examples:
    - FixOnce-Windows-Build is derivative of FixOnce
    - MyApp-dist is derivative of MyApp
    - ProjectName_build is derivative of ProjectName
    """
    if not new_folder or not active_folder:
        return False

    new_name = Path(new_folder).name.lower()
    active_name = Path(active_folder).name.lower()

    # Check if new folder name contains active project name + build suffix
    for pattern in BUILD_FOLDER_PATTERNS:
        if new_name == f"{active_name}{pattern}":
            return True
        if new_name.startswith(active_name) and pattern in new_name:
            return True

    # Check if same parent directory (sibling folders)
    new_parent = Path(new_folder).parent
    active_parent = Path(active_folder).parent
    if new_parent == active_parent:
        # Sibling folder - check if name starts with active project name
        if new_name.startswith(active_name) and new_name != active_name:
            return True

    return False


def _is_newly_created_folder(folder_path: str, max_age_seconds: int = 60) -> bool:
    """Check if folder was created very recently (likely by current AI session)."""
    try:
        folder = Path(folder_path)
        if not folder.exists():
            return True  # Doesn't exist yet = definitely new

        # Check creation/modification time
        stat = folder.stat()
        age = datetime.now().timestamp() - stat.st_mtime
        return age < max_age_seconds
    except Exception:
        return False


def find_project_root(file_path: str) -> tuple[Optional[str], str, str]:
    """
    Walk up from file_path to find project root.

    Returns:
        (project_root, marker_found, confidence)
        - project_root: Absolute path or None
        - marker_found: Which marker was found (e.g., ".git", "package.json")
        - confidence: "high" | "medium" | "low"
    """
    if not file_path:
        return None, "", "low"

    # Start from file's directory (or parent if file doesn't exist yet)
    current = Path(file_path)

    # If file exists and is a file, use its parent
    if current.exists():
        if current.is_file():
            current = current.parent
    else:
        # File doesn't exist yet (new file being written)
        # Use the parent directory
        current = current.parent
        # If parent also doesn't exist, keep going up until we find something
        while not current.exists() and current != current.parent:
            current = current.parent
        if not current.exists():
            return None, "", "low"

    home = Path.home()
    root = Path('/')

    while current != root and current != home:
        # Check for strong markers in priority order
        for marker in STRONG_MARKERS:
            marker_path = current / marker
            if marker_path.exists():
                confidence = "high" if marker == '.git' else "medium"
                return str(current), marker, confidence

        current = current.parent

    # No strong marker found
    return None, "", "low"


def _get_potential_project_root(file_path: str) -> Optional[str]:
    """
    Get the potential project root for a file without strong markers.
    Returns the first directory under Desktop/Documents/Projects that contains the file.
    """
    if not file_path:
        return None

    current = Path(file_path)
    if current.is_file():
        current = current.parent
    elif not current.exists():
        current = current.parent

    home = Path.home()
    desktop = home / "Desktop"
    documents = home / "Documents"

    # Walk up to find a folder directly under Desktop or Documents
    while current != home and current.parent != home:
        parent = current.parent
        if parent == desktop or parent == documents:
            # This is a project folder (direct child of Desktop/Documents)
            return str(current)
        current = parent

    return None


def _is_valid_new_project_folder(folder_path: str) -> bool:
    """Check if a folder is valid for auto-creating as a new project."""
    if not folder_path or not os.path.isdir(folder_path):
        return False

    folder = Path(folder_path)

    # Must be under Desktop or Documents
    home = Path.home()
    desktop = home / "Desktop"
    documents = home / "Documents"

    try:
        # Check if it's under Desktop or Documents
        folder.relative_to(desktop)
        is_valid_location = True
    except ValueError:
        try:
            folder.relative_to(documents)
            is_valid_location = True
        except ValueError:
            is_valid_location = False

    if not is_valid_location:
        return False

    # Folder name shouldn't be too generic or system-like
    bad_names = {'tmp', 'temp', 'cache', 'node_modules', '.git', '__pycache__', 'venv', 'env'}
    if folder.name.lower() in bad_names:
        return False

    return True


def auto_create_project_marker(folder_path: str) -> Optional[str]:
    """
    Auto-create a package.json in a new project folder.
    Returns the path to the created marker, or None if not created.
    """
    if not _is_valid_new_project_folder(folder_path):
        return None

    package_json_path = Path(folder_path) / "package.json"

    # Don't overwrite existing package.json
    if package_json_path.exists():
        return str(package_json_path)

    folder_name = Path(folder_path).name

    package_content = {
        "name": folder_name,
        "version": "1.0.0",
        "description": f"Project created by FixOnce auto-detection",
        "_fixonce": {
            "auto_created": True,
            "created_at": datetime.now().isoformat()
        }
    }

    try:
        with open(package_json_path, 'w', encoding='utf-8') as f:
            json.dump(package_content, f, indent=2, ensure_ascii=False)
        print(f"[PROJECT_BOUNDARY] Auto-created package.json in {folder_path}")
        return str(package_json_path)
    except Exception as e:
        print(f"[PROJECT_BOUNDARY] Failed to create package.json: {e}")
        return None


def is_within_boundary(file_path: str, project_root: str) -> bool:
    """Check if file_path is within the project boundary."""
    if not file_path or not project_root:
        return False

    try:
        file_abs = os.path.abspath(file_path)
        root_abs = os.path.abspath(project_root)

        # Normalize paths
        if not root_abs.endswith(os.sep):
            root_abs += os.sep

        return file_abs.startswith(root_abs) or file_abs == root_abs.rstrip(os.sep)
    except Exception:
        return False


def _is_cooldown_active(state: Dict[str, Any]) -> bool:
    """Check if we're still in cooldown period."""
    last_switch = state.get("last_switch_timestamp")
    if not last_switch:
        return False

    try:
        last_time = datetime.fromisoformat(last_switch)
        cooldown = timedelta(seconds=state.get("cooldown_seconds", SWITCH_COOLDOWN_SECONDS))
        return datetime.now() < last_time + cooldown
    except Exception:
        return False


def detect_boundary_violation(file_path: str) -> Optional[BoundaryEvent]:
    """
    Detect if a file operation violates the current project boundary.

    MVP Rules:
    - Compare file_path against active project's working_dir
    - Only switch if file is OUTSIDE and a valid new project root is found
    - Require high/medium confidence (git or strong marker)
    - Return None if no switch should happen

    Returns:
        BoundaryEvent if switch should happen, None otherwise
    """
    if not file_path:
        return None

    # Skip system paths
    if _is_skip_path(file_path):
        return None

    # Load current active project
    active = _load_active_project()
    active_working_dir = active.get("working_dir") or active.get("detected_from_path")
    active_project_id = active.get("active_id", "")

    # If no active project, can't detect violation
    if not active_working_dir:
        return None

    # Check if file is within current project boundary
    if is_within_boundary(file_path, active_working_dir):
        # File is inside current project - no violation
        return None

    # File is OUTSIDE current project boundary
    # Try to find a new project root
    new_root, marker, confidence = find_project_root(file_path)

    # Log the detection
    print(f"[PROJECT_BOUNDARY] Violation detected")
    print(f"  File: {file_path}")
    print(f"  Active project: {active_working_dir}")
    print(f"  New root found: {new_root}")
    print(f"  Marker: {marker}")
    print(f"  Confidence: {confidence}")

    # If confidence is low, try to auto-create a project marker
    if confidence == "low":
        # Find potential project root (folder under Desktop/Documents)
        potential_root = _get_potential_project_root(file_path)

        if potential_root and _is_valid_new_project_folder(potential_root):
            print(f"  Low confidence - attempting auto-create marker in: {potential_root}")
            marker_created = auto_create_project_marker(potential_root)

            if marker_created:
                # Re-check with the new marker
                new_root, marker, confidence = find_project_root(file_path)
                print(f"  After auto-create: root={new_root}, marker={marker}, confidence={confidence}")
            else:
                print(f"  Action: SKIP (couldn't auto-create marker)")
                return None
        else:
            print(f"  Action: SKIP (low confidence, no valid folder for auto-create)")
            return None

    # Only switch on high or medium confidence
    if confidence == "low":
        print(f"  Action: SKIP (still low confidence after auto-create attempt)")
        return None

    # Check if new root is same as current (shouldn't happen, but safety check)
    if new_root and os.path.abspath(new_root) == os.path.abspath(active_working_dir):
        return None

    if not new_root:
        print(f"  Action: SKIP (no project root found)")
        return None

    # Check if new folder is a build/derivative of active project
    if _is_build_or_derivative_folder(new_root, active_working_dir):
        print(f"  Action: SKIP (build/derivative folder of active project)")
        return None

    # Check if folder was just created (likely by current session copying files)
    if _is_newly_created_folder(new_root, max_age_seconds=120):
        # Extra caution: if folder is brand new AND related to active project, skip
        new_name = Path(new_root).name.lower()
        active_name = Path(active_working_dir).name.lower()
        if active_name in new_name or new_name in active_name:
            print(f"  Action: SKIP (newly created folder related to active project)")
            return None

    # Check cooldown
    state = _load_boundary_state()
    if _is_cooldown_active(state):
        print(f"  Action: SKIP (cooldown active)")
        return None

    # Don't override manually selected projects (within 10 minutes)
    if active.get("detected_from") == "manual":
        detected_at = active.get("detected_at", "")
        if detected_at:
            try:
                manual_time = datetime.fromisoformat(detected_at)
                if datetime.now() - manual_time < timedelta(minutes=10):
                    print(f"  Action: SKIP (manual selection active, selected at {detected_at})")
                    return None
            except Exception:
                pass

    # MVP: Don't auto-switch BACK to a project we switched FROM
    # Only switch INTO new projects
    if state.get("last_switch_from") == _get_project_id_from_path(new_root):
        recent_switch = state.get("last_switch_timestamp", "")
        print(f"  Action: SKIP (would switch back to {new_root}, last switched from there at {recent_switch})")
        return None

    # Create boundary event
    new_project_id = _get_project_id_from_path(new_root)

    event = BoundaryEvent(
        old_project_id=active_project_id,
        old_working_dir=active_working_dir,
        new_project_id=new_project_id,
        new_working_dir=new_root,
        file_path=file_path,
        reason=f"git_root" if marker == ".git" else "strong_marker",
        confidence=confidence,
        timestamp=datetime.now().isoformat()
    )

    print(f"  Action: SWITCH to {new_root} ({new_project_id})")

    return event


def handle_boundary_transition(event: BoundaryEvent) -> str:
    """
    Execute the project switch.

    Returns:
        The new project_id
    """
    from managers.multi_project_manager import (
        set_active_project,
        init_project_memory,
        load_project_memory
    )

    # Log structured transition
    print(f"[PROJECT_BOUNDARY] Executing transition")
    print(f"  Old root: {event.old_working_dir}")
    print(f"  New root: {event.new_working_dir}")
    print(f"  Reason: {event.reason}")
    print(f"  Confidence: {event.confidence}")
    print(f"  Trigger file: {event.file_path}")

    # Check if project exists, create if not
    existing = load_project_memory(event.new_project_id)
    if not existing:
        print(f"  Creating new project: {event.new_project_id}")
        init_project_memory(
            project_id=event.new_project_id,
            display_name=Path(event.new_working_dir).name,
            working_dir=event.new_working_dir
        )

    # Update active project with transition metadata
    set_active_project(
        project_id=event.new_project_id,
        detected_from="boundary",
        display_name=Path(event.new_working_dir).name,
        working_dir=event.new_working_dir
    )

    # Update boundary state
    state = _load_boundary_state()
    state["last_switch_timestamp"] = event.timestamp
    state["last_switch_from"] = event.old_project_id
    state["last_switch_to"] = event.new_project_id
    _save_boundary_state(state)

    print(f"  Transition complete: {event.old_project_id} -> {event.new_project_id}")

    return event.new_project_id


def get_boundary_status() -> Dict[str, Any]:
    """Get current boundary detection status (for debugging/dashboard)."""
    active = _load_active_project()
    state = _load_boundary_state()

    return {
        "active_project": active.get("active_id"),
        "active_working_dir": active.get("working_dir"),
        "last_switch": state.get("last_switch_timestamp"),
        "last_switch_from": state.get("last_switch_from"),
        "last_switch_to": state.get("last_switch_to"),
        "cooldown_active": _is_cooldown_active(state),
        "cooldown_seconds": state.get("cooldown_seconds", SWITCH_COOLDOWN_SECONDS)
    }
