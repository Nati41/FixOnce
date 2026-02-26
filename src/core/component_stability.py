"""
Component Stability Layer

Tracks component stability states and enables rollback to known-good states.

Features:
- Clear status: stable/building/broken
- File mapping: which files belong to each component
- Checkpoint: last known good commit per component
- History: track all changes
- Rollback: restore to last stable state via Git
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Valid statuses for components
VALID_STATUSES = ["stable", "building", "broken"]

# Status mapping from old to new (for backwards compatibility)
STATUS_MIGRATION = {
    "done": "stable",
    "in_progress": "building",
    "not_started": "building",
    "blocked": "broken"
}


def get_current_commit(repo_path: str) -> Optional[Dict[str, str]]:
    """
    Get current git commit info.

    Returns:
        {"hash": "abc123...", "date": "2026-02-26T10:00:00", "message": "..."}
        or None if not a git repo
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return None

        commit_hash = result.stdout.strip()

        # Get commit date
        date_result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        commit_date = date_result.stdout.strip() if date_result.returncode == 0 else None

        # Get commit message (first line)
        msg_result = subprocess.run(
            ["git", "log", "-1", "--format=%s", commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        commit_msg = msg_result.stdout.strip() if msg_result.returncode == 0 else ""

        return {
            "hash": commit_hash,
            "short_hash": commit_hash[:8],
            "date": commit_date,
            "message": commit_msg[:100]
        }
    except Exception:
        return None


def get_changed_files_since(repo_path: str, since_commit: str) -> List[str]:
    """Get list of files changed since a specific commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", since_commit, "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return []
    except Exception:
        return []


def get_files_in_commit(repo_path: str, commit_hash: str) -> List[str]:
    """Get list of files changed in a specific commit."""
    try:
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return []
    except Exception:
        return []


def rollback_files(repo_path: str, commit_hash: str, files: List[str]) -> Dict[str, Any]:
    """
    Rollback specific files to a previous commit state.

    Args:
        repo_path: Path to git repository
        commit_hash: The commit to restore from
        files: List of file paths to restore

    Returns:
        {"success": True/False, "restored": [...], "errors": [...]}
    """
    restored = []
    errors = []

    for file_path in files:
        try:
            result = subprocess.run(
                ["git", "checkout", commit_hash, "--", file_path],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                restored.append(file_path)
            else:
                errors.append({"file": file_path, "error": result.stderr.strip()})
        except Exception as e:
            errors.append({"file": file_path, "error": str(e)})

    return {
        "success": len(errors) == 0,
        "restored": restored,
        "errors": errors,
        "commit": commit_hash
    }


def create_rollback_branch(repo_path: str, commit_hash: str, branch_name: str = None) -> Dict[str, Any]:
    """
    Create a new branch from a stable commit for safe rollback.

    Args:
        repo_path: Path to git repository
        commit_hash: The commit to branch from
        branch_name: Optional branch name (auto-generated if not provided)

    Returns:
        {"success": True/False, "branch": "...", "error": "..."}
    """
    if not branch_name:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"fixonce-rollback-{timestamp}"

    try:
        # Create branch from commit
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name, commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            return {
                "success": True,
                "branch": branch_name,
                "from_commit": commit_hash
            }
        else:
            return {
                "success": False,
                "error": result.stderr.strip()
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def mark_component_stable(
    component: Dict[str, Any],
    repo_path: str,
    marked_by: str = "unknown"
) -> Dict[str, Any]:
    """
    Mark a component as stable and record the current commit as checkpoint.

    Args:
        component: The component dict to update
        repo_path: Path to git repository
        marked_by: Who is marking this stable (e.g., "claude", "user")

    Returns:
        Updated component dict
    """
    commit_info = get_current_commit(repo_path)
    now = datetime.now().isoformat()

    # Update status
    component["status"] = "stable"
    component["updated_at"] = now

    # Record stable checkpoint
    if commit_info:
        component["last_stable"] = {
            "commit_hash": commit_info["hash"],
            "commit_short": commit_info["short_hash"],
            "commit_date": commit_info["date"],
            "commit_message": commit_info["message"],
            "marked_at": now,
            "marked_by": marked_by
        }

    # Add to history
    if "history" not in component:
        component["history"] = []

    component["history"].append({
        "status": "stable",
        "timestamp": now,
        "by": marked_by,
        "commit": commit_info["short_hash"] if commit_info else None,
        "action": "marked_stable"
    })

    # Keep last 20 history entries
    if len(component["history"]) > 20:
        component["history"] = component["history"][-20:]

    return component


def add_files_to_component(
    component: Dict[str, Any],
    files: List[str]
) -> Dict[str, Any]:
    """
    Add files to a component's file list.

    Args:
        component: The component dict
        files: List of file paths to add

    Returns:
        Updated component dict
    """
    if "files" not in component:
        component["files"] = []

    for f in files:
        if f not in component["files"]:
            component["files"].append(f)

    return component


def detect_files_from_activity(
    repo_path: str,
    since_commit: str,
    component_name: str
) -> List[str]:
    """
    Auto-detect which files belong to a component based on recent changes.

    This is a simple heuristic - files changed since the component was
    created are likely part of it.

    Args:
        repo_path: Path to git repository
        since_commit: Commit when component work started
        component_name: Name of the component (for filtering)

    Returns:
        List of file paths that likely belong to this component
    """
    changed_files = get_changed_files_since(repo_path, since_commit)

    # Filter out common non-component files
    ignore_patterns = [
        ".git", "node_modules", "__pycache__", ".pyc",
        "package-lock.json", "yarn.lock", ".DS_Store"
    ]

    filtered = []
    for f in changed_files:
        skip = False
        for pattern in ignore_patterns:
            if pattern in f:
                skip = True
                break
        if not skip:
            filtered.append(f)

    return filtered


def check_component_stability(
    component: Dict[str, Any],
    repo_path: str
) -> Dict[str, Any]:
    """
    Check if a stable component has been modified since its checkpoint.

    Args:
        component: The component dict
        repo_path: Path to git repository

    Returns:
        {
            "is_stable": True/False,
            "modified_since_checkpoint": True/False,
            "changed_files": [...],
            "can_rollback": True/False
        }
    """
    result = {
        "is_stable": component.get("status") == "stable",
        "modified_since_checkpoint": False,
        "changed_files": [],
        "can_rollback": False
    }

    last_stable = component.get("last_stable")
    if not last_stable:
        return result

    commit_hash = last_stable.get("commit_hash")
    if not commit_hash:
        return result

    # Check if files in this component have changed since checkpoint
    component_files = set(component.get("files", []))

    if component_files:
        all_changed = get_changed_files_since(repo_path, commit_hash)
        changed_component_files = [f for f in all_changed if f in component_files]

        if changed_component_files:
            result["modified_since_checkpoint"] = True
            result["changed_files"] = changed_component_files
            result["can_rollback"] = True

    return result


def migrate_component_status(component: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate old status values to new ones.

    Old: done, in_progress, not_started, blocked
    New: stable, building, broken
    """
    old_status = component.get("status", "building")

    if old_status in VALID_STATUSES:
        # Already new format
        return component

    # Migrate to new status
    new_status = STATUS_MIGRATION.get(old_status, "building")
    component["status"] = new_status

    # Add migration note to history
    if "history" not in component:
        component["history"] = []

    component["history"].append({
        "action": "status_migrated",
        "old_status": old_status,
        "new_status": new_status,
        "timestamp": datetime.now().isoformat(),
        "by": "system"
    })

    return component


def get_stability_summary(components: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get a summary of component stability across the project.

    Returns:
        {
            "total": 10,
            "stable": 5,
            "building": 3,
            "broken": 2,
            "with_checkpoints": 4,
            "can_rollback": 2
        }
    """
    summary = {
        "total": len(components),
        "stable": 0,
        "building": 0,
        "broken": 0,
        "with_checkpoints": 0,
        "with_files": 0
    }

    for comp in components:
        status = comp.get("status", "building")

        # Count by status (handle both old and new format)
        if status in ["stable", "done"]:
            summary["stable"] += 1
        elif status in ["broken", "blocked"]:
            summary["broken"] += 1
        else:
            summary["building"] += 1

        # Count features
        if comp.get("last_stable"):
            summary["with_checkpoints"] += 1
        if comp.get("files"):
            summary["with_files"] += 1

    return summary
