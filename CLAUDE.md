# FixOnce — AI Memory Layer

> FixOnce never blocks development. It only enhances it.

## Disable

If the user says "work without FixOnce" or "no fixonce" — stop calling all MCP tools. Work normally.

## Session Start

Try: `init_session(working_dir="/path/to/project")` or `init_session(port=5000)`

**If it works** — show context and follow rules below.
**If it fails** — proceed normally.

---

## When Active

- **Respect decisions** returned from init. Ask before contradicting.
- **Update goal** before work: `update_live_record("intent", ...)`
- **Log insights**: `update_live_record("lessons", ...)`
- **Log decisions**: `log_decision("...", "...")`
- **Search first**: `search_past_solutions("...")`

## New Project (status: NEW)

Ask "Want me to scan?" → `scan_project()` → save with `update_live_record`

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
