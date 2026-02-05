/**
 * FixOnce Node.js Hook - Production Ready
 * Never debug the same bug twice.
 *
 * Safety features:
 * - Anti-loop guard (prevents recursive error capture)
 * - Rate limiting (max 10 errors per minute)
 * - Non-blocking sends (async with catch)
 * - Graceful degradation (silent fail)
 *
 * Usage:
 *   require('fixonce-hook'); // At the top of your main file
 *   // or
 *   import 'fixonce-hook';
 */

const FIXONCE_SERVER = 'http://localhost:5000/api/log_error';
const MAX_ERRORS_PER_MINUTE = 10;

// Internal state
let isSending = false;
const errorTimestamps = [];
const originalConsoleError = console.error;

/**
 * Rate limit check - returns true if OK to send
 */
function rateLimitCheck() {
    const now = Date.now();

    // Remove timestamps older than 60 seconds
    while (errorTimestamps.length > 0 && (now - errorTimestamps[0]) > 60000) {
        errorTimestamps.shift();
    }

    // Check limit
    if (errorTimestamps.length >= MAX_ERRORS_PER_MINUTE) {
        return false;
    }

    errorTimestamps.push(now);
    return true;
}

/**
 * Send error to FixOnce server (non-blocking)
 */
async function sendError(payload) {
    if (isSending) return; // Anti-loop guard

    isSending = true;

    try {
        // Use dynamic import for fetch in older Node versions
        const fetchFn = globalThis.fetch || (await import('node-fetch')).default;

        await fetchFn(FIXONCE_SERVER, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-FixOnce-Origin': 'node-hook' // Anti-loop marker
            },
            body: JSON.stringify(payload),
            signal: AbortSignal.timeout(2000) // 2 second timeout
        });
    } catch (e) {
        // Silent fail - never crash the app
    } finally {
        isSending = false;
    }
}

/**
 * Extract stack trace info
 */
function extractStackInfo(error) {
    const stack = error?.stack || '';
    const lines = stack.split('\n');

    let file = '';
    let line = 0;
    let func = '';

    // Find first non-internal stack frame
    for (const stackLine of lines.slice(1)) {
        const match = stackLine.match(/at\s+(?:(.+?)\s+\()?(.+?):(\d+):(\d+)\)?/);
        if (match) {
            func = match[1] || '<anonymous>';
            file = match[2] || '';
            line = parseInt(match[3], 10) || 0;

            // Skip node_modules and internal
            if (!file.includes('node_modules') && !file.startsWith('node:')) {
                break;
            }
        }
    }

    return { file, line, func, stack: stack.substring(0, 2000) };
}

/**
 * Intercept console.error
 */
console.error = function (...args) {
    // Always call original first
    originalConsoleError.apply(console, args);

    // Safety checks
    if (isSending || !rateLimitCheck()) {
        return;
    }

    const message = args
        .map(arg => {
            if (arg instanceof Error) return arg.message;
            if (typeof arg === 'object') {
                try { return JSON.stringify(arg); }
                catch { return String(arg); }
            }
            return String(arg);
        })
        .join(' ')
        .substring(0, 500);

    // Extract error info if first arg is Error
    const firstArg = args[0];
    const isError = firstArg instanceof Error;
    const stackInfo = isError ? extractStackInfo(firstArg) : { file: '', line: 0, func: '', stack: '' };

    const payload = {
        type: isError ? `node.${firstArg.name || 'Error'}` : 'node.console.error',
        message,
        severity: 'error',
        file: stackInfo.file,
        line: stackInfo.line,
        function: stackInfo.func,
        stack: stackInfo.stack,
        timestamp: new Date().toISOString(),
        source: 'node-hook'
    };

    // Send asynchronously (fire and forget)
    sendError(payload);
};

/**
 * Handle uncaught exceptions
 */
process.on('uncaughtException', (error, origin) => {
    // Log to original console first
    originalConsoleError('Uncaught Exception:', error);

    if (isSending || !rateLimitCheck()) {
        // Re-throw to crash as expected
        throw error;
    }

    const stackInfo = extractStackInfo(error);

    const payload = {
        type: `node.${error.name || 'Error'}`,
        message: (error.message || String(error)).substring(0, 500),
        severity: 'critical',
        file: stackInfo.file,
        line: stackInfo.line,
        function: stackInfo.func,
        stack: stackInfo.stack,
        timestamp: new Date().toISOString(),
        source: 'node-hook',
        origin: origin
    };

    sendError(payload);

    // Re-throw to let Node crash normally (don't swallow exceptions)
    setTimeout(() => {
        throw error;
    }, 100);
});

/**
 * Handle unhandled promise rejections
 */
process.on('unhandledRejection', (reason, promise) => {
    originalConsoleError('Unhandled Rejection:', reason);

    if (isSending || !rateLimitCheck()) {
        return;
    }

    const error = reason instanceof Error ? reason : new Error(String(reason));
    const stackInfo = extractStackInfo(error);

    const payload = {
        type: `node.UnhandledRejection`,
        message: (error.message || String(reason)).substring(0, 500),
        severity: 'critical',
        file: stackInfo.file,
        line: stackInfo.line,
        function: stackInfo.func,
        stack: stackInfo.stack,
        timestamp: new Date().toISOString(),
        source: 'node-hook'
    };

    sendError(payload);
});

// Signal that hook is installed
console.log('[FixOnce] Node.js hook installed - Never debug the same bug twice');

// Export for manual control
module.exports = {
    disable: () => {
        console.error = originalConsoleError;
        console.log('[FixOnce] Node.js hook disabled');
    },
    setServer: (url) => {
        FIXONCE_SERVER = url;
    }
};
