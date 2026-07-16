# FixOnce Session Rules

Use FixOnce automatically at the first meaningful user message in every new session.

Examples of first meaningful messages:
- hi
- hello
- hey
- היי
- מה מצבנו
- continue

## Session Start

1. Call `fo_init(cwd="/path/to/project")` silently.
2. Call it once per session unless the user explicitly asks to reconnect or the session is reset.
3. Display the `fo_init` opener exactly once.
4. Do not paraphrase it.
5. Do not add a second opener or a second `Ready.` line.

If `fo_init` returns `ACTION_REQUIRED`, execute that action immediately and continue.

### If fo_init fails or is unavailable

Tell the user immediately:

```
⚠️ FixOnce is not connected.

Project memory will NOT be recorded.

Please ensure FixOnce is running,
then start a new Codex task.

Do you want to continue without FixOnce?
```

Do NOT continue silently. Get explicit user approval before proceeding without FixOnce.

## During Work

- Before debugging, call `fo_search(query)` to reuse previous fixes.
- If live browser failures matter, call `fo_errors()`.
- After a meaningful code or decision change, call `fo_sync(last_change, next_step)`.
- After fixing a bug, call `fo_solved(error, solution)`.
- Record important decisions with `fo_decide(text, reason)`.

### If fo_* tools fail during work

When any `fo_*` tool disappears or fails due to MCP connection loss:

1. Stop and notify the user immediately
2. Explain that FixOnce recording has stopped
3. Further work will not be saved into project memory
4. Recommend: ensure FixOnce is running, then start a new Codex task
5. Continue only if user explicitly approves working without FixOnce

### Before completion

Before marking task complete or committing:

1. Call `fo_status()` to verify FixOnce can record
2. If not connected: warn before finishing
3. Suggest syncing work after connection is restored

## Tools

| Tool | When |
|------|------|
| `fo_init(cwd)` | Start of session |
| `fo_status()` | Verify connection before commit/completion |
| `fo_search(query)` | Before debugging (check past solutions) |
| `fo_errors()` | Check browser errors |
| `fo_apply()` | Apply known fix (when AUTO-FIX READY) |
| `fo_sync(last_change, next_step)` | After meaningful progress |
| `fo_solved(error, solution)` | After fixing a bug |
| `fo_decide(text, reason)` | Record a decision |

## Guardrails

- No duplicate init in the same session.
- No setup explanation after the opener.
- No extra onboarding text after the opener if it already contains the next step.
