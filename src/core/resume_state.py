"""
Session Resume State - Persistent work state across sessions.

This is NOT knowledge storage (insights, decisions, solutions).
This is operational state - where we were in the work.

Stored per project in the project's JSON file under "resume_state" key.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Data paths
DATA_DIR = Path(__file__).parent.parent.parent / 'data'
PROJECTS_DIR = DATA_DIR / 'projects_v2'


def _get_project_file(project_id: str) -> Path:
    """Get the project file path."""
    return PROJECTS_DIR / f"{project_id}.json"


def _load_project_data(project_id: str) -> Optional[Dict[str, Any]]:
    """Load project data from file."""
    project_file = _get_project_file(project_id)
    if not project_file.exists():
        return None
    try:
        with open(project_file, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def _save_project_data(project_id: str, data: Dict[str, Any]) -> bool:
    """Save project data to file."""
    project_file = _get_project_file(project_id)
    try:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(project_file, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def save_resume_state(
    project_id: str,
    active_task: str,
    last_completed_step: str = "",
    current_status: str = "in_progress",
    next_recommended_action: str = "",
    short_summary: str = ""
) -> Dict[str, Any]:
    """
    Save the current session resume state.

    Args:
        project_id: The project identifier
        active_task: What task is currently in progress
        last_completed_step: The last step that was completed
        current_status: One of: in_progress, waiting_for_restart, blocked, paused, completed
        next_recommended_action: What should be done next
        short_summary: Human-readable summary of where we stopped

    Returns:
        The saved resume state
    """
    data = _load_project_data(project_id)
    if not data:
        return {"error": f"Project not found: {project_id}"}

    resume_state = {
        "active_task": active_task,
        "last_completed_step": last_completed_step,
        "current_status": current_status,
        "next_recommended_action": next_recommended_action,
        "short_summary": short_summary,
        "updated_at": datetime.now().isoformat(),
        "version": 1
    }

    data["resume_state"] = resume_state

    if _save_project_data(project_id, data):
        return resume_state
    else:
        return {"error": "Failed to save resume state"}


def get_resume_state(project_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the current resume state for a project.

    Returns None if no resume state exists.
    """
    data = _load_project_data(project_id)
    if not data:
        return None

    return data.get("resume_state")


def clear_resume_state(project_id: str) -> bool:
    """
    Clear the resume state (task completed, no longer relevant).
    """
    data = _load_project_data(project_id)
    if not data:
        return False

    if "resume_state" in data:
        # Archive before clearing
        if "resume_state_history" not in data:
            data["resume_state_history"] = []

        old_state = data.pop("resume_state")
        old_state["cleared_at"] = datetime.now().isoformat()
        data["resume_state_history"].append(old_state)

        # Keep only last 5 states
        data["resume_state_history"] = data["resume_state_history"][-5:]

        return _save_project_data(project_id, data)

    return True


def format_resume_for_init(resume_state: Dict[str, Any]) -> str:
    """
    Format resume state for display in init_session response.
    """
    if not resume_state:
        return ""

    # Skip if completed or too old
    status = resume_state.get("current_status", "")
    if status == "completed":
        return ""

    # Check if state is fresh (within 24 hours)
    updated_at = resume_state.get("updated_at", "")
    if updated_at:
        try:
            updated = datetime.fromisoformat(updated_at)
            age_hours = (datetime.now() - updated).total_seconds() / 3600
            if age_hours > 24:
                return ""  # Too old, skip
        except:
            pass

    lines = ["## 🔄 Resume State Found"]
    lines.append("")

    if resume_state.get("active_task"):
        lines.append(f"**Task:** {resume_state['active_task']}")

    if resume_state.get("last_completed_step"):
        lines.append(f"**Last completed:** {resume_state['last_completed_step']}")

    status_emoji = {
        "in_progress": "🔵",
        "waiting_for_restart": "⏳",
        "blocked": "🔴",
        "paused": "⏸️"
    }
    if status:
        emoji = status_emoji.get(status, "")
        lines.append(f"**Status:** {emoji} {status}")

    if resume_state.get("next_recommended_action"):
        lines.append(f"**Next action:** {resume_state['next_recommended_action']}")

    if resume_state.get("short_summary"):
        lines.append("")
        lines.append(f"_{resume_state['short_summary']}_")

    lines.append("")
    lines.append("---")

    return "\n".join(lines)
