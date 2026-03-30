# FixOnce — AI Memory Layer

> **DOGFOODING**: This IS the FixOnce project. AI MUST use FixOnce correctly.

## Disable

Say "no fixonce" to disable. Otherwise, FixOnce is mandatory.

---

## Opening

**Use fo_init data to ground your opening:**
- Mention the goal, what was done, what's next
- Sound like a working partner, not a tool output
- 2-3 lines, natural, action-oriented
- No generic: "Ready", "How can I help"

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
| `fo_errors()` | Check browser errors |
| `fo_apply()` | **When AUTO-FIX READY** (mandatory) |
| `fo_search(query)` | Before fixing unknown errors |
| `fo_solved(error, solution)` | After fixing any error |
| `fo_sync(last_change, next_step)` | After meaningful progress |
| `fo_decide(text, reason)` | Record decision |
| `fo_component(action, name)` | Track components |

---

## Rules

1. **Init first** — `fo_init()` before anything
2. **Auto-fix first** — if AUTO-FIX READY, use `fo_apply()` immediately
3. **Save fixes** — `fo_solved()` after every fix
4. **Sync on progress** — `fo_sync()` after any meaningful work:
   - Code changes
   - Decisions made
   - Direction changes
   - Completing a step
   - Reaching a clear next action
5. **Specific next_step** — must be actionable:
   - Good: "Fix validation in api/endpoints.py:203"
   - Bad: "Continue work"
6. **Sync at stopping points** — call `fo_sync(last_change, next_step)` when reaching natural pauses, don't rely on session end

---

## Voice & Behavior

**NEVER say:**
- "Let's test...", "Checking tools...", "The format works"
- "Do you want me to...?" (for obvious actions)

**ALWAYS:**
- Act immediately on known fixes
- Speak like a working assistant, not a validator
- Execute API calls silently, show only results

**When fo_apply returns a fix:**
1. Apply it to code immediately
2. Respond: "🔧 Fixed [brief description]"

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
