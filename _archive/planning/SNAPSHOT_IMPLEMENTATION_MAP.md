# Project Snapshot Implementation Map

**Date**: 2026-07-19  
**Status**: APPROVED ARCHITECTURE  
**Estimated Effort**: 8-12 days

---

## Executive Summary

Replace fragmented state building with a unified **Project Snapshot** model.

**Before:**
```
Dashboard API → builds its own view
fo_init      → builds opener separately
             → Can diverge (stale opener bug)
```

**After:**
```
get_project_snapshot()
├── Dashboard renderer → visual display
└── fo_init renderer   → natural language opener
                       → Same data, different presentation
```

---

## Architecture

### Three-Layer Snapshot Model

```
┌──────────────────────────────────────────────────────────────────┐
│                      PROJECT SNAPSHOT                            │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 1: DECLARED STATE (stored)                                │
│  ├── goal: str              # Current work objective             │
│  ├── last_change: str       # What was just completed            │
│  ├── next_step: str         # What to do next                    │
│  ├── work_area: str         # Feature/module area                │
│  ├── open_items: list       # Unfinished work items              │
│  └── updated_at: datetime   # When state was last synced         │
│                                                                  │
│  Source: fo_sync writes to live_record.intent                    │
│  Storage: ~/.fixonce/projects_v2/{project_id}.json               │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 2: RECORDED KNOWLEDGE (queried)                           │
│  ├── recent_decisions: list[5]    # Last 5 decisions             │
│  ├── recent_solutions: list[5]    # Last 5 solved bugs           │
│  ├── recent_insights: list[3]     # Last 3 insights              │
│  ├── avoid_patterns: list[3]      # Most relevant avoid patterns │
│  └── pending_reviews: int         # Count of pending reviews     │
│                                                                  │
│  Source: Query from committed_knowledge + project JSON           │
│  Always fresh: Reads current storage, not cached                 │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 3: LIVE EVIDENCE (computed)                               │
│  ├── branch: str                  # git branch --show-current    │
│  ├── uncommitted_files: list      # git status --porcelain       │
│  ├── recent_commits: list[5]      # git log -5 --oneline         │
│  ├── has_uncommitted: bool        # len(uncommitted_files) > 0   │
│  └── tests_passing: bool|None     # If detectable                │
│                                                                  │
│  Source: Git commands + filesystem inspection                    │
│  Always fresh: Computed at read time                             │
├──────────────────────────────────────────────────────────────────┤
│  METADATA                                                        │
│  ├── project_id: str                                             │
│  ├── project_name: str                                           │
│  ├── snapshot_at: datetime        # When snapshot was generated  │
│  └── freshness: FreshnessInfo     # Staleness indicators         │
└──────────────────────────────────────────────────────────────────┘
```

### Freshness Detection

```python
@dataclass
class FreshnessInfo:
    state_updated_at: datetime       # Last fo_sync
    evidence_computed_at: datetime   # Now
    state_age_hours: float           # Hours since last sync
    state_may_be_stale: bool         # True if > 4 hours old
    has_new_activity: bool           # Commits/files since last sync
    staleness_reason: str | None     # Why it's considered stale
```

---

## Implementation Phases

### Phase 1: Core Snapshot Function (2-3 days)

**Goal**: Single function that both Dashboard and fo_init can use.

**New File**: `src/core/project_snapshot.py`

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path


@dataclass
class DeclaredState:
    """What the user/agent said about the work."""
    goal: str = ""
    last_change: str = ""
    next_step: str = ""
    work_area: str = ""
    open_items: List[str] = field(default_factory=list)
    updated_at: Optional[datetime] = None


@dataclass
class RecordedKnowledge:
    """What FixOnce has recorded."""
    recent_decisions: List[Dict] = field(default_factory=list)
    recent_solutions: List[Dict] = field(default_factory=list)
    recent_insights: List[Dict] = field(default_factory=list)
    avoid_patterns: List[Dict] = field(default_factory=list)
    pending_reviews: int = 0
    total_decisions: int = 0
    total_solutions: int = 0
    total_insights: int = 0


@dataclass
class LiveEvidence:
    """What we can observe right now."""
    branch: str = ""
    uncommitted_files: List[str] = field(default_factory=list)
    recent_commits: List[Dict] = field(default_factory=list)
    has_uncommitted: bool = False
    tests_passing: Optional[bool] = None


@dataclass
class FreshnessInfo:
    """How fresh is the declared state?"""
    state_updated_at: Optional[datetime] = None
    evidence_computed_at: Optional[datetime] = None
    state_age_hours: float = 0.0
    state_may_be_stale: bool = False
    has_new_activity: bool = False
    staleness_reason: Optional[str] = None


@dataclass
class ProjectSnapshot:
    """Complete project state at a point in time."""
    # Identity
    project_id: str
    project_name: str
    working_dir: str
    
    # Three layers
    state: DeclaredState
    knowledge: RecordedKnowledge
    evidence: LiveEvidence
    
    # Meta
    freshness: FreshnessInfo
    snapshot_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API/Dashboard."""
        from dataclasses import asdict
        return asdict(self)


def get_project_snapshot(
    project_id: str,
    working_dir: str,
    include_evidence: bool = True,
) -> ProjectSnapshot:
    """
    Build a complete project snapshot.
    
    This is the SINGLE SOURCE OF TRUTH for project state.
    Both Dashboard and fo_init use this function.
    
    Args:
        project_id: The resolved project ID
        working_dir: Project working directory
        include_evidence: Whether to compute git/filesystem state
        
    Returns:
        Complete ProjectSnapshot
    """
    now = datetime.now()
    project_name = Path(working_dir).name
    
    # Layer 1: Declared State (from storage)
    state = _load_declared_state(project_id)
    
    # Layer 2: Recorded Knowledge (query storage)
    knowledge = _query_recorded_knowledge(project_id, working_dir)
    
    # Layer 3: Live Evidence (compute fresh)
    if include_evidence:
        evidence = _compute_live_evidence(working_dir)
    else:
        evidence = LiveEvidence()
    
    # Freshness detection
    freshness = _compute_freshness(state, evidence, now)
    
    return ProjectSnapshot(
        project_id=project_id,
        project_name=project_name,
        working_dir=working_dir,
        state=state,
        knowledge=knowledge,
        evidence=evidence,
        freshness=freshness,
        snapshot_at=now,
    )


def _load_declared_state(project_id: str) -> DeclaredState:
    """Load the declared state from project storage."""
    from core.project_context import ProjectContext
    
    project_file = ProjectContext.get_project_file(project_id)
    if not project_file.exists():
        return DeclaredState()
    
    try:
        import json
        with open(project_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        intent = data.get("live_record", {}).get("intent", {})
        
        updated_at = None
        if intent.get("updated_at"):
            try:
                updated_at = datetime.fromisoformat(
                    intent["updated_at"].replace('Z', '+00:00')
                )
            except:
                pass
        
        return DeclaredState(
            goal=intent.get("current_goal", ""),
            last_change=intent.get("last_change", ""),
            next_step=intent.get("next_step", ""),
            work_area=intent.get("work_area", ""),
            open_items=intent.get("open_items", []),
            updated_at=updated_at,
        )
    except Exception:
        return DeclaredState()


def _query_recorded_knowledge(project_id: str, working_dir: str) -> RecordedKnowledge:
    """Query recorded knowledge from storage."""
    try:
        from core.committed_knowledge import read_committed_knowledge
        ck = read_committed_knowledge(working_dir)
    except:
        ck = {}
    
    # Get counts
    decisions = ck.get("decisions", [])
    solutions = ck.get("solutions", [])
    insights = ck.get("insights", [])
    avoid = ck.get("avoid", [])
    
    # Sort by timestamp, get recent
    def sort_by_time(items):
        return sorted(
            [i for i in items if isinstance(i, dict)],
            key=lambda x: x.get("timestamp", ""),
            reverse=True
        )
    
    # Count pending reviews
    pending_reviews = 0
    try:
        from core.pending_memories import get_pending_count
        pending_reviews = get_pending_count()
    except:
        pass
    
    return RecordedKnowledge(
        recent_decisions=sort_by_time(decisions)[:5],
        recent_solutions=sort_by_time(solutions)[:5],
        recent_insights=sort_by_time(insights)[:3],
        avoid_patterns=sort_by_time(avoid)[:3],
        pending_reviews=pending_reviews,
        total_decisions=len(decisions),
        total_solutions=len(solutions),
        total_insights=len(insights),
    )


def _compute_live_evidence(working_dir: str) -> LiveEvidence:
    """Compute live evidence from git and filesystem."""
    import subprocess
    
    evidence = LiveEvidence()
    
    try:
        # Branch
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            evidence.branch = result.stdout.strip()
        
        # Uncommitted files
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            evidence.uncommitted_files = [
                line[3:] for line in result.stdout.strip().split('\n')
                if line
            ]
            evidence.has_uncommitted = len(evidence.uncommitted_files) > 0
        
        # Recent commits
        result = subprocess.run(
            ["git", "log", "-5", "--oneline", "--format=%h|%s|%ci"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                parts = line.split('|', 2)
                if len(parts) >= 2:
                    evidence.recent_commits.append({
                        "hash": parts[0],
                        "message": parts[1],
                        "date": parts[2] if len(parts) > 2 else "",
                    })
    except Exception:
        pass
    
    return evidence


def _compute_freshness(
    state: DeclaredState,
    evidence: LiveEvidence,
    now: datetime,
) -> FreshnessInfo:
    """Determine how fresh the declared state is."""
    freshness = FreshnessInfo(evidence_computed_at=now)
    
    if not state.updated_at:
        freshness.state_may_be_stale = True
        freshness.staleness_reason = "No fo_sync recorded"
        return freshness
    
    freshness.state_updated_at = state.updated_at
    
    # Calculate age
    try:
        # Handle timezone-naive comparison
        state_time = state.updated_at
        if state_time.tzinfo:
            state_time = state_time.replace(tzinfo=None)
        
        age = now - state_time
        freshness.state_age_hours = age.total_seconds() / 3600
        
        # Stale if > 4 hours
        if freshness.state_age_hours > 4:
            freshness.state_may_be_stale = True
            freshness.staleness_reason = f"Last synced {freshness.state_age_hours:.1f} hours ago"
        
        # Check if there's new activity since last sync
        if evidence.recent_commits:
            latest_commit_date = evidence.recent_commits[0].get("date", "")
            if latest_commit_date:
                try:
                    commit_time = datetime.fromisoformat(latest_commit_date.replace(' ', 'T'))
                    if commit_time.tzinfo:
                        commit_time = commit_time.replace(tzinfo=None)
                    if commit_time > state_time:
                        freshness.has_new_activity = True
                        if not freshness.state_may_be_stale:
                            freshness.state_may_be_stale = True
                            freshness.staleness_reason = "New commits since last sync"
                except:
                    pass
        
        if evidence.has_uncommitted and not freshness.has_new_activity:
            freshness.has_new_activity = True
    except Exception:
        pass
    
    return freshness
```

**Changes to existing files:**

1. `src/core/__init__.py` - Export new module
2. No other changes in Phase 1

---

### Phase 2: Snapshot Renderers (2-3 days)

**Goal**: Create renderers that present the same snapshot differently.

**New File**: `src/core/snapshot_renderer.py`

```python
from core.project_snapshot import ProjectSnapshot


def render_snapshot_for_agent(
    snapshot: ProjectSnapshot,
    include_priorities: bool = True,
) -> str:
    """
    Render snapshot as natural language opener for AI agents.
    
    This replaces _format_minimal_init() logic.
    """
    lines = [f"🧠 Back to {snapshot.project_name}"]
    lines.append("")
    
    # Priorities section (errors, reviews, etc.)
    # ... (reuse existing _nav_priorities logic)
    
    # Declared state
    if snapshot.state.goal:
        lines.append(snapshot.state.goal)
        if snapshot.state.work_area:
            lines.append(f"Area: {snapshot.state.work_area}")
        lines.append("")
    
    if snapshot.state.last_change:
        lines.append(f"Last:\n{snapshot.state.last_change}.")
    if snapshot.state.next_step:
        lines.append(f"Next:\n{snapshot.state.next_step}.")
    if snapshot.state.last_change or snapshot.state.next_step:
        lines.append("")
    
    # Knowledge stats
    k = snapshot.knowledge
    if k.total_decisions or k.total_solutions or k.total_insights:
        stats = []
        if k.total_decisions:
            stats.append(f"{k.total_decisions} Decisions")
        if k.total_solutions:
            stats.append(f"{k.total_solutions} Solved Bugs")
        if k.total_insights:
            stats.append(f"{k.total_insights} Insights")
        lines.append(f"📊 Project Knowledge: {' · '.join(stats)}")
        lines.append("")
    
    # Freshness warning
    if snapshot.freshness.state_may_be_stale:
        lines.append(f"⚠️ {snapshot.freshness.staleness_reason}")
        lines.append("")
    
    lines.append("💾 Progress synced automatically")
    lines.append("")
    
    # Suggested action
    if snapshot.state.next_step:
        lines.append(f"→ Suggested: {snapshot.state.next_step}")
    
    lines.append("")
    lines.append("Ready.")
    
    return "\n".join(lines)


def render_snapshot_for_dashboard(snapshot: ProjectSnapshot) -> dict:
    """
    Render snapshot as structured JSON for Dashboard API.
    
    This provides the same data in a format suitable for UI rendering.
    """
    return {
        "project": {
            "id": snapshot.project_id,
            "name": snapshot.project_name,
            "path": snapshot.working_dir,
        },
        "state": {
            "goal": snapshot.state.goal,
            "last_change": snapshot.state.last_change,
            "next_step": snapshot.state.next_step,
            "work_area": snapshot.state.work_area,
            "open_items": snapshot.state.open_items,
            "updated_at": snapshot.state.updated_at.isoformat() if snapshot.state.updated_at else None,
        },
        "knowledge": {
            "recent_decisions": snapshot.knowledge.recent_decisions,
            "recent_solutions": snapshot.knowledge.recent_solutions,
            "recent_insights": snapshot.knowledge.recent_insights,
            "avoid_patterns": snapshot.knowledge.avoid_patterns,
            "pending_reviews": snapshot.knowledge.pending_reviews,
            "totals": {
                "decisions": snapshot.knowledge.total_decisions,
                "solutions": snapshot.knowledge.total_solutions,
                "insights": snapshot.knowledge.total_insights,
            }
        },
        "evidence": {
            "branch": snapshot.evidence.branch,
            "uncommitted_files": snapshot.evidence.uncommitted_files,
            "has_uncommitted": snapshot.evidence.has_uncommitted,
            "recent_commits": snapshot.evidence.recent_commits,
        },
        "freshness": {
            "state_updated_at": snapshot.freshness.state_updated_at.isoformat() if snapshot.freshness.state_updated_at else None,
            "state_age_hours": snapshot.freshness.state_age_hours,
            "may_be_stale": snapshot.freshness.state_may_be_stale,
            "has_new_activity": snapshot.freshness.has_new_activity,
            "reason": snapshot.freshness.staleness_reason,
        },
        "snapshot_at": snapshot.snapshot_at.isoformat(),
    }
```

---

### Phase 3: Integration (2-3 days)

**Goal**: Replace existing code to use unified snapshot.

#### 3.1 Update fo_init

**File**: `src/mcp_server/mcp_memory_server_v2.py`

Replace `_format_minimal_init()` with:

```python
def _format_minimal_init(working_dir: str, task_hint: str = "") -> str:
    """Format session opener using unified snapshot."""
    from core.project_snapshot import get_project_snapshot
    from core.snapshot_renderer import render_snapshot_for_agent
    from core.project_context import ProjectContext
    
    project_id = ProjectContext.from_path(working_dir)
    snapshot = get_project_snapshot(project_id, working_dir)
    
    # Handle error gates (auto-fixes, live errors)
    # ... (keep existing gate logic, inject into snapshot)
    
    return render_snapshot_for_agent(snapshot)
```

#### 3.2 Add Dashboard API Endpoint

**File**: `src/api/snapshot.py` (new)

```python
from flask import Blueprint, jsonify, request
from core.project_snapshot import get_project_snapshot
from core.snapshot_renderer import render_snapshot_for_dashboard

snapshot_bp = Blueprint('snapshot', __name__)


@snapshot_bp.route('/api/snapshot', methods=['GET'])
def get_snapshot():
    """Get unified project snapshot for dashboard."""
    from api import resolve_project_id_for_request
    
    project_id, error = resolve_project_id_for_request(request)
    if error:
        return jsonify({"error": error}), 400
    
    # Get working_dir from project registry
    from managers.multi_project_manager import get_project_working_dir
    working_dir = get_project_working_dir(project_id)
    
    if not working_dir:
        return jsonify({"error": "Project working directory not found"}), 404
    
    snapshot = get_project_snapshot(project_id, working_dir)
    return jsonify(render_snapshot_for_dashboard(snapshot))


@snapshot_bp.route('/api/snapshot/agent-opener', methods=['GET'])
def get_agent_opener():
    """Get the same opener an AI agent would see."""
    from api import resolve_project_id_for_request
    
    project_id, error = resolve_project_id_for_request(request)
    if error:
        return jsonify({"error": error}), 400
    
    from managers.multi_project_manager import get_project_working_dir
    working_dir = get_project_working_dir(project_id)
    
    if not working_dir:
        return jsonify({"error": "Project working directory not found"}), 404
    
    snapshot = get_project_snapshot(project_id, working_dir)
    
    from core.snapshot_renderer import render_snapshot_for_agent
    opener = render_snapshot_for_agent(snapshot)
    
    return jsonify({"opener": opener})
```

#### 3.3 Register Blueprint

**File**: `src/server.py`

```python
from api.snapshot import snapshot_bp
app.register_blueprint(snapshot_bp)
```

---

### Phase 4: Polish & Validation (2-3 days)

1. **Tests**
   - `test_project_snapshot.py` - Snapshot generation
   - `test_snapshot_renderer.py` - Both renderers
   - `test_snapshot_api.py` - API endpoints
   - `test_snapshot_consistency.py` - Dashboard == fo_init

2. **Cache Layer** (optional)
   - Add 5-10 second cache for Dashboard requests
   - Invalidate on fo_sync

3. **Migration**
   - Update Dashboard frontend to use `/api/snapshot`
   - Deprecate old status endpoints gradually

---

## Files Changed Summary

### New Files
| File | Purpose |
|------|---------|
| `src/core/project_snapshot.py` | Core snapshot model + builder |
| `src/core/snapshot_renderer.py` | Agent + Dashboard renderers |
| `src/api/snapshot.py` | REST API for snapshot |
| `tests/test_project_snapshot.py` | Unit tests |
| `tests/test_snapshot_renderer.py` | Renderer tests |
| `tests/test_snapshot_api.py` | API tests |

### Modified Files
| File | Change |
|------|--------|
| `src/mcp_server/mcp_memory_server_v2.py` | Replace `_format_minimal_init` |
| `src/server.py` | Register snapshot blueprint |
| `src/core/__init__.py` | Export new modules |

### Deprecated (Phase 4+)
| File/Function | Replacement |
|---------------|-------------|
| `_format_minimal_init()` | `render_snapshot_for_agent()` |
| Parts of `system_status.py` | `get_project_snapshot()` |

---

## Validation Criteria

### Must Pass

1. **Consistency Test**
   ```python
   def test_dashboard_matches_agent():
       snapshot = get_project_snapshot(project_id, working_dir)
       
       dashboard_view = render_snapshot_for_dashboard(snapshot)
       agent_view = render_snapshot_for_agent(snapshot)
       
       # Same core data
       assert dashboard_view["state"]["goal"] in agent_view
       assert dashboard_view["state"]["next_step"] in agent_view
   ```

2. **Freshness Test**
   ```python
   def test_staleness_detected():
       # fo_sync 5 hours ago
       # New commit 1 hour ago
       snapshot = get_project_snapshot(...)
       assert snapshot.freshness.state_may_be_stale
       assert snapshot.freshness.has_new_activity
   ```

3. **Evidence Always Fresh**
   ```python
   def test_evidence_never_cached():
       # Make commit
       subprocess.run(["git", "commit", ...])
       
       # Snapshot immediately reflects it
       snapshot = get_project_snapshot(...)
       assert "new-commit-hash" in [c["hash"] for c in snapshot.evidence.recent_commits]
   ```

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Performance regression | Cache dashboard requests; evidence is fast (<100ms) |
| fo_sync not called | Freshness warning shows in both views |
| Breaking existing Dashboard | New endpoint `/api/snapshot`, old endpoints stay |
| Git timeout | Existing timeout handling preserved |

---

## Rollout Plan

1. **Week 1**: Phase 1+2 (Core + Renderers)
   - Internal testing only
   - Old paths still work

2. **Week 2**: Phase 3 (Integration)
   - fo_init uses snapshot
   - Dashboard has new endpoint (not yet used)
   - A/B comparison possible

3. **Week 3**: Phase 4 (Polish)
   - Dashboard frontend migrates
   - Old endpoints deprecated
   - Documentation updated

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Stale opener incidents | 0 (currently: occasional) |
| Dashboard-agent consistency | 100% |
| fo_init latency | <200ms (current: ~150ms) |
| Dashboard /api/snapshot latency | <300ms |
