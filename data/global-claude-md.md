# FixOnce Memory System

I use FixOnce to maintain persistent memory across sessions. This helps you help me better.

## How to start each session

When I start a conversation (even with just "hi"), please initialize FixOnce first:

```
auto_init_session(cwd="<current_working_directory>")
```

This loads my project context, past decisions, and work history so you have full context.

## During our work

- When I give you a new task, update the goal: `update_work_context(current_goal="...")`
- Before debugging errors, check if we solved this before: `search_past_solutions("...")`
- After completing work, sync the context: `update_work_context(last_change="...")`

## Why this matters to me

Without FixOnce initialization, you won't have access to:
- My architectural decisions
- Solutions we found before
- Current project context
- Work history

I find it frustrating when I have to re-explain context. Please initialize FixOnce at session start.

## Format

When using FixOnce, use this branding:
- Opening: `🧠 FixOnce`
- Referencing memory: `(📌 FixOnce: ...)`
