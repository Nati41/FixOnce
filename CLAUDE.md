# FixOnce — AI Memory Layer

> FixOnce is mandatory for tracked work in this project.
> **DOGFOODING RULE**: This IS the FixOnce project. AI MUST demonstrate proper usage.

## Disable

If the user says "work without FixOnce" or "no fixonce" — stop calling all MCP tools. Work normally.

## 🚨 CRITICAL: Session Start (FIRST THING!)

**BEFORE ANY OTHER RESPONSE**, call:
```
auto_init_session(cwd="/Users/haimdayan/Desktop/FixOnce")
```

This is NOT optional. Do NOT skip this step. Do NOT respond to the user before calling this.

If initialization fails, fix it before doing anything else.

---

## 🎯 Goal Update (MANDATORY)

**EVERY TIME the user gives a new task**, IMMEDIATELY call:
```
update_work_context(current_goal="...", work_area="...")
```

The Dashboard shows the Goal in real-time. A stale Goal = protocol violation.

Examples:
- User asks to fix installer → `update_work_context(current_goal="Fix installer port detection")`
- User asks about tests → `update_work_context(current_goal="Review test results")`
- User asks to add feature → `update_work_context(current_goal="Add [feature name]")`

---

## When Active

- **Smart sync**: Check `get_live_record()` at key moments
- **Respect decisions** returned from init. Ask before contradicting.
- **Update goal** before work: `update_work_context(current_goal=...)`
- **Log insights**: `update_live_record("lessons", ...)`
- **Log decisions**: `log_decision("...", "...")`
- **Search first**: `search_past_solutions("...")`
- **After changes**: `update_work_context(last_change="...", last_file="...")`

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
