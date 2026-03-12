"""
Session Registry for Multi-AI Isolation.

Manages isolated sessions per AI+project combination.
Each AI can work on a different project without conflicts.

Key format: "ai_name:project_path" → IsolatedSession
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict

# Data paths
DATA_DIR = Path(__file__).parent.parent.parent / 'data'
REGISTRY_FILE = DATA_DIR / 'session_registry.json'

# Session timeout (remove inactive sessions after this)
SESSION_TIMEOUT_MINUTES = 60


@dataclass
class IsolatedSession:
    """An isolated session for one AI working on one project."""

    # Identity
    ai_name: str  # "claude", "codex", "cursor"
    project_id: str
    project_path: str

    # Timestamps
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now().isoformat())

    # Protocol compliance
    initialized: bool = False
    decisions_displayed: bool = False
    goal_updated: bool = False
    search_performed: bool = False
    component_updated: bool = False
    decision_logged: bool = False

    # Activity tracking
    tool_calls: List[Dict] = field(default_factory=list)

    def __post_init__(self):
        # Ensure tool_calls is a list
        if self.tool_calls is None:
            self.tool_calls = []

    @property
    def session_key(self) -> str:
        """Unique key for this session."""
        return f"{self.ai_name}:{self.project_path}"

    def is_active(self) -> bool:
        """Check if session is active (has activity in last timeout period)."""
        try:
            last = datetime.fromisoformat(self.last_activity)
            return (datetime.now() - last) < timedelta(minutes=SESSION_TIMEOUT_MINUTES)
        except:
            return False

    def touch(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now().isoformat()

    def log_tool_call(self, tool_name: str):
        """Log a tool call."""
        self.tool_calls.append({
            "tool": tool_name,
            "timestamp": datetime.now().isoformat()
        })
        # Prevent unbounded memory growth - keep last 100 calls
        if len(self.tool_calls) > 100:
            self.tool_calls = self.tool_calls[-100:]
        self.touch()

        # Track specific tools
        if tool_name == "search_past_solutions":
            self.search_performed = True
        elif tool_name == "update_component_status":
            self.component_updated = True
        elif tool_name == "log_decision":
            self.decision_logged = True

    def mark_initialized(self):
        """Mark session as initialized."""
        self.initialized = True
        self.touch()

    def get_compliance_score(self) -> int:
        """Calculate compliance score (0-100)."""
        rules = [
            (self.initialized, 2),  # Required, weight 2
            (self.goal_updated, 2),  # Required, weight 2
            (self.search_performed, 1),
            (self.component_updated, 1),
            (self.decision_logged, 1),
        ]

        total_weight = sum(w for _, w in rules)
        earned_weight = sum(w for passed, w in rules if passed)

        return int((earned_weight / total_weight) * 100) if total_weight > 0 else 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ai_name": self.ai_name,
            "project_id": self.project_id,
            "project_path": self.project_path,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "initialized": self.initialized,
            "decisions_displayed": self.decisions_displayed,
            "goal_updated": self.goal_updated,
            "search_performed": self.search_performed,
            "component_updated": self.component_updated,
            "decision_logged": self.decision_logged,
            "tool_calls_count": len(self.tool_calls),
            "compliance_score": self.get_compliance_score(),
            "is_active": self.is_active(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IsolatedSession':
        """Create from dictionary."""
        return cls(
            ai_name=data.get("ai_name", "unknown"),
            project_id=data.get("project_id", ""),
            project_path=data.get("project_path", ""),
            started_at=data.get("started_at", datetime.now().isoformat()),
            last_activity=data.get("last_activity", datetime.now().isoformat()),
            initialized=data.get("initialized", False),
            decisions_displayed=data.get("decisions_displayed", False),
            goal_updated=data.get("goal_updated", False),
            search_performed=data.get("search_performed", False),
            component_updated=data.get("component_updated", False),
            decision_logged=data.get("decision_logged", False),
            tool_calls=data.get("tool_calls", []),
        )


class SessionRegistry:
    """
    Thread-safe registry of isolated sessions.

    Each AI+project combination gets its own session.
    Sessions persist to disk for Flask API access.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._sessions: Dict[str, IsolatedSession] = {}
        self._lock = threading.Lock()
        self._load_from_disk()
        self._initialized = True

    def _load_from_disk(self, force_reload: bool = False):
        """Load sessions from disk.

        Args:
            force_reload: If True, clear in-memory sessions and reload from disk.
                         Use this when reading data that may have been updated
                         by another process (e.g., MCP server).
        """
        try:
            if REGISTRY_FILE.exists():
                with open(REGISTRY_FILE, 'r') as f:
                    data = json.load(f)

                if force_reload:
                    self._sessions.clear()

                for key, session_data in data.get("sessions", {}).items():
                    session = IsolatedSession.from_dict(session_data)
                    # Only load active sessions
                    if session.is_active():
                        self._sessions[key] = session
        except Exception as e:
            print(f"[SessionRegistry] Load error: {e}")

    def _save_to_disk(self):
        """Save sessions to disk."""
        try:
            REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "updated_at": datetime.now().isoformat(),
                "sessions": {
                    key: session.to_dict()
                    for key, session in self._sessions.items()
                    if session.is_active()
                }
            }

            with open(REGISTRY_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SessionRegistry] Save error: {e}")

    def get_or_create(
        self,
        ai_name: str,
        project_id: str,
        project_path: str
    ) -> IsolatedSession:
        """
        Get existing session or create new one.

        Args:
            ai_name: The AI name (claude, codex, cursor)
            project_id: The project ID
            project_path: The project working directory path

        Returns:
            IsolatedSession for this AI+project
        """
        key = f"{ai_name}:{project_path}"

        with self._lock:
            if key in self._sessions:
                session = self._sessions[key]
                session.touch()
            else:
                session = IsolatedSession(
                    ai_name=ai_name,
                    project_id=project_id,
                    project_path=project_path
                )
                self._sessions[key] = session
                print(f"[SessionRegistry] New session: {ai_name} on {project_path}")

            self._save_to_disk()
            return session

    def get_session(self, ai_name: str, project_path: str) -> Optional[IsolatedSession]:
        """Get session by AI and project path, if exists."""
        key = f"{ai_name}:{project_path}"
        with self._lock:
            return self._sessions.get(key)

    def get_all_active(self) -> List[IsolatedSession]:
        """Get all active sessions."""
        with self._lock:
            return [s for s in self._sessions.values() if s.is_active()]

    def get_sessions_by_project(self, project_id: str) -> List[IsolatedSession]:
        """Get all sessions for a project (may have multiple AIs)."""
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.project_id == project_id and s.is_active()
            ]

    def get_sessions_by_ai(self, ai_name: str) -> List[IsolatedSession]:
        """Get all sessions for an AI (may have multiple projects)."""
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.ai_name == ai_name and s.is_active()
            ]

    def close_project_sessions(self, project_id: str) -> int:
        """Close all sessions for a project. Returns count of closed."""
        with self._lock:
            keys_to_remove = [
                key for key, session in self._sessions.items()
                if session.project_id == project_id
            ]

            for key in keys_to_remove:
                del self._sessions[key]

            if keys_to_remove:
                self._save_to_disk()
                print(f"[SessionRegistry] Closed {len(keys_to_remove)} sessions for project {project_id}")

            return len(keys_to_remove)

    def cleanup_stale(self) -> int:
        """Remove stale sessions. Returns count of removed."""
        with self._lock:
            stale_keys = [
                key for key, session in self._sessions.items()
                if not session.is_active()
            ]

            for key in stale_keys:
                del self._sessions[key]

            if stale_keys:
                self._save_to_disk()
                print(f"[SessionRegistry] Cleaned {len(stale_keys)} stale sessions")

            return len(stale_keys)

    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get data for dashboard tabs.

        Note: This method reloads from disk to ensure we see sessions
        created by other processes (e.g., MCP server writes, Flask reads).

        Returns:
            {
                "sessions": [...],
                "projects": {
                    "project_id": {
                        "name": "...",
                        "path": "...",
                        "active_ais": ["claude", "codex"],
                        "primary_ai": "claude",
                        "last_activity": "..."
                    }
                }
            }
        """
        with self._lock:
            # Reload from disk to see updates from other processes
            self._load_from_disk(force_reload=True)
            active_sessions = [s for s in self._sessions.values() if s.is_active()]

            # Group by project
            projects = {}
            for session in active_sessions:
                pid = session.project_id
                if pid not in projects:
                    projects[pid] = {
                        "project_id": pid,
                        "path": session.project_path,
                        "name": Path(session.project_path).name,
                        "active_ais": [],
                        "last_activity": session.last_activity,
                        "sessions": []
                    }

                projects[pid]["active_ais"].append(session.ai_name)
                projects[pid]["sessions"].append(session.to_dict())

                # Update last activity if more recent
                if session.last_activity > projects[pid]["last_activity"]:
                    projects[pid]["last_activity"] = session.last_activity

            # Determine primary AI per project (most recent activity)
            for pid, proj in projects.items():
                if proj["sessions"]:
                    most_recent = max(proj["sessions"], key=lambda s: s["last_activity"])
                    proj["primary_ai"] = most_recent["ai_name"]

            return {
                "updated_at": datetime.now().isoformat(),
                "session_count": len(active_sessions),
                "project_count": len(projects),
                "sessions": [s.to_dict() for s in active_sessions],
                "projects": projects
            }


# Global singleton instance
_registry = None


def get_registry() -> SessionRegistry:
    """Get the global SessionRegistry instance."""
    global _registry
    if _registry is None:
        _registry = SessionRegistry()
    return _registry


def get_or_create_session(
    ai_name: str,
    project_id: str,
    project_path: str
) -> IsolatedSession:
    """Convenience function to get or create a session."""
    return get_registry().get_or_create(ai_name, project_id, project_path)


def get_dashboard_sessions() -> Dict[str, Any]:
    """Get session data for dashboard."""
    return get_registry().get_dashboard_data()
