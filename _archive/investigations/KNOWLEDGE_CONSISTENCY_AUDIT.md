# Knowledge Consistency Audit

## Executive Summary

**Status: RESOLVED** ✅

**Root Cause** (FIXED): The system had TWO independent data sources for knowledge counts:

| Data Source | Location | Field Name | Previous Count |
|-------------|----------|------------|----------------|
| Project Memory | `~/.fixonce/projects_v2/{id}.json` | `debug_sessions` | 64 (4 corrupted) |
| Committed Knowledge | `{project}/.fixonce/solutions.json` | `solutions` | 60 (correct) |

**Resolution**: Created `get_canonical_knowledge_counts()` in `core/knowledge_counters.py` as the single source of truth. All consumers now use Committed Knowledge (the authoritative source).

**Verified Counts** (all sources now match):
- Tray: 100 Decisions, 60 Solved, 14 Avoid
- Dashboard: 100 Decisions, 60 Solved, 14 Avoid  
- fo_init: 100 Decisions, 60 Solved, 14 Avoid

The 4 discrepant records in Project Memory were CORRUPTED/INVALID entries with empty problem/solution fields created during dashboard-review.

---

## All Knowledge Count Computation Locations

### 1. CANONICAL COUNTER (should be single source)

| File | Function | Data Source | Filtering | Used By |
|------|----------|-------------|-----------|---------|
| `core/knowledge_counters.py:21` | `get_live_project_counters(memory)` | Project Memory | Superseded filtered | Tray, /api/status |
| `core/project_snapshot.py:279` | `_query_recorded_knowledge(working_dir)` | Committed Knowledge | Superseded filtered | Dashboard, fo_init |

**PROBLEM**: These are two different functions reading from two different data sources.

---

### 2. TRAY

| File | Function | Data Source | Filtering | Notes |
|------|----------|-------------|-----------|-------|
| `api/status.py:1733` | `api_tray_status()` | `get_live_project_counters(memory)` | Yes | Reads from PROJECT MEMORY |

```python
# Line 1733
live_counts = get_live_project_counters(memory)
tray_counts = {
    "decisions": live_counts["decisions"],
    "solved": live_counts["solved"],  # debug_sessions = 64
    "avoid": live_counts["avoid"],
}
```

**Action Required**: Should use canonical provider.

---

### 3. DASHBOARD (/api/snapshot)

| File | Function | Data Source | Filtering | Notes |
|------|----------|-------------|-----------|-------|
| `api/snapshot.py:92` | `get_snapshot()` | `get_project_snapshot()` | Yes | Reads from COMMITTED KNOWLEDGE |
| `core/project_snapshot.py:435` | `get_project_snapshot()` | `_query_recorded_knowledge()` | Yes | Via committed_knowledge |

```python
# project_snapshot.py:316-318
counts = KnowledgeCounts(
    decisions=len(active_decisions),
    solutions=len(active_solutions),  # solutions.json = 60
    avoid=len(avoid_patterns),
    insights=len(insights),
)
```

**Action Required**: Should use canonical provider.

---

### 4. fo_init (MCP)

| File | Function | Data Source | Filtering | Notes |
|------|----------|-------------|-----------|-------|
| `mcp_server/mcp_memory_server_v2.py:10715` | `_format_minimal_init()` | `get_project_snapshot()` | Yes | Via project_snapshot.py |
| `mcp_server/mcp_memory_server_v2.py:10882` | Knowledge counts display | `snapshot.knowledge_counts` | Yes | From snapshot |

**Action Required**: Should use canonical provider (already uses project_snapshot).

---

### 5. /api/status (Dashboard legacy)

| File | Function | Data Source | Filtering | Notes |
|------|----------|-------------|-----------|-------|
| `api/status.py:973` | `api_get_status()` | `get_live_project_counters(memory)` | Yes | Reads from PROJECT MEMORY |

```python
# Line 973-980
live_counts = get_live_project_counters(memory)
snapshot["knowledge"]["total_decisions"] = live_counts["decisions"]
snapshot["knowledge"]["total_avoids"] = live_counts["avoid"]
snapshot["knowledge"]["total_solutions"] = live_counts["solved"]  # 64
```

**Action Required**: Remove or redirect to canonical provider. Currently conflicts with /api/snapshot.

---

### 6. REORIENTATION MODE (fo_init when stale)

| File | Function | Data Source | Filtering | Notes |
|------|----------|-------------|-----------|-------|
| `mcp_server/mcp_memory_server_v2.py:10804-10808` | Reorientation briefing | `get_live_project_counters(data)` | Yes | PROJECT MEMORY |

```python
# Line 10804-10808
from core.knowledge_counters import get_live_project_counters, format_project_knowledge_line
counters = get_live_project_counters(data)  # PROJECT MEMORY
knowledge_stats = ""
if any(counters.values()):
    knowledge_stats = format_project_knowledge_line(counters)
```

**Action Required**: Should use canonical provider.

---

### 7. OTHER INLINE COMPUTATIONS

| File | Line | Computation | Data Source | Should Exist? |
|------|------|-------------|-------------|---------------|
| `core/active_project_resolver.py:406` | `len(memory.get("decisions", []))` | Project Memory | NO - use canonical |
| `core/safe_file.py:582` | `len(lessons.get('insights', []))` | Project Memory | YES - recovery logic |
| `core/committed_knowledge.py:726` | `len(quality_decisions)` | Committed Knowledge | YES - commit stats |
| `managers/multi_project_manager.py:1249` | `len(memory.get('decisions', []))` | Project Memory | NO - use canonical |
| `managers/multi_project_manager.py:1576` | `len(memory.get(...))` | Project Memory | NO - use canonical |
| `api/memory.py:47` | `len(decisions)` | Project Memory | YES - raw listing |
| `api/knowledge.py:54` | `len(pending_ids.get(...))` | Pending | YES - pending counts |
| `api/openai_adapter.py:423` | `len(decisions)` | Project Memory | NO - use canonical |

---

### 8. DATA SOURCE SCHEMA DIFFERENCES

#### Project Memory (`~/.fixonce/projects_v2/{id}.json`)
```json
{
  "decisions": [...],
  "avoid": [...],
  "debug_sessions": [...]  // <-- "solutions" are called "debug_sessions" here
}
```

#### Committed Knowledge (`{project}/.fixonce/`)
```json
// decisions.json
{ "decisions": [...] }

// solutions.json  
{ "solutions": [...] }  // <-- Different field name!

// avoid.json
{ "patterns": [...] }  // <-- Different field name!
```

**PROBLEM**: Different field names cause independent counting logic.

---

## Proposed Architecture

### Single Canonical Provider

```python
# core/knowledge_counters.py

def get_canonical_knowledge_counts(
    project_id: str,
    working_dir: str,
) -> KnowledgeCounts:
    """
    THE SINGLE SOURCE OF TRUTH for knowledge counts.
    
    ALL UIs and APIs must use this function.
    No inline counting logic anywhere else.
    
    Data source hierarchy:
    1. Committed knowledge (.fixonce/ in project) - primary
    2. Project memory (projects_v2/) - fallback only
    
    Returns:
        KnowledgeCounts with decisions, solutions, avoid, insights
    """
    # Read from committed_knowledge (single source)
    from core.committed_knowledge import read_committed_knowledge
    ck = read_committed_knowledge(working_dir)
    
    # Filter superseded
    decisions = [d for d in ck.get("decisions", []) if not d.get("superseded")]
    solutions = [s for s in ck.get("solutions", []) if not s.get("superseded")]
    avoid = ck.get("avoid", [])
    insights = ck.get("insights", [])
    
    return KnowledgeCounts(
        decisions=len(decisions),
        solutions=len(solutions),
        avoid=len(avoid),
        insights=len(insights),
    )
```

### Migration Plan

1. **Add canonical provider** to `core/knowledge_counters.py`
2. **Update all consumers**:
   - Tray (`api/status.py:1733`) → use `get_canonical_knowledge_counts()`
   - /api/status (`api/status.py:973`) → use canonical or remove (defer to /api/snapshot)
   - fo_init reorientation → use canonical
   - multi_project_manager → use canonical
   - active_project_resolver → use canonical
3. **Deprecate** `get_live_project_counters()` after migration
4. **Remove** inline `len()` calls that compute counts
5. **Sync data sources** - ensure debug_sessions ↔ solutions stay aligned

### Data Source Decision

**CHOOSE ONE PRIMARY SOURCE**:

| Option | Pro | Con |
|--------|-----|-----|
| Committed Knowledge | Git-portable, team-shared, canonical | Requires commit to update |
| Project Memory | Real-time, local | Not portable, not shared |

**Recommendation**: Committed Knowledge as primary, with real-time overlay from project memory for uncommitted items.

---

## Summary Table: Migration Status

| Component | Previous Source | New Source | Status |
|-----------|----------------|------------|--------|
| Tray | `get_live_project_counters` | `get_canonical_knowledge_counts` | ✅ DONE |
| /api/snapshot | `_query_recorded_knowledge` | Uses unified snapshot | ✅ DONE |
| fo_init | `get_project_snapshot` | Uses unified snapshot | ✅ DONE |
| /api/status | `get_live_project_counters` | `get_canonical_knowledge_counts` | ✅ DONE |
| Reorientation | `get_live_project_counters` | `get_canonical_knowledge_counts` | ✅ DONE |
| multi_project_manager | inline `len()` | `get_canonical_knowledge_counts` | ✅ DONE |
| active_project_resolver | inline `len()` | `get_canonical_knowledge_counts` | ✅ DONE |

### Files Modified
- `src/core/knowledge_counters.py` - Added `CanonicalKnowledgeCounts` class and `get_canonical_knowledge_counts()`
- `src/api/status.py` - Updated Tray endpoint and /api/status to use canonical provider
- `src/mcp_server/mcp_memory_server_v2.py` - Updated Navigator V1 and Reorientation mode
- `src/managers/multi_project_manager.py` - Updated `list_all_projects()`
- `src/core/active_project_resolver.py` - Updated `get_active_project_diagnostics()`
- `tests/test_project_snapshot.py` - Added tests for canonical provider
