# FixOnce Chrome Extension

> AI Memory Layer for developers - Never debug the same bug twice.

## Installation (Development)

1. Open Chrome and go to `chrome://extensions/`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select this `extension` folder
5. The extension icon will appear in your toolbar

## How It Works

1. **Enable on a site** - Click extension icon → "Enable on this site"
2. **Errors captured** - JavaScript errors and HTTP failures are sent to FixOnce server
3. **View in dashboard** - Open `localhost:5000/brain` to see captured errors
4. **AI fixes bugs** - AI assistants read errors and apply fixes

## Files

```
extension/
├── manifest.json      # Extension config (Manifest V3)
├── background.js      # Service worker
├── popup.html         # Extension popup UI
├── popup.js           # Popup logic
├── logger.js          # Error capture (MAIN world)
├── bridge.js          # Communication bridge
├── content.js         # Content script
├── injected.js        # Injected script
├── icon16.png         # Toolbar icon
├── icon48.png         # Extension icon
├── icon128.png        # Store icon
├── store/             # Chrome Web Store materials
│   ├── privacy-policy.html
│   ├── STORE_LISTING.md
│   ├── PERMISSION_JUSTIFICATIONS.md
│   ├── SUBMISSION_CHECKLIST.md
│   └── SCREENSHOTS_GUIDE.md
└── README.md          # This file
```

## Requirements

- Chrome 88+ (Manifest V3 support)
- FixOnce server running on `localhost:5000`

## Chrome Web Store

See the `store/` folder for all submission materials:
- Privacy Policy
- Store listing description
- Permission justifications
- Submission checklist
- Screenshots guide

## Permissions

| Permission | Why |
|------------|-----|
| `storage` | Save whitelist preferences |
| `activeTab` | Detect current site domain |
| `tabs` | Query tab URL |
| `<all_urls>` | Inject error capture on whitelisted sites |

## Privacy

- All data stays on YOUR machine
- No external servers
- Opt-in only - inactive by default
- You control which sites are monitored

## Version History

### v2.0.0 (Feb 2026)
- Prepared for Chrome Web Store
- Added 16px icon
- Updated description
- Added store materials

### v1.3
- HTTP 4xx/5xx capture
- Improved deduplication

### v1.0
- Initial release
- JavaScript error capture
- Whitelist system
