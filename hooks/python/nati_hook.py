"""
FixOnce Python Hook - Rich Context Edition
Never debug the same bug twice.
Captures deep error context: code snippets + local variables
"""

import sys
import traceback
import linecache
import json
import requests
from datetime import datetime

# Configuration
NATI_SERVER = "http://localhost:5000/api/log_error"
ENABLED = True
MAX_VAR_LENGTH = 200
CONTEXT_LINES = 5  # Lines before and after error

_original_excepthook = sys.excepthook


def _safe_repr(value, max_length=MAX_VAR_LENGTH):
    """Safely convert a value to string, truncating if needed."""
    try:
        repr_str = repr(value)
        if len(repr_str) > max_length:
            return repr_str[:max_length] + "... [truncated]"
        return repr_str
    except Exception:
        return "<unrepresentable>"


def _extract_locals(frame):
    """Extract local variables from frame, with safety limits."""
    if not frame:
        return {}

    safe_locals = {}
    try:
        for key, value in frame.f_locals.items():
            # Skip private/magic variables
            if key.startswith('__'):
                continue
            # Skip modules and functions
            if hasattr(value, '__module__') and hasattr(value, '__call__'):
                safe_locals[key] = f"<function {key}>"
                continue
            # Safely convert value
            safe_locals[key] = _safe_repr(value)

        # Limit total number of variables
        if len(safe_locals) > 20:
            keys = list(safe_locals.keys())[:20]
            safe_locals = {k: safe_locals[k] for k in keys}
            safe_locals["__note__"] = "... more variables truncated"

    except Exception as e:
        safe_locals["__error__"] = f"Could not extract locals: {e}"

    return safe_locals


def _extract_code_snippet(filename, lineno):
    """Extract code snippet around the error line."""
    snippet = []

    try:
        start_line = max(1, lineno - CONTEXT_LINES)
        end_line = lineno + CONTEXT_LINES + 1

        for i in range(start_line, end_line):
            line = linecache.getline(filename, i)
            if line:
                # Mark the error line
                marker = ">>>" if i == lineno else "   "
                snippet.append(f"{marker} {i:4d} | {line.rstrip()}")
            elif i == lineno:
                snippet.append(f">>> {i:4d} | <source not available>")

    except Exception as e:
        snippet.append(f"Could not extract code: {e}")

    return snippet


def _get_exception_chain(exc_type, exc_value, exc_tb):
    """Get the full exception chain for chained exceptions."""
    chain = []
    seen = set()

    current = exc_value
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = getattr(current, '__cause__', None) or getattr(current, '__context__', None)

    return chain


def nati_excepthook(exc_type, exc_value, exc_tb):
    """Rich context exception hook for NatiDebugger."""

    # Always call original first
    _original_excepthook(exc_type, exc_value, exc_tb)

    if not ENABLED:
        return

    try:
        # Basic error info
        error_type = exc_type.__name__
        error_message = str(exc_value)

        # Extract file and line from traceback
        filename = ""
        lineno = 0
        func_name = ""

        if exc_tb:
            # Get the deepest frame (actual error location)
            tb = exc_tb
            while tb.tb_next:
                tb = tb.tb_next

            frame = tb.tb_frame
            lineno = tb.tb_lineno
            filename = frame.f_code.co_filename
            func_name = frame.f_code.co_name

            # Extract rich context
            code_snippet = _extract_code_snippet(filename, lineno)
            local_vars = _extract_locals(frame)
        else:
            code_snippet = ["<no traceback available>"]
            local_vars = {}

        # Build full stack trace
        stack_trace = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

        # Build payload with rich context
        payload = {
            "type": f"backend.{error_type}",
            "message": error_message[:500],
            "severity": "critical",
            "file": filename,
            "line": lineno,
            "function": func_name,
            "url": f"python://{filename}",
            "timestamp": datetime.now().isoformat(),

            # Rich context (X-Ray)
            "snippet": code_snippet,
            "locals": local_vars,
            "stack": stack_trace[:2000]
        }

        # Send to NatiDebugger server
        # Use ensure_ascii=False to preserve Hebrew/Unicode strings
        requests.post(
            NATI_SERVER,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json; charset=utf-8'},
            timeout=2
        )

    except Exception:
        # Silent fail - never crash the crash handler
        pass


def install():
    """Install the FixOnce error hook."""
    sys.excepthook = nati_excepthook
    print("[FixOnce] Error hook installed - Never debug the same bug twice")


def uninstall():
    """Restore the original exception hook."""
    sys.excepthook = _original_excepthook
    print("[FixOnce] Hook uninstalled")


# Auto-install when imported (optional)
if __name__ != "__main__":
    # Uncomment the next line for auto-install on import
    # install()
    pass
