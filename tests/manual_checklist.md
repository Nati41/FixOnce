# FixOnce Manual Test Checklist

Run before any release. Check each box when verified.

---

## 1. Install
- [ ] Clone fresh repo
- [ ] `pip install -r requirements.txt` works
- [ ] `python src/server.py` starts without errors
- [ ] Dashboard loads at `localhost:5000/lite`
- [ ] MCP server responds

## 2. Resume
- [ ] Open existing project in Claude Code
- [ ] Opening message shows project name
- [ ] Shows specific time (not just "today")
- [ ] Shows last file worked on
- [ ] Shows work area
- [ ] "Where we stopped" is specific/technical
- [ ] Close and reopen - same context preserved

## 3. Rules
- [ ] Add rule in dashboard
- [ ] Rule appears in AI's next response
- [ ] Delete rule - AI stops following it
- [ ] Toggle rule off - AI ignores it
- [ ] "Notify AI" button works
- [ ] No duplicates when clicking multiple times

## 4. Errors
- [ ] Create browser error (console.error)
- [ ] Error appears in dashboard
- [ ] AI sees error via `fo_errors()`
- [ ] Fix error + call `fo_solved()`
- [ ] Clear logs (POST /api/clear_errors)
- [ ] Orb turns green
- [ ] New session - `fo_search()` finds fix
- [ ] Similar (not identical) error - correct solution returned

## 5. Isolation
- [ ] Project A in Claude - add decision
- [ ] Project B in Codex - decision NOT visible
- [ ] Back to A in Cursor - decision IS visible
- [ ] Rules don't leak between projects
- [ ] Resume context is project-specific
- [ ] Activity is project-specific

## 6. Dashboard
- [ ] Active AI updates when switching tools
- [ ] Project name correct
- [ ] Memory counters accurate
- [ ] Activity feed updates live
- [ ] Rules list correct
- [ ] Orb color reflects actual state
- [ ] No empty sections when data exists

## 7. Safety Point
- [ ] Click "Set Safety Point" button
- [ ] Verify something was saved
- [ ] Can identify the saved point
- [ ] Components marked as stable

## 8. Empty Project
- [ ] New folder with just one .py file
- [ ] Open in Claude Code
- [ ] FixOnce initializes without error
- [ ] Dashboard shows "new project" state
- [ ] No broken UI / empty boxes
- [ ] Can add first rule
- [ ] Can add first decision

## 9. Multi-AI
Test same project across AIs:

| Test | Claude | Cursor | Codex |
|------|--------|--------|-------|
| Opens with resume | | | |
| Shows correct project | | | |
| Rules enforced | | | |
| Decisions respected | | | |
| Activity logged | | | |

## 10. Windows / Mac
- [ ] Mac: Full flow works
- [ ] Windows: Server starts
- [ ] Windows: Dashboard loads
- [ ] Windows: Project detection works
- [ ] Windows: Paths handled correctly

---

## Quick Smoke Test (5 min)
If short on time, verify just these:
1. Server starts
2. Dashboard loads
3. Project detected
4. Resume shows context
5. Rule added and followed
6. Error saved and found

---

**Date tested:** ___________
**Tester:** ___________
**Version/commit:** ___________
