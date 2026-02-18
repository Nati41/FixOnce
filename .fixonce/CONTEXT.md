# FixOnce Context

> **Auto-generated file.** Do not edit manually.
> Last updated: 2026-02-18 13:02

---

## Project: FixOnce

## Current Goal

**Build Bootstrap Context Generator - auto-generated context.md for any AI**

Next step: Implement grouped layout + smart badge visibility

---

## Decisions (MUST FOLLOW)

> **These are architectural decisions that MUST be respected.**
> Before making changes that contradict these, ask for explicit approval.

### Thread-local session במקום global state

*Reason:* מניעת race conditions וזליגת פרויקטים בין threads

### projects_v2 הוא ה-canonical storage היחיד

*Reason:* פישוט ארכיטקטורה, מניעת כפילות וסנכרונים מורכבים

### No auto-switch-back for project boundaries

*Reason:* Prevents ping-pong switching. Only switch INTO new projects, return to old project must be manual (dashboard) or explicit working_dir change.

### PostToolUse hook לבדיקת שגיאות דפדפן

*Reason:* התראה אוטומטית בטרמינל כשיש שגיאות חדשות אחרי כל פעולת קובץ

### _require_session() for tool validation

*Reason:* All MCP tools that need session must use _require_session() helper - returns aggressive error if not initialized

### Inversion of Control - FixOnce שולט, Claude מבצע

*Reason:* MCP הוא צינור לא שוטר. במקום לבקש מClaude לעקוב - המערכת מזריקה את ההקשר ומונעת ממנו להתעלם

### Auto-Inject Solutions Architecture

*Reason:* _find_solution_for_error() searches insights for matching solutions. min_similarity=40% with bonus for keyword matches. Injected in all error display paths.

### Session ID = MD5 hash of project_id + initialized_at

*Reason:* Short 8-char unique identifier that's reproducible. Using hash instead of UUID because it allows debugging which session belongs to which project.

### FixOnce = שכבת זיכרון אוניברסלית, לא תלוית עורך

*Reason:* Codex הוכיח: בינה בלי MCP עדיין רואה את המידע דרך קבצים/API. MCP הוא ערוץ גישה אחד, לא הליבה. אם OpenAI/Cursor משנים משהו - FixOnce חייב להישאר חי. הכוח צריך להיות בפרויקט עצמו.

### .fixonce/CONTEXT.md שייך ל-git, לא ל-gitignore

*Reason:* Context הוא חלק מהפרויקט. אם לא רגיש - תן לו להיות ב-git. כל צוות רואה, כל clone מקבל, כל branch יודע איפה הוא. אם נסתיר - זה חוזר להיות תשתית נסתרת.

### AI Bootstrap via README + CONTEXT.md, לא דרך MCP/injection

*Reason:* כל AI סורק README אוטומטית. הוספנו section שמפנה ל-.fixonce/CONTEXT.md. עובד עם Codex, Claude, Cursor, כל agent. לא תלוי בכלום - רק קבצים. Codex הוכיח שזה עובד.

---

## Architecture

AI Memory Layer - שכבת זיכרון persistent ל-AI assistants. מאפשר ל-Claude/Cursor/Copilot לזכור errors, solutions, decisions והקשר בין sessions.

**Stack:** Python (Flask), FastMCP, JavaScript (Browser Extension), HTML/CSS Dashboard, SQLite

**Key Flows:**
- Session Start: init_session -> load project context -> warm start
- Error Capture: Browser extension -> Flask API -> error_store -> dedup
- Solution Search: search_past_solutions -> semantic engine -> find similar
- Memory Update: update_live_record -> save to project JSON
- Multi-Project: switch_project -> isolated memory per directory

---

---

## Key Insights

> Lessons learned from previous work. Search `search_past_solutions()` for more.

- ב-macOS, .app עם CFBundleExecutable שמצביע על סקריפט bash עלול להיכשל בפתיחה דרך Finder/LaunchServices עם ‎kLSNoExecutableErr (-10827). פתרון: לשים Mach-O launcher ב-Contents/MacOS (למשל C קטן שעושה e...
- test
- History panel: raw activity logs are boring and repetitive. Solution: group consecutive activities by human_name within 5min window, then generate narrative sentences (e.g. 'עיצבת את הדשבורד — 6 עדכונ...
- Mismatch explanation: 'X פעולות' counts raw events filtered by tool & date from the last /api/activity/feed?limit=50, while History shows grouped 'stories' (groupActivities clusters events within 5 mi...
- Multi-AI Sync cache path fix: _do_init_session has a cache path that returns early via _format_from_snapshot. The Multi-AI tracking code must be DUPLICATED in the cache path (lines 1201-1230) not just...
- Dashboard ai_session path bug: API returns ai_session under memory.ai_session, but dashboard looked for ai_session directly on the active project object. Fixed in updateHeader() and loadAIStatus().
- Cursor MCP requirement: MCP servers from .cursor/mcp.json only load when the PROJECT FOLDER is open in Cursor AND you start a NEW chat. Unlike Claude Code which works from any directory, Cursor requir...
- Cursor MCP server name fix: In Cursor IDE, the FixOnce MCP server is named 'user-fixonce' (not 'fixonce'). The .cursorrules must reference 'user-fixonce' as the server name. Using the wrong name cause...
- Dashboard sync fix: activity feed updates constantly (hooks on every file edit), but project data (goal, active_ais) only updates when MCP tools are called. Fix: added /api/projects/live-state endpoin...
- Dashboard clarity improved when top card states immediate now-status (active AI + blocking error) and activity feed uses outcome language instead of raw technical counters.

---

## Solved Problems

> Reference these when encountering similar errors.

### Cursor לא מזהה MCP tools - אומר "I don't have access to auto_init_session"
**Solution:** Open the project folder in Cursor first, then start a new chat. The MCP tools will be available.

---

*Generated by [FixOnce](https://github.com/fixonce) - AI Memory Layer*