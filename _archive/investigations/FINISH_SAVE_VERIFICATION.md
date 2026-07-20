# Finish & Save Communication Path Verification

**Date**: 2026-07-19  
**Scope**: Live verification of Dashboard → Agent communication claim  
**Constraint**: NO CODE CHANGES

---

## Executive Summary

**VERDICT: D — No Reliable Delivery Path**

The `ai_queue` mechanism exists but **cannot reliably deliver commands to an active agent** because:

1. The `get_pending_commands()` tool is **not exposed to Claude Code**
2. Pending command injection only occurs in 4 rarely-used tools
3. There is no push mechanism — agent must poll via MCP tool call
4. Agent waiting for user input **cannot receive dashboard commands**

---

## Test 1: Code Path Mapping

### Step 1: Dashboard → ai_queue write

| Aspect | Value |
|--------|-------|
| File | `src/api/memory.py` |
| Function | `api_queue_for_ai()` |
| Lines | 205-246 |
| Initiator | Dashboard (user click) or REST client |
| Type | Synchronous HTTP POST |
| Endpoint | `POST /api/memory/queue-for-ai` |

**Code:**
```python
@memory_bp.route("/queue-for-ai", methods=["POST"])
def api_queue_for_ai():
    # Creates command with id, type, message, status="pending"
    ai_queue.append(command)
    memory["ai_queue"] = ai_queue
    save_project_memory(project_id, memory)
```

### Step 2: Pending command storage

| Aspect | Value |
|--------|-------|
| File | `~/.fixonce/projects_v2/{project_id}.json` |
| Key | `ai_queue` (array) |
| Initiator | REST API (from Step 1) |
| Type | Synchronous file write |

### Step 3: Command selection for injection

| Aspect | Value |
|--------|-------|
| File | `src/mcp_server/mcp_memory_server_v2.py` |
| Function | `_get_pending_commands_for_injection()` |
| Lines | 1841-1850 |
| Initiator | `_build_context_header()` |
| Type | Synchronous HTTP GET to REST API |

**Code:**
```python
def _get_pending_commands_for_injection() -> list:
    res = requests.get(f'{_get_api_url()}/api/memory/ai-queue', timeout=2)
    return data.get('commands', [])[:3]  # Max 3
```

### Step 4: Context header injection

| Aspect | Value |
|--------|-------|
| File | `src/mcp_server/mcp_memory_server_v2.py` |
| Function | `_build_context_header()` |
| Lines | 1906-1981 |
| Initiator | `_universal_gate()` |
| Type | Synchronous |

**Code:**
```python
def _build_context_header() -> str:
    # ... 
    pending_cmds = _get_pending_commands_for_injection()
    if pending_cmds:
        lines.append("📬 **PENDING COMMANDS FROM DASHBOARD:**")
        # ...
        lines.append("**Use `get_pending_commands()` to process these!**")
```

### Step 5: CRITICAL — When is context header injected?

| Aspect | Value |
|--------|-------|
| File | `src/mcp_server/mcp_memory_server_v2.py` |
| Function | `_universal_gate()` |
| Lines | 2088-2090 |
| Condition | **ONLY for tools in `_CONTEXT_HEADER_TOOLS`** |

**Code:**
```python
_CONTEXT_HEADER_TOOLS = {
    "get_live_record",
    "get_policy_status",
    "get_stability_report",
    "check_and_report",
}

# Line 2090:
context = _build_context_header() if tool_name in _CONTEXT_HEADER_TOOLS else ""
```

### Step 6: Agent-visible message

**The pending command notification is ONLY visible when:**
- Agent calls `get_live_record()`
- Agent calls `get_policy_status()`
- Agent calls `get_stability_report()`
- Agent calls `check_and_report()`

**The pending command notification is NOT visible when:**
- Agent calls `fo_init()` ❌
- Agent calls `fo_sync()` ❌
- Agent calls `fo_errors()` ❌
- Agent calls `fo_search()` ❌
- Agent calls `fo_solved()` ❌
- Agent calls any other fo_* tool ❌

### Step 7: get_pending_commands tool

| Aspect | Value |
|--------|-------|
| File | `src/mcp_server/mcp_memory_server_v2.py` |
| Function | `get_pending_commands()` |
| Lines | 9334-9401 |
| Decorated | `@mcp.tool()` ✓ |
| **Exposed to Claude Code** | **NO** ❌ |

**Evidence:**
The deferred tools list in system-reminder shows:
```
mcp__fixonce__fo_apply
mcp__fixonce__fo_brief
mcp__fixonce__fo_decide
mcp__fixonce__fo_errors
mcp__fixonce__fo_init
mcp__fixonce__fo_search
mcp__fixonce__fo_solved
mcp__fixonce__fo_status
mcp__fixonce__fo_sync
```

**Missing:**
- `mcp__fixonce__get_pending_commands` ❌
- `mcp__fixonce__mark_command_executed` ❌

### Step 8: mark_command_executed tool

| Aspect | Value |
|--------|-------|
| File | `src/mcp_server/mcp_memory_server_v2.py` |
| Function | `mark_command_executed()` |
| Lines | 9255-9330 |
| Decorated | `@mcp.tool()` ✓ |
| **Exposed to Claude Code** | **NO** ❌ |

---

## Answers to Specific Questions

### 1. לתוך מה `_get_pending_commands_for_injection()` מזריק את הפקודה?

**Answer:** Into the return value of `_build_context_header()`, which is prepended to tool responses **only for tools in `_CONTEXT_HEADER_TOOLS`** (4 tools: `get_live_record`, `get_policy_status`, `get_stability_report`, `check_and_report`).

### 2. מתי הפונקציה נקראת?

**Answer:** Only when `_universal_gate()` is called with a tool name that is in `_CONTEXT_HEADER_TOOLS`. This happens during execution of those 4 specific tools.

### 3. האם היא יכולה לרוץ כאשר הסוכן רק ממתין להודעת משתמש?

**Answer:** **NO.** The function only runs during MCP tool execution. When the agent is waiting for user input, no MCP tools are being called, so no injection can occur.

### 4. האם השרת יכול לפתוח turn חדש אצל הסוכן?

**Answer:** **NO.** The MCP protocol is request-response. The server cannot push a new turn to the agent. The server can only respond to tool calls initiated by the agent.

### 5. האם נדרשת קריאת MCP/REST נוספת מצד הסוכן?

**Answer:** **YES.** The agent must call an MCP tool for any communication to occur. The pending command would only be visible if:
- The agent calls one of the 4 `_CONTEXT_HEADER_TOOLS`, OR
- The agent calls `get_pending_commands()` (but this tool is not exposed)

### 6. האם `get_pending_commands()` הוא כלי שהסוכן חייב לקרוא מיוזמתו?

**Answer:** **YES, but the tool is not available.** The tool exists in the MCP server code (`@mcp.tool()` decorated) but is NOT exposed to Claude Code's tool list. I verified this by:
- Searching for the tool with ToolSearch — not found
- Checking the deferred tools list in system-reminder — not listed
- The tool IS registered with `@mcp.tool()` at line 9334

### 7. מה מבטיח שהסוכן אכן יקרא אותו?

**Answer:** **Nothing.** Even if the tool were available:
- The agent would need to proactively call it
- There's no protocol-level notification to prompt the call
- The injection in `_build_context_header()` says "Use `get_pending_commands()` to process these!" but this message only appears in 4 rarely-used tools

### 8. האם קיימת דרך platform-specific ל־push אמיתי ב־Claude Code או Codex?

**Answer:** **NO.** 
- Claude Code's MCP integration is request-response only
- There is no WebSocket push, no server-sent events, no polling loop
- The agent cannot receive unsolicited messages from the MCP server
- Codex has similar limitations

---

## Test 2: Live Experiment

### Step 1: Queue test command

```bash
curl -s -X POST http://localhost:5001/api/memory/queue-for-ai \
  -H "Content-Type: application/json" \
  -d '{"type":"test_verification","message":"VERIFICATION_TEST_2026_07_19_UNIQUE_ID_ABC123","source":"audit_test"}'
```

**Result:** `{"command_id":"b6f25c0d","status":"ok"}`

### Step 2: Verify command in queue

```bash
curl -s http://localhost:5001/api/memory/ai-queue
```

**Result:** Command exists with `status: "pending"`

### Step 3: Call fo_status (active agent, no user message)

Called `fo_status()` from active conversation.

**Result:** 
```
🟢 **FixOnce can currently record project memory.**
MCP connection is working. Project memory writes will succeed.
Last tool: fo_sync
```

**The pending command was NOT shown.** ❌

### Step 4: Attempt to call get_pending_commands

Searched for `get_pending_commands` in available tools.

**Result:** Tool not found. Not in deferred tools list. ❌

### Step 5: Conclusion

The command `VERIFICATION_TEST_2026_07_19_UNIQUE_ID_ABC123` was successfully queued but:
- Did NOT appear in fo_status response
- Cannot be retrieved because `get_pending_commands()` is not exposed
- Would NOT appear in any normal fo_* tool response
- Would ONLY appear if I called `get_live_record()`, `check_and_report()`, `get_policy_status()`, or `get_stability_report()`

---

## Architecture Diagram: Actual vs. Claimed

### Claimed Path (from original audit)

```
Dashboard
    │ POST /api/memory/queue-for-ai
    ▼
ai_queue write
    │
    ▼ "_get_pending_commands_for_injection()"
    │   → injected into EVERY tool response  ← WRONG
    ▼
Agent sees pending commands automatically  ← WRONG
    │
    ▼ get_pending_commands()  ← NOT AVAILABLE
    │
    ▼ mark_command_executed()  ← NOT AVAILABLE
```

### Actual Path

```
Dashboard
    │ POST /api/memory/queue-for-ai
    ▼
ai_queue write (works ✓)
    │
    ▼ "_get_pending_commands_for_injection()"
    │   → ONLY called by _build_context_header()
    │   → ONLY for 4 tools in _CONTEXT_HEADER_TOOLS
    │   → NOT for fo_init, fo_sync, fo_errors, etc.
    ▼
Agent sees pending commands ONLY IF:
    │   - Agent calls get_live_record() (rare)
    │   - Agent calls check_and_report() (rare)
    │   - Agent calls get_policy_status() (rare)
    │   - Agent calls get_stability_report() (rare)
    │
    ▼ get_pending_commands() — NOT EXPOSED TO AGENT
    ▼ mark_command_executed() — NOT EXPOSED TO AGENT
```

---

## Why The Tools Are Not Exposed

The MCP server defines 51 tools with `@mcp.tool()`, but Claude Code only shows 9 FixOnce tools:
- fo_apply
- fo_brief
- fo_decide
- fo_errors
- fo_init
- fo_search
- fo_solved
- fo_status
- fo_sync

**Hypothesis:** Claude Code or the MCP protocol layer may be filtering tools based on:
1. Name prefix pattern (`fo_*`)
2. Explicit allowlist
3. Tool count limit
4. Some other mechanism

The `get_pending_commands` and `mark_command_executed` tools don't match the `fo_*` pattern and are not exposed.

---

## VERDICT

### D — No Reliable Delivery Path

The ai_queue exists, but there is **no guarantee** that an active agent will see the command:

1. **No push mechanism**: MCP is request-response; server cannot initiate
2. **Injection limited**: Only 4 rarely-used tools get the context header
3. **Critical tools not exposed**: `get_pending_commands()` and `mark_command_executed()` are not available to the agent
4. **Agent must act first**: Without a tool call, no communication occurs

---

## V1 Recommendation Based on Actual Capability

Given **VERDICT D**, the viable V1 is:

### Agent-First Finish & Save

```
User says "סיימתי" / "finish" / "done"
    │
    ▼
Agent calls fo_finish() (new tool)
    │
    ▼
Agent generates recap
    │
    ▼
Agent writes recap to project memory
    │
    ▼
fo_finish() returns confirmation
    │
    ▼
Dashboard shows recap (via polling /api/status)
```

**Dashboard role:** Display and confirm, NOT initiate.

**Required changes:**
1. Add `fo_finish(recap: str)` MCP tool
2. Dashboard polls for episode status
3. Dashboard displays recap when available

**What the dashboard "Finish & Save" button can do:**
- Show modal prompting user: "Tell your AI: סיימתי"
- Cannot directly trigger agent action

---

## Alternative: Fix The Exposure Gap

If we want Dashboard-first Finish & Save, we need to:

1. **Expose `get_pending_commands()`** — rename to `fo_pending()` to match pattern
2. **Expand context header injection** — add `fo_sync`, `fo_errors` to `_CONTEXT_HEADER_TOOLS`
3. **Add polling instruction to CLAUDE.md** — "After every tool, call `fo_pending()` to check for dashboard commands"

**Effort:** 2-3 days, but adds protocol complexity and polling overhead.

---

## Appendix: Evidence

### Deferred Tools List (from system-reminder)

```
mcp__fixonce__fo_apply
mcp__fixonce__fo_brief
mcp__fixonce__fo_decide
mcp__fixonce__fo_errors
mcp__fixonce__fo_init
mcp__fixonce__fo_search
mcp__fixonce__fo_solved
mcp__fixonce__fo_status
mcp__fixonce__fo_sync
```

### Total MCP Tools in Server

```bash
grep -n "@mcp.tool()" mcp_memory_server_v2.py | wc -l
# Result: 51
```

### _CONTEXT_HEADER_TOOLS (line 1984)

```python
_CONTEXT_HEADER_TOOLS = {
    "get_live_record",
    "get_policy_status",
    "get_stability_report",
    "check_and_report",
}
```

### Live Test Command

```bash
curl -s http://localhost:5001/api/memory/ai-queue
# Result: {"commands":[{"id":"b6f25c0d","message":"VERIFICATION_TEST_2026_07_19_UNIQUE_ID_ABC123","status":"pending",...}]}
```

Command exists but agent cannot see it.
