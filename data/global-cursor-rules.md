FixOnce should be used automatically at the first meaningful user message in every new session.

First-message examples: hi, hello, hey, היי, מה מצבנו, continue.

On the first meaningful user message:
1. Call fo_init(cwd="/path/to/project") silently.
2. Call it once per session unless the user explicitly asks to reconnect or the session is reset.
3. Show the fo_init opener exactly once.
4. Do not paraphrase the opener.
5. Do not add a duplicate opener or a second Ready. line.

If fo_init returns ACTION_REQUIRED, execute it immediately and continue.

During work:
- Before debugging, call fo_search(query).
- If browser failures matter, call fo_errors().
- After meaningful progress, call fo_sync(last_change, next_step).
- After fixing a bug, call fo_solved(error, solution).
- Record important decisions with fo_decide(text, reason).
