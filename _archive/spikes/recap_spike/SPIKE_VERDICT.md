# Recap Spike Verdict

**Date**: 2026-07-19  
**Spike Duration**: ~2 hours  
**Status**: COMPLETE

---

## Executive Summary

**VERDICT A: Local CLI recap is viable for V1.**

Both Codex and Claude Code transcripts can be extracted reliably. Codex exec provides non-interactive recap generation without requiring new API keys. The approach works for closed sessions and does not modify the original conversation files.

---

## Step 1: Claude Transcript Extractor — PASS

### Implementation
- Location: `spikes/recap_spike/transcript_extractor.py`
- Class: `ClaudeTranscriptExtractor`

### Test Results

```
Platform: claude
Session: 73f62cec-78fa-40ee-959f-a601a11321c3
CWD: /Users/haimdayan/Desktop/FixOnce
Started: 2026-07-19T05:22:35.234Z
Last Activity: 2026-07-19T08:49:07.296Z
Stats: {
  'total_lines': 1194,
  'user_messages': 10,
  'assistant_messages': 59,
  'filtered_system': 0,
  'filtered_tool_results': 276,
  'parse_errors': 0
}
```

### Capabilities Verified
- ✅ Read-only extraction
- ✅ System messages filtered
- ✅ Permissions/skills metadata filtered  
- ✅ Tool results excluded by default
- ✅ User messages preserved
- ✅ Assistant messages preserved
- ✅ Session identification by cwd
- ✅ Explicit session ID support
- ✅ Multiple sessions warning
- ✅ Malformed JSONL handling
- ✅ Active session detection

### Storage Location
```
~/.claude/projects/{project-path-encoded}/{session-uuid}.jsonl
Active session: ~/.claude/sessions/{pid}.json
```

---

## Step 2: Codex Transcript Extractor — PASS

### Implementation
- Location: `spikes/recap_spike/transcript_extractor.py`
- Class: `CodexTranscriptExtractor`

### Test Results

```
Platform: codex
Session: 019f56e6-c19f-7ea3-a431-629ff36ea733
CWD: /Users/haimdayan/Desktop/FixOnce
Started: 2026-07-12T15:16:36.202Z
Last Activity: 2026-07-12T15:38:28.816Z
Stats: {
  'total_lines': 517,
  'user_messages': 4,
  'assistant_messages': 48,
  'filtered_system': 2,
  'filtered_tool_results': 0,
  'parse_errors': 0
}
```

### Capabilities Verified
- ✅ Same normalized schema as Claude
- ✅ SQLite metadata query
- ✅ JSONL rollout parsing
- ✅ System tags filtered
- ✅ Multiple threads warning
- ✅ Active thread detection

### Storage Location
```
~/.codex/sessions/{year}/{month}/{day}/rollout-{timestamp}-{thread-id}.jsonl
Thread metadata: ~/.codex/state_5.sqlite → threads table
```

---

## Step 3: Recap Generator — PASS (Codex), BLOCKED (Claude)

### Codex exec — WORKS

```bash
codex exec --json --ephemeral --skip-git-repo-check "prompt"
```

**Test Results:**
```
Method: ai_codex
Status: success
Time: 31458ms
Messages: 72
```

**Recap Quality (Current Session):**
> The session examined stale FixOnce opening context, the handoff synchronization 
> model, and the proposed Work Episode direction. The user repeatedly constrained 
> the work to investigation only, correcting earlier conclusions and steering the 
> analysis toward evidence-based validation rather than implementation.

### Claude CLI — BLOCKED

```bash
claude -p --output-format json "prompt"
```

The Claude CLI hangs indefinitely in non-interactive mode. This may be due to:
- OAuth/auth flow requiring TTY
- Permission prompts not handled
- Session initialization blocking

**Status**: Not viable without further investigation.

---

## Step 4: System Evidence — PASS

### Implementation
- Location: `spikes/recap_spike/recap_generator.py`
- Function: `collect_system_evidence()`

### Evidence Collected
| Source | Data |
|--------|------|
| Git branch | ✅ Current branch name |
| Git status | ✅ Uncommitted files |
| Git log | ✅ Commits in time range |
| FixOnce decisions | ✅ From projects_v2/*.json |
| FixOnce solutions | ✅ Solved bugs |
| FixOnce insights | ✅ Learning records |

### Evidence vs Narrative Separation
The recap output separates:
- `recap`: AI-generated narrative from conversation
- `evidence`: System-observed facts from FixOnce/git

---

## Step 5: Live Tests — PASS

### Test 1: Claude Conversation

| Metric | Value |
|--------|-------|
| Session | 73f62cec-78fa-40ee-959f-a601a11321c3 |
| Messages included | 72 |
| Messages filtered | 276 (tool results) |
| Parse errors | 0 |
| AI recap generated | ✅ Yes |
| Generation time | 31.4s |
| Conversation modified | ❌ (by active session, not extractor) |

### Test 2: Codex Conversation

| Metric | Value |
|--------|-------|
| Session | 019f56e6-c19f-7ea3-a431-629ff36ea733 |
| Messages included | 52 |
| Messages filtered | 2 (system) |
| Parse errors | 0 |
| AI recap generated | ✅ Yes |
| Generation time | 40.8s |
| Conversation modified | ✅ Not modified |

### Consistency Test

Two recap generations for the same Codex session:
- Same session_id: ✅
- Same structure: ✅
- Different titles: Expected (AI non-determinism)

### Recap Quality Assessment

| Criterion | Result |
|-----------|--------|
| Captures user goal | ✅ Accurate |
| Lists completed work | ✅ Correct |
| Includes decisions | ✅ From discussion |
| Notes user corrections | ✅ Found and reported |
| Open threads identified | ✅ Accurate |
| No invented "Next" | ✅ None |
| Semantic compression | ✅ Good |
| Uncertainties noted | ✅ Present |

---

## Step 6: Fallback — WORKS

### Evidence-Only Recap

When AI generation fails:

```
Generation Method: evidence_only
Generation Status: fallback
```

Output includes:
- Session stats (message counts)
- Git branch and status
- FixOnce decisions
- Recent commits
- Uncommitted files

---

## Safety and Privacy

### Findings

| Check | Result |
|-------|--------|
| Tool results may contain secrets | ⚠️ Yes (env vars, file contents) |
| Default excludes tool_results | ✅ Safe |
| Secret patterns in user messages | ✅ None found |
| File write to Claude/Codex dirs | ✅ None |
| Original conversation modified | ✅ No (for closed sessions) |

### Recommendations

1. **Always exclude tool_results** — they contain command output that may include env vars, file contents, or credentials
2. **Display privacy notice** — inform user that transcript is read locally
3. **Opt-out mechanism** — let users disable recap for sensitive sessions
4. **Schema versioning** — track JSONL format version for future compatibility

---

## Platform Verdicts

### Claude Code

| Capability | Status |
|------------|--------|
| Transcript extraction | ✅ VIABLE |
| Non-interactive recap | ❌ BLOCKED (CLI hangs) |
| Evidence collection | ✅ VIABLE |
| Overall | **B: Transcript capture works, recap requires Codex or API** |

### Codex

| Capability | Status |
|------------|--------|
| Transcript extraction | ✅ VIABLE |
| Non-interactive recap | ✅ VIABLE |
| Evidence collection | ✅ VIABLE |
| Overall | **A: Fully viable for V1** |

---

## V1 Implementation Path

Given the findings, the recommended V1:

### Architecture

```
FixOnce Server
├── Transcript Adapter (read-only)
│   ├── Claude extractor
│   └── Codex extractor
├── Recap Generator
│   ├── codex exec (primary)
│   └── evidence-only fallback
├── Episode Storage
│   └── projects_v2/{id}.json → episode_history[]
└── Dashboard Display
    └── Episode card with recap
```

### User Flow

1. User clicks "Finish & Save" in Dashboard
2. FixOnce reads transcript from disk (read-only)
3. FixOnce calls `codex exec` with recap prompt
4. Recap stored in project memory
5. Dashboard displays recap for review

### Requirements

| Requirement | Solution |
|-------------|----------|
| No new API key | ✅ Uses codex exec |
| No user message in conversation | ✅ Reads closed transcript |
| No modification to conversation | ✅ Read-only |
| Works for Claude sessions | ✅ Extract + Codex generates |
| Works for Codex sessions | ✅ Extract + Codex generates |
| Fallback if AI unavailable | ✅ Evidence-only recap |

### Effort Estimate

| Component | Days |
|-----------|------|
| Integrate extractors into FixOnce core | 1-2 |
| Recap generation service | 1-2 |
| Episode storage schema | 1 |
| Dashboard "Finish & Save" button | 1 |
| Dashboard recap display | 1 |
| Testing & polish | 1-2 |
| **Total** | **6-10 days** |

---

## Files Produced

```
spikes/recap_spike/
├── transcript_extractor.py   # Claude + Codex extractors
├── recap_generator.py        # AI + fallback generation
└── SPIKE_VERDICT.md          # This document
```

---

## Conclusion

**The spike proves the core hypothesis:** FixOnce can read existing conversation transcripts and generate quality recaps without requiring user action in the conversation, agent awareness, or new API credentials.

The approach uses:
- Read-only transcript access (no modification)
- Existing Codex CLI for AI generation (no new API)
- Structured evidence from FixOnce + git (system truth)
- Graceful fallback when AI unavailable

**Recommended next step:** Integrate transcript extractors into FixOnce core and implement the "Finish & Save" button in Dashboard.
