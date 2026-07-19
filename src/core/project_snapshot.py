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
class KnowledgeCounts:
    """Project knowledge statistics."""
    decisions: int = 0
    solutions: int = 0
    insights: int = 0


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
    knowledge_counts: KnowledgeCounts = field(default_factory=KnowledgeCounts)

    # Live Evidence (computed fresh)
    branch: str = ""
    uncommitted_files: List[str] = field(default_factory=list)
    recent_commits: List[Dict] = field(default_factory=list)

    # Activity (from ai_connections.json)
    connected_agent: Optional[str] = None
    last_activity_at: Optional[datetime] = None

    # Freshness (computed)
    state_age_hours: float = 0.0
    may_be_stale: bool = False

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
            "knowledge_counts": {
                "decisions": self.knowledge_counts.decisions,
                "solutions": self.knowledge_counts.solutions,
                "insights": self.knowledge_counts.insights,
            },
            "branch": self.branch,
            "uncommitted_files": self.uncommitted_files,
            "recent_commits": self.recent_commits,
            "connected_agent": self.connected_agent,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "state_age_hours": round(self.state_age_hours, 1),
            "may_be_stale": self.may_be_stale,
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

def _query_recorded_knowledge(working_dir: str) -> Dict[str, Any]:
    """
    Query recent decisions and solutions from committed knowledge.

    Source: .fixonce/decisions.json, .fixonce/solutions.json

    Returns:
        {"recent_decisions": [...], "recent_solutions": [...], "counts": KnowledgeCounts}
    """
    recent_decisions = []
    recent_solutions = []
    counts = KnowledgeCounts()

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
        insights = ck.get("insights", [])

        # Get 3 most recent of each (V1: compact display)
        recent_decisions = sort_by_time(decisions)[:3]
        recent_solutions = sort_by_time(solutions)[:3]

        # Counts
        counts = KnowledgeCounts(
            decisions=len(decisions),
            solutions=len(solutions),
            insights=len(insights),
        )

    except Exception:
        pass

    return {
        "recent_decisions": recent_decisions,
        "recent_solutions": recent_solutions,
        "counts": counts,
    }


# =============================================================================
# ACTIVITY - From ai_connections.json
# =============================================================================

def _get_activity_info(project_id: str) -> Dict[str, Any]:
    """
    Get activity info from ai_connections.json.

    Returns:
        {"connected_agent": "Claude Code" | None, "last_activity_at": datetime | None}
    """
    connected_agent = None
    last_activity_at = None

    try:
        ai_connections_file = _get_user_data_dir() / "ai_connections.json"
        if ai_connections_file.exists():
            with open(ai_connections_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Find connection for this project
            for conn in data.get("connections", []):
                if conn.get("project_id") == project_id:
                    connected_agent = conn.get("editor") or conn.get("actor")
                    last_seen = conn.get("last_seen")
                    if last_seen:
                        try:
                            last_activity_at = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                        except:
                            pass
                    break
    except Exception:
        pass

    return {
        "connected_agent": connected_agent,
        "last_activity_at": last_activity_at,
    }


# =============================================================================
# FRESHNESS - Computed from updated_at
# =============================================================================

def _compute_freshness(updated_at: Optional[datetime]) -> Dict[str, Any]:
    """
    Compute freshness indicators.

    Returns:
        {"state_age_hours": float, "may_be_stale": bool}
    """
    if not updated_at:
        return {"state_age_hours": 0.0, "may_be_stale": True}

    now = datetime.now()

    # Handle timezone-naive comparison
    if updated_at.tzinfo:
        updated_at = updated_at.replace(tzinfo=None)

    try:
        age = now - updated_at
        age_hours = age.total_seconds() / 3600

        # Stale if > 4 hours
        may_be_stale = age_hours > 4.0

        return {
            "state_age_hours": age_hours,
            "may_be_stale": may_be_stale,
        }
    except Exception:
        return {"state_age_hours": 0.0, "may_be_stale": True}


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
    recent_commits = get_recent_commits(working_dir, limit=3)

    # Layer 4: Activity
    activity = _get_activity_info(project_id)

    # Layer 5: Freshness
    freshness = _compute_freshness(state.get("updated_at"))

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
        knowledge_counts=knowledge["counts"],
        branch=branch,
        uncommitted_files=uncommitted_files,
        recent_commits=recent_commits,
        connected_agent=activity["connected_agent"],
        last_activity_at=activity["last_activity_at"],
        state_age_hours=freshness["state_age_hours"],
        may_be_stale=freshness["may_be_stale"],
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


def render_snapshot_opener_v1(snapshot: ProjectSnapshot) -> str:
    """
    Render snapshot as V1 text opener for fo_init.

    Format:
        🧠 Back to {project}

        ── Current Project Snapshot ──

        Goal:
        {goal}

        Last completed:
        {last}

        Suggested next step:
        {next}
        (by {agent}, {time_ago})
        ⚠️ This suggestion may be outdated.  # if stale

        📊 {decisions} Decisions · {solutions} Solved Bugs · {insights} Insights

        Ready.
    """
    lines = [f"🧠 Back to {snapshot.project_name}", ""]

    lines.append("── Current Project Snapshot ──")
    lines.append("")

    # Goal
    if snapshot.goal:
        lines.append("Goal:")
        lines.append(snapshot.goal)
        lines.append("")

    # Last completed
    if snapshot.last:
        lines.append("Last completed:")
        lines.append(snapshot.last)
        lines.append("")

    # Suggested next step
    if snapshot.next:
        lines.append("Suggested next step:")
        lines.append(snapshot.next)

        # Source and time
        source_parts = []
        if snapshot.connected_agent:
            source_parts.append(f"by {snapshot.connected_agent}")
        if snapshot.updated_at:
            age = _format_time_ago(snapshot.state_age_hours)
            source_parts.append(age)
        if source_parts:
            lines.append(f"({', '.join(source_parts)})")

        # Stale warning
        if snapshot.may_be_stale:
            lines.append("⚠️ This suggestion may be outdated.")

        lines.append("")

    # Knowledge counts
    k = snapshot.knowledge_counts
    if k.decisions or k.solutions or k.insights:
        parts = []
        if k.decisions:
            parts.append(f"{k.decisions} Decisions")
        if k.solutions:
            parts.append(f"{k.solutions} Solved Bugs")
        if k.insights:
            parts.append(f"{k.insights} Insights")
        lines.append(f"📊 {' · '.join(parts)}")
        lines.append("")

    lines.append("Ready.")

    return "\n".join(lines)


def _format_time_ago(hours: float) -> str:
    """Format hours as human-readable time ago."""
    if hours < 1:
        minutes = int(hours * 60)
        if minutes < 1:
            return "just now"
        return f"{minutes}m ago"
    elif hours < 24:
        return f"{int(hours)}h ago"
    else:
        days = int(hours / 24)
        return f"{days}d ago"
