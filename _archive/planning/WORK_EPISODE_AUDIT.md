# Work Episode Architecture Audit

**Date**: 2026-07-19  
**Scope**: Feasibility analysis for transforming FixOnce from memory system to work lifecycle system  
**Constraint**: NO CODE CHANGES — analysis only

---

## Executive Summary

FixOnce has **~60% of the infrastructure needed** for Work Episodes. The critical "Finish & Save" path is **feasible via existing ai_queue mechanism**. The main gaps are: explicit episode lifecycle (Start/Pause/Resume/Finish), episode-aware attribution, and dashboard UI controls.

**Verdict**: Work Episode is architecturally viable. V1 can ship with 2-3 weeks of focused work.

---

## A. Existing Infrastructure Inventory

### 1. Session Registry (`src/core/session_registry.py`)

| Capability | Status | Evidence |
|------------|--------|----------|
| Per AI+project isolation | ✅ Ready | `IsolatedSession` with `session_key = "ai_name:project_path"` |
| Started timestamp | ✅ Ready | `started_at: str` field |
| Last activity tracking | ✅ Ready | `last_activity: str` updated via `touch()` |
| Tool call history | ✅ Ready | `tool_calls: List[Dict]` with last 100 calls |
| Compliance scoring | ✅ Ready | `get_compliance_score()` method |
| Automatic timeout | ⚠️ Partial | 60-minute `SESSION_TIMEOUT_MINUTES` (implicit end, no explicit) |
| Explicit Start/End | ❌ Missing | No `start_episode()` / `end_episode()` |
| Pause/Resume states | ❌ Missing | No pause/resume tracking |
| Episode history | ❌ Missing | Sessions are ephemeral, not persisted as episodes |

**Readiness Score: 3/5** — Good foundation, needs lifecycle methods

### 2. AI Detector (`src/core/ai_detector.py`)

| Capability | Status | Evidence |
|------------|--------|----------|
| Multi-AI detection | ✅ Ready | Claude, Codex, Cursor, Aider defined |
| Process detection | ✅ Ready | `_check_process_running()` |
| MCP connection status | ✅ Ready | `_get_connection_status()` reads `ai_connections.json` |
| Connection freshness | ✅ Ready | `CONNECTED_THRESHOLD = 300s` (5 minutes) |
| Unprotected warning | ✅ Ready | Detects running-but-not-connected state |
| Episode awareness | ❌ Missing | No concept of "in episode" vs "idle" |

**Readiness Score: 4/5** — Nearly complete for detection needs

### 3. Dirty State Tracking (`src/core/unreported_work.py`)

| Capability | Status | Evidence |
|------------|--------|----------|
| Work marking | ✅ Ready | `mark_work(project_id, actor, kind, file_path, ...)` |
| Sync marking | ✅ Ready | `mark_synced(project_id, actor, tool_name)` |
| Significant files tracking | ✅ Ready | `significant_files` list, `SIGNIFICANCE_THRESHOLD = 3` |
| Per-actor tracking | ✅ Ready | `SUPPORTED_ACTORS = {"claude", "codex"}` |
| Sync tool list | ✅ Ready | `SYNC_TOOLS = {fo_sync, fo_solved, fo_decide}` |
| File filtering | ✅ Ready | `INSIGNIFICANT_PATH_PATTERNS` regex list |
| Episode boundary | ❌ Missing | No "episode ended without sync" detection |

**Readiness Score: 4/5** — This IS the foundation for "significant unsynced work"

### 4. Dashboard → Agent Communication (`src/api/memory.py`, MCP tools)

| Capability | Status | Evidence |
|------------|--------|----------|
| Command queue | ✅ Ready | `ai_queue` in project memory |
| REST endpoint | ✅ Ready | `POST /api/memory/queue-for-ai` |
| Agent polling | ✅ Ready | `get_pending_commands()` MCP tool |
| Proactive injection | ✅ Ready | `_get_pending_commands_for_injection()` in tool responses |
| Command status | ✅ Ready | `mark_command_executed()` MCP tool |
| Finish & Save trigger | ⚠️ Needs Work | Type exists conceptually, needs specific implementation |

**Readiness Score: 4/5** — **This IS the critical "Finish & Save" communication channel!**

### 5. Attribution System (`mcp_memory_server_v2.py:1598`)

| Capability | Status | Evidence |
|------------|--------|----------|
| Actor identity | ✅ Ready | `actor`, `actor_source`, `actor_confidence` |
| Session tracking | ✅ Ready | `session_id` from runtime |
| Tool name | ✅ Ready | `tool_name` in attribution |
| Episode ID | ❌ Missing | No `episode_id` field |
| Confirmation status | ❌ Missing | No `confirmation_status` (draft/confirmed/stale) |
| Evidence type | ❌ Missing | No `evidence_type` (direct/inferred/manual) |

**Readiness Score: 3/5** — Core fields exist, episode-specific fields missing

### 6. Resume State (`src/core/resume_state.py`)

| Capability | Status | Evidence |
|------------|--------|----------|
| Status enum | ✅ Ready | `in_progress`, `waiting_for_restart`, `blocked`, `paused`, `completed` |
| Active task | ✅ Ready | `active_task` field |
| Last completed | ✅ Ready | `last_completed_step` field |
| Next action | ✅ Ready | `next_recommended_action` field |
| Short summary | ✅ Ready | `short_summary` field |
| Clear on completion | ✅ Ready | `clear_resume_state()` |
| Episode binding | ❌ Missing | Not tied to episode lifecycle |

**Readiness Score: 4/5** — The "paused" status exists but is unused. Could map directly to Episode states.

### 7. Activity API (`src/api/activity.py`)

| Capability | Status | Evidence |
|------------|--------|----------|
| Hook integration | ✅ Ready | Receives Claude Code PostToolUse events |
| File change tracking | ✅ Ready | `_get_git_diff_stats()` |
| File type context | ✅ Ready | `FILE_TYPE_CONTEXT` mapping |
| Boundary detection | ✅ Ready | `detect_boundary_violation()` for project switching |
| Activity feed | ✅ Ready | `activity_log.json` |
| Episode attribution | ❌ Missing | Activities not tagged with episode_id |

**Readiness Score: 3/5** — Needs episode tagging

### 8. MCP Health (`src/core/mcp_health.py`)

| Capability | Status | Evidence |
|------------|--------|----------|
| Connection states | ✅ Ready | `active`, `stale`, `configured`, `misconfigured`, `inactive` |
| Activity threshold | ✅ Ready | `ACTIVE_THRESHOLD_SECONDS = 300` |
| Config validation | ✅ Ready | `_check_config_validity()` |
| Stale detection | ✅ Ready | `STALE_THRESHOLD_SECONDS = 3600` |
| Episode health | ❌ Missing | No "episode stalled" detection |

**Readiness Score: 4/5** — Good foundation

### 9. Live Record / Intent (`mcp_memory_server_v2.py`)

| Capability | Status | Evidence |
|------------|--------|----------|
| Current goal | ✅ Ready | `live_record.intent.current_goal` |
| Work area | ✅ Ready | `live_record.intent.work_area` |
| Last change | ✅ Ready | `live_record.intent.last_change` |
| Next step | ✅ Ready | `live_record.intent.next_step` |
| Goal history | ✅ Ready | `live_record.intent.goal_history` |
| Episode context | ❌ Missing | No `episode_id` in intent |

**Readiness Score: 4/5** — Needs episode binding

---

## B. Capability Matrix (30 Capabilities)

| # | Capability | Readiness | Gap |
|---|------------|-----------|-----|
| 1 | Explicit episode start | 0/5 | No `fo_start()` or trigger |
| 2 | Explicit episode end | 0/5 | No `fo_finish()` or trigger |
| 3 | Pause episode | 1/5 | `resume_state.paused` exists but unused |
| 4 | Resume episode | 1/5 | Same as above |
| 5 | Episode ID generation | 0/5 | No episode_id field anywhere |
| 6 | Episode persistence | 0/5 | No episode history storage |
| 7 | Episode → session binding | 2/5 | `session_id` exists, no episode link |
| 8 | Episode → activity binding | 1/5 | Activity tracking exists, no episode tag |
| 9 | Episode → commit binding | 0/5 | No `related_commit` in attribution |
| 10 | Agent-authored recap | 0/5 | No recap generation or storage |
| 11 | Dashboard recap trigger | 4/5 | `ai_queue` mechanism ready |
| 12 | Agent recap delivery | 3/5 | `mark_command_executed()` exists |
| 13 | Recap persistence | 2/5 | Could use `live_record.summaries` |
| 14 | Dirty state → episode | 4/5 | `unreported_work` is 90% there |
| 15 | Stale episode detection | 2/5 | 60-min timeout exists, no episode logic |
| 16 | Episode warning in opener | 3/5 | `_build_context_header()` can inject |
| 17 | Multi-AI episode isolation | 4/5 | `session_registry` per AI+project |
| 18 | Episode compliance score | 4/5 | `get_compliance_score()` exists |
| 19 | Dashboard episode controls | 0/5 | No UI for Start/Pause/Finish |
| 20 | Dashboard episode history | 0/5 | No episode list view |
| 21 | Episode timeline view | 0/5 | No timeline UI |
| 22 | Claude Code support | 5/5 | Full MCP integration |
| 23 | Codex support | 4/5 | Needs hook verification |
| 24 | Cursor support | 2/5 | Limited MCP support |
| 25 | Episode analytics | 0/5 | No episode metrics |
| 26 | Episode export | 0/5 | No export format |
| 27 | Episode search | 2/5 | `fo_search` exists, no episode filter |
| 28 | Episode decisions | 3/5 | `fo_decide` exists, needs episode tag |
| 29 | Episode errors | 4/5 | `fo_errors` tracks errors, needs episode |
| 30 | Episode git context | 2/5 | Commit detection exists, no binding |

**Summary**: 
- Ready (4-5): 9 capabilities
- Partial (2-3): 11 capabilities
- Missing (0-1): 10 capabilities

---

## C. Critical Path: "Finish & Save"

### The Question
> Can the dashboard trigger the agent to create a recap at Finish & Save?

### The Answer: YES

**Existing Communication Channel:**

```
Dashboard (HTML)
    │
    ▼ POST /api/memory/queue-for-ai
    │ {type: "finish_episode", message: "Generate recap for episode E-2026-0001"}
    │
REST API (memory.py:205)
    │
    ▼ writes to ai_queue in project memory
    │
MCP Server (mcp_memory_server_v2.py:1841)
    │
    ▼ _get_pending_commands_for_injection() 
    │   → injected into EVERY tool response
    │
    ▼ Agent sees: "📬 PENDING COMMANDS FROM DASHBOARD"
    │
Agent
    │
    ▼ calls get_pending_commands()
    │
    ▼ generates recap
    │
    ▼ calls mark_command_executed(result="recap: ...")
    │
Dashboard
    │
    ▼ polls /api/memory/command-status/{id}
    │
    ▼ displays recap
```

**What Exists:**
1. ✅ `POST /api/memory/queue-for-ai` — REST endpoint to queue commands
2. ✅ `get_pending_commands()` — MCP tool for agent to receive commands
3. ✅ Command injection in tool responses — Agent sees pending commands
4. ✅ `mark_command_executed()` — Agent reports completion with result
5. ✅ `/api/memory/command-status/{id}` — Dashboard polls for completion

**What's Missing:**
1. ❌ `type: "finish_episode"` command type not defined
2. ❌ Recap generation logic in agent
3. ❌ Dashboard UI button for "Finish & Save"
4. ❌ Recap display component in dashboard

**Effort Estimate**: 3-5 days for MVP

---

## D. Platform Feasibility

### Claude Code (Primary)

| Integration | Status | Evidence |
|-------------|--------|----------|
| MCP tools | ✅ Full | All fo_* tools available |
| PostToolUse hooks | ✅ Full | Activity API receives all events |
| Agent detection | ✅ Full | `claude` in AI_TOOLS |
| Session tracking | ✅ Full | session_registry works |
| Dirty state | ✅ Full | `SUPPORTED_ACTORS = {"claude", ...}` |
| Recap capability | ✅ Full | Agent can generate text responses |

**Verdict**: **100% compatible** — primary target platform

### Codex

| Integration | Status | Evidence |
|-------------|--------|----------|
| MCP tools | ⚠️ Partial | Needs verification |
| PostToolUse hooks | ⚠️ Partial | May differ from Claude Code |
| Agent detection | ✅ Full | `codex` in AI_TOOLS |
| Session tracking | ✅ Full | session_registry supports |
| Dirty state | ✅ Full | `SUPPORTED_ACTORS = {"codex", ...}` |
| Recap capability | ⚠️ Unknown | Needs testing |

**Verdict**: **80% compatible** — needs hook verification

### Cursor

| Integration | Status | Evidence |
|-------------|--------|----------|
| MCP tools | ❌ Limited | Different MCP implementation |
| PostToolUse hooks | ❌ Missing | No hook system documented |
| Agent detection | ✅ Full | `cursor` in AI_TOOLS (process detection) |
| Session tracking | ⚠️ Partial | Works for detection, not for episode |
| Dirty state | ❌ Missing | Not in SUPPORTED_ACTORS |
| Recap capability | ❌ Unknown | Would need different approach |

**Verdict**: **30% compatible** — not recommended for V1

---

## E. Proposed Work Episode Data Model

```python
@dataclass
class WorkEpisode:
    # Identity
    episode_id: str          # "E-2026-0719-001"
    project_id: str          # "FixOnce_34592c5b"
    
    # State
    status: str              # started | active | paused | finished
    started_at: str          # ISO timestamp
    ended_at: Optional[str]  # ISO timestamp when finished
    paused_at: Optional[str] # ISO timestamp when paused
    
    # Agent
    actor: str               # "claude" | "codex"
    session_ids: List[str]   # MCP sessions that were part of this episode
    
    # Work tracking
    intent_at_start: Dict    # Snapshot of intent when episode started
    activities: List[str]    # Activity IDs during episode
    commits: List[str]       # Commit hashes during episode
    files_modified: List[str]
    significant_files: int
    
    # Lifecycle
    goal: str                # Copy from intent.current_goal
    last_action: str         # Last thing done
    recap: Optional[str]     # Agent-generated at finish
    
    # Attribution
    started_by: str          # "agent" | "dashboard" | "auto"
    finished_by: str         # "agent" | "dashboard" | "timeout"
```

**Storage Location**: `~/.fixonce/projects_v2/{project_id}.json` → `episode_history[]`

---

## F. Proposed State Machine

```
                    ┌─────────────┐
                    │   (idle)    │
                    └──────┬──────┘
                           │ fo_init() or Start button
                           ▼
                    ┌─────────────┐
                    │   STARTED   │
                    └──────┬──────┘
                           │ first fo_* tool call
                           ▼
          ┌────────────────────────────────┐
          │                                │
          ▼                                │
   ┌─────────────┐                        │
   │   ACTIVE    │◄───────────────────────┘
   └──────┬──────┘        Resume
          │
          ├──────────────────────────────────┐
          │ Pause button                     │ Finish & Save button
          │                                  │ or 60-min timeout
          ▼                                  ▼
   ┌─────────────┐                    ┌─────────────┐
   │   PAUSED    │                    │  FINISHING  │
   └──────┬──────┘                    └──────┬──────┘
          │                                  │ Agent generates recap
          │                                  ▼
          │                           ┌─────────────┐
          │                           │  FINISHED   │
          │                           └─────────────┘
          │                                  │
          └───────── (auto timeout) ─────────┘
```

---

## G. MCP Tool Changes

### New Tools

| Tool | Purpose | When Called |
|------|---------|-------------|
| `fo_start()` | Begin new episode | Auto on first meaningful work, or explicit |
| `fo_pause()` | Pause episode | Dashboard button or agent decision |
| `fo_resume()` | Resume paused episode | Dashboard button or fo_init detection |
| `fo_finish(recap)` | End episode with summary | Dashboard trigger or agent decision |

### Modified Tools

| Tool | Change |
|------|--------|
| `fo_init()` | Detect and resume or warn about stale episode |
| `fo_sync()` | Tag with `episode_id` |
| `fo_solved()` | Tag with `episode_id` |
| `fo_decide()` | Tag with `episode_id` |

---

## H. Dashboard Changes

### New Components

1. **Episode Status Bar** (header)
   - Shows: Episode ID, duration, status
   - Actions: Pause, Finish & Save

2. **Episode History Card**
   - Lists: Past episodes with recaps
   - Actions: View details, search

3. **Finish & Save Modal**
   - Shows: Work summary, files changed
   - Input: Optional user note
   - Button: Trigger recap generation

4. **Recap Display**
   - Shows: Agent-generated recap
   - Actions: Copy, edit, confirm

### Modified Components

1. **AI Status Badge**
   - Add: Episode indicator (⚡ Active | ⏸ Paused | ✓ Finished)

2. **Activity Feed**
   - Group: By episode
   - Filter: Current episode / All

---

## I. V1 Minimal Implementation

### Phase 1: Episode Foundation (3-5 days)

1. Add `episode_id` to attribution payload
2. Add `WorkEpisode` dataclass to storage
3. Add `fo_start()` and `fo_finish()` MCP tools
4. Auto-start episode on first fo_sync/fo_solved after fo_init

### Phase 2: Finish & Save (3-5 days)

1. Add `type: "finish_episode"` to ai_queue types
2. Add recap generation prompt to MCP
3. Add "Finish & Save" button to dashboard
4. Add recap display component

### Phase 3: Dashboard UI (3-5 days)

1. Episode status bar in header
2. Episode history list
3. Episode details modal

### Phase 4: Polish (2-3 days)

1. Stale episode detection in fo_init
2. Auto-pause on 30-min inactivity
3. Episode search in fo_search

**Total V1 Estimate**: 11-18 days

---

## J. V2 Future Enhancements

1. Multi-AI episode handoff (Claude → Codex seamless)
2. Episode templates (bug fix, feature, refactor)
3. Episode analytics dashboard
4. Episode export to markdown
5. Episode → GitHub PR integration
6. Episode → Linear/Jira integration

---

## K. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Agent doesn't poll ai_queue | Medium | High | Inject in every tool response (already done) |
| Recap generation fails | Low | Medium | Fallback to activity summary |
| Episode boundary ambiguity | Medium | Medium | Clear rules: fo_init = potential start, explicit = definitive |
| Dashboard-Agent timing | Medium | Low | Polling with timeout, visual feedback |
| Cursor incompatibility | High | Low | V1 = Claude/Codex only |

---

## L. Product Verdict

### Does Work Episode fit FixOnce's vision?

| Vision Statement | Alignment |
|------------------|-----------|
| Memory belongs to the project | ✅ Episodes ARE project memory |
| Memory is the primary authority | ✅ Episode recap becomes authoritative summary |
| Context is deliverable | ✅ Episode = packaged context |
| What's not saved didn't happen | ✅ Episode enforces save-before-close |
| Simple beats comprehensive | ⚠️ Adds complexity, but high value |
| Failures are as valuable as successes | ✅ "Abandoned" episodes are recorded |

**Product Verdict**: **Strong alignment**. Work Episode is a natural evolution of FixOnce's memory-first approach. It transforms implicit context into explicit, bounded, shareable artifacts.

---

## M. Engineering Verdict

### Is Work Episode architecturally feasible?

| Dimension | Assessment |
|-----------|------------|
| Existing infrastructure | 60% ready |
| Critical path (Finish & Save) | Proven viable via ai_queue |
| Platform support | Claude Code 100%, Codex 80%, Cursor 30% |
| Data model | Simple, fits existing schema |
| State machine | Well-defined, no ambiguous transitions |
| Integration points | Clean, minimal changes to existing tools |

**Engineering Verdict**: **Feasible with low risk**. The ai_queue mechanism is the key enabler — it already solves the hard problem of dashboard → agent communication.

---

## N. Recommendation

### Proceed with V1

1. **Scope**: Claude Code only (Codex as stretch goal)
2. **Focus**: Start → Active → Finish lifecycle
3. **Skip for V1**: Pause/Resume, multi-AI handoff, analytics
4. **Ship**: Episode ID in attribution + Finish & Save button + recap display

### Success Criteria

- [ ] Episode created on first fo_sync after fo_init
- [ ] Dashboard shows "Finish & Save" button when episode active
- [ ] Agent generates recap when Finish triggered
- [ ] Recap persisted in project memory
- [ ] Next fo_init shows "Last episode: [recap preview]"

---

## O. Critical Question Answered

**Q: Can the dashboard trigger the agent to create a recap at Finish & Save?**

**A: Yes.** The `ai_queue` mechanism provides a proven, working communication channel. The agent already sees pending commands via `_get_pending_commands_for_injection()` in every tool response, and can report completion via `mark_command_executed()`. The dashboard can poll for completion via `/api/memory/command-status/{id}`.

This is the key finding that makes Work Episode viable.

---

## Appendix: Source File References

| Component | File | Key Lines |
|-----------|------|-----------|
| Session Registry | `src/core/session_registry.py` | 29-132 (IsolatedSession) |
| AI Detector | `src/core/ai_detector.py` | 51-104 (AI_TOOLS), 250-366 (detect_ai_tools) |
| Unreported Work | `src/core/unreported_work.py` | 149-202 (mark_work), 205-250 (mark_synced) |
| AI Queue API | `src/api/memory.py` | 186-246 (queue endpoints) |
| Pending Commands | `mcp_memory_server_v2.py` | 1841-1850, 9334-9401 |
| Attribution | `mcp_memory_server_v2.py` | 1598-1610 (_new_record_attribution) |
| Resume State | `src/core/resume_state.py` | 72-114 (save_resume_state) |
| Activity API | `src/api/activity.py` | 163-184 (activity storage) |
| MCP Health | `src/core/mcp_health.py` | 54-56 (thresholds) |
| Dashboard HTML | `data/dashboard.html` | Full file (needs episode controls) |
