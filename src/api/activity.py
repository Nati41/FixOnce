"""
FixOnce Activity API
Receives activity logs from Claude Code hooks.
Now with Git diff stats and file type context!

Phase 0: Added project_id tagging to prevent cross-project leakage.
Phase 1: Added boundary detection for auto project switching.
"""

import sys
from pathlib import Path

# Add src directory to path for imports
SRC_DIR = Path(__file__).parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from flask import Blueprint, jsonify, request
from datetime import datetime
import json
import subprocess
import hashlib

# Boundary detection imports
try:
    from core.boundary_detector import (
        detect_boundary_violation,
        handle_boundary_transition
    )
    BOUNDARY_DETECTION_ENABLED = True
    print("[Activity] Boundary detection ENABLED")
except ImportError as e:
    BOUNDARY_DETECTION_ENABLED = False
    print(f"[Activity] Boundary detection not available: {e}")

# Session registry for updating Active AI
try:
    from core.session_registry import get_registry
    SESSION_REGISTRY_ENABLED = True
except ImportError:
    SESSION_REGISTRY_ENABLED = False

activity_bp = Blueprint('activity', __name__)


# File type to context mapping
FILE_TYPE_CONTEXT = {
    # Styles
    ".css": "style",
    ".scss": "style",
    ".sass": "style",
    ".less": "style",
    ".styled.js": "style",
    ".styled.ts": "style",

    # Scripts/Logic
    ".js": "code",
    ".ts": "code",
    ".jsx": "component",
    ".tsx": "component",
    ".vue": "component",
    ".svelte": "component",

    # Python
    ".py": "code",

    # Config
    ".json": "config",
    ".yaml": "config",
    ".yml": "config",
    ".toml": "config",
    ".ini": "config",
    ".env": "env",

    # Data/Content
    ".html": "ui",
    ".md": "docs",
    ".txt": "text",

    # Tests
    ".test.js": "test",
    ".test.ts": "test",
    ".spec.js": "test",
    ".spec.ts": "test",
    "_test.py": "test",
    "test_.py": "test",
}


def _get_file_type_context(file_path: str) -> str:
    """Get context word based on file type."""
    if not file_path:
        return ""

    file_lower = file_path.lower()

    # Check compound extensions first (like .test.js)
    for ext, context in FILE_TYPE_CONTEXT.items():
        if file_lower.endswith(ext):
            return context

    # Check simple extension
    ext = Path(file_path).suffix.lower()
    return FILE_TYPE_CONTEXT.get(ext, "")


def _get_git_diff_stats(file_path: str, cwd: str = None) -> dict:
    """Get git diff statistics for a file."""
    try:
        if not file_path:
            return {}

        # Determine working directory
        work_dir = cwd or str(Path(file_path).parent)

        # Run git diff --numstat for the specific file
        result = subprocess.run(
            ["git", "diff", "--numstat", "HEAD~1", "--", file_path],
            capture_output=True,
            text=True,
            cwd=work_dir,
            timeout=5
        )

        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('\t')
            if len(parts) >= 2:
                added = int(parts[0]) if parts[0] != '-' else 0
                removed = int(parts[1]) if parts[1] != '-' else 0
                return {"added": added, "removed": removed}

        # Try unstaged changes if no committed diff
        result = subprocess.run(
            ["git", "diff", "--numstat", "--", file_path],
            capture_output=True,
            text=True,
            cwd=work_dir,
            timeout=5
        )

        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('\t')
            if len(parts) >= 2:
                added = int(parts[0]) if parts[0] != '-' else 0
                removed = int(parts[1]) if parts[1] != '-' else 0
                return {"added": added, "removed": removed}

    except Exception as e:
        print(f"[Activity] Git diff error: {e}")

    return {}

# Activity log file
DATA_DIR = Path(__file__).parent.parent.parent / "data"
ACTIVITY_FILE = DATA_DIR / "activity_log.json"


def _load_activity():
    """Load activity log."""
    if ACTIVITY_FILE.exists():
        try:
            with open(ACTIVITY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"activities": [], "sessions": {}}


def _save_activity(data):
    """Save activity log."""
    DATA_DIR.mkdir(exist_ok=True)
    with open(ACTIVITY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_human_name(data: dict) -> str:
    """Generate human-readable name for activity."""
    file_path = data.get("file", "")
    tool = data.get("tool", "")
    command = data.get("command", "")

    if file_path:
        # Get filename without path
        name = Path(file_path).stem
        # Common file type mappings
        suffixes = {
            "server": "Server",
            "dashboard": "Dashboard",
            "activity": "Activity",
            "memory": "Memory",
            "status": "Status",
            "config": "Config",
            "test": "Test",
            "index": "Index",
        }
        for key, label in suffixes.items():
            if key in name.lower():
                return label
        return name.title()[:20]

    if command:
        # First word of command
        return command.split()[0][:15] if command.split() else "Command"

    return tool or "Activity"


def _get_project_id_from_cwd(cwd: str) -> str:
    """Generate project_id from cwd (same logic as MCP server)."""
    if not cwd:
        return "__global__"
    try:
        path_hash = hashlib.md5(cwd.encode()).hexdigest()[:12]
        name = Path(cwd).name
        return f"{name}_{path_hash}"
    except:
        return "__global__"


def _get_project_id_from_file(file_path: str) -> str:
    """
    Get project_id from file path using boundary detection.
    Falls back to __global__ if no project found.
    """
    if not file_path:
        return "__global__"

    try:
        if BOUNDARY_DETECTION_ENABLED:
            from core.boundary_detector import find_project_root, _get_project_id_from_path
            project_root, marker, confidence = find_project_root(file_path)
            if project_root and confidence in ("high", "medium"):
                return _get_project_id_from_path(project_root)

        # Fallback: use file's parent directory
        parent = str(Path(file_path).parent)
        return _get_project_id_from_cwd(parent)
    except Exception:
        return "__global__"


def _get_project_id_smart(cwd: str, file_path: str) -> str:
    """
    Smart project ID detection - tries multiple methods.
    Priority:
    1. Boundary detection from file_path
    2. cwd if valid
    3. Active project from dashboard
    4. __global__ as fallback
    """
    # 1. Try boundary detection from file_path
    if file_path:
        project_id = _get_project_id_from_file(file_path)
        if project_id != "__global__":
            return project_id

    # 2. Try cwd if valid (not home directory)
    if cwd:
        home = str(Path.home())
        if cwd != home and Path(cwd).exists():
            return _get_project_id_from_cwd(cwd)

    # 3. Try active project from dashboard
    try:
        active_file = DATA_DIR / "active_project.json"
        if active_file.exists():
            import json
            with open(active_file, 'r') as f:
                data = json.load(f)
            active_id = data.get("active_id")
            if active_id:
                return active_id
    except Exception:
        pass

    return "__global__"


def _update_session_registry(editor: str, project_id: str, project_path: str, tool: str):
    """
    Update session registry when activity is logged from hooks.
    This ensures Active AI updates even when MCP tools aren't called.
    """
    if not SESSION_REGISTRY_ENABLED:
        return

    if not editor or editor == "unknown":
        return

    if not project_id or project_id == "__global__":
        return

    try:
        registry = get_registry()
        session = registry.get_or_create(editor, project_id, project_path or "")
        if session:
            session.touch()
            # Log the tool call for activity tracking
            if tool:
                session.log_tool_call(f"hook:{tool}")
    except Exception as e:
        print(f"[Activity] Session registry update failed: {e}")


@activity_bp.route("/log", methods=["POST"])
def log_activity():
    """
    Log an activity from Claude Code hooks.

    Body:
        type: "file_change" | "command"
        tool: tool name
        file: file path (for file changes)
        command: command (for commands)
        cwd: working directory
        timestamp: ISO timestamp
    """
    try:
        data = request.get_json(silent=True) or {}

        # Skip empty/invalid activities (but allow MCP tool activities)
        is_mcp_activity = data.get("type") == "mcp_tool" or data.get("file_context") == "memory"
        if not is_mcp_activity and not data.get("file") and not data.get("command") and not data.get("cwd"):
            return jsonify({"status": "skipped", "reason": "no meaningful data"})

        file_path = data.get("file")
        cwd = data.get("cwd")
        boundary_transition = None

        # For MCP activities, use the provided project_id directly
        if is_mcp_activity and data.get("project_id"):
            project_id = data.get("project_id")
        # Phase 1: Check for boundary violation (file outside active project)
        elif BOUNDARY_DETECTION_ENABLED and file_path and data.get("tool") in ["Edit", "Write", "NotebookEdit"]:
            boundary_event = detect_boundary_violation(file_path)
            if boundary_event:
                # High or medium confidence - execute switch
                new_project_id = handle_boundary_transition(boundary_event)
                project_id = new_project_id
                boundary_transition = boundary_event.to_dict()
            else:
                # No violation or low confidence - use smart detection
                project_id = _get_project_id_smart(cwd, file_path)
        else:
            # Fallback: Use smart detection (handles empty cwd)
            project_id = _get_project_id_smart(cwd, file_path)

        # Get enriched data
        # For MCP activities, use provided file_context; otherwise detect from file
        if is_mcp_activity:
            file_context = data.get("file_context", "memory")
        else:
            file_context = _get_file_type_context(file_path) if file_path else ""
        diff_stats = _get_git_diff_stats(file_path, cwd) if file_path and data.get("tool") in ["Edit", "Write"] else {}

        # Get current editor - use provided editor for MCP activities
        if is_mcp_activity and data.get("editor"):
            current_editor = data.get("editor")
        else:
            # Try to get from project memory
            current_editor = None
            try:
                from managers.multi_project_manager import load_project_memory
                if project_id and project_id != "__global__":
                    memory = load_project_memory(project_id)
                    if memory and memory.get("ai_session"):
                        current_editor = memory["ai_session"].get("editor")
            except:
                pass

            # Fallback: if this is from hooks (Edit/Write/Read tools), assume Claude Code
            if not current_editor and data.get("tool") in ["Edit", "Write", "Read", "NotebookEdit"]:
                current_editor = "claude"
            elif not current_editor:
                current_editor = "unknown"

        activity = {
            "id": f"act_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
            "type": data.get("type", "unknown"),
            "tool": data.get("tool"),
            "file": file_path,
            "command": data.get("command"),
            "cwd": cwd,
            "project_id": project_id,  # Phase 0: Tag with project
            "editor": current_editor,  # Track which AI made this action
            "timestamp": data.get("timestamp") or datetime.now().isoformat(),
            "human_name": _get_human_name(data),
            "file_context": file_context,
            "diff": diff_stats,
            "boundary_transition": boundary_transition  # Phase 1: Track project switches
        }

        log = _load_activity()
        log["activities"].insert(0, activity)  # Most recent first

        # Keep only last 100 activities (global, will be filtered by project_id when reading)
        log["activities"] = log["activities"][:100]

        _save_activity(log)

        # Update session registry so Active AI updates in dashboard
        _update_session_registry(current_editor, project_id, cwd, data.get("tool"))

        print(f"[Activity] {activity['type']}: {activity.get('file') or (activity.get('command') or '')[:50] or activity.get('human_name', '')}")

        return jsonify({"status": "ok", "activity": activity})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@activity_bp.route("/feed", methods=["GET"])
def get_activity_feed():
    """
    Get activity feed for dashboard.

    Query params:
        limit: max activities (default 20)
    """
    try:
        limit = request.args.get("limit", 20, type=int)

        log = _load_activity()
        activities = log.get("activities", [])[:limit]

        return jsonify({
            "activities": activities,
            "count": len(activities),
            "total": len(log.get("activities", []))
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


