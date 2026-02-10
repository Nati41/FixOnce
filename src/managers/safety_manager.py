"""
Safety Manager for FixOnce
Provides backup, preview, approve/reject, and undo capabilities for code changes.
"""

import json
import difflib
import shutil
import threading
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any

# Import from config
from config import MEMORY_FILE

# Thread lock for file operations
_safety_lock = threading.Lock()

# Constants
DEFAULT_BACKUPS_DIR = ".fixonce_backups"
MAX_CHANGE_HISTORY = 100
BACKUP_RETENTION_DAYS = 30


def _get_memory_file() -> Path:
    """Get the project memory file path."""
    return MEMORY_FILE


def _load_memory() -> Dict[str, Any]:
    """Load project memory from JSON file."""
    memory_file = _get_memory_file()
    if not memory_file.exists():
        return {}
    try:
        with open(memory_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_memory(memory: Dict[str, Any]) -> bool:
    """Save project memory to JSON file."""
    try:
        memory_file = _get_memory_file()
        memory['stats']['last_updated'] = datetime.now().isoformat()
        with open(memory_file, 'w', encoding='utf-8') as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        print(f"[SafetyManager] Save error: {e}")
        return False


def _get_safety_section(memory: Dict[str, Any]) -> Dict[str, Any]:
    """Get or create the safety section in memory."""
    if 'safety' not in memory:
        memory['safety'] = {
            "enabled": True,
            "auto_backup": True,
            "require_approval": True,
            "changes_history": [],
            "backups_dir": DEFAULT_BACKUPS_DIR
        }
    return memory['safety']


def _generate_change_id() -> str:
    """Generate a unique change ID."""
    return f"chg_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


def _get_backups_dir(memory: Dict[str, Any]) -> Path:
    """Get the backups directory path."""
    safety = _get_safety_section(memory)
    project_root = memory.get('project_info', {}).get('root_path', '')

    if project_root:
        return Path(project_root) / safety.get('backups_dir', DEFAULT_BACKUPS_DIR)
    else:
        # Fallback to server directory
        return Path(__file__).parent / safety.get('backups_dir', DEFAULT_BACKUPS_DIR)


def _generate_diff(original: str, new: str, filename: str = "file") -> str:
    """Generate a unified diff between original and new content."""
    original_lines = original.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    # Ensure lines end with newline for proper diff
    if original_lines and not original_lines[-1].endswith('\n'):
        original_lines[-1] += '\n'
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'

    diff = difflib.unified_diff(
        original_lines,
        new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}"
    )
    return ''.join(diff)


# ============================================================================
# CORE FUNCTIONS
# ============================================================================

def init_safety_system(project_root: str = "") -> Dict[str, Any]:
    """
    Initialize the safety system for a project.

    Args:
        project_root: Path to project root directory

    Returns:
        Dict with status and settings
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        # Create backups directory
        backups_dir = _get_backups_dir(memory)
        try:
            backups_dir.mkdir(parents=True, exist_ok=True)
            # Add .gitignore to prevent committing backups
            gitignore = backups_dir / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text("*\n!.gitignore\n")
        except IOError as e:
            return {"status": "error", "message": f"Failed to create backups dir: {e}"}

        _save_memory(memory)

        return {
            "status": "ok",
            "message": "Safety system initialized",
            "settings": {
                "enabled": safety['enabled'],
                "auto_backup": safety['auto_backup'],
                "require_approval": safety['require_approval'],
                "backups_dir": str(backups_dir)
            }
        }


def get_safety_settings() -> Dict[str, Any]:
    """
    Get current safety settings.

    Returns:
        Dict with safety settings
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)
        backups_dir = _get_backups_dir(memory)

        # Count pending changes
        pending_count = sum(
            1 for c in safety.get('changes_history', [])
            if c.get('status') == 'pending'
        )

        return {
            "enabled": safety.get('enabled', True),
            "auto_backup": safety.get('auto_backup', True),
            "require_approval": safety.get('require_approval', True),
            "backups_dir": str(backups_dir),
            "pending_changes_count": pending_count,
            "total_changes": len(safety.get('changes_history', []))
        }


def update_safety_settings(
    enabled: Optional[bool] = None,
    auto_backup: Optional[bool] = None,
    require_approval: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Update safety settings.

    Args:
        enabled: Enable/disable safety system
        auto_backup: Enable/disable automatic backups
        require_approval: Require user approval for changes

    Returns:
        Dict with updated settings
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        if enabled is not None:
            safety['enabled'] = enabled
        if auto_backup is not None:
            safety['auto_backup'] = auto_backup
        if require_approval is not None:
            safety['require_approval'] = require_approval

        _save_memory(memory)

        return {
            "status": "ok",
            "message": "Settings updated",
            "settings": {
                "enabled": safety['enabled'],
                "auto_backup": safety['auto_backup'],
                "require_approval": safety['require_approval']
            }
        }


# ============================================================================
# CHANGE MANAGEMENT
# ============================================================================

def create_pending_change(
    file_path: str,
    new_content: str,
    description: str
) -> Dict[str, Any]:
    """
    Create a pending change with preview diff.

    Args:
        file_path: Path to the file to change
        new_content: New content for the file
        description: Description of the change

    Returns:
        Dict with change info and diff preview
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        # Check if safety is enabled
        if not safety.get('enabled', True):
            return {
                "status": "disabled",
                "message": "Safety system is disabled. Changes will be applied directly."
            }

        file_path = Path(file_path)
        filename = file_path.name

        # Read original content
        original_content = ""
        file_exists = file_path.exists()
        if file_exists:
            try:
                original_content = file_path.read_text(encoding='utf-8')
            except IOError as e:
                return {"status": "error", "message": f"Cannot read file: {e}"}

        # Check if content is actually different
        if original_content == new_content:
            return {
                "status": "no_change",
                "message": "File content is identical, no change needed"
            }

        # Generate diff
        diff = _generate_diff(original_content, new_content, filename)

        # Create change record
        change_id = _generate_change_id()
        change = {
            "id": change_id,
            "file_path": str(file_path),
            "original_content": original_content,
            "new_content": new_content,
            "diff": diff,
            "description": description,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "applied_at": None,
            "backup_path": None,
            "file_existed": file_exists
        }

        # Add to history
        if 'changes_history' not in safety:
            safety['changes_history'] = []
        safety['changes_history'].append(change)

        # Trim history if too long
        if len(safety['changes_history']) > MAX_CHANGE_HISTORY:
            # Keep pending changes, trim old completed ones
            pending = [c for c in safety['changes_history'] if c['status'] == 'pending']
            completed = [c for c in safety['changes_history'] if c['status'] != 'pending']
            completed = completed[-(MAX_CHANGE_HISTORY - len(pending)):]
            safety['changes_history'] = completed + pending

        _save_memory(memory)

        return {
            "status": "ok",
            "message": "Pending change created",
            "change_id": change_id,
            "file_path": str(file_path),
            "description": description,
            "diff": diff,
            "diff_lines": len(diff.splitlines()),
            "requires_approval": safety.get('require_approval', True)
        }


def preview_change(change_id: str) -> Dict[str, Any]:
    """
    Get the diff preview for a pending change.

    Args:
        change_id: ID of the change

    Returns:
        Dict with change info and diff
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        for change in safety.get('changes_history', []):
            if change['id'] == change_id:
                return {
                    "status": "ok",
                    "change": {
                        "id": change['id'],
                        "file_path": change['file_path'],
                        "description": change['description'],
                        "diff": change['diff'],
                        "change_status": change['status'],
                        "created_at": change['created_at']
                    }
                }

        return {"status": "error", "message": f"Change {change_id} not found"}


def approve_change(change_id: str) -> Dict[str, Any]:
    """
    Approve a pending change (marks it ready to apply).

    Args:
        change_id: ID of the change to approve

    Returns:
        Dict with status
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        for change in safety.get('changes_history', []):
            if change['id'] == change_id:
                if change['status'] != 'pending':
                    return {
                        "status": "error",
                        "message": f"Change is not pending (status: {change['status']})"
                    }

                change['status'] = 'approved'
                change['approved_at'] = datetime.now().isoformat()
                _save_memory(memory)

                return {
                    "status": "ok",
                    "message": "Change approved",
                    "change_id": change_id,
                    "file_path": change['file_path']
                }

        return {"status": "error", "message": f"Change {change_id} not found"}


def reject_change(change_id: str, reason: str = "") -> Dict[str, Any]:
    """
    Reject a pending change.

    Args:
        change_id: ID of the change to reject
        reason: Optional reason for rejection

    Returns:
        Dict with status
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        for change in safety.get('changes_history', []):
            if change['id'] == change_id:
                if change['status'] != 'pending':
                    return {
                        "status": "error",
                        "message": f"Change is not pending (status: {change['status']})"
                    }

                change['status'] = 'rejected'
                change['rejected_at'] = datetime.now().isoformat()
                change['rejection_reason'] = reason
                _save_memory(memory)

                return {
                    "status": "ok",
                    "message": "Change rejected",
                    "change_id": change_id,
                    "file_path": change['file_path']
                }

        return {"status": "error", "message": f"Change {change_id} not found"}


def apply_change(change_id: str) -> Dict[str, Any]:
    """
    Apply an approved change (creates backup first if enabled).

    Args:
        change_id: ID of the change to apply

    Returns:
        Dict with status and backup info
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        for change in safety.get('changes_history', []):
            if change['id'] == change_id:
                # Check status
                if change['status'] not in ('pending', 'approved'):
                    return {
                        "status": "error",
                        "message": f"Change cannot be applied (status: {change['status']})"
                    }

                # If require_approval is on and status is pending, reject
                if safety.get('require_approval', True) and change['status'] == 'pending':
                    return {
                        "status": "error",
                        "message": "Change must be approved before applying"
                    }

                file_path = Path(change['file_path'])

                # Create backup if enabled and file exists
                backup_path = None
                if safety.get('auto_backup', True) and change.get('file_existed', True):
                    backup_result = create_backup(str(file_path))
                    if backup_result.get('status') == 'ok':
                        backup_path = backup_result['backup_path']
                        change['backup_path'] = backup_path
                    elif backup_result.get('status') != 'no_file':
                        return backup_result  # Return backup error

                # Apply the change
                try:
                    # Create parent directories if needed
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(change['new_content'], encoding='utf-8')
                except IOError as e:
                    return {"status": "error", "message": f"Failed to write file: {e}"}

                # Update change status
                change['status'] = 'applied'
                change['applied_at'] = datetime.now().isoformat()
                _save_memory(memory)

                return {
                    "status": "ok",
                    "message": "Change applied successfully",
                    "change_id": change_id,
                    "file_path": str(file_path),
                    "backup_path": backup_path
                }

        return {"status": "error", "message": f"Change {change_id} not found"}


def get_pending_changes() -> List[Dict[str, Any]]:
    """
    Get list of all pending changes.

    Returns:
        List of pending changes
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        pending = []
        for change in safety.get('changes_history', []):
            if change['status'] in ('pending', 'approved'):
                pending.append({
                    "id": change['id'],
                    "file_path": change['file_path'],
                    "description": change['description'],
                    "status": change['status'],
                    "created_at": change['created_at'],
                    "diff_preview": change['diff'][:500] + "..." if len(change['diff']) > 500 else change['diff']
                })

        return pending


# ============================================================================
# BACKUP & UNDO
# ============================================================================

def create_backup(file_path: str) -> Dict[str, Any]:
    """
    Create a backup of a file.

    Args:
        file_path: Path to the file to backup

    Returns:
        Dict with backup path
    """
    with _safety_lock:
        memory = _load_memory()
        backups_dir = _get_backups_dir(memory)

        src = Path(file_path)
        if not src.exists():
            return {"status": "no_file", "message": "File does not exist"}

        # Create backups directory
        try:
            backups_dir.mkdir(parents=True, exist_ok=True)
        except IOError as e:
            return {"status": "error", "message": f"Cannot create backups dir: {e}"}

        # Generate backup filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup_name = f"{src.name}.{timestamp}"
        backup_path = backups_dir / backup_name

        # Copy file
        try:
            shutil.copy2(src, backup_path)
        except IOError as e:
            return {"status": "error", "message": f"Backup failed: {e}"}

        return {
            "status": "ok",
            "message": "Backup created",
            "backup_path": str(backup_path),
            "original_path": str(src)
        }


def undo_change(change_id: str) -> Dict[str, Any]:
    """
    Undo an applied change by restoring from backup.

    Args:
        change_id: ID of the change to undo

    Returns:
        Dict with status
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        for change in safety.get('changes_history', []):
            if change['id'] == change_id:
                if change['status'] != 'applied':
                    return {
                        "status": "error",
                        "message": f"Change cannot be undone (status: {change['status']})"
                    }

                file_path = Path(change['file_path'])
                backup_path = change.get('backup_path')

                if backup_path:
                    # Restore from backup
                    result = restore_from_backup(backup_path, str(file_path))
                    if result['status'] != 'ok':
                        return result
                else:
                    # No backup - restore original content from memory
                    if change.get('file_existed', True):
                        try:
                            file_path.write_text(change['original_content'], encoding='utf-8')
                        except IOError as e:
                            return {"status": "error", "message": f"Restore failed: {e}"}
                    else:
                        # File didn't exist before, delete it
                        try:
                            if file_path.exists():
                                file_path.unlink()
                        except IOError as e:
                            return {"status": "error", "message": f"Delete failed: {e}"}

                # Update change status
                change['status'] = 'undone'
                change['undone_at'] = datetime.now().isoformat()
                _save_memory(memory)

                return {
                    "status": "ok",
                    "message": "Change undone successfully",
                    "change_id": change_id,
                    "file_path": str(file_path)
                }

        return {"status": "error", "message": f"Change {change_id} not found"}


def undo_last_change() -> Dict[str, Any]:
    """
    Undo the most recent applied change.

    Returns:
        Dict with status
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        # Find the most recent applied change
        applied = [
            c for c in safety.get('changes_history', [])
            if c['status'] == 'applied'
        ]

        if not applied:
            return {"status": "error", "message": "No applied changes to undo"}

        # Sort by applied_at and get the most recent
        applied.sort(key=lambda x: x.get('applied_at', ''), reverse=True)
        last_change = applied[0]

    # Undo the change (release lock first as undo_change acquires it)
    return undo_change(last_change['id'])


def restore_from_backup(backup_path: str, target_path: str) -> Dict[str, Any]:
    """
    Restore a file from a backup.

    Args:
        backup_path: Path to the backup file
        target_path: Path to restore to

    Returns:
        Dict with status
    """
    backup = Path(backup_path)
    target = Path(target_path)

    if not backup.exists():
        return {"status": "error", "message": f"Backup not found: {backup_path}"}

    try:
        shutil.copy2(backup, target)
    except IOError as e:
        return {"status": "error", "message": f"Restore failed: {e}"}

    return {
        "status": "ok",
        "message": "File restored from backup",
        "backup_path": backup_path,
        "target_path": target_path
    }


def get_change_history(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Get change history.

    Args:
        limit: Maximum number of changes to return

    Returns:
        List of changes (most recent first)
    """
    with _safety_lock:
        memory = _load_memory()
        safety = _get_safety_section(memory)

        history = []
        for change in safety.get('changes_history', [])[-limit:]:
            history.append({
                "id": change['id'],
                "file_path": change['file_path'],
                "description": change['description'],
                "status": change['status'],
                "created_at": change['created_at'],
                "applied_at": change.get('applied_at'),
                "undone_at": change.get('undone_at'),
                "backup_path": change.get('backup_path')
            })

        # Return most recent first
        history.reverse()
        return history


def get_backups_list() -> List[Dict[str, Any]]:
    """
    Get list of all backup files.

    Returns:
        List of backup info
    """
    with _safety_lock:
        memory = _load_memory()
        backups_dir = _get_backups_dir(memory)

        if not backups_dir.exists():
            return []

        backups = []
        for backup_file in backups_dir.iterdir():
            if backup_file.name.startswith('.'):
                continue

            stat = backup_file.stat()
            backups.append({
                "path": str(backup_file),
                "name": backup_file.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat()
            })

        # Sort by creation time, newest first
        backups.sort(key=lambda x: x['created_at'], reverse=True)
        return backups


def cleanup_old_backups(days: int = BACKUP_RETENTION_DAYS) -> Dict[str, Any]:
    """
    Clean up backup files older than specified days.

    Args:
        days: Delete backups older than this many days

    Returns:
        Dict with cleanup stats
    """
    with _safety_lock:
        memory = _load_memory()
        backups_dir = _get_backups_dir(memory)

        if not backups_dir.exists():
            return {"status": "ok", "deleted": 0, "message": "No backups directory"}

        cutoff = datetime.now() - timedelta(days=days)
        deleted = 0
        errors = []

        for backup_file in backups_dir.iterdir():
            if backup_file.name.startswith('.'):
                continue

            try:
                created = datetime.fromtimestamp(backup_file.stat().st_ctime)
                if created < cutoff:
                    backup_file.unlink()
                    deleted += 1
            except IOError as e:
                errors.append(f"{backup_file.name}: {e}")

        return {
            "status": "ok" if not errors else "partial",
            "deleted": deleted,
            "errors": errors if errors else None,
            "message": f"Deleted {deleted} old backup(s)"
        }
