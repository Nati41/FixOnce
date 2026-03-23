# FixOnce — AI Memory Layer

> **DOGFOODING**: This IS the FixOnce project. AI MUST use FixOnce correctly.

## Disable

Say "no fixonce" to disable. Otherwise, FixOnce is mandatory.

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
| `fo_sync(last_change)` | After edits |
| `fo_decide(text, reason)` | Record decision |
| `fo_component(action, name)` | Track components |

---

## Rules

1. **Init first** — `fo_init()` before anything
2. **Auto-fix first** — if AUTO-FIX READY, use `fo_apply()` immediately
3. **Save fixes** — `fo_solved()` after every fix
4. **Sync context** — `fo_sync()` after edits

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
