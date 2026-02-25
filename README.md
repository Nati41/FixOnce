# FixOnce

> **Your AI Never Forgets.**

FixOnce gives AI coding assistants (Claude, Cursor) persistent memory across sessions. Your AI remembers decisions, solutions, and context — picking up exactly where you left off.

---

## Quick Start (60 seconds)

```bash
git clone https://github.com/Nati41/FixOnce.git
cd FixOnce
bash setup.sh
```

That's it. The setup script:
1. Installs dependencies
2. Configures MCP for Cursor and Claude Code
3. Starts the server

After setup: **Reload Cursor** (Cmd+Shift+P → Reload Window) and start chatting. FixOnce works automatically.

---

## Manual Setup

If you prefer to set things up yourself:

### 1. Install

```bash
git clone https://github.com/Nati41/FixOnce.git
cd FixOnce
pip3 install flask flask-cors requests fastmcp scikit-learn watchdog
```

### 2. Configure MCP

**Cursor** — add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "fixonce": {
      "command": "python3",
      "args": ["/absolute/path/to/FixOnce/src/mcp_server/mcp_memory_server_v2.py"]
    }
  }
}
```

**Claude Code** — add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "fixonce": {
      "command": "python3",
      "args": ["/absolute/path/to/FixOnce/src/mcp_server/mcp_memory_server_v2.py"]
    }
  }
}
```

### 3. Start Server

```bash
python3 src/server.py
```

### 4. Reload Your Editor

Cursor: Cmd+Shift+P → Reload Window

---

## How It Works

```
You open a project → AI starts a conversation
                          │
                          ▼
              AI calls auto_init_session()
                          │
              ┌───────────┴───────────┐
              │                       │
         New project            Existing project
              │                       │
     "Want me to scan?"     Shows: goal, decisions,
              │                insights, avoid patterns
              ▼                       │
     AI scans & saves          AI continues with
     architecture               full context
```

**If FixOnce isn't running** — AI works normally. No errors, no blocking.

---

## What Gets Remembered

| Category | Example |
|----------|---------|
| **Decisions** | "Use JWT instead of sessions — stateless scaling" |
| **Insights** | "React Query handles caching better than manual fetch" |
| **Avoid** | "Don't use moment.js — too heavy, use date-fns" |
| **Architecture** | Stack, structure, key flows |
| **Goals** | Current task, next steps, blockers |

---

## Dashboard

```
http://localhost:5000
```

Three layers:
- **Overview** — active AI sessions, value metrics, projects, recent changes
- **Project View** — timeline, insights, decisions, avoid patterns
- **Advanced** — semantic index, debug tools (hidden by default)

---

## Supported Editors

| Editor | Integration | Setup |
|--------|-------------|-------|
| **Cursor** | MCP (automatic) | `setup.sh` or manual `mcp.json` |
| **Claude Code** | MCP (automatic) | `setup.sh` or manual `settings.json` |

---

## MCP Tools

| Tool | Purpose |
|------|---------|
| `auto_init_session` | Initialize session (auto-detect project) |
| `scan_project` | Scan new project structure |
| `update_live_record` | Update memory (goal, lessons, architecture) |
| `log_decision` | Log a decision with reason |
| `log_avoid` | Log an anti-pattern |
| `search_past_solutions` | Search past insights and solutions |
| `get_live_record` | Read current project memory |

---

## Project Structure

```
FixOnce/
├── src/
│   ├── server.py                    # Flask server
│   ├── api/                         # REST endpoints
│   ├── mcp_server/
│   │   └── mcp_memory_server_v2.py  # MCP tools (AI interface)
│   ├── core/                        # Business logic
│   └── managers/                    # Project management
├── data/
│   ├── dashboard_vnext.html          # Dashboard UI
│   └── projects_v2/                 # Project memories
├── setup.sh                         # One-command setup
└── tests/
```

---

## License

MIT

---

**Your AI Never Forgets.**
