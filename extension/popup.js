// FixOnce Popup - Smart Auto-Focus

const API = 'http://localhost:5000';

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

// Common dev ports (any host with these ports is considered dev)
const DEV_PORTS = ['3000', '3001', '4200', '5000', '5173', '5174', '8000', '8080', '8888'];

let currentDomain = '';
let currentTab = null;

// Check if domain is auto-allowed (dev environment)
function isAutoAllowed(domain) {
  // Check patterns
  for (const pattern of AUTO_ALLOWED_PATTERNS) {
    if (pattern.test(domain)) return true;
  }

  // Check dev ports
  const port = domain.split(':')[1];
  if (port && DEV_PORTS.includes(port)) return true;

  return false;
}

// Get whitelist from storage
async function getWhitelist() {
  const result = await chrome.storage.local.get(['whitelist', 'sessionWhitelist']);
  return {
    permanent: result.whitelist || [],
    session: result.sessionWhitelist || []
  };
}

// Add domain to whitelist
async function addToWhitelist(domain, permanent = true) {
  const lists = await getWhitelist();

  if (permanent) {
    if (!lists.permanent.includes(domain)) {
      lists.permanent.push(domain);
      await chrome.storage.local.set({ whitelist: lists.permanent });
    }
  } else {
    if (!lists.session.includes(domain)) {
      lists.session.push(domain);
      await chrome.storage.local.set({ sessionWhitelist: lists.session });
    }
  }
}

// Remove domain from whitelist
async function removeFromWhitelist(domain) {
  const lists = await getWhitelist();

  lists.permanent = lists.permanent.filter(d => d !== domain);
  lists.session = lists.session.filter(d => d !== domain);

  await chrome.storage.local.set({
    whitelist: lists.permanent,
    sessionWhitelist: lists.session
  });
}

// Check if domain is allowed (auto or whitelist)
async function isDomainAllowed(domain) {
  if (isAutoAllowed(domain)) return { allowed: true, reason: 'auto' };

  const lists = await getWhitelist();
  if (lists.permanent.includes(domain)) return { allowed: true, reason: 'whitelist' };
  if (lists.session.includes(domain)) return { allowed: true, reason: 'session' };

  return { allowed: false, reason: 'blocked' };
}

// Update UI based on domain status
async function updateUI() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs[0]?.url) return;

  currentTab = tabs[0];

  try {
    const url = new URL(currentTab.url);
    currentDomain = url.host;
  } catch {
    currentDomain = 'unknown';
  }

  document.getElementById('domain-badge').textContent = currentDomain;

  const status = await isDomainAllowed(currentDomain);

  const statusIndicator = document.getElementById('status-indicator');
  const statusDot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');
  const sleepingView = document.getElementById('sleeping-view');
  const activeView = document.getElementById('active-view');
  const whitelistInfo = document.getElementById('whitelist-info');
  const activeInfo = document.getElementById('active-info');

  if (status.allowed) {
    // Active state
    statusIndicator.className = 'status-indicator active';
    statusDot.className = 'status-dot active';
    statusText.className = 'status-text active';
    statusText.textContent = 'Tracking errors';

    sleepingView.style.display = 'none';
    activeView.style.display = 'block';

    if (status.reason === 'auto') {
      activeInfo.textContent = 'Auto-enabled (dev environment)';
      document.getElementById('disable-btn').style.display = 'none';
    } else if (status.reason === 'session') {
      activeInfo.textContent = 'Enabled for this session';
      document.getElementById('disable-btn').style.display = 'block';
    } else {
      activeInfo.textContent = 'Manually enabled';
      document.getElementById('disable-btn').style.display = 'block';
    }

    // Load stats
    loadStats();
  } else {
    // Sleeping state
    statusIndicator.className = 'status-indicator sleeping';
    statusDot.className = 'status-dot sleeping';
    statusText.className = 'status-text sleeping';
    statusText.textContent = 'Inactive on this site';

    sleepingView.style.display = 'block';
    activeView.style.display = 'none';
    whitelistInfo.textContent = '';
  }
}

// Load error stats
async function loadStats() {
  try {
    const res = await fetch(API + '/api/memory');
    const data = await res.json();

    const issues = data.active_issues || [];
    const solutions = data.solutions_history || [];

    // Count errors from current domain
    const domainErrors = issues.filter(i => {
      const errorDomain = i.domain || i.url || '';
      return errorDomain.includes(currentDomain);
    });

    const errorCount = document.getElementById('error-count');
    const solvedCount = document.getElementById('solved-count');

    errorCount.textContent = domainErrors.length;
    errorCount.className = domainErrors.length > 0 ? 'stat-number' : 'stat-number zero';

    solvedCount.textContent = solutions.length;
  } catch (e) {
    console.error('Failed to load stats:', e);
  }
}

// Event Listeners
document.getElementById('enable-btn').addEventListener('click', async () => {
  await addToWhitelist(currentDomain, true);

  // Notify background script
  chrome.runtime.sendMessage({
    type: 'WHITELIST_UPDATED',
    domain: currentDomain,
    action: 'add'
  });

  // Reload the tab to start capturing
  chrome.tabs.reload(currentTab.id);
  window.close();
});

document.getElementById('enable-session-btn').addEventListener('click', async () => {
  await addToWhitelist(currentDomain, false);

  chrome.runtime.sendMessage({
    type: 'WHITELIST_UPDATED',
    domain: currentDomain,
    action: 'add-session'
  });

  chrome.tabs.reload(currentTab.id);
  window.close();
});

document.getElementById('disable-btn').addEventListener('click', async () => {
  await removeFromWhitelist(currentDomain);

  chrome.runtime.sendMessage({
    type: 'WHITELIST_UPDATED',
    domain: currentDomain,
    action: 'remove'
  });

  updateUI();
});

document.getElementById('open-dashboard-btn').addEventListener('click', () => {
  chrome.tabs.create({ url: API + '/brain' });
});

// Initialize
updateUI();
