# FixOnce REST Fallback Protocol

When MCP transport disconnects but the local FixOnce server is still running, agents can continue recording project memory through the REST fallback.

## Architecture

```
Normal path (MCP working):
AI → MCP tools → FixOnce server/core → project memory

Fallback path (MCP disconnected):
AI → curl/shell → REST API → same FixOnce server/core → same project memory
```

Both paths use the **same core functions** for business logic, validation, and storage.

## When to Use REST Fallback

### Safe Immediate Fallback

Use REST fallback when:
1. MCP tool is **absent from the session** (tool list doesn't include `fo_*`)
2. MCP transport is **already known disconnected** before invocation

### Ambiguous Result (DO NOT AUTO-RETRY)

When an MCP operation:
- Times out
- Transport drops after request may have reached FixOnce

**Do NOT blindly resubmit via REST.** The operation may have already been recorded.

For V1 protocol:
- **Sync**: Safe to retry (idempotent timestamp update)
- **Decide/Solved**: Use fingerprint deduplication (same error+solution text = update not duplicate)
- **Resolution actions**: NOT safe to retry without checking (may double-mutate)

If the ambiguous operation was a resolution action, verify the target state before retrying.

## Available REST Actions

### `fixonce_status`

Check recording capability for a specific project.

**IMPORTANT**: Include `cwd` to verify recording for YOUR project.

```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  -d '{"name": "fixonce_status", "arguments": {"cwd": "/path/to/your/project"}}'
```

Response:
```json
{
  "function": "fixonce_status",
  "result": {
    "success": true,
    "action": "fixonce_status",
    "recording": true,
    "transport": "rest_fallback",
    "project_id": "project_abc123",
    "resolved_cwd": "/path/to/your/project",
    "message": "FixOnce can record to project project_abc123 via REST fallback."
  }
}
```

### `fixonce_sync`

Sync work context (equivalent to `fo_sync`).

**REQUIRED**: `cwd` - absolute path to your project directory.

```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_sync",
  "arguments": {
    "cwd": "/path/to/your/project",
    "goal": "Fix login validation",
    "work_area": "authentication",
    "last_change": "Added email format check",
    "last_file": "src/auth/validator.py",
    "why": "Prevent invalid emails from reaching the database",
    "next_step": "Test with edge cases"
  }
}
EOF
```

Response:
```json
{
  "function": "fixonce_sync",
  "result": {
    "success": true,
    "action": "fixonce_sync",
    "message": "Context synced via REST fallback.",
    "transport": "rest_fallback",
    "project_id": "project_abc123",
    "resolved_cwd": "/path/to/your/project"
  }
}
```

### `fixonce_decide`

Record a decision or avoid pattern (equivalent to `fo_decide`). Supports full review/resolution.

**REQUIRED**: `cwd` - absolute path to your project directory.

**Basic decision:**
```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_decide",
  "arguments": {
    "cwd": "/path/to/your/project",
    "text": "Use PostgreSQL for the database",
    "reason": "Better for our scale and ACID compliance"
  }
}
EOF
```

**Avoid pattern:**
```bash
{
  "name": "fixonce_decide",
  "arguments": {
    "text": "Never use eval()",
    "reason": "Security vulnerability",
    "action": "avoid"
  }
}
```

**Resolution actions:**
```bash
{
  "name": "fixonce_decide",
  "arguments": {
    "text": "Use MySQL instead",
    "reason": "Migrated database",
    "action": "resolve:supersede_existing:dec_postgres_123"
  }
}
```

Available resolution actions:
- `resolve:acknowledge_existing:TARGET_ID` - Acknowledge duplicate without saving
- `resolve:save_as_extends:TARGET_ID` - Save as compatible extension
- `resolve:save_as_exception:TARGET_ID` - Save as scoped exception
- `resolve:supersede_existing:TARGET_ID` - Save and mark existing as superseded
- `resolve:save_anyway_under_review:TARGET_ID` - Save but flag for review
- `resolve:cancel` - Don't save

**Review required response:**
```json
{
  "result": {
    "success": false,
    "requires_review": true,
    "relationship": "potential_conflict",
    "target_id": "dec_existing_123",
    "target_text": "Use PostgreSQL...",
    "allowed_actions": ["supersede_existing", "save_as_exception", "cancel"],
    "error_code": "review_required"
  }
}
```

### `fixonce_solved`

Record a bug fix (equivalent to `fo_solved`). Supports review and resolution.

**REQUIRED**: `cwd` - absolute path to your project directory.

**Basic save:**
```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_solved",
  "arguments": {
    "cwd": "/path/to/your/project",
    "error": "TypeError: Cannot read property 'map' of undefined",
    "solution": "Added null check before mapping the array",
    "files": "src/components/List.tsx"
  }
}
EOF
```

**Resolution (supersede existing):**
```bash
{
  "name": "fixonce_solved",
  "arguments": {
    "error": "TypeError: Cannot read property 'map' of undefined",
    "solution": "Use optional chaining: items?.map()",
    "files": "src/components/List.tsx",
    "resolution_action": "supersede_existing",
    "resolution_target_id": "fix_existing_123",
    "resolution_review_id": "solrev_abc123def456"
  }
}
```

## Port Discovery

```bash
FIXONCE_PORT=$(cat ~/.fixonce/runtime.json 2>/dev/null | grep -o '"port":[0-9]*' | grep -o '[0-9]*' || echo 5000)
```

## Safe Curl Pattern

For multiline text, quotes, and special characters:

```bash
curl -sS http://127.0.0.1:$FIXONCE_PORT/openai/call \
  -H 'Content-Type: application/json' \
  --data-binary @- << 'EOF'
{
  "name": "fixonce_solved",
  "arguments": {
    "error": "Error with \"quotes\" and\nmultiple lines",
    "solution": "Escaped properly",
    "files": "src/utils.ts"
  }
}
EOF
```

## Error Response Contract

All error responses include:
- `success: false`
- `action`: the attempted action name
- `error`: human-readable error message
- `error_code`: machine-parseable code

Error codes:
- `missing_text`, `missing_reason` - required fields
- `missing_error`, `missing_solution` - required fields
- `no_active_project` - call init_session first
- `invalid_resolution_action` - unknown action
- `missing_target_id` - resolution requires target
- `missing_review_id` - solution resolution requires review ID
- `review_required` - must resolve before saving
- `decision_blocked` - policy conflict
- `exception` - unexpected error

## Dashboard Behavior

When REST fallback succeeds:
- Activity logged with `type: "rest_fallback"`
- `actor: "rest_fallback"`, `actor_source: "rest_api"`
- Dashboard shows recording is active
- MCP state shows disconnected (accurate)
- Recording state shows green (REST working)

The dashboard does **NOT** falsely claim MCP is connected.

## Idempotency

| Operation | Retry Behavior |
|-----------|----------------|
| sync | Safe (timestamp update) |
| decide (new) | Fingerprint dedup or review |
| decide (resolution) | Check target state first |
| solved (new) | Fingerprint dedup (same error+solution = update) |
| solved (resolution) | Consumed review prevents double-mutation |

### V1 Limitation

There is no shared operation ID across MCP and REST. Cross-transport retry relies on:
- Fingerprint-based duplicate detection for new records
- Review consumption tracking for resolution actions

If an MCP call timed out ambiguously and you cannot verify whether it succeeded:
1. For **sync**: Safe to retry via REST
2. For **decide/solved (new)**: Safe to retry (fingerprint dedup)
3. For **resolution actions**: Verify target state before retrying

## Agent Protocol Rules

```
1. Prefer MCP whenever fo_* tools are available
2. Use REST fallback ONLY when:
   - MCP tool is ABSENT from session (not in tool list)
   - MCP transport is ALREADY KNOWN disconnected
3. Do NOT use REST fallback for MCP business errors:
   - review_required
   - validation failure
   - conflict
4. For AMBIGUOUS MCP timeout:
   - Do NOT auto-retry resolution actions
   - Verify target state OR use safe-to-retry operations only
5. If REST fallback succeeds:
   - Continue working
   - Notify: "FixOnce MCP disconnected. Recording via local fallback."
6. If REST also fails:
   - Stop before meaningful work
   - Tell user project memory is not recording
   - Continue only with explicit approval
```

## Files Changed

- `src/api/openai_adapter.py` - Added status, sync, decide, solved handlers
- `tests/test_rest_fallback.py` - 33 tests for REST/MCP parity
- `docs/REST_FALLBACK_PROTOCOL.md` - This documentation
- `docs/REST_FALLBACK_QA_PLAN.md` - Manual QA checklist
