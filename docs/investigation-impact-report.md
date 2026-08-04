# Investigation: Evidence of Impact Architecture

**Date:** 2026-08-04  
**Status:** Investigation Complete  
**Next:** Design Review

---

## Executive Summary

FixOnce already has an ROI tracking system (`_track_roi_event`), but it counts events without capturing what was reused or how it affected work. An Impact Report system needs:

1. **Per-session event accumulation** (not just cumulative counts)
2. **Content IDs and summaries** (not just event types)
3. **Explicit evidence only** (no AI inference)

---

## Q1: Which Existing Events Can Prove Real Value?

### Already Tracked (via `_track_roi_event`)

| Event | Location | What It Proves |
|-------|----------|----------------|
| `solution_reused` | `search_past_solutions` L8348 | fo_search found matching solution |
| `decision_used` | L5304 | A decision was retrieved |
| `error_prevented` | L9188 | Avoid pattern was surfaced |
| `session_context` | L4941 | fo_init loaded existing context |
| `insight_used` | L2614 | An insight was returned |
| `error_caught_live` | L8526 | Browser error detected in real-time |

### Current Storage (project_memory_manager.py)

```python
roi = {
    "solutions_reused": 5,
    "decisions_referenced": 3,
    "errors_prevented": 2,
    "sessions_with_context": 12,
    "insights_used": 8,
    "errors_caught_live": 4,
    "tokens_saved": 50000,        # ← Estimate (unreliable)
    "time_saved_minutes": 120,    # ← Estimate (unreliable)
}
```

**Problem:** These are cumulative counts across all sessions. We cannot answer:
- "What happened THIS session?"
- "WHICH solution was reused?"
- "What did the decision SAY?"

---

## Q2: Which Mechanisms Should Contribute?

### ✅ fo_init

**Current:** Tracks `session_context` when context exists.

**Has access to:**
- Goal, last_change, next_step (from resume_state)
- Priorities (errors, reviews, decisions)
- Knowledge package (must_know, should_check items)

**Gap:** Does not record WHICH items were loaded.

**Impact evidence possible:**
- "Continued from goal: 'Fix Guardian bug' with next step: 'Test the fix'"
- "Loaded 3 must-know items including avoid pattern for 'direct SQL'"

---

### ✅ fo_search

**Current:** Tracks `solution_reused` when matches found.

**Has access to:**
- Query
- Matched items (IDs, text, category)
- Match scores

**Gap:** Does not record which specific items were returned.

**Impact evidence possible:**
- "Found 2 matching solutions for 'TypeError: undefined is not a function'"
- "Retrieved decision: 'Use shlex not regex for command parsing'"

---

### ✅ Decision Retrieval

**Current:** Tracks `decision_used` when decision surfaced.

**Gap:** Does not capture decision content or context.

**Impact evidence possible:**
- "Decision 'API responses must include version header' was surfaced"

---

### ✅ Avoid Patterns

**Current:** Tracks `error_prevented` when pattern fires.

**Gap:** Does not capture which pattern or what was avoided.

**Impact evidence possible:**
- "Avoid pattern triggered: 'Never use --force without explicit user confirmation'"

---

### ✅ Guardian Signals/Verdicts

**Current:** Shadow verdicts recorded to JSONL, not connected to ROI.

**Potential:**
- `require_approval` verdict = value created (destructive action flagged)
- `risk_unknown_impact` = potential risk identified

**Impact evidence possible:**
- "Destructive command 'rm -rf build/' flagged for review"

---

### ✅ Intervention Policy

**Current:** `InterventionAuditEntry` records gate + verdict + evidence.

**Gap:** Not connected to user-facing reporting.

**Impact evidence possible:**
- "Risk gate triggered: file outside project boundary"

---

### ⚠️ Conflict Detection

**Current:** fo_solved can detect SUPERSEDES/EXCEPTION_TO conflicts.

**Gap:** Only fires during save, not during retrieval.

**Not currently observable:** "This decision would conflict with X"

---

### ⚠️ Pre-Save Review

**Current:** fo_solved checks for related solutions before saving.

**Gap:** Review results not tracked as impact events.

**Potential:** "Found 2 related solutions during pre-save review"

---

## Q3: Value-Producing Events NOT Currently Observable

| Event | Why It Matters | Why Not Observable |
|-------|---------------|-------------------|
| Agent actually USED retrieved info | Proves real impact | Agent action is external |
| Continuation prevented rework | Time saved | Cannot measure counterfactual |
| Conflict prevented mistake | Error avoided | No tracking of "what would have happened" |
| Decision changed implementation | Design influence | Agent doesn't report this |
| Guardian prevented destructive action | Data protected | Shadow mode, no enforcement yet |

### Key Insight

**We can only report what FixOnce tools explicitly did, not what the agent did with the information.**

Reliable:
- "fo_search returned 3 matching solutions"
- "Decision X was surfaced"

Unreliable (requires AI inference):
- "Agent followed the decision"
- "Time was saved"
- "Bug was avoided"

---

## Q4: Smallest Architecture for Evidence of Impact

### Data Model

```python
@dataclass
class ImpactEvent:
    event_type: str          # "solution_retrieved", "decision_surfaced", etc.
    source_tool: str         # "fo_search", "fo_init", "fo_errors"
    content_id: str          # ID of the reused item
    content_summary: str     # Brief text (max 100 chars) for reporting
    timestamp: str
    session_id: str          # Groups events per-task
    
    # Optional fields
    query: str = ""          # What the agent was looking for
    match_score: float = 0.0 # How confident the match was
```

### Session-Level Accumulator

```python
# In-memory, per-session
_SESSION_IMPACT_EVENTS: Dict[str, List[ImpactEvent]] = {}

def record_impact_event(event: ImpactEvent) -> None:
    """Append to current session's impact log."""
    
def get_session_impact(session_id: str) -> List[ImpactEvent]:
    """Return all impact events for this session."""
    
def format_impact_report(events: List[ImpactEvent]) -> Optional[str]:
    """Format events into 1-2 factual sentences. Returns None if no events."""
```

### Event Type → Report Template Mapping

| Event Type | Report Template |
|------------|-----------------|
| `solution_retrieved` | "Reused a previously saved solution for '{query}'" |
| `decision_surfaced` | "Project decision '{summary}' was referenced" |
| `avoid_pattern_triggered` | "Avoid pattern '{summary}' prevented potential issue" |
| `context_restored` | "Continued from: {summary}" |
| `guardian_flagged` | "Flagged destructive operation: {summary}" |
| `error_caught_live` | "Detected browser error before manual discovery" |

### Integration Points

```
fo_init()
  └─ record_impact_event(context_restored, content from resume_state)
  
fo_search()
  └─ if matches: record_impact_event(solution_retrieved, top match)
  
fo_errors() + fo_apply()
  └─ if auto_fix: record_impact_event(auto_fix_available, error summary)
  
Guardian signal production
  └─ if require_approval: record_impact_event(guardian_flagged, command)
  
Avoid pattern surface
  └─ record_impact_event(avoid_pattern_triggered, pattern text)
```

---

## Q5: Implementation Without AI Guesswork

### Principle: Report Tool Actions, Not Agent Behavior

**✅ Factual (tool action):**
- "fo_search returned 3 solutions matching 'TypeError'"
- "fo_init loaded context with goal 'Fix Guardian bug'"
- "Avoid pattern 'no force push without confirmation' was surfaced"

**❌ Inferential (agent behavior):**
- "Saved 15 minutes by reusing solution"
- "Agent followed the decision"
- "Bug was prevented"

### Report Generation Rules

1. **Only if events exist** - No report if nothing happened
2. **Max 2 sentences** - Brief, not verbose
3. **Specific content** - Name the solution/decision/pattern
4. **No estimates** - No time, no tokens, no percentages
5. **Passive voice where uncertain** - "was surfaced" not "I used"

### Example Reports

**Minimal (one event):**
> "I reused a previously saved solution instead of investigating from scratch."

**Contextual (multiple events):**
> "This session benefited from project memory: continued from existing context, and referenced a prior decision about command parsing."

**Guardian (destructive flagged):**
> "Flagged 'rm -rf build/' for review before execution."

**No report (no events):**
> *(nothing - silence is correct)*

---

## Recommended Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Tool Layer                        │
│  fo_init, fo_search, fo_errors, fo_apply, fo_decide     │
└───────────────────────┬─────────────────────────────────┘
                        │ record_impact_event()
                        ▼
┌─────────────────────────────────────────────────────────┐
│              Impact Event Accumulator                    │
│  - Per-session in-memory storage                         │
│  - Bounded (max 50 events per session)                   │
│  - Deduplication by content_id + event_type              │
└───────────────────────┬─────────────────────────────────┘
                        │ get_session_impact()
                        ▼
┌─────────────────────────────────────────────────────────┐
│              Impact Report Formatter                     │
│  - Maps events to factual templates                      │
│  - Returns None if no events                             │
│  - Max 2 sentences                                       │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                    Agent Output                          │
│  "I reused a saved solution for 'TypeError: undefined'" │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Infrastructure (Smallest)
- `ImpactEvent` dataclass
- In-memory session accumulator
- `record_impact_event()` function
- Single integration: fo_search (most common value event)

### Phase 2: Integration
- fo_init context restoration
- fo_errors auto-fix detection
- Avoid pattern surfacing

### Phase 3: Reporting
- `format_impact_report()` function
- Agent-callable tool or automatic inclusion

### Phase 4: Guardian Integration
- Connect shadow verdicts to impact events
- Report flagged destructive operations

---

## Files to Modify

| File | Change |
|------|--------|
| `src/core/impact_events.py` | **NEW** - ImpactEvent, accumulator, formatter |
| `src/mcp_server/mcp_memory_server_v2.py` | Wire into fo_search, fo_init |
| `src/core/signal_audit.py` | Wire Guardian verdicts (Phase 4) |

---

## Success Criteria

1. Agent can report "I reused X" when X was actually retrieved
2. Report is factual - no time estimates, no marketing
3. Every statement traceable to a specific ImpactEvent
4. No report when no value was created
5. Works for any AI agent (Claude, Codex, Cursor) via MCP

---

## Open Questions for Design Review

1. Should impact report be automatic (end of task) or agent-requested?
2. Should events persist to disk or remain session-only?
3. How to handle multi-session tasks (user resumes after break)?
4. Should Guardian verdicts count as impact even in shadow mode?
