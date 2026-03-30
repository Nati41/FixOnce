# FixOnce

> **Your AI fixes bugs — and remembers everything.**

**👉 Install FixOnce here:**
https://nati41.github.io/FixOnce/install.html

---

## What You Get

| Feature | How It Works |
|---------|--------------|
| **Continuation** | AI picks up where you left off — automatically |
| **Auto-Fix** | AI detects known errors and applies fixes — automatically |
| **Controlled Memory** | You tell the AI what to remember — it saves and retrieves on request |

---

## How It Works

```
You: "Fix the bug"
AI: checks fo_errors() → finds known fix → applies it → done

Dashboard shows:
✓ No errors
Recent: Fixed: .map() null error (just now)
```

Your AI learns from every fix. Next time the same error appears — it already knows the solution.

---

## Dashboard

```
http://localhost:5000
```

Shows:
- Current project and goal
- Errors detected + auto-fixes ready
- Recent activity (what was just fixed)
- System status (Server / Extension / Memory)

---

## Controlled Memory

FixOnce doesn't auto-save everything. You control what gets remembered:

```
You: "Remember: we're using date-fns instead of moment.js"
AI: saves decision

Later:
You: "What date library are we using?"
AI: retrieves → "date-fns"
```

The AI saves what you tell it, and retrieves when you ask.

---

## MCP Tools (fo_* workflow)

| Tool | Purpose |
|------|---------|
| `fo_init` | Start session |
| `fo_errors` | Check browser errors |
| `fo_apply` | Apply known fix |
| `fo_sync` | Update context after changes |
| `fo_search` | Search past solutions |
| `fo_solved` | Record a fix |
| `fo_decide` | Record a decision |

---

## Supported Editors

- **Claude Code** — MCP integration
- **Cursor** — MCP integration
- **Codex** — MCP integration

---

## For Developers

If you prefer manual setup:

```bash
git clone https://github.com/Nati41/FixOnce.git
cd FixOnce
pip3 install -r requirements.txt
python3 src/server.py
```

Then configure MCP for your editor. See [docs](https://nati41.github.io/FixOnce/).

---

## Version

**v1.0.12** — Port 5000

---

## License

MIT

---

**Never debug the same bug twice.**
