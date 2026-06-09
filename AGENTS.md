# FixOnce Project - Codex Instructions

This IS the FixOnce project itself - a persistent memory layer for AI coding assistants.

## On Session Start

1. Call `fo_init(cwd="project-path")` silently — ONCE only
2. Display the `fo_init` opener exactly once
3. Do not paraphrase, summarize, or repeat it
4. Do not add anything after it if the opener already includes `Ready.`

## Opening Style

**Required output:**
- Call `fo_init` silently — no "I'll start...", "Checking...", "Let me..."
- `fo_init` returns the final human opener, including formatting and `Ready.`
- Display that opener once, exactly as returned
- Do not add a separate `Ready.` line

**Do not:**
- Explain setup (Codex configured, MCP connected, etc.)
- Ask "What should we tackle next?" if `fo_init` already includes Next
- Restate, paraphrase, or summarize the opener
- Add commentary, verification notes, or follow-up questions after the opener

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

After changing Flask API or server modules, restart the local FixOnce server
before manual validation. The development server does not reload code changes
automatically.
