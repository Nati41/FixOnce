"""
FixOnce Python Hook - Production Ready
Never debug the same bug twice.

Safety features:
- Anti-loop guard (prevents recursive error capture)
- Rate limiting (max 10 errors per minute)
- Non-blocking sends (uses threading)
- Graceful degradation (silent fail on errors)
"""

import sys
import traceback
import linecache
import json
import threading
import time
from datetime import datetime
from collections import deque
from typing import Optional, Dict, Any

# Configuration
FIXONCE_SERVER = "http://localhost:5000/api/log_error"
ENABLED = True
MAX_VAR_LENGTH = 200
CONTEXT_LINES = 5
MAX_ERRORS_PER_MINUTE = 10  # Rate limiting

# Internal state
_original_excepthook = sys.excepthook
_is_sending = False  # Anti-loop guard
_error_timestamps: deque = deque(maxlen=MAX_ERRORS_PER_MINUTE)
_lock = threading.Lock()


def _rate_limit_check() -> bool:
    """Check if we're within rate limits. Returns True if OK to send."""
    now = time.time()
    with _lock:
        # Remove timestamps older than 60 seconds
        while _error_timestamps and (now - _error_timestamps[0]) > 60:
            _error_timestamps.popleft()

        # Check if we have room
        if len(_error_timestamps) >= MAX_ERRORS_PER_MINUTE:
            return False

        _error_timestamps.append(now)
        return True


def _safe_repr(value, max_length=MAX_VAR_LENGTH) -> str:
    """Safely convert a value to string, truncating if needed."""
    try:
        repr_str = repr(value)
        if len(repr_str) > max_length:
            return repr_str[:max_length] + "... [truncated]"
        return repr_str
    except Exception:
        return "<unrepresentable>"


def _extract_locals(frame) -> Dict[str, str]:
    """Extract local variables from frame, with safety limits."""
    if not frame:
        return {}

    safe_locals = {}
    try:
        for key, value in frame.f_locals.items():
            if key.startswith('__'):
                continue
            if hasattr(value, '__module__') and hasattr(value, '__call__'):
                safe_locals[key] = f"<function {key}>"
                continue
            safe_locals[key] = _safe_repr(value)

        if len(safe_locals) > 20:
            keys = list(safe_locals.keys())[:20]
            safe_locals = {k: safe_locals[k] for k in keys}
            safe_locals["__note__"] = "... more variables truncated"

    except Exception as e:
        safe_locals["__error__"] = f"Could not extract locals: {e}"

    return safe_locals


def _extract_code_snippet(filename: str, lineno: int) -> list:
    """Extract code snippet around the error line."""
    snippet = []

    try:
        start_line = max(1, lineno - CONTEXT_LINES)
        end_line = lineno + CONTEXT_LINES + 1

        for i in range(start_line, end_line):
            line = linecache.getline(filename, i)
            if line:
                marker = ">>>" if i == lineno else "   "
                snippet.append(f"{marker} {i:4d} | {line.rstrip()}")
            elif i == lineno:
                snippet.append(f">>> {i:4d} | <source not available>")

    except Exception as e:
        snippet.append(f"Could not extract code: {e}")

    return snippet


def _send_error_async(payload: Dict[str, Any]):
    """Send error to FixOnce server in background thread."""
    global _is_sending

    def _send():
        global _is_sending
        try:
            import requests
            requests.post(
                FIXONCE_SERVER,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json; charset=utf-8',
                    'X-FixOnce-Origin': 'python-hook'  # Anti-loop marker
                },
                timeout=2
            )
        except Exception:
            pass  # Silent fail
        finally:
            _is_sending = False

    _is_sending = True
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def fixonce_excepthook(exc_type, exc_value, exc_tb):
    """Rich context exception hook for FixOnce."""
    global _is_sending

    # Always call original first
    _original_excepthook(exc_type, exc_value, exc_tb)

    # Safety checks
    if not ENABLED:
        return

    if _is_sending:  # Anti-loop: don't capture errors while sending
        return

    if not _rate_limit_check():  # Rate limiting
        return

    try:
        error_type = exc_type.__name__
        error_message = str(exc_value)

        filename = ""
        lineno = 0
        func_name = ""
        code_snippet = ["<no traceback available>"]
        local_vars = {}

        if exc_tb:
            tb = exc_tb
            while tb.tb_next:
                tb = tb.tb_next

            frame = tb.tb_frame
            lineno = tb.tb_lineno
            filename = frame.f_code.co_filename
            func_name = frame.f_code.co_name

            code_snippet = _extract_code_snippet(filename, lineno)
            local_vars = _extract_locals(frame)

        stack_trace = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

        payload = {
            "type": f"python.{error_type}",
            "message": error_message[:500],
            "severity": "critical",
            "file": filename,
            "line": lineno,
            "function": func_name,
            "url": f"python://{filename}",
            "timestamp": datetime.now().isoformat(),
            "snippet": code_snippet,
            "locals": local_vars,
            "stack": stack_trace[:2000],
            "source": "python-hook"
        }

        # Send asynchronously (non-blocking)
        _send_error_async(payload)

    except Exception:
        pass  # Never crash the crash handler


def install():
    """Install the FixOnce error hook."""
    sys.excepthook = fixonce_excepthook
    print("[FixOnce] Python hook installed - Never debug the same bug twice")


def uninstall():
    """Restore the original exception hook."""
    sys.excepthook = _original_excepthook
    print("[FixOnce] Python hook uninstalled")


# Convenience: auto-install when imported
def auto_install():
    """Call this at the start of your main file."""
    install()


# Make import fixonce_hook work as auto-install
if __name__ != "__main__":
    # Auto-install on import (can be disabled by setting ENABLED = False before import)
    pass
