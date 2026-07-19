"""
Project Snapshot - Single source of truth for project state.

This module provides ONE function that both Dashboard and fo_init use:
    get_project_snapshot(project_id, working_dir)

Design principles:
1. Read-only aggregator - does not write, only reads existing data
2. Single source - eliminates divergence between Dashboard and fo_init
3. Uses existing storage - no new schema or migration
4. Git functions extracted here to avoid duplication
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import subprocess
import json


@dataclass
class ProjectSnapshot:
    """
    Complete project state at a point in time.

    This is the single source of truth for:
    - fo_init (renders as text opener)
    - Dashboard API (returns as JSON)
    """
    # Identity
    project_id: str
    project_name: str

    # Declared State (from fo_sync -> live_record.intent)
    goal: str = ""
    last: str = ""
    next: str = ""
    work_area: str = ""
    updated_at: Optional[datetime] = None

    # Recorded Knowledge (from committed_knowledge)
    recent_decisions: List[Dict] = field(default_factory=list)
    recent_solutions: List[Dict] = field(default_factory=list)

    # Live Evidence (computed fresh)
    branch: str = ""
    uncommitted_files: List[str] = field(default_factory=list)
    recent_commits: List[Dict] = field(default_factory=list)

    # Meta
    snapshot_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API/Dashboard."""
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "goal": self.goal,
            "last": self.last,
            "next": self.next,
            "work_area": self.work_area,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "recent_decisions": self.recent_decisions,
            "recent_solutions": self.recent_solutions,
            "branch": self.branch,
            "uncommitted_files": self.uncommitted_files,
            "recent_commits": self.recent_commits,
            "snapshot_at": self.snapshot_at.isoformat(),
        }


# =============================================================================
# GIT HELPERS - Single source for git data collection
# =============================================================================

def _get_creationflags() -> int:
    """Get subprocess creationflags for Windows (hide console window)."""
    try:
        from core.component_stability import no_window_creationflags
        return no_window_creationflags()
    except ImportError:
        import sys
        if sys.platform == "win32":
            return subprocess.CREATE_NO_WINDOW
        return 0


def get_git_branch(working_dir: str) -> str:
    """
    Get current git branch name.

    Returns:
        Branch name or empty string if not a git repo
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=_get_creationflags(),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def get_uncommitted_files(working_dir: str) -> List[str]:
    """
    Get list of uncommitted file paths.

    Returns:
        List of file paths with changes (staged, unstaged, or untracked)
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=_get_creationflags(),
        )
        if result.returncode == 0 and result.stdout.strip():
            files = []
            for line in result.stdout.strip().split('\n'):
                if line and len(line) > 3:
                    # Format: "XY filename" where XY is status, filename starts at position 3
                    files.append(line[3:].strip())
            return files
    except Exception:
        pass
    return []


def get_recent_commits(working_dir: str, limit: int = 5) -> List[Dict[str, str]]:
    """
    Get recent commit history.

    Returns:
        List of {"hash": ..., "message": ..., "date": ...}
    """
    try:
        result = subprocess.run(
            ["git", "log", f"-{limit}", "--format=%h|%s|%ci"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=_get_creationflags(),
        )
        if result.returncode == 0 and result.stdout.strip():
            commits = []
            for line in result.stdout.strip().split('\n'):
                parts = line.split('|', 2)
                if len(parts) >= 2:
                    commits.append({
                        "hash": parts[0],
                        "message": parts[1][:80],
                        "date": parts[2] if len(parts) > 2 else "",
                    })
            return commits
    except Exception:
        pass
    return []


# =============================================================================
# DECLARED STATE - From fo_sync -> live_record.intent
# =============================================================================

def _get_user_data_dir() -> Path:
    """Get FixOnce user data directory (~/.fixonce/)."""
    return Path.home() / ".fixonce"


def _get_project_file_path(project_id: str) -> Path:
    """
    Get path to project memory file.

    Uses USER data directory (~/.fixonce/projects_v2/), not the install directory.
    This matches where the MCP server reads/writes project data.
    """
    return _get_user_data_dir() / "projects_v2" / f"{project_id}.json"


def _load_declared_state(project_id: str) -> Dict[str, Any]:
    """
    Load declared state from project storage.

    Source: ~/.fixonce/projects_v2/{project_id}.json -> live_record.intent

    Returns:
        {"goal": ..., "last": ..., "next": ..., "updated_at": ...}
    """
    try:
        project_file = _get_project_file_path(project_id)

        if not project_file.exists():
            return {}

        with open(project_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        intent = data.get("live_record", {}).get("intent", {})

        # Parse timestamp
        updated_at = None
        ts = intent.get("updated_at")
        if ts:
            try:
                updated_at = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except:
                pass

        return {
            "goal": intent.get("current_goal", ""),
            "last": intent.get("last_change", ""),
            "next": intent.get("next_step", ""),
            "work_area": intent.get("work_area", ""),
            "updated_at": updated_at,
        }
    except Exception:
        return {}


# =============================================================================
# RECORDED KNOWLEDGE - From committed_knowledge
# =============================================================================

def _query_recorded_knowledge(working_dir: str) -> Dict[str, List[Dict]]:
    """
    Query recent decisions and solutions from committed knowledge.

    Source: .fixonce/decisions.json, .fixonce/solutions.json

    Returns:
        {"recent_decisions": [...], "recent_solutions": [...]}
    """
    recent_decisions = []
    recent_solutions = []

    try:
        from core.committed_knowledge import read_committed_knowledge
        ck = read_committed_knowledge(working_dir)

        def sort_by_time(items: List) -> List[Dict]:
            return sorted(
                [i for i in items if isinstance(i, dict)],
                key=lambda x: x.get("timestamp", ""),
                reverse=True
            )

        decisions = ck.get("decisions", [])
        solutions = ck.get("solutions", [])

        # Get 5 most recent of each
        recent_decisions = sort_by_time(decisions)[:5]
        recent_solutions = sort_by_time(solutions)[:5]

    except Exception:
        pass

    return {
        "recent_decisions": recent_decisions,
        "recent_solutions": recent_solutions,
    }


# =============================================================================
# MAIN FUNCTION - Single source of truth
# =============================================================================

def get_project_snapshot(
    project_id: str,
    working_dir: str,
) -> ProjectSnapshot:
    """
    Build a complete project snapshot.

    This is the SINGLE SOURCE OF TRUTH for project state.
    Both Dashboard and fo_init MUST use this function.

    Args:
        project_id: The resolved project ID
        working_dir: Project working directory

    Returns:
        Complete ProjectSnapshot with all fields populated
    """
    project_name = Path(working_dir).name

    # Layer 1: Declared State (from storage)
    state = _load_declared_state(project_id)

    # Layer 2: Recorded Knowledge (query storage)
    knowledge = _query_recorded_knowledge(working_dir)

    # Layer 3: Live Evidence (compute fresh)
    branch = get_git_branch(working_dir)
    uncommitted_files = get_uncommitted_files(working_dir)
    recent_commits = get_recent_commits(working_dir, limit=5)

    return ProjectSnapshot(
        project_id=project_id,
        project_name=project_name,
        goal=state.get("goal", ""),
        last=state.get("last", ""),
        next=state.get("next", ""),
        work_area=state.get("work_area", ""),
        updated_at=state.get("updated_at"),
        recent_decisions=knowledge["recent_decisions"],
        recent_solutions=knowledge["recent_solutions"],
        branch=branch,
        uncommitted_files=uncommitted_files,
        recent_commits=recent_commits,
    )


# =============================================================================
# RENDERERS - Present same data differently
# =============================================================================

def render_snapshot_for_dashboard(snapshot: ProjectSnapshot) -> Dict[str, Any]:
    """
    Render snapshot as structured JSON for Dashboard API.

    This is a thin wrapper - just returns the dict representation.
    """
    return snapshot.to_dict()


def render_snapshot_for_agent(snapshot: ProjectSnapshot) -> Dict[str, Any]:
    """
    Render snapshot as data dict for agent opener composition.

    Note: This does NOT render the full opener text.
    The existing _format_minimal_init handles text formatting,
    this just provides the data in a consistent format.

    Returns:
        Dict with same keys as ProjectSnapshot.to_dict()
    """
    return snapshot.to_dict()
