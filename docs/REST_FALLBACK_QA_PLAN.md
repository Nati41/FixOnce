# REST Fallback Manual QA Plan

Production QA procedure for Codex/Claude testing the MCP disconnect fallback.

## Prerequisites

- FixOnce server running locally
- A test project with existing memory
- Access to both MCP tools and shell/curl

## Test Procedure

### 1. Verify Normal MCP Path

```bash
# Start a new AI session (Codex/Claude)
# fo_init should work normally
fo_init(cwd="/path/to/test/project")

# Save a test decision via MCP
fo_decide(text="QA Test Decision via MCP", reason="Testing MCP path")

# Save a test solution via MCP
fo_solved(
    error="QA Test Error via MCP",
    solution="QA Test Solution via MCP",
    files="qa_test.py"
)

# Verify in dashboard: Recent activity shows MCP tool call
```

**Expected:** Decision and solution saved, dashboard shows MCP activity.

### 2. Simulate MCP Disconnect

Option A (Codex): The MCP tools become unavailable after idle timeout
Option B (Manual): Force-close the MCP transport while keeping the server running

```bash
# Verify server is still running
curl -s http://localhost:5000/api/ping
# Should return: {"service": "fixonce", "status": "ok", ...}
```

### 3. Verify REST Fallback Status

```bash
# Get runtime port
FIXONCE_PORT=$(cat ~/.fixonce/runtime.json 2>/dev/null | grep -o '"port":[0-9]*' | grep -o '[0-9]*' || echo 5000)

# Check status via REST
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  -d '{"name": "fixonce_status", "arguments": {}}'
```

**Expected:**
```json
{
  "function": "fixonce_status",
  "result": {
    "success": true,
    "recording": true,
    "transport": "rest_fallback"
  }
}
```

### 4. Save Decision via REST Fallback

```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_decide",
  "arguments": {
    "text": "QA Test Decision via REST Fallback",
    "reason": "Testing REST fallback path"
  }
}
EOF
```

**Expected:**
```json
{
  "function": "fixonce_decide",
  "result": {
    "success": true,
    "action": "fixonce_decide",
    "transport": "rest_fallback"
  }
}
```

### 5. Test Decision Review/Resolution via REST

```bash
# Save a similar decision to trigger review
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_decide",
  "arguments": {
    "text": "QA Test Decision via REST Fallback - Updated",
    "reason": "Testing conflict detection"
  }
}
EOF
```

If review is required, resolve with:
```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_decide",
  "arguments": {
    "text": "QA Test Decision via REST Fallback - Updated",
    "reason": "Testing resolution",
    "action": "resolve:supersede_existing:<target_id>"
  }
}
EOF
```

### 6. Save Solution via REST Fallback

```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_solved",
  "arguments": {
    "error": "QA Test Error via REST Fallback",
    "solution": "QA Test Solution via REST Fallback",
    "files": "qa_test_rest.py"
  }
}
EOF
```

**Expected:**
```json
{
  "function": "fixonce_solved",
  "result": {
    "success": true,
    "message": "Solution saved.",
    "transport": "rest_fallback"
  }
}
```

### 7. Verify Dashboard Shows Fallback Activity

- Open FixOnce dashboard
- Check Recent Activity section
- Should show "REST fallback: decide" and "REST fallback: solved"
- Recording indicator should be GREEN
- MCP indicator may show disconnected

**Expected:** Dashboard shows recording is active via REST fallback, NOT claiming MCP is connected.

### 8. Test Solution Review Flow via REST

```bash
# Save a similar solution to trigger review
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_solved",
  "arguments": {
    "error": "QA Test Error via REST Fallback",
    "solution": "QA Test Better Solution via REST",
    "files": "qa_test_rest.py"
  }
}
EOF
```

**Expected (if review triggered):**
```json
{
  "result": {
    "success": false,
    "requires_review": true,
    "review_id": "solrev_...",
    "target_id": "fix_...",
    "allowed_actions": ["supersede_existing", "cancel"]
  }
}
```

### 9. Test Supersede Resolution via REST

```bash
# Use the review_id and target_id from step 8
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_solved",
  "arguments": {
    "error": "QA Test Error via REST Fallback",
    "solution": "QA Test Better Solution via REST",
    "files": "qa_test_rest.py",
    "resolution_action": "supersede_existing",
    "resolution_target_id": "<target_id from step 8>",
    "resolution_review_id": "<review_id from step 8>"
  }
}
EOF
```

**Expected:**
```json
{
  "result": {
    "success": true,
    "message": "Solution saved."
  }
}
```

### 10. Test Direct Bypass Rejection

```bash
# Try to supersede without review_id (should fail)
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_solved",
  "arguments": {
    "error": "Bypass attempt",
    "solution": "Malicious solution",
    "resolution_action": "supersede_existing",
    "resolution_target_id": "fix_whatever"
  }
}
EOF
```

**Expected:**
```json
{
  "result": {
    "success": false,
    "error_code": "missing_review_id"
  }
}
```

### 11. Verify Knowledge Persisted After MCP Reconnect

```bash
# Start a NEW AI session (reconnects MCP)
fo_init(cwd="/path/to/test/project")

# Search for REST-saved content
fo_search("QA Test Error via REST Fallback")
fo_search("QA Test Decision via REST Fallback")
```

**Expected:** Both the solution and decision saved via REST fallback appear in search results.

### 12. Test Sync via REST

```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_sync",
  "arguments": {
    "goal": "QA Testing REST Fallback",
    "work_area": "QA",
    "last_change": "Verified REST fallback works",
    "next_step": "Complete QA checklist"
  }
}
EOF
```

**Expected:**
```json
{
  "result": {
    "success": true,
    "transport": "rest_fallback"
  }
}
```

### 13. Test Avoid Pattern via REST

```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_decide",
  "arguments": {
    "text": "Never skip REST fallback testing",
    "reason": "QA completeness",
    "action": "avoid"
  }
}
EOF
```

**Expected:**
```json
{
  "result": {
    "success": true,
    "action": "fixonce_decide",
    "transport": "rest_fallback"
  }
}
```

## QA Checklist

| # | Test | Result |
|---|------|--------|
| 1 | MCP path works normally (decide + solved) | ☐ |
| 2 | Server running after MCP disconnect | ☐ |
| 3 | REST status returns recording=true | ☐ |
| 4 | REST decide saves decision | ☐ |
| 5 | REST decide review/resolution works | ☐ |
| 6 | REST solved saves solution | ☐ |
| 7 | Dashboard shows REST fallback activity (not MCP) | ☐ |
| 8 | Solution review triggered | ☐ |
| 9 | Supersede resolution works | ☐ |
| 10 | Direct bypass is rejected | ☐ |
| 11 | REST-saved knowledge visible after MCP reconnect | ☐ |
| 12 | REST sync updates context | ☐ |
| 13 | REST avoid pattern works | ☐ |

## Troubleshooting

**Server not responding:**
```bash
# Check if server is running
pgrep -f "server.py"
launchctl list | grep fixonce
```

**Wrong port:**
```bash
# Check runtime.json
cat ~/.fixonce/runtime.json
```

**Permission denied:**
```bash
# Check firewall/security settings
# macOS may block localhost connections
```
