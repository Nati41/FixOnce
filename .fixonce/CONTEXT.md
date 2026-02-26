# FixOnce Context

> **Auto-generated file.** Do not edit manually.
> Last updated: 2026-02-26 21:12

---

## Project: FixOnce

## Current Goal

**Replace dashboard_vnext.html with health-focused design (Orb-based) while preserving all API integrations**

---

## Decisions (MUST FOLLOW)

> **These are architectural decisions that MUST be respected.**
> Before making changes that contradict these, ask for explicit approval.

### Per-project Semantic Index with provider abstraction layer

*Reason:* Enables semantic search across project memory. Architecture: EmbeddingProvider abstraction (swappable models), EmbeddingConfig (version tracking), SemanticIndex (per-project), FastEmbedProvider (ONNX, no PyTorch). Index auto-rebuilds if model changes.

### MCP activity logging in dashboard

*Reason:* Added

### Display opening message and conversation in user's language, but store all data in English

*Reason:* Storage must be consistent (English) for search and dashboard. But AI should present information to user in whatever language they're speaking for better UX.

### Atomic file writes with FileLock for crash safety and concurrent access

*Reason:* Prevents file corruption on crash (write to temp then os.replace). Prevents race conditions with file locking (fcntl/msvcrt). Core module: src/core/safe

### Stress tests must use dedicated test project, not active project

*Reason:* Running stress tests on active project destroys real data. Tests should create isolated test project with unique ID.

### Codex CLI integration via FastMCP STDIO transport

*Reason:* OpenAI Codex CLI supports MCP. Config in ~/.codex/config.toml using fastmcp run with --transport stdio. All 21 FixOnce tools now available in Codex.

### Dashboard snapshot now exposes a policy object with non-invasive fallback derivation

*Reason:* Policy Pulse UI expected snapshot.policy while API did not provide it; deriving from intent/project

### Activity/timeline now marks non-active actors as historical

*Reason:* Reduces confusion when old claude events appear while codex is the current active session.

### vNext dashboard now includes visible Policy Pulse section wired to snapshot.policy

*Reason:* User was using /next (dashboard

### Dashboard HTML routes now disable cache headers

*Reason:* Ensures UI edits are immediately visible on refresh and prevents stale dashboard pages.

### vNext dashboard includes an in-product Help Layer (global ? modal + contextual tooltips + setup hint)

*Reason:* Reduces onboarding friction, explains data provenance, and prevents confusion around empty/not-set states.

### update_component_status MCP tool for AI-managed component statuses

*Reason:* Allows AI to update component statuses (done/in

### Dashboard translation layer with auto-detected language

*Reason:* Uses navigator.language to detect user's language (he/en). TRANSLATIONS object stores pairs, t() function for lookups. Data stored in English, displayed in user's language.

### Data written in user's conversation language, not English

*Reason:* AI writes goals, insights, component names in the language the user speaks (Hebrew/English). Dashboard UI labels stay in English. This is simpler than translation layers and feels more natural.

### אחסון נתונים בעברית

*Reason:* בדיקה האם המערכת מונעת הפרת מדיניות

### Never store data in English, always use Hebrew

*Reason:* Testing conflict detection with existing English storage decision

### All data stored in English for consistency

*Reason:* Consistent storage format for search and dashboard

### Store all data in Hebrew only

*Reason:* Testing force override

### Auto-backup before every project file write

*Reason:* Prevents data loss. Timestamped backups stored in data/projects_v2/.backups/. Keeps last 5 backups per file. Auto-recovery on read if file is corrupt or missing.

### Merged Status Rail into Tree Summary - single status display with clickable chips

*Reason:* Removed duplicate status display. Now Tree Section has chips that filter the tree on click, with progress bar and last updated info.

### Minimal installer approach - no complex packaging, just scripts

*Reason:* Simpler to maintain, works cross-platform, auto-port detection and health checks built into server and launcher

### Component Stability Layer with Git-based rollback

*Reason:* Enables rollback to last known good state. Stores commit hash per component, tracks files, supports file restore or branch creation.

### Checkpoints created for 13 components

*Reason:* Bulk checkpoint at commit 22caa38d

### Checkpoint created for Dashboard

*Reason:* Saved at commit 22caa38d - can rollback to this state

### Checkpoints created for 1 components

*Reason:* Bulk checkpoint at commit 56e55cd3

---

## Architecture

FixOnce is a persistent memory layer for AI coding assistants (Claude Code, Cursor, Codex). It remembers decisions, solutions, insights, and context across sessions so AI never forgets previous work.

**Stack:** Python 3, Flask, FastMCP (MCP protocol), Chrome Extension (JS), NumPy, scikit-learn (TF-IDF embeddings), SQLite, JSON storage

**Key Flows:**
- auto_init_session() - Initialize AI session with project context
- search_past_solutions() - Semantic search for past fixes before debugging
- log_decision/log_avoid - Persist architectural decisions permanently
- update_live_record - Save goals, insights, failed attempts
- get_browser_errors - Proactive error detection from Chrome extension
- Boundary detection - Auto-switch projects when file operations cross boundaries

---

---

## Key Insights

> Lessons learned from previous work. Search `search_past_solutions()` for more.

- Project structure: src/server.py (Flask main), src/mcp_server/mcp_memory_server_v2.py (MCP tools), src/core/ (business logic), src/api/ (REST endpoints), data/dashboard_v3.html (main UI)
- MCP Server runs on port 5000 (Flask) with tools like auto_init_session, update_live_record, log_decision, search_past_solutions, get_browser_errors
- Semantic search uses EmbeddingProvider abstraction (provider.py) with FastEmbedProvider (ONNX) for local embeddings - no PyTorch dependency
- Chrome extension (extension/) captures browser errors and sends to Flask server for proactive error detection
- Boundary detection (boundary_detector.py) auto-switches projects when AI edits files outside current project root - uses .git, package.json, pyproject.toml as markers
- Project data stored in data/projects_v2/{project_id}.json with embeddings in {project_id}.embeddings/ folder
- Dashboard activity now shows MCP tool calls (update_live_record, log_decision, log_avoid) with smart project detection when cwd is empty
- Testing MCP activity logging after server restart
- Dashboard vNext complete: SVG logo, Deep Dive panel with tabs (Timeline/Decisions/Insights/Avoids/System), MCP icons in What Changed, Glow effect for recent updates, ROI auto-calculated
- Windows EXE packaging: fixonce.spec + windows_bootstrap.py handle AppData paths, build_windows.bat for building. Extension deployed to %APPDATA%/FixOnce/extension/

## Failed Attempts

> These approaches were tried and failed. Don't repeat them.

- When adding DELETE endpoint to errors.py, accidentally broke GET endpoint by inserting new function in the middle of existing code - GET was left without return statement

---

---

*Generated by [FixOnce](https://github.com/fixonce) - AI Memory Layer*