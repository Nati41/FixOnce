# Conversation Storage Analysis

**Date**: 2026-07-19  
**Purpose**: Evaluate external recap generation feasibility

---

## Claude Code Storage

### Location Structure

```
~/.claude/
├── sessions/                          # Active sessions (by PID)
│   └── {pid}.json                     # Active session metadata
├── projects/                          # Conversation storage by project
│   └── {project-path-encoded}/        # e.g., -Users-haimdayan-Desktop-FixOnce
│       ├── {session-uuid}.jsonl       # Full conversation transcript
│       └── memory/                    # Claude's auto-memory
└── history.jsonl                      # Global command history
```

### Identifying Active Conversation

**File**: `~/.claude/sessions/{pid}.json`

```json
{
  "pid": 28962,
  "sessionId": "73f62cec-78fa-40ee-959f-a601a11321c3",  // ← Conversation ID
  "cwd": "/Users/haimdayan/Desktop/FixOnce",            // ← Project path
  "status": "waiting",                                   // ← Current state
  "bridgeSessionId": "session_0128SAtyPVZKBPSh82eFj6EC"
}
```

**Stability**: ✅ Stable — JSON format, clear structure, documented fields

### Conversation Transcript Format

**File**: `~/.claude/projects/{path}/{session-uuid}.jsonl`

Each line is a JSON object with `type` field:
- `"type": "user"` with `"role": "user"` — Human input or tool results
- `"type": "assistant"` with `"role": "assistant"` — AI responses

**Message Structure (User)**:
```json
{
  "type": "user",
  "uuid": "...",
  "timestamp": "2026-07-19T05:38:44.056Z",
  "message": {
    "role": "user",
    "content": "היי"  // Simple string or array of content blocks
  },
  "sessionId": "73f62cec-78fa-40ee-959f-a601a11321c3",
  "cwd": "/Users/haimdayan/Desktop/FixOnce"
}
```

**Message Structure (Assistant)**:
```json
{
  "type": "assistant",
  "uuid": "...",
  "timestamp": "...",
  "message": {
    "role": "assistant",
    "content": [
      {"type": "thinking", "thinking": "..."},
      {"type": "text", "text": "..."},
      {"type": "tool_use", "name": "...", "input": {...}}
    ]
  }
}
```

**Extraction Stability**: ⚠️ Medium
- JSONL format is stable
- Message structure varies (string vs array content)
- Tool results interleaved with human messages
- Need to filter `userType: "human"` vs `userType: "external"` (tool results)

### Extraction Script

```python
import json

def extract_claude_conversation(session_id, project_path):
    """Extract user/assistant text from Claude Code conversation."""
    path = f"~/.claude/projects/{project_path}/{session_id}.jsonl"
    messages = []
    
    with open(path, "r") as f:
        for line in f:
            obj = json.loads(line)
            msg = obj.get("message", {})
            role = msg.get("role")
            content = msg.get("content")
            
            if role == "user":
                if isinstance(content, str) and content:
                    messages.append({"role": "user", "text": content})
                elif isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            messages.append({"role": "user", "text": item["text"]})
            elif role == "assistant":
                if isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            messages.append({"role": "assistant", "text": item["text"]})
    
    return messages
```

---

## Codex Storage

### Location Structure

```
~/.codex/
├── state_5.sqlite                     # Thread metadata
├── history.jsonl                      # Simple text history
├── sessions/                          # Full conversation rollouts
│   └── {year}/{month}/{day}/
│       └── rollout-{timestamp}-{thread-id}.jsonl
└── logs_2.sqlite                      # Debug logs (not conversations)
```

### Identifying Active Conversation

**Database**: `~/.codex/state_5.sqlite`
**Table**: `threads`

```sql
SELECT id, title, cwd, created_at, updated_at
FROM threads 
WHERE archived = 0
ORDER BY updated_at DESC
LIMIT 1;
```

**Fields**:
- `id` — Thread UUID
- `cwd` — Project directory
- `title` — Auto-generated title
- `first_user_message` — Initial prompt

**Stability**: ✅ Stable — SQLite schema, clear columns

### Conversation Transcript Format

**File**: `~/.codex/sessions/{year}/{month}/{day}/rollout-{timestamp}-{thread-id}.jsonl`

Each line is a JSON object with `type` field:
- `"type": "response_item"` with `payload.role` — Messages
- `"type": "event_msg"` with `payload.type: "agent_message"` — AI commentary

**User Message**:
```json
{
  "timestamp": "...",
  "type": "response_item",
  "payload": {
    "type": "message",
    "role": "user",
    "content": [
      {"type": "input_text", "text": "..."}
    ]
  }
}
```

**Agent Message**:
```json
{
  "type": "event_msg",
  "payload": {
    "type": "agent_message",
    "message": "...",
    "phase": "commentary"
  }
}
```

**Extraction Stability**: ⚠️ Medium
- JSONL format stable
- Multiple message types to handle
- System messages interleaved (permissions, skills, etc.)
- `input_text` vs `output_text` distinction

### Extraction Script

```python
import json
import sqlite3

def extract_codex_conversation(thread_id):
    """Extract user/assistant text from Codex conversation."""
    # Find rollout file
    import glob
    pattern = f"~/.codex/sessions/*/*/rollout-*-{thread_id}.jsonl"
    files = glob.glob(pattern)
    if not files:
        return []
    
    messages = []
    with open(files[0], "r") as f:
        for line in f:
            obj = json.loads(line)
            
            # User messages
            if obj.get("type") == "response_item":
                payload = obj.get("payload", {})
                if payload.get("role") == "user":
                    for item in payload.get("content", []):
                        if item.get("type") == "input_text":
                            text = item.get("text", "")
                            # Skip system instructions
                            if not text.startswith("<"):
                                messages.append({"role": "user", "text": text})
            
            # Agent messages
            if obj.get("type") == "event_msg":
                payload = obj.get("payload", {})
                if payload.get("type") == "agent_message":
                    messages.append({"role": "assistant", "text": payload.get("message", "")})
    
    return messages
```

---

## Feasibility: External Recap Generation

### Question 3: Can we summarize a real conversation externally?

**Answer: YES, with caveats.**

### Approach

1. **Identify conversation** — Read active session file (Claude) or query SQLite (Codex)
2. **Extract messages** — Parse JSONL, filter to user/assistant text
3. **Summarize** — Send to Claude API with recap prompt
4. **Store** — Write to FixOnce project memory

### Proof of Concept

```python
import anthropic
import json

def generate_recap(messages: list[dict]) -> str:
    """Generate recap from conversation messages."""
    
    # Format for summarization
    transcript = "\n\n".join([
        f"{'USER' if m['role'] == 'user' else 'ASSISTANT'}: {m['text'][:500]}"
        for m in messages
        if m.get('text')
    ])
    
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""Summarize this work session in 3-5 bullet points.
Focus on: what was accomplished, key decisions made, and what's next.

TRANSCRIPT:
{transcript[:8000]}

RECAP:"""
        }]
    )
    
    return response.content[0].text
```

### Quality Assessment

| Factor | Claude Code | Codex |
|--------|-------------|-------|
| Message extraction | Good | Good |
| Project identification | Excellent (cwd in session) | Excellent (cwd in thread) |
| Content quality | Full text available | Full text available |
| System noise | Low (filter by userType) | Medium (filter <tags>) |
| Stability | High | High |

**Expected Recap Quality**: ✅ Good to Excellent

The conversation transcripts contain enough context to generate meaningful recaps.

---

## Integration with FixOnce

### Finish & Save Flow (External Processing)

```
User clicks "Finish & Save" in Dashboard
    │
    ▼
Dashboard reads active session file
    │ ~/.claude/sessions/{pid}.json → sessionId, cwd
    │
    ▼
Dashboard extracts conversation
    │ ~/.claude/projects/{path}/{sessionId}.jsonl
    │
    ▼
Dashboard calls FixOnce recap API
    │ POST /api/episode/finish
    │ {conversation: [...], project_id: "..."}
    │
    ▼
FixOnce server generates recap (calls Claude API)
    │
    ▼
Recap stored in project memory
    │ ~/.fixonce/projects_v2/{project_id}.json → episode_history[]
    │
    ▼
Dashboard displays recap
```

### Required Components

1. **Session watcher** — Read Claude/Codex session files
2. **Transcript extractor** — Parse JSONL to messages
3. **Recap generator** — Call Claude API with transcript
4. **Storage layer** — Save to project memory
5. **Dashboard UI** — Trigger and display

### Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| File access requires local server | Dashboard must read filesystem | FixOnce server already runs locally |
| Claude API cost | ~$0.01-0.05 per recap | Acceptable for high-value feature |
| Conversation size | May exceed context window | Truncate old messages, summarize in chunks |
| Platform differences | Claude vs Codex formats differ | Abstract with platform adapters |
| No push to agent | Agent won't see recap | Recap is for human review, not agent |

---

## Verdict

### Q1: Where does Claude Code store transcripts?

`~/.claude/projects/{project-path-encoded}/{session-uuid}.jsonl`

Active session identified via `~/.claude/sessions/{pid}.json`

### Q2: Where does Codex store transcripts?

`~/.codex/sessions/{year}/{month}/{day}/rollout-{timestamp}-{thread-id}.jsonl`

Active thread identified via `~/.codex/state_5.sqlite` → `threads` table

### Q3: Can we generate good recaps externally?

**YES.** Both platforms store full conversation transcripts in parseable formats. External summarization via Claude API is feasible and should produce quality recaps.

---

## Recommended V1: Server-Side Recap

Given **VERDICT D** from communication analysis (no reliable Dashboard → Agent path), the best V1 is:

### Server-Side Finish & Save

1. User clicks "Finish & Save" in Dashboard
2. FixOnce server reads conversation transcript from disk
3. FixOnce server calls Claude API to generate recap
4. Recap stored in project memory
5. Dashboard displays recap for confirmation

**Agent role:** None (recap generated externally)

**Advantages:**
- No push mechanism needed
- No agent polling required
- Works even if agent session is closed
- Consistent quality (controlled prompt)

**Disadvantages:**
- Requires Claude API key on server
- Additional cost (~$0.01-0.05 per recap)
- Recap lacks agent's internal context

**Effort Estimate:** 5-7 days
