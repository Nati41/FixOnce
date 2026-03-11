/**
 * FixOnce Element Picker v5 - FINAL
 * Project-aware, dedupe, clean states, proper cleanup
 */

(function() {
  'use strict';

  // Prevent duplicate initialization
  if (window.__fixonce_initialized__) {
    console.log('[FixOnce] Already initialized, skipping');
    return;
  }
  window.__fixonce_initialized__ = true;

  // Config
  const SERVER_PORTS = [5000, 5001, 5002];
  const POLL_INTERVAL = 2000;
  const ACK_HIGHLIGHT_DURATION = 1200;
  const DONE_HIGHLIGHT_DURATION = 900;
  const WORKING_HIGHLIGHT_MAX_DURATION = 45000;
  const FADE_DURATION = 300;

  let serverPort = null;
  let pollInterval = null;

  // State
  let pickerState = 'idle'; // 'idle' | 'selecting' | 'active'
  let selected = [];
  let hovered = null;
  let isProjectPage = false;
  let selectionIdCounter = 0;

  // UI Elements
  let highlight = null;
  let badge = null;
  let fab = null;
  let scrollHandler = null;
  let resizeHandler = null;

  // Track active highlights to prevent duplicates
  const activeHighlights = new Map();

  // ============================================================
  // CLEANUP - Prevent Duplicates
  // ============================================================

  function cleanup() {
    console.log('[FixOnce] Cleanup triggered');

    // Stop polling
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }

    // Remove all FixOnce elements
    document.querySelectorAll('[id^="__fo_"], [class*="__fo_"]').forEach(el => el.remove());

    // Clear state
    selected = [];
    hovered = null;
    highlight = null;
    badge = null;
    fab = null;
    pickerState = 'idle';
    activeHighlights.clear();

    // Remove event listeners
    if (scrollHandler) {
      window.removeEventListener('scroll', scrollHandler, true);
      scrollHandler = null;
    }
    if (resizeHandler) {
      window.removeEventListener('resize', resizeHandler);
      resizeHandler = null;
    }

    document.removeEventListener('mousemove', onMove, true);
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('keydown', onKey, true);
    document.body.style.cursor = '';

    window.__fixonce_initialized__ = false;
  }

  // Cleanup on navigation
  window.addEventListener('beforeunload', cleanup);
  window.addEventListener('pagehide', cleanup);

  // For SPA navigation
  let lastUrl = location.href;
  const urlObserver = new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      console.log('[FixOnce] URL changed, reinitializing');
      cleanup();
      setTimeout(init, 100);
    }
  });
  urlObserver.observe(document.body, { childList: true, subtree: true });

  // ============================================================
  // SERVER COMMUNICATION
  // ============================================================

  async function findServer() {
    for (const port of SERVER_PORTS) {
      try {
        const response = await fetch(`http://localhost:${port}/api/ping`, {
          method: 'GET',
          signal: AbortSignal.timeout(500)
        });
        if (response.ok) {
          const data = await response.json();
          if (data.service === 'fixonce') {
            serverPort = port;
            return true;
          }
        }
      } catch (e) {}
    }
    return false;
  }

  async function checkProjectUrl() {
    if (!serverPort && !(await findServer())) return false;

    try {
      const response = await fetch(`http://localhost:${serverPort}/api/check-project-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: location.href })
      });
      const data = await response.json();
      return data.belongs_to_project === true;
    } catch (e) {
      return false;
    }
  }

  async function pollHighlights() {
    if (!serverPort || !isProjectPage) return;

    try {
      const response = await fetch(`http://localhost:${serverPort}/api/highlight-element`);
      const data = await response.json();

      if (data.has_highlight) {
        executeHighlight(data.selector, data.message, data.mode, data.duration_ms, {
          requireVisible: data.require_visible === true,
          allowContextOpen: data.allow_context_open !== false
        });
      }
    } catch (e) {}
  }

  // ============================================================
  // AI HIGHLIGHT - With Dedupe
  // ============================================================

  function getHighlightPalette(mode) {
    if (mode === 'working') {
      return {
        border: '2px solid #0ea5a5',
        background: 'rgba(14, 165, 165, 0.08)',
        glow: '0 0 0 3px rgba(14, 165, 165, 0.18), 0 4px 18px rgba(14, 165, 165, 0.22)',
        labelBg: '#0f766e',
        labelColor: '#ecfeff',
        labelText: 'Working on this'
      };
    }
    if (mode === 'done') {
      return {
        border: '2px solid #16a34a',
        background: 'rgba(22, 163, 74, 0.12)',
        glow: '0 0 0 4px rgba(34, 197, 94, 0.22), 0 4px 20px rgba(34, 197, 94, 0.28)',
        labelBg: '#15803d',
        labelColor: '#f0fdf4',
        labelText: 'Done'
      };
    }
    return {
      border: '2px solid #8b5cf6',
      background: 'rgba(139, 92, 246, 0.1)',
      glow: '0 0 0 4px rgba(139, 92, 246, 0.2), 0 4px 20px rgba(139, 92, 246, 0.3)',
      labelBg: '#8b5cf6',
      labelColor: '#fff',
      labelText: 'Selected'
    };
  }

  function removeHighlight(selector) {
    if (!activeHighlights.has(selector)) return;
    const existing = activeHighlights.get(selector);
    if (existing.element && existing.element.parentNode) {
      existing.element.style.opacity = '0';
      setTimeout(() => {
        if (existing.element && existing.element.parentNode) {
          existing.element.remove();
        }
      }, FADE_DURATION);
    }
    if (existing.timer) clearTimeout(existing.timer);
    activeHighlights.delete(selector);
  }

  function isElementVisiblyRenderable(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (parseFloat(style.opacity || '1') < 0.05) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 2 && rect.height > 2;
  }

  function tryOpenUiContext(selector) {
    // Known case: project switcher modal in FixOnce dashboard.
    if (selector && selector.includes('#project-modal')) {
      const modal = document.querySelector('#project-modal');
      if (modal && !modal.classList.contains('show')) {
        const opener = document.querySelector('[onclick*="openProjectSwitcher"]');
        if (opener) {
          opener.click();
          return true;
        }
      }
    }
    return false;
  }

  async function resolveVisibleElement(selector, options = {}) {
    const requireVisible = options.requireVisible === true;
    const allowContextOpen = options.allowContextOpen !== false;

    let el = document.querySelector(selector);
    if (isElementVisiblyRenderable(el)) return el;

    if (requireVisible && !allowContextOpen) return null;

    const contextOpened = allowContextOpen ? tryOpenUiContext(selector) : false;
    if (!contextOpened) return null;

    const timeoutMs = 1500;
    const pollEveryMs = 75;
    const deadline = Date.now() + timeoutMs;

    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, pollEveryMs));
      el = document.querySelector(selector);
      if (isElementVisiblyRenderable(el)) return el;
    }
    return null;
  }

  async function executeHighlight(selector, message, mode, durationMs, options = {}) {
    const resolvedMode = mode || 'ack';

    if (resolvedMode === 'clear') {
      removeHighlight(selector);
      return;
    }

    if (resolvedMode === 'done') {
      if (activeHighlights.has(selector)) {
        removeHighlight(selector);
      }
      // continue with a short success flash
    }

    if (resolvedMode === 'ack' && activeHighlights.has(selector)) {
      removeHighlight(selector);
    }

    // Generate unique ID for this highlight
    const highlightId = `${selector}-${Date.now()}`;

    try {
      const el = await resolveVisibleElement(selector, options);
      if (!el) {
        console.log('[FixOnce] Highlight target not visible/found:', selector);
        return;
      }

      const rect = el.getBoundingClientRect();

      // Create highlight overlay
      const overlay = document.createElement('div');
      overlay.id = '__fo_ai_hl_' + highlightId;
      overlay.className = '__fo_ai_highlight__';
      const palette = getHighlightPalette(resolvedMode);
      Object.assign(overlay.style, {
        position: 'absolute',
        top: (rect.top + window.scrollY - 4) + 'px',
        left: (rect.left + window.scrollX - 4) + 'px',
        width: (rect.width + 8) + 'px',
        height: (rect.height + 8) + 'px',
        border: palette.border,
        borderRadius: '8px',
        background: palette.background,
        boxShadow: palette.glow,
        pointerEvents: 'none',
        zIndex: '2147483646',
        opacity: '0',
        transition: `opacity ${FADE_DURATION}ms ease`
      });

      // Tooltip - consistent template
      if (message || resolvedMode === 'working') {
        const tooltip = document.createElement('div');
        Object.assign(tooltip.style, {
          position: 'absolute',
          top: '-40px',
          left: '50%',
          transform: 'translateX(-50%)',
          padding: '8px 14px',
          background: palette.labelBg,
          color: palette.labelColor,
          borderRadius: '8px',
          fontSize: '13px',
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
          fontWeight: '500',
          whiteSpace: 'nowrap',
          maxWidth: '300px',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          boxShadow: '0 4px 12px rgba(0,0,0,0.25)'
        });
        tooltip.textContent = message || palette.labelText;

        const arrow = document.createElement('div');
        Object.assign(arrow.style, {
          position: 'absolute',
          bottom: '-6px',
          left: '50%',
          transform: 'translateX(-50%)',
          borderLeft: '6px solid transparent',
          borderRight: '6px solid transparent',
          borderTop: `6px solid ${palette.labelBg}`
        });
        tooltip.appendChild(arrow);
        overlay.appendChild(tooltip);
      }

      document.body.appendChild(overlay);
      const entry = { element: overlay, id: highlightId, mode: resolvedMode, timer: null };
      activeHighlights.set(selector, entry);

      // Scroll into view
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });

      // Fade in
      requestAnimationFrame(() => {
        overlay.style.opacity = '1';
      });

      if (resolvedMode === 'working') {
        const maxDuration = (durationMs && durationMs > 0) ? durationMs : WORKING_HIGHLIGHT_MAX_DURATION;
        entry.timer = setTimeout(() => {
          executeHighlight(selector, 'Done', 'done', DONE_HIGHLIGHT_DURATION);
        }, maxDuration);
      } else {
        const flashDuration = (durationMs && durationMs > 0)
          ? durationMs
          : (resolvedMode === 'done' ? DONE_HIGHLIGHT_DURATION : ACK_HIGHLIGHT_DURATION);
        entry.timer = setTimeout(() => removeHighlight(selector), flashDuration);
      }

    } catch (e) {
      console.error('[FixOnce] Highlight error:', e);
    }
  }

  // ============================================================
  // USER ELEMENT PICKING
  // ============================================================

  function generateSelectionId() {
    return `sel_${Date.now()}_${++selectionIdCounter}`;
  }

  function updateMarkerPositions() {
    selected.forEach((s) => {
      if (s.el && s.marker && s.el.isConnected) {
        const rect = s.el.getBoundingClientRect();
        Object.assign(s.marker.style, {
          top: (rect.top + window.scrollY) + 'px',
          left: (rect.left + window.scrollX) + 'px',
          width: rect.width + 'px',
          height: rect.height + 'px'
        });
      }
    });
  }

  function createPickerUI() {
    // Highlight box
    highlight = document.createElement('div');
    highlight.id = '__fo_highlight__';
    Object.assign(highlight.style, {
      position: 'fixed',
      pointerEvents: 'none',
      border: '2px dashed #3b82f6',
      background: 'rgba(59, 130, 246, 0.08)',
      borderRadius: '4px',
      zIndex: '2147483647',
      display: 'none',
      transition: 'all 0.05s ease',
      boxShadow: '0 0 0 4px rgba(59, 130, 246, 0.15)'
    });
    document.body.appendChild(highlight);

    // Badge
    badge = document.createElement('div');
    badge.id = '__fo_badge__';
    Object.assign(badge.style, {
      position: 'fixed',
      bottom: '24px',
      left: '50%',
      transform: 'translateX(-50%)',
      padding: '12px 24px',
      background: 'linear-gradient(135deg, rgba(15,15,15,0.95), rgba(30,30,30,0.95))',
      color: '#fff',
      borderRadius: '12px',
      fontSize: '13px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      zIndex: '2147483647',
      display: 'none',
      boxShadow: '0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.1)',
      backdropFilter: 'blur(10px)'
    });
    document.body.appendChild(badge);

    scrollHandler = () => updateMarkerPositions();
    resizeHandler = () => updateMarkerPositions();
    window.addEventListener('scroll', scrollHandler, true);
    window.addEventListener('resize', resizeHandler);
  }

  function updateBadge() {
    if (!badge) return;
    if (selected.length === 0) {
      badge.innerHTML = `
        <span style="opacity:0.6">🎯</span>
        <span style="margin-left:8px">Click to select</span>
        <span style="margin-left:16px;opacity:0.5">ESC exit</span>
      `;
    } else {
      badge.innerHTML = `
        <span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;background:#22c55e;border-radius:50%;font-size:12px;font-weight:600">${selected.length}</span>
        <span style="margin-left:10px">selected</span>
        <span style="margin-left:16px;opacity:0.6">ESC to exit</span>
      `;
    }
    badge.style.display = 'flex';
    badge.style.alignItems = 'center';
  }

  function createMarker(el, index) {
    const rect = el.getBoundingClientRect();
    const marker = document.createElement('div');
    const markerId = generateSelectionId();
    marker.id = '__fo_marker_' + markerId;
    marker.className = '__fo_marker__';
    marker.dataset.selectionId = markerId;

    Object.assign(marker.style, {
      position: 'absolute',
      top: (rect.top + window.scrollY) + 'px',
      left: (rect.left + window.scrollX) + 'px',
      width: rect.width + 'px',
      height: rect.height + 'px',
      border: '2px solid #22c55e',
      background: 'rgba(34, 197, 94, 0.1)',
      borderRadius: '6px',
      pointerEvents: 'none',
      zIndex: '2147483646',
      boxShadow: '0 0 0 4px rgba(34, 197, 94, 0.15)'
    });

    const num = document.createElement('div');
    Object.assign(num.style, {
      position: 'absolute',
      top: '-14px',
      left: '-14px',
      width: '28px',
      height: '28px',
      background: 'linear-gradient(135deg, #22c55e, #16a34a)',
      color: '#fff',
      borderRadius: '50%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: '13px',
      fontWeight: '600',
      fontFamily: '-apple-system, sans-serif',
      boxShadow: '0 2px 8px rgba(34, 197, 94, 0.4)',
      border: '2px solid #fff'
    });
    num.textContent = index + 1;
    marker.appendChild(num);

    document.body.appendChild(marker);
    return { marker, id: markerId };
  }

  function getSelector(el) {
    if (el.id && !el.id.startsWith('__fo_')) return '#' + el.id;
    let s = el.tagName.toLowerCase();
    if (el.className && typeof el.className === 'string') {
      const cls = el.className.trim().split(/\s+/).filter(c => !c.startsWith('__fo_')).slice(0, 2).join('.');
      if (cls) s += '.' + cls;
    }
    return s;
  }

  function getSelectorPath(el) {
    const path = [];
    let cur = el;
    while (cur && cur !== document.body && path.length < 4) {
      path.unshift(getSelector(cur));
      cur = cur.parentElement;
    }
    return path.join(' > ');
  }

  function capture(el, selectionId) {
    const rect = el.getBoundingClientRect();
    const computed = getComputedStyle(el);
    const cssKeys = ['display', 'position', 'width', 'height', 'color', 'background', 'font-size'];
    const css = {};
    cssKeys.forEach(k => {
      const v = computed.getPropertyValue(k);
      if (v && v !== 'none' && v !== 'auto' && v !== '0px') css[k] = v;
    });

    return {
      id: selectionId,
      selector: getSelectorPath(el),
      tagName: el.tagName.toLowerCase(),
      elementId: el.id || null,
      classes: el.className ? String(el.className).split(/\s+/).filter(c => c && !c.startsWith('__fo_')) : [],
      html: el.outerHTML.substring(0, 1500),
      innerText: (el.innerText || '').substring(0, 150),
      css,
      rect: { width: Math.round(rect.width), height: Math.round(rect.height) },
      url: location.href,
      timestamp: new Date().toISOString()
    };
  }

  function send() {
    const data = selected.map(s => s.data);
    window.postMessage({
      source: 'FIXONCE_PICKER',
      type: 'ELEMENT_SELECTED',
      payload: data,
      multiple: true
    }, '*');
  }

  function onMove(e) {
    if (pickerState !== 'selecting') return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    if (!el || el.id?.startsWith('__fo_') || el.className?.includes?.('__fo_')) return;

    hovered = el;
    const rect = el.getBoundingClientRect();
    Object.assign(highlight.style, {
      display: 'block',
      top: rect.top + 'px',
      left: rect.left + 'px',
      width: rect.width + 'px',
      height: rect.height + 'px'
    });
  }

  function onClick(e) {
    if (pickerState !== 'selecting') return;
    if (e.target.id?.startsWith('__fo_')) return;

    e.preventDefault();
    e.stopPropagation();

    if (!hovered || hovered.id?.startsWith('__fo_')) return;
    if (selected.some(s => s.el === hovered)) return;

    // No permanent marker - just flash green on highlight
    const id = generateSelectionId();
    const data = capture(hovered, id);
    selected.push({ el: hovered, data, marker: null, id });

    // Brief green flash to confirm selection
    highlight.style.borderColor = '#22c55e';
    highlight.style.background = 'rgba(34, 197, 94, 0.15)';
    setTimeout(() => {
      if (highlight) {
        highlight.style.borderColor = '#3b82f6';
        highlight.style.background = 'rgba(59, 130, 246, 0.08)';
      }
    }, 200);

    updateBadge();
    send();
  }

  function onKey(e) {
    if (pickerState !== 'selecting') return;

    if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();

      if (selected.length > 0) {
        send();
        if (badge) {
          badge.innerHTML = `<span style="color:#22c55e">✓</span><span style="margin-left:8px">${selected.length} captured</span>`;
        }
        setTimeout(() => stopPicker(), 300);
      } else {
        stopPicker();
      }
      return;
    }

    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      // ESC exits picker mode entirely (elements remain selected)
      stopPicker();
    }
  }

  function startPicker() {
    if (pickerState === 'selecting') return;
    pickerState = 'selecting';
    selected = [];

    createPickerUI();
    updateBadge();
    updateFabState();

    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', onKey, true);
    document.body.style.cursor = 'crosshair';
  }

  function stopPicker() {
    if (pickerState !== 'selecting') return;
    pickerState = selected.length > 0 ? 'active' : 'idle';

    document.removeEventListener('mousemove', onMove, true);
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('keydown', onKey, true);
    document.body.style.cursor = '';

    if (scrollHandler) {
      window.removeEventListener('scroll', scrollHandler, true);
      scrollHandler = null;
    }
    if (resizeHandler) {
      window.removeEventListener('resize', resizeHandler);
      resizeHandler = null;
    }

    if (highlight) { highlight.remove(); highlight = null; }
    if (badge) { badge.remove(); badge = null; }

    // Always remove markers from screen when exiting picker mode
    // User can manage elements from dashboard
    document.querySelectorAll('.__fo_marker__').forEach(m => m.remove());

    updateFabState();
  }

  // ============================================================
  // FAB - 3 States: Idle / Selecting / Active
  // ============================================================

  function updateFabState() {
    if (!fab) return;

    const svg = fab.querySelector('svg');
    const stateIndicator = fab.querySelector('.__fo_state__');

    if (pickerState === 'idle') {
      svg.style.stroke = '#a1a1aa';
      if (stateIndicator) stateIndicator.remove();
      fab.title = 'FixOnce: Select Elements';
      fab.style.display = 'flex';
    } else if (pickerState === 'selecting') {
      svg.style.stroke = '#3b82f6';
      fab.style.display = 'none';
    } else if (pickerState === 'active') {
      svg.style.stroke = '#22c55e';
      fab.title = `FixOnce: ${selected.length} selected (click to clear)`;
      fab.style.display = 'flex';

      // Add count indicator
      if (!stateIndicator) {
        const indicator = document.createElement('div');
        indicator.className = '__fo_state__';
        Object.assign(indicator.style, {
          position: 'absolute',
          top: '-4px',
          right: '-4px',
          width: '18px',
          height: '18px',
          background: '#22c55e',
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '11px',
          fontWeight: '600',
          color: '#fff',
          border: '2px solid #18181b'
        });
        indicator.textContent = selected.length;
        fab.appendChild(indicator);
      } else {
        stateIndicator.textContent = selected.length;
      }
    }
  }

  function createFAB() {
    if (document.getElementById('__fo_fab__')) return;

    fab = document.createElement('div');
    fab.id = '__fo_fab__';
    fab.title = 'FixOnce: Select Elements';
    Object.assign(fab.style, {
      position: 'fixed',
      bottom: '24px',
      right: '24px',
      width: '48px',
      height: '48px',
      background: 'linear-gradient(135deg, #18181b, #27272a)',
      borderRadius: '14px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer',
      boxShadow: '0 4px 20px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.1)',
      zIndex: '2147483640',
      transition: 'all 0.2s ease',
      userSelect: 'none'
    });

    fab.innerHTML = `
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#a1a1aa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="transition: stroke 0.2s">
        <circle cx="12" cy="12" r="10"/>
        <circle cx="12" cy="12" r="6"/>
        <circle cx="12" cy="12" r="2"/>
      </svg>
    `;

    fab.onmouseenter = () => {
      fab.style.transform = 'scale(1.05)';
      if (pickerState === 'idle') fab.querySelector('svg').style.stroke = '#22c55e';
    };
    fab.onmouseleave = () => {
      fab.style.transform = 'scale(1)';
      if (pickerState === 'idle') fab.querySelector('svg').style.stroke = '#a1a1aa';
    };
    fab.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();

      if (pickerState === 'active') {
        // Clear selections
        document.querySelectorAll('.__fo_marker__').forEach(m => m.remove());
        selected = [];
        pickerState = 'idle';
        window.postMessage({ source: 'FIXONCE_PICKER', type: 'ELEMENT_CLEARED' }, '*');
        updateFabState();
      } else {
        startPicker();
      }
    };

    document.body.appendChild(fab);
  }

  // Listen for activation from bridge
  window.addEventListener('message', e => {
    if (e.source !== window) return;
    if (e.data?.source === 'FIXONCE_PICKER_CONTROL') {
      if (e.data.action === 'ACTIVATE') startPicker();
      if (e.data.action === 'DEACTIVATE') stopPicker();
    }
  });

  // Expose API
  window.__fixonce_picker__ = {
    start: startPicker,
    stop: stopPicker,
    isActive: () => pickerState === 'selecting',
    highlight: executeHighlight,
    getState: () => pickerState,
    getSelected: () => selected.length
  };

  // ============================================================
  // INITIALIZATION
  // ============================================================

  async function init() {
    isProjectPage = await checkProjectUrl();

    if (isProjectPage) {
      console.log('[FixOnce] Project page - enabled');
      createFAB();
      pollInterval = setInterval(pollHighlights, POLL_INTERVAL);
    } else {
      console.log('[FixOnce] Not project page - disabled');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
