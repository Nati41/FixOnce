"""
MCP Server for FixOnce - V2 (Simplified)

Project ID = Working Directory. That's it.

Phase 0: Thread-safe sessions, no global state leakage.
Phase 1: Boundary detection as single source of truth for project identity.
"""

import sys
import os
import json
import hashlib
import subprocess
import threading
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional


def _log(*args, **kwargs):
    """MCP-safe logging: never write to stdout on stdio transport."""
    kwargs.pop("file", None)
    print(*args, file=sys.stderr, flush=True, **kwargs)


def _debug_log(message: str):
    """
    Write debug message to user-specific log file.
    Uses ~/.fixonce/mcp_debug.log to avoid permission issues with /tmp.
    Silently fails if can't write - debug logs are non-critical.
    """
    try:
        log_dir = Path.home() / ".fixonce"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "mcp_debug.log"
        with open(log_file, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass  # Silent fail - debug logs are non-critical


# Safe File Operations (auto-backup, atomic writes)
_safe_file_available = False
try:
    from core.safe_file import atomic_json_write, atomic_json_read
    _safe_file_available = True
except ImportError:
    pass  # Safe file not available, will use regular json

# Semantic Search Integration
_semantic_available = False
try:
    from core.project_semantic import (
        index_insight, index_decision, index_avoid,
        search_project, rebuild_project_index
    )
    _semantic_available = True
except ImportError:
    pass  # Semantic search not available, will use fallback

# Session Registry for Multi-AI Isolation - imported later after sys.path is set
_session_registry_available = False

# Policy Enforcement Engine - imported later after sys.path is set
_policy_available = False
_policy_error = None

# ============================================================
# SESSION INITIALIZATION ENFORCEMENT
# ============================================================
# Track if auto_init_session was called this session.
# If not, other tools will return a reminder.
# This works for ALL AI clients (Claude, Cursor, Codex, etc.)

_session_initialized = False
_session_init_lock = threading.Lock()


def _mark_session_initialized():
    """Mark that auto_init_session was called."""
    global _session_initialized
    with _session_init_lock:
        _session_initialized = True


def _is_session_initialized() -> bool:
    """Check if session was initialized."""
    with _session_init_lock:
        return _session_initialized


def _get_init_reminder() -> str:
    """Get reminder message if session not initialized."""
    if _is_session_initialized():
        return ""
    return """
⚠️ **FixOnce Not Connected!**

You MUST call `auto_init_session(cwd="/path/to/project")` FIRST before using other tools.

This connects FixOnce to your project and loads context, decisions, and insights.
Without this, you're working without memory.

"""


def _detect_editor_with_confidence() -> tuple:
    """
    Detect which editor/AI is running this MCP server.
    Returns: (editor_name, detection_source, confidence)
    - confidence: 1.0 = certain, 0.7 = high, 0.5 = medium, 0.3 = low, 0.0 = unknown
    """
    # Priority 0: Check for Codex CLI (OpenAI) - HIGH confidence
    if any(key.startswith("CODEX_") for key in os.environ):
        return ("codex", "env_var", 1.0)

    codex_home = os.environ.get("CODEX_HOME", "")
    if codex_home:
        return ("codex", "env_var", 1.0)

    # Check parent process for codex/fastmcp
    try:
        ppid = os.getppid()
        result = subprocess.run(['ps', '-p', str(ppid), '-o', 'command='],
                              capture_output=True, text=True, timeout=1)
        parent_cmd = result.stdout.strip().lower()
        if 'codex' in parent_cmd:
            return ("codex", "parent_process", 0.9)
        if 'fastmcp' in parent_cmd:
            return ("codex", "parent_process", 0.7)
    except:
        pass

    # Priority 1: Check Cursor env vars - HIGH confidence
    cursor_channel = os.environ.get("CURSOR_CHANNEL", "")
    if cursor_channel:
        return ("cursor", "env_var", 1.0)

    for key in os.environ:
        if key.startswith("CURSOR_"):
            return ("cursor", "env_var", 0.9)

    term_program = os.environ.get("TERM_PROGRAM", "")
    if "cursor" in term_program.lower():
        return ("cursor", "term_program", 0.8)

    # Priority 2: Check VS Code
    vscode_pid = os.environ.get("VSCODE_PID", "")
    if vscode_pid:
        try:
            result = subprocess.run(['ps', '-p', vscode_pid, '-o', 'comm='],
                                  capture_output=True, text=True, timeout=1)
            proc_name = result.stdout.strip().lower()
            if 'cursor' in proc_name:
                return ("cursor", "vscode_pid_check", 0.8)
        except:
            pass
        return ("vscode", "env_var", 0.9)

    # Priority 3: Check parent process for Claude Code - HIGH confidence
    try:
        ppid = os.getppid()
        result = subprocess.run(['ps', '-p', str(ppid), '-o', 'command='],
                              capture_output=True, text=True, timeout=1)
        parent_cmd = result.stdout.strip().lower()
        if 'claude' in parent_cmd:
            return ("claude", "parent_process", 0.9)
    except:
        pass

    # Priority 4: Check config files - MEDIUM confidence (heuristic)
    home = Path.home()
    claude_settings = home / ".claude" / "settings.json"
    cursor_config = home / ".cursor" / "mcp.json"

    if claude_settings.exists():
        try:
            settings_mtime = claude_settings.stat().st_mtime
            import time
            if time.time() - settings_mtime < 3600:
                return ("claude", "config_file", 0.5)
        except:
            pass

    if cursor_config.exists():
        return ("cursor", "config_file", 0.3)

    return ("unknown", "none", 0.0)


def _detect_editor() -> str:
    """Detect which editor/AI is running this MCP server. Returns name only."""
    editor, _, _ = _detect_editor_with_confidence()
    return editor


def _resolve_actor_identity() -> Dict[str, Any]:
    """
    Resolve actor identity for this MCP call with provenance metadata.

    Priority:
    1. Explicit client-provided actor env vars (confidence: 1.0)
    2. Runtime environment detection (confidence from detector)
    """
    allowed = {"codex", "claude", "cursor", "vscode"}

    # Priority 1: Explicit client-provided actor
    explicit_actor = (
        os.environ.get("FIXONCE_ACTOR", "")
        or os.environ.get("MCP_CLIENT_ACTOR", "")
        or os.environ.get("FIXONCE_EDITOR", "")
    ).strip().lower()

    if explicit_actor in allowed:
        return {
            "editor": explicit_actor,
            "source": "client_actor",
            "confidence": 1.0,
        }

    # Priority 2: Runtime detection with actual confidence
    editor, source, confidence = _detect_editor_with_confidence()
    if editor in allowed:
        return {
            "editor": editor,
            "source": source,
            "confidence": confidence,
        }

    return {
        "editor": "unknown",
        "source": "none",
        "confidence": 0.0,
    }

# Add src directory to path
SRC_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SRC_DIR))

from fastmcp import FastMCP
from core.system_mode import get_system_mode, MODE_FULL, MODE_PASSIVE, MODE_OFF

# Policy Enforcement Engine - must be after sys.path is set
try:
    from core.policy_engine import (
        detect_conflicts, validate_decision, check_blocked_components,
        supersede_decision as do_supersede, get_active_decisions, format_policy_status
    )
    _policy_available = True
    _log("[FixOnce] Policy engine loaded successfully")
except ImportError as e:
    _policy_error = str(e)
    _log(f"[FixOnce] Policy engine not available: {e}")

# Session Registry for Multi-AI Isolation - must be after sys.path is set
try:
    from core.session_registry import get_registry, get_or_create_session
    _session_registry_available = True
    _log("[FixOnce] Session registry loaded successfully")
except ImportError as e:
    _log(f"[FixOnce] Session registry not available: {e}")

# Resume State - persistent work state across sessions
_resume_state_available = False
try:
    from core.resume_state import (
        save_resume_state as _save_resume_state,
        get_resume_state as _get_resume_state,
        clear_resume_state as _clear_resume_state,
        format_resume_for_init
    )
    _resume_state_available = True
    _log("[FixOnce] Resume state loaded successfully")
except ImportError as e:
    _log(f"[FixOnce] Resume state not available: {e}")

# Resume Context - structured context builder for session opening
_resume_context_available = False
try:
    from core.resume_context import (
        build_resume_context,
        build_suggested_opening,
        build_new_project_opening
    )
    _resume_context_available = True
    _log("[FixOnce] Resume context loaded successfully")
except ImportError as e:
    _log(f"[FixOnce] Resume context not available: {e}")

# Phase 0: Project isolation - central project context
from core.project_context import ProjectContext, resolve_project_id

# Phase 1: Boundary detection imports
try:
    from core.boundary_detector import (
        find_project_root,
        detect_boundary_violation,
        handle_boundary_transition,
        is_within_boundary,
        BoundaryEvent
    )
    BOUNDARY_DETECTION_ENABLED = True
except ImportError as e:
    BOUNDARY_DETECTION_ENABLED = False
    _log(f"[MCP] Boundary detection not available: {e}")

# Data directory
DATA_DIR = SRC_DIR.parent / "data" / "projects_v2"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Project index file (for caching)
INDEX_FILE = SRC_DIR.parent / "data" / "project_index.json"

# Global on/off toggle (controlled by dashboard)
ENABLED_FLAG_FILE = SRC_DIR.parent / "data" / "fixonce_enabled.json"


def _is_fixonce_enabled() -> bool:
    """Legacy boolean compatibility: enabled unless mode is OFF."""
    try:
        return _get_fixonce_mode() != MODE_OFF
    except Exception:
        return True


def _get_fixonce_mode() -> str:
    """Get global FixOnce mode (full/passive/off)."""
    try:
        return (get_system_mode().get("mode") or MODE_FULL).lower()
    except Exception:
        return MODE_FULL


# ============================================================
# PHASE 0: Thread-Local Session (No Global State)
# ============================================================

_session_local = threading.local()


class SessionContext:
    """Thread-safe session context with protocol compliance tracking."""

    def __init__(self, project_id: str = None, working_dir: str = None):
        self.project_id = project_id
        self.working_dir = working_dir
        # Protocol compliance tracking
        self.initialized_at = None
        self.decisions_displayed = False
        self.goal_updated = False
        self.search_performed = False
        self.component_updated = False
        self.decision_logged = False
        self.tool_calls = []

    def __repr__(self):
        return f"SessionContext(project_id={self.project_id})"

    def is_active(self) -> bool:
        return self.project_id is not None

    def mark_initialized(self):
        self.initialized_at = datetime.now().isoformat()

    def mark_decisions_displayed(self):
        self.decisions_displayed = True

    def mark_goal_updated(self):
        self.goal_updated = True

    def mark_search_performed(self):
        self.search_performed = True

    def mark_component_updated(self):
        self.component_updated = True

    def mark_decision_logged(self):
        self.decision_logged = True

    def log_tool_call(self, tool_name: str):
        self.tool_calls.append({
            "tool": tool_name,
            "timestamp": datetime.now().isoformat()
        })
        # Prevent unbounded memory growth - keep last 100 calls
        if len(self.tool_calls) > 100:
            self.tool_calls = self.tool_calls[-100:]
        # Track specific tool calls for compliance
        if tool_name == "search_past_solutions":
            self.search_performed = True
        elif tool_name == "update_component_status":
            self.component_updated = True
        elif tool_name == "log_decision":
            self.decision_logged = True

    def get_compliance_status(self) -> dict:
        """Get protocol compliance status for dashboard."""
        return {
            "session_initialized": self.is_active(),
            "initialized_at": self.initialized_at,
            "decisions_displayed": self.decisions_displayed,
            "goal_updated": self.goal_updated,
            "search_performed": self.search_performed,
            "component_updated": self.component_updated,
            "decision_logged": self.decision_logged,
            "tool_calls_count": len(self.tool_calls),
            "last_tool": self.tool_calls[-1] if self.tool_calls else None
        }

    def get_compliance_score(self) -> dict:
        """Calculate compliance score with detailed breakdown."""
        rules = [
            {"id": "session_init", "name": "Session initialized", "passed": self.is_active(), "required": True},
            {"id": "goal_updated", "name": "Goal updated", "passed": self.goal_updated, "required": True},
            {"id": "search_first", "name": "Search before debug", "passed": self.search_performed, "required": False},
            {"id": "component_status", "name": "Component status updated", "passed": self.component_updated, "required": False},
        ]

        # Calculate score (required rules count double)
        total_weight = 0
        earned_weight = 0
        for rule in rules:
            weight = 2 if rule["required"] else 1
            total_weight += weight
            if rule["passed"]:
                earned_weight += weight

        score = int((earned_weight / total_weight) * 100) if total_weight > 0 else 0

        return {
            "score": score,
            "rules": rules,
            "passed": sum(1 for r in rules if r["passed"]),
            "total": len(rules),
            "tool_calls": len(self.tool_calls)
        }


# Protocol compliance state (shared across threads for dashboard)
_compliance_state = {
    "last_session_init": None,
    "violations": [],
    "editor": None,
    "session_active": False,
    "initialized_at": None,
    "project_id": None
}


# Session persistence file (survives MCP restarts)
SESSION_FILE = SRC_DIR.parent / "data" / "mcp_session.json"
COMPLIANCE_FILE = SRC_DIR.parent / "data" / "mcp_compliance.json"


def _persist_compliance():
    """Save compliance state to file for Flask API access."""
    try:
        with open(COMPLIANCE_FILE, 'w') as f:
            json.dump(_compliance_state, f)
    except Exception:
        pass


def _load_compliance() -> dict:
    """Load compliance state from file."""
    try:
        if COMPLIANCE_FILE.exists():
            with open(COMPLIANCE_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _persist_session(project_id: str, working_dir: str):
    """Save current session to file for recovery after restart."""
    try:
        data = {
            "project_id": project_id,
            "working_dir": working_dir,
            "timestamp": datetime.now().isoformat()
        }
        with open(SESSION_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def _recover_session() -> Optional[tuple]:
    """Try to recover session from file. Returns (project_id, working_dir) or None."""
    try:
        if not SESSION_FILE.exists():
            return None

        with open(SESSION_FILE, 'r') as f:
            data = json.load(f)

        # Check if session is recent (within last hour)
        timestamp = datetime.fromisoformat(data.get("timestamp", ""))
        age_hours = (datetime.now() - timestamp).total_seconds() / 3600

        if age_hours < 1 and data.get("project_id") and data.get("working_dir"):
            return (data["project_id"], data["working_dir"])

        return None
    except Exception:
        return None


# ============================================================
# PHASE 2: UNIVERSAL GATE (Inversion of Control)
# ============================================================
# FixOnce is in control. Claude executes.
# - Auto-session: No manual init required
# - Context injection: Every response includes context
# - Error gate: Live errors are always visible
# ============================================================

def _get_active_project_from_api() -> Optional[dict]:
    """Get active project info from Flask API."""
    try:
        res = requests.get('http://localhost:5000/api/projects/active', timeout=2)
        if res.status_code == 200:
            return res.json()
        return None
    except Exception:
        return None


def _auto_create_session() -> bool:
    """
    Automatically create session from active project or last session.
    Returns True if session was created.
    """
    # 1. Try to recover from persisted session
    recovered = _recover_session()
    if recovered:
        project_id, working_dir = recovered
        _set_session(project_id, working_dir)
        session = _get_session()
        session.mark_initialized()
        _log(f"[FixOnce] Auto-session from file: {project_id}")
        return True

    # 2. Try to get active project from API
    active = _get_active_project_from_api()
    if active and active.get('project_id'):
        project_id = active['project_id']
        # working_dir is nested in memory.project_info
        working_dir = active.get('memory', {}).get('project_info', {}).get('working_dir', '')
        _set_session(project_id, working_dir)
        session = _get_session()
        session.mark_initialized()
        _persist_session(project_id, working_dir)
        _log(f"[FixOnce] Auto-session from API: {project_id}")
        return True

    return False


def _get_live_errors() -> list:
    """Get unacknowledged browser errors."""
    try:
        res = requests.get('http://localhost:5000/api/live-errors?since=600', timeout=2)
        if res.status_code == 200:
            data = res.json()
            return data.get('errors', [])[:5]  # Max 5
        return []
    except Exception:
        return []


def _get_pending_commands_for_injection() -> list:
    """Get pending commands from dashboard (without marking as delivered)."""
    try:
        res = requests.get('http://localhost:5000/api/memory/ai-queue', timeout=2)
        if res.status_code == 200:
            data = res.json()
            return data.get('commands', [])[:3]  # Max 3
        return []
    except Exception:
        return []


def _get_new_rules() -> list:
    """Get custom rules that might be new."""
    try:
        res = requests.get('http://localhost:5000/api/memory/rules', timeout=2)
        if res.status_code == 200:
            data = res.json()
            # Return only custom (non-default) rules
            rules = data.get('rules', [])
            return [r for r in rules if not r.get('default', False) and r.get('enabled', True)]
        return []
    except Exception:
        return []


def _get_recent_activities_for_handoff(editor: str, limit: int = 3) -> list:
    """Get recent activities for handoff summary between AIs."""
    try:
        res = requests.get(f'http://localhost:5000/api/activity/feed?limit=20', timeout=2)
        if res.status_code != 200:
            return []

        data = res.json()
        activities = data.get('activities', [])

        # Filter to show what happened (not specific to editor since we track globally)
        summaries = []
        for a in activities[:limit * 2]:  # Get more to filter
            tool = a.get('tool', '')
            human_name = a.get('human_name', '')
            file_name = a.get('file', '').split('/')[-1] if a.get('file') else ''

            if tool == 'Edit' and file_name:
                diff = a.get('diff', {})
                added = diff.get('added', 0)
                if added > 0:
                    summaries.append(f"Edited {file_name} (+{added} lines)")
                else:
                    summaries.append(f"Edited {file_name}")
            elif tool == 'Write' and file_name:
                summaries.append(f"Created {file_name}")
            elif tool == 'Bash':
                cmd = a.get('command', '')[:30]
                if cmd:
                    summaries.append(f"Ran: {cmd}...")

            if len(summaries) >= limit:
                break

        return summaries
    except Exception:
        return []


def _build_context_header() -> str:
    """
    Build context header that gets injected into EVERY tool response.
    This is the core of "FixOnce in control".
    """
    lines = []
    session = _get_session()

    if not session.is_active():
        return ""

    # Load project data
    memory = _load_project(session.project_id)
    if not memory:
        return ""

    lr = memory.get('live_record', {})

    # 1. LIVE ERRORS (Always first - IMPOSSIBLE TO MISS)
    errors = _get_live_errors()
    if errors:
        lines.append("")
        lines.append("🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
        lines.append(f"⚠️ **{len(errors)} LIVE BROWSER ERRORS**")
        lines.append("🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
        for e in errors[:3]:
            msg = e.get('message', 'Unknown error')[:100]
            lines.append(f"  ❌ {msg}")
            # Show solution if available
            solution = e.get('solution')
            if solution:
                lines.append(f"     💡 FIX: {solution.get('text', '')[:80]}")
        if len(errors) > 3:
            lines.append(f"  ...and {len(errors) - 3} more")
        lines.append("")
        lines.append("**FIX THESE BEFORE DOING ANYTHING ELSE!**")
        lines.append("")

    # 1.5. PENDING COMMANDS (Dashboard → AI communication)
    pending_cmds = _get_pending_commands_for_injection()
    if pending_cmds:
        lines.append("")
        lines.append("📬 **PENDING COMMANDS FROM DASHBOARD:**")
        for cmd in pending_cmds:
            cmd_type = cmd.get('type', 'message')
            cmd_msg = cmd.get('message', '')[:100]
            lines.append(f"  → [{cmd_type}] {cmd_msg}")
        lines.append("**Use `get_pending_commands()` to process these!**")
        lines.append("")

    # 1.6. CUSTOM RULES (AI must follow these)
    custom_rules = _get_new_rules()
    if custom_rules:
        lines.append("")
        lines.append("📋 **ACTIVE RULES (you MUST follow):**")
        for rule in custom_rules:
            rule_text = rule.get('text', '')[:80]
            lines.append(f"  📌 {rule_text}")
        lines.append("")

    # 2. Current context (compact)
    project_name = memory.get('project_info', {}).get('name', session.project_id)
    goal = lr.get('intent', {}).get('current_goal', '')

    lines.append(f"📍 **{project_name}**" + (f" | 🎯 {goal}" if goal else ""))

    # 3. Active decisions (compact, one line)
    decisions = memory.get('decisions', [])
    if decisions:
        recent_dec = decisions[-1]  # Most recent
        dec_text = recent_dec.get('decision', '')[:50]
        lines.append(f"🔒 {dec_text}")

    lines.append("───────────────────────────────────────")

    return '\n'.join(lines)


def _universal_gate(tool_name: str) -> tuple:
    """
    Universal gate for all MCP tools.

    Returns: (error_message, context_header)
    - If error_message is not None, tool should return it immediately
    - context_header should be prepended to tool response

    This replaces _require_session with auto-session + context injection.
    """
    current_mode = _get_fixonce_mode()

    if current_mode == MODE_OFF:
        return ("FixOnce is off. Proceed normally without FixOnce tools.", "")

    passive_blocked_tools = {
        "auto_init_session",
        "init_session",
        "sync_to_active_project",
        "update_live_record",
        "log_decision",
        "log_avoid",
        "supersede_decision",
        "update_component_status",
        "mark_component_stable",
        "rollback_component",
        "add_component_files",
        "auto_discover_components",
        "log_debug_session",
        "rebuild_semantic_index",
        "smart_file_operation",
        "mark_command_executed",
        "get_pending_commands",
        "highlight_element",
    }
    if current_mode == MODE_PASSIVE and tool_name in passive_blocked_tools:
        return (
            "FixOnce is in PASSIVE mode. Write/action tools are disabled until mode returns to FULL.",
            "",
        )

    session = _get_session()

    # AUTO-SESSION: Create session automatically if not active
    if not session.is_active():
        if _auto_create_session():
            session = _get_session()
        else:
            # Still no session - but don't block, just note it
            return (None, "⚠️ No active project. Use auto_init_session() for full features.\n")

    # Resolve actor for this tool call
    actor_identity = _resolve_actor_identity()
    _compliance_state["editor"] = actor_identity["editor"]

    # Log tool call
    session.log_tool_call(tool_name)
    _sync_compliance()

    # REGISTER IN SESSION REGISTRY (Multi-AI Isolation)
    if _session_registry_available and session.is_active():
        try:
            ai_name = actor_identity.get("editor", "unknown")
            isolated_session = get_or_create_session(
                ai_name=ai_name,
                project_id=session.project_id,
                project_path=session.working_dir or ""
            )
            # Sync state to isolated session
            isolated_session.log_tool_call(tool_name)
            if session.initialized_at:
                isolated_session.mark_initialized()
            isolated_session.goal_updated = session.goal_updated
            isolated_session.decisions_displayed = session.decisions_displayed
        except Exception as e:
            _log(f"[FixOnce] SessionRegistry error: {e}")

    # UPDATE ACTIVE AI on every tool call (lightweight)
    _update_active_ai(actor_identity)

    # BUILD CONTEXT HEADER (injected into response)
    context = _build_context_header()

    # ADD INIT REMINDER if session not properly initialized
    # Skip for init tools themselves
    init_tools = {"auto_init_session", "init_session", "sync_to_active_project"}
    if tool_name not in init_tools and not _is_session_initialized():
        init_reminder = _get_init_reminder()
        context = init_reminder + context

    return (None, context)


def _update_active_ai(actor_identity: Optional[Dict[str, Any]] = None):
    """
    Update active_ais on every MCP tool call.
    PRIMARY MODEL: Only one AI is "primary" (currently active).
    Other AIs are marked as "historical" when a new AI takes over.
    """
    try:
        session = _get_session()
        if not session.project_id:
            return

        actor_identity = actor_identity or _resolve_actor_identity()
        detected_editor = actor_identity.get("editor", "unknown")
        actor_source = actor_identity.get("source", "fallback")
        actor_confidence = actor_identity.get("confidence", 0.0)
        if detected_editor == "unknown":
            return
        now = datetime.now()
        HISTORICAL_TIMEOUT_SECONDS = 60  # 1 minute to become historical

        # Check if we need to update
        project_id = session.project_id
        data = _load_project(project_id)
        if not data:
            return

        # Initialize active_ais if needed
        if "active_ais" not in data:
            data["active_ais"] = {}

        # Get this AI's current state
        ai_state = data["active_ais"].get(detected_editor, {})
        last_update = ai_state.get("last_activity", "")

        # Skip if same AI, already primary, and updated recently (30 seconds)
        if last_update and ai_state.get("is_primary"):
            try:
                last_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                if last_dt.tzinfo:
                    last_dt = last_dt.replace(tzinfo=None)
                if (now - last_dt).total_seconds() < 30:
                    return  # Skip update - too recent
            except:
                pass

        # Mark ALL other AIs as non-primary (historical)
        for ai_name in data["active_ais"]:
            if ai_name != detected_editor:
                data["active_ais"][ai_name]["is_primary"] = False

        # Get session tool calls count
        session = _get_session()
        session_tool_calls = len(session.tool_calls) if session else 0

        # Update this AI's state - make it PRIMARY
        if detected_editor not in data["active_ais"]:
            # New AI joining
            data["active_ais"][detected_editor] = {
                "started_at": now.isoformat(),
                "last_activity": now.isoformat(),
                "is_primary": True,
                "actor_source": actor_source,
                "actor_confidence": actor_confidence,
                "tool_calls": session_tool_calls,
            }
            _log(f"[MCP] AI Joined (primary): {detected_editor}")
        else:
            # Existing AI - update activity and make primary
            data["active_ais"][detected_editor]["last_activity"] = now.isoformat()
            data["active_ais"][detected_editor]["is_primary"] = True
            data["active_ais"][detected_editor]["actor_source"] = actor_source
            data["active_ais"][detected_editor]["actor_confidence"] = actor_confidence
            data["active_ais"][detected_editor]["tool_calls"] = session_tool_calls

        # Clean up old historical AIs (no activity for 1 minute AND not primary)
        remove_ais = []
        for ai_name, ai_data in list(data["active_ais"].items()):
            if ai_data.get("is_primary"):
                continue  # Never remove primary
            try:
                last_act = datetime.fromisoformat(ai_data.get("last_activity", "").replace('Z', '+00:00'))
                if last_act.tzinfo:
                    last_act = last_act.replace(tzinfo=None)
                if (now - last_act).total_seconds() > HISTORICAL_TIMEOUT_SECONDS:
                    remove_ais.append(ai_name)
            except:
                pass

        for ai_name in remove_ais:
            _log(f"[MCP] AI Removed (historical timeout): {ai_name}")
            del data["active_ais"][ai_name]

        # Update ai_session for backward compatibility (most recent AI)
        if "ai_session" not in data:
            data["ai_session"] = {}

        old_editor = data["ai_session"].get("editor", "")
        data["ai_session"]["editor"] = detected_editor
        data["ai_session"]["last_activity"] = now.isoformat()
        data["ai_session"]["active"] = True
        data["ai_session"]["actor_source"] = actor_source
        data["ai_session"]["actor_confidence"] = actor_confidence

        # Track handoff only if this is truly a different AI taking over
        # (not just parallel work)
        if old_editor and old_editor != detected_editor:
            # Check if old editor is still active
            old_ai_data = data["active_ais"].get(old_editor)
            if not old_ai_data:
                # Old editor timed out - this is a handoff
                if "ai_handoffs" not in data:
                    data["ai_handoffs"] = []
                data["ai_handoffs"].append({
                    "from": old_editor,
                    "to": detected_editor,
                    "timestamp": now.isoformat()
                })
                data["ai_handoffs"] = data["ai_handoffs"][-10:]

                data["ai_session"]["previous_ai"] = {
                    "editor": old_editor,
                    "started_at": data["ai_session"].get("started_at", ""),
                    "ended_at": now.isoformat()
                }
                _log(f"[MCP] AI Handoff: {old_editor} → {detected_editor}")

        _save_project(project_id, data)

    except Exception as e:
        # Don't break tool calls if update fails
        _log(f"[MCP] _update_active_ai error: {e}")


# Legacy function for backward compatibility
def _require_session(tool_name: str) -> Optional[str]:
    """
    DEPRECATED: Use _universal_gate instead.
    Kept for backward compatibility during transition.
    """
    error, _ = _universal_gate(tool_name)
    return error


def _require_project() -> str:
    """
    Get project_id from thread-local session.

    IMPORTANT: This is the NEW way to get project context.
    It NEVER reads from active_project.json.
    The session must be initialized via init_session() or auto_init_session().

    Returns:
        project_id from the current session

    Raises:
        ValueError: If no session is active
    """
    session = _get_session()
    if not session or not session.working_dir:
        raise ValueError("No project context. Call init_session(cwd) or auto_init_session() first.")
    return ProjectContext.from_path(session.working_dir)


def _get_browser_errors_reminder() -> str:
    """Get reminder about browser errors if there are any recent ones."""
    try:
        res = requests.get('http://localhost:5000/api/live-errors?since=300', timeout=2)
        if res.status_code == 200:
            data = res.json()
            count = data.get('count', 0)
            if count > 0:
                return f"""

🚨 BROWSER ERRORS DETECTED: {count} errors!
═══════════════════════════════════════
You MUST call: get_browser_errors()
DO NOT ignore this - the user sees these errors!
═══════════════════════════════════════"""
        return ""
    except Exception:
        return ""


def _is_ai_context_mode_active() -> bool:
    """Check if AI Context Mode is active (simple check, no injection)."""
    # v1: Feature disabled
    return False


def _get_ai_context_injection() -> Optional[str]:
    """
    Get AI Context injection if mode is active AND elements are selected.

    This function implements the AI Context feature:
    - When user enables AI Context mode in dashboard
    - AND has selected element(s) using the FAB in browser
    - We inject this context into init_session response
    - So the AI knows what "this/that/זה" refers to

    Returns:
        Formatted string with selected elements, or None if not applicable
    """
    # v1: Feature disabled
    return None

    try:
        # Check if AI Context mode is active
        mode_res = requests.get('http://localhost:5000/api/ai-context-mode', timeout=1)
        if mode_res.status_code != 200:
            return None

        mode_data = mode_res.json()
        if not mode_data.get('active', False):
            return None

        # Get selected elements
        context_res = requests.get('http://localhost:5000/api/browser-context', timeout=2)
        if context_res.status_code != 200:
            return None

        context_data = context_res.json()
        selected = context_data.get('selected_element')

        if not selected:
            return None

        # Extract element(s)
        elements = selected.get('elements', [])
        if not elements:
            el = selected.get('element')
            if el:
                elements = [el]

        if not elements:
            return None

        # Build injection
        lines = [
            "═══════════════════════════════════════",
            "## 🎯 AI CONTEXT ACTIVE - USER SELECTED ELEMENT(S)",
            "═══════════════════════════════════════",
            "",
            "**When user says \"this\", \"that\", \"זה\", \"את זה\" - they mean:**",
            ""
        ]

        for i, el in enumerate(elements[:3]):  # Max 3 elements
            selector = el.get('selector', 'N/A')
            tag = el.get('tagName', 'N/A')
            text = el.get('textContent', '')[:50]
            el_id = el.get('id', '')
            classes = el.get('className', '')[:30]

            if len(elements) > 1:
                lines.append(f"### Element {i+1}")

            lines.append(f"**Selector:** `{selector}`")
            lines.append(f"**Tag:** `{tag}`")

            if el_id:
                lines.append(f"**ID:** `{el_id}`")
            if classes:
                lines.append(f"**Classes:** `{classes}`")
            if text:
                lines.append(f"**Text:** \"{text}{'...' if len(el.get('textContent', '')) > 50 else ''}\"")

            # Show HTML snippet if available
            html = el.get('html', '')[:150]
            if html:
                lines.append(f"**HTML:** `{html}{'...' if len(el.get('html', '')) > 150 else ''}`")

            lines.append("")

        if len(elements) > 3:
            lines.append(f"_...and {len(elements) - 3} more elements_")
            lines.append("")

        lines.append("**Use this context when responding to user references.**")
        lines.append("═══════════════════════════════════════")
        lines.append("")

        return '\n'.join(lines)

    except Exception:
        return None


def _get_protocol_reminder() -> str:
    """Get periodic protocol reminder."""
    session = _get_session()
    if not session.is_active():
        return ""

    tool_count = len(session.tool_calls)

    # Every 5 tool calls, remind about browser errors
    if tool_count > 0 and tool_count % 5 == 0:
        return """

📋 PROTOCOL REMINDER (every 5 actions):
• Did you check get_browser_errors()?
• Did you update the goal if task changed?
• Are you using insights from init, not researching again?"""

    return ""


def _track_roi_event(event_type: str):
    """
    Track ROI event via Flask API.

    Events:
    - session_context: Session started with existing context
    - solution_reused: Past solution was found and applied
    - decision_used: Architectural decision was referenced
    - error_prevented: Avoid pattern prevented a mistake
    - insight_used: Existing insight was applied
    - error_caught_live: Browser error detected in real-time
    """
    try:
        requests.post(
            "http://localhost:5000/api/memory/roi/track",
            json={"event": event_type},
            timeout=2
        )
    except Exception:
        pass  # Silent fail - don't block MCP operations


def _log_mcp_activity(tool_name: str, details: dict = None):
    """
    Log MCP tool calls as activity for dashboard tracking.

    This enables visibility into AI memory operations like:
    - update_live_record (goal changes, insights)
    - log_decision
    - log_avoid
    - search_past_solutions

    Args:
        tool_name: Name of the MCP tool being called
        details: Optional dict with additional info (section, text, etc.)
    """
    try:
        session = _get_session()
        project_id = session.project_id if session.is_active() else "__global__"
        working_dir = session.working_dir if session.is_active() else ""

        # Get actor info
        actor_identity = _resolve_actor_identity()
        detected_editor = actor_identity.get("editor", "unknown")

        # Build activity entry
        activity = {
            "type": "mcp_tool",
            "tool": tool_name,
            "file": None,  # MCP tools don't have files
            "command": None,
            "cwd": working_dir,
            "project_id": project_id,
            "editor": detected_editor,
            "actor": detected_editor,
            "actor_source": actor_identity.get("source", "fallback"),
            "actor_confidence": actor_identity.get("confidence", 0.0),
            "timestamp": datetime.now().isoformat(),
            "human_name": _get_mcp_human_name(tool_name, details),
            "file_context": "memory",
            "mcp_details": details or {}
        }

        # Send to activity API
        requests.post(
            "http://localhost:5000/api/activity/log",
            json=activity,
            timeout=2
        )
    except Exception as e:
        # Silent fail - don't block MCP operations
        _log(f"[MCP] Activity log failed: {e}")


def _get_mcp_human_name(tool_name: str, details: dict = None) -> str:
    """Get human-readable name for MCP tool activity."""
    details = details or {}

    if tool_name == "update_live_record":
        section = details.get("section", "")
        if section == "intent":
            goal = details.get("goal", "")[:30]
            return f"Goal: {goal}..." if goal else "Updated goal"
        elif section == "lessons":
            if details.get("insight"):
                return "Added insight"
            elif details.get("failed_attempt"):
                return "Logged failed attempt"
            return "Updated lessons"
        elif section == "architecture":
            return "Updated architecture"
        return f"Updated {section}"

    elif tool_name == "log_decision":
        decision = details.get("decision", "")[:25]
        return f"Decision: {decision}..." if decision else "Logged decision"

    elif tool_name == "log_avoid":
        what = details.get("what", "")[:25]
        return f"Avoid: {what}..." if what else "Logged avoid pattern"

    elif tool_name == "search_past_solutions":
        query = details.get("query", "")[:20]
        return f"Search: {query}..." if query else "Searched solutions"

    elif tool_name == "auto_init_session":
        return "Session initialized"

    elif tool_name == "scan_project":
        return "Scanned project"

    elif tool_name == "update_component_status":
        name = details.get("name", "")[:20]
        status = details.get("status", "")
        status_icons = {"done": "🟢", "in_progress": "🟡", "blocked": "🔴", "not_started": "⚪",
                        "stable": "🟢", "building": "🟡", "broken": "🔴"}
        icon = status_icons.get(status, "⚙️")
        return f"{icon} {name}: {status}"

    elif tool_name == "mark_component_stable":
        name = details.get("name", "")[:20]
        return f"🔒 Marked stable: {name}"

    elif tool_name == "rollback_component":
        name = details.get("name", "")[:20]
        return f"🔄 Rollback: {name}"

    elif tool_name == "check_component_changes":
        name = details.get("name", "")[:20]
        return f"🔍 Checked: {name}"

    elif tool_name == "add_component_files":
        name = details.get("name", "")[:20]
        return f"📁 Added files to: {name}"

    elif tool_name == "stability_warning":
        component = details.get("component", "")[:20]
        return f"⚠️ Modified stable: {component}"

    elif tool_name == "get_stability_report":
        return "📊 Stability report"

    elif tool_name == "supersede_decision":
        old = details.get("old", "")[:20]
        return f"Superseded: {old}..."

    elif tool_name == "get_policy_status":
        return "Checked policy status"

    return tool_name.replace("_", " ").title()


# ============================================================
# MEMORY DECAY SYSTEM
# ============================================================

def _create_insight(text: str, linked_error: Optional[dict] = None) -> dict:
    """
    Create a new insight with full metadata for decay tracking.

    Fix #2: Auto-Link Incidents - if there's an active error, link it to this insight.
    """
    insight = {
        "text": text,
        "timestamp": datetime.now().isoformat(),
        "use_count": 0,
        "last_used": None,
        "importance": "medium"  # low/medium/high - auto-calculated
    }

    # Fix #2: Link to active error if provided
    if linked_error:
        insight["linked_error"] = {
            "message": linked_error.get("message", "")[:200],
            "source": linked_error.get("source", ""),
            "timestamp": linked_error.get("timestamp", ""),
            "linked_at": datetime.now().isoformat()
        }

    return insight


def _mark_insight_used(insight: dict) -> dict:
    """Mark an insight as used and update its importance."""
    insight["use_count"] = insight.get("use_count", 0) + 1
    insight["last_used"] = datetime.now().isoformat()

    # Track ROI: insight was used
    _track_roi_event("insight_used")

    # Auto-calculate importance based on use_count
    use_count = insight["use_count"]
    if use_count >= 5:
        insight["importance"] = "high"
    elif use_count >= 2:
        insight["importance"] = "medium"
    else:
        insight["importance"] = "low"

    return insight


def _normalize_insight(insight) -> dict:
    """Ensure insight has the new format with metadata."""
    if isinstance(insight, str):
        # Old format: just a string
        return _create_insight(insight)
    elif isinstance(insight, dict):
        # Might be old format with just 'text' or new format
        if "use_count" not in insight:
            # Old format with text/timestamp but no decay metadata
            text = insight.get("text", str(insight))
            new_insight = _create_insight(text)
            # Preserve original timestamp if it exists
            if "timestamp" in insight:
                new_insight["timestamp"] = insight["timestamp"]
            return new_insight
        return insight
    else:
        return _create_insight(str(insight))


def _calculate_insight_score(insight: dict) -> float:
    """
    Calculate a score for ranking insights.
    Higher score = more important/recent.
    """
    score = 0.0

    # Importance weight
    importance = insight.get("importance", "medium")
    if importance == "high":
        score += 100
    elif importance == "medium":
        score += 50
    else:
        score += 10

    # Use count bonus
    use_count = insight.get("use_count", 0)
    score += use_count * 10

    # Recency bonus (insights from last 7 days get boost)
    try:
        timestamp = insight.get("timestamp", "")
        if timestamp:
            created = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if created.tzinfo:
                created = created.replace(tzinfo=None)
            age_days = (datetime.now() - created).days
            if age_days <= 1:
                score += 50  # Today
            elif age_days <= 7:
                score += 30  # This week
            elif age_days <= 30:
                score += 10  # This month
    except Exception:
        pass

    return score


def _get_ranked_insights(insights: list, limit: int = 10) -> list:
    """Get top insights ranked by importance/recency/usage."""
    # Normalize all insights to new format
    normalized = [_normalize_insight(ins) for ins in insights]

    # Sort by score (highest first)
    ranked = sorted(normalized, key=_calculate_insight_score, reverse=True)

    return ranked[:limit]


def _should_archive_insight(insight: dict) -> bool:
    """
    Check if an insight should be archived (moved to cold storage).

    IMPORTANT: Decisions and avoid patterns should NEVER be archived.
    They are stored separately in memory['decisions'] and memory['avoid'],
    but this check ensures they're protected even if accidentally mixed in.
    """
    try:
        # NEVER archive decisions or avoid patterns - they are permanent institutional knowledge
        insight_type = insight.get("type", "insight")
        if insight_type in ("decision", "avoid", "failed_attempt"):
            return False

        # Never archive high-importance insights
        if insight.get("importance") == "high":
            return False

        # Never used and older than 30 days
        use_count = insight.get("use_count", 0)
        timestamp = insight.get("timestamp", "")

        if not timestamp:
            return False

        created = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if created.tzinfo:
            created = created.replace(tzinfo=None)
        age_days = (datetime.now() - created).days

        # Archive if: never used AND older than 30 days AND importance is low
        if use_count == 0 and age_days > 30 and insight.get("importance") == "low":
            return True

        # Archive if: not used in 60 days regardless (but only for low importance)
        last_used = insight.get("last_used")
        if last_used:
            last = datetime.fromisoformat(last_used.replace('Z', '+00:00'))
            if last.tzinfo:
                last = last.replace(tzinfo=None)
            unused_days = (datetime.now() - last).days
            if unused_days > 60 and insight.get("importance") != "medium":
                return True
        elif age_days > 60 and insight.get("importance") == "low":
            # Never used and very old - only for low importance
            return True

        return False
    except Exception:
        return False


def _get_session() -> SessionContext:
    """Get current session for this thread (never returns None)."""
    if not hasattr(_session_local, 'session') or _session_local.session is None:
        _session_local.session = SessionContext()
    return _session_local.session


def _set_session(project_id: str, working_dir: str):
    """Set session for current thread and update global state for dashboard."""
    _session_local.session = SessionContext(project_id, working_dir)
    # Sync to global state for Flask API (different thread)
    _compliance_state["session_active"] = True
    _compliance_state["initialized_at"] = datetime.now().isoformat()
    _compliance_state["project_id"] = project_id
    _compliance_state["last_session_init"] = datetime.now().isoformat()


def _clear_session():
    """Clear session for current thread and global state."""
    _session_local.session = SessionContext()
    # Clear global state
    _compliance_state["session_active"] = False
    _compliance_state["initialized_at"] = None
    _compliance_state["project_id"] = None


def _sync_compliance():
    """Sync session state to global _compliance_state for dashboard API."""
    session = _get_session()
    _compliance_state["session_active"] = session.is_active()
    _compliance_state["initialized_at"] = session.initialized_at
    _compliance_state["project_id"] = session.project_id
    _compliance_state["decisions_displayed"] = session.decisions_displayed
    _compliance_state["goal_updated"] = session.goal_updated
    _compliance_state["search_performed"] = session.search_performed
    _compliance_state["component_updated"] = session.component_updated
    _compliance_state["decision_logged"] = session.decision_logged
    _compliance_state["tool_calls_count"] = len(session.tool_calls)
    # Calculate and sync score
    score_data = session.get_compliance_score()
    _compliance_state["score"] = score_data["score"]
    _compliance_state["rules"] = score_data["rules"]
    # Persist to file for Flask API access
    _persist_compliance()


# ============================================================
# GIT UTILITIES
# ============================================================

def _get_git_commit_hash(working_dir: str) -> Optional[str]:
    """Get current git commit hash for a directory."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]  # Short hash
        return None
    except Exception:
        return None


def _is_git_repo(working_dir: str) -> bool:
    """Check if directory is a git repository."""
    git_dir = Path(working_dir) / '.git'
    return git_dir.exists()


# ============================================================
# PROJECT INDEX (Cache with git hash invalidation)
# ============================================================

def _load_index() -> Dict[str, Any]:
    """Load project index from disk."""
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"version": 1, "projects": {}}


def _save_index(index: Dict[str, Any]):
    """Save project index to disk."""
    index["updated_at"] = datetime.now().isoformat()
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _get_cached_snapshot(project_id: str, working_dir: str) -> Optional[Dict[str, Any]]:
    """
    Get cached snapshot if valid.
    Returns None if:
    - Not in cache
    - Git hash changed (code changed)
    """
    index = _load_index()
    snapshot = index.get("projects", {}).get(project_id)

    if not snapshot:
        return None

    # Check git hash if it's a git repo
    if _is_git_repo(working_dir):
        current_hash = _get_git_commit_hash(working_dir)
        cached_hash = snapshot.get("git_commit_hash")

        if current_hash and cached_hash and current_hash != cached_hash:
            # Code changed - invalidate cache
            return None

    return snapshot


def _update_snapshot(project_id: str, working_dir: str, data: Dict[str, Any]):
    """Update project snapshot in index."""
    index = _load_index()

    lr = data.get('live_record', {})

    snapshot = {
        "project_id": project_id,
        "working_dir": working_dir,
        "name": data.get('project_info', {}).get('name', Path(working_dir).name),
        "git_commit_hash": _get_git_commit_hash(working_dir) if _is_git_repo(working_dir) else None,
        "summary": lr.get('architecture', {}).get('summary', ''),
        "stack": lr.get('architecture', {}).get('stack', ''),
        "current_goal": lr.get('intent', {}).get('current_goal', ''),
        "last_insight": (lr.get('lessons', {}).get('insights', []) or [''])[-1] if lr.get('lessons', {}).get('insights') else '',
        "decisions_count": len(data.get('decisions', [])),
        "avoid_count": len(data.get('avoid', [])),
        "indexed_at": datetime.now().isoformat()
    }

    if "projects" not in index:
        index["projects"] = {}

    index["projects"][project_id] = snapshot
    _save_index(index)


# ============================================================
# MCP SERVER
# ============================================================

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
    except Exception:
        return None


def _get_project_id(working_dir: str) -> str:
    """
    Convert working_dir to a safe project ID.

    IMPORTANT: This now delegates to ProjectContext.from_path()
    which is the SINGLE SOURCE OF TRUTH for project ID generation.
    """
    return ProjectContext.from_path(working_dir)


def _get_project_path(project_id: str) -> Path:
    """Get path to project memory file."""
    return DATA_DIR / f"{project_id}.json"


def _load_project(project_id: str) -> Dict[str, Any]:
    """Load project memory with auto-recovery from backups."""
    path = _get_project_path(project_id)

    if _safe_file_available:
        # Use safe read with auto-recovery
        return atomic_json_read(str(path), default={}, auto_recover=True)

    # Fallback to regular json
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_project(project_id: str, data: Dict[str, Any]):
    """Save project memory with auto-backup (to V2 canonical storage)."""
    path = _get_project_path(project_id)

    if _safe_file_available:
        # Use safe write with auto-backup
        atomic_json_write(str(path), data, create_backup=True)
    else:
        # Fallback to regular json
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # Update index snapshot
    session = _get_session()
    if session.working_dir:
        _update_snapshot(project_id, session.working_dir, data)


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
                "stack": "",
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


def _find_and_migrate_legacy_project(new_project_id: str, working_dir: str) -> Optional[Dict[str, Any]]:
    """
    Search for legacy project files with the same name but a different hash.

    Handles ID changes caused by:
    - git remote URL changes
    - Migration between hash strategies (path → git_remote, etc.)
    - Repository renames

    Safety: only migrates if the old file's working_dir is empty or matches.

    Returns migrated data dict, or None if no legacy data found.
    """
    name_prefix = new_project_id.rsplit('_', 1)[0]
    if not name_prefix:
        return None

    candidates = []
    for f in DATA_DIR.glob(f"{name_prefix}_*.json"):
        if '.migrated' in f.name:
            continue
        candidate_id = f.stem
        if candidate_id == new_project_id:
            continue
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception:
            continue

        if not _is_meaningful_project(data):
            continue

        old_wd = data.get('project_info', {}).get('working_dir', '')
        old_gps_wd = data.get('live_record', {}).get('gps', {}).get('working_dir', '')
        effective_old_wd = old_wd or old_gps_wd

        if effective_old_wd and effective_old_wd != working_dir:
            continue

        decisions = len(data.get('decisions', []))
        insights = len(data.get('live_record', {}).get('lessons', {}).get('insights', []))
        solutions = len(data.get('solutions_history', []))
        candidates.append((f, candidate_id, data, decisions + insights + solutions))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[3], reverse=True)
    best_file, old_id, old_data, _ = candidates[0]

    new_data = _init_project_memory(working_dir)

    for key in ['decisions', 'avoid', 'solutions_history', 'active_issues', 'stats', 'roi']:
        if old_data.get(key):
            new_data[key] = old_data[key]

    old_lr = old_data.get('live_record', {})
    new_lr = new_data['live_record']
    for section in ['architecture', 'intent', 'lessons']:
        old_section = old_lr.get(section, {})
        if section == 'lessons':
            if old_section.get('insights') or old_section.get('failed_attempts'):
                new_lr[section] = old_section
        elif section == 'architecture':
            if old_section.get('summary') or old_section.get('stack') or old_section.get('key_flows'):
                new_lr[section] = old_section
        elif section == 'intent':
            if old_section.get('current_goal'):
                new_lr[section] = old_section

    if old_data.get('project_info', {}).get('created_at'):
        new_data['project_info']['created_at'] = old_data['project_info']['created_at']

    # Migrate embeddings directory if it exists
    old_embeddings = DATA_DIR / f"{old_id}.embeddings"
    new_embeddings = DATA_DIR / f"{new_project_id}.embeddings"
    if old_embeddings.is_dir() and not new_embeddings.exists():
        try:
            old_embeddings.rename(new_embeddings)
        except Exception as e:
            _log(f"[MCP] Failed to migrate embeddings: {e}")

    # Archive old project file
    try:
        archive_path = best_file.with_suffix('.migrated.json')
        best_file.rename(archive_path)
    except Exception:
        pass

    _log(f"[MCP] Migrated project data: {old_id} → {new_project_id}")
    return new_data


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
def auto_init_session(cwd: str = "", sync_to_active: bool = False) -> str:
    """
    Automatically initialize session for the current project.

    Phase 1: Uses boundary detection as single source of truth.
    - Detects actual project root from cwd (not just uses cwd directly)
    - Compares against active project
    - Triggers boundary transition if needed

    Args:
        cwd: Optional current working directory from Claude Code
        sync_to_active: If True, join the currently active project regardless of cwd.
                       Use this for Multi-AI sync (e.g., Cursor joining Claude's project)

    Returns:
        Session info with project details
    """
    mode = _get_fixonce_mode()
    if mode == MODE_OFF:
        return "FixOnce is off. Proceed normally without FixOnce tools."
    if mode == MODE_PASSIVE:
        return "FixOnce is in PASSIVE mode. Session initialization is disabled."

    # Multi-AI Sync: If sync_to_active is True, use the active project
    if sync_to_active:
        try:
            from core.boundary_detector import _load_active_project
            active = _load_active_project()
            active_working_dir = active.get("working_dir")
            if active_working_dir and os.path.isdir(active_working_dir):
                _log(f"[MCP] Multi-AI Sync: Joining active project at {active_working_dir}")
                _debug_log(f"SYNC_TO_ACTIVE: joining {active_working_dir}")
                return _do_init_session(active_working_dir)
        except Exception as e:
            _log(f"[MCP] Multi-AI Sync failed: {e}")

    # DEBUG: Log what cwd is received
    import sys
    _log(f"[MCP DEBUG] auto_init_session called with cwd='{cwd}'", file=sys.stderr)
    _debug_log(f"auto_init_session cwd='{cwd}'")

    working_dir = None
    boundary_triggered = False

    # Phase 1: Use boundary detection to find actual project root
    if BOUNDARY_DETECTION_ENABLED and cwd and os.path.isdir(cwd):
        # Find the actual project root from cwd
        project_root, marker, confidence = find_project_root(cwd)

        if project_root and confidence in ("high", "medium"):
            # We found a valid project root
            # Check if it's different from current active project
            from core.boundary_detector import _load_active_project
            active = _load_active_project()
            active_working_dir = active.get("working_dir")

            if active_working_dir:
                # Compare: is this a different project?
                if not is_within_boundary(project_root, active_working_dir):
                    # Different project! Check if we should switch
                    # Create a synthetic boundary event for the session start
                    _log(f"[MCP] Session init boundary check:")
                    _log(f"  CWD: {cwd}")
                    _log(f"  Detected root: {project_root}")
                    _log(f"  Active project: {active_working_dir}")
                    _log(f"  Confidence: {confidence}")

                    # Trigger boundary transition
                    from core.boundary_detector import _get_project_id_from_path, _load_boundary_state, _is_cooldown_active

                    state = _load_boundary_state()
                    new_project_id = _get_project_id_from_path(project_root)

                    # Check cooldown and anti-ping-pong
                    if not _is_cooldown_active(state) and state.get("last_switch_from") != new_project_id:
                        event = BoundaryEvent(
                            old_project_id=active.get("active_id", ""),
                            old_working_dir=active_working_dir,
                            new_project_id=new_project_id,
                            new_working_dir=project_root,
                            file_path=cwd,
                            reason="session_init",
                            confidence=confidence,
                            timestamp=datetime.now().isoformat()
                        )
                        handle_boundary_transition(event)
                        boundary_triggered = True
                        _log(f"  Action: SWITCH to {project_root}")

            working_dir = project_root
        elif _is_valid_project_dir(cwd):
            # No strong marker but cwd itself is valid
            working_dir = cwd

    # Fallback: cwd if valid project directory
    if not working_dir:
        home_dir = str(Path.home())
        if cwd and os.path.isdir(cwd) and cwd != home_dir and _is_valid_project_dir(cwd):
            working_dir = cwd

    # WORKSPACE-BASED IDENTITY: cwd is required, no fallback to global state
    # active_project.json is updated as side-effect but NOT used for routing
    if working_dir:
        return _do_init_session(working_dir)

    # No valid workspace - return clear, actionable error
    home_dir = str(Path.home())
    is_home = cwd == home_dir if cwd else True

    if is_home:
        return f"""🏠 You're in your home directory ({home_dir}).

FixOnce needs a project folder to work with.

**What to do:**
1. Close this terminal
2. Open Claude Code **from inside a project folder**:
   ```
   cd ~/your-project
   claude
   ```

Or use `init_session(working_dir="/path/to/project")` to connect manually.

---
🏠 אתה בתיקיית הבית. FixOnce צריך תיקיית פרויקט.
פתח Claude Code מתוך תיקיית פרויקט (cd ~/project && claude)"""
    else:
        return f"""📁 This folder doesn't look like a project: {cwd}

FixOnce needs a project folder with files like:
.git, package.json, requirements.txt, etc.

**What to do:**
Navigate to your project root and try again, or:
`init_session(working_dir="/path/to/your/project")`"""


def _is_valid_project_dir(path: str) -> bool:
    """Check if path is a valid project directory (not home, not root, has project files)."""
    p = Path(path)

    # Reject home directory and root
    if str(p) == str(Path.home()) or str(p) == "/":
        return False

    # Check for common project markers
    project_markers = [
        '.git', 'package.json', 'pyproject.toml', 'Cargo.toml',
        'go.mod', 'pom.xml', 'build.gradle', 'Makefile',
        'requirements.txt', 'setup.py', '.project', 'CLAUDE.md'
    ]

    for marker in project_markers:
        if (p / marker).exists():
            return True

    # Check if it has source files (not just random dir)
    source_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java', '.rb'}
    try:
        for f in p.iterdir():
            if f.is_file() and f.suffix in source_extensions:
                return True
    except PermissionError:
        pass

    return False


def _get_working_dir_from_recent_activity() -> Optional[str]:
    """Get the most recent project directory from activity log."""
    try:
        activity_file = SRC_DIR.parent / "data" / "activity_log.json"
        if not activity_file.exists():
            return None

        with open(activity_file, 'r') as f:
            data = json.load(f)

        activities = data.get('activities', [])
        if not activities:
            return None

        # Find the most recent activity with a valid cwd
        for act in activities:
            cwd = act.get('cwd', '')
            if cwd and os.path.isdir(cwd) and _is_valid_project_dir(cwd):
                return cwd

        return None
    except Exception:
        return None


def _do_init_session(working_dir: str) -> str:
    """Internal init session logic - thread-safe, no global state."""
    if not working_dir or not os.path.isdir(working_dir):
        return f"Error: Invalid working directory: {working_dir}"

    project_id = _get_project_id(working_dir)

    # Set thread-local session
    _set_session(project_id, working_dir)

    # Persist session to file for recovery after MCP restart
    _persist_session(project_id, working_dir)

    # Mark session as initialized for compliance tracking
    session = _get_session()
    session.mark_initialized()
    session.log_tool_call("auto_init_session")

    # Mark global session as initialized (for cross-tool reminder)
    _mark_session_initialized()

    # Update global compliance state for dashboard
    _compliance_state["last_session_init"] = datetime.now().isoformat()
    actor_identity = _resolve_actor_identity()
    _compliance_state["editor"] = actor_identity.get("editor", "unknown")

    # REGISTER IN SESSION REGISTRY (Multi-AI Isolation)
    if _session_registry_available:
        try:
            ai_name = actor_identity.get("editor", "unknown")
            isolated_session = get_or_create_session(
                ai_name=ai_name,
                project_id=project_id,
                project_path=working_dir
            )
            isolated_session.mark_initialized()
            isolated_session.log_tool_call("auto_init_session")
            _log(f"[FixOnce] Registered session: {ai_name} on {project_id}")
        except Exception as e:
            _log(f"[FixOnce] SessionRegistry error in init: {e}")

    # Update active_ais for Multi-Active support
    _update_active_ai()

    # CRITICAL FIX: Update dashboard's active project
    # When AI explicitly calls auto_init_session(cwd), dashboard should follow
    try:
        from managers.multi_project_manager import set_active_project
        set_active_project(
            project_id=project_id,
            detected_from="auto_init",
            display_name=Path(working_dir).name,
            working_dir=working_dir
        )
    except Exception as e:
        _log(f"[FixOnce] Failed to update active project: {e}")

    # Track ROI: session with context
    _track_roi_event("session_context")

    # Check cache first (with git hash validation)
    cached = _get_cached_snapshot(project_id, working_dir)
    if cached and _is_meaningful_snapshot(cached):
        # Still update ai_session for cached projects
        actor_identity = _resolve_actor_identity()
        detected_editor = actor_identity.get("editor", "unknown")
        data = _load_project(project_id)
        if data:
            # Track previous AI for handoff (Multi-AI Sync) - also in cache path
            previous_ai = None
            if data.get("ai_session") and data["ai_session"].get("editor"):
                prev_editor = data["ai_session"].get("editor")
                prev_started = data["ai_session"].get("started_at")
                if prev_editor and prev_started:
                    previous_ai = {
                        "editor": prev_editor,
                        "started_at": prev_started,
                        "ended_at": datetime.now().isoformat()
                    }

            data["ai_session"] = {
                "active": True,
                "editor": detected_editor,
                "started_at": datetime.now().isoformat(),
                "briefing_sent": False,
                "actor_source": actor_identity.get("source", "fallback"),
                "actor_confidence": actor_identity.get("confidence", 0.0),
                "previous_ai": previous_ai
            }

            # Track handoff history
            if "ai_handoffs" not in data:
                data["ai_handoffs"] = []
            if previous_ai and previous_ai["editor"] != detected_editor:
                data["ai_handoffs"].append({
                    "from": previous_ai["editor"],
                    "to": detected_editor,
                    "timestamp": datetime.now().isoformat()
                })
                data["ai_handoffs"] = data["ai_handoffs"][-10:]

            _save_project(project_id, data)
        return _format_from_snapshot(cached, working_dir)

    # Load or create project (with legacy migration)
    data = _load_project(project_id)
    migrated = False
    if not data or not _is_meaningful_project(data):
        legacy_data = _find_and_migrate_legacy_project(project_id, working_dir)
        if legacy_data:
            if data:
                for key in ('ai_session', 'active_ais', 'ai_handoffs'):
                    if data.get(key):
                        legacy_data[key] = data[key]
            data = legacy_data
            migrated = True
        elif not data:
            data = _init_project_memory(working_dir)

    # Track previous AI for handoff (Multi-AI Sync)
    previous_ai = None
    if data.get("ai_session") and data["ai_session"].get("editor"):
        prev_editor = data["ai_session"].get("editor")
        prev_started = data["ai_session"].get("started_at")
        if prev_editor and prev_started:
            previous_ai = {
                "editor": prev_editor,
                "started_at": prev_started,
                "ended_at": datetime.now().isoformat()
            }

    # Update ai_session with detected editor
    actor_identity = _resolve_actor_identity()
    detected_editor = actor_identity.get("editor", "unknown")
    data["ai_session"] = {
        "active": True,
        "editor": detected_editor,
        "started_at": datetime.now().isoformat(),
        "briefing_sent": False,
        "actor_source": actor_identity.get("source", "fallback"),
        "actor_confidence": actor_identity.get("confidence", 0.0),
        "previous_ai": previous_ai  # Track handoff
    }

    # Keep history of AI handoffs
    if "ai_handoffs" not in data:
        data["ai_handoffs"] = []
    if previous_ai and previous_ai["editor"] != detected_editor:
        data["ai_handoffs"].append({
            "from": previous_ai["editor"],
            "to": detected_editor,
            "timestamp": datetime.now().isoformat()
        })
        # Keep last 10 handoffs
        data["ai_handoffs"] = data["ai_handoffs"][-10:]

    _save_project(project_id, data)

    # Determine status
    status = "existing" if _is_meaningful_project(data) else "new"

    # Update index
    _update_snapshot(project_id, working_dir, data)

    # Build response
    response = _format_init_response(data, status, working_dir)
    if migrated:
        response += "\n\n🔄 **Memory migrated** — project ID changed (git remote/hash strategy). All decisions, insights, and history preserved."
    return response


def _is_meaningful_snapshot(snapshot: Dict[str, Any]) -> bool:
    """Check if snapshot has meaningful data."""
    return bool(
        snapshot.get('summary') or
        snapshot.get('current_goal') or
        snapshot.get('last_insight') or
        snapshot.get('decisions_count', 0) > 0
    )


def _get_browser_errors_summary(limit: int = 3) -> Optional[str]:
    """Get summary of recent browser errors for init response with auto-injected solutions."""
    try:
        res = requests.get('http://localhost:5000/api/live-errors', timeout=2)
        if res.status_code != 200:
            return None

        data = res.json()
        errors = data.get('errors', [])

        if not errors:
            return None

        lines = ["### ⚠️ Browser Errors Detected"]
        solutions_found = 0
        injected_solutions = set()  # Prevent duplicates

        for err in errors[:limit]:
            msg = err.get('message', err.get('error', 'Unknown'))
            msg_short = msg[:60] if len(msg) > 60 else msg
            source = err.get('source', err.get('url', ''))
            source_short = source.split('/')[-1][:30] if source else 'Browser'
            lines.append(f"• **{source_short}**: {msg_short}")

            # Auto-Inject Solutions (with quality controls)
            solution = _find_solution_for_error(msg)
            if solution:
                solution_key = solution['text'][:50]
                if solution_key not in injected_solutions:
                    solutions_found += 1
                    injected_solutions.add(solution_key)
                    lines.append(f"  💡 **Solved before ({solution['similarity']}%):** {solution['text'][:80]}...")

        if solutions_found > 0:
            lines.append(f"\n✅ **{solutions_found} known fix(es).** Apply them.")

        if len(errors) > limit:
            lines.append(f"_...and {len(errors) - limit} more. Use `get_browser_errors()` for full list._")

        return '\n'.join(lines)
    except Exception:
        return None


def _check_stable_component_impact(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Check if a file belongs to a STABLE component.

    Returns:
        None if no stable component affected
        Dict with component info if affected: {"name": ..., "commit": ..., "files": [...]}
    """
    try:
        session = _get_session()
        if not session.is_active():
            return None

        memory = _load_project(session.project_id)
        arch = memory.get("live_record", {}).get("architecture", {})
        components = arch.get("components", [])

        # Normalize file path for comparison
        file_path_normalized = file_path.replace("\\", "/")
        if file_path_normalized.startswith("./"):
            file_path_normalized = file_path_normalized[2:]

        for comp in components:
            # Only check stable components with checkpoints
            if comp.get("status") not in ["stable", "done"]:
                continue
            if not comp.get("last_stable"):
                continue

            comp_files = comp.get("files", [])
            for cf in comp_files:
                cf_normalized = cf.replace("\\", "/")
                if cf_normalized.startswith("./"):
                    cf_normalized = cf_normalized[2:]

                # Check if file matches (exact or ends with)
                if (file_path_normalized == cf_normalized or
                    file_path_normalized.endswith("/" + cf_normalized) or
                    cf_normalized.endswith("/" + file_path_normalized)):
                    return {
                        "name": comp.get("name"),
                        "commit": comp.get("last_stable", {}).get("commit_short", "unknown"),
                        "files": comp_files
                    }

        return None
    except Exception:
        return None


def _log_stable_component_modification(component_name: str, file_path: str, actor: str = "AI") -> None:
    """Log when AI modifies a stable component."""
    try:
        session = _get_session()
        if not session.is_active():
            return

        memory = _load_project(session.project_id)

        # Add to activity log in memory
        activity = {
            "type": "stability_warning",
            "action": f"Modified stable component: {component_name}",
            "file": file_path,
            "actor": actor,
            "timestamp": datetime.now().isoformat(),
            "severity": "warning"
        }

        if "activity_log" not in memory:
            memory["activity_log"] = []
        memory["activity_log"].append(activity)

        # Keep last 100 activities
        if len(memory["activity_log"]) > 100:
            memory["activity_log"] = memory["activity_log"][-100:]

        _save_project(session.project_id, memory)

        # Send to activity API for dashboard visibility
        actor_identity = _resolve_actor_identity()
        detected_editor = actor_identity.get("editor", "unknown")

        api_activity = {
            "type": "stability_warning",
            "tool": "stability_warning",
            "file": file_path,
            "cwd": session.working_dir,
            "project_id": session.project_id,
            "editor": detected_editor,
            "actor": detected_editor,
            "timestamp": datetime.now().isoformat(),
            "human_name": f"⚠️ Modified stable: {component_name}",
            "action": f"Modified stable component: {component_name}",
            "file_context": "stability",
            "mcp_details": {
                "component": component_name,
                "file": file_path
            }
        }

        requests.post(
            "http://localhost:5000/api/activity/log",
            json=api_activity,
            timeout=2
        )
    except Exception:
        pass


def _format_from_snapshot(snapshot: Dict[str, Any], working_dir: str) -> str:
    """Format init response from cached snapshot."""
    lines = []

    # LIVE ERRORS FIRST (Universal Gate principle) + AUTO-INJECT SOLUTIONS
    live_errors = _get_live_errors()
    if live_errors:
        lines.append("═══════════════════════════════════════")
        lines.append(f"## ⚠️ {len(live_errors)} LIVE ERRORS - FIX BEFORE PROCEEDING")
        lines.append("═══════════════════════════════════════")

        solutions_found = 0
        injected_solutions = set()  # Prevent duplicates

        for e in live_errors[:3]:
            msg = e.get('message', 'Unknown error')
            msg_short = msg[:70] if len(msg) > 70 else msg
            lines.append(f"• {msg_short}")

            # Auto-Inject Solutions (with quality controls)
            solution = _find_solution_for_error(msg)
            if solution:
                solution_key = solution['text'][:50]
                if solution_key not in injected_solutions:
                    solutions_found += 1
                    injected_solutions.add(solution_key)
                    lines.append(f"  💡 **Solved before ({solution['similarity']}%):** {solution['text'][:100]}...")

        if len(live_errors) > 3:
            lines.append(f"• ...and {len(live_errors) - 3} more")

        if solutions_found > 0:
            lines.append("")
            lines.append(f"✅ **{solutions_found} known fix(es).** Apply them.")
        else:
            lines.append("")
            lines.append("**You MUST address these errors before doing anything else.**")
        lines.append("")

    # Project info
    lines.extend([
        f"## Project: {snapshot.get('name', Path(working_dir).name)}",
        f"**Status:** EXISTING",
        f"**Path:** `{working_dir}`",
        ""
    ])

    # DECISIONS FIRST - Load from project file (not cached in snapshot)
    project_id = _get_project_id(working_dir)
    data = _load_project(project_id)
    all_decisions = data.get('decisions', []) if data else []
    # Filter out superseded decisions - only show active ones
    decisions = [d for d in all_decisions if not d.get('superseded')]
    superseded_count = len(all_decisions) - len(decisions)

    if decisions:
        lines.append("---")
        lines.append("## 🚨 ACTIVE DECISIONS - YOU MUST RESPECT THESE")
        lines.append("")
        lines.append("**STOP before any change that contradicts these decisions!**")
        lines.append("**Ask user for explicit override approval if request conflicts.**")
        lines.append("")
        # MCP DIET: Limit to 8 most recent decisions (same as _format_init_response)
        MAX_DECISIONS = 8
        decisions_to_show = decisions[-MAX_DECISIONS:]
        for dec in decisions_to_show:
            # Truncate long decisions
            dec_text = dec.get('decision', '')[:100]
            reason_text = dec.get('reason', '')[:80]
            lines.append(f"🔒 **{dec_text}**")
            lines.append(f"   _Reason: {reason_text}_")
            lines.append("")
        hidden_count = len(decisions) - len(decisions_to_show) + superseded_count
        if hidden_count > 0:
            lines.append(f"_(...{hidden_count} more decisions. Use `get_policy_status()` for full list)_")
            lines.append("")
        lines.append("---")
        lines.append("")

        # Mark decisions as displayed for compliance tracking
        session = _get_session()
        session.mark_decisions_displayed()
        _sync_compliance()

        # Track ROI: decisions enforced this session (track once per init, not per decision)
        if len(decisions) > 0:
            _track_roi_event("decision_used")

    # PROJECT RULES - User-defined behavioral rules
    project_rules = data.get('project_rules', []) if data else []
    enabled_rules = [r for r in project_rules if r.get('enabled', True)]
    if enabled_rules:
        lines.append("---")
        lines.append("## 📋 PROJECT RULES - FOLLOW THESE")
        lines.append("")
        for rule in enabled_rules:
            text = rule.get('text', '')
            is_default = rule.get('default', False)
            marker = "📌" if is_default else "✏️"
            lines.append(f"{marker} {text}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # INSIGHTS - Check these BEFORE researching anything!
    # Use Memory Decay ranking to show most important insights
    insights = data.get('live_record', {}).get('lessons', {}).get('insights', []) if data else []
    if insights:
        # Get top 5 ranked insights (by importance, use_count, recency)
        top_insights = _get_ranked_insights(insights, limit=5)

        lines.append("---")
        lines.append("## 🧠 STORED INSIGHTS - CHECK BEFORE RESEARCHING")
        lines.append("")
        lines.append("**YOU ARE FORBIDDEN from external research if relevant insight exists below!**")
        lines.append("**If relevant → use it. If not → proceed with research.**")
        lines.append("")
        for ins in top_insights:
            text = ins.get('text', '')
            importance = ins.get('importance', 'medium')
            use_count = ins.get('use_count', 0)

            # Show importance indicator
            if importance == 'high':
                prefix = "🔥"  # Hot/important
            elif use_count > 0:
                prefix = "✓"   # Used before
            else:
                prefix = "💡"  # Regular

            lines.append(f"{prefix} {text}")

        if len(insights) > 5:
            lines.append(f"_...and {len(insights) - 5} more. Use `search_past_solutions()` to find specific ones._")
        lines.append("")
        lines.append("---")
        lines.append("")

    if snapshot.get('current_goal'):
        lines.append(f"**Last Goal:** {snapshot['current_goal']}")

    if snapshot.get('summary'):
        lines.append(f"**Architecture:** {snapshot['summary']}")

    if snapshot.get('last_insight'):
        lines.append(f"**Last Insight:** {snapshot['last_insight']}")

    # Show git status if available
    if snapshot.get('git_commit_hash'):
        lines.append(f"**Git:** `{snapshot['git_commit_hash']}`")

    # Multi-AI Handoff Summary
    ai_session = data.get("ai_session", {}) if data else {}
    previous_ai = ai_session.get("previous_ai")
    current_editor = ai_session.get("editor", "unknown")

    if previous_ai and previous_ai.get("editor") != current_editor:
        prev_editor = previous_ai.get("editor", "unknown").capitalize()
        prev_started = previous_ai.get("started_at", "")

        # Calculate time ago
        time_ago = ""
        if prev_started:
            try:
                started_dt = datetime.fromisoformat(prev_started.replace('Z', '+00:00'))
                diff = datetime.now() - started_dt.replace(tzinfo=None)
                mins = int(diff.total_seconds() // 60)
                if mins < 60:
                    time_ago = f"{mins} min"
                elif mins < 1440:
                    time_ago = f"{mins // 60}h"
                else:
                    time_ago = f"{mins // 1440}d"
            except:
                pass

        lines.append("")
        lines.append("---")
        lines.append(f"## 🔄 Handoff from {prev_editor}")
        if time_ago:
            lines.append(f"**{prev_editor}** worked here {time_ago} ago.")

        # Show recent activity from previous AI
        recent_activities = _get_recent_activities_for_handoff(prev_editor.lower(), limit=3)
        if recent_activities:
            lines.append("**Last actions:**")
            for act in recent_activities:
                lines.append(f"• {act}")
        lines.append("")

    # AI Queue - errors/tasks sent from dashboard
    ai_queue = data.get("ai_queue", []) if data else []
    pending_items = [q for q in ai_queue if q.get("status") == "pending"]

    # Separate action commands from regular items
    action_commands = [q for q in pending_items if q.get("type") == "action_command"]
    other_items = [q for q in pending_items if q.get("type") != "action_command"]

    # Show action commands first (user requested action from dashboard)
    if action_commands:
        lines.append("═══════════════════════════════════════")
        lines.append("## 🚀 ACTION REQUESTED FROM DASHBOARD")
        lines.append("═══════════════════════════════════════")
        lines.append("")
        lines.append("The user clicked an action button in the FixOnce dashboard.")
        lines.append("**Execute the following request:**")
        lines.append("")

        for cmd in action_commands[:1]:  # Show only the most recent command
            cmd_id = cmd.get("id", "unknown")
            msg = cmd.get("message", "")
            lines.append(f"**Command ID:** `{cmd_id}`")
            lines.append("```")
            lines.append(msg)
            lines.append("```")

        lines.append("")
        lines.append("**This is a HIGH PRIORITY request. Execute it now.**")
        lines.append("**After completing, call:** `mark_command_executed(command_id, result, details)`")
        lines.append("")

    # Show other queued items
    if other_items:
        lines.append("---")
        lines.append("## 🎯 QUEUED FOR YOU")
        for item in other_items[:3]:
            item_type = item.get("type", "task")
            msg = item.get("message", "")[:80]
            source = item.get("source", "")
            line_num = item.get("line", "")

            if item_type == "error":
                lines.append(f"⚠️ **Error:** `{msg}`")
                if source:
                    loc = source + (f":{line_num}" if line_num else "")
                    lines.append(f"   📍 {loc}")
            else:
                lines.append(f"📋 **Task:** {msg}")

        lines.append("")
        lines.append("**Fix these first, then mark as handled.**")
        lines.append("")

        # Mark items as delivered (old code used "shown", now using security layer status)
        now = datetime.now().isoformat()
        for item in pending_items[:3]:
            item["status"] = "delivered"
            item["delivered_at"] = now
            item["delivered_to"] = _detect_editor()
        _save_project(snapshot.get("project_id") or _get_project_id(working_dir), data)

    # Fix #3: Session State Visibility
    session = _get_session()
    if session and session.initialized_at:
        session_id = hashlib.md5(f"{session.project_id}_{session.initialized_at}".encode()).hexdigest()[:8]
        start_time = session.initialized_at[:19].replace('T', ' ')
        tools_count = len(session.tool_calls)
        lines.append(f"**Session:** `{session_id}` | Started: {start_time} | Tools: {tools_count}")

    # Resume State - show if there's pending work from last session
    if _resume_state_available:
        try:
            resume_state = _get_resume_state(project_id)
            if resume_state:
                resume_section = format_resume_for_init(resume_state)
                if resume_section:
                    lines.append("")
                    lines.append(resume_section)
        except Exception as e:
            _log(f"[FixOnce] Resume state error in snapshot: {e}")

    lines.append("")
    lines.append("_Ask: 'נמשיך מכאן?'_")

    # Add recent activity
    activity_info = _get_recent_activity_summary(working_dir, limit=5)
    if activity_info:
        lines.append("")
        lines.append(activity_info)

    # Add browser errors if any
    errors_info = _get_browser_errors_summary(limit=3)
    if errors_info:
        lines.append("")
        lines.append(errors_info)

    # Add AI Context injection if active and elements selected
    ai_context = _get_ai_context_injection()
    if ai_context:
        lines.append("")
        lines.append(ai_context)

    return '\n'.join(lines)


def _format_init_response(data: Dict[str, Any], status: str, working_dir: str) -> str:
    """Format init session response with structured resume_context."""
    project_name = data.get('project_info', {}).get('name', Path(working_dir).name)

    lines = []

    # BUILD STRUCTURED RESUME CONTEXT (if available)
    resume_context = None
    suggested_opening = None

    if _resume_context_available and status != "new":
        try:
            # Get git hash for checkpoint
            git_hash = None
            try:
                result = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=working_dir,
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    git_hash = result.stdout.strip()
            except:
                pass

            # Build structured context from real saved state
            resume_context = build_resume_context(data, working_dir, git_hash)

            # Build human-readable opening from that context
            suggested_opening = build_suggested_opening(resume_context, language='he')

            # Add structured JSON block at the beginning
            lines.append("<!-- RESUME_CONTEXT_START -->")
            lines.append("```json")
            context_output = {
                "resume_context": resume_context,
                "suggested_opening": suggested_opening
            }
            lines.append(json.dumps(context_output, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("<!-- RESUME_CONTEXT_END -->")
            lines.append("")

        except Exception as e:
            _log(f"[FixOnce] Resume context build error: {e}")

    # LIVE ERRORS FIRST (Universal Gate principle) + AUTO-INJECT SOLUTIONS
    live_errors = _get_live_errors()
    if live_errors:
        lines.append("═══════════════════════════════════════")
        lines.append(f"## ⚠️ {len(live_errors)} LIVE ERRORS - FIX BEFORE PROCEEDING")
        lines.append("═══════════════════════════════════════")

        solutions_found = 0
        injected_solutions = set()  # Prevent duplicates

        for e in live_errors[:3]:
            msg = e.get('message', 'Unknown error')
            msg_short = msg[:70] if len(msg) > 70 else msg
            lines.append(f"• {msg_short}")

            # Auto-Inject Solutions (with quality controls)
            solution = _find_solution_for_error(msg)
            if solution:
                solution_key = solution['text'][:50]
                if solution_key not in injected_solutions:
                    solutions_found += 1
                    injected_solutions.add(solution_key)
                    lines.append(f"  💡 **Solved before ({solution['similarity']}%):** {solution['text'][:100]}...")

        if len(live_errors) > 3:
            lines.append(f"• ...and {len(live_errors) - 3} more")

        if solutions_found > 0:
            lines.append("")
            lines.append(f"✅ **{solutions_found} known fix(es).** Apply them.")
        else:
            lines.append("")
            lines.append("**You MUST address these errors before doing anything else.**")
        lines.append("")

    # Project info
    lines.extend([
        f"## Project: {project_name}",
        f"**Status:** {status.upper()}",
        f"**Path:** `{working_dir}`",
        ""
    ])

    # Fix #3: Session State Visibility
    session = _get_session()
    if session and session.initialized_at:
        session_id = hashlib.md5(f"{session.project_id}_{session.initialized_at}".encode()).hexdigest()[:8]
        start_time = session.initialized_at[:19].replace('T', ' ')
        tools_count = len(session.tool_calls)
        lines.append(f"**Session:** `{session_id}` | Started: {start_time} | Tools: {tools_count}")
        lines.append("")

    # Resume State - show if there's pending work from last session
    if _resume_state_available:
        try:
            project_id = _get_project_id(working_dir)
            resume_state = _get_resume_state(project_id)
            if resume_state:
                resume_section = format_resume_for_init(resume_state)
                if resume_section:
                    lines.append(resume_section)
        except Exception as e:
            _log(f"[FixOnce] Resume state error: {e}")

    # Multi-AI Handoff Summary
    ai_session = data.get("ai_session", {})
    previous_ai = ai_session.get("previous_ai")
    current_editor = ai_session.get("editor", "unknown")

    if previous_ai and previous_ai.get("editor") != current_editor:
        prev_editor = previous_ai.get("editor", "unknown").capitalize()
        prev_started = previous_ai.get("started_at", "")

        # Calculate how long ago
        if prev_started:
            try:
                prev_time = datetime.fromisoformat(prev_started.replace('Z', '+00:00'))
                now = datetime.now()
                if prev_time.tzinfo:
                    now = datetime.now(prev_time.tzinfo)
                diff_mins = int((now - prev_time).total_seconds() / 60)

                if diff_mins < 60:
                    time_ago = f"{diff_mins} דקות"
                elif diff_mins < 1440:
                    time_ago = f"{diff_mins // 60} שעות"
                else:
                    time_ago = f"{diff_mins // 1440} ימים"

                lines.append("---")
                lines.append(f"## 🔄 Handoff from {prev_editor}")
                lines.append(f"**{prev_editor}** worked here {time_ago} ago.")
                lines.append("")

                # Show recent activity from that AI
                recent_activities = _get_recent_activities_for_handoff(prev_editor.lower(), limit=3)
                if recent_activities:
                    lines.append("**Last actions:**")
                    for act in recent_activities:
                        lines.append(f"• {act}")
                    lines.append("")
                lines.append("---")
                lines.append("")
            except:
                pass  # Skip handoff if timestamp parsing fails

    # AI Queue - errors/tasks/commands sent from dashboard
    # Security Layer: Session Scope Guard + Explicit Marker Lock
    ai_queue = data.get("ai_queue", [])
    pending_items = [q for q in ai_queue if q.get("status") == "pending"]

    # Get current session ID for scope validation
    current_project_id = _get_project_id(working_dir)
    current_session_id = hashlib.md5(
        f"{current_project_id}_{session.initialized_at}".encode()
    ).hexdigest()[:8] if session.initialized_at else None

    # Filter items by scope (Session Scope Guard)
    # Only show commands meant for this project/session
    valid_items = []
    skipped_items = []
    for item in pending_items:
        item_project = item.get("project_id")
        item_session = item.get("session_id")

        # Scope validation: skip if command is for different project
        if item_project and item_project != current_project_id:
            skipped_items.append(item)
            continue

        # Session validation: warn but still show if different session
        # (user might have restarted AI but command is still valid)
        if item_session and item_session != current_session_id:
            item["_session_mismatch"] = True

        valid_items.append(item)

    # Separate action commands from regular items
    action_commands = [q for q in valid_items if q.get("type") == "action_command"]
    other_items = [q for q in valid_items if q.get("type") != "action_command"]

    # Show action commands first (user requested action from dashboard)
    if action_commands:
        lines.append("═══════════════════════════════════════")
        lines.append("## 🚀 ACTION REQUESTED FROM DASHBOARD")
        lines.append("═══════════════════════════════════════")
        lines.append("")
        lines.append("The user clicked an action button in the FixOnce dashboard.")
        lines.append("**Execute the following request:**")
        lines.append("")

        for cmd in action_commands[:1]:  # Show only the most recent command
            cmd_id = cmd.get("id", "unknown")
            msg = cmd.get("message", "")
            session_warning = " ⚠️ (different session)" if cmd.get("_session_mismatch") else ""
            lines.append(f"**Command ID:** `{cmd_id}`{session_warning}")
            lines.append("```")
            lines.append(msg)
            lines.append("```")

        lines.append("")
        lines.append("**This is a HIGH PRIORITY request. Execute it now.**")
        lines.append("")

    # Show other queued items
    if other_items:
        lines.append("---")
        lines.append("## 🎯 QUEUED FOR YOU")
        for item in other_items[:3]:
            item_id = item.get("id", "")
            item_type = item.get("type", "task")
            msg = item.get("message", "")[:80]
            source = item.get("source", "")
            line_num = item.get("line", "")

            if item_type == "error":
                lines.append(f"⚠️ **Error** `[{item_id}]`: `{msg}`")
                if source:
                    loc = source + (f":{line_num}" if line_num else "")
                    lines.append(f"   📍 {loc}")
            else:
                lines.append(f"📋 **Task** `[{item_id}]`: {msg}")

        lines.append("")
        lines.append("**Fix these first, then mark as handled.**")
        lines.append("")

    # Mark valid items as delivered with full audit trail (Explicit Marker Lock)
    if valid_items:
        project_id = _get_project_id(working_dir)
        now = datetime.now().isoformat()
        detected_editor = _detect_editor()

        # Initialize audit log if needed
        if "command_audit" not in data:
            data["command_audit"] = []

        for item in valid_items:
            # Mark as delivered (one-time delivery)
            item["status"] = "delivered"
            item["delivered_at"] = now
            item["delivered_to"] = detected_editor

            # Add audit entry
            data["command_audit"].append({
                "id": item.get("id", "unknown"),
                "action": "delivered",
                "delivered_to": detected_editor,
                "timestamp": now,
                "session_id": current_session_id
            })

        # Keep audit log bounded
        data["command_audit"] = data["command_audit"][-50:]
        _save_project(project_id, data)

    # Log skipped items (wrong project scope)
    if skipped_items:
        lines.append(f"_(Skipped {len(skipped_items)} commands from other projects)_")
        lines.append("")

    if status == "new":
        # New project onboarding - bilingual, welcoming
        lines.append("---")
        lines.append("## 🆕 New Project")
        lines.append("")
        lines.append("**FixOnce is now connected to this project.**")
        lines.append("")
        lines.append("From now on, I will remember:")
        lines.append("- 🔒 **Decisions** — architectural choices and their reasons")
        lines.append("- 💡 **Insights** — what we learned during development")
        lines.append("- ⚠️ **Avoid patterns** — mistakes we shouldn't repeat")
        lines.append("- 🐛 **Solutions** — how we fixed errors")
        lines.append("")
        lines.append("This knowledge persists across sessions, so we never lose context.")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("**Want me to scan the project?** I can detect the tech stack and structure.")
        lines.append("")
        lines.append("_Just say: 'scan' or 'סרוק'_")
        lines.append("")
    else:
        # Show existing context
        lr = data.get('live_record', {})

        # DECISIONS FIRST - Most important for respecting past choices
        all_decisions = data.get('decisions', [])
        # Filter out superseded decisions - only show active ones
        decisions = [d for d in all_decisions if not d.get('superseded')]
        superseded_count = len(all_decisions) - len(decisions)

        if decisions:
            lines.append("---")
            lines.append("## 🚨 ACTIVE DECISIONS - YOU MUST RESPECT THESE")
            lines.append("")
            lines.append("**STOP before any change that contradicts these decisions!**")
            lines.append("**Ask user for explicit override approval if request conflicts.**")
            lines.append("")
            # MCP DIET: Limit to 8 most recent decisions
            MAX_DECISIONS = 8
            decisions_to_show = decisions[-MAX_DECISIONS:]
            for dec in decisions_to_show:
                # Truncate long decisions
                dec_text = dec.get('decision', '')[:100]
                reason_text = dec.get('reason', '')[:80]
                lines.append(f"🔒 **{dec_text}**")
                lines.append(f"   _Reason: {reason_text}_")
                lines.append("")
            hidden_count = len(decisions) - len(decisions_to_show) + superseded_count
            if hidden_count > 0:
                lines.append(f"_(...{hidden_count} more decisions. Use `get_policy_status()` for full list)_")
                lines.append("")
            lines.append("---")
            lines.append("")

            # Mark decisions as displayed for compliance tracking
            session = _get_session()
            session.mark_decisions_displayed()
            _sync_compliance()

        # PROJECT RULES - User-defined behavioral rules
        project_rules = data.get('project_rules', [])
        enabled_rules = [r for r in project_rules if r.get('enabled', True)]
        if enabled_rules:
            lines.append("---")
            lines.append("## 📋 PROJECT RULES - FOLLOW THESE")
            lines.append("")
            for rule in enabled_rules:
                text = rule.get('text', '')
                is_default = rule.get('default', False)
                marker = "📌" if is_default else "✏️"
                lines.append(f"{marker} {text}")
            lines.append("")
            lines.append("---")
            lines.append("")

        # INSIGHTS - Check these BEFORE researching anything!
        # Use Memory Decay ranking to show most important insights
        insights = lr.get('lessons', {}).get('insights', [])
        if insights:
            # Get top 5 ranked insights (by importance, use_count, recency)
            top_insights = _get_ranked_insights(insights, limit=5)

            lines.append("---")
            lines.append("## 🧠 STORED INSIGHTS - CHECK BEFORE RESEARCHING")
            lines.append("")
            lines.append("**YOU ARE FORBIDDEN from external research if relevant insight exists below!**")
            lines.append("**If relevant → use it. If not → proceed with research.**")
            lines.append("")
            for ins in top_insights:
                text = ins.get('text', '')
                importance = ins.get('importance', 'medium')
                use_count = ins.get('use_count', 0)

                # Show importance indicator
                if importance == 'high':
                    prefix = "🔥"  # Hot/important
                elif use_count > 0:
                    prefix = "✓"   # Used before
                else:
                    prefix = "💡"  # Regular

                lines.append(f"{prefix} {text}")

            if len(insights) > 5:
                lines.append(f"_...and {len(insights) - 5} more. Use `search_past_solutions()` to find specific ones._")
            lines.append("")
            lines.append("---")
            lines.append("")

        intent = lr.get('intent', {})
        if intent.get('current_goal'):
            lines.append(f"**Last Goal:** {intent['current_goal']}")

        arch = lr.get('architecture', {})
        if arch.get('summary'):
            lines.append(f"**Architecture:** {arch['summary']}")

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

    # Add browser errors if any
    errors_info = _get_browser_errors_summary(limit=3)
    if errors_info:
        lines.append("")
        lines.append(errors_info)

    # Add AI Context injection if active and elements selected
    ai_context = _get_ai_context_injection()
    if ai_context:
        lines.append("")
        lines.append(ai_context)

    return '\n'.join(lines)


@mcp.tool()
def init_session(working_dir: str = "", port: int = 0) -> str:
    """
    Initialize FixOnce session for the current project.

    Phase 1: Uses boundary detection to find actual project root.

    Args:
        working_dir: The absolute path to the project directory (use cwd)
        port: OR a port number - will auto-detect the working directory from it

    Returns:
        Session info with project_status ('new' or 'existing')
    """
    mode = _get_fixonce_mode()
    if mode == MODE_OFF:
        return "FixOnce is off. Proceed normally without FixOnce tools."
    if mode == MODE_PASSIVE:
        return "FixOnce is in PASSIVE mode. Session initialization is disabled."

    # If port given, detect working_dir from it
    if port and not working_dir:
        detected = _get_working_dir_from_port(port)
        if detected:
            working_dir = detected
        else:
            return f"Error: Could not detect project directory from port {port}. Is a server running?"

    # Phase 1: Use boundary detection to find actual project root
    if BOUNDARY_DETECTION_ENABLED and working_dir and os.path.isdir(working_dir):
        project_root, marker, confidence = find_project_root(working_dir)
        if project_root and confidence in ("high", "medium"):
            # Use the detected project root instead of raw working_dir
            _log(f"[MCP] init_session: {working_dir} → {project_root} ({confidence})")
            working_dir = project_root

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
    session = _get_session()
    if not session.is_active():
        return "Error: No active session. Call init_session() first."

    working_dir = session.working_dir

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
                lines.append("**README preview:**")
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

    For 'intent', use: {"current_goal": "...", "work_area": "...", "why": "...", "last_change": "...", "last_file": "..."}
    - current_goal: What we're currently working on
    - work_area: Feature/module area (e.g., "session resume / opening UX")
    - why: Why this work matters
    - last_change: Description of the most recent change
    - last_file: Last file that was worked on
    - next_step: What should be done next

    For other sections, data REPLACES the section.
    """
    error, context = _universal_gate("update_live_record")
    if error:
        return error

    session = _get_session()
    # Track goal updates for compliance
    if section == 'intent':
        session.mark_goal_updated()
        _sync_compliance()

    try:
        update_data = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError:
        return f"Error: Invalid JSON: {data}"

    project_id = session.project_id
    memory = _load_project(project_id)

    if 'live_record' not in memory:
        memory['live_record'] = {}

    lr = memory['live_record']

    # PRE-ACTION INTELLIGENCE: Track any warnings
    pre_action_warning = ""

    if section == 'lessons':
        # APPEND mode with Memory Decay tracking
        if 'lessons' not in lr:
            lr['lessons'] = {'insights': [], 'failed_attempts': [], 'archived': []}

        if 'insight' in update_data:
            # PRE-ACTION: Check for similar existing insights
            new_text = update_data['insight'].lower()
            for existing in lr['lessons'].get('insights', []):
                existing_text = _normalize_insight(existing).get('text', '').lower()
                # Check for significant word overlap
                new_words = set(new_text.split())
                existing_words = set(existing_text.split())
                overlap = new_words & existing_words - {'the', 'a', 'is', 'in', 'to', 'and', 'of'}
                if len(overlap) >= 4:  # At least 4 meaningful words in common
                    pre_action_warning = f"\n💡 **Similar insight exists:** {existing_text[:50]}..."
                    break

            # Fix #2: Auto-Link Incidents - check for active errors
            active_errors = _get_live_errors()
            linked_error = active_errors[0] if active_errors else None

            # Create insight with full decay metadata (+ linked error if exists)
            new_insight = _create_insight(update_data['insight'], linked_error=linked_error)
            lr['lessons']['insights'].append(new_insight)

            # Auto-index for semantic search
            if _semantic_available:
                try:
                    index_insight(project_id, update_data['insight'])
                except Exception as e:
                    _log(f"[SemanticIndex] Failed to index insight: {e}")

            # Fix #2: Notify about the link
            if linked_error:
                pre_action_warning += f"\n🔗 **Auto-linked to error:** {linked_error.get('message', '')[:50]}..."

        if 'failed_attempt' in update_data:
            # Failed attempts also get metadata - marked as type to prevent decay
            new_attempt = _create_insight(update_data['failed_attempt'])
            new_attempt['type'] = 'failed_attempt'  # Will NEVER be archived
            lr['lessons']['failed_attempts'].append(new_attempt)
    elif section == 'intent':
        # INTENT mode - track goal history
        if 'intent' not in lr:
            lr['intent'] = {}

        # POLICY ENFORCEMENT: Check for blocked components when setting new goal
        new_goal = update_data.get('current_goal', '')
        if new_goal and _policy_available:
            components = lr.get('architecture', {}).get('components', [])
            blocked_relevant = check_blocked_components(new_goal, components)
            if blocked_relevant:
                blocked_names = [b['name'] for b in blocked_relevant]
                pre_action_warning += f"\n⚠️ **BLOCKED COMPONENTS MAY AFFECT THIS GOAL:**\n"
                for b in blocked_relevant:
                    pre_action_warning += f"  🔴 **{b['name']}**: {b.get('desc', '')[:50]}\n"
                pre_action_warning += "Consider unblocking these first, or adjust the goal."

        # Save previous goal to history before replacing
        old_goal = lr['intent'].get('current_goal', '')
        if old_goal and old_goal != update_data.get('current_goal', ''):
            if 'goal_history' not in lr['intent']:
                lr['intent']['goal_history'] = []
            lr['intent']['goal_history'].insert(0, {
                'goal': old_goal,
                'completed_at': datetime.now().isoformat()
            })
            # Keep only last 5 goals
            lr['intent']['goal_history'] = lr['intent']['goal_history'][:5]

        # Update intent with new data
        lr['intent'].update(update_data)
        # Always update timestamp when intent changes
        lr['intent']['updated_at'] = datetime.now().isoformat()
    else:
        # REPLACE mode for other sections
        if section not in lr:
            lr[section] = {}
        lr[section].update(update_data)

    lr['updated_at'] = datetime.now().isoformat()
    _save_project(project_id, memory)

    # Log MCP activity for dashboard
    _log_mcp_activity("update_live_record", {
        "section": section,
        "goal": update_data.get("current_goal", "") if section == "intent" else "",
        "insight": update_data.get("insight", "")[:50] if section == "lessons" else "",
        "failed_attempt": bool(update_data.get("failed_attempt")) if section == "lessons" else False
    })

    # Add browser errors reminder if any
    reminder = _get_browser_errors_reminder()

    # ALWAYS prepend context header (shows live errors!)
    return context + f"Updated {section}{pre_action_warning}{reminder}"


@mcp.tool()
def update_work_context(
    current_goal: str = "",
    work_area: str = "",
    why: str = "",
    last_change: str = "",
    last_file: str = "",
    next_step: str = ""
) -> str:
    """
    Update work context for better session continuity.

    This tool updates the structured context that appears in opening messages.
    Call this when starting new work or after completing a significant change.

    Args:
        current_goal: What you're currently working on (e.g., "Improve opening UX")
        work_area: Feature/module area (e.g., "session resume / opening UX")
        why: Why this work matters (e.g., "Users should feel the AI remembers them")
        last_change: What was just done (e.g., "Added work_area field to opening message")
        last_file: Last file worked on (e.g., "CLAUDE.md")
        next_step: What should be done next (e.g., "Test with real session")

    At minimum, update current_goal when starting new work.
    Update last_change and last_file after completing changes.
    """
    error, context = _universal_gate("update_work_context")
    if error:
        return error

    session = _get_session()

    # Build update data from non-empty fields
    update_data = {}
    if current_goal:
        update_data['current_goal'] = current_goal
    if work_area:
        update_data['work_area'] = work_area
    if why:
        update_data['why'] = why
    if last_change:
        update_data['last_change'] = last_change
    if last_file:
        update_data['last_file'] = last_file
    if next_step:
        update_data['next_step'] = next_step

    if not update_data:
        return context + "Error: No fields provided to update"

    # Update the intent section
    project_id = session.project_id
    memory = _load_project(project_id)

    if 'live_record' not in memory:
        memory['live_record'] = {}
    if 'intent' not in memory['live_record']:
        memory['live_record']['intent'] = {}

    # Track goal updates for compliance
    if current_goal:
        session.mark_goal_updated()
        _sync_compliance()

    memory['live_record']['intent'].update(update_data)
    memory['live_record']['intent']['updated_at'] = datetime.now().isoformat()
    memory['live_record']['updated_at'] = datetime.now().isoformat()

    _save_project(project_id, memory)

    # Log activity
    _log_mcp_activity("update_work_context", update_data)

    # Format response
    updated_fields = list(update_data.keys())
    return context + f"Updated work context: {', '.join(updated_fields)}"


@mcp.tool()
def sync_to_active_project() -> str:
    """
    Sync this AI to the currently active project.

    Use this when:
    - You're in Cursor but want to join the project Claude is working on
    - You opened the wrong folder but want to work on the active FixOnce project
    - You want to enable Multi-AI collaboration

    This will:
    1. Find the active project from FixOnce dashboard
    2. Initialize session for that project
    3. Show handoff info from previous AI (if different)

    Returns:
        Session info for the active project with handoff summary
    """
    try:
        from core.boundary_detector import _load_active_project
        active = _load_active_project()
        active_working_dir = active.get("working_dir")
        active_id = active.get("active_id")

        if not active_working_dir or not os.path.isdir(active_working_dir):
            return """❌ No active project found.

Use the FixOnce dashboard to select a project first,
or call init_session(working_dir="/path/to/project")"""

        # Get current editor
        detected_editor = _detect_editor()

        # Log the sync
        _log(f"[MCP] Multi-AI Sync: {detected_editor} joining project at {active_working_dir}")

        # Initialize with the active project
        return _do_init_session(active_working_dir)

    except Exception as e:
        return f"❌ Sync failed: {str(e)}"


@mcp.tool()
def get_live_record() -> str:
    """Get the current Live Record (summarized to save tokens)."""
    error, context = _universal_gate("get_live_record")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)
    lr = memory.get('live_record', {})

    # === MCP DIET v2: Aggressive but smart summarization ===

    # 1. Components: Only show non-stable/non-done (these need attention)
    all_components = lr.get("architecture", {}).get("components", [])
    STABLE_STATUSES = {"stable", "done"}
    active_components = [
        {"name": c.get("name"), "status": c.get("status")}
        for c in all_components
        if c.get("status") not in STABLE_STATUSES
    ]
    stable_count = len(all_components) - len(active_components)

    # 2. Insights: Strip metadata, keep only text and linked_error
    all_insights = lr.get("lessons", {}).get("insights", [])
    recent_insights = [
        {"text": ins.get("text")} | ({"linked_error": ins["linked_error"]} if ins.get("linked_error") else {})
        for ins in all_insights[-5:]
    ]

    # 3. Failed attempts: Same treatment
    all_failed = lr.get("lessons", {}).get("failed_attempts", [])
    recent_failed = [{"text": f.get("text")} for f in all_failed[-3:]]

    # 4. Intent: Limit goal_history to 3
    intent = lr.get("intent", {}).copy()
    if "goal_history" in intent:
        intent["goal_history"] = intent["goal_history"][-3:]

    summarized = {
        "gps": lr.get("gps", {}),
        "intent": intent,
        "architecture": {
            "summary": lr.get("architecture", {}).get("summary", ""),
            "stack": lr.get("architecture", {}).get("stack", ""),
            "components": active_components,
            "stable_count": stable_count
        },
        "lessons": {
            "insights": {"recent": recent_insights, "total": len(all_insights)},
            "failed_attempts": {"recent": recent_failed, "total": len(all_failed)}
        }
    }

    # Context header + summarized data
    return context + json.dumps(summarized, indent=2, ensure_ascii=False)


@mcp.tool()
def log_decision(decision: str, reason: str, force: bool = False) -> str:
    """
    Log an architectural decision. Decisions NEVER decay - they are permanent.

    Args:
        decision: The decision text
        reason: Why this decision was made
        force: If True, override conflict detection and log anyway

    Returns:
        Success message or BLOCK message if conflict detected
    """
    error, context = _universal_gate("log_decision")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    if 'decisions' not in memory:
        memory['decisions'] = []

    # POLICY ENFORCEMENT: Check for conflicts
    policy_message = ""
    if _policy_available:
        # Filter to active decisions only for validation
        active_decisions = [d for d in memory['decisions'] if not d.get('superseded')]
        is_valid, message, conflicts = validate_decision(
            decision, reason, active_decisions, force=force
        )

        _log(f"[PolicyEngine] Validating: {decision[:50]}...")
        _log(f"[PolicyEngine] Against {len(active_decisions)} active decisions")
        _log(f"[PolicyEngine] Result: is_valid={is_valid}, conflicts={len(conflicts)}")

        if not is_valid:
            # BLOCK the decision - return error
            return context + f"\n{message}\n\nDecision NOT logged."

        if conflicts:
            policy_message = f"\n{message}"

    else:
        # Fallback: simple word overlap check
        decision_lower = decision.lower()
        for existing in memory['decisions']:
            if existing.get("superseded"):
                continue
            existing_text = existing.get('decision', '').lower()
            decision_words = set(decision_lower.split())
            existing_words = set(existing_text.split())
            overlap = decision_words & existing_words
            if len(overlap) >= 3:
                policy_message = f"\n⚠️ **Similar decision exists:** {existing.get('decision', '')[:60]}..."
                break

    # Log the decision
    memory['decisions'].append({
        "type": "decision",
        "decision": decision,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "importance": "permanent",
        "forced": force if force else None
    })

    _save_project(session.project_id, memory)

    # Log MCP activity for dashboard
    _log_mcp_activity("log_decision", {
        "decision": decision[:50],
        "reason": reason[:50],
        "forced": force
    })

    # Auto-index for semantic search
    if _semantic_available:
        try:
            index_decision(session.project_id, decision, reason)
        except Exception as e:
            _log(f"[SemanticIndex] Failed to index decision: {e}")

    return context + f"Logged decision: {decision}" + policy_message


@mcp.tool()
def log_avoid(what: str, reason: str) -> str:
    """Log something to avoid. Avoid patterns NEVER decay - they are permanent."""
    error, context = _universal_gate("log_avoid")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    if 'avoid' not in memory:
        memory['avoid'] = []

    memory['avoid'].append({
        "type": "avoid",  # Marked as avoid - will NEVER be archived
        "what": what,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "importance": "permanent"  # Avoid patterns never decay
    })

    _save_project(session.project_id, memory)

    # Log MCP activity for dashboard
    _log_mcp_activity("log_avoid", {
        "what": what[:50],
        "reason": reason[:50]
    })

    # Auto-index for semantic search
    if _semantic_available:
        try:
            index_avoid(session.project_id, what, reason)
        except Exception as e:
            _log(f"[SemanticIndex] Failed to index avoid: {e}")

    return context + f"Logged avoid: {what}"


@mcp.tool()
def supersede_decision(
    old_decision: str,
    new_decision: str = "",
    new_reason: str = "",
    supersede_reason: str = ""
) -> str:
    """
    Supersede (replace) an existing decision with a new one.

    Use this when:
    - A previous decision was wrong or outdated
    - Requirements changed and old decision no longer applies
    - You need to resolve a policy conflict

    Args:
        old_decision: Text of the decision to supersede (partial match OK)
        new_decision: The new decision (optional - leave empty to just deprecate)
        new_reason: Reason for the new decision
        supersede_reason: Why the old decision is being superseded

    Returns:
        Success message or error if decision not found
    """
    error, context = _universal_gate("supersede_decision")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    if 'decisions' not in memory or not memory['decisions']:
        return context + "No decisions found to supersede."

    if not _policy_available:
        return context + "Policy engine not available. Cannot supersede decisions."

    success, message, updated_decisions = do_supersede(
        memory['decisions'],
        old_decision,
        new_decision,
        new_reason,
        supersede_reason or "Superseded via MCP tool"
    )

    if not success:
        return context + f"❌ {message}"

    memory['decisions'] = updated_decisions
    _save_project(session.project_id, memory)

    # Log MCP activity
    _log_mcp_activity("supersede_decision", {
        "old": old_decision[:30],
        "new": new_decision[:30] if new_decision else "(deprecated)"
    })

    result = f"✅ {message}"
    if new_decision:
        result += f"\n📝 New decision: {new_decision}"

    return context + result


@mcp.tool()
def get_policy_status() -> str:
    """
    Get current policy status including active decisions, conflicts, and blocked components.

    Returns summary of:
    - Active vs superseded decisions
    - Blocked components that need attention
    - Any detected policy issues
    """
    error, context = _universal_gate("get_policy_status")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    decisions = memory.get('decisions', [])
    components = memory.get('live_record', {}).get('architecture', {}).get('components', [])

    if _policy_available:
        status = format_policy_status(decisions, components)
    else:
        active = [d for d in decisions if not d.get('superseded')]
        superseded = [d for d in decisions if d.get('superseded')]
        blocked = [c for c in components if c.get('status') == 'blocked']

        status = f"## Policy Status\n\n"
        status += f"**Active Decisions:** {len(active)}\n"
        status += f"**Superseded:** {len(superseded)}\n"
        status += f"**Blocked Components:** {len(blocked)}"

        if blocked:
            status += "\n\n### ⚠️ Blocked Components\n"
            for comp in blocked:
                status += f"- **{comp.get('name')}**: {comp.get('desc', 'No description')}\n"

    return context + status


@mcp.tool()
def update_component_status(name: str, status: str, desc: str = "") -> str:
    """
    Update a component's status in the System Tree.

    Use this at the end of tasks to reflect progress:
    - When you finish implementing something → status="done"
    - When you start working on something → status="in_progress"
    - When something is blocked → status="blocked"
    - When something is planned but not started → status="not_started"

    If the component doesn't exist, it will be created.

    Args:
        name: Component name (e.g., "Policy Engine", "Dashboard")
        status: One of: "done", "in_progress", "not_started", "blocked"
        desc: Optional description update
    """
    error, context = _universal_gate("update_component_status")
    if error:
        return error

    valid_statuses = ["done", "in_progress", "not_started", "blocked"]
    if status not in valid_statuses:
        return f"❌ Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"

    session = _get_session()
    memory = _load_project(session.project_id)
    actor_identity = _resolve_actor_identity()

    # Ensure live_record and architecture exist
    if 'live_record' not in memory:
        memory['live_record'] = {}
    if 'architecture' not in memory['live_record']:
        memory['live_record']['architecture'] = {"components": [], "key_flows": [], "summary": "", "stack": ""}

    arch = memory['live_record']['architecture']
    if 'components' not in arch:
        arch['components'] = []

    components = arch['components']

    # Find existing component or create new one
    found = False
    for comp in components:
        if comp.get('name', '').lower() == name.lower():
            old_status = comp.get('status', 'unknown')
            comp['status'] = status
            if desc:
                comp['desc'] = desc
            comp['updated_at'] = datetime.now().isoformat()
            comp['updated_by'] = actor_identity.get("editor", "unknown")
            comp['update_source'] = actor_identity.get("source", "fallback")
            found = True
            action = f"Updated '{name}': {old_status} → {status}"
            break

    if not found:
        # Create new component
        new_comp = {
            "name": name,
            "status": status,
            "desc": desc or f"Added by AI",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "updated_by": actor_identity.get("editor", "unknown"),
            "update_source": actor_identity.get("source", "fallback"),
        }
        components.append(new_comp)
        action = f"Created '{name}' with status: {status}"

    # Keep max 30 components (newest ones if over limit)
    if len(components) > 30:
        arch['components'] = components[-30:]
    else:
        arch['components'] = components
    arch['updated_at'] = datetime.now().isoformat()

    _save_project(session.project_id, memory)

    # Log MCP activity for dashboard
    _log_mcp_activity("update_component_status", {
        "name": name,
        "status": status
    })

    # Status icons for display
    icons = {"done": "🟢", "in_progress": "🟡", "not_started": "⚪", "blocked": "🔴",
             "stable": "🟢", "building": "🟡", "broken": "🔴"}
    icon = icons.get(status, "⚪")

    return context + f"{icon} {action}"


@mcp.tool()
def mark_component_stable(name: str, files: str = "") -> str:
    """
    Mark a component as STABLE and create a checkpoint for rollback.

    This records the current git commit as the "last known good" state.
    If the component breaks later, you can rollback to this checkpoint.

    Args:
        name: Component name (e.g., "API Server", "Dashboard")
        files: Comma-separated list of files belonging to this component (optional)
               Example: "src/api/server.py,src/api/routes.py"

    Returns:
        Confirmation with commit hash
    """
    error, context = _universal_gate("mark_component_stable")
    if error:
        return error

    from core.component_stability import (
        mark_component_stable as do_mark_stable,
        add_files_to_component,
        get_current_commit
    )

    session = _get_session()
    memory = _load_project(session.project_id)
    actor_identity = _resolve_actor_identity()

    # Get project path for git operations
    gps = memory.get("live_record", {}).get("gps", {})
    repo_path = gps.get("working_dir", "")

    if not repo_path:
        return context + "[ERROR] No project path. Run auto_init_session first."

    # Find component
    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    found_idx = None
    for i, comp in enumerate(components):
        if comp.get("name", "").lower() == name.lower():
            found_idx = i
            break

    if found_idx is None:
        return context + f"[ERROR] Component '{name}' not found. Create it first with update_component_status."

    component = components[found_idx]

    # Add files if provided
    if files:
        file_list = [f.strip() for f in files.split(",") if f.strip()]
        component = add_files_to_component(component, file_list)

    # Mark as stable and record commit
    marked_by = actor_identity.get("editor", "unknown")
    component = do_mark_stable(component, repo_path, marked_by)

    # Save back
    components[found_idx] = component
    arch["components"] = components
    arch["updated_at"] = datetime.now().isoformat()
    memory["live_record"]["architecture"] = arch
    _save_project(session.project_id, memory)

    # Log activity
    _log_mcp_activity("mark_component_stable", {"name": name})

    # Build response
    last_stable = component.get("last_stable", {})
    commit_short = last_stable.get("commit_short", "unknown")
    file_count = len(component.get("files", []))

    result = f"[STABLE] {name} marked as stable\n"
    result += f"Checkpoint: {commit_short}\n"
    if file_count > 0:
        result += f"Files tracked: {file_count}\n"
    result += "You can now rollback to this state if needed."

    return context + result


@mcp.tool()
def rollback_component(name: str, mode: str = "files") -> str:
    """
    Rollback a component to its last stable state.

    Two modes available:
    - "files": Restore specific files to their stable state (default)
    - "branch": Create a new branch from the stable commit

    Args:
        name: Component name to rollback
        mode: "files" (restore files) or "branch" (create rollback branch)

    Returns:
        Result of rollback operation
    """
    error, context = _universal_gate("rollback_component")
    if error:
        return error

    from core.component_stability import (
        rollback_files,
        create_rollback_branch
    )

    session = _get_session()
    memory = _load_project(session.project_id)

    # Get project path
    gps = memory.get("live_record", {}).get("gps", {})
    repo_path = gps.get("working_dir", "")

    if not repo_path:
        return context + "[ERROR] No project path. Run auto_init_session first."

    # Find component
    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    component = None
    for comp in components:
        if comp.get("name", "").lower() == name.lower():
            component = comp
            break

    if not component:
        return context + f"[ERROR] Component '{name}' not found."

    # Check if has stable checkpoint
    last_stable = component.get("last_stable")
    if not last_stable:
        return context + f"[ERROR] No stable checkpoint for '{name}'. Mark it stable first."

    commit_hash = last_stable.get("commit_hash")
    if not commit_hash:
        return context + f"[ERROR] Invalid checkpoint for '{name}'."

    # Perform rollback based on mode
    if mode == "branch":
        result = create_rollback_branch(repo_path, commit_hash)
        if result["success"]:
            return context + f"[OK] Created rollback branch: {result['branch']}\nFrom commit: {commit_hash[:8]}"
        else:
            return context + f"[ERROR] Failed to create branch: {result.get('error', 'Unknown error')}"

    else:  # files mode
        files = component.get("files", [])
        if not files:
            return context + f"[ERROR] No files tracked for '{name}'. Add files with mark_component_stable first."

        result = rollback_files(repo_path, commit_hash, files)

        if result["success"]:
            restored_count = len(result["restored"])
            return context + f"[OK] Restored {restored_count} files to stable state\nCommit: {commit_hash[:8]}\nFiles: {', '.join(result['restored'][:5])}{'...' if restored_count > 5 else ''}"
        else:
            error_msgs = [e["error"] for e in result["errors"][:3]]
            return context + f"[ERROR] Rollback failed:\n" + "\n".join(error_msgs)


@mcp.tool()
def check_component_changes(name: str) -> str:
    """
    Check if a stable component has been modified since its checkpoint.

    Use this before AI modifies a stable component to warn the user.

    Args:
        name: Component name to check

    Returns:
        Status: unchanged, modified (with list of changed files), or no checkpoint
    """
    error, context = _universal_gate("check_component_changes")
    if error:
        return error

    from core.component_stability import check_component_stability

    session = _get_session()
    memory = _load_project(session.project_id)

    # Get project path
    gps = memory.get("live_record", {}).get("gps", {})
    repo_path = gps.get("working_dir", "")

    # Find component
    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    component = None
    for comp in components:
        if comp.get("name", "").lower() == name.lower():
            component = comp
            break

    if not component:
        return context + f"[ERROR] Component '{name}' not found."

    if not component.get("last_stable"):
        return context + f"[INFO] '{name}' has no stable checkpoint. Nothing to compare."

    result = check_component_stability(component, repo_path)

    if not result["is_stable"]:
        return context + f"[INFO] '{name}' is not marked as stable (status: {component.get('status', 'unknown')})"

    if result["modified_since_checkpoint"]:
        changed = result["changed_files"]
        msg = f"[WARNING] '{name}' has been modified since stable checkpoint!\n"
        msg += f"Changed files ({len(changed)}):\n"
        for f in changed[:10]:
            msg += f"  - {f}\n"
        if len(changed) > 10:
            msg += f"  ... and {len(changed) - 10} more\n"
        msg += "\nYou can rollback with: rollback_component(\"{name}\")"
        return context + msg

    return context + f"[OK] '{name}' is stable and unchanged since checkpoint."


@mcp.tool()
def add_component_files(name: str, files: str) -> str:
    """
    Add files to a component's tracked file list.

    These files will be restored when you rollback the component.

    Args:
        name: Component name
        files: Comma-separated list of file paths
               Example: "src/api/server.py,src/api/routes.py"

    Returns:
        Updated file list
    """
    error, context = _universal_gate("add_component_files")
    if error:
        return error

    from core.component_stability import add_files_to_component

    session = _get_session()
    memory = _load_project(session.project_id)

    # Find component
    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    found_idx = None
    for i, comp in enumerate(components):
        if comp.get("name", "").lower() == name.lower():
            found_idx = i
            break

    if found_idx is None:
        return context + f"[ERROR] Component '{name}' not found."

    # Parse and add files
    file_list = [f.strip() for f in files.split(",") if f.strip()]
    if not file_list:
        return context + "[ERROR] No valid files provided."

    component = components[found_idx]
    component = add_files_to_component(component, file_list)
    component["updated_at"] = datetime.now().isoformat()

    # Save
    components[found_idx] = component
    arch["components"] = components
    memory["live_record"]["architecture"] = arch
    _save_project(session.project_id, memory)

    all_files = component.get("files", [])
    return context + f"[OK] Added {len(file_list)} files to '{name}'\nTotal tracked: {len(all_files)}"


@mcp.tool()
def get_stability_report() -> str:
    """
    Get a summary of component stability across the project.

    Shows:
    - How many components are stable/building/broken
    - Which have checkpoints (can rollback)
    - Which track files

    Returns:
        Stability report
    """
    error, context = _universal_gate("get_stability_report")
    if error:
        return error

    from core.component_stability import get_stability_summary

    session = _get_session()
    memory = _load_project(session.project_id)

    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    if not components:
        return context + "[INFO] No components defined yet."

    summary = get_stability_summary(components)

    report = "## Component Stability Report\n\n"
    report += f"Total components: {summary['total']}\n"
    report += f"  Stable: {summary['stable']}\n"
    report += f"  Building: {summary['building']}\n"
    report += f"  Broken: {summary['broken']}\n"
    report += f"\nWith checkpoints (can rollback): {summary['with_checkpoints']}\n"
    report += f"With file tracking: {summary['with_files']}\n"

    # List components with their status
    report += "\n### Components:\n"
    icons = {"stable": "[OK]", "done": "[OK]", "building": "[...]", "in_progress": "[...]",
             "broken": "[X]", "blocked": "[X]", "not_started": "[ ]"}

    for comp in components:
        status = comp.get("status", "building")
        icon = icons.get(status, "[ ]")
        name = comp.get("name", "Unknown")
        has_checkpoint = "[checkpoint]" if comp.get("last_stable") else ""
        file_count = len(comp.get("files", []))
        files_info = f"[{file_count} files]" if file_count > 0 else ""

        report += f"  {icon} {name} {has_checkpoint} {files_info}\n"

    return context + report


@mcp.tool()
def auto_discover_components(apply: bool = False) -> str:
    """
    Automatically discover components from the codebase.

    Scans the project's source code and identifies:
    - API modules and blueprints
    - Major classes (Managers, Engines, Providers)
    - Extension files
    - Dashboard files

    Args:
        apply: If True, add discovered components to the System Tree

    Returns:
        List of discovered components with suggestions
    """
    error, context = _universal_gate("auto_discover_components")
    if error:
        return error

    try:
        from core.auto_discovery import suggest_components

        session = _get_session()
        memory = _load_project(session.project_id)

        # Get project path
        gps = memory.get("live_record", {}).get("gps", {})
        project_path = gps.get("working_dir", "")

        if not project_path:
            return context + "❌ No project path found. Run auto_init_session first."

        # Get existing components
        existing = memory.get("live_record", {}).get("architecture", {}).get("components", [])

        # Run discovery
        result = suggest_components(project_path, existing)

        if "error" in result:
            return context + f"❌ {result['error']}"

        suggestions = result.get("suggestions", [])

        if not suggestions:
            return context + f"✅ No new components found. All {len(existing)} components are up to date."

        # Apply if requested
        if apply:
            arch = memory.setdefault("live_record", {}).setdefault("architecture", {})
            components = arch.setdefault("components", [])

            for suggestion in suggestions:
                new_comp = {
                    "name": suggestion["name"],
                    "status": suggestion.get("suggested_status", "done"),
                    "desc": suggestion.get("suggested_desc", "Auto-discovered"),
                    "source": suggestion.get("source", ""),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "auto_discovered": True
                }
                components.append(new_comp)

            arch["updated_at"] = datetime.now().isoformat()
            _save_project(session.project_id, memory)

            _log_mcp_activity("auto_discover_components", {
                "added": len(suggestions),
                "applied": True
            })

            return context + f"✅ Added {len(suggestions)} components:\n" + "\n".join(
                f"  🟢 {s['name']} ({s.get('source', 'unknown')})" for s in suggestions
            )

        # Just show suggestions
        lines = [f"🔍 Found {len(suggestions)} new components:\n"]
        for s in suggestions:
            conf = "⭐" if s.get("confidence") == "high" else "○"
            lines.append(f"  {conf} {s['name']} - {s.get('source', 'unknown')}")

        lines.append(f"\nRun with apply=True to add them to the System Tree.")

        return context + "\n".join(lines)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return context + f"❌ Error: {e}"


@mcp.tool()
def get_latest_changes() -> str:
    """
    Get the latest changes - unified source of truth.

    Returns canonical "latest change" using this priority:
    1. Activity feed (file edits < 10 min)
    2. Git commit (< 30 min)
    3. Current goal (fallback)

    Use this when user asks "what's the latest change" or "what happened recently".
    """
    error, context = _universal_gate("get_latest_changes")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id) if session.project_id else {}
    now = datetime.now()

    result = {
        "latest_activity": None,
        "latest_git": None,
        "latest_goal": None,
        "canonical": None
    }

    # 1. Check activity log
    try:
        activity_file = DATA_DIR / "activity_log.json"
        if activity_file.exists():
            with open(activity_file, 'r', encoding='utf-8') as f:
                activity_data = json.load(f)
            activities = activity_data.get("activities", [])
            if activities:
                latest = activities[-1]
                result["latest_activity"] = {
                    "file": latest.get("human_name") or latest.get("file"),
                    "tool": latest.get("tool"),
                    "timestamp": latest.get("timestamp"),
                    "actor": latest.get("editor", "unknown")
                }
    except:
        pass

    # 2. Check git
    try:
        working_dir = memory.get("project_info", {}).get("working_dir")
        if working_dir and Path(working_dir).exists():
            import subprocess
            git_result = subprocess.run(
                ["git", "log", "-1", "--format=%s|%ai"],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            if git_result.returncode == 0 and git_result.stdout.strip():
                parts = git_result.stdout.strip().split("|")
                if len(parts) >= 2:
                    result["latest_git"] = {
                        "message": parts[0],
                        "timestamp": parts[1]
                    }
    except:
        pass

    # 3. Get current goal
    intent = memory.get("live_record", {}).get("intent", {})
    result["latest_goal"] = intent.get("current_goal")

    # Determine canonical latest
    canonical_text = None
    canonical_source = None

    # Priority 1: Activity (< 10 min)
    if result["latest_activity"]:
        try:
            act_ts = result["latest_activity"]["timestamp"]
            act_dt = datetime.fromisoformat(act_ts.replace('Z', ''))
            if (now - act_dt).total_seconds() < 600:
                canonical_text = f"נערך {result['latest_activity']['file']}"
                canonical_source = "activity"
        except:
            pass

    # Priority 2: Git (< 30 min)
    if not canonical_text and result["latest_git"]:
        try:
            git_ts = result["latest_git"]["timestamp"]
            git_dt = datetime.strptime(git_ts.split()[0] + " " + git_ts.split()[1], "%Y-%m-%d %H:%M:%S")
            if (now - git_dt).total_seconds() < 1800:
                canonical_text = f"commit: {result['latest_git']['message'][:50]}"
                canonical_source = "git"
        except:
            pass

    # Priority 3: Goal (fallback)
    if not canonical_text and result["latest_goal"]:
        canonical_text = f"מטרה: {result['latest_goal']}"
        canonical_source = "intent"

    if not canonical_text:
        canonical_text = "אין פעילות אחרונה"
        canonical_source = "none"

    result["canonical"] = {
        "text": canonical_text,
        "source": canonical_source
    }

    # Format output
    output = f"""📊 Latest Changes (Unified):

🎯 Canonical: {canonical_text}
   (source: {canonical_source})

📝 Activity: {result['latest_activity']['file'] if result['latest_activity'] else 'None'}
🔀 Git: {result['latest_git']['message'][:40] if result['latest_git'] else 'None'}
🎯 Goal: {result['latest_goal'] or 'None'}
"""
    return context + output


@mcp.tool()
def log_debug_session(
    problem: str,
    root_cause: str,
    solution: str,
    files_changed: str = "",
    symptoms: str = ""
) -> str:
    """
    Log a completed debug session. Use this when:
    1. There was a REAL problem (not just a question)
    2. There was a debugging PROCESS (investigation, trial/error)
    3. There is a CLEAR solution (not just "it works now")
    4. Files were CHANGED to fix it

    This creates a structured problem→solution record that prevents
    repeating the same debugging session in the future.

    Args:
        problem: Short description of the problem (e.g., "Cursor לא מזהה MCP tools")
        root_cause: The actual cause found (e.g., "Cursor requires project folder to be open")
        solution: What fixed it (e.g., "Open project folder, start new chat")
        files_changed: Comma-separated list of files that were modified
        symptoms: Comma-separated list of error messages/symptoms seen
    """
    error, context = _universal_gate("log_debug_session")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    # Initialize debug_sessions if needed
    if 'debug_sessions' not in memory:
        memory['debug_sessions'] = []

    # Parse comma-separated strings to lists
    files_list = [f.strip() for f in files_changed.split(",") if f.strip()] if files_changed else []
    symptoms_list = [s.strip() for s in symptoms.split(",") if s.strip()] if symptoms else []

    # Create debug session
    debug_session = {
        "id": f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "problem": problem,
        "root_cause": root_cause,
        "solution": solution,
        "symptoms": symptoms_list,
        "files_changed": files_list,
        "resolved_at": datetime.now().isoformat(),
        "importance": "high"  # Debug sessions are always important
    }

    # Check for duplicate/similar debug sessions
    problem_lower = problem.lower()
    for existing in memory['debug_sessions']:
        existing_problem = existing.get('problem', '').lower()
        # Simple word overlap check
        problem_words = set(problem_lower.split())
        existing_words = set(existing_problem.split())
        overlap = problem_words & existing_words
        if len(overlap) >= 3:
            return context + f"⚠️ Similar debug session already exists: '{existing.get('problem', '')[:50]}...'\nNot creating duplicate."

    memory['debug_sessions'].append(debug_session)

    # Mark related insights as consolidated (optional cleanup)
    # Find insights from today that might be related
    today = datetime.now().strftime('%Y-%m-%d')
    consolidated_count = 0
    if 'live_record' in memory and 'lessons' in memory['live_record']:
        insights = memory['live_record']['lessons'].get('insights', [])
        for i, insight in enumerate(insights):
            if isinstance(insight, dict):
                insight_time = insight.get('timestamp', '')
                insight_text = insight.get('text', '').lower()
                # Check if insight is from today and related to this debug session
                if today in insight_time:
                    # Check word overlap with problem or solution
                    insight_words = set(insight_text.split())
                    problem_words = set(problem_lower.split())
                    solution_words = set(solution.lower().split())
                    if len(insight_words & problem_words) >= 2 or len(insight_words & solution_words) >= 2:
                        insight['consolidated_into'] = debug_session['id']
                        consolidated_count += 1

    _save_project(session.project_id, memory)

    result = f"""✅ Debug session logged!

🐛 **Problem:** {problem}
🎯 **Root cause:** {root_cause}
✅ **Solution:** {solution}
📁 **Files:** {', '.join(files_list) if files_list else 'None specified'}
"""
    if consolidated_count > 0:
        result += f"\n📦 Consolidated {consolidated_count} related insights into this session."

    return context + result


@mcp.tool()
def solution_applied(
    error_message: str,
    solution: str,
    files_changed: str = ""
) -> str:
    """
    Quick way to record that you fixed an error.

    Call this AFTER you fix a browser error or bug. This creates a
    solution record that will be:
    1. Stored in project memory
    2. Committed to .fixonce/solutions.json
    3. Surfaced next time a similar error appears

    This is simpler than log_debug_session() - use this for quick fixes.

    Args:
        error_message: The error message you just fixed (copy from browser errors)
        solution: What you did to fix it (1-2 sentences)
        files_changed: Comma-separated list of files you modified

    Example:
        solution_applied(
            "Cannot read property 'map' of undefined",
            "Added null check before mapping the array",
            "src/components/List.tsx"
        )
    """
    error, context = _universal_gate("solution_applied")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    # Initialize debug_sessions if needed
    if 'debug_sessions' not in memory:
        memory['debug_sessions'] = []

    # Parse files
    files_list = [f.strip() for f in files_changed.split(",") if f.strip()] if files_changed else []

    # Create solution record (same structure as debug_session for compatibility)
    solution_record = {
        "id": f"fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "problem": error_message[:200],  # Truncate long errors
        "root_cause": "",  # Not required for quick fixes
        "solution": solution,
        "symptoms": [error_message[:100]],  # Use error as symptom for matching
        "files_changed": files_list,
        "resolved_at": datetime.now().isoformat(),
        "importance": "high",  # All fixes are important
        "reuse_count": 0
    }

    # Check for duplicate (same error already solved)
    error_lower = error_message.lower()[:100]
    for existing in memory['debug_sessions']:
        existing_problem = existing.get('problem', '').lower()[:100]
        if error_lower in existing_problem or existing_problem in error_lower:
            # Update reuse_count instead of creating duplicate
            existing['reuse_count'] = existing.get('reuse_count', 0) + 1
            existing['solution'] = solution  # Update with latest solution
            existing['files_changed'] = files_list or existing.get('files_changed', [])
            _save_project(session.project_id, memory)
            return context + f"✅ Updated existing solution (reused {existing['reuse_count']} times)"

    memory['debug_sessions'].append(solution_record)
    _save_project(session.project_id, memory)

    # Track ROI
    _track_roi_event("solution_saved")

    return context + f"""✅ Solution recorded!

🐛 **Error:** {error_message[:80]}{'...' if len(error_message) > 80 else ''}
✅ **Fix:** {solution}
📁 **Files:** {', '.join(files_list) if files_list else 'None specified'}

This solution will be suggested next time a similar error appears.
Run `Commit Knowledge` to save it to Git."""


def _calculate_similarity(query: str, text: str) -> int:
    """Calculate simple word-based similarity percentage."""
    query_words = set(query.lower().split())
    text_words = set(text.lower().split())
    if not query_words:
        return 0
    matches = len(query_words & text_words)
    return min(100, int((matches / len(query_words)) * 100))


def _find_solution_for_error(error_message: str, min_similarity: int = 50, min_keyword_matches: int = 2) -> Optional[dict]:
    """
    Auto-find a matching solution for an error message.

    This is the core of Fix #1: Auto-Inject Solutions.
    When an error is detected, automatically search for existing solutions.

    Quality controls:
    - Requires minimum 2 keyword matches to avoid false positives
    - Higher similarity threshold (50%) for better precision

    Args:
        error_message: The error message to search for
        min_similarity: Minimum similarity % to consider a match (default 50)
        min_keyword_matches: Minimum keyword matches required (default 2)

    Returns:
        Dict with solution info if found, None otherwise
    """
    session = _get_session()
    if not session or not session.project_id:
        return None

    try:
        memory = _load_project(session.project_id)
        if not memory:
            return None

        lessons = memory.get('live_record', {}).get('lessons', {})
        insights = lessons.get('insights', [])

        if not insights:
            return None

        # Extract keywords from error message (remove common noise)
        error_lower = error_message.lower()
        noise_words = {'error', 'failed', 'cannot', 'undefined', 'null', 'is', 'not',
                       'the', 'a', 'an', 'to', 'of', 'in', 'at', 'on', 'for', 'with',
                       'file', 'found', 'could', 'was', 'been', 'has', 'have', 'from'}
        error_words = set(error_lower.split()) - noise_words

        best_match = None
        best_score = 0
        best_keyword_matches = 0

        for insight in insights:
            normalized = _normalize_insight(insight)
            text = normalized.get('text', '').lower()

            # Calculate similarity
            similarity = _calculate_similarity(error_message, text)

            # Count keyword matches (quality gate #1: avoid false positives)
            text_words = set(text.split())
            keyword_matches = len(error_words & text_words)

            # Skip if not enough keyword matches
            if keyword_matches < min_keyword_matches:
                continue

            bonus = keyword_matches * 10
            total_score = similarity + bonus

            if total_score > best_score and total_score >= min_similarity:
                best_score = total_score
                use_count = normalized.get('use_count', 0)
                timestamp = normalized.get('timestamp', '')
                linked_error = normalized.get('linked_error')

                best_match = {
                    'text': normalized.get('text', ''),
                    'similarity': min(100, total_score),
                    'confidence': min(95, 50 + (use_count * 10)),
                    'date': timestamp[:10] if timestamp else 'unknown',
                    'use_count': use_count,
                    'linked_error': linked_error  # Fix #2: Include linked error info
                }

        # Also search debug_sessions (solutions) - these are higher quality
        debug_sessions = memory.get('debug_sessions', [])
        for session in debug_sessions:
            problem = session.get('problem', '').lower()
            solution = session.get('solution', '')
            symptoms = [s.lower() for s in session.get('symptoms', [])]

            # Check keyword matches in problem
            problem_words = set(problem.split()) - noise_words
            keyword_matches = len(error_words & problem_words)

            # Also check symptoms
            symptom_match = any(s in error_lower for s in symptoms if s)

            if keyword_matches >= min_keyword_matches or symptom_match:
                similarity = _calculate_similarity(error_message, problem)
                bonus = keyword_matches * 15  # Higher bonus for debug sessions
                if symptom_match:
                    bonus += 20
                total_score = similarity + bonus

                if total_score > best_score and total_score >= min_similarity:
                    best_score = total_score
                    best_match = {
                        'text': f"Problem: {session.get('problem', '')}\nSolution: {solution}",
                        'similarity': min(100, total_score),
                        'confidence': 90,  # High confidence for debug sessions
                        'date': session.get('resolved_at', '')[:10] if session.get('resolved_at') else 'unknown',
                        'use_count': session.get('reuse_count', 1),
                        'source': 'debug_session',
                        'files_changed': session.get('files_changed', [])
                    }

        return best_match

    except Exception:
        return None


def _format_smart_override(insight: dict, query: str) -> dict:
    """Format insight as Smart Override with metadata."""
    text = insight.get('text', '')
    timestamp = insight.get('timestamp', insight.get('last_used', ''))
    use_count = insight.get('use_count', 0)

    # Calculate confidence based on use_count and recency
    confidence = min(95, 50 + (use_count * 10))
    similarity = _calculate_similarity(query, text)

    # Extract date
    date_str = timestamp[:10] if timestamp else "unknown"

    return {
        "text": text,
        "confidence": confidence,
        "similarity": similarity,
        "date": date_str,
        "use_count": use_count
    }


@mcp.tool()
def search_past_solutions(query: str) -> str:
    """Search for past solutions matching the query."""
    error, context = _universal_gate("search_past_solutions")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    # Search in lessons
    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    failed = lessons.get('failed_attempts', [])

    query_lower = query.lower()
    matches = []
    matched_insights = []
    matched_indices = []

    # === SEMANTIC SEARCH (if available) ===
    semantic_results = []
    if _semantic_available:
        try:
            semantic_results = search_project(session.project_id, query, k=5, min_score=0.3)
            _log(f"[SemanticSearch] Found {len(semantic_results)} results for '{query}'")
        except Exception as e:
            _log(f"[SemanticSearch] Error: {e}, falling back to string match")
            semantic_results = []

    # If semantic search found results, use them
    if semantic_results:
        for result in semantic_results:
            # Find the original insight to update use count
            for i, insight in enumerate(insights):
                normalized = _normalize_insight(insight)
                if normalized.get('text', '') == result.text:
                    override = _format_smart_override(normalized, query)
                    # Add semantic score
                    override['similarity'] = int(result.score * 100)
                    matched_insights.append(override)
                    matched_indices.append(i)
                    _mark_insight_used(normalized)
                    insights[i] = normalized
                    break
            else:
                # Result from index but not in current insights (decision/avoid)
                matched_insights.append({
                    'text': result.text,
                    'confidence': 80,
                    'similarity': int(result.score * 100),
                    'date': result.metadata.get('created_at', 'unknown')[:10],
                    'use_count': 0,
                    'type': result.metadata.get('doc_type', 'insight')
                })

    # === FALLBACK: String matching (if no semantic results) ===
    if not matched_insights:
        for i, insight in enumerate(insights):
            normalized = _normalize_insight(insight)
            insight_text = normalized.get('text', '')

            if query_lower in insight_text.lower():
                override = _format_smart_override(normalized, query)
                matched_insights.append(override)
                matched_indices.append(i)
                _mark_insight_used(normalized)
                insights[i] = normalized

    # Search failed attempts (always string match)
    for attempt in failed:
        normalized = _normalize_insight(attempt)
        attempt_text = normalized.get('text', '')

        if query_lower in attempt_text.lower():
            matches.append(f"❌ Failed attempt: {attempt_text}")

    # === CRITICAL: Search debug_sessions (solutions from solution_applied) ===
    debug_sessions = memory.get('debug_sessions', [])
    noise_words = {'error', 'failed', 'cannot', 'undefined', 'null', 'is', 'not',
                   'the', 'a', 'an', 'to', 'of', 'in', 'at', 'on', 'for', 'with',
                   'file', 'found', 'could', 'was', 'been', 'has', 'have', 'from'}
    query_words = set(query_lower.split()) - noise_words

    for ds in debug_sessions:
        problem = ds.get('problem', '').lower()
        solution = ds.get('solution', '')
        symptoms = [s.lower() for s in ds.get('symptoms', [])]

        # Check for keyword matches
        problem_words = set(problem.split()) - noise_words
        keyword_matches = len(query_words & problem_words)

        # Also check symptoms
        symptom_match = any(s in query_lower for s in symptoms if s)

        # Match if enough keyword overlap or symptom match
        if keyword_matches >= 2 or symptom_match or query_lower in problem:
            similarity = _calculate_similarity(query, problem)
            matched_insights.append({
                'text': f"🐛 **Problem:** {ds.get('problem', '')}\n✅ **Solution:** {solution}",
                'confidence': 90,
                'similarity': max(similarity, 70 if symptom_match else 50),
                'date': ds.get('resolved_at', '')[:10] if ds.get('resolved_at') else 'unknown',
                'use_count': ds.get('reuse_count', 1),
                'type': 'solution',
                'files_changed': ds.get('files_changed', [])
            })
            # Update reuse count
            ds['reuse_count'] = ds.get('reuse_count', 0) + 1

    # Save updated use counts
    if matched_indices:
        _save_project(session.project_id, memory)

    # Log MCP activity for dashboard
    _log_mcp_activity("search_past_solutions", {
        "query": query[:30],
        "found": len(matched_insights) + len(matches)
    })

    if matched_insights:
        _track_roi_event("solution_reused")

        # Build Smart Override Header
        lines = [context]
        lines.append("## 🎯 EXISTING SOLUTION FOUND\n")

        search_method = "🔍 Semantic" if semantic_results else "📝 Keyword"
        lines.append(f"_Search method: {search_method}_\n")

        for i, m in enumerate(matched_insights[:3]):  # Top 3
            lines.append(f"### Match #{i+1}")
            lines.append(f"**Confidence:** {m['confidence']}%")
            lines.append(f"**Similarity:** {m['similarity']}%")
            lines.append(f"**Date:** {m['date']}")
            lines.append(f"**Used:** {m.get('use_count', 0)} times")
            if m.get('type') and m['type'] != 'insight':
                lines.append(f"**Type:** {m['type']}")
            lines.append(f"\n> {m['text']}\n")

        lines.append("---")
        lines.append("**📌 Recommended:** Apply existing solution.")
        lines.append("**💡 Override:** Only investigate if this doesn't match your case.")

        if matches:
            lines.append("\n### Also found (failed attempts):")
            lines.extend(matches)

        return '\n'.join(lines)

    elif matches:
        return context + "## Found (failed attempts only):\n" + '\n'.join(matches)

    else:
        return context + "No matching solutions found. You may investigate."


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
    session = _get_session()
    activity_file = SRC_DIR.parent / "data" / "activity_log.json"

    if not activity_file.exists():
        return "No activity log found."

    try:
        with open(activity_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        all_activities = data.get('activities', [])

        if not all_activities:
            return "No recent activity."

        # Filter to current project only if session active
        working_dir = session.working_dir if session.is_active() else ""

        if working_dir:
            # Only show activities from current project
            project_activities = []
            for act in all_activities:
                file_path = act.get('file') or ''
                cwd = act.get('cwd') or ''
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


@mcp.tool()
def rebuild_semantic_index() -> str:
    """
    Rebuild semantic search index from existing project memory.

    Use this when:
    - First time enabling semantic search on existing project
    - Index seems out of sync
    - After model upgrade

    Returns:
        Stats about the rebuild
    """
    error, context = _universal_gate("rebuild_semantic_index")
    if error:
        return error

    if not _semantic_available:
        return context + "❌ Semantic search not available. Install fastembed: pip install fastembed"

    session = _get_session()

    try:
        result = rebuild_project_index(session.project_id)
        if result.get('status') == 'ok':
            return context + f"""## ✅ Semantic Index Rebuilt

**Project:** {result.get('project_id')}
**Documents indexed:** {result.get('documents_indexed')}

Index is now ready for semantic search."""
        else:
            return context + f"❌ Rebuild failed: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return context + f"❌ Error rebuilding index: {e}"


@mcp.tool()
def get_browser_errors(limit: int = 10) -> str:
    """
    Get recent browser errors captured by the FixOnce Chrome extension.

    These are JavaScript errors, network errors, and console errors from
    the user's browser. Use this to proactively help fix frontend issues.

    Args:
        limit: Max number of errors to return (default 10)

    Returns:
        Recent browser errors with messages, sources, and timestamps
    """
    error, _ = _universal_gate("get_browser_errors")
    if error:
        return error

    try:
        # Try to fetch from the dashboard API
        res = requests.get('http://localhost:5000/api/live-errors', timeout=3)
        if res.status_code != 200:
            return "No browser errors available (dashboard not running or no errors)."

        data = res.json()
        errors = data.get('errors', [])

        if not errors:
            return "No browser errors captured."

        # Track ROI: errors caught in real-time
        _track_roi_event("error_caught_live")

        lines = ["## Browser Errors (from Chrome Extension)\n"]
        lines.append("These errors were captured from the user's browser:\n")

        solutions_found = 0
        injected_solutions = set()  # Quality gate #2: prevent duplicate injections

        for err in errors[:limit]:
            msg = err.get('message', err.get('error', 'Unknown error'))
            source = err.get('source', err.get('url', 'Unknown source'))
            timestamp = err.get('timestamp', '')[:16].replace('T', ' ')
            line_no = err.get('lineno', err.get('line', ''))
            col_no = err.get('colno', err.get('column', ''))

            # Format source
            source_short = source.split('/')[-1] if '/' in source else source
            if source_short and len(source_short) > 40:
                source_short = source_short[:40] + '...'

            location = f":{line_no}" if line_no else ""
            if col_no:
                location += f":{col_no}"

            lines.append(f"### Error in {source_short}{location}")
            lines.append(f"**Message:** {msg}")
            if timestamp:
                lines.append(f"**Time:** {timestamp}")

            # 🔥 FIX #1: Auto-Inject Solutions (with quality controls)
            solution = _find_solution_for_error(msg)
            if solution:
                solution_key = solution['text'][:50]  # Use first 50 chars as key

                # Quality gate #2: Don't inject same solution twice
                if solution_key not in injected_solutions:
                    solutions_found += 1
                    injected_solutions.add(solution_key)
                    _track_roi_event("solution_reused")
                    lines.append(f"\n**💡 This was solved before ({solution['similarity']}% match):**")
                    lines.append(f"> {solution['text'][:200]}{'...' if len(solution['text']) > 200 else ''}")
                    lines.append(f"_Applied {solution['use_count']} times_")
                else:
                    lines.append(f"\n_💡 Same solution as above_")
            lines.append("")

        if solutions_found > 0:
            lines.append(f"\n✅ **{solutions_found} known fix(es) found.** Apply them.")
        else:
            lines.append("\n_No existing solutions. Fix and save with `update_live_record()`._")

        return '\n'.join(lines)

    except requests.exceptions.RequestException:
        return "Could not connect to dashboard. Make sure FixOnce server is running on port 5000."
    except Exception as e:
        return f"Error fetching browser errors: {e}"


@mcp.tool()
def get_browser_context() -> str:
    """
    Get the element user selected in browser + recent errors.

    Use this when the user says "this element", "the button", "fix this",
    or refers to something visible in their browser.

    The user selects elements using the FixOnce Chrome extension's
    "Select Element" feature.

    Returns:
        Selected element with HTML, CSS, and selector path + recent errors
    """
    # v1: Feature disabled - AI Context Mode is planned for v2
    return "AI Context Mode is disabled in v1. This feature will be available in a future version."

    error, _ = _universal_gate("get_browser_context")
    if error:
        return error

    try:
        res = requests.get('http://localhost:5000/api/browser-context', timeout=3)
        if res.status_code != 200:
            return "No browser context available."

        data = res.json()
        selected = data.get('selected_element')
        errors = data.get('recent_errors', [])

        lines = ["## Browser Context\n"]

        if selected:
            # Handle both 'element' (old) and 'elements' (new array format)
            elements = selected.get('elements', [])
            el = elements[0] if elements else selected.get('element', {})

            if not el:
                lines.append("_No element data._")
            else:
                lines.append("### 🎯 Selected Element\n")
                lines.append(f"**Selector:** `{el.get('selector', 'N/A')}`")
                lines.append(f"**Tag:** `{el.get('tagName', 'N/A')}`")

                if el.get('id'):
                    lines.append(f"**ID:** `{el.get('id')}`")
                if el.get('classes'):
                    lines.append(f"**Classes:** `{' '.join(el.get('classes', []))}`")

                lines.append(f"\n**HTML:**\n```html\n{el.get('html', '')[:500]}\n```")

                css = el.get('css', {})
                if css:
                    lines.append("\n**Key CSS Properties:**")
                    for prop, value in list(css.items())[:8]:
                        lines.append(f"- `{prop}`: `{value}`")

                rect = el.get('rect', {})
                if rect:
                    lines.append(f"\n**Dimensions:** {rect.get('width', 0)}x{rect.get('height', 0)}px")

                # Get URL from element or parent
                url = el.get('url') or selected.get('url', 'N/A')
                timestamp = el.get('timestamp') or selected.get('timestamp', '')
                selector = el.get('selector', '')
                lines.append(f"\n**Page URL:** {url}")
                lines.append(f"**Captured:** {timestamp[:16].replace('T', ' ') if timestamp else 'N/A'}")

                # Auto-confirm selection with a short, visibility-guarded ack.
                # This keeps immediate UX feedback while avoiding stale highlights
                # when the UI changed (e.g., modal already closed).
                if selector:
                    selection_key = f"{selector}|{timestamp or ''}"
                    last_key = getattr(get_browser_context, "_last_auto_highlight_key", "")

                    is_fresh = True
                    if timestamp:
                        try:
                            ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                            age_sec = (datetime.now(ts.tzinfo) - ts).total_seconds()
                            is_fresh = age_sec <= 5
                        except Exception:
                            is_fresh = True

                    if selection_key != last_key and is_fresh:
                        try:
                            requests.post(
                                'http://localhost:5000/api/highlight-element',
                                json={
                                    "selector": selector,
                                    "message": "Selection received",
                                    "mode": "ack",
                                    "duration_ms": 900,
                                    "require_visible": True,
                                    "allow_context_open": False
                                },
                                timeout=2
                            )
                            setattr(get_browser_context, "_last_auto_highlight_key", selection_key)
                        except Exception:
                            pass
        else:
            lines.append("_No element selected. User can click 'Select Element' in FixOnce extension._")

        if errors:
            lines.append("\n### 🔴 Recent Errors\n")
            for err in errors[:5]:
                lines.append(f"- **{err.get('type', 'error')}:** {err.get('message', '')[:100]}")
        else:
            lines.append("\n_No recent browser errors._")

        return '\n'.join(lines)

    except requests.exceptions.RequestException:
        return "Could not connect to dashboard. Make sure FixOnce server is running."
    except Exception as e:
        return f"Error fetching browser context: {e}"


@mcp.tool()
def highlight_element(selector: str, message: str = "", mode: str = "ack", duration_ms: int = 0) -> str:
    """
    Highlight an element in the user's browser.

    Use this to point to or track work on an element in the user's browser.

    Args:
        selector: CSS selector for the element (e.g., "#submit-btn", ".error-message")
        message: Short message to show in tooltip (max 100 chars)
        mode: One of: ack, working, done, clear
        duration_ms: Optional custom duration in milliseconds

    Returns:
        Confirmation that highlight was queued
    """
    # v1: Feature disabled - AI Context Mode is planned for v2
    return "AI Context Mode is disabled in v1. This feature will be available in a future version."

    error, _ = _universal_gate("highlight_element")
    if error:
        return error

    try:
        res = requests.post(
            'http://localhost:5000/api/highlight-element',
            json={
                "selector": selector,
                "message": message[:100] if message else "",
                "mode": mode,
                "duration_ms": max(0, int(duration_ms or 0))
            },
            timeout=3
        )
        if res.status_code == 200:
            suffix = f" ({mode})" if mode else ""
            return f"✨ Highlighting{suffix} `{selector}` with message: '{message}'" if message else f"✨ Highlighting{suffix} `{selector}`"
        else:
            return f"Failed to queue highlight: {res.text}"

    except requests.exceptions.RequestException:
        return "Could not connect to dashboard. Make sure FixOnce server is running."
    except Exception as e:
        return f"Error highlighting element: {e}"


@mcp.tool()
def get_protocol_compliance() -> str:
    """
    Get current protocol compliance status.

    Use this to check if you're following FixOnce protocol correctly.
    Returns status of: session init, decisions display, goal updates.
    """
    session = _get_session()
    score_data = session.get_compliance_score()
    score = score_data["score"]

    # Score bar visualization
    filled = score // 10
    empty = 10 - filled
    bar = "█" * filled + "░" * empty

    lines = [f"## Protocol Compliance: {bar} {score}%\n"]

    # Rules checklist
    for rule in score_data["rules"]:
        icon = "✅" if rule["passed"] else ("❌" if rule["required"] else "⚠️")
        req = " (required)" if rule["required"] else ""
        lines.append(f"{icon} {rule['name']}{req}")

    # Tool calls
    lines.append(f"\n📊 Tool calls this session: {score_data['tool_calls']}")

    # Violations
    if _compliance_state["violations"]:
        lines.append("\n### ⚠️ Recent Violations:")
        for v in _compliance_state["violations"][-5:]:
            lines.append(f"- {v['type']}: {v['tool']} at {v['timestamp']}")

    return '\n'.join(lines)


@mcp.tool()
def run_memory_cleanup() -> str:
    """
    Run memory decay cleanup - archive old/unused insights.

    This tool:
    - Archives low-importance insights not used in 60+ days
    - Archives never-used low-importance insights older than 30 days
    - Shows memory statistics

    PROTECTED (never archived):
    - Decisions (log_decision) - permanent institutional knowledge
    - Avoid patterns (log_avoid) - permanent warnings
    - Failed attempts - prevent repeating mistakes
    - High-importance insights

    Run this periodically to keep memory clean and relevant.
    """
    error = _require_session("run_memory_cleanup")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    archived = lessons.get('archived', [])

    if not insights:
        return "No insights to process."

    # Normalize all insights
    normalized = [_normalize_insight(ins) for ins in insights]

    # Separate active from archived
    still_active = []
    newly_archived = []

    for ins in normalized:
        if _should_archive_insight(ins):
            newly_archived.append(ins)
        else:
            still_active.append(ins)

    # Update memory
    lessons['insights'] = still_active
    lessons['archived'] = archived + newly_archived
    memory['live_record']['lessons'] = lessons

    _save_project(session.project_id, memory)

    # Build stats report
    lines = ["## Memory Cleanup Report\n"]

    # Show protected items count
    decisions_count = len(memory.get('decisions', []))
    avoid_count = len(memory.get('avoid', []))
    failed_count = len(lessons.get('failed_attempts', []))

    lines.append("### 🔒 Protected (Never Archived)")
    lines.append(f"- **Decisions:** {decisions_count}")
    lines.append(f"- **Avoid Patterns:** {avoid_count}")
    lines.append(f"- **Failed Attempts:** {failed_count}")
    lines.append("")

    lines.append("### 📊 Insights")
    lines.append(f"**Active:** {len(still_active)}")
    lines.append(f"**Newly Archived:** {len(newly_archived)}")
    lines.append(f"**Total Archived:** {len(lessons['archived'])}")

    if newly_archived:
        lines.append("\n### Archived Insights:")
        for ins in newly_archived[:5]:
            text = ins.get('text', '')[:50]
            lines.append(f"- {text}...")

    # Show top insights by importance
    if still_active:
        lines.append("\n### Top Active Insights:")
        top = _get_ranked_insights(still_active, limit=3)
        for ins in top:
            text = ins.get('text', '')[:50]
            importance = ins.get('importance', 'medium')
            use_count = ins.get('use_count', 0)
            lines.append(f"- 🔥 [{importance}] (used {use_count}x) {text}...")

    return '\n'.join(lines)


@mcp.tool()
def get_memory_stats() -> str:
    """
    Get memory statistics for the current project.

    Shows:
    - Total insights (active vs archived)
    - Importance distribution
    - Usage statistics
    - Recommendations for cleanup
    """
    error = _require_session("get_memory_stats")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    archived = lessons.get('archived', [])
    failed = lessons.get('failed_attempts', [])
    decisions = memory.get('decisions', [])

    lines = ["## Memory Statistics\n"]

    # Totals
    lines.append(f"**Active Insights:** {len(insights)}")
    lines.append(f"**Archived Insights:** {len(archived)}")
    lines.append(f"**Failed Attempts:** {len(failed)}")
    lines.append(f"**Decisions:** {len(decisions)}")

    if insights:
        # Normalize for stats
        normalized = [_normalize_insight(ins) for ins in insights]

        # Importance distribution
        high = sum(1 for i in normalized if i.get('importance') == 'high')
        medium = sum(1 for i in normalized if i.get('importance') == 'medium')
        low = sum(1 for i in normalized if i.get('importance') == 'low')

        lines.append(f"\n**Importance Distribution:**")
        lines.append(f"- 🔥 High: {high}")
        lines.append(f"- 💡 Medium: {medium}")
        lines.append(f"- ⚪ Low: {low}")

        # Usage stats
        used = sum(1 for i in normalized if i.get('use_count', 0) > 0)
        never_used = len(normalized) - used
        total_uses = sum(i.get('use_count', 0) for i in normalized)

        lines.append(f"\n**Usage Statistics:**")
        lines.append(f"- Used at least once: {used}")
        lines.append(f"- Never used: {never_used}")
        lines.append(f"- Total usage count: {total_uses}")

        # Recommendations
        lines.append(f"\n**Recommendations:**")
        if never_used > 10:
            lines.append(f"⚠️ {never_used} insights never used - consider running `run_memory_cleanup()`")
        if len(insights) > 50:
            lines.append(f"⚠️ Memory growing large ({len(insights)} insights) - consider cleanup")
        if never_used == 0 and len(insights) < 50:
            lines.append("✅ Memory is healthy - no action needed")

    return '\n'.join(lines)


@mcp.tool()
def get_impact_stats() -> str:
    """
    Get FixOnce impact statistics.

    Shows how FixOnce is saving time:
    - Time saved (estimated minutes)
    - Solutions reused (vs debugging from scratch)
    - Decisions applied (preventing wrong direction)
    - Errors prevented (avoid patterns)
    - Sessions with context (handover continuity)

    Use this to report impact to the user.
    """
    try:
        res = requests.get('http://localhost:5000/api/memory/roi', timeout=3)
        if res.status_code != 200:
            return "Could not fetch impact stats"

        roi = res.json()

        time_saved = roi.get('time_saved_minutes', 0)
        reused = roi.get('solutions_reused', 0)
        decisions = roi.get('decisions_referenced', 0)
        prevented = roi.get('errors_prevented', 0)
        sessions = roi.get('sessions_with_context', 0)
        errors_live = roi.get('errors_caught_live', 0)
        insights = roi.get('insights_used', 0)

        # Format time
        if time_saved < 60:
            time_str = f"{time_saved} minutes"
        else:
            hours = time_saved // 60
            mins = time_saved % 60
            time_str = f"{hours}h {mins}m" if mins else f"{hours} hours"

        lines = [
            "## ⚡ FixOnce Impact\n",
            f"**🕐 Time Saved:** {time_str}\n"
        ]

        # Breakdown
        lines.append("**Breakdown:**")
        if reused > 0:
            lines.append(f"- 🔍 {reused} solutions reused (saved ~{reused * 10}m)")
        if decisions > 0:
            lines.append(f"- 🔒 {decisions} decisions applied (saved ~{decisions * 20}m)")
        if prevented > 0:
            lines.append(f"- 🛡️ {prevented} errors prevented (saved ~{prevented * 30}m)")
        if sessions > 0:
            lines.append(f"- 🔄 {sessions} sessions with context (saved ~{sessions * 10}m)")
        if errors_live > 0:
            lines.append(f"- ⚡ {errors_live} live errors caught")
        if insights > 0:
            lines.append(f"- 💡 {insights} insights used")

        if reused == 0 and decisions == 0 and prevented == 0 and sessions == 0:
            lines.append("- Building impact... (use search, log decisions, work across sessions)")

        return '\n'.join(lines)

    except Exception as e:
        return f"Error getting impact stats: {e}"


# ============================================================
# SMART TOOLS - File operations with automatic error checking
# ============================================================
# These tools wrap file operations and automatically check for
# browser errors after each operation. Claude should use these
# instead of regular Edit/Write when working on web projects.
# ============================================================

import time

def _get_new_errors_since(timestamp: str) -> list:
    """Get errors that occurred after the given timestamp."""
    try:
        res = requests.get(f'http://localhost:5000/api/live-errors?since=10', timeout=2)
        if res.status_code == 200:
            data = res.json()
            errors = data.get('errors', [])
            # Filter to errors after timestamp
            new_errors = []
            for e in errors:
                err_time = e.get('timestamp', '')
                if err_time > timestamp:
                    new_errors.append(e)
            return new_errors
        return []
    except Exception:
        return []


def _format_error_alert(errors: list) -> str:
    """Format errors as an alert message."""
    if not errors:
        return ""

    lines = [
        "",
        "═══════════════════════════════════════",
        f"🚨 **{len(errors)} NEW ERROR(S) DETECTED!**",
        "═══════════════════════════════════════"
    ]

    for e in errors[:5]:
        msg = e.get('message', 'Unknown error')[:80]
        source = e.get('source', '')
        if source:
            source_short = source.split('/')[-1][:20]
            lines.append(f"• [{source_short}] {msg}")
        else:
            lines.append(f"• {msg}")

    if len(errors) > 5:
        lines.append(f"• ...and {len(errors) - 5} more")

    lines.append("")
    lines.append("**⚠️ FIX THESE BEFORE CONTINUING!**")
    lines.append("═══════════════════════════════════════")

    return '\n'.join(lines)


@mcp.tool()
def smart_file_operation(
    operation: str,
    file_path: str,
    content: str = "",
    description: str = ""
) -> str:
    """
    Execute a file operation and automatically check for browser errors.

    USE THIS instead of regular Edit/Write when working on web projects!
    After the operation, waits briefly and checks if any new browser errors appeared.

    Args:
        operation: "read", "write", "append", or "info"
        file_path: Path to the file
        content: Content to write (for write/append operations)
        description: What this change does (for logging)

    Returns:
        Operation result + any new browser errors detected

    Example:
        smart_file_operation("write", "game.js", "function startGame() {...}", "Added start function")
    """
    error, context = _universal_gate("smart_file_operation")
    if error:
        return error

    # Record timestamp before operation
    before_time = datetime.now().isoformat()

    result_lines = [context]

    try:
        path = Path(file_path)

        if operation == "read":
            if path.exists():
                content = path.read_text(encoding='utf-8')
                result_lines.append(f"📄 Read {len(content)} chars from {file_path}")
                result_lines.append("```")
                result_lines.append(content[:2000])
                if len(content) > 2000:
                    result_lines.append(f"... ({len(content) - 2000} more chars)")
                result_lines.append("```")
            else:
                result_lines.append(f"❌ File not found: {file_path}")

        elif operation == "write":
            # Check if this affects a stable component BEFORE writing
            stable_impact = _check_stable_component_impact(file_path)
            if stable_impact:
                result_lines.append("")
                result_lines.append(f"⚠️ **STABILITY WARNING**: This file belongs to stable component '{stable_impact['name']}'")
                result_lines.append(f"   Checkpoint: {stable_impact['commit']}")
                result_lines.append(f"   Consider: rollback_component(\"{stable_impact['name']}\") if issues occur")
                result_lines.append("")
                # Log this modification
                _log_stable_component_modification(stable_impact['name'], file_path, "AI")

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            result_lines.append(f"✅ Wrote {len(content)} chars to {file_path}")
            if description:
                result_lines.append(f"📝 {description}")

        elif operation == "append":
            # Check if this affects a stable component BEFORE appending
            stable_impact = _check_stable_component_impact(file_path)
            if stable_impact:
                result_lines.append("")
                result_lines.append(f"⚠️ **STABILITY WARNING**: This file belongs to stable component '{stable_impact['name']}'")
                result_lines.append(f"   Checkpoint: {stable_impact['commit']}")
                result_lines.append(f"   Consider: rollback_component(\"{stable_impact['name']}\") if issues occur")
                result_lines.append("")
                # Log this modification
                _log_stable_component_modification(stable_impact['name'], file_path, "AI")

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(content)
            result_lines.append(f"✅ Appended {len(content)} chars to {file_path}")
            if description:
                result_lines.append(f"📝 {description}")

        elif operation == "info":
            if path.exists():
                stat = path.stat()
                result_lines.append(f"📄 {file_path}")
                result_lines.append(f"   Size: {stat.st_size} bytes")
                result_lines.append(f"   Modified: {datetime.fromtimestamp(stat.st_mtime).isoformat()}")
            else:
                result_lines.append(f"❌ File not found: {file_path}")

        else:
            result_lines.append(f"❌ Unknown operation: {operation}")
            return '\n'.join(result_lines)

    except Exception as e:
        result_lines.append(f"❌ Error: {e}")
        return '\n'.join(result_lines)

    # Wait for browser to potentially throw errors
    time.sleep(1.5)

    # Check for new errors
    new_errors = _get_new_errors_since(before_time)

    if new_errors:
        result_lines.append(_format_error_alert(new_errors))

        # Log this as a potential issue
        session = _get_session()
        if session.is_active():
            # Track that we caught an error
            _track_roi_event("error_prevented")
    else:
        result_lines.append("")
        result_lines.append("✅ No new browser errors detected")

    return '\n'.join(result_lines)


@mcp.tool()
def check_and_report() -> str:
    """
    Quick check for browser errors and project status.

    Call this periodically while working to catch any errors early.
    Returns a compact status report.
    """
    error, context = _universal_gate("check_and_report")
    if error:
        return error

    lines = [context]

    # Check browser errors
    errors = _get_live_errors()

    if errors:
        lines.append(f"🚨 **{len(errors)} BROWSER ERRORS:**")
        for e in errors[:3]:
            msg = e.get('message', 'Unknown')[:60]
            lines.append(f"  • {msg}")
        if len(errors) > 3:
            lines.append(f"  • ...and {len(errors) - 3} more")
        lines.append("")
        lines.append("**Use `get_browser_errors()` for details.**")
    else:
        lines.append("✅ No browser errors")

    # Add goal reminder
    session = _get_session()
    if session.is_active():
        memory = _load_project(session.project_id)
        if memory:
            goal = memory.get('live_record', {}).get('intent', {}).get('current_goal', '')
            if goal:
                lines.append("")
                lines.append(f"🎯 Current goal: {goal}")

    # Check AI Context mode
    ai_context = _get_ai_context_injection()
    if ai_context:
        lines.append("")
        lines.append("🎯 **AI Context ACTIVE** - User has selected element(s)")
        lines.append("   When they say \"this/that/זה\" → use the selected element")

    return '\n'.join(lines)


@mcp.tool()
def generate_context() -> str:
    """
    Generate the universal context file (.fixonce/CONTEXT.md).

    This file can be read by ANY AI - not just those with MCP access.
    It's auto-generated on every memory change, but you can also
    trigger manual generation with this tool.

    Returns:
        Path to the generated file, or error if failed.
    """
    error, context = _universal_gate("generate_context")
    if error:
        return error

    session = _get_session()
    if not session.is_active():
        return "Error: No active session. Call auto_init_session first."

    memory = _load_project(session.project_id)
    if not memory:
        return "Error: Could not load project memory."

    working_dir = memory.get('project_info', {}).get('working_dir', '')
    if not working_dir:
        return "Error: No working_dir in project_info."

    try:
        from core.context_generator import generate_context_file
        context_path = generate_context_file(memory, working_dir)
        return f"✅ Context file generated:\n`{context_path}`\n\nAny AI can now read this file to get project context."
    except Exception as e:
        return f"Error generating context: {e}"


# ============================================================
# COMMAND EXECUTION ACKNOWLEDGMENT
# ============================================================

@mcp.tool()
def mark_command_executed(command_id: str, result: str = "success", details: str = "") -> str:
    """
    Mark a dashboard command as executed (completed).

    Call this AFTER you finish executing a command from the dashboard.
    This completes the audit trail: queued → delivered → executed.

    Args:
        command_id: The command ID shown in the action request (e.g., "a1b2c3d4")
        result: "success", "failed", or "partial"
        details: Optional details about the execution result

    Returns:
        Confirmation message
    """
    error, context = _universal_gate("mark_command_executed")
    if error:
        return error

    session = _get_session()
    if not session.is_active():
        return "Error: No active session."

    memory = _load_project(session.project_id)
    if not memory:
        return "Error: Could not load project memory."

    # Find the command in the queue
    ai_queue = memory.get("ai_queue", [])
    command = None
    for item in ai_queue:
        if item.get("id") == command_id:
            command = item
            break

    if not command:
        # Command might have been cleaned up, just log to audit
        pass
    else:
        # EXECUTION LOCK: Only allow marking if status is "delivered"
        current_status = command.get("status", "")
        if current_status != "delivered":
            return f"❌ Cannot mark command `{command_id}` as executed.\nCurrent status: `{current_status}` (must be `delivered`).\n(📌 FixOnce: execution lock rejected)"

        # Update command status
        command["status"] = "executed" if result == "success" else f"executed_{result}"
        command["executed_at"] = datetime.now().isoformat()
        command["execution_result"] = result
        command["execution_details"] = details

    # Add to audit log
    if "command_audit" not in memory:
        memory["command_audit"] = []

    memory["command_audit"].append({
        "id": command_id,
        "action": "executed",
        "result": result,
        "details": details[:200] if details else "",
        "timestamp": datetime.now().isoformat(),
        "executed_by": _detect_editor()
    })

    # Keep audit bounded
    memory["command_audit"] = memory["command_audit"][-50:]

    _save_project(session.project_id, memory)

    result_emoji = "✅" if result == "success" else "⚠️" if result == "partial" else "❌"
    return f"{result_emoji} Command `{command_id}` marked as {result}.\n(📌 FixOnce: execution logged)"


@mcp.tool()
def get_pending_commands(mark_delivered: bool = True) -> str:
    """
    Get pending commands from the dashboard AI queue.

    Use this to receive messages/commands sent from the FixOnce dashboard.
    When user clicks "Send to AI" or uses action buttons, commands are queued here.

    Args:
        mark_delivered: If True (default), mark retrieved commands as "delivered"
                       so they won't be returned again.

    Returns:
        Pending commands with their messages, or "No pending commands."
    """
    error, context = _universal_gate("get_pending_commands")
    if error:
        return error

    session = _get_session()
    if not session.is_active():
        return "Error: No active session."

    memory = _load_project(session.project_id)
    if not memory:
        return "Error: Could not load project memory."

    # Get pending commands
    ai_queue = memory.get("ai_queue", [])
    pending = [cmd for cmd in ai_queue if cmd.get("status") == "pending"]

    if not pending:
        return "No pending commands."

    # Build response
    lines = ["## 🚀 ACTION REQUESTED FROM DASHBOARD\n"]

    for cmd in pending:
        cmd_id = cmd.get("id", "unknown")
        cmd_type = cmd.get("type", "unknown")
        message = cmd.get("message", "")
        source = cmd.get("source", "dashboard")
        queued_at = cmd.get("queued_at", "")

        lines.append(f"**Command ID:** `{cmd_id}`")
        lines.append(f"**Type:** {cmd_type}")
        lines.append(f"**Source:** {source}")
        if queued_at:
            lines.append(f"**Queued:** {queued_at}")
        lines.append("")
        lines.append("**Message:**")
        lines.append(message)
        lines.append("")
        lines.append("---")
        lines.append("")

        # Mark as delivered
        if mark_delivered:
            cmd["status"] = "delivered"
            cmd["delivered_at"] = datetime.now().isoformat()
            cmd["delivered_to"] = _detect_editor()

    # Save if we marked any as delivered
    if mark_delivered and pending:
        _save_project(session.project_id, memory)

    lines.append(f"_Call `mark_command_executed(command_id=\"{pending[0].get('id')}\", result=\"success\")` when done._")

    return "\n".join(lines)


# ============================================================
# SESSION RESUME STATE
# ============================================================

@mcp.tool()
def save_resume_state(
    active_task: str,
    last_completed_step: str = "",
    current_status: str = "in_progress",
    next_recommended_action: str = "",
    short_summary: str = ""
) -> str:
    """
    Save the current work state for resuming after restart.

    Call this BEFORE:
    - Restarting Claude/MCP
    - Closing a session
    - Major refactors
    - When a clear next action is defined

    Args:
        active_task: What task is currently in progress
        last_completed_step: The last step that was completed
        current_status: One of: in_progress, waiting_for_restart, blocked, paused, completed
        next_recommended_action: What should be done next
        short_summary: Human-readable summary of where we stopped

    Returns:
        Confirmation of saved state
    """
    error = _require_session("save_resume_state")
    if error:
        return error

    if not _resume_state_available:
        return "Error: Resume state module not available."

    session = _get_session()

    result = _save_resume_state(
        project_id=session.project_id,
        active_task=active_task,
        last_completed_step=last_completed_step,
        current_status=current_status,
        next_recommended_action=next_recommended_action,
        short_summary=short_summary
    )

    if "error" in result:
        return f"Error: {result['error']}"

    lines = ["## ✅ Resume State Saved\n"]
    lines.append(f"**Task:** {active_task}")
    if last_completed_step:
        lines.append(f"**Last step:** {last_completed_step}")
    lines.append(f"**Status:** {current_status}")
    if next_recommended_action:
        lines.append(f"**Next action:** {next_recommended_action}")
    lines.append("")
    lines.append("_This state will be shown automatically when you start a new session._")

    return "\n".join(lines)


@mcp.tool()
def get_resume_state() -> str:
    """
    Get the current resume state for this project.

    Returns the saved work state, or indicates if none exists.
    """
    error = _require_session("get_resume_state")
    if error:
        return error

    if not _resume_state_available:
        return "Error: Resume state module not available."

    session = _get_session()
    resume_state = _get_resume_state(session.project_id)

    if not resume_state:
        return "No resume state saved for this project."

    lines = ["## 🔄 Current Resume State\n"]
    lines.append(f"**Task:** {resume_state.get('active_task', 'N/A')}")

    if resume_state.get('last_completed_step'):
        lines.append(f"**Last completed:** {resume_state['last_completed_step']}")

    status = resume_state.get('current_status', 'unknown')
    status_emoji = {
        "in_progress": "🔵",
        "waiting_for_restart": "⏳",
        "blocked": "🔴",
        "paused": "⏸️",
        "completed": "✅"
    }
    emoji = status_emoji.get(status, "")
    lines.append(f"**Status:** {emoji} {status}")

    if resume_state.get('next_recommended_action'):
        lines.append(f"**Next action:** {resume_state['next_recommended_action']}")

    if resume_state.get('short_summary'):
        lines.append("")
        lines.append(f"_{resume_state['short_summary']}_")

    if resume_state.get('updated_at'):
        lines.append("")
        lines.append(f"_Saved at: {resume_state['updated_at'][:19]}_")

    return "\n".join(lines)


@mcp.tool()
def clear_resume_state() -> str:
    """
    Clear the resume state (task completed, no longer relevant).

    Call this when the active task is fully completed.
    """
    error = _require_session("clear_resume_state")
    if error:
        return error

    if not _resume_state_available:
        return "Error: Resume state module not available."

    session = _get_session()
    success = _clear_resume_state(session.project_id)

    if success:
        return "✅ Resume state cleared. No pending work state."
    else:
        return "No resume state to clear."


# ============================================================
# COMPLIANCE API (For Dashboard Widget)
# ============================================================

def get_compliance_for_api() -> dict:
    """Get compliance status for dashboard API.

    Loads from file since Flask runs in different process than MCP.
    """
    # Load from file (shared between MCP and Flask processes)
    state = _load_compliance()
    return {
        "session_initialized": state.get("session_active", False),
        "initialized_at": state.get("initialized_at"),
        "decisions_displayed": state.get("decisions_displayed", False),
        "goal_updated": state.get("goal_updated", False),
        "search_performed": state.get("search_performed", False),
        "component_updated": state.get("component_updated", False),
        "decision_logged": state.get("decision_logged", False),
        "tool_calls_count": state.get("tool_calls_count", 0),
        "score": state.get("score", 0),
        "rules": state.get("rules", []),
        "last_session_init": state.get("last_session_init"),
        "violations": state.get("violations", [])[-5:],
        "editor": state.get("editor"),
        "project_id": state.get("project_id")
    }


if __name__ == "__main__":
    mcp.run(show_banner=False)
