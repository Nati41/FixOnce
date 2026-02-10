/**
 * FixOnce v1.0 - Bridge (ISOLATED World)
 * Relays messages from MAIN world to background service worker
 */
(function() {
  'use strict';

  window.addEventListener('message', function(event) {
    if (event.source !== window) return;
    if (!event.data || event.data.source !== 'FIXONCE') return;

    const payload = event.data.payload;
    if (!payload) return;

    try {
      chrome.runtime.sendMessage({
        action: 'LOG_ERROR',
        payload: payload
      });
    } catch (e) {
      // Extension context invalidated
    }
  });
})();
