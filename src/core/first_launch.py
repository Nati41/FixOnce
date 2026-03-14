"""
FixOnce First Launch Initialization
Creates necessary data files from templates on first run.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime


def get_data_dir() -> Path:
    """Get the data directory path."""
    return Path(__file__).parent.parent.parent / "data"


def is_first_launch() -> bool:
    """Check if this is the first launch (no user data exists)."""
    data_dir = get_data_dir()

    # Check for key user data files
    required_files = [
        "active_project.json",
        "session_registry.json",
    ]

    for filename in required_files:
        filepath = data_dir / filename
        if not filepath.exists():
            return True

        # Also check if file is empty or has null/empty data
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                # For active_project, check if it has a valid active_id
                if filename == "active_project.json":
                    if data.get("active_id") is None:
                        continue  # Valid empty state
        except (json.JSONDecodeError, IOError):
            return True

    return False


def initialize_data_files():
    """Initialize data files from templates."""
    data_dir = get_data_dir()

    # Ensure directories exist
    (data_dir / "projects_v2").mkdir(parents=True, exist_ok=True)
    (data_dir / "global").mkdir(parents=True, exist_ok=True)

    # Template mappings: template_name -> target_name
    templates = {
        "active_project.template.json": "active_project.json",
        "session_registry.template.json": "session_registry.json",
        "activity_log.template.json": "activity_log.json",
        "project_memory.template.json": "project_memory.json",
    }

    initialized = []

    for template_name, target_name in templates.items():
        template_path = data_dir / template_name
        target_path = data_dir / target_name

        # Only create if target doesn't exist
        if not target_path.exists() and template_path.exists():
            shutil.copy(template_path, target_path)
            initialized.append(target_name)

    # Create empty files that need to exist
    empty_json_files = [
        "fixonce_enabled.json",
        "system_mode.json",
        "mcp_compliance.json",
        "boundary_state.json",
        "project_index.json",
    ]

    for filename in empty_json_files:
        filepath = data_dir / filename
        if not filepath.exists():
            with open(filepath, 'w') as f:
                json.dump({}, f)
            initialized.append(filename)

    # Create gitkeep files
    for subdir in ["projects_v2", "global"]:
        gitkeep = data_dir / subdir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    return initialized


def ensure_initialized():
    """Ensure data files are initialized. Call this on server startup."""
    if is_first_launch():
        print("[FixOnce] First launch detected - initializing data files...")
        initialized = initialize_data_files()
        if initialized:
            print(f"[FixOnce] Initialized: {', '.join(initialized)}")
        print("[FixOnce] Ready for use")
        return True
    return False


def get_first_launch_status() -> dict:
    """Get status for dashboard display."""
    data_dir = get_data_dir()

    status = {
        "is_first_launch": is_first_launch(),
        "has_active_project": False,
        "project_count": 0,
        "data_dir": str(data_dir),
    }

    # Check active project
    active_file = data_dir / "active_project.json"
    if active_file.exists():
        try:
            with open(active_file, 'r') as f:
                data = json.load(f)
                status["has_active_project"] = data.get("active_id") is not None
        except (json.JSONDecodeError, IOError):
            pass

    # Count projects
    projects_dir = data_dir / "projects_v2"
    if projects_dir.exists():
        status["project_count"] = len([
            f for f in projects_dir.glob("*.json")
            if not f.name.startswith('.')
        ])

    return status
