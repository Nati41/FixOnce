/**
 * FixOnce v1.0 - Logger (MAIN World)
 * Privacy-first error capture with sanitization
 */
(function() {
  'use strict';

  const MAX_LEN = 5000; // Performance safety
  const FIXONCE_ID = 'FIXONCE_LOG_' + Date.now();

  function sanitize(str) {
    if (typeof str !== 'string') str = String(str);

    // Privacy Sanitization:
    return str
      // Email addresses
      .replace(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g, '[EMAIL]')
      // Bearer tokens
      .replace(/Bearer [a-zA-Z0-9\-\._~+/]+=*/g, '[TOKEN]')
      // Passwords in various formats
      .replace(/password["\s:=]+[^"\s&,}]+/gi, 'password=[REDACTED]')
      // Credit card numbers (13-19 digits)
      .replace(/\b\d{13,19}\b/g, '[CARD]')
      // API keys (must contain both letters AND numbers, 32+ chars)
      .replace(/\b(?=\S*[a-zA-Z])(?=\S*[0-9])[a-zA-Z0-9_-]{32,}\b/g, '[API_KEY]')
      // JWT tokens
      .replace(/eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*/g, '[JWT]');
  }

  function send(type, data) {
    try {
      // Sanitize data first
      let dataStr = JSON.stringify(data);
      dataStr = sanitize(dataStr);
      if (dataStr.length > MAX_LEN) {
        dataStr = dataStr.substring(0, MAX_LEN);
      }

      const payload = {
        type: type,
        message: data.message ? sanitize(String(data.message)).substring(0, 2000) : '',
        severity: data.severity || 'error',
        file: data.file || '',
        line: data.line || '',
        column: data.column || '',
        url: location.href.substring(0, 200),
        timestamp: new Date().toISOString()
      };

      window.postMessage({
        source: 'FIXONCE',
        payload: payload
      }, '*');

    } catch (e) {
      // Silent fail
    }
  }

  // 1. Intercept console.error
  const origError = console.error;
  console.error = function(...args) {
    origError.apply(console, args);
    try {
      const message = args.map(a => {
        if (a instanceof Error) return a.message + '\n' + a.stack;
        if (typeof a === 'object') return JSON.stringify(a);
        return String(a);
      }).join(' ');

      send('console.error', {
        message: sanitize(message),
        severity: 'error'
      });
    } catch (e) {}
  };

  // 2. Intercept console.warn
  const origWarn = console.warn;
  console.warn = function(...args) {
    origWarn.apply(console, args);
    try {
      const message = args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ');
      send('console.warn', {
        message: sanitize(message),
        severity: 'warning'
      });
    } catch (e) {}
  };

  // 3. Uncaught Exceptions
  window.addEventListener('error', function(e) {
    send('window.error', {
      message: sanitize(e.message || 'Unknown error'),
      file: e.filename ? e.filename.substring(0, 100) : '',
      line: e.lineno || 0,
      column: e.colno || 0,
      severity: 'critical'
    });
  });

  // 4. Unhandled Promise Rejections
  window.addEventListener('unhandledrejection', function(e) {
    let message = 'Unknown rejection';
    if (e.reason) {
      if (e.reason instanceof Error) {
        message = e.reason.message;
      } else if (typeof e.reason === 'string') {
        message = e.reason;
      } else {
        try { message = JSON.stringify(e.reason); } catch {}
      }
    }
    send('promise.rejection', {
      message: sanitize(message),
      severity: 'critical'
    });
  });

  // 5. HTTP Errors - Intercept fetch
  const origFetch = window.fetch;
  window.fetch = async function(...args) {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    const method = args[1]?.method || 'GET';

    try {
      const response = await origFetch.apply(this, args);

      // Check for HTTP errors (4xx, 5xx)
      if (response.status >= 400) {
        let errorBody = '';
        try {
          // Clone response to read body without consuming it
          const clone = response.clone();
          errorBody = await clone.text();
          if (errorBody.length > 500) errorBody = errorBody.substring(0, 500) + '...';
        } catch (e) {}

        send('http.error', {
          message: `HTTP ${response.status}: ${method} ${url}`,
          severity: response.status >= 500 ? 'critical' : 'error',
          file: url,
          line: response.status,
          responseBody: sanitize(errorBody)
        });
      }

      return response;
    } catch (err) {
      // Network error (no response at all)
      send('http.network', {
        message: `Network Error: ${method} ${url} - ${err.message}`,
        severity: 'critical',
        file: url
      });
      throw err;
    }
  };

  // 6. HTTP Errors - Intercept XMLHttpRequest
  const origXHROpen = XMLHttpRequest.prototype.open;
  const origXHRSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this._fixonce_method = method;
    this._fixonce_url = url;
    return origXHROpen.apply(this, [method, url, ...rest]);
  };

  XMLHttpRequest.prototype.send = function(...args) {
    this.addEventListener('load', function() {
      if (this.status >= 400) {
        let errorBody = '';
        try {
          errorBody = this.responseText;
          if (errorBody.length > 500) errorBody = errorBody.substring(0, 500) + '...';
        } catch (e) {}

        send('http.error', {
          message: `HTTP ${this.status}: ${this._fixonce_method} ${this._fixonce_url}`,
          severity: this.status >= 500 ? 'critical' : 'error',
          file: this._fixonce_url,
          line: this.status,
          responseBody: sanitize(errorBody)
        });
      }
    });

    this.addEventListener('error', function() {
      send('http.network', {
        message: `Network Error: ${this._fixonce_method} ${this._fixonce_url}`,
        severity: 'critical',
        file: this._fixonce_url
      });
    });

    return origXHRSend.apply(this, args);
  };

  // Signal activation
  console.log('%c[FixOnce] v1.1 Active (HTTP Monitoring)', 'color:#56d364;font-weight:bold;font-size:12px');
})();
