# Handoff Synchronization Architecture — Post-Mortem

**Date**: 2026-07-19  
**Scope**: Complete analysis of "Last / Next / Goal" state across sessions

---

## Part 1 — Complete Lifecycle

### User Work → Opening Context Flow

```
User (performs work)
       │
       ├──────────────────────────────────────────────────────┐
       │                                                      │
       ▼                                                      ▼
  fo_decide()                                           fo_solved()
       │                                                      │
       ▼                                                      ▼
  log_decision()                                        log_solution()
       │                                                      │
       ▼                                                      ▼
  decisions.json (project .fixonce)         debug_sessions[] (projects_v2)
       │                                                      │
       └──────────────────────┬───────────────────────────────┘
                              │
                              ▼
                        fo_sync()
                              │
                              ▼
               _update_work_context_lightweight()
                              │
                              ├─────────────────────────────────┐
                              │                                 │
                              ▼                                 ▼
               _load_project_lightweight()          _mark_unreported_work_synced()
                              │                                 │
                              ▼                                 ▼
               projects_v2/PROJECT_ID.json          unreported_work.json
                              │                     (dirty=false, last_sync_at)
                              ▼
               live_record.intent UPDATE:
               - current_goal
               - work_area
               - last_change
               - last_file
               - next_step
               - updated_at
                              │
                              ▼
               _save_project_lightweight()
                              │
                              ▼
               projects_v2/PROJECT_ID.json (written)
                              │
                              ▼
                        [COMMIT]
                              │
                              ▼ (no fo_sync after commit)
                              
- - - - - - - - - NEW SESSION - - - - - - - - - - - - - - - -

                       fo_init(cwd)
                              │
                              ▼
               _resolve_init_working_dir()
                              │
                              ▼
                    _get_project_id()
                              │
                              ▼
                    _set_session()
                              │
                              ▼
               _persist_session()
                              │
                              ▼
               ensure_dashboard_project()
                              │
                              ▼
               _format_minimal_init()
                              │
                              ├─────────────────────────────────┐
                              │                                 │
                              ▼                                 ▼
               _load_project(project_id)         _get_resume_state(project_id)
                              │                                 │
                              ▼                                 ▼
               projects_v2/PROJECT_ID.json      projects_v2/PROJECT_ID.json
               → live_record.intent              → resume_state
                              │                                 │
                              └──────────────┬──────────────────┘
                                             │
                                             ▼
                              Compare timestamps:
                              intent.updated_at vs resume_state.updated_at
                                             │
                                             ▼ (fresher wins)
                              Extract: current_goal, last_change, next_step
                                             │
                                             ▼
                              Format opener string:
                              "🧠 Back to {project_name}
                               {current_goal}
                               Area: {work_area}
                               Last: {last_change}
                               Next: {next_step}
                               📊 Project Knowledge: X Decisions · Y Solved Bugs
                               💾 Progress synced automatically
                               → Suggested: {next_step}
                               Ready."
                                             │
                                             ▼
                              Return to AI → Display to User
```

### Component-by-Component Breakdown

| Step | Function | Reads | Writes | Fields Changed | Owner |
|------|----------|-------|--------|----------------|-------|
| 1. User work | (external) | — | — | — | User |
| 2. fo_decide | `log_decision()` | projects_v2/X.json | decisions.json, projects_v2/X.json | decisions[], decision_conflicts[] | MCP Server |
| 3. fo_solved | `log_solution()` | projects_v2/X.json | projects_v2/X.json | debug_sessions[] | MCP Server |
| 4. fo_sync | `_update_work_context_lightweight()` | projects_v2/X.json | projects_v2/X.json, unreported_work.json | live_record.intent.*, dirty=false | MCP Server |
| 5. (commit) | git | — | — | — | User |
| 6. fo_init | `_format_minimal_init()` | projects_v2/X.json | session_registry.json, active_project.json | — | MCP Server |
| 7. Display | — | — | — | — | AI Agent |

---

## Part 2 — Source of Truth Analysis

### Storage Locations

| Location | Purpose | Owner | Lifetime | Type | Staleness Risk |
|----------|---------|-------|----------|------|----------------|
| **~/.fixonce/projects_v2/{ID}.json** | Primary project memory | MCP Server | Permanent | CANONICAL | LOW |
| └ `live_record.intent` | Current goal/progress state | fo_sync | Until next sync | CANONICAL | **HIGH** - not updated after commits |
| └ `resume_state` | Operational work state | save_resume_state | Until cleared | CANONICAL | MEDIUM |
| └ `decisions[]` | Recorded decisions | fo_decide | Permanent | CANONICAL | LOW |
| └ `debug_sessions[]` | Solved bugs | fo_solved | Permanent | CANONICAL | LOW |
| └ `decision_conflicts[]` | Unresolved conflicts | fo_decide | Until resolved | CANONICAL | MEDIUM |
| └ `ai_handoffs[]` | Historical handoffs | fo_init | Permanent | ARCHIVE | LOW |
| └ `agent_audit[]` | Agent behavior audit | All tools | Permanent | AUDIT | LOW |
| **~/.fixonce/unreported_work.json** | Dirty state tracking | PostToolUse hook | Until sync | OPERATIONAL | MEDIUM |
| └ `entries.{ID}:{actor}` | Per-actor dirty state | mark_work/mark_synced | Until sync | OPERATIONAL | LOW |
| **~/.fixonce/activity_log.json** | Activity feed | _log_mcp_activity | 100 entries | CACHE | **HIGH** - currently empty |
| **~/.fixonce/session_registry.json** | Live AI sessions | fo_init, activity API | Session lifetime | OPERATIONAL | LOW |
| **~/.fixonce/active_project.json** | Dashboard selection | ensure_dashboard_project | Until changed | DERIVED | MEDIUM |
| **~/.fixonce/project_index.json** | Project catalog | catalog migration | Permanent | INDEX | LOW |
| **~/.fixonce/runtime.json** | Server port/pid | Server startup | Until shutdown | RUNTIME | LOW |
| **project/.fixonce/team_memory.json** | Per-project team context | Various | Permanent | CANONICAL | MEDIUM |
| └ `handoffs[]` | Legacy handoff records | fo_init | Permanent | ARCHIVE | LOW |
| **project/.fixonce/decisions.json** | Committed decisions | commit flow | Permanent | CANONICAL | LOW |
| **project/.fixonce/insights.json** | Committed insights | commit flow | Permanent | CANONICAL | LOW |

### Canonical vs Cache Classification

**CANONICAL** (source of truth):
- `projects_v2/{ID}.json` → All persistent project state
- `project/.fixonce/*.json` → Committed knowledge

**OPERATIONAL** (transient state):
- `unreported_work.json` → Dirty tracking
- `session_registry.json` → Live sessions
- `runtime.json` → Server port

**DERIVED** (computed from canonical):
- `active_project.json` → Dashboard selection
- `project_index.json` → Project catalog

**CACHE** (can be rebuilt):
- `activity_log.json` → Activity feed
- `ai_connections.json` → Connection state

---

## Part 3 — State Transitions

```
                    ┌────────────────────────────────────┐
                    │                                    │
                    ▼                                    │
              ┌─────────┐                               │
              │  CLEAN  │◀─────────────────────────────┐│
              └────┬────┘                              ││
                   │ User performs work                ││
                   │ (file_write, git_commit,          ││
                   │  fo_decide, fo_solved)            ││
                   ▼                                   ││
              ┌─────────┐                              ││
              │  DIRTY  │ ◀──────────────────────┐     ││
              └────┬────┘                        │     ││
                   │                             │     ││
          ┌────────┴────────┐                    │     ││
          │                 │                    │     ││
          ▼                 ▼                    │     ││
   ┌─────────────┐   ┌─────────────┐             │     ││
   │ UNSYNCED    │   │ COMMIT      │             │     ││
   │ (dirty=true)│   │ DETECTED    │─────────────┘     ││
   └──────┬──────┘   └─────────────┘                   ││
          │ fo_sync() called                           ││
          │ with all fields                            ││
          ▼                                            ││
   ┌─────────────┐                                     ││
   │  SYNCED     │─────────────────────────────────────┘│
   │ (dirty=false│                                      │
   │  intent     │                                      │
   │  updated)   │                                      │
   └──────┬──────┘                                      │
          │ New session starts                          │
          │ fo_init() called                            │
          ▼                                             │
   ┌─────────────┐                                      │
   │ SESSION     │──────────────────────────────────────┘
   │ INITIALIZED │
   └─────────────┘
```

### Transition Functions

| Transition | Trigger | Function | State Change |
|------------|---------|----------|--------------|
| CLEAN → DIRTY | File write | `mark_work()` | dirty=true, dirty_since=now |
| CLEAN → DIRTY | Git commit | `mark_work(kind="git_commit")` | dirty=true |
| CLEAN → DIRTY | fo_decide | `log_decision()` | dirty=true (implicit) |
| DIRTY → SYNCED | fo_sync | `_update_work_context_lightweight()` + `mark_synced()` | dirty=false, intent updated |
| DIRTY → DIRTY | Commit without sync | (none) | **BUG: intent not updated** |
| SYNCED → SESSION | fo_init | `_format_minimal_init()` | Session registered |
| SESSION → DIRTY | Any work | `mark_work()` | dirty=true |

---

## Part 4 — Failure Modes

### 4.1 fo_sync Never Called

**Scenario**: User completes work and commits without calling fo_sync.

**Detection**: 
- `unreported_work.json` shows `dirty=true` with `last_work_kind="git_commit"`
- `live_record.intent.updated_at` is older than commit timestamp

**Recovery**: Call fo_sync with correct last_change and next_step.

**Current Handling**: **NOT HANDLED** — No warning shown, stale opener displayed.

**Risk Level**: **CRITICAL** — This is exactly what happened.

---

### 4.2 fo_sync Failed

**Scenario**: fo_sync called but write failed (disk full, permission error, concurrent write).

**Detection**:
- `unreported_work.json` still shows `dirty=true`
- fo_sync returned error message

**Recovery**: Retry fo_sync.

**Current Handling**: Error returned to AI, but no persistent retry mechanism.

**Risk Level**: **MEDIUM** — Failure is visible but not enforced.

---

### 4.3 Write Succeeded but Wrong Project

**Scenario**: AI called fo_sync but session was pointing to wrong project.

**Detection**:
- Check session.project_id vs expected project_id
- Compare working_dir in session vs actual cwd

**Recovery**: Re-init with correct cwd, call fo_sync again.

**Current Handling**: Session validation exists but can be bypassed.

**Risk Level**: **LOW** — Session initialization is robust.

---

### 4.4 Stale Cache

**Scenario**: MCP server has old data in memory, newer data on disk.

**Detection**:
- Compare in-memory data timestamp vs file mtime
- File hash comparison

**Recovery**: Force reload from disk.

**Current Handling**: `_load_project()` reads from disk each time, no persistent cache.

**Risk Level**: **LOW** — No caching in MCP server.

---

### 4.5 Wrong Project Selected

**Scenario**: active_project.json points to different project than cwd.

**Detection**:
- Compare cwd project_id vs active_project.json
- session_registry shows different project

**Recovery**: Call fo_init(cwd) to re-sync.

**Current Handling**: Handled by `ensure_dashboard_project()`.

**Risk Level**: **LOW** — Robust handling.

---

### 4.6 Duplicate State

**Scenario**: Same data stored in multiple locations with divergent values.

**Detection**:
- Compare `live_record.intent` vs `resume_state`
- Compare `projects_v2` vs `team_memory`

**Recovery**: Use canonical source (projects_v2) and clear duplicates.

**Current Handling**: Freshness comparison exists but doesn't warn on divergence.

**Risk Level**: **MEDIUM** — Silent divergence possible.

---

### 4.7 Commit After Sync

**Scenario**: fo_sync called → commit → new session → stale opener.

**Detection**:
- Git commit timestamp > `intent.updated_at`
- `unreported_work` shows `last_work_kind="git_commit"` after `last_sync_at`

**Recovery**: Call fo_sync after commit.

**Current Handling**: **NOT HANDLED** — This is the exact bug.

**Risk Level**: **CRITICAL**

---

### 4.8 Interrupted Sync

**Scenario**: fo_sync started but process killed mid-write.

**Detection**:
- Partial JSON file
- Lock file exists but process dead

**Recovery**: atomic_json_update handles this with temp file + rename.

**Current Handling**: **HANDLED** — safe_file module provides atomic writes.

**Risk Level**: **LOW**

---

### 4.9 Concurrent Agents

**Scenario**: Claude and Codex both call fo_sync simultaneously.

**Detection**:
- session_registry shows multiple active sessions
- unreported_work has entries for multiple actors

**Recovery**: Three-way merge via `merge_concurrent_value()`.

**Current Handling**: **PARTIAL** — Merge exists but not always invoked.

**Risk Level**: **MEDIUM**

---

### 4.10 Multiple Repositories

**Scenario**: User switches between repos without proper handoff.

**Detection**:
- active_project.json doesn't match cwd
- session_registry shows different project_path

**Recovery**: fo_init(cwd) re-syncs to correct project.

**Current Handling**: **HANDLED** — fo_init always uses cwd.

**Risk Level**: **LOW**

---

## Part 5 — Protocol Audit

### Is there exactly one source of truth?

**VIOLATION**: Two sources for handoff context:
1. `live_record.intent` (updated by fo_sync)
2. `resume_state` (updated by save_resume_state)

Both are read by `_format_minimal_init()` with freshness comparison, but:
- Neither is definitively canonical
- Staleness detection is based on timestamp, not semantic validity
- A fresh but incomplete `resume_state` can override a complete but older `intent`

### Is there exactly one owner?

**VIOLATION**: Multiple writers to handoff state:
1. `fo_sync` → writes `live_record.intent`
2. `save_resume_state` → writes `resume_state`
3. No tool owns "sync after commit" responsibility

### Is there duplicated logic?

**VIOLATION**: Three places format opener context:
1. `_format_minimal_init()` (primary)
2. `format_resume_for_init()` (legacy)
3. `_handoff_details()` (for handoff records)

### Is there duplicated persistence?

**VIOLATION**: Handoff context stored in:
1. `projects_v2/{ID}.json → live_record.intent`
2. `projects_v2/{ID}.json → resume_state`
3. `projects_v2/{ID}.json → ai_handoffs[]`
4. `team_memory.json → handoffs[]`

### Is there duplicated state?

**VIOLATION**: Same conceptual "next step" in:
1. `intent.next_step`
2. `resume_state.next_recommended_action`
3. `handoffs[].next_action`

### Is there duplicated interpretation?

**VIOLATION**: Freshness comparison in `_format_minimal_init()` interprets two sources, choosing one. This is interpretation, not data retrieval.

---

## Part 6 — Product Improvements

### Critical

1. **Enforce fo_sync after commits**
   - Detect `git_commit` in unreported_work after last sync
   - Show warning in fo_init opener: "⚠️ Work committed but not synced"
   - Consider: Block "Ready" until sync is called

2. **Stale handoff detection**
   - Compare `intent.updated_at` vs git log
   - If commits exist after last sync, warn explicitly
   - Show exact commit hashes that are unsynced

3. **Single source of truth**
   - Remove `resume_state` → migrate to `intent`
   - OR: Make `resume_state` authoritative and deprecate `intent`
   - Never compare timestamps to choose between them

### High

4. **Handoff completeness validation**
   - Require `goal`, `last_change`, `next_step` in fo_sync
   - Warn if any field is empty after significant work

5. **Auto-sync on commit detection**
   - When PostToolUse sees `git_commit`, prompt AI to sync
   - Or: Auto-populate intent from commit message

6. **Activity log health monitoring**
   - Detect empty activity_log.json
   - Log write failures explicitly

7. **Unreported work warning in opener**
   - If `dirty=true` and `significant_files >= 3`, show in opener
   - Currently `should_show_unsynced_warning()` exists but isn't used in fo_init

### Medium

8. **Consolidate handoff persistence**
   - One location: `live_record.intent`
   - Archive handoffs to `ai_handoffs[]` only on explicit session close

9. **Decision conflict cleanup**
   - Auto-resolve AVOID_PATTERN_CONFLICT if unrelated
   - Show only PENDING_DECISION_REVIEW in opener

10. **Session registry cleanup**
    - Mark sessions stale after 24h without activity
    - Clear stale sessions on fo_init

11. **Regression tests**
    - Test: fo_sync updates intent correctly
    - Test: fo_init reads latest intent
    - Test: Commit after sync is detected
    - Test: Stale opener warning appears

### Low

12. **Dashboard sync status**
    - Show "Last synced: X ago" in dashboard
    - Show "Unsynced work: Y files" badge

13. **fo_sync return value**
    - Return what was actually written
    - Include timestamp for verification

14. **Handoff history viewer**
    - Dashboard section showing handoff timeline
    - Useful for debugging stale openers

---

## Part 7 — Final Verdict

### 1. Is the current handoff architecture fundamentally correct?

**NO.**

The architecture has the right primitives (`intent`, `unreported_work`, `fo_sync`) but violates single-source-of-truth by having both `intent` and `resume_state`. The freshness comparison is a workaround for not having a clear owner.

### 2. Is the stale opener caused by user workflow, architecture, or implementation?

**ARCHITECTURE + IMPLEMENTATION.**

- **Architecture**: No mechanism exists to enforce or detect "sync after commit"
- **Implementation**: `_format_minimal_init()` reads stale `intent` without checking git state
- **User workflow**: Not at fault — protocol should handle common patterns like commit-then-close

### 3. Is this an isolated issue or a class of bugs?

**CLASS OF BUGS: "State divergence after external events."**

Other instances of this class:
- Resume_state vs intent divergence
- Decision conflicts accumulating without resolution
- Activity log going empty
- Handoffs stored in multiple locations

### 4. Can this entire category of bugs be eliminated?

**YES.**

Single source of truth + event-driven sync + validation gates would eliminate divergence.

### 5. If yes, what architectural change would eliminate it completely?

**Core Protocol Architecture Change:**

```
┌─────────────────────────────────────────────────────────────┐
│                   HANDOFF STATE                             │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              live_record.intent                      │   │
│  │  (SINGLE CANONICAL SOURCE)                          │   │
│  │                                                      │   │
│  │  - current_goal                                      │   │
│  │  - work_area                                         │   │
│  │  - last_change                                       │   │
│  │  - next_step                                         │   │
│  │  - updated_at                                        │   │
│  │  - last_commit_hash   ← NEW: track git state        │   │
│  │  - sync_status        ← NEW: clean/dirty/stale      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  WRITES: Only fo_sync()                                    │
│  READS:  Only _format_minimal_init()                       │
│  VALIDATION: Intent must be fresher than last commit       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Implementation:**

1. **DELETE** `resume_state` — migrate to `intent`
2. **ADD** `last_commit_hash` to intent — track what git state was synced
3. **ADD** `sync_status` field: `clean`, `dirty`, `stale`
4. **MODIFY** fo_init:
   - Get latest commit hash
   - If `intent.last_commit_hash != latest_commit_hash`, set `sync_status=stale`
   - If `stale`, show warning: "⚠️ Work committed since last sync"
5. **MODIFY** fo_sync:
   - Always capture current commit hash
   - Set `sync_status=clean`
6. **REMOVE** duplicate handoff storage in `team_memory.json`

This eliminates the entire class by:
- Single owner (fo_sync)
- Single source (intent)
- Validation against external state (git)
- Explicit staleness detection

---

## Appendix: Files Involved

```
~/.fixonce/
├── projects_v2/
│   └── {PROJECT_ID}.json          ← Primary project memory
├── unreported_work.json           ← Dirty state tracking
├── session_registry.json          ← Live AI sessions
├── active_project.json            ← Dashboard selection
├── activity_log.json              ← Activity feed (currently empty)
├── project_index.json             ← Project catalog
├── runtime.json                   ← Server port/pid
└── ai_connections.json            ← AI connection state

project/.fixonce/
├── team_memory.json               ← Per-project team context
├── decisions.json                 ← Committed decisions
├── insights.json                  ← Committed insights
├── solutions.json                 ← Committed solutions
└── avoid.json                     ← Committed avoid patterns

src/mcp_server/mcp_memory_server_v2.py
├── fo_init()                      ← Line 10912
├── fo_sync()                      ← Line 11052
├── _format_minimal_init()         ← Line 10623
├── _update_work_context_lightweight() ← Line 6456
├── _load_project()                ← Line 4223
└── _mark_unreported_work_synced() ← Line 1211

src/core/
├── unreported_work.py             ← Dirty state module
├── resume_state.py                ← Resume state module
├── durable_memory.py              ← Atomic write module
├── session_registry.py            ← Session tracking
└── active_project_resolver.py     ← Project resolution
```
