// FixOnce v3.0 - MAIN world
// Minimal data to fit within limits

(function() {
  const el = document.createElement('div');
  el.id = '__fixonce_data__';
  el.style.display = 'none';

  function send(msg, sev) {
    // Keep only essential data, very short
    if (msg.length > 60) msg = msg.substring(0, 60);
    el.textContent = JSON.stringify({m: msg, s: sev});
  }

  function appendElement() {
    if (document.body && !document.getElementById('__fixonce_data__')) {
      document.body.appendChild(el);
    }
  }

  if (document.body) appendElement();
  else document.addEventListener('DOMContentLoaded', appendElement);

  const _error = console.error;
  console.error = function(...args) {
    const msg = args.map(a => typeof a === "object" ? JSON.stringify(a) : String(a)).join(" ");
    send(msg, "e");
    _error.apply(console, args);
  };

  const _warn = console.warn;
  console.warn = function(...args) {
    const msg = args.map(a => typeof a === "object" ? JSON.stringify(a) : String(a)).join(" ");
    send(msg, "w");
    _warn.apply(console, args);
  };

  window.addEventListener("error", e => send(e.message || "Error", "c"));
  window.addEventListener("unhandledrejection", e => send(e.reason?.message || String(e.reason), "c"));

  console.log("%c[FixOnce] Active v3.0", "color:#56d364;font-weight:bold");
})();
