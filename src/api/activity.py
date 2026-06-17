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
import os
import re
import subprocess
from core.project_context import ProjectContext
from core.runtime_log import log_runtime_event
from core.unreported_work import mark_work
from core.windows_subprocess import no_window_creationflags

# Boundary detection imports
try:
    if os.environ.get("FIXONCE_DISABLE_BOUNDARY") == "1":
        raise ImportError("disabled by FIXONCE_DISABLE_BOUNDARY")
    else:
        from core.boundary_detector import (
            detect_boundary_violation,
            handle_boundary_transition
        )
        BOUNDARY_DETECTION_ENABLED = True
        log_runtime_event("[Activity] Boundary detection enabled")
except ImportError as e:
    BOUNDARY_DETECTION_ENABLED = False
    log_runtime_event(f"[Activity] Boundary detection not available: {e}", e)

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
            timeout=5,
            creationflags=no_window_creationflags(),
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
            timeout=5,
            creationflags=no_window_creationflags(),
        )

        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('\t')
            if len(parts) >= 2:
                added = int(parts[0]) if parts[0] != '-' else 0
                removed = int(parts[1]) if parts[1] != '-' else 0
                return {"added": added, "removed": removed}

    except Exception as e:
        log_runtime_event(f"[Activity] Git diff error: {e}", e)

    return {}

# Activity log file - canonical path: USER_DATA_DIR / "activity_log.json"
# Must match dashboard reader in status.py (via config.DATA_DIR = USER_DATA_DIR)
from config import USER_DATA_DIR
ACTIVITY_FILE = USER_DATA_DIR / "activity_log.json"


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
    USER_DATA_DIR.mkdir(exist_ok=True)
    with open(ACTIVITY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_human_name(data: dict) -> str:
    """Generate human-readable name for activity."""
    # If caller provided a custom human_name, use it
    if data.get("human_name"):
        return data["human_name"]

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
    """Resolve project_id from cwd using the canonical project identity."""
    if not cwd:
        return "__global__"
    try:
        return ProjectContext.from_path(cwd)
    except Exception:
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
            with open(active_file, 'r', encoding='utf-8') as f:
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
        log_runtime_event(f"[Activity] Session registry update failed: {e}", e)


def _is_git_commit(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    return bool(re.search(r"(?:^|[;&|])\s*git(?:\s+-C\s+\S+)?\s+commit(?:\s|$)", normalized))


def _is_file_delete(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    return bool(re.search(r"(?:^|[;&|])\s*(?:rm|unlink|git\s+rm)(?:\s|$)", normalized))


def _is_file_write_command(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    return bool(
        re.search(r"(?:^|[;&|])\s*(?:touch|cp|mv|install|tee)(?:\s|$)", normalized)
        or re.search(r"(?:^|[^<])>{1,2}(?!=)", normalized)
    )


def _track_unreported_work(data: dict, project_id: str, editor: str) -> None:
    activity_type = data.get("type")
    tool = str(data.get("tool") or "")
    file_path = str(data.get("file") or "")
    command = str(data.get("command") or "")
    event = str(data.get("event") or "")

    if activity_type == "file_change" and tool in {
        "Edit", "Write", "NotebookEdit", "apply_patch"
    }:
        mark_work(
            project_id,
            editor,
            "file_delete" if event == "deleted" else "file_write",
            file_path=file_path,
            session_id=str(data.get("session_id") or ""),
            source=str(data.get("source") or tool),
        )
    elif activity_type == "command" and _is_git_commit(command):
        mark_work(
            project_id,
            editor,
            "git_commit",
            command=command,
            session_id=str(data.get("session_id") or ""),
            source=str(data.get("source") or tool or "PostToolUse"),
        )
    elif activity_type == "command" and _is_file_delete(command):
        mark_work(
            project_id,
            editor,
            "file_delete",
            command=command,
            session_id=str(data.get("session_id") or ""),
            source=str(data.get("source") or tool or "PostToolUse"),
        )
    elif activity_type == "command" and _is_file_write_command(command):
        mark_work(
            project_id,
            editor,
            "file_write",
            command=command,
            session_id=str(data.get("session_id") or ""),
            source=str(data.get("source") or tool or "PostToolUse"),
        )


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
        if data.get("editor"):
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
            "event": data.get("event"),
            "boundary_transition": boundary_transition  # Phase 1: Track project switches
        }

        log = _load_activity()
        log["activities"].insert(0, activity)  # Most recent first

        # Keep only last 100 activities (global, will be filtered by project_id when reading)
        log["activities"] = log["activities"][:100]

        _save_activity(log)

        # Update session registry so Active AI updates in dashboard
        _update_session_registry(current_editor, project_id, cwd, data.get("tool"))
        _track_unreported_work(data, project_id, current_editor)

        log_runtime_event(f"[Activity] {activity['type']}: {activity.get('file') or (activity.get('command') or '')[:50] or activity.get('human_name', '')}")

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
        all_activities = log.get("activities", [])

        # Prefer activity from the currently active project so the dashboard
        # doesn't show stale "Recent" items from older sessions in other projects.
        try:
            from managers.multi_project_manager import get_active_project_id
            active_project_id = get_active_project_id()
        except Exception:
            active_project_id = None

        if active_project_id:
            project_activities = [
                act for act in all_activities
                if act.get("project_id") == active_project_id
            ]
            global_activities = [
                act for act in all_activities
                if act.get("project_id") == "__global__"
            ]
            activities = (project_activities + global_activities)[:limit]
        else:
            activities = all_activities[:limit]

        return jsonify({
            "activities": activities,
            "count": len(activities),
            "total": len(all_activities)
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _extract_area(path: str) -> str:
    """
    Extract area from a file path.

    Examples:
        /Users/.../src/auth/login.py → "auth"
        /Users/.../src/api/status.py → "api"
        /Users/.../tests/test_auth.py → "tests"
        /Users/.../hooks/session_start.sh → "hooks"
    """
    if not path:
        return ""

    # Normalize path
    path = path.replace("\\", "/")

    # Directories that are themselves areas (not containers)
    direct_areas = ["/tests/", "/hooks/", "/scripts/"]
    for marker in direct_areas:
        if marker in path:
            return marker.strip("/")

    # Container directories - look for subdirectory as area
    containers = ["/src/", "/lib/", "/app/", "/packages/"]
    for marker in containers:
        if marker in path:
            after_marker = path.split(marker)[1]
            parts = after_marker.split("/")
            if parts:
                area = parts[0]
                # If it's a file directly in src/, use the filename stem
                if "." in area:
                    return Path(area).stem
                return area

    # Fallback: use parent directory name
    parent = Path(path).parent.name
    if parent and parent not in [".", ".."]:
        return parent

    return ""


def _path_matches_area(path: str, area: str) -> bool:
    """Check if a path belongs to an area."""
    if not path or not area:
        return False
    path_lower = path.lower().replace("\\", "/")
    area_lower = area.lower()
    # Match /area/ or /area. patterns
    return f"/{area_lower}/" in path_lower or f"/{area_lower}." in path_lower


def _load_area_warnings():
    """Load area-specific warnings from config."""
    warnings_file = Path(__file__).parent.parent.parent / "data" / "area_warnings.json"
    if warnings_file.exists():
        try:
            with open(warnings_file, 'r', encoding='utf-8') as f:
                return json.load(f).get("warnings", [])
        except Exception:
            pass
    return []


def _get_warnings_for_file(path: str, area: str) -> list:
    """Get applicable warnings for a file path."""
    warnings = _load_area_warnings()
    applicable = []
    filename = Path(path).stem.lower()

    for w in warnings:
        if w.get("area", "").lower() != area.lower():
            continue
        pattern = w.get("file_pattern", "").lower()
        if pattern and pattern in filename:
            applicable.append(w)

    return applicable


def _format_blocking_warning(warning: dict, file_path: str) -> str:
    """Format a blocking warning as operational STOP_AND_CONFIRM."""
    blocked = warning.get("blocked_actions", [])
    allowed = warning.get("allowed_actions", [])
    reason = warning.get("warning", "")

    blocked_lines = "\n".join(f"  • {action}" for action in blocked)
    allowed_lines = "\n".join(f"  • {action}" for action in allowed)

    return f"""🚨 FIXONCE_BLOCKING_WARNING
severity: blocking
action: stop_and_confirm

scope: {file_path}

reason:
{reason}

blocked_until_confirmation:
{blocked_lines}

allowed_without_confirmation:
{allowed_lines}

Required user choice:
1. Targeted fix only
2. Read-only review
3. Proceed with confirmation
4. Stop"""


def _is_noise_command(command: str) -> bool:
    """Check if a command is low-value noise."""
    if not command:
        return False
    cmd_lower = command.lower().strip()
    noise_prefixes = (
        "curl ", "grep ", "ls ", "cat ", "head ", "tail ",
        "find ", "wc ", "echo ", "pwd", "cd ", "which ",
    )
    return cmd_lower.startswith(noise_prefixes)


@activity_bp.route("/area-context", methods=["GET"])
def get_area_context():
    """
    Get relevant activity history for a file/area.

    This is the core of the "code remembers" feature.
    When an agent touches a file, we return recent history for that area.

    Query params:
        path: file path being accessed
        limit: max events to return (default 10, max 30)

    Returns:
        Recent activities in the same area, formatted for context injection.
        Warnings appear first, then filtered high-value events.
    """
    try:
        path = request.args.get("path", "")
        limit = min(request.args.get("limit", 10, type=int), 30)

        if not path:
            return jsonify(None)

        # Extract area from path
        area = _extract_area(path)
        if not area:
            return jsonify(None)

        # Get warnings for this file (high-signal, always shown first)
        file_warnings = _get_warnings_for_file(path, area)

        # Load activities
        log = _load_activity()
        all_activities = log.get("activities", [])

        # Filter activities that match this area AND are high-value
        area_activities = []
        for act in all_activities:
            act_file = act.get("file", "")
            act_command = act.get("command", "")
            act_cwd = act.get("cwd", "")
            act_type = act.get("type", "")

            # Skip noise commands
            if act_type == "command" and _is_noise_command(act_command):
                continue

            # Check if activity touches this area
            matches = False
            if act_file and _path_matches_area(act_file, area):
                matches = True
            elif act_command and area.lower() in act_command.lower():
                matches = True
            elif act_cwd and _path_matches_area(act_cwd, area):
                matches = f"/{area}/" in act_cwd.lower() or act_cwd.lower().endswith(f"/{area}")

            if matches:
                area_activities.append(act)

        # Build context: warnings first, then recent activity
        context_lines = []

        # Add warnings at top (high-signal)
        for w in file_warnings:
            if w.get("severity") == "blocking":
                context_lines.append(_format_blocking_warning(w, path))
            else:
                context_lines.append(f"⚠️ {w['warning']}")

        # Add separator if we have both warnings and activities
        if file_warnings and area_activities:
            context_lines.append("")

        # Add recent activity (if any non-noise events)
        if area_activities:
            recent = area_activities[:limit]
            context_lines.append(f"📁 Area: {area} — Recent:")
            for act in recent:
                ts = act.get("timestamp", "")[:10]
                act_type = act.get("type", "")

                if act_type == "file_change":
                    tool = act.get("tool", "Edit")
                    file_name = Path(act.get("file", "")).name
                    context_lines.append(f"  • [{ts}] {tool}: {file_name}")
                elif act_type == "command":
                    cmd = act.get("command", "")[:60]
                    context_lines.append(f"  • [{ts}] $ {cmd}")
                elif act_type == "mcp_tool":
                    tool = act.get("tool", "")
                    context_lines.append(f"  • [{ts}] {tool}")

        # Return null if no warnings and no activities
        if not context_lines:
            return jsonify(None)

        context_text = "\n".join(context_lines)

        return jsonify({
            "area": area,
            "count": len(area_activities[:limit]) if area_activities else 0,
            "warnings_count": len(file_warnings),
            "context": context_text,
            "activities": area_activities[:limit] if area_activities else []
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
