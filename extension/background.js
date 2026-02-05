/**
 * FixOnce v1.1 - Background Service Worker
 * Never debug the same bug twice.
 * Smart Auto-Focus: Only captures errors from dev environments and whitelisted domains
 */

// Dynamic port discovery
const PORT_RANGE = [5000, 5001, 5002, 5003, 5004, 5005];
let ACTIVE_PORT = 5000;
let SERVER_URL = 'http://localhost:5000/api/log_error';
let BATCH_URL = 'http://localhost:5000/api/log_errors_batch';
let HANDSHAKE_URL = 'http://localhost:5000/api/handshake';
let CURRENT_SITE_URL = 'http://localhost:5000/api/current-site';
const BATCH_SIZE = 10;
const BATCH_INTERVAL = 1000;

// Discover which port FixOnce is running on
async function discoverServer() {
  for (const port of PORT_RANGE) {
    try {
      const response = await fetch(`http://localhost:${port}/api/ping`, {
        method: 'GET',
        timeout: 1000
      });
      if (response.ok) {
        const data = await response.json();
        if (data.service === 'fixonce') {
          ACTIVE_PORT = port;
          SERVER_URL = `http://localhost:${port}/api/log_error`;
          BATCH_URL = `http://localhost:${port}/api/log_errors_batch`;
          HANDSHAKE_URL = `http://localhost:${port}/api/handshake`;
          CURRENT_SITE_URL = `http://localhost:${port}/api/current-site`;
          console.log(`[FixOnce] Server found on port ${port}`);
          return true;
        }
      }
    } catch (e) {
      // Port not available, try next
    }
  }
  console.log('[FixOnce] Server not found on any port');
  return false;
}

let errorQueue = [];
let isServerAvailable = true;
let flushTimer = null;

// ===== SMART AUTO-FOCUS =====

// Dev environment patterns (always allowed)
const AUTO_ALLOWED_PATTERNS = [
  /^localhost(:\d+)?$/,
  /^127\.0\.0\.1(:\d+)?$/,
  /^0\.0\.0\.0(:\d+)?$/,
  /^.*\.local(:\d+)?$/,
  /^.*\.localhost(:\d+)?$/,
  /^local\..*(:\d+)?$/,
  /^dev\..*(:\d+)?$/,
  /^staging\..*(:\d+)?$/,
];

// Common dev ports
const DEV_PORTS = ['3000', '3001', '4200', '5000', '5173', '5174', '8000', '8080', '8888'];

// Check if domain is auto-allowed
function isAutoAllowed(domain) {
  if (!domain) return false;

  for (const pattern of AUTO_ALLOWED_PATTERNS) {
    if (pattern.test(domain)) return true;
  }

  const port = domain.split(':')[1];
  if (port && DEV_PORTS.includes(port)) return true;

  return false;
}

// Get domain from URL
function getDomain(url) {
  try {
    const parsed = new URL(url);
    return parsed.host;
  } catch {
    return null;
  }
}

// Check if domain is allowed
async function isDomainAllowed(domain) {
  if (!domain) return false;
  if (isAutoAllowed(domain)) return true;

  const result = await chrome.storage.local.get(['whitelist', 'sessionWhitelist']);
  const permanent = result.whitelist || [];
  const session = result.sessionWhitelist || [];

  return permanent.includes(domain) || session.includes(domain);
}

// Update extension icon based on domain status
async function updateIcon(tabId, domain) {
  const allowed = await isDomainAllowed(domain);

  // Set badge
  if (allowed) {
    chrome.action.setBadgeBackgroundColor({ tabId, color: '#81b29a' });
    chrome.action.setBadgeText({ tabId, text: '' });
  } else {
    chrome.action.setBadgeBackgroundColor({ tabId, color: '#555' });
    chrome.action.setBadgeText({ tabId, text: 'OFF' });
  }
}

// Track error counts per tab
const tabErrorCounts = {};

function updateErrorBadge(tabId, count) {
  if (count > 0) {
    chrome.action.setBadgeBackgroundColor({ tabId, color: '#e76f51' });
    chrome.action.setBadgeText({ tabId, text: count > 99 ? '99+' : String(count) });
  }
}

// ===== SERVER COMMUNICATION =====

async function sendHandshake() {
  try {
    const response = await fetch(HANDSHAKE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: '1.1', timestamp: new Date().toISOString() })
    });
    if (response.ok) {
      console.log('[FixOnce] Handshake successful');
      isServerAvailable = true;
    }
  } catch {
    console.log('[FixOnce] Server not available for handshake');
  }
}

chrome.runtime.onInstalled.addListener((details) => {
  console.log('[FixOnce] Extension installed/updated:', details.reason);
  sendHandshake();

  // Clear session whitelist on install/update
  chrome.storage.local.set({ sessionWhitelist: [] });
});

chrome.runtime.onStartup.addListener(() => {
  console.log('[FixOnce] Browser started');
  sendHandshake();

  // Clear session whitelist on browser start
  chrome.storage.local.set({ sessionWhitelist: [] });
});

async function checkServer() {
  try {
    // First try to discover server if not available
    if (!isServerAvailable) {
      await discoverServer();
    }

    const response = await fetch(`http://localhost:${ACTIVE_PORT}/api/config`, { method: 'GET' });
    isServerAvailable = response.ok;
    if (isServerAvailable) {
      sendHandshake();
    }
  } catch {
    isServerAvailable = false;
    // Try to discover server on next check
    discoverServer();
  }
}

async function flushQueue() {
  if (errorQueue.length === 0 || !isServerAvailable) return;

  const batch = errorQueue.splice(0, errorQueue.length);

  try {
    const response = await fetch(BATCH_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ errors: batch })
    });

    if (!response.ok) {
      errorQueue.unshift(...batch);
    }
  } catch {
    errorQueue.unshift(...batch);
  }
}

function scheduleFlush() {
  if (flushTimer) return;

  flushTimer = setTimeout(() => {
    flushTimer = null;
    flushQueue();
  }, BATCH_INTERVAL);
}

function queueError(payload) {
  errorQueue.push(payload);

  if (errorQueue.length >= BATCH_SIZE) {
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    flushQueue();
  } else {
    scheduleFlush();
  }
}

// ===== MESSAGE HANDLING =====

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'LOG_ERROR' && message.payload) {
    const tabUrl = sender.tab?.url;
    const domain = getDomain(tabUrl);

    // Check if domain is allowed
    isDomainAllowed(domain).then(allowed => {
      if (!allowed) {
        console.log('[FixOnce] Ignoring error from blocked domain:', domain);
        sendResponse({ success: false, reason: 'domain_blocked' });
        return;
      }

      const payload = {
        ...message.payload,
        tabId: sender.tab?.id,
        tabUrl: tabUrl?.substring(0, 200),
        domain: domain
      };

      queueError(payload);

      // Update error count badge
      const tabId = sender.tab?.id;
      if (tabId) {
        tabErrorCounts[tabId] = (tabErrorCounts[tabId] || 0) + 1;
        updateErrorBadge(tabId, tabErrorCounts[tabId]);
      }

      sendResponse({ success: true, queued: true });
    });

    return true; // Keep channel open for async response
  }

  // Handle whitelist updates from popup
  if (message.type === 'WHITELIST_UPDATED') {
    console.log('[FixOnce] Whitelist updated:', message.domain, message.action);
    sendResponse({ success: true });
    return true;
  }
});

// ===== TAB EVENTS =====

// Update icon when tab is activated
chrome.tabs.onActivated.addListener(async (activeInfo) => {
  try {
    const tab = await chrome.tabs.get(activeInfo.tabId);
    if (tab.url) {
      const domain = getDomain(tab.url);
      updateIcon(activeInfo.tabId, domain);
    }
  } catch {}
});

// Update icon when tab URL changes
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    const domain = getDomain(tab.url);
    updateIcon(tabId, domain);

    // Reset error count for new page
    tabErrorCounts[tabId] = 0;
  }
});

// Clean up when tab is closed
chrome.tabs.onRemoved.addListener((tabId) => {
  delete tabErrorCounts[tabId];
});

// ===== CURRENT SITE TRACKING =====

let currentSite = null;

async function updateCurrentSite(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (tab.url) {
      const domain = getDomain(tab.url);
      if (domain && isAutoAllowed(domain)) {
        currentSite = {
          url: tab.url,
          domain: domain,
          title: tab.title || domain,
          timestamp: new Date().toISOString()
        };

        // Send to server
        try {
          await fetch(CURRENT_SITE_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentSite)
          });
        } catch (e) {
          // Server not available
        }
      }
    }
  } catch (e) {}
}

// Track when user switches tabs
chrome.tabs.onActivated.addListener(async (activeInfo) => {
  updateCurrentSite(activeInfo.tabId);
});

// Track when tab URL changes
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.active) {
    updateCurrentSite(tabId);
  }
});

// ===== INITIALIZATION =====

// Discover server on startup, then check periodically
discoverServer().then(() => {
  checkServer();
});

setInterval(checkServer, 30000);

// Get current site on startup
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  if (tabs[0]) updateCurrentSite(tabs[0].id);
});

console.log('[FixOnce] Service worker ready (v1.3 with Dynamic Port Discovery)');
