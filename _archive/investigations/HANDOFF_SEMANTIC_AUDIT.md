# Handoff Semantic Contract Audit

**Date**: 2026-07-19  
**Scope**: Semantic truth and user trust analysis of opening handoff fields

---

## Part 1 — Field Lifecycle Trace

### Goal (current_goal)

| Aspect | Finding |
|--------|---------|
| **Writer** | `fo_sync()` via `_update_work_context_lightweight()` (mcp_memory_server_v2.py:6471) |
| **Actor** | AI agent — free text provided by Claude/Codex/Cursor |
| **Validation** | NONE — stored as-is, no verification against code, git, or user confirmation |
| **Consumers** | fo_init opener, fo_brief, _handoff_details, dashboard |
| **Can become stale?** | YES — indefinitely, no expiration or git-correlation |
| **Explicit clear?** | NO — can only be overwritten by new fo_sync |
| **Missing value?** | Supported — opener shows no goal line if empty |

**Evidence of write** (mcp_memory_server_v2.py:6470-6471):
```python
if current_goal:
    update_data['current_goal'] = current_goal
```

---

### Work Area (work_area)

| Aspect | Finding |
|--------|---------|
| **Writer** | `fo_sync()` via `_update_work_context_lightweight()` (mcp_memory_server_v2.py:6472-6473) |
| **Actor** | AI agent — free text |
| **Validation** | NONE |
| **Consumers** | fo_init opener (line 10824: `"Area: {work_area}"`) |
| **Can become stale?** | YES |
| **Explicit clear?** | NO |
| **Missing value?** | Supported — line omitted if empty |

---

### Last (last_change)

| Aspect | Finding |
|--------|---------|
| **Writer** | `fo_sync()` via `_update_work_context_lightweight()` (mcp_memory_server_v2.py:6476-6477) |
| **Actor** | AI agent — **free text claim, NOT verified against git/tools** |
| **Validation** | NONE — no comparison to actual commits, file changes, or tool calls |
| **Consumers** | fo_init opener (line 10837: `"Last:\n{last_thing}."`) |
| **Can become stale?** | YES — indefinitely |
| **Explicit clear?** | NO |
| **Missing value?** | Partially — falls back to `last_file` (line 10838-10839) |

**Critical finding**: The system stores what the AI CLAIMS was done, not what was ACTUALLY done. No verification occurs.

---

### Next (next_step)

| Aspect | Finding |
|--------|---------|
| **Writer** | `fo_sync()` via `_update_work_context_lightweight()` (mcp_memory_server_v2.py:6484) |
| **Actor** | AI agent — free text |
| **Validation** | Minimal — `_normalize_next_step()` removes numbered lists, but no semantic validation |
| **Consumers** | fo_init opener (lines 10841-10842, 10895-10896) |
| **Can become stale?** | YES — indefinitely, even after work is completed |
| **Explicit clear?** | YES — passing empty string clears it (line 6484) |
| **Missing value?** | Supported — opener shows priorities or "Continue with current task" instead |

**Normalization** (mcp_memory_server_v2.py:6484):
```python
update_data['next_step'] = _normalize_next_step(next_step) if next_step else ""
```

---

### Suggested Action

| Aspect | Finding |
|--------|---------|
| **Writer** | Computed at fo_init time from `next_step` or priorities |
| **Actor** | Derived from stored values |
| **Source** | (mcp_memory_server_v2.py:10894-10902) |
| **Priority** | 1) next_step from intent, 2) first priority (errors, reviews) |
| **Labeling** | Uses "→ Suggested:" prefix, distinguishing from confirmed |

**Code** (mcp_memory_server_v2.py:10894-10902):
```python
if next_thing:
    lines.append(f"→ Suggested: {next_thing}")
elif priorities:
    top_priority = priorities[0]
    lines.append(f"→ Suggested: {top_priority['action']}")
```

---

## Part 2 — Agent Behavior Audit

### Documented Requirements

#### Global CLAUDE.md (~/.claude/CLAUDE.md)

| Requirement | Present? | Excerpt |
|-------------|----------|---------|
| fo_sync after task completion | **NO explicit requirement** | Only "after meaningful progress" |
| fo_sync after commit | **NO** | Rule 10 says "fo_status() before commit", not fo_sync after |
| fo_sync before session end | **NO** | No session-end protocol |
| fo_sync when next_step changes | **NO explicit rule** | Only "after meaningful work" |

**Rule 8** (line 123):
> "Sync on progress — `fo_sync()` after meaningful work (code changes, decisions, direction changes)"

**Rule 10** (line 125):
> "Verify before commit — call `fo_status()` before committing to verify FixOnce is still recording"

#### Project CLAUDE.md

| Requirement | Present? | Excerpt |
|-------------|----------|---------|
| fo_sync after error fix | YES | Error protocol: "fo_solved() → fo_sync()" |
| fo_sync after commit | **NO explicit rule** | |
| fo_sync before session end | **NO** | |

#### Memory Files

**feedback_fo_sync_after_commit.md** contains explicit requirement:
> "After every commit, call fo_sync IMMEDIATELY after fo_solved."
> "commit → fo_solved → fo_sync (this order, no exceptions)"

**STATUS**: This is a learned behavior from user feedback, NOT enforced in code.

#### MCP Tool Description (fo_sync docstring)

```python
"""
Sync work context with FixOnce. Call after changes or when starting new work.
"""
```

**Finding**: No mention of calling after commits, completing tasks, or ending sessions.

---

### Audit Questions

| Question | Answer |
|----------|--------|
| Is agent required to call fo_sync after completing a task? | **NO** — only "after meaningful work" |
| Is it required after a commit? | **NO** — only memory file suggests this, not enforced |
| Is it required before ending a session? | **NO** — no session-end protocol exists |
| Is it required when planned next_step changes? | **NO** — no explicit rule |
| What happens if not called? | Opener shows stale context indefinitely |
| Is there enforcement or reminder? | **NO** — no detection, no warning, no prompt |
| Could agent believe Git commit already updates FixOnce? | **YES** — git_commit detected in activity but doesn't trigger sync |

---

### Evidence Available for Validation (NOT USED)

| Evidence Type | Available? | Used for Validation? |
|--------------|------------|---------------------|
| Git commits | YES — `_get_git_commit_hash()` exists | NO |
| Git log | YES — subprocess available | NO |
| File changes | YES — unreported_work tracks them | NO |
| Tool calls | YES — session.log_tool_call() | NO |
| fo_solved calls | YES — stored in debug_sessions | NO |
| fo_decide calls | YES — stored in decisions | NO |
| Timestamps | YES — stored on all records | NO |
| Sync timestamps | YES — in unreported_work | NOT compared to commits |

**Current state**: FixOnce has extensive evidence available but uses NONE of it to validate handoff claims.

---

## Part 3 — Truth Semantics

### Field Classification

| Field | Current Classification | Correct Classification |
|-------|----------------------|----------------------|
| Goal | **Agent recommendation** displayed as fact | Should be: User-confirmed intent OR labeled as agent interpretation |
| Work Area | **Agent recommendation** | Should be: Verified against code structure OR labeled |
| Last | **Agent claim** (unverified) | Should be: Evidence-backed OR labeled as claim |
| Next | **Agent recommendation** displayed as confirmed | Should be: Explicitly separated (confirmed vs suggested) |

### Does the system distinguish truth categories?

**NO** — all fields are stored identically regardless of:
- Whether user explicitly confirmed
- Whether derived from approved plan
- Whether agent independently chose
- Whether evidence supports the claim

The system stores:
```python
{
    "actor": "claude",
    "actor_source": "parent_process",
    "actor_confidence": 0.9,
    "session_id": "...",
    "tool_name": "fo_sync"
}
```

**Missing**:
- `evidence_type`: none / git_commit / file_change / user_statement
- `confirmation_status`: unconfirmed / user_confirmed / plan_derived
- `claim_confidence`: how certain is the claim about Last/Next
- `related_commit`: git hash that validates Last
- `superseded_at`: when this became obsolete

---

### Last — Detailed Analysis

**Current behavior**: Free text from AI agent, stored verbatim.

**Available evidence NOT used**:
1. `git log` — could verify "Created docs/X.md" by checking file in recent commits
2. `unreported_work.significant_files` — tracks modified files
3. `fo_solved` calls — records fixed bugs
4. `fo_decide` calls — records decisions
5. `activity_log` — tracks file_change events

**Example of mismatch**:
- Agent claims: "Created docs/ACTIVE_PROJECT_SPLIT_BRAIN_ANALYSIS.md"
- Evidence: File exists in commit 898e6bf
- System behavior: Stores claim, never verifies

**Honest alternative**:
- Store: `last_change_claim` (agent text) + `last_commit_hash` (git evidence)
- Display: "Last: Created docs/... (verified: commit 898e6bf)" or "Last: ... (unverified)"

---

### Next — Detailed Analysis

**Current behavior**: Free text from AI, displayed as both "Next:" and "→ Suggested:".

**Sources of Next (undistinguished)**:
1. User explicitly says "next do X" → agent calls fo_sync(next_step="X")
2. Agent recommends next step → agent calls fo_sync(next_step="X")
3. Agent copies from older handoff (stale)
4. Agent infers from work pattern

**Semantic problem**: The opener shows:
```
Next:
Delete legacy data/active_project.json and fix catalog_repair...

→ Suggested: Delete legacy data/active_project.json...
```

This presents an agent recommendation AS IF it were a confirmed user intention. The user never said "next, delete that file" — the agent inferred it.

**Honest alternative**:
- Separate "Next confirmed:" (user explicitly stated) from "Suggested next:" (agent recommendation)
- Or: Always show as "Suggested" and never claim confirmation without evidence

---

## Part 4 — Controlled Scenarios

### Scenario 1: User explicitly says what to do next, agent calls fo_sync

**User**: "Next, fix the authentication bug in login.py"
**Agent**: Calls `fo_sync(next_step="Fix authentication bug in login.py")`

**What FixOnce displays**: `Next: Fix authentication bug in login.py.`

**Semantic honesty**: ✅ HONEST — this was user-confirmed intent

**Problem**: System doesn't KNOW this is user-confirmed. Same storage as agent-recommended.

---

### Scenario 2: Agent independently recommends, calls fo_sync

**User**: "Continue working"
**Agent**: Analyzes code, calls `fo_sync(next_step="Refactor the database module")`

**What FixOnce displays**: `Next: Refactor the database module.`

**Semantic honesty**: ❌ MISLEADING — displays agent recommendation as if it were confirmed plan

---

### Scenario 3: User never specifies next step

**User**: Just says "looks good, thanks"
**Agent**: Ends session without fo_sync

**What FixOnce displays**: Previous next_step from stale intent

**Semantic honesty**: ❌ MISLEADING — shows obsolete recommendation

---

### Scenario 4: Previously confirmed next step becomes obsolete

**Before**: User confirmed "Next: Fix bug #123"
**During session**: User says "actually, let's work on feature Y instead"
**Agent**: Doesn't call fo_sync

**What FixOnce displays**: `Next: Fix bug #123.`

**Semantic honesty**: ❌ MISLEADING — obsolete intent displayed

---

### Scenario 5: Work completed and committed, fo_sync not called

**What happened**: Agent implemented feature, created commit
**Agent behavior**: Called fo_solved but not fo_sync
**Current intent**: `next_step = "Implement the feature"` (already done)

**What FixOnce displays**: `Next: Implement the feature.`

**Semantic honesty**: ❌ MISLEADING — completed work shown as pending
**This is exactly what happened in the incident.**

---

### Scenario 6: fo_sync before final commit, not after

**Before commit**: fo_sync(last_change="Working on X", next_step="Finish and commit")
**After commit**: No fo_sync

**What FixOnce displays**: `Next: Finish and commit.` (already done)

**Semantic honesty**: ❌ MISLEADING

---

### Scenario 7: Two agents, different next steps

**Claude**: fo_sync(next_step="Refactor database")
**Codex**: fo_sync(next_step="Add tests")

**What FixOnce displays**: Whichever was called last

**Semantic honesty**: ⚠️ PARTIAL — no indication of conflict or that another agent had different recommendation

---

### Scenario 8: User changes direction outside coding agent

**User**: In dashboard, manually edits project notes
**User**: Tells different agent "we're pivoting to mobile"
**First agent**: Resumes with stale intent

**What FixOnce displays**: Stale `Next:` from before pivot

**Semantic honesty**: ❌ MISLEADING

---

### Scenario 9: Last claimed but no repository evidence

**Agent claims**: `last_change="Fixed critical security bug"`
**Git state**: No commits with security fix

**What FixOnce displays**: `Last: Fixed critical security bug.`

**Semantic honesty**: ❌ MISLEADING — unverifiable claim displayed as fact

---

### Scenario 10: Repository changes, approved next step still valid

**User confirmed**: "Next: Add user authentication"
**Git commits**: 3 commits adding other features

**What FixOnce displays**: `Next: Add user authentication.`

**Semantic honesty**: ✅ HONEST — next step is still valid even if work happened
**BUT**: No way to know if this is still the user's intention after seeing new commits

---

## Part 5 — Provenance and Authority

### Currently Stored Attribution

| Field | Stored? | Example |
|-------|---------|---------|
| actor | YES | "claude" |
| timestamp | YES | "2026-06-07T10:55:53.192171" (creation time) |
| updated_at | YES | "2026-07-19T08:30:22.199293" |
| actor_source | YES | "parent_process" |
| actor_confidence | YES | 0.9 |
| session_id | YES | "f38d0fcd" |
| tool_name | YES | "fo_sync" |
| status | YES | "active" |
| synced_via | YES | "rest_fallback" |

### NOT Stored

| Field | Impact |
|-------|--------|
| evidence_type | Cannot distinguish claim from fact |
| confirmation_status | Cannot distinguish user-confirmed from agent-recommended |
| claim_confidence | All claims treated equally |
| related_commit | Cannot verify Last against git |
| superseded_at | Cannot mark obsolete |
| user_confirmed | Cannot separate user intent from agent interpretation |
| source_quote | Cannot show what user actually said |
| plan_reference | Cannot link to approved plan |

---

## Part 6 — Required Product Contract

### Current (Implicit) Contract

```
Goal: Whatever the AI last wrote
Last: Whatever the AI last claimed
Next: Whatever the AI last recommended
Suggested: Same as Next

All displayed as equal truth.
No distinction between confirmed and recommended.
No expiration or staleness warning.
No validation against evidence.
```

### Proposed Semantic Contract

```
Goal: 
  - Explicit user goal OR 
  - Agent interpretation (labeled: "Goal (inferred)")

Last:
  - Evidence-backed: "Last: {action} (commit {hash})" OR
  - Agent claim: "Last: {action} (unverified)"

Next:
  - Confirmed: "Next confirmed: {action}" (user explicitly stated OR derived from approved plan)
  - Suggested: "Suggested next: {action}" (agent recommendation only)
  - Unknown: "No confirmed next step" (when no trustworthy action exists)

The system MUST NEVER present an inferred or agent-recommended next step as confirmed user intent.
```

### UI Renaming Options

| Current | Option A | Option B | Option C |
|---------|----------|----------|----------|
| "Next:" | "Next confirmed:" | "Planned:" | Keep, add "(unconfirmed)" if unconfirmed |
| "→ Suggested:" | "Suggested next:" | "AI recommends:" | Keep |
| (missing) | "Next unknown" | "No plan set" | "What's next?" |

**Recommendation**: Use "Suggested next:" consistently. Reserve "Next confirmed:" only when user explicitly stated it.

---

## Part 7 — Responsibility Boundaries

### Question 1: Is the AI responsible for understanding and summarizing work?

**YES** — but it should be HONEST about the nature of its summary.

The AI should:
- Describe what it believes happened
- Label uncertainty ("I believe I fixed...", "The commit should contain...")
- Not claim verification it hasn't performed

### Question 2: Is the MCP tool responsible only for persistence?

**CURRENT**: Yes, MCP is just storage.
**RECOMMENDED**: MCP should also:
- Store evidence type (claim vs verified)
- Compare sync timestamps to git commits
- Mark intent as potentially stale

### Question 3: Should FixOnce Core validate factual claims in Last?

**YES, minimally**:
- Compare `last_file` to unreported_work.significant_files
- Compare `updated_at` to last git commit
- Flag mismatches but don't block

### Question 4: Who has final authority over Next?

**Current**: Last agent to call fo_sync.
**Recommended**: User has authority; agent provides suggestions.

Implementation:
- `next_confirmed` (user explicitly stated) — authoritative
- `next_suggested` (agent recommended) — advisory
- Display: Prioritize confirmed over suggested

### Question 5: Can Next ever be automatically inferred with 100% confidence?

**NO** — even if the code clearly shows "TODO: implement X", the user may have changed their mind.

Safe automatic inference: NONE
Reasonable inference: After AUTO-FIX, suggest "test the fix"

### Question 6: When must the opener admit Next is unknown?

When:
- No fo_sync has been called this session
- Intent timestamp is older than last commit
- User explicitly cleared the next step
- Multiple agents have conflicting recommendations

### Question 7: Should agent be forced/prompted to sync before session completion?

**FORCED**: Too disruptive — sessions can end unexpectedly.
**STRONGLY PROMPTED**: YES — fo_init should warn about unsynced commits.

Implementation:
- Detect: `last_sync_at < last_commit_timestamp`
- Show: "⚠️ Work committed since last sync. Run fo_sync to update handoff."

### Question 8: Can session completion be detected reliably?

**Claude Code**: No explicit session end signal.
**Codex**: No explicit session end signal.
**Cursor**: No explicit session end signal.

**Alternative**: Detect inactivity + git commits → mark intent as potentially stale.

---

## Final Report

### 1. Current Exact Contract (Implicit)

The handoff system currently operates on this implicit contract:

> **All handoff fields are agent-authored free text, stored without validation, displayed without distinction between confirmed and recommended, and retained indefinitely regardless of staleness.**

There is no semantic distinction between:
- User explicitly saying "do X next"
- Agent independently recommending "do X next"
- Agent copying stale "do X next" from previous session

### 2. Why the Stale Opener Occurred

The stale opener occurred because:

1. Agent called fo_sync BEFORE commit (set next_step = "Delete legacy...")
2. Agent completed the work and committed
3. Agent did NOT call fo_sync AFTER commit
4. System had no mechanism to:
   - Detect commits occurred after last sync
   - Warn about potentially stale intent
   - Distinguish "Next" that was already done from "Next" that is still pending

### 3. Main Failure Classification

| Failure Type | Present? | Severity |
|--------------|----------|----------|
| Agent discipline | YES — agent didn't follow memory file guidance | CONTRIBUTING |
| Missing protocol | YES — no explicit "sync after commit" rule | CONTRIBUTING |
| Missing product enforcement | YES — no detection or warning | **PRIMARY** |
| Unclear semantics | YES — no distinction between claim and fact | **PRIMARY** |
| Combination | YES | — |

**Primary failures**:
1. Product doesn't enforce or detect missing sync
2. Product doesn't distinguish agent claim from verified fact
3. Product displays stale recommendation as confirmed intent

### 4. Smallest Correction That Improves Trust

**Stale detection without semantic change**:

Add to fo_init:
```python
if intent_updated_at < last_git_commit_time:
    warning = "⚠️ Context may be stale (commits since last sync)"
```

Cost: ~20 lines of code.
Benefit: User sees warning, can ask agent to sync.

### 5. Ideal Long-term Design

```
STORAGE:
  intent:
    goal: { text, source: "user" | "agent", confidence }
    last: { text, evidence: "commit:abc123" | "claim" | "file_change" }
    next_confirmed: { text, source: "user_statement" | "plan:xxx", confirmed_at }
    next_suggested: { text, source: "agent_recommendation", confidence }

DISPLAY:
  Goal: {goal.text}
  Last: {last.text} ✓ (if evidence) or (unverified)
  Next: {next_confirmed.text} (if exists)
  Suggested: {next_suggested.text} (always, even if confirmed exists)
  
  If no confirmed and no suggested:
    "What's next? Run fo_sync to set direction."
```

### 6. Transport-Independent Core Behavior

These can be in FixOnce Core (independent of Claude/Codex/Cursor):

- Stale detection (compare intent.updated_at to git)
- Evidence tracking (store commit hash with Last)
- Confirmation tracking (store source of Next)
- Staleness warnings in opener
- Missing sync detection in unreported_work

### 7. Agent/Tool Integration Required

These require integration with specific agents:

- Prompting agent to sync before session end (agent-specific hooks)
- Detecting when agent commits (already done via PostToolUse)
- Parsing user statements to distinguish confirmation from conversation

### 8. Proposed Test Matrix

#### Last Correctness

| Test Case | Expected Outcome |
|-----------|------------------|
| fo_sync(last_change="X"), no commit | Display "Last: X" without verification marker |
| fo_sync(last_change="X"), commit contains X | Display "Last: X ✓" or "Last: X (verified)" |
| fo_sync(last_change="X"), commit doesn't contain X | Display "Last: X" with warning |
| No fo_sync, work done | Display warning about missing sync |

#### Next Correctness

| Test Case | Expected Outcome |
|-----------|------------------|
| User explicitly says "next do X", fo_sync | Display "Next confirmed: X" |
| Agent recommends X, fo_sync | Display "Suggested next: X" |
| No fo_sync, previous next exists | Display previous + warning if stale |
| fo_sync(next_step=""), clearing | Display "No next step set" |
| Multiple agents, conflicting | Display most recent + "other agent suggested Y" |
| Work done on "Next", not cleared | Display warning "Suggested may be complete" |

---

## Summary

The current handoff system operates on trust without verification. It stores agent claims as truth, displays recommendations as confirmations, and retains obsolete state indefinitely.

The stale opener incident was caused by:
1. Agent not calling fo_sync after commit (discipline failure)
2. No protocol requiring sync after commit (protocol gap)
3. No detection of commits-after-sync (product enforcement gap)
4. No distinction between agent claim and evidence (semantic gap)

**The core semantic problem**: The system presents agent recommendations as confirmed user intent. This violates user trust when the recommendation is stale, wrong, or never confirmed.

**The smallest fix**: Detect commits-after-sync and show warning.

**The correct fix**: Distinguish confirmed from suggested, verify claims against evidence, and admit uncertainty when it exists.
