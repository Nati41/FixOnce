# FixOnce — AI Memory Layer

> **DOGFOODING**: This IS the FixOnce project. AI MUST use FixOnce correctly.

## Disable

Say "no fixonce" to disable. Otherwise, FixOnce is mandatory.

---

## Working Contract

When connected to FixOnce, you work inside persistent project memory.

**Principles:**
1. Never start from zero — check what the project knows first.
2. Knowledge belongs to the project — solutions and decisions must be recorded.
3. No work outside memory — use existing memory or contribute new memory.
4. Context is deliverable — next session continues without "where were we?"
5. Known fix first — when AUTO-FIX exists, apply before investigating.

---

## Vision V1

Use these statements to judge future decisions.

| # | Vision | Key |
|---|--------|-----------|
| 1 | **Memory belongs to the project, not the AI.** A new agent inherits what the previous one learned. | Ownership |
| 2 | **Memory is the primary authority.** If a decision exists, it's the source of truth — not code, not git. | Authority |
| 3 | **Context is deliverable.** Next session continues without "where were we?" | Continuity |
| 4 | **What's not saved didn't happen.** Every fix, decision, avoid must enter memory. | Recording |
| 5 | **Simple beats comprehensive.** 8 tools, not 45. Minimal surface. | Simplicity |
| 6 | **Failures are as valuable as successes.** Avoid patterns prevent repeated mistakes. | Learning |

**How to use:**
- When choosing between approaches → check which aligns with Vision
- When adding features → does it support or contradict these statements?
- When in doubt → simpler is better, recorded is better, memory-first is better

---

## Connection Awareness

### Before Meaningful Work

Call `fo_init()`. If it fails or is unavailable:

```
⚠️ FixOnce is not connected.

Project memory will NOT be recorded.

Please ensure FixOnce is running,
then open a new AI conversation.

Do you want to continue without FixOnce?
```

Do NOT silently continue without user acknowledgment.

### During Work

If any `fo_*` tool disappears or fails due to MCP connection loss:

1. Immediately notify the user
2. Explain that FixOnce recording has stopped
3. Recommend opening a new AI conversation after FixOnce is restored
4. Continue only if user explicitly chooses to work without FixOnce

### Before Completion

Before commit, "task complete", or major milestone:

1. Call `fo_status()` to verify FixOnce is still recording
2. If not recording, warn before finishing
3. Suggest syncing work after connection is restored

---

## Opening

1. Call `fo_init(cwd="project-path")` silently — ONCE only
2. Display the `fo_init` opener exactly once
3. Do not paraphrase, summarize, or repeat it
4. Do not add anything after it if the opener already includes `Ready.`

**Do not:**
- Say "I'll start...", "Checking...", "Let me..."
- Explain setup (Codex configured, MCP connected, etc.)
- Ask "What should we tackle next?" if `fo_init` already includes Next
- Restate, paraphrase, or summarize the opener
- Add commentary, verification notes, or follow-up questions after the opener

`fo_init` is responsible for returning the final human opener, including `Ready.`
The assistant should display that opener exactly once and add nothing else.

**ACTION_REQUIRED directive:**

If fo_init contains `ACTION_REQUIRED: <tool>`:
- `ACTION_REQUIRED: fo_errors` → call `fo_errors()` immediately
- `ACTION_REQUIRED: fo_apply` → call `fo_apply()` immediately

**After executing:** Be proactive — suggest the fix or offer to apply it.
Don't ask "מה צריך שאעשה?" — lead the process.

---

## Error Handling Protocol

### KNOWN ERROR (AUTO-FIX READY)

When `fo_errors()` returns **"AUTO-FIX READY"**:

```
fo_errors()  → sees AUTO-FIX READY
fo_apply()   → MANDATORY - get fix instructions
[apply fix]  → edit the code
fo_solved()  → record it
fo_sync()    → update context
```

**DO NOT** use fo_search or manual investigation when AUTO-FIX READY exists.

### UNKNOWN ERROR

When no AUTO-FIX:

```
fo_errors()  → sees error, no auto-fix
fo_search()  → check if solved before
[investigate & fix]
fo_solved()  → record it
fo_sync()    → update context
```

---

## Tools

| Tool | When |
|------|------|
| `fo_init(cwd)` | Start of conversation |
| `fo_status()` | Verify connection before commit/completion |
| `fo_errors()` | Check browser errors |
| `fo_apply()` | **When AUTO-FIX READY** (mandatory) |
| `fo_search(query)` | Before Read/Bash — check project history first |
| `fo_solved(error, solution)` | After fixing any error |
| `fo_sync(last_change, next_step)` | After meaningful progress |
| `fo_decide(text, reason)` | Record decision |
| `fo_component(action, name)` | Track components |

---

## Rules

1. **Init first** — `fo_init()` before anything
2. **Auto-fix first** — if AUTO-FIX READY, use `fo_apply()` immediately
3. **Search before investigating** — call `fo_search(query)` BEFORE using Read/Bash. Applies to:
   - Errors and bugs (check if solved before)
   - Refactors and architecture changes (check past decisions)
   - Critical files: project_context.py, MCP tools, timeout/sync logic
   - "Why did we do it this way" questions
4. **Stop on AVOID** — when fo_search returns AVOID PATTERN, summarize risks and ask before proceeding
5. **Use search answers** — if fo_search returns a complete answer (decision, solved bug, explicit reasoning), use it directly — don't verify against code. Search results are authority, not hints.
6. **Save fixes** — `fo_solved()` after every fix
7. **Record decisions** — `fo_decide()` after important project decisions
8. **Sync on progress** — `fo_sync()` after meaningful work (code changes, decisions, direction changes)
9. **Specific next_step** — must be actionable: "Fix validation in api/endpoints.py:203" not "Continue work"

---

## Active Decisions

| Decision | Reason |
|----------|--------|
| **Dashboard UI = English** | User preference |

---

## Fresh Install QA (run on new user)

If user says **"run fresh install QA"** or **"בדיקת התקנה"**, execute ALL steps below and report results.

### Step 1: Pre-install state (should be clean)
```bash
ls -la ~/.fixonce 2>/dev/null && echo "⚠️ EXISTS" || echo "✓ Clean"
ls ~/Library/LaunchAgents/*fixonce* 2>/dev/null && echo "⚠️ EXISTS" || echo "✓ Clean"
pgrep -fl "server.py" && echo "⚠️ RUNNING" || echo "✓ No process"
```

### Step 2: Run install
```bash
cd [project-path]
./install.sh
```

### Step 3: Verify server
```bash
# Wait for server to start
sleep 3
curl -s http://localhost:5000/api/ping
curl -s http://localhost:5000/api/status | head -20
```

### Step 4: Verify LaunchAgent
```bash
cat ~/Library/LaunchAgents/com.fixonce.server.plist
launchctl list | grep fixonce
```

### Step 5: Test fo_init + fo_errors
```
fo_init(cwd="[project-path]")
fo_errors()
```

### Step 6: Test error flow
```bash
# Send test error
curl -s -X POST http://localhost:5000/api/log_error \
  -H "Content-Type: application/json" \
  -d '{"type":"error","data":{"message":"QA test error"}}'
```
Then run `fo_errors()` and verify it appears.

### Step 7: Test clear flow
```bash
curl -s -X POST http://localhost:5000/api/clear_errors
```
Then run `fo_errors()` and verify "No browser errors".

### Step 8: Report results
```
### Fresh Install QA Results

| Check | Result |
|-------|--------|
| Pre-install clean | ✓/✗ |
| Install completed | ✓/✗ |
| Server responds | ✓/✗ |
| LaunchAgent exists | ✓/✗ |
| fo_init works | ✓/✗ |
| fo_errors works | ✓/✗ |
| Error capture works | ✓/✗ |
| Clear works | ✓/✗ |

**Verdict:** Ready / Not Ready
**Issues found:** [list any]
```
