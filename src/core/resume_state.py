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

from core.durable_memory import durable_memory_write

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
        saved = durable_memory_write(
            project_file,
            updated=data,
            tool_name="resume_state",
        )
        return saved is not None
    except Exception:
        return False


def _update_project_data(
    project_id: str,
    mutator,
    attribution: Optional[Dict[str, Any]] = None,
    tool_name: str = "resume_state",
) -> Optional[Dict[str, Any]]:
    project_file = _get_project_file(project_id)
    try:
        return durable_memory_write(
            project_file,
            mutator=mutator,
            attribution=attribution,
            tool_name=tool_name,
            require_existing=True,
        )
    except Exception:
        return None


def save_resume_state(
    project_id: str,
    active_task: str,
    last_completed_step: str = "",
    current_status: str = "in_progress",
    next_recommended_action: str = "",
    short_summary: str = "",
    attribution: Optional[Dict[str, Any]] = None,
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
    resume_state = {
        "active_task": active_task,
        "last_completed_step": last_completed_step,
        "current_status": current_status,
        "next_recommended_action": next_recommended_action,
        "short_summary": short_summary,
        "updated_at": datetime.now().isoformat(),
        "version": 1
    }
    if attribution:
        resume_state.update(attribution)

    updated = _update_project_data(
        project_id,
        lambda data: {**(data or {}), "resume_state": resume_state},
        attribution=attribution,
        tool_name="save_resume_state",
    )
    if updated:
        return resume_state
    return {"error": f"Project not found or could not be updated: {project_id}"}


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
    def clear_state(data):
        data = dict(data or {})
        if "resume_state" not in data:
            return data
        history = list(data.get("resume_state_history", []))
        old_state = dict(data.pop("resume_state"))
        old_state["cleared_at"] = datetime.now().isoformat()
        history.append(old_state)
        data["resume_state_history"] = history[-5:]
        return data

    return _update_project_data(project_id, clear_state) is not None


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
