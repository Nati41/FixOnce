# FixOnce — AI Memory Layer

> FixOnce is mandatory for tracked work in this project.

## Disable

If the user says "work without FixOnce" or "no fixonce" — stop calling all MCP tools. Work normally.

## Session Start

Mandatory first step: `auto_init_session(cwd="/path/to/project")`

Fallback: `init_session(working_dir="/path/to/project")` or `init_session(port=5000)`

Do not continue with other FixOnce tools until session initialization succeeds.
If initialization fails, surface the failure and resolve it before continuing tracked work.

---

## When Active

- **Smart sync**: Check `get_live_record()` at key moments: session start, before significant code changes, when user mentions rules changed
- **Respect decisions** returned from init. Ask before contradicting.
- **Update goal** before work: `update_live_record("intent", ...)`
- **Log insights**: `update_live_record("lessons", ...)`
- **Log decisions**: `log_decision("...", "...")`
- **Search first**: `search_past_solutions("...")`

## New Project (status: NEW)

Ask "Want me to scan?" → `scan_project()` → save with `update_live_record`

## Enforcement

- FixOnce is in mandatory enforcement mode for MCP usage.
- Non-init FixOnce tools are blocked until explicit session initialization occurs.
- Do not bypass FixOnce by starting tracked work without an active session.

## Tools

| Tool | Purpose |
|------|---------|
| `auto_init_session` / `init_session` | Start session |
| `scan_project` | Scan new project |
| `update_live_record` | Save goal / lessons / architecture |
| `log_decision` | Record a decision |
| `log_avoid` | Record an anti-pattern |
| `search_past_solutions` | Search memory |
| `get_live_record` | Read memory |

## 🔒 Active Decisions

| Decision | Reason |
|----------|--------|
| **Dashboard/UI = English only** | User requested |

## 🎯 AI Context Mode

When user says "this", "that", "זה", "את זה" referring to a UI element:
1. Call `get_browser_context()`
2. The selected element is what they mean
3. Don't mention the mode - just use it naturally
