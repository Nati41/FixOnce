(function() {
  let errorOccurred = false;

  function sendLog(payload) {
    try {
      errorOccurred = true;
      window.postMessage({
        source: "FIXONCE",
        payload: payload
      }, "*");
    } catch(e) {}
  }

  function sendPageLoadSuccess() {
    try {
      window.postMessage({
        source: "FIXONCE",
        payload: {
          type: "page_load_success",
          url: location.href
        }
      }, "*");
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

  window.addEventListener("load", function() {
    setTimeout(function() {
      if (!errorOccurred) {
        sendPageLoadSuccess();
      }
    }, 5000);
  });

  console.log("%c[FixOnce] Active", "color: #56d364; font-weight: bold;");
})();
