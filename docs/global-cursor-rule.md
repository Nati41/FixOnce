# FixOnce — Global Cursor Rule

Copy the text below into: **Cursor Settings → General → Rules for AI**

---

```
## FixOnce Memory (Optional)

If user says "no fixonce" or "work without fixonce" — skip all FixOnce tools.

Otherwise, at conversation start, try:
  MCP Tool: user-fixonce → auto_init_session
  Parameters: {"cwd": "<workspace root path>"}

If it works — show context, respect decisions, log insights during work.
If it fails — proceed normally. FixOnce never blocks development.
```
