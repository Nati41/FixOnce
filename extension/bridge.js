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
      // Handle page load success (clear old errors)
      if (payload.type === 'page_load_success') {
        chrome.runtime.sendMessage({
          action: 'PAGE_LOAD_SUCCESS',
          payload: payload
        });
        return;
      }

      // Normal error logging
      chrome.runtime.sendMessage({
        action: 'LOG_ERROR',
        payload: payload
      });
    } catch (e) {
      // Extension context invalidated
    }
  });
})();
