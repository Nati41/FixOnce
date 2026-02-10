"""
MCP Server for FixOnce - V2 (Simplified)

Project ID = Working Directory. That's it.
"""

import sys
import os
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Add src directory to path
SRC_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SRC_DIR))

from fastmcp import FastMCP

# Data directory
DATA_DIR = SRC_DIR.parent / "data" / "projects_v2"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Current session
_current_session = {
    "project_id": None,
    "working_dir": None
}

mcp = FastMCP("fixonce")


def _get_working_dir_from_port(port: int) -> Optional[str]:
    """Detect working directory from a running port using lsof."""
    try:
        # Get PID of process on port
        result = subprocess.run(
            ['lsof', '-i', f':{port}', '-t'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        pid = result.stdout.strip().split('\n')[0]

        # Get cwd of that process
        result = subprocess.run(
            ['lsof', '-p', pid],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None

        # Find cwd line
        for line in result.stdout.split('\n'):
            if ' cwd ' in line:
                # Extract path (last column)
                parts = line.split()
                if len(parts) >= 9:
                    path = parts[-1]
                    # Go up if we're in src/ or similar
                    if Path(path).name in ('src', 'dist', 'build', 'bin'):
                        path = str(Path(path).parent)
                    return path
        return None
    except Exception as e:
        return None


def _get_project_id(working_dir: str) -> str:
    """Convert working_dir to a safe project ID."""
    # Use hash of path for safe filename
    path_hash = hashlib.md5(working_dir.encode()).hexdigest()[:12]
    # Also keep readable name
    name = Path(working_dir).name
    return f"{name}_{path_hash}"


def _get_project_path(project_id: str) -> Path:
    """Get path to project memory file."""
    return DATA_DIR / f"{project_id}.json"


def _load_project(project_id: str) -> Dict[str, Any]:
    """Load project memory."""
    path = _get_project_path(project_id)
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _get_active_port() -> Optional[int]:
    """Get active port from dashboard's active_project.json."""
    try:
        active_file = SRC_DIR.parent / "data" / "active_project.json"
        if active_file.exists():
            with open(active_file, 'r') as f:
                data = json.load(f)
                active_id = data.get('active_id', '') or data.get('display_name', '')
                for sep in ['-', ':']:
                    if sep in active_id:
                        try:
                            return int(active_id.split(sep)[-1])
                        except ValueError:
                            pass
        return None
    except:
        return None


def _sync_to_dashboard(data: Dict[str, Any]):
    """Sync live_record to dashboard's project memory."""
    try:
        port = _get_active_port()
        if not port:
            return

        # Dashboard path: data/projects/localhost-{port}/memory.json
        dashboard_dir = SRC_DIR.parent / "data" / "projects" / f"localhost-{port}"
        dashboard_path = dashboard_dir / "memory.json"

        if not dashboard_path.exists():
            return  # Don't create, just update existing

        # Load dashboard memory
        with open(dashboard_path, 'r', encoding='utf-8') as f:
            dashboard_mem = json.load(f)

        # Merge live_record
        if 'live_record' not in dashboard_mem:
            dashboard_mem['live_record'] = {}

        v2_live = data.get('live_record', {})
        for section in ['gps', 'architecture', 'intent', 'lessons']:
            if section in v2_live:
                if section not in dashboard_mem['live_record']:
                    dashboard_mem['live_record'][section] = {}
                for key, value in v2_live[section].items():
                    if value:  # Only sync non-empty
                        dashboard_mem['live_record'][section][key] = value

        # Save back
        with open(dashboard_path, 'w', encoding='utf-8') as f:
            json.dump(dashboard_mem, f, ensure_ascii=False, indent=2)

    except Exception as e:
        pass  # Silently fail - dashboard sync is optional


def _save_project(project_id: str, data: Dict[str, Any]):
    """Save project memory to v2 AND dashboard location."""
    # Save to v2
    path = _get_project_path(project_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Also save to dashboard location (data/projects/localhost-{port}/memory.json)
    _sync_to_dashboard(data)


def _init_project_memory(working_dir: str) -> Dict[str, Any]:
    """Create empty project memory."""
    return {
        "project_info": {
            "working_dir": working_dir,
            "name": Path(working_dir).name,
            "created_at": datetime.now().isoformat()
        },
        "live_record": {
            "gps": {
                "working_dir": working_dir,
                "active_ports": [],
                "url": "",
                "environment": "dev"
            },
            "architecture": {
                "summary": "",
                "key_flows": []
            },
            "intent": {
                "current_goal": "",
                "next_step": "",
                "blockers": []
            },
            "lessons": {
                "insights": [],
                "failed_attempts": []
            }
        },
        "decisions": [],
        "avoid": [],
        "errors": []
    }


def _is_meaningful_project(data: Dict[str, Any]) -> bool:
    """Check if project has meaningful data."""
    lr = data.get('live_record', {})

    # Has architecture info?
    arch = lr.get('architecture', {})
    if arch.get('summary', '').strip() or arch.get('description', '').strip() or arch.get('stack', '').strip():
        return True

    # Has lessons?
    if lr.get('lessons', {}).get('insights', []):
        return True

    # Has decisions?
    if data.get('decisions', []):
        return True

    return False


def _get_recent_activity_summary(working_dir: str, limit: int = 5) -> str:
    """Get recent activity summary for init_session response."""
    activity_file = SRC_DIR.parent / "data" / "activity_log.json"

    if not activity_file.exists():
        return ""

    try:
        with open(activity_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        activities = data.get('activities', [])
        if not activities:
            return ""

        # Filter to current project
        project_activities = []
        for act in activities:
            file_path = act.get('file', '')
            cwd = act.get('cwd', '')
            if working_dir and (file_path.startswith(working_dir) or cwd.startswith(working_dir)):
                project_activities.append(act)

        if not project_activities:
            return ""

        # Take last N
        recent = project_activities[:limit]

        lines = ["**📋 Recent Activity:**"]
        for act in recent:
            human_name = act.get('human_name', '')
            file_path = act.get('file', '')
            file_name = file_path.split('/')[-1] if file_path else ''

            if human_name and file_name:
                lines.append(f"  • {human_name} ({file_name})")
            elif file_name:
                lines.append(f"  • {file_name}")
            elif act.get('command'):
                lines.append(f"  • `{act['command'][:30]}`")

        return '\n'.join(lines)

    except Exception:
        return ""


# ============================================================
# MCP TOOLS
# ============================================================

def _get_active_port_from_dashboard() -> Optional[int]:
    """Read active project port from dashboard."""
    try:
        active_file = DATA_DIR.parent.parent / "data" / "active_project.json"
        if not active_file.exists():
            # Try alternate location
            active_file = SRC_DIR.parent / "data" / "active_project.json"

        if active_file.exists():
            with open(active_file, 'r') as f:
                data = json.load(f)
                # Extract port from "localhost-5000" or "localhost:5000"
                active_id = data.get('active_id', '') or data.get('display_name', '')
                for sep in ['-', ':']:
                    if sep in active_id:
                        try:
                            return int(active_id.split(sep)[-1])
                        except ValueError:
                            pass
        return None
    except Exception:
        return None


@mcp.tool()
def auto_init_session() -> str:
    """
    Automatically initialize session based on dashboard's active project.

    Call this FIRST at session start - it reads which project is active
    from the FixOnce dashboard and initializes automatically.

    Returns:
        Session info with project details
    """
    # Try to get port from dashboard
    port = _get_active_port_from_dashboard()
    if port:
        working_dir = _get_working_dir_from_port(port)
        if working_dir:
            return _do_init_session(working_dir)
        else:
            return f"Dashboard shows port {port} but no server found. Is it running?"

    return "No active project in dashboard. Use init_session(port=X) or init_session(working_dir=path)"


def _do_init_session(working_dir: str) -> str:
    """Internal init session logic."""
    global _current_session

    if not working_dir or not os.path.isdir(working_dir):
        return f"Error: Invalid working directory: {working_dir}"

    project_id = _get_project_id(working_dir)
    _current_session["project_id"] = project_id
    _current_session["working_dir"] = working_dir

    # Load or create project
    data = _load_project(project_id)
    if not data:
        data = _init_project_memory(working_dir)
        _save_project(project_id, data)

    # Determine status
    status = "existing" if _is_meaningful_project(data) else "new"

    # Build response
    project_name = data.get('project_info', {}).get('name', Path(working_dir).name)

    lines = [
        f"## Project: {project_name}",
        f"**Status:** {status.upper()}",
        f"**Path:** `{working_dir}`",
        ""
    ]

    if status == "new":
        lines.append("_This is a new project. Ask: 'רוצה שאסרוק את הפרויקט?'_")
    else:
        # Show existing context
        lr = data.get('live_record', {})

        intent = lr.get('intent', {})
        if intent.get('current_goal'):
            lines.append(f"**Last Goal:** {intent['current_goal']}")

        arch = lr.get('architecture', {})
        if arch.get('summary'):
            lines.append(f"**Architecture:** {arch['summary']}")

        lessons = lr.get('lessons', {}).get('insights', [])
        if lessons:
            lines.append(f"**Last Insight:** {lessons[-1]}")

        avoid = data.get('avoid', [])
        if avoid:
            lines.append(f"**Avoid:** {avoid[-1].get('what', '')}")

        lines.append("")
        lines.append("_Ask: 'נמשיך מכאן?'_")

    # Add recent activity
    activity_info = _get_recent_activity_summary(working_dir, limit=5)
    if activity_info:
        lines.append("")
        lines.append(activity_info)

    return '\n'.join(lines)


@mcp.tool()
def init_session(working_dir: str = "", port: int = 0) -> str:
    """
    Initialize FixOnce session for the current project.

    Args:
        working_dir: The absolute path to the project directory (use cwd)
        port: OR a port number - will auto-detect the working directory from it

    Returns:
        Session info with project_status ('new' or 'existing')
    """
    # If port given, detect working_dir from it
    if port and not working_dir:
        detected = _get_working_dir_from_port(port)
        if detected:
            working_dir = detected
        else:
            return f"Error: Could not detect project directory from port {port}. Is a server running?"

    return _do_init_session(working_dir)


@mcp.tool()
def detect_project_from_port(port: int) -> str:
    """
    Detect which project directory is running on a given port.

    Args:
        port: The port number to check (e.g., 5000, 3000)

    Returns:
        The detected project path, or error message
    """
    detected = _get_working_dir_from_port(port)
    if detected:
        return f"Port {port} → `{detected}`"
    else:
        return f"No process found on port {port}"


@mcp.tool()
def scan_project() -> str:
    """
    Scan the current project directory.
    Use this for NEW projects after user approves.

    Returns:
        Scan results (technologies, structure, etc.)
    """
    if not _current_session.get("working_dir"):
        return "Error: No active session. Call init_session() first."

    working_dir = _current_session["working_dir"]

    lines = [f"# Scanning: {Path(working_dir).name}", ""]

    # Detect technologies
    tech_files = {
        'package.json': 'Node.js/JavaScript',
        'requirements.txt': 'Python',
        'pyproject.toml': 'Python',
        'Cargo.toml': 'Rust',
        'go.mod': 'Go',
        'pom.xml': 'Java',
        'Gemfile': 'Ruby',
        'tsconfig.json': 'TypeScript',
        'docker-compose.yml': 'Docker',
        'Dockerfile': 'Docker'
    }

    found_tech = []
    for file, tech in tech_files.items():
        if os.path.exists(os.path.join(working_dir, file)):
            found_tech.append(tech)

    if found_tech:
        lines.append(f"**Stack:** {', '.join(set(found_tech))}")
        lines.append("")

    # List directories
    lines.append("**Structure:**")
    try:
        dirs = sorted([d for d in os.listdir(working_dir)
                      if os.path.isdir(os.path.join(working_dir, d))
                      and not d.startswith('.')])[:10]
        for d in dirs:
            lines.append(f"- 📁 {d}/")
    except Exception as e:
        lines.append(f"_Error reading directory: {e}_")

    lines.append("")

    # Check for README
    for readme in ['README.md', 'README.txt', 'README']:
        readme_path = os.path.join(working_dir, readme)
        if os.path.exists(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read(500)
                lines.append(f"**README preview:**")
                lines.append(f"```\n{content}\n```")
            except:
                pass
            break

    lines.append("")
    lines.append("---")
    lines.append("Now call `update_live_record()` to save this info.")

    return '\n'.join(lines)


@mcp.tool()
def update_live_record(section: str, data: str) -> str:
    """
    Update a section of the Live Record.

    Args:
        section: One of 'gps', 'architecture', 'intent', 'lessons'
        data: JSON string with the data to update

    For 'lessons', use: {"insight": "..."} or {"failed_attempt": "..."}
    These APPEND to the list.

    For 'architecture', use: {"summary": "...", "stack": "...", "key_flows": [...]}
    - summary: Short description of what this project is
    - stack: Technologies used (e.g., "React, Node.js, MongoDB")
    - key_flows: Main user flows or features

    For other sections, data REPLACES the section.
    """
    if not _current_session.get("project_id"):
        return "Error: No active session. Call init_session() first."

    try:
        update_data = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError:
        return f"Error: Invalid JSON: {data}"

    project_id = _current_session["project_id"]
    memory = _load_project(project_id)

    if 'live_record' not in memory:
        memory['live_record'] = {}

    lr = memory['live_record']

    if section == 'lessons':
        # APPEND mode
        if 'lessons' not in lr:
            lr['lessons'] = {'insights': [], 'failed_attempts': []}

        if 'insight' in update_data:
            lr['lessons']['insights'].append(update_data['insight'])
        if 'failed_attempt' in update_data:
            lr['lessons']['failed_attempts'].append(update_data['failed_attempt'])
    else:
        # REPLACE mode
        if section not in lr:
            lr[section] = {}
        lr[section].update(update_data)

    lr['updated_at'] = datetime.now().isoformat()
    _save_project(project_id, memory)

    return f"Updated {section}"


@mcp.tool()
def get_live_record() -> str:
    """Get the current Live Record."""
    if not _current_session.get("project_id"):
        return "Error: No active session. Call init_session() first."

    memory = _load_project(_current_session["project_id"])
    lr = memory.get('live_record', {})

    return json.dumps(lr, indent=2, ensure_ascii=False)


@mcp.tool()
def log_decision(decision: str, reason: str) -> str:
    """Log an architectural decision."""
    if not _current_session.get("project_id"):
        return "Error: No active session."

    memory = _load_project(_current_session["project_id"])

    if 'decisions' not in memory:
        memory['decisions'] = []

    memory['decisions'].append({
        "decision": decision,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })

    _save_project(_current_session["project_id"], memory)
    return f"Logged decision: {decision}"


@mcp.tool()
def log_avoid(what: str, reason: str) -> str:
    """Log something to avoid."""
    if not _current_session.get("project_id"):
        return "Error: No active session."

    memory = _load_project(_current_session["project_id"])

    if 'avoid' not in memory:
        memory['avoid'] = []

    memory['avoid'].append({
        "what": what,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })

    _save_project(_current_session["project_id"], memory)
    return f"Logged avoid: {what}"


@mcp.tool()
def search_past_solutions(query: str) -> str:
    """Search for past solutions matching the query."""
    if not _current_session.get("project_id"):
        return "Error: No active session."

    memory = _load_project(_current_session["project_id"])

    # Search in lessons
    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    failed = lessons.get('failed_attempts', [])

    query_lower = query.lower()

    matches = []
    for insight in insights:
        if query_lower in insight.lower():
            matches.append(f"💡 Insight: {insight}")

    for attempt in failed:
        if query_lower in attempt.lower():
            matches.append(f"❌ Failed: {attempt}")

    if matches:
        return "## Found:\n" + '\n'.join(matches)
    else:
        return "No matching solutions found."


@mcp.tool()
def get_recent_activity(limit: int = 10) -> str:
    """
    Get recent Claude activity from the dashboard.

    Shows what files were edited, commands run, etc.
    Useful for understanding recent context and what changed.

    Args:
        limit: Max number of activities to return (default 10)

    Returns:
        Recent activity list with timestamps and human-readable names
    """
    activity_file = SRC_DIR.parent / "data" / "activity_log.json"

    if not activity_file.exists():
        return "No activity log found."

    try:
        with open(activity_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        all_activities = data.get('activities', [])

        if not all_activities:
            return "No recent activity."

        # Filter to current project only
        working_dir = _current_session.get("working_dir", "")

        if working_dir:
            # Only show activities from current project
            project_activities = []
            for act in all_activities:
                file_path = act.get('file', '')
                cwd = act.get('cwd', '')
                if file_path.startswith(working_dir) or cwd.startswith(working_dir):
                    project_activities.append(act)
            activities = project_activities[:limit]
        else:
            activities = all_activities[:limit]

        if not activities:
            return "No recent activity for this project."

        lines = ["## Recent Activity\n"]

        for act in activities:
            file_path = act.get('file', '')
            human_name = act.get('human_name', '')
            tool = act.get('tool', '')
            timestamp = act.get('timestamp', '')[:16].replace('T', ' ')

            # Format the activity
            if file_path:
                file_name = file_path.split('/')[-1]
                display = human_name if human_name else file_name
                lines.append(f"• **{display}** ({file_name}) - {tool} - {timestamp}")
            elif act.get('command'):
                cmd = act.get('command', '')[:40]
                lines.append(f"• `{cmd}` - {timestamp}")

        return '\n'.join(lines)

    except Exception as e:
        return f"Error reading activity: {e}"


if __name__ == "__main__":
    mcp.run()
