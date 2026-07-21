# Active Project Display Investigation

**Date:** 2026-07-16  
**Status:** Resolved  
**Outcome:** No bug found; historical observation could not be reproduced

---

## Summary

A user reported that the native FixOnce app displayed "v3-main" while MCP was connected to "FixOnce". Investigation found:

1. **The split-brain hypothesis was disproven** — there is no second source of truth
2. **All APIs returned correct data** at time of investigation
3. **The historical display issue could not be reproduced**
4. **No speculative fix was added** — the architecture is correct as-is

---

## Architecture (Verified)

### Single Source of Truth

`~/.fixonce/active_project.json` is the only persisted active-project state.

### Write Routing

MCP tools use explicit `cwd` parameter for project binding:
- `fo_init(cwd="/path/to/project")` establishes session context
- All subsequent tool calls route to that project
- The resolver writes to `~/.fixonce/active_project.json` for dashboard display
- **MCP never reads from active_project.json for routing**

### Read Paths

| Consumer | Source |
|----------|--------|
| Dashboard (web) | `/api/dashboard_snapshot` → server reads resolver |
| Tray (native) | `/api/tray/status` → server reads resolver |
| Native window | Same dashboard via pywebview |

All paths read from the same resolver, which reads from `~/.fixonce/active_project.json`.

---

## What Was Removed

### Legacy File: `<repo>/data/active_project.json`

This file was created before the portability refactor (March 2026) and was never deleted. It was:
- Not read by any current code
- Not written by any current code
- A confusing artifact that suggested split-brain

**Action:** Deleted from repository, added to `.gitignore`.

---

## Investigation Results

### API State at Investigation Time

| Endpoint | Value |
|----------|-------|
| `/api/dashboard_snapshot` → `project_name` | FixOnce |
| `/api/dashboard_snapshot` → `selected_project_id` | FixOnce_34592c5b |
| `/api/dashboard_snapshot` → `identity.name` | FixOnce |
| `/api/tray/status` → `project_name` | FixOnce |
| `~/.fixonce/active_project.json` → `display_name` | FixOnce |

All sources agreed. The reported v3-main display could not be reproduced.

### Cache Search

| Location | v3-main found? |
|----------|----------------|
| `~/.fixonce/active_project.json` | No |
| `~/Library/WebKit/com.fixonce.app/` | No |
| `~/Library/Caches/com.fixonce.app/` | No |
| Dashboard HTML source | No |
| localStorage/sessionStorage | Not used |

### Process State

- Single dashboard process running
- Single tray process running
- No stale webview windows

---

## Possible Explanations (Unproven)

The historical observation may have been caused by:

1. **Timing** — Screenshot taken before JavaScript `fetchData()` completed (runs every 5s)
2. **Prior session** — Webview from a previous session before the file was corrected
3. **Manual file edit** — The file was manually corrected during investigation

No speculative fix was added because:
- The architecture is correct
- All current state is consistent
- The issue cannot be reproduced

---

## Regression Tests Added

`tests/test_catalog_repair_stale_override.py`:
- `test_force_false_preserves_live_session` — Stale writes blocked when live session exists
- `test_force_true_does_override` — Explicit force works
- `test_no_live_session_allows_update` — Updates allowed when no live session
- `test_legacy_repo_file_deleted` — Legacy file does not exist
- `test_repo_file_in_gitignore` — Legacy file path is ignored
- `test_template_file_exists` — Template file preserved

`tests/test_native_app_project_display.py`:
- `test_snapshot_project_fields_agree` — All project name sources agree
- `test_selected_project_exists_in_list` — Selected ID exists in project list
- `test_tray_matches_dashboard` — Tray and dashboard show same project
- `test_file_matches_api` — File and API agree
- `test_api_reflects_file_change` — API reflects current file state
- `test_fresh_fetch_returns_current_project` — Multiple fetches are consistent
- `test_single_dashboard_process` — Only one dashboard process
- `test_single_tray_process` — Only one tray process

---

## Follow-Up Items (Deferred)

### ImportError Direct-Write Fallbacks

Two locations bypass the resolver when import fails:

1. `src/managers/multi_project_manager.py:564-567`
2. `src/core/system_status.py:920-930`

These write directly to `active_project.json` without live-session checks. Risk is low because:
- They only trigger if the resolver module cannot be imported
- This should never happen in production
- They are fallback paths for edge cases

**Decision:** No change in this commit. Monitor for issues.

---

## Conclusion

The active-project architecture is sound:

1. **One persisted source:** `~/.fixonce/active_project.json`
2. **Authoritative routing:** MCP uses cwd/session context, not the file
3. **Consistent reads:** Dashboard, tray, and native app all read server state
4. **No split-brain:** The legacy repo file was dead code

The historical v3-main observation was not reproducible and required no code fix.
