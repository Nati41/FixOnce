# FixOnce Product Protocol

**Version:** 1.0  
**Status:** Canonical Source of Truth  
**Last Updated:** 2026-07-16

This document defines the complete FixOnce product contract. All client-specific rule files, installer behaviors, and runtime enforcement must derive from this protocol.

No behavior defined here may exist only in one client's implementation.

---

## 1. Vision

FixOnce is a persistent memory layer for AI-assisted software development.

### Core Promises

| Promise | Meaning |
|---------|---------|
| **Memory belongs to the project** | Knowledge is stored with the project, not with the AI session. A new AI inherits what the previous one learned. |
| **AI is replaceable** | Switch between Claude, Codex, Cursor, or any future client. The project memory remains intact. |
| **Continuity is guaranteed** | Every session resumes where the last one stopped. No "where were we?" |
| **Decisions are preserved** | Architectural choices, avoided patterns, and solved bugs persist indefinitely. |
| **Memory is authoritative** | When a decision exists in memory, it is the source of truth — not code comments, not git history. |
| **Failures are valuable** | Avoid patterns prevent the same mistake twice. Failed approaches are as important as successful ones. |
| **Simplicity over comprehensiveness** | A small, reliable tool surface. Eight tools, not forty-five. |

### What FixOnce Is Not

- Not a code editor plugin
- Not a documentation generator
- Not a git replacement
- Not a team communication tool (yet)

FixOnce is the memory that makes AI assistants consistent, reliable, and continuous.

---

## 2. Universal Product Behaviors

These behaviors MUST exist identically across all supported AI clients.

### 2.1 Session Lifecycle

#### 2.1.1 Initialization

**Behavior:** `fo_init` must be called before any meaningful work.

**Product Rule:**
- First tool call in every session
- Receives project context via `cwd` parameter
- Returns continuation state: goal, last work, next step
- Agent must display the opener exactly once, without paraphrasing

**Failure Mode:**
- If `fo_init` is unavailable or fails, agent must warn user before proceeding
- Agent must NOT silently continue without project memory

#### 2.1.2 Project Binding

**Behavior:** Memory is scoped to the project, identified by `cwd`.

**Product Rule:**
- Project identity is determined by working directory
- Project memory is isolated — decisions from Project A are invisible in Project B
- Same project opened from different AI clients sees the same memory

#### 2.1.3 Connection Verification

**Behavior:** Agent must verify recording capability before critical operations.

**Product Rule:**
- Before committing code: call `fo_status` to verify connection
- Before marking task complete: verify memory was recorded
- If not connected: warn user before finishing

#### 2.1.4 Disconnection Handling

**Behavior:** When MCP connection is lost mid-session, agent must notify user.

**Product Rule:**
- If any `fo_*` tool disappears or fails due to transport loss:
  1. Stop and notify user immediately
  2. Explain that recording has stopped
  3. Recommend opening a new session after FixOnce is restored
  4. Continue only with explicit user approval

---

### 2.2 Search Discipline

**Behavior:** Agent must search project memory before investigating independently.

#### 2.2.1 Search Before Debugging

**Trigger:** Any error, exception, or unexpected behavior.

**Product Rule:**
- Call `fo_search` with error keywords BEFORE using Read/Bash to investigate
- If a solution exists, apply it directly
- If no solution exists, investigate and then record the fix

#### 2.2.2 Search Before Architectural Changes

**Trigger:** Changing database, framework, library, or major design pattern.

**Product Rule:**
- Call `fo_search` for related decisions
- If a decision exists, respect it or explicitly supersede it
- Never silently contradict an existing architectural decision

#### 2.2.3 Search Before Replacing Existing Designs

**Trigger:** Proposing to replace JSON with SQLite, REST with GraphQL, etc.

**Product Rule:**
- Call `fo_search` to check if this was previously decided
- If the existing design was a deliberate choice, the agent must acknowledge this before proposing replacement

#### 2.2.4 Search Before Answering "Why"

**Trigger:** User asks "why did we do it this way?" or similar.

**Product Rule:**
- Call `fo_search` first
- If a decision record exists, quote it
- Do not speculate when memory has the answer

#### 2.2.5 Search Before Major Refactors

**Trigger:** Renaming, restructuring, or reorganizing significant code.

**Product Rule:**
- Check for related decisions or avoid patterns
- Respect existing architectural boundaries

---

### 2.3 Decision Authority

**Behavior:** Project memory is the primary authority for decisions.

**Product Rule:**
- If a decision exists in memory, it supersedes code inference
- Agent must not contradict a recorded decision without user approval
- To change a decision, use the supersede flow — do not silently ignore

**Authority Hierarchy:**
1. Explicit user instruction in current session
2. Recorded project decisions
3. Code/configuration state
4. Git history
5. Agent inference

---

### 2.4 Avoid Pattern Behavior

**Behavior:** When `fo_search` returns an AVOID pattern, agent must stop and warn.

**Product Rule:**
- Summarize the risk from the avoid pattern
- Ask user before proceeding
- Do not silently continue past an avoid pattern

**Example:**
```
fo_search("eval") → AVOID: Never use eval() — security risk
Agent: "This approach uses eval(), which is marked as an avoid pattern 
       due to security risks. Do you want to proceed anyway?"
```

---

### 2.5 Solved Bug Behavior

**Behavior:** After fixing any bug, record the solution.

**Product Rule:**
- Call `fo_solved` with error description and solution
- Include affected files
- If a similar solution already exists, the review flow will offer to supersede or extend

---

### 2.6 Progress Sync

**Behavior:** Meaningful work must be synced to project memory.

**Product Rule:**
- Call `fo_sync` after code changes, decisions, or direction changes
- Include: last change, next step, work area
- `next_step` must be specific and actionable (not "continue work")

---

### 2.7 Known Fix Priority

**Behavior:** When a known fix exists, apply it before investigating.

**Product Rule:**
- If `fo_errors` returns "AUTO-FIX READY": call `fo_apply` immediately
- Do not manually investigate when a known fix is available
- Apply first, verify second

---

### 2.8 REST Fallback

**Behavior:** When MCP transport fails, continue recording via REST API.

**Product Rule:**
- If `fo_*` tools are absent from session: use REST fallback
- If MCP transport disconnects: notify user, then use REST if available
- REST endpoints provide identical functionality to MCP tools
- Notify user when operating in fallback mode

**REST Endpoints:**
- `fixonce_status` — verify recording capability
- `fixonce_sync` — sync context
- `fixonce_decide` — record decision
- `fixonce_solved` — record bug fix

---

### 2.9 Review Before Replacement

**Behavior:** Before saving conflicting decisions or solutions, review required.

#### 2.9.1 Decision Review

**Product Rule:**
- Before saving a decision that conflicts with existing decisions, system returns review options
- Agent must present options to user or choose appropriate resolution
- Resolution actions: acknowledge, extend, exception, supersede, save under review, cancel

#### 2.9.2 Solution Review

**Product Rule:**
- Before saving a solution for an error that already has a solution, review required
- Agent must decide: supersede existing or save as alternative
- Review ID must be passed back to prevent double-mutation

---

### 2.10 Project Isolation

**Behavior:** Memory is strictly isolated per project.

**Product Rule:**
- Decisions, solutions, and avoid patterns are project-scoped
- Browser errors are filtered by project
- Activity logs are project-specific
- No cross-project contamination

---

## 3. Client-Specific Behavior

Only implementation details belong here. Product behavior must be identical.

### 3.1 Claude Code

**Hook System:**
- `SessionStart` hook triggers fo_init reminder
- `PostToolUse` hook for activity tracking

**Rules Location:**
- `~/.claude/CLAUDE.md` (user global)
- `.claude/settings.json` (hooks)

**MCP Configuration:**
- `~/.claude.json` (mcpServers)

**Transport:**
- stdio via fastmcp or direct Python

### 3.2 Codex

**Hook System:**
- `hooks.json` for PostToolUse and PreToolUse
- AGENTS.md for session rules

**Rules Location:**
- `~/.codex/AGENTS.md`
- `~/.codex/hooks.json`

**MCP Configuration:**
- `~/.codex/config.toml`

**Transport:**
- stdio with FIXONCE_ACTOR=codex

### 3.3 Cursor

**Rules Location:**
- Cursor settings.json (`cursor.general.aiRules`)
- `~/.cursor/mcp.json`

**No Hook System:**
- Rules only, no lifecycle hooks

**Transport:**
- stdio MCP

### 3.4 Windsurf

**Rules Location:**
- `~/.codeium/windsurf/memories/global_rules.md`
- `~/.codeium/windsurf/mcp_config.json`

**No Hook System:**
- Rules only

**Transport:**
- stdio MCP

---

## 4. Generated Artifacts

The following files should be generated from this protocol.

### 4.1 Client Rule Files

| File | Client | Generation Source |
|------|--------|-------------------|
| `data/generated/claude-rules.md` | Claude Code | Sections 2.1-2.10 + 3.1 |
| `data/generated/codex-rules.md` | Codex | Sections 2.1-2.10 + 3.2 |
| `data/generated/cursor-rules.md` | Cursor | Sections 2.1-2.10 + 3.3 |
| `data/generated/windsurf-rules.md` | Windsurf | Sections 2.1-2.10 + 3.4 |

### 4.2 Installer Injection Files

| File | Purpose |
|------|---------|
| `data/generated/install-inject-claude.md` | Injected into ~/.claude/CLAUDE.md |
| `data/generated/install-inject-codex.md` | Injected into ~/.codex/AGENTS.md |
| `data/generated/install-inject-cursor.txt` | Injected into Cursor settings |
| `data/generated/install-inject-windsurf.md` | Injected into Windsurf memories |

### 4.3 Documentation

| File | Purpose |
|------|---------|
| `docs/generated/user-protocol.md` | User-facing protocol documentation |
| `docs/generated/tool-reference.md` | MCP tool reference |

### 4.4 Generation Architecture

```
fixonce-product-protocol.md (THIS FILE)
         │
         ▼
   [generator script]
         │
         ├──► data/generated/claude-rules.md
         ├──► data/generated/codex-rules.md
         ├──► data/generated/cursor-rules.md
         ├──► data/generated/windsurf-rules.md
         │
         └──► install.py reads from data/generated/
```

**Generator Responsibilities:**
1. Parse this protocol document
2. Extract universal behaviors
3. Merge with client-specific implementation details
4. Output formatted rules for each client
5. Verify no universal behavior is missing from any output

---

## 5. Canonical Source of Truth

### 5.1 Single Source Principle

This document (`data/fixonce-product-protocol.md`) is the ONLY place where product behavior is defined.

**Rules:**
- No product behavior may be defined only in a client-specific file
- No product behavior may be defined only in CLAUDE.md
- No product behavior may be defined only in tests
- All client rule files must be generated, not manually maintained

### 5.2 Change Process

To change product behavior:
1. Update this protocol document
2. Run generator script
3. Verify all client files updated
4. Run parity tests
5. Commit all files together

### 5.3 Prohibited Patterns

| Pattern | Why Prohibited |
|---------|----------------|
| Manual edit to client rule file | Will drift from protocol |
| Behavior in CLAUDE.md not in protocol | Creates client-specific behavior |
| Different wording for same behavior | Creates interpretation drift |
| Copy-paste between client files | Will diverge over time |

---

## 6. Parity Requirements

Every behavior listed must function identically across all clients.

### 6.1 Parity Matrix

| Behavior | Claude | Codex | Cursor | Windsurf |
|----------|--------|-------|--------|----------|
| fo_init before work | Required | Required | Required | Required |
| Connection warning | Required | Required | Required | Required |
| Search before debug | Required | Required | Required | Required |
| Search before architecture | Required | Required | Required | Required |
| Search before refactor | Required | Required | Required | Required |
| Search before "why" | Required | Required | Required | Required |
| Decision authority | Required | Required | Required | Required |
| Stop on AVOID | Required | Required | Required | Required |
| Record solved bugs | Required | Required | Required | Required |
| Sync progress | Required | Required | Required | Required |
| Known fix priority | Required | Required | Required | Required |
| Verify before commit | Required | Required | Required | Required |
| REST fallback | Required | Required | Required | Required |
| Decision review | Required | Required | Required | Required |
| Solution review | Required | Required | Required | Required |
| Project isolation | Required | Required | Required | Required |

### 6.2 Future Clients

Any new AI client must implement all behaviors marked "Required" before being considered supported.

---

## 7. Product Test Matrix

These tests verify PRODUCT behavior, not implementation details.

### 7.1 Session Tests

| Test | Verification |
|------|--------------|
| Fresh install | User receives complete protocol, not partial |
| Fresh project | New folder initializes without error |
| Resume session | Context preserved across sessions |
| Different AI client | Same project shows same memory |

### 7.2 Search Discipline Tests

| Test | Verification |
|------|--------------|
| Error debugging | Agent searches before investigating |
| Architecture change | Agent searches for prior decisions |
| "Why" question | Agent searches before answering |
| Refactor proposal | Agent searches for constraints |

### 7.3 Authority Tests

| Test | Verification |
|------|--------------|
| Existing decision | Agent respects it, does not contradict |
| Avoid pattern | Agent stops and warns before proceeding |
| Known fix | Agent applies without manual investigation |

### 7.4 Recording Tests

| Test | Verification |
|------|--------------|
| Bug fix | Recorded via fo_solved |
| Decision made | Recorded via fo_decide |
| Progress sync | Recorded via fo_sync |
| Commit verification | fo_status called before commit |

### 7.5 Connection Tests

| Test | Verification |
|------|--------------|
| MCP disconnect | User warned before continuing |
| REST fallback | Recording continues when MCP fails |
| Reconnection | New session picks up where left off |

### 7.6 Platform Tests

| Test | Mac | Windows |
|------|-----|---------|
| Server starts | Required | Required |
| Dashboard loads | Required | Required |
| MCP connects | Required | Required |
| Hooks fire | Required | Required |
| Auto-start works | Required | Required |

### 7.7 Client Parity Tests

For each test above, run on:
- Claude Code
- Codex
- Cursor
- Windsurf

All must produce identical product behavior.

---

## 8. Rule Classification

Every rule in the FixOnce system must be classified.

### 8.1 Universal Product Rules

These rules define the product. They must exist in all clients.

| Rule | Classification |
|------|----------------|
| fo_init before work | Universal |
| Search before debugging | Universal |
| Search before architecture changes | Universal |
| Search before refactors | Universal |
| Search before "why" questions | Universal |
| Decision authority (memory > code) | Universal |
| Stop on AVOID patterns | Universal |
| Use search answers as authority | Universal |
| Record solved bugs | Universal |
| Record decisions | Universal |
| Sync meaningful progress | Universal |
| Specific next_step | Universal |
| Verify recording before commit | Universal |
| Warn on disconnect | Universal |
| REST fallback when MCP fails | Universal |
| Known fix before investigation | Universal |
| Decision review before conflict save | Universal |
| Solution review before duplicate save | Universal |
| Project isolation | Universal |

### 8.2 Client Implementation Rules

These rules are implementation-specific but must achieve the same product behavior.

| Rule | Client | Purpose |
|------|--------|---------|
| SessionStart hook reminder | Claude | Trigger fo_init |
| AGENTS.md placement | Codex | Rule injection location |
| settings.json aiRules | Cursor | Rule injection method |
| FIXONCE_ACTOR env var | All | Client identification |
| stdio transport | All | MCP communication |
| fastmcp wrapper | Claude | Transport optimization |
| PowerShell hooks | Windows | Cross-platform hooks |

### 8.3 Internal Development Rules

These rules apply only to FixOnce development, not to the product.

| Rule | Purpose |
|------|---------|
| Dogfooding protocol | Full protocol in source repo |
| Fresh Install QA | Developer testing checklist |
| Test coverage requirements | CI/CD |
| Commit conventions | Development workflow |

---

## Appendix A: Tool Reference

### A.1 MCP Tools

| Tool | Required | Purpose |
|------|----------|---------|
| `fo_init` | Yes | Initialize session, bind to project |
| `fo_status` | Yes | Verify connection before critical ops |
| `fo_sync` | Yes | Sync work context |
| `fo_search` | Yes | Search past solutions, decisions |
| `fo_decide` | Yes | Record decisions, avoid patterns |
| `fo_solved` | Yes | Record bug fixes |
| `fo_errors` | Yes | Check browser errors |
| `fo_apply` | Yes | Apply known fix |
| `fo_brief` | No | Get summary briefing |
| `fo_component` | No | Track component status |
| `fo_vision` | No | Get vision statements |

### A.2 REST Fallback Endpoints

| Endpoint | MCP Equivalent |
|----------|----------------|
| `fixonce_status` | fo_status |
| `fixonce_sync` | fo_sync |
| `fixonce_decide` | fo_decide |
| `fixonce_solved` | fo_solved |

---

## Appendix B: Versioning

This protocol uses semantic versioning.

- **Major:** Breaking change to universal product behavior
- **Minor:** New universal behavior added
- **Patch:** Clarification or client-specific update

Current version: **1.0.0**

---

*This document is the canonical source of truth for FixOnce product behavior.*
