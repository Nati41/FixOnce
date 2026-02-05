# Screenshots Guide for Chrome Web Store

## Required Screenshots

Chrome Web Store requires at least 1 screenshot, recommends 3-5.
Size: 1280x800 or 640x400 pixels (16:10 aspect ratio)

---

## Screenshot 1: Extension Popup (REQUIRED)

**What to capture:**
- Extension popup in "Active" state
- Error count showing (e.g., "3")
- Solved count showing (e.g., "1")
- Domain badge visible (e.g., "localhost:3000")
- "Open Dashboard" button visible

**How to take:**
1. Open a dev site with some errors
2. Enable FixOnce on the site
3. Trigger a few errors
4. Click extension icon
5. Screenshot the popup

**Caption:** "Track errors in real-time on any website you're developing"

---

## Screenshot 2: Dashboard Overview (REQUIRED)

**What to capture:**
- Brain Dashboard (localhost:5000/brain)
- Active Issues section with 2-3 errors
- Solutions History with at least 1 solution
- ROI stats showing usage
- Clean, professional look

**How to take:**
1. Open localhost:5000/brain
2. Make sure there are some issues and solutions
3. Full page screenshot
4. Crop to 1280x800

**Caption:** "AI-ready dashboard shows errors with full context for instant fixing"

---

## Screenshot 3: Error Flow (RECOMMENDED)

**What to capture:**
- Split view or annotated image showing:
  - Left: Browser console with error
  - Right: FixOnce capturing it
  - Arrow showing the flow

**How to create:**
1. Take screenshot of console error
2. Take screenshot of FixOnce popup/dashboard
3. Combine in image editor
4. Add arrow annotation

**Caption:** "Errors captured automatically with stack traces and file locations"

---

## Screenshot 4: AI Integration (RECOMMENDED)

**What to capture:**
- Claude Code or Cursor showing:
  - Error from FixOnce
  - AI suggesting/applying fix
  - Code being modified

**How to take:**
1. Start Claude Code session
2. Say "hi" - let it load FixOnce context
3. Show it fixing an error
4. Screenshot the interaction

**Caption:** "AI assistants read errors directly and apply fixes from memory"

---

## Screenshot 5: Solutions Memory (OPTIONAL)

**What to capture:**
- Solutions History section expanded
- Multiple past solutions visible
- Keywords/tags visible
- Search functionality shown

**How to take:**
1. Open dashboard
2. Make sure you have 3+ solutions saved
3. Screenshot the solutions section

**Caption:** "Build a searchable memory of solutions - never debug the same bug twice"

---

## Screenshot Tips

### Do's ✅
- Use real data (actual errors, not lorem ipsum)
- Keep UI clean and uncluttered
- Show the extension doing its job
- Use consistent browser/theme
- Highlight key features with annotations

### Don'ts ❌
- Don't show sensitive data (real API keys, passwords)
- Don't use placeholder text
- Don't include browser toolbars/bookmarks
- Don't show personal information
- Don't use low-resolution images

---

## Recommended Tools

- **macOS:** Cmd+Shift+4 (select area) or Cmd+Shift+5 (options)
- **Chrome:** DevTools → More tools → Screenshot
- **Editing:** Figma, Canva, or Preview (macOS)
- **Annotations:** Skitch, Cleanshot X, or Figma

---

## File Naming

Save screenshots as:
```
screenshot-1-popup.png
screenshot-2-dashboard.png
screenshot-3-error-flow.png
screenshot-4-ai-integration.png
screenshot-5-solutions.png
```

---

## Quick Checklist

- [ ] At least 1280x800 resolution
- [ ] 16:10 aspect ratio
- [ ] No personal/sensitive data visible
- [ ] Extension functionality clearly shown
- [ ] Professional, clean appearance
- [ ] Saved as PNG (not JPG)
