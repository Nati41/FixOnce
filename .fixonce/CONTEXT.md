# FixOnce Context

> **Auto-generated file.** Do not edit manually.
> Last updated: 2026-03-11 21:02

---

## Project: FixOnce

## Current Goal

**תשתית בדיקות לפני release**

Next step: Produce a focused report on widgets, user flows, strengths, and gaps

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

### Checkpoints created for 1 components

*Reason:* Bulk checkpoint at commit cf79438e

### Checkpoints created for 1 components

*Reason:* Bulk checkpoint at commit c57599ad

### AI Command Injection Security Layer with three mechanisms: Explicit Marker Lock (uuid4 IDs, one-time delivery), Session Scope Guard (project/session validation), Audit Visibility (full lifecycle tracking)

*Reason:* Prevents duplicate execution, scope hijacking, and provides transparency. Commands only execute once, in the correct project/session, with full audit trail.

### Unified Nervous System - Orb calculates health from Command Engine + Stability + Browser Errors. Timeout = 5 minutes for delivered commands.

*Reason:* Prevents cognitive dissonance. Single source of truth for system health. Commands not executed within 5 min = failed_timeout.

### Isolated Tabs Architecture: Backend session isolation per AI+project path, UI tabs per active project with independent Health Orbs

*Reason:* Prevents AI conflicts, enables multi-project parallel work, maintains minimalist UX. Each AI works in isolated bubble, dashboard shows tabs for all active projects.

### Browser-style Project Tabs with Session Isolation

*Reason:* Tabs feel like browser tabs - user knows what's open, sees activity via pulse color, can switch without losing Health Orb state. Hidden when only one project active.

### Hybrid element highlight lifecycle: auto ack pulse on browser-context fetch, subtle working indicator, and explicit done/clear modes.

*Reason:* Gives immediate user confirmation, avoids distracting continuous blinking, and keeps a clear work-state signal.

### AI Context Mode auto-injects selected browser elements into init_session response when active

*Reason:* When user enables AI Context in dashboard AND has selected elements via FAB, the init response includes formatted element details (selector, tag, id, classes, text, HTML). This allows AI to understand "this/that/זה" references automatically.

### AI must clear browser errors after fixing them using POST /api/clear-logs

*Reason:* When AI fixes a browser error, old errors remain in the dashboard causing false "unhealthy" status. After confirming fix works, AI should clear the error log so Orb returns to green.

### AI Commands auto-cleanup: executed commands decay after 5 minutes, failed commands stay, Clear History button for manual cleanup

*Reason:* Prevents queue buildup while keeping audit trail. Executed commands auto-removed after 5min. Failed commands need attention so they stay. Dashboard has Clear button for immediate cleanup.

### Checkpoints created for 10 components

*Reason:* Bulk checkpoint at commit 8d6ac320

### Clear on Success: When page loads without errors for 5 seconds, old errors (>60s) are automatically cleared

*Reason:* Prevents stale fixed errors from polluting the error log. Extension sends PAGE_LOAD_SUCCESS after 5s clean load, server clears errors older than 60 seconds.

### Solutions Memory Layer: debug_sessions stored in .fixonce/solutions.json, auto-surfaced on matching errors

*Reason:* Closes the bug→fix→remember→suggest loop. Solutions from debug_sessions are committed to Git, synced on clone, and surfaced when similar errors appear. Higher matching priority than insights.

### Session Resume State layer: save_resume_state/get_resume_state/clear_resume_state tools for persisting work state across sessions

*Reason:* FixOnce needs to remember not just knowledge (insights, decisions, solutions) but also operational state - where we were in the work. This enables true session continuity after MCP restart.

### Opening message format: narrative story style instead of bullet-point report. Tell what we did, why we stopped, what we wanted to test, what's the result. Creates emotional continuity.

*Reason:* Bullet points feel like a technical report. Narrative style makes user feel the system really remembers them - creates emotional continuity, not just data continuity.

### Opening message v2: (1) "עצרנו אחרי ש..." must be SPECIFIC/technical (2) NO stats like "40 decisions" - use human text (3) End with SPECIFIC next step, not generic "רוצה שנמשיך?"

*Reason:* שלושה שיפורי UX: דיוק טכני באיפה עצרנו, טקסט אנושי במקום סטטיסטיקות קרות, כיוון ברור לצעד הבא

### Opening message v3: הוספת 3 שדות מטא בראש ההודעה - (1) 📦 פרויקט: שם (2) ⏱ עדכון אחרון: זמן יחסי/מוחלט (3) 📌 checkpoint: שם או hash קצר

*Reason:* שלושת השדות האלה נותנים קונטקסט מיידי - איפה אני, מתי עבדתי, ובאיזו גרסה. זה מחזק את תחושת האמינות שהמערכת באמת זוכרת

### Opening message v4: (1) זמן חייב להיות ספציפי כמו "10 Mar 11:52" ולא סתם "היום" (2) הוספת שדה 📂 קובץ אחרון (3) שורת הזיכרון חמה יותר: "FixOnce עדיין זוכר..." במקום סטטיסטיקות

*Reason:* שלושה שיפורי UX: זמן ספציפי נותן context מדויק, קובץ אחרון נותן context של קוד אמיתי, שורת זיכרון חמה במקום קרה

### Opening message v5: הוספת שדה 🧩 אזור עבודה, מבנה נרטיבי משופר (מה→למה→איפה עצרנו→מצב נוכחי), שדות אופציונליים ⚠️ להימנע ו-🔧 פתוח, שאלת סיום ממוקדת יותר

*Reason:* שדרוג חוויית הפתיחה: אזור עבודה נותן מיקוד מיידי, המבנה מספר סיפור ולא דוח, שדות אופציונליים מונעים חזרה על טעויות ומזכירים משימות פתוחות

### Resume Context Architecture: auto_init_session returns both structured resume_context object AND human-readable suggested_opening. The context is built from real saved state (not templates). New tool update_work_context makes it easy to keep context fresh.

*Reason:* הפרדה בין truth layer (resume_context) לבין rendering layer (suggested_opening). ה-AI יכול לענות על שאלות המשך מהמידע המובנה, לא רק להציג טקסט.

### Opening message v6: (1) 📂 קובץ אחרון חייב להיות נתיב אמיתי כמו src/core/resume_context.py ולא תיאור כללי (2) להוסיף "השלב הבא יכול להיות..." לפני השאלה הסוגרת - נותן כיוון עבודה (3) לקצר את "FixOnce זוכר את ההחלטות..." ל"אז אפשר להמשיך בדיוק מאותה נקודה"

*Reason:* שלושה שיפורי UX אחרונים לגרסת 10/10: קובץ אמיתי נותן אמינות, הצעת שלב הבא נותנת כיוון, וקיצור הסיום מונע חזרתיות

### Memory Architecture Separation: projects_v2 = working cache, .fixonce = portable source of truth

*Reason:* שני מקורות אמת מייצרים באגים שקטים. ההפרדה: projects_v2 הוא cache עבודה מלא, .fixonce הוא הידע האיכותי שנוסע עם הריפו. בעתיד נשקול להעביר הכל ל-.fixonce כמקור יחיד.

### Opening format v7: Clean scannable sections - header, DECISIONS, AVOID, CONTEXT, STATE

*Reason:* נרטיבי ארוך מדי. פורמט חדש כמו Cursor/Linear - קצר, חד, סריק. מפתחים רוצים: איפה אנחנו, מה חשוב, מה הבא.

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

## Solved Problems

> Reference these when encountering similar errors.

### Uncaught TypeError: Cannot read properties of undefined (reading 'settings')
**Solution:** הסרתי גישה ל-undefined variable - testConfig היה undefined וניסיתי לגשת ל-testConfig.settings.theme

### Uncaught TypeError: Cannot read properties of null (reading 'someMethod')
**Solution:** בדקתי שהאובייקט לא null לפני קריאה למתודה - הוספתי optional chaining: obj?.someMethod() או בדיקת if (obj) לפני הקריאה

### Test error from FixOnce testing
**Solution:** This was a test error - removed the console.error call

---

*Generated by [FixOnce](https://github.com/fixonce) - AI Memory Layer*