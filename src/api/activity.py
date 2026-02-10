"""
FixOnce Activity API
Receives activity logs from Claude Code hooks.
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
import json
from pathlib import Path

activity_bp = Blueprint('activity', __name__)

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

        activity = {
            "id": f"act_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
            "type": data.get("type", "unknown"),
            "tool": data.get("tool"),
            "file": data.get("file"),
            "command": data.get("command"),
            "cwd": data.get("cwd"),
            "timestamp": data.get("timestamp") or datetime.now().isoformat(),
            "human_name": _get_human_name(data)
        }

        log = _load_activity()
        log["activities"].insert(0, activity)  # Most recent first

        # Keep only last 100 activities
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
