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

## During Work

- Before debugging, call `fo_search(query)` to reuse previous fixes.
- If live browser failures matter, call `fo_errors()`.
- After a meaningful code or decision change, call `fo_sync(last_change, next_step)`.
- After fixing a bug, call `fo_solved(error, solution)`.
- Record important decisions with `fo_decide(text, reason)`.

## Guardrails

- No duplicate init in the same session.
- No setup explanation after the opener.
- No extra onboarding text after the opener if it already contains the next step.
