// This script is injected directly into the page context
// to intercept console.error and other errors

(function() {
  const SERVER_URL = "http://localhost:5000/log";

  function sendLog(payload) {
    try {
      fetch(SERVER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(function() {});
    } catch(e) {}
  }

  // Intercept console.error
  const originalError = console.error;
  console.error = function(...args) {
    const message = args.map(a =>
      typeof a === "object" ? JSON.stringify(a) : String(a)
    ).join(" ");

    sendLog({
      type: "console.error",
      severity: "error",
      message: message,
      url: location.href,
      timestamp: new Date().toISOString()
    });

    originalError.apply(console, args);
  };

  // Intercept console.warn
  const originalWarn = console.warn;
  console.warn = function(...args) {
    const message = args.map(a =>
      typeof a === "object" ? JSON.stringify(a) : String(a)
    ).join(" ");

    sendLog({
      type: "console.warn",
      severity: "warning",
      message: message,
      url: location.href,
      timestamp: new Date().toISOString()
    });

    originalWarn.apply(console, args);
  };

  // Listen to uncaught errors
  window.addEventListener("error", function(event) {
    sendLog({
      type: "window.onerror",
      severity: "critical",
      message: event.message || String(event),
      source: event.filename || "",
      line: event.lineno || 0,
      column: event.colno || 0,
      url: location.href,
      timestamp: new Date().toISOString()
    });
  });

  // Listen to unhandled promise rejections
  window.addEventListener("unhandledrejection", function(event) {
    const reason = event.reason;
    sendLog({
      type: "unhandledrejection",
      severity: "critical",
      message: reason instanceof Error ? reason.message : String(reason),
      stack: reason instanceof Error ? reason.stack : null,
      url: location.href,
      timestamp: new Date().toISOString()
    });
  });

  console.log("%c[Nati Debugger] Active", "color: #56d364; font-weight: bold;");
})();
