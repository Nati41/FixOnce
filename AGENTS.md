# FixOnce Project - Codex Instructions

This IS the FixOnce project itself - a persistent memory layer for AI coding assistants.

## On Session Start

1. Call `fo_init(cwd="project-path")` — ONCE only
2. Respond with 1-2 lines max

## Opening Style

**Use fo_init data for grounded opening:**
- Mention goal, last action, next step — naturally
- Sound like resuming work with a partner
- 2-3 lines max, no generic phrases

**Good:**
```
Back to FixOnce — working on sync polish.
Last: fixed port detection. Next: verify dashboard.
```

**Skip:**
- "Ready", "How can I help"
- Step lists (1. 2. 3.)
- Long context dumps

**ACTION_REQUIRED:** If fo_init contains `ACTION_REQUIRED: fo_X` — call that tool immediately.
After: Be proactive — suggest fix or offer to apply. Don't ask "מה צריך שאעשה?"

---

## Tools (fo_* workflow)

| Tool | Purpose |
|------|---------|
| `fo_init` | Start session |
| `fo_errors` | Check browser errors |
| `fo_apply` | Apply known fix (when AUTO-FIX READY) |
| `fo_sync` | Update context after changes |
| `fo_search` | Search past solutions |
| `fo_solved` | Record a fix |
| `fo_decide` | Record a decision |

## Project Structure

- `src/server.py` - Flask main server
- `src/mcp_server/mcp_memory_server_v2.py` - MCP tools
- `src/core/` - Business logic
- `src/api/` - REST endpoints
- `data/dashboard.html` - Dashboard UI

## Rules

1. `fo_init()` before anything
2. If AUTO-FIX READY → `fo_apply()` immediately
3. `fo_sync()` after code changes

## Testing

```bash
python3 tests/stress_test.py --quick
```
