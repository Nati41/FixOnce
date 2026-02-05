# FixOnce - Chrome Web Store Listing

## Basic Information

**Extension Name:** FixOnce - Error Trapper

**Short Description (132 chars max):**
```
AI-native error tracking. Capture JS errors, build solution memory, never debug the same bug twice. Works with Claude, Cursor & more.
```

**Category:** Developer Tools

**Language:** English (Primary), Hebrew

---

## Full Description

```
🎯 NEVER DEBUG THE SAME BUG TWICE

FixOnce is an AI Memory Layer for developers. It captures JavaScript errors from your web applications and builds a persistent memory of problems and solutions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔥 KEY FEATURES

✅ Smart Error Capture
• Catches JavaScript errors with full stack traces
• Captures HTTP 4xx/5xx network failures
• Records exact file paths and line numbers
• Automatic deduplication - same error counted once

✅ AI Memory Layer
• Solutions History - Past fixes with searchable keywords
• Handover - Session summaries that transfer context
• Decisions - Architectural choices preserved
• Avoid Patterns - Failed approaches documented

✅ AI Editor Integration
• Works with Claude Code, Cursor, and any MCP-compatible AI
• AI reads errors directly and fixes them
• Solutions auto-saved for future sessions
• Full context persists across conversations

✅ Privacy First
• All data stays on YOUR machine
• No external servers, no cloud storage
• You control what sites are monitored
• Opt-in only - inactive by default

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 HOW IT WORKS

1. Install FixOnce extension
2. Start the local FixOnce server
3. Enable tracking on your dev sites
4. Errors are captured automatically
5. AI assistants read and fix bugs
6. Solutions saved for next time

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 PERFECT FOR

• Frontend developers debugging React/Vue/Angular apps
• Full-stack developers working on web applications
• Teams using AI coding assistants
• Anyone tired of debugging the same bugs repeatedly

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔒 PRIVACY & SECURITY

• Zero data collection - we never see your errors
• Local storage only - data stays on your machine
• Whitelist control - you choose which sites to monitor
• Open source - inspect the code yourself

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📖 GETTING STARTED

1. Install this extension
2. Download FixOnce server from GitHub
3. Run: python3 server.py
4. Click extension icon → Enable on your site
5. Open localhost:5000/brain to see captured errors

Full documentation: github.com/fixonce/fixonce

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Made with ❤️ for developers who hate debugging the same bug twice.
```

---

## Screenshots Requirements

Need 1-5 screenshots (1280x800 or 640x400):

### Screenshot 1: Popup Active State
- Show the extension popup with error count
- Domain badge visible
- "Open Dashboard" button

### Screenshot 2: Dashboard Overview
- Brain dashboard with active issues
- Solutions history visible
- ROI stats

### Screenshot 3: Error Capture in Action
- Console showing error
- FixOnce capturing it
- Arrow showing flow to dashboard

### Screenshot 4: AI Integration
- Claude/Cursor reading the error
- Solution being applied
- Code being fixed

### Screenshot 5: Solutions Memory
- Past solutions searchable
- Keywords visible
- "Never debug twice" message

---

## Promotional Images (Optional)

### Small Promo Tile (440x280)
- FixOnce logo
- "AI Memory Layer"
- Dark gradient background

### Large Promo Tile (920x680)
- Full branding
- Key features bullets
- Screenshot preview

### Marquee (1400x560)
- Hero image for featured placement
- "Never Debug the Same Bug Twice"
- Visual showing error → fix → memory flow

---

## Store Category & Tags

**Category:** Developer Tools

**Tags/Keywords:**
- error tracking
- debugging
- AI assistant
- developer tools
- JavaScript
- bug fix
- Claude
- Cursor
- MCP
- web development

---

## Support & Links

**Support URL:** https://github.com/fixonce/fixonce/issues

**Privacy Policy URL:** [Your hosted privacy-policy.html URL]

**Homepage URL:** https://github.com/fixonce/fixonce

---

## Review Notes for Google

```
This extension is a developer tool for error tracking and debugging.

PERMISSIONS JUSTIFICATION:

1. "storage" - Required to save user's whitelist preferences (which sites have tracking enabled).

2. "activeTab" - Required to detect the current website's domain to show in the popup and check whitelist status.

3. "tabs" - Required to get the current tab's URL for domain detection and whitelist checking.

4. "host_permissions: <all_urls>" - Required to inject error capture scripts into websites the user chooses to monitor. This permission is ONLY used on sites the user explicitly enables via the whitelist. By default, the extension is inactive on all sites.

DATA HANDLING:
- All captured error data is sent ONLY to the user's local server (localhost:5000 by default)
- No data is ever sent to external servers
- No personal information is collected
- Users have full control over which sites are monitored

The extension is open source and can be inspected at: github.com/fixonce/fixonce
```
