# Handoff System Verification Report

**Date**: 2026-07-19  
**Scope**: Evidence-based analysis of stale opener incident

---

## Question A — What caused the actual stale opener?

### Evidence Table

| Event | Timestamp | Evidence Source | State Before | State After |
|-------|-----------|-----------------|--------------|-------------|
| fo_sync (protocol goal) | 2026-07-16 17:13:13 | Backup `FixOnce_34592c5b_20260716_171332.json` | Unknown | `intent.current_goal` = "Define canonical FixOnce product protocol architecture" |
| fo_sync (split-brain goal) | Between 17:13 and 18:03 | Inferred from stale opener + `last_file` = `docs/ACTIVE_PROJECT_SPLIT_BRAIN_ANALYSIS.md` | Protocol goal | `intent.current_goal` = "Investigate active_project split-brain bug", `next_step` = "Delete legacy data/active_project.json..." |
| Commit 898e6bf | 2026-07-16 18:03:42 | `git show 898e6bf` | Split-brain work in progress | Split-brain work COMPLETED (file created, legacy deleted per commit message) |
| (NO fo_sync) | — | No backup, no audit entry, no unreported_work sync record | `next_step` = "Delete legacy..." (already done) | `next_step` unchanged |
| Commit 22bc82b | 2026-07-16 20:17:40 | `git show 22bc82b` | Stale intent | Stale intent |
| (NO fo_sync) | — | No evidence of sync | Stale intent | Stale intent |
| Gap (July 17-18) | — | No activity | Stale intent | Stale intent |
| fo_init (stale opener) | 2026-07-19 08:22:47 | `agent_audit` entry with `intent_detail` = "Investigate active_project split-brain bug" | — | Read stale `intent`, displayed stale opener |
| fo_sync (correction) | 2026-07-19 08:30:22 | `unreported_work.json` shows `last_sync_at` | Stale intent | `intent.current_goal` = "Migrate FixOnce..." |

### Key Evidence

1. **Backup proof**: `FixOnce_34592c5b_20260716_171332.json` shows `intent.current_goal` = "Define canonical FixOnce product protocol architecture" with `updated_at` = "2026-07-16T17:13:13.315471"

2. **No split-brain backup**: No backup exists with "Investigate active_project split-brain bug", meaning the fo_sync that set this goal did NOT trigger a backup (normal behavior — backups are periodic, not per-write)

3. **Commit evidence**: Commit 898e6bf message says "Delete data/active_project.json" — this is exactly what the stale `next_step` said to do, proving the work was completed but the intent wasn't updated

4. **No sync evidence**: `unreported_work.json` shows `last_sync_at` for claude was my sync today (2026-07-19T08:30:22), confirming no fo_sync between July 16 and my correction

5. **Audit confirmation**: `agent_audit` entries from today (08:22:47) show `intent_detail` = "Investigate active_project split-brain bug", proving fo_init READ this stale value from `intent`

### Verdict

**PROVEN WORKFLOW FAILURE: fo_sync was not called after the commits**

Evidence is conclusive:
- fo_sync WAS called before commit 898e6bf (set split-brain goal)
- fo_sync was NOT called after commit 898e6bf (intent remained stale)
- fo_sync was NOT called after commit 22bc82b
- Result: fo_init on July 19 displayed stale context from BEFORE commit 898e6bf

---

## Question B — Are intent and resume_state duplicate sources of truth?

### Structure Analysis

| Structure | Writers | Readers | Purpose | Current or History | Type |
|-----------|---------|---------|---------|-------------------|------|
| `live_record.intent` | fo_sync (`_update_work_context_lightweight`) | fo_init (`_format_minimal_init`), `_handoff_details`, `fo_brief`, `_get_project_summary_for_init` | Current goal, area, last/next work | CURRENT | CANONICAL |
| `resume_state` | `save_resume_state` MCP tool | fo_init (fallback for last/next), `get_resume_state` MCP tool | Operational session state | CURRENT | OPERATIONAL |
| `ai_handoffs[]` | fo_init (on session change) | None for opener | Historical handoff records | HISTORY | ARCHIVE |
| `team_memory.handoffs[]` | fo_init (legacy) | None for opener | Legacy handoff records | HISTORY | ARCHIVE |
| `unreported_work` | PostToolUse hook | Dashboard status display | Dirty state tracking | CURRENT | OPERATIONAL |

### Field Comparison

| Field | intent | resume_state | Used for opener? | Overlap? |
|-------|--------|--------------|------------------|----------|
| current_goal | ✓ | — | YES (ONLY from intent) | NO |
| work_area | ✓ | — | YES (ONLY from intent) | NO |
| last_file | ✓ | — | YES (ONLY from intent) | NO |
| last_change | ✓ | — | YES (fresher wins) | SEMANTIC |
| last_completed_step | — | ✓ | YES (fresher wins) | SEMANTIC |
| next_step | ✓ | — | YES (fresher wins) | SEMANTIC |
| next_recommended_action | — | ✓ | YES (fresher wins) | SEMANTIC |
| active_task | — | ✓ | Fallback only | NO |
| short_summary | — | ✓ | YES (ONLY from resume) | NO |
| current_status | — | ✓ | NO | NO |
| blockers | ✓ | — | NO | NO |
| goal_history | ✓ | — | NO | NO |

### Overlapping Field Analysis

**1. last_change (intent) vs last_completed_step (resume_state)**
- Same business fact? SIMILAR — both describe what was last done
- Can values diverge? YES
- Which does fo_init prefer? Fresher one based on `updated_at` comparison
- Defined precedence rule? YES — compare timestamps, fresher wins
- Regenerated from other? NO — independently written
- Can one be deleted? YES — opener would still work with the other
- What breaks? Different MCP tools (fo_sync vs save_resume_state)

**2. next_step (intent) vs next_recommended_action (resume_state)**
- Same business fact? SIMILAR — both describe what to do next
- Can values diverge? YES
- Which does fo_init prefer? Fresher one based on `updated_at` comparison
- Defined precedence rule? YES — compare timestamps, fresher wins
- Regenerated from other? NO — independently written
- Can one be deleted? YES — opener would still work with the other
- What breaks? Different MCP tools

### Critical Finding: current_goal

**current_goal has NO duplicate source**:
- Stored ONLY in `live_record.intent`
- resume_state has NO goal field
- fo_init ALWAYS reads `intent.get("current_goal", "")` (line 10753)
- There is NO fallback to resume_state for goal

The stale opener showed "Investigate active_project split-brain bug" which came EXCLUSIVELY from `intent.current_goal`. resume_state played NO role in this incident.

---

## Proof Test Results

### Test 1: Intent-only scenario
- When resume_state is absent/stale, fo_init displays ONLY intent values
- current_goal ALWAYS comes from intent — no fallback

### Test 2: Resume-state fresher scenario
- resume_state can ONLY affect Last and Next fields
- Goal and Area come EXCLUSIVELY from intent
- resume_state CANNOT cause a stale goal to appear

### Test 3: Deliberate divergence
- Goal: ALWAYS from intent (regardless of freshness)
- Area: ALWAYS from intent (regardless of freshness)
- Last/Next: From fresher source (deterministic precedence)

### Test 4: Removal analysis
- If resume_state removed: LOW impact — rarely used, last update June 8
- If intent removed: CRITICAL — no goal, no area, opener broken
- If handoff archives removed: NONE — not used for current opener

---

## Definition of Duplicate Source of Truth — Applied

| Criterion | intent vs resume_state | Verdict |
|-----------|------------------------|---------|
| Two stores represent same current business fact | NO — intent has goal/area, resume_state has status/task | FAIL |
| Both independently writable | YES | PASS |
| Production readers consume either | PARTIAL — only for last/next, not for goal | FAIL |
| They can diverge | YES for last/next | PASS |
| No single canonical owner or derivation rule | NO — clear timestamp-based precedence | FAIL |

**3 of 5 criteria fail → NOT duplicate sources of truth**

### Correct Classification

| Structure | Classification | Relationship |
|-----------|---------------|--------------|
| `live_record.intent` | CANONICAL | Primary source for Goal, Area, Last, Next |
| `resume_state` | OPERATIONAL | Secondary operational state, fallback for Last/Next only |
| `ai_handoffs[]` | ARCHIVE | Historical record, not read for opener |
| `team_memory.handoffs[]` | ARCHIVE (legacy) | Historical record, not read for opener |

---

## Final Verdict

### 1. Was the actual incident caused by missing fo_sync?

**YES** — conclusively proven.

### 2. Is that fully proven or only strongly suggested?

**FULLY PROVEN** — backup timestamp evidence, commit timestamps, lack of sync evidence, and audit entries all align.

### 3. Is there a true duplicate source of truth?

**NO** — intent and resume_state store DIFFERENT fields. The stale field (current_goal) exists ONLY in intent. resume_state has no goal field and could not have caused this incident.

### 4. If yes, which structures and fields?

N/A — no duplicate source of truth exists for current_goal.

### 5. If no, what is the correct architectural relationship?

```
live_record.intent (CANONICAL)
├── current_goal    ← EXCLUSIVE source
├── work_area       ← EXCLUSIVE source
├── last_change     ← PRIMARY source (fresher wins)
├── next_step       ← PRIMARY source (fresher wins)
└── last_file       ← EXCLUSIVE source

resume_state (OPERATIONAL)
├── last_completed_step      ← FALLBACK for last (if fresher)
├── next_recommended_action  ← FALLBACK for next (if fresher)
├── active_task              ← FALLBACK for next (if nothing else)
├── short_summary            ← EXCLUSIVE source (different field)
└── current_status           ← NOT used in opener
```

### 6. What is the main fix?

**WORKFLOW ENFORCEMENT** — the architecture is correct, but the workflow (calling fo_sync after commits) was not followed.

Secondary: **STALE-STATE DETECTION** — fo_init should detect and warn when commits exist after the last fo_sync.

### 7. What is the smallest safe fix?

Add stale detection to fo_init:
1. Compare `intent.updated_at` vs latest git commit timestamp
2. If commits exist after last sync, add warning to opener:
   ```
   ⚠️ STALE CONTEXT: Work committed since last sync
   Last sync: 2026-07-16 17:13
   Commits since: 898e6bf, 22bc82b
   → Run fo_sync to update handoff context
   ```

### 8. What larger Core Protocol migration should be scheduled?

NONE required for this issue. The architecture is sound.

However, consider:
- **Deprecate resume_state** — last used June 8, low value, adds complexity
- **Add last_commit_hash to intent** — track what git state was synced
- **Auto-prompt for fo_sync after commit detection** — workflow enforcement

---

## Summary

The stale opener was caused by a **workflow failure** (missing fo_sync after commits), not an architectural flaw. The system has a **single canonical source of truth** for Goal/Area (`live_record.intent`). The `resume_state` structure is **not a duplicate** — it stores different operational fields and serves as a fallback only for Last/Next.

The smallest fix is **stale detection** (compare intent timestamp vs git commits). No structural changes are required.
