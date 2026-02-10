# FixOnce

> **Your AI Never Forgets.**

FixOnce is an **AI Memory Layer** that gives AI coding assistants (Claude, Cursor, Copilot) persistent memory across sessions. Your AI remembers errors, solutions, decisions, and context - picking up exactly where you left off.

---

## Why FixOnce?

| Without FixOnce | With FixOnce |
|----------------|--------------|
| AI forgets everything each session | Full context persists forever |
| Debug the same bug repeatedly | AI finds past solutions instantly |
| Explain project context every time | AI knows your stack & decisions |
| Manual documentation | Auto-saved insights & lessons |

---

## Quick Start

### 1. Install & Run
```bash
# Clone
git clone https://github.com/Nati41/FixOnce.git
cd FixOnce

# Run
python3 src/server.py
```

### 2. Open Dashboard
```
http://localhost:5000
```

### 3. Connect Your AI Editor

**Claude Code** (Automatic):
```bash
# Add to ~/.claude/settings.json
{
  "mcpServers": {
    "fixonce": {
      "command": "python3",
      "args": ["/path/to/FixOnce/src/mcp_server/mcp_memory_server_v2.py"]
    }
  }
}
```

**Cursor / GitHub Copilot** (Manual prompts):
Open Dashboard → Start AI Session → Copy prompts

---

## Supported Editors

| Editor | Integration | How It Works |
|--------|-------------|--------------|
| **Claude Code** | Automatic (MCP) | Just say "היי" - connects automatically |
| **Cursor** | Copy Prompts | Paste commands from dashboard |
| **GitHub Copilot** | Copy Prompts | Paste commands from dashboard |

---

## Dashboard Features

### Live Activity Feed
- Real-time tracking of all AI actions
- **Tool badges** - See who did what (Claude/Cursor/Watcher)
- **File links** - Click to open in editor
- **Delete controls** - Remove single or all activities

### Project Memory
- **Architecture** - Stack, structure, key flows
- **Intent** - Current goals & next steps
- **Lessons** - Insights & failed attempts
- **Decisions** - Why you chose X over Y
- **Avoid Patterns** - What NOT to do

### Multi-Project Support
- Switch between projects instantly
- Each project has isolated memory
- Auto-detect by port or directory

---

## MCP Tools

### Session Start
```python
auto_init_session()        # Auto-detect project
init_session(port=3000)    # By port
init_session(working_dir="/path")  # By path
```

### During Work
```python
search_past_solutions("error keywords")  # Find past fixes
update_live_record("lessons", {"insight": "..."})  # Save learning
log_decision("Use Redis", "Better for our scale")  # Record choice
log_avoid("moment.js", "Too heavy, use date-fns")  # Record failure
```

### After Fixing
```python
get_live_record()          # See full memory
get_recent_activity(10)    # Recent file changes
```

---

## Project Structure

```
FixOnce/
├── src/
│   ├── server.py              # Main Flask server
│   ├── api/                   # REST endpoints
│   │   ├── activity.py        # Activity feed
│   │   ├── memory.py          # Memory management
│   │   └── projects.py        # Multi-project
│   ├── mcp_server/
│   │   └── mcp_memory_server_v2.py  # MCP tools
│   └── managers/
│       └── multi_project_manager.py
├── data/
│   ├── brain_dashboard.html   # Dashboard UI
│   ├── activity_log.json      # Activity history
│   └── projects_v2/           # Project memories
├── hooks/                     # Claude Code hooks
│   ├── post_tool_use.sh
│   ├── session_start.sh
│   └── session_end.sh
└── tests/
```

---

## API Endpoints

### Activity
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/activity/feed` | Get activity feed |
| POST | `/api/activity/log` | Log new activity |
| DELETE | `/api/activity/{id}` | Delete single activity |
| DELETE | `/api/activity/clear` | Clear all activities |

### Memory
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/memory/live-record` | Get project memory |
| POST | `/api/memory/live-record/{section}` | Update section |
| GET | `/api/memory/decisions` | Get decisions |
| GET | `/api/memory/avoid` | Get avoid patterns |

### Projects
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects` | List all projects |
| POST | `/api/projects/switch` | Switch active project |
| POST | `/api/projects/scan` | Scan new project |

---

## How AI Uses FixOnce

### Session Start
```
User: "היי"
AI: [Calls auto_init_session()]
AI: "🎯 פרויקט: MyApp - React + Node
     📍 איפה עצרנו: תיקון באג בlogin
     💡 תובנה: השתמשנו ב-JWT במקום sessions
     נמשיך מכאן?"
```

### Before Fixing Errors
```
AI: [Calls search_past_solutions("TypeError undefined")]
AI: "מצאתי שטיפלנו בזה - מחיל את אותו פתרון"
```

### After Learning Something
```
AI: [Calls update_live_record("lessons", {"insight": "..."})]
AI: "שמרתי את התובנה לזיכרון"
```

---

## Changelog

### v2.1.0 - Multi-Editor Support
- Added GitHub Copilot support (replaced Windsurf)
- Copy-to-clipboard buttons for Cursor/Copilot
- Tool badges in activity feed (Claude/Cursor/Watcher)
- File path links in activities
- Activity delete controls (single + clear all)
- Removed Live Memory Sync (redundant)

### v2.0.0 - AI Memory Layer
- Complete rewrite with MCP integration
- Multi-project support
- Live Record system (GPS, Architecture, Intent, Lessons)
- Dashboard with real-time activity feed
- Hebrew-first UI

---

## License

MIT

---

**Your AI Never Forgets.** Made with ❤️ for developers who value their time.
