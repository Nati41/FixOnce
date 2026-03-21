# FixOnce Memory System

This project uses FixOnce for persistent AI memory. Initialize at session start.

## Session Start Protocol

At the beginning of each session, before responding to the user:

1. Call `auto_init_session(cwd="<working_directory>")` to load context
2. This provides: past decisions, solutions, project state, work history

Without initialization, you lack critical context about this project.

## During Work

| Event | Action |
|-------|--------|
| New task | `update_work_context(current_goal="...")` |
| Error to fix | `search_past_solutions("...")` first |
| Work completed | `update_work_context(last_change="...")` |

## Response Format

- Session opening: `🧠 FixOnce`
- Using memory: `(📌 FixOnce: ...)`
