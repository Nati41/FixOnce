# FixOnce

> **Never debug the same bug twice.**

FixOnce is an **AI Memory Layer** - an error tracking system that gives AI assistants persistent memory across sessions. Errors, solutions, decisions, and context are preserved so AI can pick up exactly where it left off.

---

## What Makes FixOnce Different

| Traditional Error Tracking | FixOnce AI Memory Layer |
|---------------------------|------------------------|
| Logs errors for humans to read | AI reads and acts on errors directly |
| No memory between sessions | Full context persists across sessions |
| Manual solution documentation | Solutions auto-saved with search keywords |
| Start from scratch each time | AI knows what was done, what worked, what to avoid |

---

## Core Features

### Error Tracking
- **X-Ray Error Capture** - Code snippets + variable values at crash time
- **Smart Deduplication** - Same error counted once, not flooding
- **Full File Paths** - AI can locate and fix files directly
- **Multi-language** - JavaScript, Python, any language

### AI Memory Layer
- **Handover** - Session summaries that transfer context to next AI session
- **Decisions** - Architectural choices preserved ("Use Redux over Context - why...")
- **Avoid Patterns** - Failed approaches documented ("Don't use moment.js - too heavy")
- **Solutions History** - Searchable database of past fixes with keywords

### Smart Partner Persona
- **Confident Opening** - AI presents context immediately, no fumbling
- **Proactive** - Just fixes and informs, doesn't ask permission for small steps
- **Memory-Aware** - References past decisions ("Based on our decision to use UUID...")
- **Hebrew-First** - Natural Hebrew communication, chat-style

### Real Usage Stats
- Solutions reused count
- Sessions with context count
- Decisions referenced count
- Errors prevented count

---

## Quick Start

### 1. Start the Server
```bash
cd server
python3 server.py
```

### 2. Open Dashboard
```
http://localhost:5000/brain
```

### 3. Configure AI Editor
Add to your MCP config (`~/.claude.json` or `~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "fixonce": {
      "command": "python3",
      "args": ["/path/to/FixOnce/server/mcp_memory_server.py"]
    }
  }
}
```

### 4. Set Project Root
```bash
curl -X POST http://localhost:5000/api/memory/project/root \
  -H "Content-Type: application/json" \
  -d '{"root_path": "/path/to/your/project"}'
```

---

## MCP Tools Reference

### Session Start
| Tool | Purpose |
|------|---------|
| `get_project_context_tool()` | Full context with project path, issues, decisions |
| `get_last_handover()` | Previous session summary |
| `get_avoid_patterns()` | What NOT to do |
| `get_project_decisions()` | Past architectural choices |

### During Work
| Tool | Purpose |
|------|---------|
| `search_past_solutions(query)` | Find existing fixes by keywords |
| `get_active_issues()` | List current problems with IDs |
| `get_issue_details(issue_id)` | Full issue info with file path |
| `set_current_focus(description)` | Update work status |
| `set_project_root(path)` | Set project root for file resolution |

### After Fixing
| Tool | Purpose |
|------|---------|
| `update_solution_status(id, solution, keywords)` | Record fix with searchable keywords |
| `log_project_decision(decision, reason)` | Record architectural choice |
| `log_avoid_pattern(what, reason)` | Record failed approach |

### Session End
| Tool | Purpose |
|------|---------|
| `create_handover(summary)` | Save session state for next AI |

---

## API Endpoints

### Core
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Server status |
| GET | `/api/memory` | Full memory dump |
| GET | `/api/memory/health` | Memory health metrics |

### Issues
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/log_error` | Log new error |
| GET | `/api/memory/issues` | Active issues |
| POST | `/api/memory/issues/<id>/resolve` | Mark resolved |
| POST | `/api/memory/clear-issues` | Clear all issues |

### AI Memory
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST/DELETE | `/api/memory/handover` | Manage handover |
| GET/POST/DELETE | `/api/memory/decisions` | Manage decisions |
| GET/POST/DELETE | `/api/memory/avoid` | Manage avoid patterns |
| POST | `/api/memory/project/root` | Set project root path |
| GET | `/api/memory/project/root` | Get project root path |

### Stats
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/memory/roi` | Usage statistics |
| POST | `/api/memory/roi/reset` | Reset stats |

### Export/Import
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/memory/export` | Export all memory |
| POST | `/api/memory/import` | Import memory backup |

---

## Dashboard Features

### Brain Dashboard (`/brain`)
- **Status Bar** - Clear/issues count with severity
- **AI Memory Section** - Handover, Decisions, Avoid patterns
- **Active Issues** - With full file paths for AI
- **Solutions History** - Searchable past fixes
- **Usage Stats** - Real counts (not estimates)
- **Quick Actions** - Copy context, detect stack, export/import
- **Full Hebrew/English** - Toggle with one click

### Test Site (`/test`)
- **4 Real Bug Scenarios** - JavaScript & Python
- **Full Workflow Testing** - Trigger → Fix → Save → Verify
- **ROI Tracking** - See stats update in real-time

---

## Project Structure

```
FixOnce/
├── server/
│   ├── server.py                 # Flask + MCP server
│   ├── project_memory_manager.py # Memory management
│   ├── mcp_memory_server.py      # MCP tools
│   ├── brain_dashboard.html      # AI Memory dashboard
│   └── project_memory.json       # Persistent storage
├── hooks/
│   ├── python/fixonce_hook.py    # Python error hook
│   └── node/fixonce-hook.js      # Node.js error hook
├── test-site/
│   ├── index.html                # Test dashboard
│   └── scenarios/                # Bug scenarios for testing
├── extension/                    # Chrome extension
├── CLAUDE.md                     # AI instructions
└── README.md
```

---

## CLAUDE.md Protocol

The `CLAUDE.md` file instructs AI assistants how to use FixOnce:

1. **Session Start** - Load context, handover, avoid patterns
2. **Before Fixing** - Search past solutions first
3. **After Fixing** - Save solution with keywords
4. **Session End** - Create handover for next session

See `CLAUDE.md` for full protocol.

---

## Hooks

### Python Hook
```python
from fixonce_hook import install_hook
install_hook()
# All unhandled exceptions now captured with X-Ray context
```

Features:
- Anti-loop guard (won't capture its own errors)
- Rate limiting (10 errors/minute max)
- Async non-blocking sends

### Node.js Hook
```javascript
require('./fixonce-hook');
// All unhandled exceptions + rejections captured
```

---

## Configuration

### Environment Variables
```bash
FIXONCE_PORT=5000          # Server port
FIXONCE_PROJECT_ROOT=/path # Default project root
```

### Memory File
All data stored in `server/project_memory.json`:
- Project info (name, stack, root_path)
- Active issues
- Solutions history
- Decisions & avoid patterns
- Handover
- Usage stats

---

## Changelog

### v2.0 - AI Memory Layer
- Added Handover system for session continuity
- Added Decisions & Avoid patterns
- Added project root path for file resolution
- Added real usage stats (not estimates)
- Added Smart Partner persona in CLAUDE.md
- Added test site with real bug scenarios
- Full Hebrew translation for all UI elements
- MCP tools for complete AI integration

### v1.0 - Initial Release
- Error capture with X-Ray
- Smart deduplication
- Basic dashboard
- Chrome extension
- Python hook

---

## License

MIT

---

Made with ❤️ for developers who hate debugging the same bug twice.

**Core Principle:** AI should remember. Every session should continue where the last one stopped.
