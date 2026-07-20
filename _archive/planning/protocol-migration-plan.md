# FixOnce Protocol Migration Plan

**Related Document:** `data/fixonce-product-protocol.md`  
**Status:** Planning (not yet implemented)  
**Date:** 2026-07-16

---

## 1. Files to Be Generated from Protocol

### 1.1 Current Manual Files (to become generated)

| Current File | Location | Current Lines | Status |
|-------------|----------|---------------|--------|
| `global-agent-rules.md` | `data/` | 84 | Manual, incomplete |
| `global-claude-md.md` | `data/` | 36 | Manual, minimal |
| `global-cursor-rules.md` | `data/` | 20 | Manual, minimal |
| `.cursorrules` | `data/` | 54 | Manual, incomplete |
| `.windsurfrules` | `data/` | 33 | Manual, minimal |

### 1.2 Files with Mixed Content

| File | Location | Issue |
|------|----------|-------|
| `CLAUDE.md` (source repo) | Root | Contains dogfooding rules + product protocol |
| `~/.claude/CLAUDE.md` (user) | User home | Has manual Protocol v7 + injected block |
| `~/.codex/AGENTS.md` | User home | Has legacy tool names + injected block |

### 1.3 Target Generated Files

| Generated File | Derived From | Replaces |
|----------------|--------------|----------|
| `data/generated/claude-rules.md` | Protocol §2 + §3.1 | `global-claude-md.md` |
| `data/generated/codex-rules.md` | Protocol §2 + §3.2 | `global-agent-rules.md` |
| `data/generated/cursor-rules.md` | Protocol §2 + §3.3 | `global-cursor-rules.md` |
| `data/generated/windsurf-rules.md` | Protocol §2 + §3.4 | `.windsurfrules` |

---

## 2. Migration Plan

### Phase 1: Protocol Stabilization (Current)

**Objective:** Finalize the canonical protocol document.

**Tasks:**
1. ✅ Create `data/fixonce-product-protocol.md`
2. ☐ Review protocol with stakeholder
3. ☐ Identify any missing behaviors
4. ☐ Lock protocol version 1.0.0

**Duration:** 1 day

### Phase 2: Generator Implementation

**Objective:** Build script that generates client rules from protocol.

**Tasks:**
1. ☐ Create `scripts/generate_client_rules.py`
2. ☐ Parse protocol document (Markdown → structured data)
3. ☐ Define templates for each client format
4. ☐ Generate all four client rule files
5. ☐ Add generation timestamp and protocol version to output

**Output:**
```
data/generated/
├── claude-rules.md
├── codex-rules.md
├── cursor-rules.md
├── windsurf-rules.md
└── generation-manifest.json
```

**Duration:** 1-2 days

### Phase 3: Installer Update

**Objective:** Update installers to use generated files.

**Tasks:**
1. ☐ Modify `install.py` to read from `data/generated/`
2. ☐ Modify `install.ps1` to read from `data/generated/`
3. ☐ Update `_load_text_asset()` to use generated files
4. ☐ Verify injection markers work with new content

**Duration:** 0.5 days

### Phase 4: Legacy Cleanup

**Objective:** Remove manual rule files, fix conflicts.

**Tasks:**
1. ☐ Delete `data/global-claude-md.md`
2. ☐ Delete `data/global-agent-rules.md`
3. ☐ Delete `data/global-cursor-rules.md`
4. ☐ Delete `data/.cursorrules`
5. ☐ Delete `data/.windsurfrules`
6. ☐ Remove legacy tool names from any remaining files
7. ☐ Update `~/.codex/AGENTS.md` to remove manual top section

**Duration:** 0.5 days

### Phase 5: Parity Testing

**Objective:** Verify all clients receive identical product behavior.

**Tasks:**
1. ☐ Create `tests/test_protocol_parity.py`
2. ☐ Test: All generated files contain all universal behaviors
3. ☐ Test: No generated file contains legacy tool names
4. ☐ Test: Fresh install on macOS receives complete protocol
5. ☐ Test: Fresh install on Windows receives complete protocol
6. ☐ Manual QA: Test each client with protocol-defined behaviors

**Duration:** 1 day

### Phase 6: Documentation

**Objective:** Update user-facing documentation.

**Tasks:**
1. ☐ Generate `docs/generated/user-protocol.md` from protocol
2. ☐ Update README references
3. ☐ Remove references to manual rule files

**Duration:** 0.5 days

---

## 3. Migration Timeline

```
Week 1
├── Day 1: Phase 1 - Protocol stabilization
├── Day 2-3: Phase 2 - Generator implementation
├── Day 4: Phase 3 - Installer update
└── Day 5: Phase 4 - Legacy cleanup

Week 2
├── Day 1-2: Phase 5 - Parity testing
└── Day 3: Phase 6 - Documentation
```

**Total estimated effort:** 5-7 working days

---

## 4. Risks

### 4.1 High Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Existing users have manual ~/.claude/CLAUDE.md customizations** | User customizations overwritten | Preserve content outside FIXONCE-AUTO-INIT markers |
| **Generator produces invalid Markdown** | Client fails to parse rules | Test output with actual clients before release |
| **Legacy tool names in user AGENTS.md** | Codex calls non-existent tools | Provide migration script for existing users |

### 4.2 Medium Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Protocol document becomes stale** | Drift re-emerges | Add CI check that generated files match protocol |
| **New behavior added to client file, not protocol** | Partial coverage | Require protocol update for any behavior change |
| **Cursor/Windsurf have format constraints** | Generated rules don't fit | Test format limits per client |

### 4.3 Low Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Protocol too long** | AI context limits | Keep protocol concise, use structured format |
| **Version mismatch** | Old rules, new server | Include protocol version in generated header |

---

## 5. Open Questions

### 5.1 Protocol Content

| Question | Options | Recommendation |
|----------|---------|----------------|
| Should REST fallback instructions be in client rules? | Yes (full) / No (docs only) / Abbreviated | Abbreviated — full docs in protocol, summary in rules |
| Should decision review flow details be in rules? | Full flow / Just "review required" | Just the trigger — agent follows MCP response |
| How much search discipline detail? | Full 5 categories / Abbreviated | Full — this was the root cause of TidyCLI incident |

### 5.2 Generation Architecture

| Question | Options | Recommendation |
|----------|---------|----------------|
| Generator language? | Python / Node / Bash | Python — matches existing codebase |
| Template format? | Jinja2 / String format / Markdown manipulation | String format — simpler, fewer dependencies |
| Where to store templates? | In generator / Separate files | In generator — single file is easier to maintain |

### 5.3 Migration Process

| Question | Options | Recommendation |
|----------|---------|----------------|
| Existing user upgrade path? | Auto-replace / Prompt / Manual | Auto-replace within markers, preserve custom content |
| How to handle Codex legacy names? | Auto-remove / Warn / Leave | Auto-remove — legacy names cause tool call failures |
| Protocol changelog? | In protocol doc / Separate CHANGELOG | In protocol doc, Appendix B |

### 5.4 Testing

| Question | Options | Recommendation |
|----------|---------|----------------|
| How to test "agent follows rule"? | Manual only / Simulated / Both | Manual for now, simulated later |
| Parity test automation level? | Content check only / Behavior check | Content check — behavior requires running agents |

---

## 6. Success Criteria

Migration is complete when:

1. ☐ `data/fixonce-product-protocol.md` is the only place product behavior is defined
2. ☐ All client rule files are generated, not manual
3. ☐ No legacy tool names exist in any distributed file
4. ☐ Fresh install on macOS receives all universal behaviors
5. ☐ Fresh install on Windows receives all universal behaviors
6. ☐ Parity tests pass for all 4 clients
7. ☐ Manual QA confirms search discipline (5 categories) in all clients
8. ☐ Manual QA confirms AVOID pattern behavior in all clients
9. ☐ Manual QA confirms decision authority in all clients

---

## 7. Rollback Plan

If migration causes issues:

1. Revert to previous manual rule files (Git)
2. Update `install.py` to use old file paths
3. Notify users to re-run installer

Risk of needing rollback: **Low** — migration is additive, not destructive.

---

*This plan documents the migration from manual rule files to protocol-generated files.*
