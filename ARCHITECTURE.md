# FixOnce - Architecture & Complete Guide

## What is FixOnce?

**AI Memory System** that prevents debugging the same bug twice.
The AI remembers errors, solutions, decisions, and context between sessions.

---

## Architecture

```
                          FRONTEND
   +--------------+    +--------------+    +--------------+
   |   Browser    |    |   Python     |    |   Manual     |
   |  (Extension) |    |   (Hook)     |    |   (AI Log)   |
   +------+-------+    +------+-------+    +------+-------+
          |                   |                   |
          +-------------------+-----------------+-+
                              |
                              v
   +----------------------------------------------------------+
   |                    Flask Server                           |
   |                   (Port 5001-5005)                        |
   |  +------------+  +------------+  +------------+          |
   |  | REST API   |  | Dashboard  |  | MCP Server |          |
   |  | /api/*     |  | /brain     |  | (stdio)    |          |
   |  +-----+------+  +------------+  +-----+------+          |
   +--------+-------------------------------+------------------+
            |                               |
            v                               v
   +----------------------------------------------------------+
   |                   MEMORY LAYER                            |
   |  +-------------+  +-------------+  +-------------+       |
   |  | project_    |  | SQLite DB   |  | Semantic    |       |
   |  | memory.json |  | (solutions) |  | Engine      |       |
   |  +-------------+  +-------------+  +-------------+       |
   +----------------------------------------------------------+
                              |
                              v
   +----------------------------------------------------------+
   |                    AI EDITORS                             |
   |         Claude Code  |  Cursor  |  Windsurf               |
   +----------------------------------------------------------+
```

---

## Components

### 1. Chrome Extension
**Purpose:** Intercept browser errors

| What's Captured | How |
|-----------------|-----|
| `console.error()` | Override |
| `console.warn()` | Override |
| `window.onerror` | Event listener |
| Promise rejections | Event listener |
| HTTP errors (fetch/XHR) | Wrapper |

**Features:**
- Auto-focus on localhost, dev.*, staging.*
- Sanitizes sensitive data (emails, tokens, passwords)
- Domain whitelist
- Badge with error count

### 2. Python Hook
**Purpose:** Capture backend errors

```python
import nati_hook
nati_hook.install()
```

**What's Sent:**
- Exception type + message
- File, line, function
- Code snippet (5 lines before/after)
- Local variables
- Full stack trace

### 3. Flask Server
**Purpose:** Central API + MCP

| Endpoint | Purpose |
|----------|---------|
| `/api/log_error` | Receive error |
| `/api/log_errors_batch` | Batch errors |
| `/api/memory` | Full JSON |
| `/api/memory/summary` | Markdown for AI |
| `/brain` | Dashboard |

### 4. Project Memory (JSON)

```json
{
  "project_info": {
    "name": "Project Name",
    "stack": "React, Python"
  },
  "active_issues": [
    {
      "id": "err_a1b2c3d4",
      "type": "TypeError",
      "message": "Cannot read property...",
      "count": 3,
      "first_seen": "...",
      "last_seen": "..."
    }
  ],
  "solutions_history": [
    {
      "problem": "...",
      "solution": "...",
      "keywords": ["array", "null", "map"]
    }
  ],
  "decisions": [
    {
      "decision": "Use Chrome Extension",
      "reason": "No SDK needed"
    }
  ],
  "avoid": [
    {
      "what": "Don't use port 5000",
      "reason": "AirPlay conflict"
    }
  ],
  "handover": {
    "summary": "Session summary...",
    "created_at": "..."
  }
}
```

### 5. Semantic Engine
**Purpose:** Smart search for similar errors

- TF-IDF vectorization
- Cosine similarity (threshold 30%)
- Normalizes: removes timestamps, line numbers, paths

---

## MCP Tools (AI API)

### Session Start
| Tool | Purpose |
|------|---------|
| `get_project_context_tool()` | Full status + issue IDs |
| `get_last_handover()` | Previous session state |
| `get_avoid_patterns()` | What NOT to do |
| `get_project_decisions()` | Architectural decisions |

### During Work
| Tool | Purpose |
|------|---------|
| `search_past_solutions(query)` | Find existing solution |
| `get_active_issues()` | List issues with IDs |
| `get_issue_details(id)` | Full issue details |
| `set_current_focus(desc)` | Update current task |

### After Fix
| Tool | Purpose |
|------|---------|
| `update_solution_status(id, sol, kw)` | Save solution |
| `log_project_decision(dec, reason)` | Record decision |
| `log_avoid_pattern(what, reason)` | Record failure |

### Session End
| Tool | Purpose |
|------|---------|
| `create_handover(summary)` | Save state for next session |

---

## User Flow

```
1. INSTALLATION (once)
   +----------------+
   | Install        |
   | Extension      |---> Chrome Extensions
   | + Server       |---> python server.py
   | + MCP Config   |---> ~/.claude.json
   +----------------+

2. DAILY DEVELOPMENT
   +----------------+     +----------------+     +----------------+
   | Code in        |---->| Error in       |---->| Extension      |
   | Browser        |     | Console        |     | Captures       |
   +----------------+     +----------------+     +-------+--------+
                                                         |
                                                         v
   +----------------+     +----------------+     +----------------+
   | AI Suggests    |<----| Server         |<----| Sends to       |
   | Solution       |     | Finds Match    |     | Server         |
   +----------------+     +----------------+     +----------------+

3. AI CONVERSATION
   +----------------+
   | "hi"           |---> AI checks FixOnce automatically
   +----------------+     Shows: issues, handover, avoid patterns

   +----------------+
   | "fix the       |---> AI searches past solutions first
   |  error"        |     Applies if found, logs if new
   +----------------+

   +----------------+
   | "bye"          |---> AI creates handover automatically
   +----------------+     Saves state for next session
```

---

## AI Flow

```
SESSION START
-------------
User: "hi"
        |
        v
+-------------------------------------+
| 1. get_project_context_tool()       | <-- Issue IDs visible!
| 2. get_last_handover()              |
| 3. get_avoid_patterns()             |
+-------------------------------------+
        |
        v
AI: "Hi! 0 active issues, continuing from [handover]"


FIXING ERROR
------------
User: "fix TypeError map undefined"
        |
        v
+-------------------------------------+
| search_past_solutions("map undef")  |
+-------------------------------------+
        |
   +----+----+
   v         v
FOUND     NOT FOUND
   |         |
   v         v
Apply it   Fix it
   |         |
   v         v
"Solved    update_solution_status(
before"      "err_xxx",
             "Added null check",
             ["array","map","null"]
           )


DURING WORK
-----------
+-------------------------------------+
| Made decision?                       |
| -> log_project_decision()           |
|                                      |
| Something failed?                    |
| -> log_avoid_pattern()              |
|                                      |
| Milestone done?                      |
| -> create_handover() checkpoint     |
|                                      |
| Switching task?                      |
| -> set_current_focus()              |
+-------------------------------------+


SESSION END
-----------
User: "bye" / "done" / "finish"
        |
        v
+-------------------------------------+
| create_handover("""                 |
|   ## Done: [what works]             |
|   ## Insight: [key learning]        |
|   ## Next: [one action]             |
| """)                                |
+-------------------------------------+
        |
        v
AI: "Saved handover, goodbye!"
```

---

## Data Flow - Error End-to-End

```
Browser Error
     |
     v
+-------------+
| logger.js   |  Intercepts console.error
| (MAIN)      |  Sanitizes data
+-----+-------+
      | window.postMessage
      v
+-------------+
| bridge.js   |  Relays to extension
| (ISOLATED)  |
+-----+-------+
      | chrome.runtime.sendMessage
      v
+-------------+
| background  |  Checks whitelist
| .js         |  Queues & batches
+-----+-------+
      | HTTP POST
      v
+-------------+
| Flask       |  /api/log_error
| Server      |  Deduplicates
+-----+-------+
      |
      v
+-------------+
| Semantic    |  Searches for similar
| Engine      |  Returns match if found
+-----+-------+
      |
      v
+-------------+
| Project     |  Stores in active_issues
| Memory      |  Updates count if exists
+-----+-------+
      |
      v
+-------------+
| Desktop     |  macOS notification
| Notif       |  (if critical)
+-----+-------+
      |
      v
+-------------+
| MCP Tools   |  AI can query via
|             |  get_active_issues()
+-------------+
```

---

## Important Files

| File | Location | Purpose |
|------|----------|---------|
| Server | `server/server.py` | Flask + MCP |
| MCP Tools | `server/mcp_memory_server.py` | AI interface |
| Memory | `server/project_memory.json` | Persistent state |
| Semantic | `server/semantic_engine.py` | Smart search |
| Extension | `extension/` | Chrome MV3 |
| Python Hook | `hooks/python/nati_hook.py` | Backend capture |
| Protocol | `CLAUDE.md` | AI instructions |
| Global | `~/.claude/CLAUDE.md` | Cross-project rules |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Flask + FastMCP (Python) |
| Database | SQLite + JSON |
| Search | scikit-learn (TF-IDF) |
| Extension | Chrome MV3 |
| GUI | pywebview |
| AI Protocol | MCP (Model Context Protocol) |

---

## Key Principle

```
+=====================================================+
|                                                     |
|     Never debug the same bug twice.                 |
|                                                     |
|     - Always check FixOnce BEFORE fixing            |
|     - Always record solutions AFTER fixing          |
|     - Always handover at session END                |
|                                                     |
+=====================================================+
```

---

## Quick Start

1. **Start Server:**
   ```bash
   cd /Users/haimdayan/Desktop/FixOnce
   python server/server.py
   ```

2. **Install Extension:**
   - Open `chrome://extensions`
   - Enable Developer Mode
   - Load unpacked -> select `extension/` folder

3. **Configure MCP (Claude Code):**
   ```json
   // ~/.claude.json
   {
     "mcpServers": {
       "fixonce": {
         "command": "python3",
         "args": ["/path/to/FixOnce/server/mcp_memory_server.py"]
       }
     }
   }
   ```

4. **Start Coding!**
   - Errors are captured automatically
   - AI checks FixOnce on every session start
   - Solutions are remembered forever
