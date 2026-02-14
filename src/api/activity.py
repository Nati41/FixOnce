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

activity_bp = Blueprint('activity', __name__)


# File type to Hebrew context mapping
FILE_TYPE_CONTEXT = {
    # Styles
    ".css": "עיצוב",
    ".scss": "עיצוב",
    ".sass": "עיצוב",
    ".less": "עיצוב",
    ".styled.js": "עיצוב",
    ".styled.ts": "עיצוב",

    # Scripts/Logic
    ".js": "לוגיקה",
    ".ts": "לוגיקה",
    ".jsx": "רכיב",
    ".tsx": "רכיב",
    ".vue": "רכיב",
    ".svelte": "רכיב",

    # Python
    ".py": "קוד",

    # Config
    ".json": "הגדרות",
    ".yaml": "הגדרות",
    ".yml": "הגדרות",
    ".toml": "הגדרות",
    ".ini": "הגדרות",
    ".env": "משתני סביבה",

    # Data/Content
    ".html": "תצוגה",
    ".md": "תיעוד",
    ".txt": "טקסט",

    # Tests
    ".test.js": "בדיקות",
    ".test.ts": "בדיקות",
    ".spec.js": "בדיקות",
    ".spec.ts": "בדיקות",
    "_test.py": "בדיקות",
    "test_.py": "בדיקות",
}


def _get_file_type_context(file_path: str) -> str:
    """Get Hebrew context word based on file type."""
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

        # Skip empty/invalid activities
        if not data.get("file") and not data.get("command") and not data.get("cwd"):
            return jsonify({"status": "skipped", "reason": "no meaningful data"})

        file_path = data.get("file")
        cwd = data.get("cwd")
        boundary_transition = None

        # Phase 1: Check for boundary violation (file outside active project)
        if BOUNDARY_DETECTION_ENABLED and file_path and data.get("tool") in ["Edit", "Write", "NotebookEdit"]:
            boundary_event = detect_boundary_violation(file_path)
            if boundary_event:
                # High or medium confidence - execute switch
                new_project_id = handle_boundary_transition(boundary_event)
                project_id = new_project_id
                boundary_transition = boundary_event.to_dict()
            else:
                # No violation or low confidence - use cwd as before
                project_id = _get_project_id_from_cwd(cwd)
        else:
            # Fallback: Generate project_id from cwd (Phase 0: prevent cross-project leakage)
            project_id = _get_project_id_from_cwd(cwd)

        # Get enriched data
        file_context = _get_file_type_context(file_path) if file_path else ""
        diff_stats = _get_git_diff_stats(file_path, cwd) if file_path and data.get("tool") in ["Edit", "Write"] else {}

        activity = {
            "id": f"act_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
            "type": data.get("type", "unknown"),
            "tool": data.get("tool"),
            "file": file_path,
            "command": data.get("command"),
            "cwd": cwd,
            "project_id": project_id,  # Phase 0: Tag with project
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

        print(f"[Activity] {activity['type']}: {activity.get('file') or activity.get('command', '')[:50]}")

        return jsonify({"status": "ok", "activity": activity})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@activity_bp.route("/session", methods=["POST"])
def log_session():
    """
    Log session start/end.

    Body:
        event: "start" | "end"
        session_id: session identifier
        cwd: working directory
        source: how session started (startup, resume, etc.)
        timestamp: ISO timestamp
    """
    try:
        data = request.get_json(silent=True) or {}

        event = data.get("event", "unknown")
        session_id = data.get("session_id", "unknown")

        log = _load_activity()

        if "sessions" not in log:
            log["sessions"] = {}

        if event == "start":
            log["sessions"][session_id] = {
                "started_at": data.get("timestamp") or datetime.now().isoformat(),
                "cwd": data.get("cwd"),
                "source": data.get("source"),
                "status": "active"
            }
            print(f"[Session] Started: {session_id[:12]}...")

        elif event == "end":
            if session_id in log["sessions"]:
                log["sessions"][session_id]["ended_at"] = data.get("timestamp") or datetime.now().isoformat()
                log["sessions"][session_id]["status"] = "ended"
            print(f"[Session] Ended: {session_id[:12]}...")

        _save_activity(log)

        return jsonify({"status": "ok", "event": event})

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


@activity_bp.route("/<activity_id>", methods=["DELETE"])
def delete_activity(activity_id):
    """Delete a single activity by ID."""
    try:
        log = _load_activity()
        original_count = len(log.get("activities", []))
        log["activities"] = [a for a in log.get("activities", []) if a.get("id") != activity_id]

        if len(log["activities"]) < original_count:
            _save_activity(log)
            return jsonify({"status": "ok", "deleted": activity_id})
        else:
            return jsonify({"status": "not_found"}), 404

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@activity_bp.route("/clear", methods=["DELETE"])
def clear_activities():
    """Clear all activities."""
    try:
        log = _load_activity()
        count = len(log.get("activities", []))
        log["activities"] = []
        _save_activity(log)

        return jsonify({"status": "ok", "cleared": count})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@activity_bp.route("/open-file", methods=["POST"])
def open_file_in_editor():
    """Open a file in the default editor (VS Code/Cursor)."""
    import subprocess
    import shutil
    try:
        data = request.get_json(silent=True) or {}
        file_path = data.get("file", "")

        if not file_path:
            return jsonify({"status": "error", "message": "No file path"}), 400

        # Try different editors in order of preference
        if shutil.which("cursor"):
            subprocess.Popen(["cursor", file_path])
        elif shutil.which("code"):
            subprocess.Popen(["code", file_path])
        else:
            # Fallback to Mac open command
            subprocess.Popen(["open", file_path])

        return jsonify({"status": "ok", "opened": file_path})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _get_human_name(data):
    """
    Convert file path to human-readable component name.
    Uses the components module for comprehensive mapping.
    """
    file_path = data.get("file", "")

    if not file_path:
        return data.get("command", "")[:30] if data.get("command") else ""

    try:
        from .components import get_component_name
        return get_component_name(file_path)
    except:
        # Fallback to file name
        return Path(file_path).stem
