# Permission Justifications for Chrome Web Store Review

This document explains why FixOnce requires each permission and how they are used.

---

## 1. storage

**Why needed:** To save the user's whitelist preferences locally.

**How used:**
- Stores array of domains where user enabled error tracking
- Stores user preferences (server URL, etc.)
- All data stored locally in chrome.storage.local

**Example:**
```javascript
// Saving whitelist
chrome.storage.local.set({ whitelist: ['localhost', 'myapp.local'] });

// Reading whitelist
chrome.storage.local.get('whitelist', (data) => { ... });
```

**Privacy:** No sensitive data stored. Only domain names and preferences.

---

## 2. activeTab

**Why needed:** To detect the domain of the current tab when user clicks the extension icon.

**How used:**
- Gets current tab URL to extract domain
- Shows domain in popup badge
- Checks if current site is in whitelist

**Example:**
```javascript
// In popup.js when popup opens
chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
  const url = new URL(tabs[0].url);
  const domain = url.hostname;
  // Show domain in popup, check whitelist status
});
```

**Privacy:** Only reads URL, does not modify page content or read page data.

---

## 3. tabs

**Why needed:** To query tab information for domain detection.

**How used:**
- Works with activeTab to get current tab's URL
- Required for chrome.tabs.query() API

**Example:**
```javascript
chrome.tabs.query({active: true, currentWindow: true}, callback);
```

**Privacy:** Only accesses tab URL, not page content.

---

## 4. host_permissions: <all_urls>

**Why needed:** To inject error capture scripts into web pages that the user wants to monitor.

**How used:**
- Content scripts (logger.js, bridge.js) are injected into pages
- Scripts listen for JavaScript errors and network failures
- **ONLY active on sites user explicitly enables**

**Default behavior:**
- Extension is INACTIVE on all sites by default
- User must click "Enable on this site" to start tracking
- Whitelist stored locally, user can disable anytime

**What scripts do:**
```javascript
// logger.js - Captures errors
window.addEventListener('error', (event) => {
  // Only if site is whitelisted
  sendToLocalServer({
    type: event.error.name,
    message: event.error.message,
    stack: event.error.stack
  });
});
```

**Why not narrower permissions:**
- Developers work on many different domains (localhost, staging, production)
- Cannot predict which domains users will need to monitor
- Each user's development environment is different
- Permission only used on explicitly whitelisted sites

**Privacy safeguards:**
1. Opt-in only - user must explicitly enable each site
2. All data sent to localhost only (user's own machine)
3. No data sent to external servers
4. User can disable/remove sites from whitelist anytime
5. Only error data captured - no forms, passwords, or personal data

---

## Alternative Approaches Considered

### Option 1: Optional host permissions
- Would require user to grant permission for each domain
- Poor UX for developers who work on many local domains
- Rejected: Too many permission prompts

### Option 2: Specific domain list
- Cannot predict all development domains
- Would break for localhost:3000, localhost:8080, etc.
- Rejected: Not practical for development use case

### Option 3: Current approach (all_urls + whitelist)
- Single permission grant on install
- User controls which sites via whitelist
- Best balance of functionality and privacy
- Accepted: Clear user control with opt-in model

---

## Data Flow Diagram

```
[Website]
    ↓ (only if whitelisted)
[FixOnce Content Script]
    ↓ (captures error)
[Background Script]
    ↓ (sends to)
[User's Local Server - localhost:5000]
    ↓ (never leaves)
[User's Machine]
```

---

## Compliance

- **No remote code execution** - All code bundled in extension
- **No analytics/tracking** - Zero external data collection
- **No minification** - Code is readable and reviewable
- **Open source** - Full transparency at github.com/fixonce/fixonce

---

## Contact for Review Questions

If reviewers have questions about permissions or functionality:
- GitHub Issues: github.com/fixonce/fixonce/issues
- Email: [your-email]

We're happy to provide additional clarification or make adjustments to meet Chrome Web Store policies.
