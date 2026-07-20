# FixOnce Core Protocol

**Version:** Draft 1.0  
**Date:** 2026-07-16  
**Status:** Mapping Complete — No Implementation Yet

This document maps all "system questions" in FixOnce, identifies sources of truth, duplications, and violations. It serves as the foundation for gradual migration to a unified Core Protocol.

---

## Table of Contents

1. [System Questions Map](#1-system-questions-map)
2. [Protocol Definitions](#2-protocol-definitions)
3. [Audit Findings](#3-audit-findings)
4. [Migration Roadmap](#4-migration-roadmap)
5. [Summary](#5-summary)

---

## 1. System Questions Map

### 1.1 Active Project

| Aspect | Current State |
|--------|---------------|
| **Question** | Which project is currently active for display and context? |
| **Who answers** | `core/active_project_resolver.py` → `resolve_active_project()` |
| **Who reads** | Dashboard, Tray, MCP (for display only), API endpoints |
| **Who writes** | MCP (`ensure_dashboard_project`), Resolver (`update_active_project`), System Status (fallback) |
| **Multiple sources?** | **YES** — 4 priority levels: live_session > boundary_transition > cached > ai_connections |
| **Duplicate logic?** | **YES** — `managers/multi_project_manager.py` has parallel `get_active_project()`, `set_active_project()` |
| **Single source of truth** | `~/.fixonce/active_project.json` (file) via `active_project_resolver.py` (code) |

**Files involved:**
- `core/active_project_resolver.py` — Canonical resolver
- `managers/multi_project_manager.py:436-490` — Parallel implementation
- `core/system_status.py:899-930` — Direct fallback writer
- `api/status.py` — Multiple read points

---

### 1.2 Connection Status (Is AI Connected?)

| Aspect | Current State |
|--------|---------------|
| **Question** | Is there an active AI connection to FixOnce? |
| **Who answers** | `core/mcp_session_health.py` → `get_session_health()` |
| **Who reads** | Dashboard, Tray, Status API, MCP tools |
| **Who writes** | MCP server on each tool call |
| **Multiple sources?** | **YES** — `mcp_session_health.json`, `ai_connections.json`, process detection |
| **Duplicate logic?** | **YES** — `ai_detector.py` and `mcp_health.py` both compute connection status |
| **Single source of truth** | Should be `mcp_session_health.json` alone |

**Files involved:**
- `core/mcp_session_health.py` — Primary source
- `core/ai_detector.py:207-298` — Alternative computation from `ai_connections.json`
- `core/mcp_health.py` — Yet another health computation
- `core/unified_health.py` — Aggregates multiple sources
- `api/status.py:153-154` — Inline computation

---

### 1.3 Recording Status (Is FixOnce Recording?)

| Aspect | Current State |
|--------|---------------|
| **Question** | Is FixOnce actively recording project memory? |
| **Who answers** | Derived from connection status + project binding |
| **Who reads** | Dashboard orb, Tray status, MCP `fo_status` |
| **Who writes** | No single writer — computed from multiple signals |
| **Multiple sources?** | **YES** — Connection status + session registry + project context |
| **Duplicate logic?** | **YES** — Dashboard, Tray, and MCP each compute this differently |
| **Single source of truth** | Should be `core/recording_status.py` (does not exist) |

**Files involved:**
- `api/status.py:661-736` — Dashboard computation
- `api/status.py:1661-1760` — Tray computation
- `mcp_server/mcp_memory_server_v2.py` — MCP computation

---

### 1.4 Project Catalog

| Aspect | Current State |
|--------|---------------|
| **Question** | What projects exist and what are their metadata? |
| **Who answers** | `managers/multi_project_manager.py` |
| **Who reads** | Dashboard project list, MCP, Search |
| **Who writes** | MCP (`fo_init`), Installer, Manual creation |
| **Multiple sources?** | **NO** — `~/.fixonce/projects_v2/` is the only storage |
| **Duplicate logic?** | **PARTIAL** — `project_index.json` duplicates some metadata |
| **Single source of truth** | `~/.fixonce/projects_v2/{project_id}.json` |

**Files involved:**
- `managers/multi_project_manager.py` — Full implementation
- `core/project_context.py` — ID generation, minimal overlap

---

### 1.5 Knowledge Counts (Decisions, Solutions, Avoids)

| Aspect | Current State |
|--------|---------------|
| **Question** | How many decisions/solutions/avoids exist for a project? |
| **Who answers** | `core/knowledge_counters.py` → `get_live_project_counters()` |
| **Who reads** | Dashboard, Tray, MCP (`fo_init` opener) |
| **Who writes** | N/A — computed from project memory |
| **Multiple sources?** | **YES** — Counted from memory, committed_knowledge, identity |
| **Duplicate logic?** | **YES** — MCP counts separately in `mcp_memory_server_v2.py:8800-8873` |
| **Single source of truth** | Should be `knowledge_counters.py` only |

**Files involved:**
- `core/knowledge_counters.py:6` — Canonical counter
- `mcp_server/mcp_memory_server_v2.py:8800-8873` — Duplicate counting
- `api/status.py:973-976` — Uses canonical
- Dashboard JavaScript — Yet another count extraction

---

### 1.6 Decision Review (Conflict Detection)

| Aspect | Current State |
|--------|---------------|
| **Question** | Does a new decision conflict with existing ones? |
| **Who answers** | `core/decision_review.py` |
| **Who reads** | MCP `fo_decide`, REST fallback |
| **Who writes** | N/A — review is read-only check |
| **Multiple sources?** | **NO** — Single implementation |
| **Duplicate logic?** | **NO** |
| **Single source of truth** | `core/decision_review.py` |

**Status:** ✅ Clean architecture

---

### 1.7 Solution Review (Duplicate Detection)

| Aspect | Current State |
|--------|---------------|
| **Question** | Does a new solution duplicate an existing one? |
| **Who answers** | `core/solutions.py` |
| **Who reads** | MCP `fo_solved`, REST fallback |
| **Who writes** | N/A — review is read-only check |
| **Multiple sources?** | **NO** — Single implementation |
| **Duplicate logic?** | **NO** |
| **Single source of truth** | `core/solutions.py` |

**Status:** ✅ Clean architecture

---

### 1.8 Server Status (Is Server Running?)

| Aspect | Current State |
|--------|---------------|
| **Question** | Is the FixOnce server running and healthy? |
| **Who answers** | `core/system_status.py` → `get_system_status()` |
| **Who reads** | Dashboard, Tray, Installer, MCP |
| **Who writes** | Server writes `runtime.json` on start |
| **Multiple sources?** | **YES** — `runtime.json`, port probe, process check |
| **Duplicate logic?** | **YES** — Tray has its own port discovery in `menubar_app.py` |
| **Single source of truth** | Should be `~/.fixonce/runtime.json` |

**Files involved:**
- `core/system_status.py` — Main implementation
- `scripts/menubar_app.py:202-230` — Duplicate port discovery
- `scripts/app_launcher.py` — Another port discovery

---

### 1.9 Runtime State (Port, PID, Install Path)

| Aspect | Current State |
|--------|---------------|
| **Question** | What port is the server on? What's the PID? |
| **Who answers** | `~/.fixonce/runtime.json` |
| **Who reads** | Tray, MCP, CLI tools |
| **Who writes** | Server on startup |
| **Multiple sources?** | **PARTIAL** — `data/current_port.txt` is legacy fallback |
| **Duplicate logic?** | **YES** — Port discovery scans range if file missing |
| **Single source of truth** | `~/.fixonce/runtime.json` |

**Files involved:**
- `src/server.py` — Writes runtime.json
- `config.py` — Reads it
- `menubar_app.py:206-230` — Fallback scanning

---

### 1.10 Project Context (Identity, Goal, Stack)

| Aspect | Current State |
|--------|---------------|
| **Question** | What is this project's identity, current goal, tech stack? |
| **Who answers** | `core/project_context.py` + project memory `project_info` |
| **Who reads** | Dashboard, MCP opener, Search |
| **Who writes** | MCP (`fo_sync`), Installer |
| **Multiple sources?** | **YES** — `project_info` in memory vs `identity` in snapshot |
| **Duplicate logic?** | **YES** — Dashboard extracts from multiple places |
| **Single source of truth** | Project memory `project_info` section |

**Files involved:**
- `core/project_context.py` — ID and path utilities
- `managers/multi_project_manager.py` — Memory storage
- `api/status.py` — `identity` extraction logic

---

### 1.11 Memory Storage (Project Memory)

| Aspect | Current State |
|--------|---------------|
| **Question** | Where is project memory stored and how is it accessed? |
| **Who answers** | `managers/multi_project_manager.py` |
| **Who reads** | MCP, Dashboard, Search, All knowledge operations |
| **Who writes** | MCP tools, Core decisions/solutions modules |
| **Multiple sources?** | **NO** — `~/.fixonce/projects_v2/{id}.json` is canonical |
| **Duplicate logic?** | **PARTIAL** — Core modules import and call manager directly |
| **Single source of truth** | `managers/multi_project_manager.py` |

**Status:** ✅ Mostly clean, but direct imports throughout codebase

---

### 1.12 Knowledge Search

| Aspect | Current State |
|--------|---------------|
| **Question** | How to search across decisions, solutions, insights? |
| **Who answers** | `core/search.py` + `core/librarian.py` |
| **Who reads** | MCP `fo_search` |
| **Who writes** | N/A — read-only |
| **Multiple sources?** | **YES** — `search.py`, `librarian.py`, `semantic_engine.py` |
| **Duplicate logic?** | **YES** — Multiple search implementations |
| **Single source of truth** | Should be unified search via `librarian.py` |

**Files involved:**
- `core/search.py` — Basic search
- `core/librarian.py` — Advanced search with ranking
- `core/semantic_engine.py` — Semantic search
- `core/semantic_index.py` — Index management

---

### 1.13 Health Status (Overall System Health)

| Aspect | Current State |
|--------|---------------|
| **Question** | What is the overall health of the FixOnce system? |
| **Who answers** | `core/unified_health.py`, `core/mcp_health.py`, `core/system_status.py` |
| **Who reads** | Dashboard, Installer, MCP |
| **Who writes** | N/A — computed |
| **Multiple sources?** | **YES** — Three separate health modules |
| **Duplicate logic?** | **YES** — Each module computes health differently |
| **Single source of truth** | Should be `core/unified_health.py` only |

**Files involved:**
- `core/unified_health.py` — Aggregator (intended single source)
- `core/mcp_health.py` — MCP-specific health
- `core/system_status.py` — System-level health
- `api/status.py` — Dashboard health computation

---

## 2. Protocol Definitions

### 2.1 Active Project Protocol

| Attribute | Value |
|-----------|-------|
| **Owner** | `core/active_project_resolver.py` |
| **Public API** | `resolve_active_project()`, `update_active_project()`, `get_active_project_for_dashboard()` |
| **Consumers** | Dashboard, Tray, MCP (display), API endpoints |
| **Allowed Writers** | MCP server, Resolver internal, Boundary detector |
| **Forbidden** | Direct file writes to `active_project.json` outside resolver |
| **Fallback Policy** | Priority cascade: live_session > boundary > cached > ai_connections |
| **Current Implementation** | Split between resolver and multi_project_manager |
| **Target Implementation** | All access through resolver; remove manager duplicates |

---

### 2.2 Connection Status Protocol

| Attribute | Value |
|-----------|-------|
| **Owner** | `core/mcp_session_health.py` |
| **Public API** | `get_session_health()`, `update_session()`, `is_connected()` |
| **Consumers** | Dashboard, Tray, Status API, MCP tools |
| **Allowed Writers** | MCP server on tool calls |
| **Forbidden** | Reading `ai_connections.json` for connection status |
| **Fallback Policy** | Stale after 30 minutes → disconnected |
| **Current Implementation** | Multiple sources: mcp_session_health, ai_connections, ai_detector |
| **Target Implementation** | Single source: `mcp_session_health.py` |

---

### 2.3 Recording Status Protocol

| Attribute | Value |
|-----------|-------|
| **Owner** | `core/recording_status.py` (TO BE CREATED) |
| **Public API** | `is_recording()`, `get_recording_state()` |
| **Consumers** | Dashboard orb, Tray, MCP `fo_status` |
| **Allowed Writers** | None — derived from connection + project |
| **Forbidden** | Computing recording status inline in UI code |
| **Fallback Policy** | No connection → not recording |
| **Current Implementation** | Computed separately in Dashboard, Tray, MCP |
| **Target Implementation** | Single `is_recording()` function |

---

### 2.4 Project Catalog Protocol

| Attribute | Value |
|-----------|-------|
| **Owner** | `managers/multi_project_manager.py` |
| **Public API** | `list_all_projects()`, `load_project_memory()`, `save_project_memory()` |
| **Consumers** | Dashboard, MCP, Search |
| **Allowed Writers** | MCP `fo_init`, Manager functions |
| **Forbidden** | Direct file access to `projects_v2/` |
| **Fallback Policy** | Create on first access |
| **Current Implementation** | Clean, but `project_index.json` is redundant |
| **Target Implementation** | Remove index file; derive from project files |

---

### 2.5 Knowledge Counts Protocol

| Attribute | Value |
|-----------|-------|
| **Owner** | `core/knowledge_counters.py` |
| **Public API** | `get_live_project_counters(memory)` |
| **Consumers** | Dashboard, Tray, MCP opener |
| **Allowed Writers** | None — computed from memory |
| **Forbidden** | Inline count calculations in MCP or Dashboard |
| **Fallback Policy** | Zero counts if memory missing |
| **Current Implementation** | Canonical exists but MCP has duplicate |
| **Target Implementation** | All callers use `knowledge_counters.py` |

---

### 2.6 Server Status Protocol

| Attribute | Value |
|-----------|-------|
| **Owner** | `core/system_status.py` |
| **Public API** | `get_system_status()`, `is_server_running()` |
| **Consumers** | Dashboard, Tray, Installer, MCP |
| **Allowed Writers** | Server on startup (runtime.json) |
| **Forbidden** | Port scanning when runtime.json exists |
| **Fallback Policy** | Scan port range only if file missing/stale |
| **Current Implementation** | Multiple port discovery implementations |
| **Target Implementation** | Single port resolution via runtime.json |

---

### 2.7 Health Status Protocol

| Attribute | Value |
|-----------|-------|
| **Owner** | `core/unified_health.py` |
| **Public API** | `get_unified_health()` |
| **Consumers** | Dashboard, Installer, MCP |
| **Allowed Writers** | None — aggregates other sources |
| **Forbidden** | Computing health outside unified_health |
| **Fallback Policy** | Degraded health if components unavailable |
| **Current Implementation** | Three separate health modules |
| **Target Implementation** | `unified_health.py` as single aggregator |

---

## 3. Audit Findings

### 3.1 Duplicate Computations

| Location | Duplication | Impact |
|----------|-------------|--------|
| `managers/multi_project_manager.py:436-490` | Parallel active project functions | Confusion about canonical source |
| `mcp_server/mcp_memory_server_v2.py:8800-8873` | Knowledge count computation | Inconsistent counts possible |
| `scripts/menubar_app.py:202-230` | Port discovery | Unnecessary complexity |
| `api/status.py:153-154` | Connection status inline | Logic scattered |
| `core/ai_detector.py:207-298` | Connection from ai_connections | Second source of truth |

### 3.2 Direct JSON File Access (Outside Core)

| File | Direct Access | Should Use |
|------|---------------|------------|
| `api/status.py:123` | `ai_connections.json` read | `mcp_session_health.py` |
| `api/status.py:295` | `extension_ping.json` write | Dedicated module |
| `core/system_status.py:732` | `session_registry.json` read | `session_registry.py` |
| `menubar_app.py:206-209` | `runtime.json` read | `system_status.py` |

### 3.3 Business Logic in Wrong Layer

| Location | Logic | Should Be In |
|----------|-------|--------------|
| `api/status.py:661-736` | Dashboard snapshot assembly | `core/dashboard_state.py` |
| `api/status.py:1661-1760` | Tray status computation | `core/tray_state.py` |
| Dashboard JavaScript | Count extraction, status display | Server returns final values |
| `mcp_server/mcp_memory_server_v2.py` | Knowledge counting | `core/knowledge_counters.py` |

### 3.4 Duplicate Resolvers

| Domain | Resolvers | Recommendation |
|--------|-----------|----------------|
| Active Project | `active_project_resolver.py`, `multi_project_manager.py` | Keep resolver only |
| Connection Status | `mcp_session_health.py`, `ai_detector.py`, `mcp_health.py` | Keep mcp_session_health only |
| Health Status | `unified_health.py`, `mcp_health.py`, `system_status.py` | Route all through unified_health |

### 3.5 Legacy Code to Remove

| File/Code | Status | Action |
|-----------|--------|--------|
| `data/current_port.txt` usage | Legacy | Remove after runtime.json adoption |
| `project_index.json` | Redundant | Derive from project files |
| `ai_connections.json` for connection | Superseded | Use mcp_session_health |
| `managers/multi_project_manager.py` active project functions | Duplicate | Route through resolver |

---

## 4. Migration Roadmap

### Phase 1: Knowledge Counters (Low Risk)

**Priority:** High — Simple, high visibility  
**Timing:** Safe before beta

| Task | Files Affected | Tests Needed | Risk |
|------|----------------|--------------|------|
| Remove MCP inline counting | `mcp_memory_server_v2.py` | Existing counter tests | Low |
| Ensure all callers use `knowledge_counters.py` | `api/status.py` | Count consistency test | Low |
| Verify Dashboard shows same counts as MCP | Dashboard JS | Manual QA | Low |

---

### Phase 2: Connection Status (Medium Risk)

**Priority:** High — Core to recording status  
**Timing:** Safe before beta

| Task | Files Affected | Tests Needed | Risk |
|------|----------------|--------------|------|
| Remove `ai_detector.py` connection logic | `core/ai_detector.py` | Connection state tests | Medium |
| Remove `mcp_health.py` connection logic | `core/mcp_health.py` | Health tests | Medium |
| Route all connection checks through `mcp_session_health.py` | `api/status.py`, `core/*.py` | Integration tests | Medium |
| Create `is_connected()` public API | `core/mcp_session_health.py` | Unit tests | Low |

---

### Phase 3: Active Project Consolidation (Medium Risk)

**Priority:** Medium — Already partially done  
**Timing:** Safe before beta

| Task | Files Affected | Tests Needed | Risk |
|------|----------------|--------------|------|
| Remove `get_active_project()` from manager | `managers/multi_project_manager.py` | Existing resolver tests | Medium |
| Remove `set_active_project()` from manager | `managers/multi_project_manager.py` | Existing resolver tests | Medium |
| Update all callers to use resolver | ~10 files | Integration tests | Medium |
| Remove ImportError fallbacks | `system_status.py`, `multi_project_manager.py` | Edge case tests | Low |

---

### Phase 4: Server Status / Port Resolution (Low Risk)

**Priority:** Low — Works, just duplicated  
**Timing:** Safe before beta

| Task | Files Affected | Tests Needed | Risk |
|------|----------------|--------------|------|
| Create `get_server_port()` in system_status | `core/system_status.py` | Port resolution tests | Low |
| Remove Tray port scanning | `scripts/menubar_app.py` | Tray connectivity test | Low |
| Remove launcher port scanning | `scripts/app_launcher.py` | Launcher tests | Low |
| Deprecate `current_port.txt` | Config, server | None | Low |

---

### Phase 5: Health Status Unification (Low Risk)

**Priority:** Low — Works, just complex  
**Timing:** Can defer to post-beta

| Task | Files Affected | Tests Needed | Risk |
|------|----------------|--------------|------|
| Route all health through `unified_health.py` | `api/status.py`, `api/setup.py` | Health status tests | Low |
| Remove direct `mcp_health.py` calls | Various | Integration tests | Low |
| Remove inline health computation | `api/status.py` | Dashboard tests | Low |

---

### Phase 6: Recording Status (New Module)

**Priority:** Medium — New abstraction  
**Timing:** Post-beta recommended

| Task | Files Affected | Tests Needed | Risk |
|------|----------------|--------------|------|
| Create `core/recording_status.py` | New file | Unit tests | Low |
| Define `is_recording()` and `get_recording_state()` | New file | Unit tests | Low |
| Update Dashboard to use new module | `api/status.py` | Dashboard tests | Medium |
| Update Tray to use new module | `api/status.py` | Tray tests | Medium |
| Update MCP to use new module | `mcp_memory_server_v2.py` | MCP tests | Medium |

---

### Phase 7: Business Logic Migration (Medium-High Risk)

**Priority:** Low — Major refactor  
**Timing:** Post-beta

| Task | Files Affected | Tests Needed | Risk |
|------|----------------|--------------|------|
| Create `core/dashboard_state.py` | New file | Unit tests | Medium |
| Move dashboard assembly from API | `api/status.py` → `core/` | Integration tests | High |
| Create `core/tray_state.py` | New file | Unit tests | Medium |
| Move tray assembly from API | `api/status.py` → `core/` | Integration tests | High |

---

## 5. Summary

### 5.1 All Sources of Truth

| Domain | Current Source | Canonical? |
|--------|----------------|------------|
| Active Project | `~/.fixonce/active_project.json` via resolver | ✅ Yes |
| Project Catalog | `~/.fixonce/projects_v2/*.json` via manager | ✅ Yes |
| Connection Status | `~/.fixonce/mcp_session_health.json` | ⚠️ Partial (competitors exist) |
| Recording Status | None (computed inline) | ❌ No canonical |
| Knowledge Counts | Computed from memory | ⚠️ Partial (duplicates exist) |
| Server Runtime | `~/.fixonce/runtime.json` | ⚠️ Partial (fallbacks exist) |
| Health Status | `core/unified_health.py` | ⚠️ Partial (bypassed often) |

### 5.2 All Duplications

1. **Active Project:** Resolver vs Manager (2 implementations)
2. **Connection Status:** mcp_session_health vs ai_detector vs mcp_health (3 implementations)
3. **Knowledge Counts:** knowledge_counters.py vs MCP inline (2 implementations)
4. **Port Discovery:** system_status vs menubar_app vs app_launcher (3 implementations)
5. **Health Status:** unified_health vs mcp_health vs system_status (3 implementations)

### 5.3 All Violations of "Single Source of Truth"

| Violation | Location | Fix |
|-----------|----------|-----|
| Manager has parallel active project functions | `multi_project_manager.py:436-490` | Remove, use resolver |
| MCP computes knowledge counts inline | `mcp_memory_server_v2.py:8800-8873` | Use knowledge_counters.py |
| ai_detector reads ai_connections for connection | `ai_detector.py:207-298` | Use mcp_session_health |
| Tray scans ports instead of using runtime.json | `menubar_app.py:202-230` | Use system_status |
| Dashboard computes recording status inline | `api/status.py` | Create recording_status.py |
| API reads ai_connections directly | `api/status.py:123` | Use mcp_session_health |

### 5.4 Safe Migration Order

**Recommended order (safest to riskiest):**

1. **Knowledge Counters** — Remove MCP duplicate, low risk, high visibility
2. **Port Resolution** — Consolidate to runtime.json, low risk
3. **Connection Status** — Route through mcp_session_health, medium risk
4. **Active Project** — Remove manager duplicates, medium risk (mostly done)
5. **Health Status** — Route through unified_health, low risk
6. **Recording Status** — Create new module, medium risk
7. **Business Logic** — Move to Core, high risk (post-beta)

---

## Appendix A: File Index

### Core Modules (59 files)

Canonical implementations should live here.

| Module | Purpose | Status |
|--------|---------|--------|
| `active_project_resolver.py` | Active project resolution | Canonical |
| `mcp_session_health.py` | Connection state | Canonical (with competitors) |
| `knowledge_counters.py` | Knowledge counts | Canonical (with duplicates) |
| `unified_health.py` | Health aggregation | Canonical (bypassed) |
| `system_status.py` | Server status | Mixed (some direct writes) |
| `decisions.py` | Decision storage | Uses manager correctly |
| `solutions.py` | Solution storage | Uses manager correctly |
| `search.py` / `librarian.py` | Knowledge search | Multiple implementations |

### Managers (2 files)

Storage abstraction layer.

| Module | Purpose | Status |
|--------|---------|--------|
| `multi_project_manager.py` | Project memory CRUD | Canonical for storage, has duplicates for active |
| `project_memory_manager.py` | Legacy? | Needs review |

### API (12 files)

HTTP endpoints — should NOT contain business logic.

| Module | Purpose | Status |
|--------|---------|--------|
| `status.py` | Dashboard/system status | Too much business logic |
| `setup.py` | Installer/onboarding | Uses system_status correctly |
| Others | Various endpoints | Mostly clean |

### MCP Server (1 file)

AI tool interface.

| Module | Purpose | Status |
|--------|---------|--------|
| `mcp_memory_server_v2.py` | All fo_* tools | Has duplicate counting, otherwise OK |

---

*This document is read-only until migration begins. No code changes until roadmap is approved.*
