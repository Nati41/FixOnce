/**
 * FixOnce Picker Bridge (ISOLATED World)
 * Relays element picker messages to background service worker
 */
(function() {
  'use strict';

  // Listen for element selection from picker
  window.addEventListener('message', function(event) {
    if (event.source !== window) return;
    if (event.data?.source !== 'FIXONCE_PICKER') return;

    console.log('[FixOnce Bridge] Received message:', event.data.type);

    if (event.data.type === 'ELEMENT_SELECTED') {
      try {
        chrome.runtime.sendMessage({
          action: 'ELEMENT_SELECTED',
          payload: event.data.payload,
          multiple: event.data.multiple || false
        });
      } catch (e) {
        console.error('[FixOnce Bridge] Failed to send element data:', e);
      }
    }

    if (event.data.type === 'ELEMENT_CLEARED') {
      try {
        chrome.runtime.sendMessage({ action: 'ELEMENT_CLEARED' });
      } catch (e) {
        console.error('[FixOnce Bridge] Failed to clear:', e);
      }
    }
  });

  // Listen for activation command from background/popup
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === 'ACTIVATE_PICKER') {
      window.postMessage({
        source: 'FIXONCE_PICKER_CONTROL',
        action: 'ACTIVATE'
      }, '*');
      sendResponse({ success: true });
    } else if (message.action === 'DEACTIVATE_PICKER') {
      window.postMessage({
        source: 'FIXONCE_PICKER_CONTROL',
        action: 'DEACTIVATE'
      }, '*');
      sendResponse({ success: true });
    }
    return true;
  });

})();
