"""
MCP Server for FixOnce - V2 (Simplified)

Project ID = Working Directory. That's it.

Phase 0: Thread-safe sessions, no global state leakage.
Phase 1: Boundary detection as single source of truth for project identity.
"""

import sys
import os
import json
import hashlib
import atexit
import signal
import subprocess
import threading
import time
import requests
import contextlib
import functools
import builtins
import copy
import tempfile
import traceback
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import replace
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

from core.windows_subprocess import no_window_creationflags

_MCP_WINDOWS_CTRL_HANDLER = None
_fo_init_trace_local = threading.local()
_FO_INIT_TRACE_STEP = 0
_FO_INIT_TRACE_LOCK = threading.Lock()
_FO_INIT_TRACE_WATCHDOG_INTERVAL_SECONDS = 10


def _log(*args, **kwargs):
    """MCP-safe logging: never write to stdout on stdio transport."""
    kwargs.pop("file", None)
    print(*args, file=sys.stderr, flush=True, **kwargs)


def _mcp_process_event(message: str, include_stack: bool = False):
    """Log MCP process lifecycle diagnostics without polluting stdout."""
    line = f"[{datetime.now().isoformat()}] [MCP-PROCESS] {message}"
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass

    try:
        log_dir = Path.home() / ".fixonce" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "mcp_process_events.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            if include_stack:
                stack_text = "".join(traceback.format_stack())
                handle.write(stack_text + "\n")
    except Exception:
        pass


def _fo_init_trace_file() -> Path:
    path = Path.home() / ".fixonce" / "logs" / "fo_init_trace.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _fo_init_trace_enabled() -> bool:
    return bool(getattr(_fo_init_trace_local, "enabled", False))


def _fo_init_trace(message: str, include_stack: bool = False) -> None:
    if not _fo_init_trace_enabled():
        return

    global _FO_INIT_TRACE_STEP
    try:
        previous_io_disabled = bool(getattr(_fo_init_trace_local, "io_disabled", False))
        _fo_init_trace_local.io_disabled = True
        with _FO_INIT_TRACE_LOCK:
            _FO_INIT_TRACE_STEP += 1
            step = _FO_INIT_TRACE_STEP
        request_id = getattr(_fo_init_trace_local, "request_id", "unknown")
        elapsed = time.monotonic() - getattr(_fo_init_trace_local, "started_at", time.monotonic())
        line = (
            f"[{datetime.now().isoformat()}] "
            f"step={step:04d} request={request_id} elapsed={elapsed:.3f}s "
            f"pid={os.getpid()} thread={threading.get_ident()} {message}"
        )
        with _fo_init_trace_file().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            if include_stack:
                handle.write("".join(traceback.format_stack()))
                handle.write("\n")
    except Exception:
        pass
    finally:
        try:
            _fo_init_trace_local.io_disabled = previous_io_disabled
        except Exception:
            pass


def _fo_init_trace_raw(message: str, include_stack: bool = False) -> None:
    try:
        previous_io_disabled = bool(getattr(_fo_init_trace_local, "io_disabled", False))
        _fo_init_trace_local.io_disabled = True
        line = (
            f"[{datetime.now().isoformat()}] "
            f"pid={os.getpid()} thread={threading.get_ident()} {message}"
        )
        with _fo_init_trace_file().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            if include_stack:
                handle.write("".join(traceback.format_stack()))
                handle.write("\n")
    except Exception:
        pass
    finally:
        try:
            _fo_init_trace_local.io_disabled = previous_io_disabled
        except Exception:
            pass


def _fo_init_io_path(value) -> str:
    try:
        return os.fspath(value)
    except Exception:
        return repr(value)


def _fo_init_should_trace_io(path: str) -> bool:
    if not _fo_init_trace_enabled():
        return False
    if bool(getattr(_fo_init_trace_local, "io_disabled", False)):
        return False
    lowered = str(path).lower()
    return "fo_init_trace.log" not in lowered


class _FoInitIOTraceScope:
    def __init__(self):
        self._orig_open = None
        self._orig_path_open = None
        self._orig_path_read_text = None
        self._orig_path_write_text = None
        self._orig_path_read_bytes = None
        self._orig_path_write_bytes = None
        self._orig_path_exists = None
        self._orig_path_mkdir = None
        self._sqlite3 = None
        self._orig_sqlite_connect = None

    def __enter__(self):
        _fo_init_trace("IO_TRACE_ENABLE_BEFORE builtins.open pathlib sqlite3")
        self._orig_open = builtins.open
        self._orig_path_open = Path.open
        self._orig_path_read_text = Path.read_text
        self._orig_path_write_text = Path.write_text
        self._orig_path_read_bytes = Path.read_bytes
        self._orig_path_write_bytes = Path.write_bytes
        self._orig_path_exists = Path.exists
        self._orig_path_mkdir = Path.mkdir

        def traced_open(file, mode="r", *args, **kwargs):
            path = _fo_init_io_path(file)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_OPEN_BEFORE builtins.open path={path!r} mode={mode!r}")
            handle = self._orig_open(file, mode, *args, **kwargs)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_OPEN_AFTER builtins.open path={path!r} mode={mode!r}")
            return handle

        def traced_path_open(path_self, *args, **kwargs):
            path = _fo_init_io_path(path_self)
            mode = args[0] if args else kwargs.get("mode", "r")
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_OPEN_BEFORE Path.open path={path!r} mode={mode!r}")
            handle = self._orig_path_open(path_self, *args, **kwargs)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_OPEN_AFTER Path.open path={path!r} mode={mode!r}")
            return handle

        def traced_read_text(path_self, *args, **kwargs):
            path = _fo_init_io_path(path_self)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_READ_TEXT_BEFORE path={path!r}")
            value = self._orig_path_read_text(path_self, *args, **kwargs)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_READ_TEXT_AFTER path={path!r} length={len(value)}")
            return value

        def traced_write_text(path_self, data, *args, **kwargs):
            path = _fo_init_io_path(path_self)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_WRITE_TEXT_BEFORE path={path!r} length={len(data) if hasattr(data, '__len__') else 'unknown'}")
            result = self._orig_path_write_text(path_self, data, *args, **kwargs)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_WRITE_TEXT_AFTER path={path!r} result={result}")
            return result

        def traced_read_bytes(path_self, *args, **kwargs):
            path = _fo_init_io_path(path_self)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_READ_BYTES_BEFORE path={path!r}")
            value = self._orig_path_read_bytes(path_self, *args, **kwargs)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_READ_BYTES_AFTER path={path!r} length={len(value)}")
            return value

        def traced_write_bytes(path_self, data, *args, **kwargs):
            path = _fo_init_io_path(path_self)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_WRITE_BYTES_BEFORE path={path!r} length={len(data) if hasattr(data, '__len__') else 'unknown'}")
            result = self._orig_path_write_bytes(path_self, data, *args, **kwargs)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_WRITE_BYTES_AFTER path={path!r} result={result}")
            return result

        def traced_exists(path_self):
            path = _fo_init_io_path(path_self)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_EXISTS_BEFORE path={path!r}")
            result = self._orig_path_exists(path_self)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_EXISTS_AFTER path={path!r} result={result}")
            return result

        def traced_mkdir(path_self, *args, **kwargs):
            path = _fo_init_io_path(path_self)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_MKDIR_BEFORE path={path!r} args={args!r} kwargs={kwargs!r}")
            result = self._orig_path_mkdir(path_self, *args, **kwargs)
            if _fo_init_should_trace_io(path):
                _fo_init_trace(f"FS_MKDIR_AFTER path={path!r}")
            return result

        builtins.open = traced_open
        Path.open = traced_path_open
        Path.read_text = traced_read_text
        Path.write_text = traced_write_text
        Path.read_bytes = traced_read_bytes
        Path.write_bytes = traced_write_bytes
        Path.exists = traced_exists
        Path.mkdir = traced_mkdir

        try:
            import sqlite3
            self._sqlite3 = sqlite3
            self._orig_sqlite_connect = sqlite3.connect

            def traced_sqlite_connect(database, *args, **kwargs):
                path = _fo_init_io_path(database)
                _fo_init_trace(
                    f"SQLITE_CONNECT_BEFORE database={path!r} "
                    f"timeout={kwargs.get('timeout', args[0] if args else 'default')!r}"
                )
                conn = self._orig_sqlite_connect(database, *args, **kwargs)
                _fo_init_trace(f"SQLITE_CONNECT_AFTER database={path!r}")
                return conn

            sqlite3.connect = traced_sqlite_connect
            _fo_init_trace("VECTOR_DB_TRACE_ENABLED sqlite3.connect patched")
        except Exception as exc:
            _fo_init_trace(f"VECTOR_DB_TRACE_ENABLE_ERROR {type(exc).__name__}: {exc}", include_stack=True)

        _fo_init_trace("IO_TRACE_ENABLE_AFTER")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            builtins.open = self._orig_open
            Path.open = self._orig_path_open
            Path.read_text = self._orig_path_read_text
            Path.write_text = self._orig_path_write_text
            Path.read_bytes = self._orig_path_read_bytes
            Path.write_bytes = self._orig_path_write_bytes
            Path.exists = self._orig_path_exists
            Path.mkdir = self._orig_path_mkdir
            if self._sqlite3 is not None and self._orig_sqlite_connect is not None:
                self._sqlite3.connect = self._orig_sqlite_connect
            _fo_init_trace("IO_TRACE_DISABLE_AFTER")
        except Exception as restore_exc:
            _fo_init_trace(f"IO_TRACE_DISABLE_ERROR {type(restore_exc).__name__}: {restore_exc}", include_stack=True)
        return False


class _FoInitTraceScope:
    def __init__(self, cwd: str):
        self.cwd = cwd
        self.previous_enabled = False
        self.previous_request_id = None
        self.previous_started_at = None
        self.request_id = f"{os.getpid()}-{int(time.time() * 1000)}-{threading.get_ident()}"
        self.thread_id = threading.get_ident()
        self.done = threading.Event()
        self.io_scope = None

    def __enter__(self):
        self.previous_enabled = bool(getattr(_fo_init_trace_local, "enabled", False))
        self.previous_request_id = getattr(_fo_init_trace_local, "request_id", None)
        self.previous_started_at = getattr(_fo_init_trace_local, "started_at", None)
        self.started_at = time.monotonic()
        _fo_init_trace_local.enabled = True
        _fo_init_trace_local.request_id = self.request_id
        _fo_init_trace_local.started_at = self.started_at
        _fo_init_trace(f"FO_INIT_REQUEST_RECEIVED cwd={self.cwd!r}", include_stack=True)
        self.io_scope = _FoInitIOTraceScope()
        self.io_scope.__enter__()
        watchdog = threading.Thread(
            target=self._watchdog,
            name="fo-init-trace-watchdog",
            daemon=True,
        )
        watchdog.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            _fo_init_trace("FO_INIT_SCOPE_EXIT_OK")
        else:
            _fo_init_trace(f"FO_INIT_SCOPE_EXIT_ERROR {exc_type.__name__}: {exc}", include_stack=True)
        if self.io_scope is not None:
            self.io_scope.__exit__(exc_type, exc, tb)
        self.done.set()
        _fo_init_trace_local.enabled = self.previous_enabled
        _fo_init_trace_local.request_id = self.previous_request_id
        _fo_init_trace_local.started_at = self.previous_started_at
        return False

    def _watchdog(self):
        while not self.done.wait(_FO_INIT_TRACE_WATCHDOG_INTERVAL_SECONDS):
            try:
                frame = sys._current_frames().get(self.thread_id)
                with _fo_init_trace_file().open("a", encoding="utf-8") as handle:
                    elapsed = time.monotonic() - self.started_at
                    handle.write(
                        f"[{datetime.now().isoformat()}] "
                        f"request={self.request_id} elapsed={elapsed:.3f}s "
                        f"pid={os.getpid()} thread={self.thread_id} FO_INIT_WATCHDOG_STACK\n"
                    )
                    if frame is not None:
                        handle.write("".join(traceback.format_stack(frame)))
                    else:
                        handle.write("watchdog could not locate target thread frame\n")
                    handle.write("\n")
            except Exception:
                pass


class _FoInitStdoutTraceProxy:
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def write(self, data):
        result = self._wrapped.write(data)
        try:
            if data:
                preview = str(data).replace("\r", "\\r").replace("\n", "\\n")[:160]
                line = (
                    f"[{datetime.now().isoformat()}] "
                    f"pid={os.getpid()} thread={threading.get_ident()} "
                    f"JSON_RPC_STDOUT_WRITE len={len(data)} preview={preview!r}"
                )
                with _fo_init_trace_file().open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception:
            pass
        return result

    def flush(self):
        result = self._wrapped.flush()
        try:
            line = (
                f"[{datetime.now().isoformat()}] "
                f"pid={os.getpid()} thread={threading.get_ident()} JSON_RPC_STDOUT_FLUSH"
            )
            with _fo_init_trace_file().open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass
        return result

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def _mcp_process_identity(label: str):
    parent_cmd = _get_windows_parent_command_line(os.getppid()) if sys.platform == "win32" else ""
    _mcp_process_event(
        f"{label}: pid={os.getpid()} ppid={os.getppid()} platform={sys.platform} "
        f"executable={sys.executable!r} argv={sys.argv!r} cwd={os.getcwd()!r} "
        f"file={Path(__file__).resolve()}"
    )
    if parent_cmd:
        _mcp_process_event(f"{label}: parent_command={parent_cmd}")


def _get_windows_parent_command_line(ppid: int) -> str:
    if not ppid:
        return ""
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(ppid)}\").CommandLine",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=no_window_creationflags(),
        )
        if result.returncode == 0:
            return (result.stdout or "").strip()
        return f"<parent lookup failed rc={result.returncode}: {(result.stderr or '').strip()}>"
    except Exception as exc:
        return f"<parent lookup failed {type(exc).__name__}: {exc}>"


def _install_mcp_process_event_probes():
    if threading.current_thread() is threading.main_thread():
        _install_mcp_signal_probe(signal.SIGINT, "SIGINT")
        sigbreak = getattr(signal, "SIGBREAK", None)
        if sigbreak is not None:
            _install_mcp_signal_probe(sigbreak, "SIGBREAK")
    else:
        _mcp_process_event("signal probes skipped: not main thread")
    _install_mcp_windows_console_ctrl_probe()
    atexit.register(lambda: _mcp_process_event("atexit cleanup reached"))


def _install_mcp_signal_probe(signum, name: str):
    current = signal.getsignal(signum)
    if getattr(current, "_fixonce_mcp_probe", False):
        return

    def traced_signal_handler(received_signum, frame):
        _mcp_process_event(
            f"{name} RECEIVED signum={received_signum} thread={threading.current_thread().name}",
            include_stack=False,
        )
        if frame is not None:
            try:
                stack_text = "".join(traceback.format_stack(frame))
                _mcp_process_event(f"{name} stack:\n{stack_text}")
            except Exception:
                pass

        previous = traced_signal_handler._previous_handler
        if previous in (None, signal.SIG_DFL):
            raise KeyboardInterrupt
        if previous == signal.SIG_IGN:
            return None
        if callable(previous):
            return previous(received_signum, frame)
        raise KeyboardInterrupt

    traced_signal_handler._fixonce_mcp_probe = True
    traced_signal_handler._previous_handler = current
    signal.signal(signum, traced_signal_handler)


def _install_mcp_windows_console_ctrl_probe():
    global _MCP_WINDOWS_CTRL_HANDLER
    if sys.platform != "win32" or _MCP_WINDOWS_CTRL_HANDLER is not None:
        return

    try:
        import ctypes

        event_names = {
            0: "CTRL_C_EVENT",
            1: "CTRL_BREAK_EVENT",
            2: "CTRL_CLOSE_EVENT",
            5: "CTRL_LOGOFF_EVENT",
            6: "CTRL_SHUTDOWN_EVENT",
        }
        handler_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

        def console_handler(ctrl_type):
            event_name = event_names.get(ctrl_type, ctrl_type)
            _mcp_process_event(
                f"Windows console control event {event_name} received "
                f"thread={threading.current_thread().name}",
                include_stack=True,
            )
            return False

        _MCP_WINDOWS_CTRL_HANDLER = handler_type(console_handler)
        ok = ctypes.windll.kernel32.SetConsoleCtrlHandler(_MCP_WINDOWS_CTRL_HANDLER, True)
        _mcp_process_event(f"SetConsoleCtrlHandler installed ok={bool(ok)}")
    except BaseException as exc:
        _mcp_process_event(f"SetConsoleCtrlHandler install failed {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Port Synchronization - Use canonical port from runtime.json
# ---------------------------------------------------------------------------
_cached_api_url = None
_api_url_cache_time = 0

def _get_api_url() -> str:
    """
    Get the canonical API URL from runtime.json.

    SINGLE SOURCE OF TRUTH: ~/.fixonce/runtime.json
    Falls back to 5000 if runtime file doesn't exist.
    Caches for 5 seconds to avoid excessive file reads.
    """
    global _cached_api_url, _api_url_cache_time
    import time

    now = time.time()
    if _cached_api_url and (now - _api_url_cache_time) < 5:
        _fo_init_trace(f"_get_api_url cache_hit url={_cached_api_url!r}")
        return _cached_api_url

    try:
        runtime_file = Path.home() / ".fixonce" / "runtime.json"
        _fo_init_trace(f"_get_api_url runtime_exists_check path={runtime_file}")
        if runtime_file.exists():
            _fo_init_trace(f"_get_api_url runtime_read_before path={runtime_file}")
            with open(runtime_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            _fo_init_trace(f"_get_api_url runtime_read_after path={runtime_file}")
            port = state.get("port", 5000)
            _cached_api_url = f"http://localhost:{port}"
            _api_url_cache_time = now
            _fo_init_trace(f"_get_api_url resolved_from_runtime url={_cached_api_url!r}")
            return _cached_api_url
    except Exception as exc:
        _fo_init_trace(f"_get_api_url runtime_error {type(exc).__name__}: {exc}", include_stack=True)
        pass

    # Fallback to default port
    _cached_api_url = "http://localhost:5000"
    _api_url_cache_time = now
    _fo_init_trace(f"_get_api_url fallback url={_cached_api_url!r}")
    return _cached_api_url


def _debug_log(message: str):
    """
    Write debug message to user-specific log file.
    Uses ~/.fixonce/mcp_debug.log to avoid permission issues with /tmp.
    Silently fails if can't write - debug logs are non-critical.
    """
    try:
        log_dir = Path.home() / ".fixonce"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "mcp_debug.log"
        with open(log_file, "a", encoding='utf-8') as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass  # Silent fail - debug logs are non-critical


# Safe File Operations (auto-backup, atomic writes)
_safe_file_available = False
try:
    from core.safe_file import atomic_json_write, atomic_json_read, atomic_json_update
    from core.durable_memory import (
        apply_new_record_defaults,
        durable_memory_write,
        merge_concurrent_value,
    )
    _safe_file_available = True
except ImportError:
    pass  # Safe file not available, will use regular json

# Semantic Search Integration
_semantic_available: Optional[bool] = None
_semantic_imports: Dict[str, Any] = {}


def _load_project_semantic(allow_cold_start: bool = True) -> Optional[Dict[str, Any]]:
    """Load semantic search lazily so MCP stdio startup stays lightweight."""
    global _semantic_available, _semantic_imports
    if _semantic_available is False:
        return None
    if _semantic_available is True:
        return _semantic_imports
    if not allow_cold_start:
        return None

    try:
        from core.project_semantic import (
            index_insight,
            index_decision,
            index_avoid,
            search_project,
            rebuild_project_index,
        )
    except ImportError:
        _semantic_available = False
        _semantic_imports = {}
        _log("[FixOnce] Semantic search not available")
        return None

    _semantic_imports = {
        "index_insight": index_insight,
        "index_decision": index_decision,
        "index_avoid": index_avoid,
        "search_project": search_project,
        "rebuild_project_index": rebuild_project_index,
    }
    _semantic_available = True
    _log("[FixOnce] Semantic search loaded lazily")
    return _semantic_imports

# Session Registry for Multi-AI Isolation - imported later after sys.path is set
_session_registry_available = False

# Policy Enforcement Engine - imported later after sys.path is set
_policy_available = False
_policy_error = None

# ============================================================
# SESSION INITIALIZATION ENFORCEMENT
# ============================================================
# Track if explicit session init was called this session.
# If not, non-init tools are blocked with a hard error.
# This works for ALL AI clients (Claude, Cursor, Codex, etc.)

_session_initialized = False
_session_init_lock = threading.Lock()


def _mark_session_initialized():
    """Mark that the public session init flow completed."""
    global _session_initialized
    with _session_init_lock:
        _session_initialized = True


def _is_session_initialized() -> bool:
    """Check if session was initialized."""
    with _session_init_lock:
        return _session_initialized


def _get_init_reminder() -> str:
    """Get reminder message if session not initialized."""
    if _is_session_initialized():
        return ""
    return """
⚠️ **FixOnce Not Connected!**

Start with `fo_init(cwd="/path/to/project")` to connect this session to your project.
That loads the saved context, decisions, and next step.

"""


def _get_init_enforcement_error() -> str:
    """Get hard-blocking error for tools used before explicit session init."""
    return """Error: FixOnce session not initialized.

Action denied. You must call `fo_init(cwd="/path/to/project")` before using any other FixOnce tool.

This is mandatory enforcement mode. FixOnce will not allow work to proceed without
an explicit project connection for the current session."""


def _get_parent_process_command() -> str:
    """Return the parent command when the platform exposes a safe process probe."""
    if os.name == "nt":
        return ""

    try:
        ppid = os.getppid()
        result = subprocess.run(
            ['ps', '-p', str(ppid), '-o', 'command='],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            return result.stdout.strip().lower()
    except Exception:
        pass

    return ""


def _detect_editor_with_confidence() -> tuple:
    """
    Detect which editor/AI is running this MCP server.
    Returns: (editor_name, detection_source, confidence)
    - confidence: 1.0 = certain, 0.7 = high, 0.5 = medium, 0.3 = low, 0.0 = unknown
    """
    # Priority 0: Check for Codex CLI (OpenAI) - HIGH confidence
    if any(key.startswith("CODEX_") for key in os.environ):
        return ("codex", "env_var", 1.0)

    codex_home = os.environ.get("CODEX_HOME", "")
    if codex_home:
        return ("codex", "env_var", 1.0)

    parent_cmd = _get_parent_process_command()
    if 'codex' in parent_cmd:
        return ("codex", "parent_process", 0.9)
    if 'fastmcp' in parent_cmd:
        return ("codex", "parent_process", 0.7)

    # Priority 1: Check Cursor env vars - HIGH confidence
    cursor_channel = os.environ.get("CURSOR_CHANNEL", "")
    if cursor_channel:
        return ("cursor", "env_var", 1.0)

    for key in os.environ:
        if key.startswith("CURSOR_"):
            return ("cursor", "env_var", 0.9)

    term_program = os.environ.get("TERM_PROGRAM", "")
    if "cursor" in term_program.lower():
        return ("cursor", "term_program", 0.8)

    # Priority 1b: Check Windsurf env vars / host process
    for key in os.environ:
        if key.startswith("WINDSURF_"):
            return ("windsurf", "env_var", 0.9)

    if 'windsurf' in parent_cmd:
        return ("windsurf", "parent_process", 0.9)

    # Priority 2: Check VS Code
    vscode_pid = os.environ.get("VSCODE_PID", "")
    if vscode_pid:
        try:
            result = subprocess.run(['ps', '-p', vscode_pid, '-o', 'comm='],
                                  capture_output=True, text=True, timeout=1)
            proc_name = result.stdout.strip().lower()
            if 'cursor' in proc_name:
                return ("cursor", "vscode_pid_check", 0.8)
        except:
            pass
        return ("vscode", "env_var", 0.9)

    # Priority 3: Check parent process for Claude Code - HIGH confidence
    if 'claude' in parent_cmd:
        return ("claude", "parent_process", 0.9)

    # Priority 4: Check config files - MEDIUM confidence (heuristic)
    home = Path.home()
    claude_settings = home / ".claude" / "settings.json"
    cursor_config = home / ".cursor" / "mcp.json"
    windsurf_config = home / ".codeium" / "windsurf" / "mcp_config.json"

    if claude_settings.exists():
        try:
            settings_mtime = claude_settings.stat().st_mtime
            import time
            if time.time() - settings_mtime < 3600:
                return ("claude", "config_file", 0.5)
        except:
            pass

    if cursor_config.exists():
        return ("cursor", "config_file", 0.3)

    if windsurf_config.exists():
        return ("windsurf", "config_file", 0.3)

    return ("unknown", "none", 0.0)


def _detect_editor() -> str:
    """Detect which editor/AI is running this MCP server. Returns name only."""
    editor, _, _ = _detect_editor_with_confidence()
    return editor


def _resolve_actor_identity() -> Dict[str, Any]:
    """
    Resolve actor identity for this MCP call with provenance metadata.

    Priority:
    1. Explicit client-provided actor env vars (confidence: 1.0)
    2. Runtime environment detection (confidence from detector)
    """
    allowed = {"codex", "claude", "cursor", "vscode", "windsurf"}

    # Priority 1: Explicit client-provided actor
    explicit_actor = (
        os.environ.get("FIXONCE_ACTOR", "")
        or os.environ.get("MCP_CLIENT_ACTOR", "")
        or os.environ.get("FIXONCE_EDITOR", "")
    ).strip().lower()

    if explicit_actor in allowed:
        return {
            "editor": explicit_actor,
            "source": "client_actor",
            "confidence": 1.0,
        }

    # Priority 2: Runtime detection with actual confidence
    editor, source, confidence = _detect_editor_with_confidence()
    if editor in allowed:
        return {
            "editor": editor,
            "source": source,
            "confidence": confidence,
        }

    return {
        "editor": "unknown",
        "source": "none",
        "confidence": 0.0,
    }

# Add src directory to path
SRC_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SRC_DIR))

from fastmcp import FastMCP
from core.agent_context import AgentContext, classify_agent_intent
from core.conflict_lifecycle import (
    bound_conflicts,
    resolve_decision_conflicts,
    upsert_decision_conflicts,
)
from core.system_mode import get_system_mode, MODE_FULL, MODE_PASSIVE, MODE_OFF

_agent_intervention_available = False
try:
    from core.agent_intervention import evaluate_agent_intervention
    from core.agent_audit import get_agent_audit
    _agent_intervention_available = True
    _log("[FixOnce] Agent intervention bridge loaded successfully")
except ImportError as e:
    _log(f"[FixOnce] Agent intervention bridge not available: {e}")

# Policy Enforcement Engine - must be after sys.path is set
try:
    from core.policy_engine import (
        detect_conflicts, validate_decision, check_blocked_components,
        supersede_decision as do_supersede, get_active_decisions, format_policy_status
    )
    _policy_available = True
    _log("[FixOnce] Policy engine loaded successfully")
except ImportError as e:
    _policy_error = str(e)
    _log(f"[FixOnce] Policy engine not available: {e}")

# Stage 7 Intervention Policy - isolated gate wiring
_intervention_policy_available = False
try:
    from core.intervention_policy import (
        InterventionContext,
        evaluate_decision_conflict_gate,
        evaluate_completion_gate,
        evaluate_error_gate,
        evaluate_repeat_bug_gate,
        evaluate_risk_gate,
    )
    _intervention_policy_available = True
    _log("[FixOnce] Intervention policy loaded successfully")
except ImportError as e:
    _log(f"[FixOnce] Intervention policy not available: {e}")

# Session Registry for Multi-AI Isolation - must be after sys.path is set
try:
    from core.session_registry import get_registry, get_or_create_session
    _session_registry_available = True
    _log("[FixOnce] Session registry loaded successfully")
except ImportError as e:
    _log(f"[FixOnce] Session registry not available: {e}")

# Resume State - persistent work state across sessions
_resume_state_available = False
try:
    from core.resume_state import (
        save_resume_state as _save_resume_state,
        get_resume_state as _get_resume_state,
        clear_resume_state as _clear_resume_state,
        format_resume_for_init
    )
    _resume_state_available = True
    _log("[FixOnce] Resume state loaded successfully")
except ImportError as e:
    _log(f"[FixOnce] Resume state not available: {e}")

# Resume Context - structured context builder for session opening
_resume_context_available = False
try:
    from core.resume_context import (
        build_resume_context,
        build_suggested_opening,
        build_new_project_opening
    )
    _resume_context_available = True
    _log("[FixOnce] Resume context loaded successfully")
except ImportError as e:
    _log(f"[FixOnce] Resume context not available: {e}")

# Phase 0: Project isolation - central project context
from core.project_context import ProjectContext, resolve_project_id

# Phase 1: Boundary detection imports
try:
    from core.boundary_detector import (
        find_project_root,
        detect_boundary_violation,
        handle_boundary_transition,
        is_within_boundary,
        BoundaryEvent
    )
    BOUNDARY_DETECTION_ENABLED = True
except ImportError as e:
    BOUNDARY_DETECTION_ENABLED = False
    _log(f"[MCP] Boundary detection not available: {e}")

# ===========================================================================
# MULTI-USER DATA PATHS
# All user data goes to ~/.fixonce/ - NEVER to installation directory
# ===========================================================================
def _get_user_data_dir() -> Path:
    """Get user-specific data directory (~/.fixonce/)."""
    override = os.environ.get("FIXONCE_USER_DATA_DIR", "").strip()
    user_dir = Path(override).expanduser() if override else Path.home() / ".fixonce"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir

USER_DATA_DIR = _get_user_data_dir()

# Data directory for projects - USER SPECIFIC
DATA_DIR = USER_DATA_DIR / "projects_v2"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Project index file - USER SPECIFIC
INDEX_FILE = USER_DATA_DIR / "project_index.json"

# Global on/off toggle - USER SPECIFIC
ENABLED_FLAG_FILE = USER_DATA_DIR / "fixonce_enabled.json"

# Installation data directory (for reading templates only)
INSTALL_DATA_DIR = SRC_DIR.parent / "data"


def _is_fixonce_enabled() -> bool:
    """Legacy boolean compatibility: enabled unless mode is OFF."""
    try:
        return _get_fixonce_mode() != MODE_OFF
    except Exception:
        return True


def _get_fixonce_mode() -> str:
    """Get global FixOnce mode (full/passive/off)."""
    try:
        return (get_system_mode().get("mode") or MODE_FULL).lower()
    except Exception:
        return MODE_FULL


# ============================================================
# PHASE 0: Thread-Local Session (No Global State)
# ============================================================

_session_local = threading.local()


class SessionContext:
    """Thread-safe session context with protocol compliance tracking."""

    def __init__(self, project_id: str = None, working_dir: str = None):
        self.project_id = project_id
        self.working_dir = working_dir
        # Protocol compliance tracking
        self.initialized_at = None
        self.decisions_displayed = False
        self.goal_updated = False
        self.search_performed = False
        self.component_updated = False
        self.decision_logged = False
        self.tool_calls = []

    def __repr__(self):
        return f"SessionContext(project_id={self.project_id})"

    def is_active(self) -> bool:
        return self.project_id is not None

    def mark_initialized(self):
        self.initialized_at = datetime.now().isoformat()

    def mark_decisions_displayed(self):
        self.decisions_displayed = True

    def mark_goal_updated(self):
        self.goal_updated = True

    def mark_search_performed(self):
        self.search_performed = True

    def mark_component_updated(self):
        self.component_updated = True

    def mark_decision_logged(self):
        self.decision_logged = True

    def log_tool_call(self, tool_name: str):
        self.tool_calls.append({
            "tool": tool_name,
            "timestamp": datetime.now().isoformat()
        })
        # Prevent unbounded memory growth - keep last 100 calls
        if len(self.tool_calls) > 100:
            self.tool_calls = self.tool_calls[-100:]
        # Track specific tool calls for compliance
        if tool_name == "search_past_solutions":
            self.search_performed = True
        elif tool_name == "update_component_status":
            self.component_updated = True
        elif tool_name == "log_decision":
            self.decision_logged = True

    def get_compliance_status(self) -> dict:
        """Get protocol compliance status for dashboard."""
        return {
            "session_initialized": self.is_active(),
            "initialized_at": self.initialized_at,
            "decisions_displayed": self.decisions_displayed,
            "goal_updated": self.goal_updated,
            "search_performed": self.search_performed,
            "component_updated": self.component_updated,
            "decision_logged": self.decision_logged,
            "tool_calls_count": len(self.tool_calls),
            "last_tool": self.tool_calls[-1] if self.tool_calls else None
        }

    def get_compliance_score(self) -> dict:
        """Calculate compliance score with detailed breakdown."""
        goal_gate = _evaluate_current_completion_gate(
            tool_name="get_protocol_compliance",
            significant_work_completed=True,
            sync_recorded=self.goal_updated,
        )

        rules = [
            {"id": "session_init", "name": "Session initialized", "passed": self.is_active(), "required": True},
            {"id": "goal_updated", "name": "Goal updated", "passed": goal_gate.level == "silent", "required": True},
        ]
        advisory = [
            {
                "id": "search_first",
                "name": "Search before debug",
                "active": self.search_performed,
                "scope": "debugging only",
            },
            {
                "id": "component_status",
                "name": "Component status update",
                "active": self.component_updated,
                "scope": "meaningful component changes only",
            },
        ]

        # Calculate score (required rules count double)
        total_weight = 0
        earned_weight = 0
        for rule in rules:
            weight = 2 if rule["required"] else 1
            total_weight += weight
            if rule["passed"]:
                earned_weight += weight

        score = int((earned_weight / total_weight) * 100) if total_weight > 0 else 0

        return {
            "score": score,
            "rules": rules,
            "advisory": advisory,
            "passed": sum(1 for r in rules if r["passed"]),
            "total": len(rules),
            "tool_calls": len(self.tool_calls)
        }


# Protocol compliance state (shared across threads for dashboard)
_compliance_state = {
    "last_session_init": None,
    "violations": [],
    "editor": None,
    "session_active": False,
    "initialized_at": None,
    "project_id": None
}


# Session persistence files - USER SPECIFIC
SESSION_FILE = USER_DATA_DIR / "mcp_session.json"
COMPLIANCE_FILE = USER_DATA_DIR / "mcp_compliance.json"
AI_CONNECTIONS_FILE = USER_DATA_DIR / "ai_connections.json"
_project_load_state = threading.local()


def _persist_compliance():
    """Save compliance state to file for Flask API access."""
    try:
        with open(COMPLIANCE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_compliance_state, f, ensure_ascii=False)
    except Exception:
        pass


def _load_compliance() -> dict:
    """Load compliance state from file."""
    try:
        if COMPLIANCE_FILE.exists():
            with open(COMPLIANCE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _persist_session(project_id: str, working_dir: str):
    """Save current session to file for recovery after restart."""
    try:
        _fo_init_trace(f"FS_WRITE_BEFORE _persist_session path={SESSION_FILE}")
        data = {
            "project_id": project_id,
            "working_dir": working_dir,
            "timestamp": datetime.now().isoformat()
        }
        with open(SESSION_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        _fo_init_trace(f"FS_WRITE_AFTER _persist_session path={SESSION_FILE}")
    except Exception as exc:
        _fo_init_trace(f"_persist_session error {type(exc).__name__}: {exc}", include_stack=True)
        pass


def _persist_ai_connection(actor_identity: Dict[str, Any], project_id: Optional[str] = None):
    """Persist last-seen heartbeat for the current AI client."""
    try:
        editor = actor_identity.get("editor", "unknown")

        payload = {"clients": {}}
        if AI_CONNECTIONS_FILE.exists():
            with open(AI_CONNECTIONS_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            if "clients" not in payload:
                payload["clients"] = {}

        payload["clients"][editor] = {
            "last_seen": datetime.now().isoformat(),
            "actor_source": actor_identity.get("source", "fallback"),
            "actor_confidence": actor_identity.get("confidence", 0.0),
            "project_id": project_id,
            "connected": True,
        }

        # Ensure parent directory exists
        AI_CONNECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(AI_CONNECTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        _log(f"[MCP] AI connection persisted: {editor} -> {AI_CONNECTIONS_FILE}")
    except Exception as e:
        _log(f"[MCP] Failed to persist AI connection: {e} (path: {AI_CONNECTIONS_FILE})")


def _recover_session() -> Optional[tuple]:
    """Try to recover session from file. Returns (project_id, working_dir) or None."""
    try:
        if not SESSION_FILE.exists():
            return None

        with open(SESSION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Check if session is recent (within last hour)
        timestamp = datetime.fromisoformat(data.get("timestamp", ""))
        age_hours = (datetime.now() - timestamp).total_seconds() / 3600

        if age_hours < 1 and data.get("project_id") and data.get("working_dir"):
            return (data["project_id"], data["working_dir"])

        return None
    except Exception:
        return None


# ============================================================
# PHASE 2: UNIVERSAL GATE (Inversion of Control)
# ============================================================
# FixOnce is in control. Claude executes.
# - Auto-session: No manual init required
# - Context injection: Every response includes context
# - Error gate: Live errors are always visible
# ============================================================

def _get_active_project_from_api() -> Optional[dict]:
    """Get active project info from Flask API."""
    try:
        res = requests.get(f'{_get_api_url()}/api/projects/active', timeout=2)
        if res.status_code == 200:
            return res.json()
        return None
    except Exception:
        return None


def _auto_create_session() -> bool:
    """
    Automatically create session from active project or last session.
    Returns True if session was created.
    """
    # 1. Try to recover from persisted session
    recovered = _recover_session()
    if recovered:
        project_id, working_dir = recovered
        _set_session(project_id, working_dir)
        session = _get_session()
        session.mark_initialized()
        _log(f"[FixOnce] Auto-session from file: {project_id}")
        return True

    # 2. Try to get active project from API
    active = _get_active_project_from_api()
    if active and active.get('project_id'):
        project_id = active['project_id']
        # working_dir is nested in memory.project_info
        working_dir = active.get('memory', {}).get('project_info', {}).get('working_dir', '')
        _set_session(project_id, working_dir)
        session = _get_session()
        session.mark_initialized()
        _persist_session(project_id, working_dir)
        _log(f"[FixOnce] Auto-session from API: {project_id}")
        return True

    return False


def _get_live_errors() -> list:
    """Get unacknowledged browser errors."""
    try:
        _fo_init_trace("BROWSER_STATE_LOAD_BEFORE source=/api/live-errors")
        url = f'{_get_api_url()}/api/live-errors?since=600'
        _fo_init_trace(f"HTTP_GET_BEFORE _get_live_errors url={url} timeout=2")
        res = requests.get(url, timeout=2)
        _fo_init_trace(f"HTTP_GET_AFTER _get_live_errors status={res.status_code}")
        if res.status_code == 200:
            data = res.json()
            _fo_init_trace(f"_get_live_errors json_after count={len(data.get('errors', []))}")
            _fo_init_trace("BROWSER_STATE_LOAD_AFTER source=/api/live-errors")
            return data.get('errors', [])[:5]  # Max 5
        _fo_init_trace("BROWSER_STATE_LOAD_AFTER non_200")
        return []
    except Exception as exc:
        _fo_init_trace(f"_get_live_errors error {type(exc).__name__}: {exc}", include_stack=True)
        _fo_init_trace("BROWSER_STATE_LOAD_AFTER error")
        return []


def _get_auto_fixes() -> list:
    """Get current auto-fixes, or empty list if pending fixes are unavailable."""
    try:
        _fo_init_trace("PENDING_FIXES_LOAD_BEFORE")
        _fo_init_trace("_get_auto_fixes import_before")
        from core.pending_fixes import get_auto_fixes
        _fo_init_trace("_get_auto_fixes import_after call_before")
        fixes = get_auto_fixes()
        _fo_init_trace(f"_get_auto_fixes call_after count={len(fixes)}")
        _fo_init_trace("PENDING_FIXES_LOAD_AFTER")
        return fixes
    except Exception as exc:
        _fo_init_trace(f"_get_auto_fixes error {type(exc).__name__}: {exc}", include_stack=True)
        _fo_init_trace("PENDING_FIXES_LOAD_AFTER error")
        return []


def _evaluate_current_error_gate(
    tool_name: str,
    live_errors: int = 0,
    auto_fix_ready: bool = False,
):
    """Evaluate the Stage 7 error gate without changing existing UX strings."""
    _fo_init_trace(
        f"ERROR_GATE_EVALUATE_ENTER tool_name={tool_name!r} "
        f"live_errors={live_errors} auto_fix_ready={auto_fix_ready}"
    )
    ctx = InterventionContext(
        tool_name=tool_name,
        live_errors=live_errors,
        auto_fix_ready=auto_fix_ready,
    )
    if _intervention_policy_available:
        _fo_init_trace("ERROR_GATE_POLICY_BEFORE evaluate_error_gate")
        gate_result = evaluate_error_gate(ctx)
        _fo_init_trace(f"ERROR_GATE_POLICY_AFTER level={gate_result.level!r}")
        _fo_init_trace("AGENT_INTERVENTION_RECORD_BEFORE error_gate")
        _record_agent_intervention(
            tool_name,
            ctx,
            gate_results=[gate_result],
            flow_classification="migrated",
        )
        _fo_init_trace("AGENT_INTERVENTION_RECORD_AFTER error_gate")
        return gate_result

    if auto_fix_ready and tool_name != "fo_apply":
        _fo_init_trace("ERROR_GATE_RETURN fallback_block")
        return type("FallbackGateResult", (), {"level": "block"})()
    if live_errors > 0:
        _fo_init_trace("ERROR_GATE_RETURN fallback_warn")
        return type("FallbackGateResult", (), {"level": "warn"})()
    _fo_init_trace("ERROR_GATE_RETURN fallback_silent")
    return type("FallbackGateResult", (), {"level": "silent"})()


def _evaluate_current_risk_gate(
    tool_name: str = "",
    stable_component_touched: bool = False,
    blocked_components_relevant: int = 0,
    lock_violation: bool = False,
    risky_change: bool = False,
):
    """Evaluate the Stage 7 risk gate without changing existing UX strings."""
    ctx = InterventionContext(
        tool_name=tool_name,
        stable_component_touched=stable_component_touched,
        blocked_components_relevant=blocked_components_relevant,
        lock_violation=lock_violation,
        risky_change=risky_change,
    )
    if _intervention_policy_available:
        gate_result = evaluate_risk_gate(ctx)
        _record_agent_intervention(
            tool_name or "risk_gate",
            ctx,
            gate_results=[gate_result],
            flow_classification="migrated",
        )
        return gate_result

    if lock_violation:
        return type("FallbackGateResult", (), {"level": "block"})()
    if blocked_components_relevant > 0 or stable_component_touched or risky_change:
        return type("FallbackGateResult", (), {"level": "warn"})()
    return type("FallbackGateResult", (), {"level": "silent"})()


def _evaluate_current_repeat_bug_gate(
    tool_name: str = "",
    similar_past_solution_found: bool = False,
    repeat_bug_detected: bool = False,
):
    """Evaluate the Stage 7 repeat bug gate without changing existing UX strings."""
    ctx = InterventionContext(
        tool_name=tool_name,
        similar_past_solution_found=similar_past_solution_found,
        repeat_bug_detected=repeat_bug_detected,
    )
    if _intervention_policy_available:
        gate_result = evaluate_repeat_bug_gate(ctx)
        _record_agent_intervention(
            tool_name or "repeat_bug_gate",
            ctx,
            gate_results=[gate_result],
            flow_classification="migrated",
        )
        return gate_result

    if similar_past_solution_found or repeat_bug_detected:
        return type("FallbackGateResult", (), {"level": "warn"})()
    return type("FallbackGateResult", (), {"level": "silent"})()


def _evaluate_current_completion_gate(
    tool_name: str = "",
    bug_fix_completed: bool = False,
    fo_solved_called: bool = False,
    significant_work_completed: bool = False,
    sync_recorded: bool = False,
    component_changed: bool = False,
    component_status_updated: bool = False,
):
    """Evaluate the Stage 7 completion gate without changing existing UX strings."""
    ctx = InterventionContext(
        tool_name=tool_name,
        bug_fix_completed=bug_fix_completed,
        fo_solved_called=fo_solved_called,
        significant_work_completed=significant_work_completed,
        sync_recorded=sync_recorded,
        component_changed=component_changed,
        component_status_updated=component_status_updated,
    )
    if _intervention_policy_available:
        gate_result = evaluate_completion_gate(ctx)
        _record_agent_intervention(
            tool_name or "completion_gate",
            ctx,
            gate_results=[gate_result],
            flow_classification="migrated",
        )
        return gate_result

    if (
        (bug_fix_completed and not fo_solved_called)
        or (significant_work_completed and not sync_recorded)
        or (component_changed and not component_status_updated)
    ):
        return type("FallbackGateResult", (), {"level": "warn"})()
    return type("FallbackGateResult", (), {"level": "silent"})()


def _get_runtime_session_id(session: SessionContext) -> str:
    """Build a stable runtime session identifier for the current MCP session."""
    if not session or not session.project_id or not session.initialized_at:
        return "unknown-session"
    return hashlib.md5(
        f"{session.project_id}_{session.initialized_at}".encode()
    ).hexdigest()[:8]


def _evaluate_current_decision_conflict_gate(
    tool_name: str = "",
    decision_conflict_severity: str = "",
    conflicts: Optional[list] = None,
    intent: Optional[str] = None,
):
    """Evaluate the Stage 7 decision conflict gate via the Stage 8 bridge."""
    ctx = InterventionContext(
        tool_name=tool_name,
        decision_conflict_severity=decision_conflict_severity,
        extra={"conflicts": list(conflicts or [])},
    )
    if _intervention_policy_available:
        gate_result = evaluate_decision_conflict_gate(ctx)
        _record_agent_intervention(
            tool_name or "decision_conflict_gate",
            ctx,
            gate_results=[gate_result],
            intent=intent,
            flow_classification="migrated",
        )
        return gate_result

    severity = (decision_conflict_severity or "").lower()
    if severity in {"high", "severe", "critical"}:
        return type("FallbackGateResult", (), {"level": "block"})()
    if severity in {"medium", "moderate", "low"}:
        return type("FallbackGateResult", (), {"level": "warn"})()
    return type("FallbackGateResult", (), {"level": "silent"})()


def build_agent_context(
    tool_name: str,
    intent: Optional[str] = None,
    intervention_ctx: Optional[InterventionContext] = None,
    flow_classification: str = "partial",
) -> AgentContext:
    """
    Build a real AgentContext from current runtime state.

    This is Stage 8 runtime wiring only. It does not change UX or enforce
    any new behavior.
    """
    _fo_init_trace(f"AGENT_CONTEXT_BUILD_ENTER tool_name={tool_name!r}")
    _fo_init_trace("AGENT_CONTEXT_GET_SESSION_BEFORE")
    session = _get_session()
    _fo_init_trace(f"AGENT_CONTEXT_GET_SESSION_AFTER active={session.is_active() if session else False}")
    _fo_init_trace("AGENT_CONTEXT_ACTOR_IDENTITY_BEFORE")
    actor_identity = _resolve_actor_identity()
    _fo_init_trace(f"AGENT_CONTEXT_ACTOR_IDENTITY_AFTER editor={actor_identity.get('editor', 'unknown')!r}")

    project_id = session.project_id or "unknown-project"
    _fo_init_trace("AGENT_CONTEXT_SESSION_ID_BEFORE")
    session_id = _get_runtime_session_id(session)
    _fo_init_trace(f"AGENT_CONTEXT_SESSION_ID_AFTER session_id={session_id!r}")

    resolved_intent_detail = intent or ""
    if not resolved_intent_detail and session.is_active():
        try:
            _fo_init_trace("AGENT_CONTEXT_PROJECT_LOAD_BEFORE")
            memory = _load_project(session.project_id)
            _fo_init_trace("AGENT_CONTEXT_PROJECT_LOAD_AFTER")
            resolved_intent_detail = (
                memory.get("live_record", {})
                .get("intent", {})
                .get("current_goal", "")
            )
        except Exception as exc:
            _fo_init_trace(f"AGENT_CONTEXT_PROJECT_LOAD_ERROR {type(exc).__name__}: {exc}", include_stack=True)
            resolved_intent_detail = ""

    _fo_init_trace("AGENT_CONTEXT_CLASSIFY_INTENT_BEFORE")
    resolved_intent, resolved_intent_detail = classify_agent_intent(
        tool_name,
        explicit_intent=resolved_intent_detail,
        intervention_ctx=intervention_ctx,
    )
    _fo_init_trace(f"AGENT_CONTEXT_CLASSIFY_INTENT_AFTER intent={resolved_intent!r}")

    _fo_init_trace("AGENT_CONTEXT_BUILD_RETURN")
    return AgentContext(
        actor_name=actor_identity.get("editor", "unknown") or "unknown",
        actor_source=actor_identity.get("source", "none") or "none",
        actor_confidence=float(actor_identity.get("confidence", 0.0) or 0.0),
        tool_name=tool_name,
        intent=resolved_intent,
        session_id=session_id,
        project_id=project_id,
        intent_detail=resolved_intent_detail,
        flow_classification=flow_classification,
    )


def _new_record_attribution(tool_name: str) -> Dict[str, Any]:
    """Build the canonical attribution payload for a newly durable record."""
    session = _get_session()
    identity = _resolve_actor_identity()
    return {
        "actor": identity.get("editor", "unknown") or "unknown",
        "actor_source": identity.get("source", "none") or "none",
        "actor_confidence": float(identity.get("confidence", 0.0) or 0.0),
        "session_id": _get_runtime_session_id(session),
        "tool_name": tool_name or "unknown-tool",
    }


def _record_agent_intervention(
    tool_name: str,
    intervention_ctx: InterventionContext,
    gate_results: Optional[list] = None,
    intent: Optional[str] = None,
    flow_classification: str = "partial",
) -> str:
    """
    Stage 8 boundary: consume Stage 7 policy output in an agent-aware way.

    This is audit-only. It must not change runtime UX or enforce behavior.
    """
    if not _agent_intervention_available:
        _fo_init_trace("AGENT_INTERVENTION_UNAVAILABLE")
        return "silent"

    try:
        _fo_init_trace("AGENT_INTERVENTION_CONTEXT_BEFORE")
        agent_ctx = build_agent_context(
            tool_name,
            intent=intent,
            intervention_ctx=intervention_ctx,
            flow_classification=flow_classification,
        )
        _fo_init_trace("AGENT_INTERVENTION_CONTEXT_AFTER")
        ctx = intervention_ctx
        if gate_results is not None:
            _fo_init_trace("AGENT_INTERVENTION_REPLACE_CONTEXT_BEFORE")
            ctx = replace(
                intervention_ctx,
                extra={**intervention_ctx.extra, "gate_results": list(gate_results)},
            )
            _fo_init_trace("AGENT_INTERVENTION_REPLACE_CONTEXT_AFTER")

        audit_count_before = len(get_agent_audit(limit=500))
        _fo_init_trace("AGENT_INTERVENTION_EVALUATE_BEFORE")
        verdict = evaluate_agent_intervention(agent_ctx, ctx)
        _fo_init_trace(f"AGENT_INTERVENTION_EVALUATE_AFTER verdict={verdict!r}")
        _fo_init_trace("AGENT_INTERVENTION_COMPLIANCE_STATE_BEFORE")
        _compliance_state["last_agent_intervention"] = {
            "tool_name": tool_name,
            "verdict": verdict,
            "intent": agent_ctx.intent,
            "intent_detail": agent_ctx.intent_detail,
            "flow_classification": agent_ctx.flow_classification,
            "actor_name": agent_ctx.actor_name,
            "actor_source": agent_ctx.actor_source,
            "actor_confidence": agent_ctx.actor_confidence,
            "project_id": agent_ctx.project_id,
            "session_id": agent_ctx.session_id,
            "timestamp": datetime.now().isoformat(),
        }
        _fo_init_trace("AGENT_INTERVENTION_PERSIST_COMPLIANCE_BEFORE")
        _persist_compliance()
        _fo_init_trace("AGENT_INTERVENTION_PERSIST_COMPLIANCE_AFTER")
        _persist_agent_audit(
            agent_ctx.project_id,
            get_agent_audit(limit=500)[audit_count_before:],
        )
        return verdict
    except Exception as e:
        _fo_init_trace(f"AGENT_INTERVENTION_ERROR {type(e).__name__}: {e}", include_stack=True)
        _log(f"[FixOnce] Agent intervention audit failed: {e}")
        return "silent"


def _persist_agent_audit(project_id: str, entries: List[Dict[str, Any]]) -> None:
    """Persist new audit entries in project memory and portable team memory."""
    if not entries or not project_id or project_id == "unknown-project":
        return
    path = _get_project_path(project_id)
    if not path.exists() or not _safe_file_available:
        return

    def append_entries(memory):
        memory = dict(memory or {})
        existing = list(memory.get("agent_audit", []))
        known = {
            (item.get("timestamp"), item.get("session_id"), item.get("gate"))
            for item in existing
            if isinstance(item, dict)
        }
        for entry in entries:
            key = (entry.get("timestamp"), entry.get("session_id"), entry.get("gate"))
            if key not in known:
                existing.append(entry)
                known.add(key)
        memory["agent_audit"] = existing[-200:]
        return memory

    memory = durable_memory_write(
        path,
        mutator=append_entries,
        attribution=_new_record_attribution("agent_intervention"),
        tool_name="agent_intervention",
        create_backup=False,
    )
    session = _get_session()
    if session.project_id == project_id and session.working_dir:
        _persist_portable_team_memory(project_id, session.working_dir, memory)


def _persist_detected_decision_conflicts(
    project_id: str,
    conflicts: List[Dict[str, Any]],
    proposed_decision: str,
    proposed_reason: str,
    *,
    resolve_as_override: bool = False,
) -> List[str]:
    """Upsert detected conflicts even when the proposed decision is blocked."""
    if not conflicts or not project_id or project_id == "unknown-project":
        return []
    path = _get_project_path(project_id)
    if not path.exists() or not _safe_file_available:
        return []

    attribution = _new_record_attribution("fo_decide")
    touched_ids: List[str] = []

    def mutate(memory):
        nonlocal touched_ids
        memory, touched_ids = upsert_decision_conflicts(
            dict(memory or {}),
            conflicts,
            proposed_decision,
            proposed_reason,
            attribution=attribution,
        )
        if resolve_as_override:
            memory, _ = resolve_decision_conflicts(
                memory,
                status="resolved",
                action="accepted_override",
                reason=proposed_reason or "Decision accepted with force override.",
                attribution=attribution,
                conflict_ids=touched_ids,
            )
        return memory

    memory = durable_memory_write(
        path,
        mutator=mutate,
        attribution=attribution,
        tool_name="fo_decide",
        create_backup=False,
    )
    session = _get_session()
    if session.project_id == project_id and session.working_dir:
        _persist_portable_team_memory(project_id, session.working_dir, memory)
    return touched_ids


def _resolve_decision_conflict_by_id(conflict_id: str, reason: str) -> str:
    """Explicitly resolve one open conflict through fo_decide."""
    error, context = _universal_gate("fo_decide")
    if error:
        return error
    session = _get_session()
    attribution = _new_record_attribution("fo_decide")
    resolved_count = 0

    def mutate(memory):
        nonlocal resolved_count
        memory, resolved_count = resolve_decision_conflicts(
            dict(memory or {}),
            status="resolved",
            action="manual_resolution",
            reason=reason,
            attribution=attribution,
            conflict_ids=[conflict_id],
        )
        return memory

    memory = durable_memory_write(
        _get_project_path(session.project_id),
        mutator=mutate,
        attribution=attribution,
        tool_name="fo_decide",
        create_backup=True,
        require_existing=True,
    )
    if resolved_count == 0:
        return context + f"Conflict not found or already closed: {conflict_id}"
    if session.working_dir:
        _persist_portable_team_memory(session.project_id, session.working_dir, memory)
    return context + f"Resolved conflict: {conflict_id}"


def get_agent_evaluation_flow_audit() -> Dict[str, Dict[str, Any]]:
    """Return the Stage 8 runtime classification for each gate flow."""
    return {
        "error_gate": {
            "classification": "migrated",
            "runtime_entrypoint": "_evaluate_current_error_gate",
            "bypasses": [],
        },
        "decision_conflict_gate": {
            "classification": "migrated",
            "runtime_entrypoint": "_evaluate_current_decision_conflict_gate",
            "bypasses": [],
        },
        "risk_gate": {
            "classification": "migrated",
            "runtime_entrypoint": "_evaluate_current_risk_gate",
            "bypasses": [],
        },
        "repeat_bug_gate": {
            "classification": "migrated",
            "runtime_entrypoint": "_evaluate_current_repeat_bug_gate",
            "bypasses": [],
        },
        "completion_gate": {
            "classification": "migrated",
            "runtime_entrypoint": "_evaluate_current_completion_gate",
            "bypasses": [],
        },
        "standalone_bridge": {
            "classification": "partial",
            "runtime_entrypoint": "evaluate_agent_intervention",
            "bypasses": [],
        },
        "legacy_bypasses": {
            "classification": "legacy",
            "runtime_entrypoint": "",
            "bypasses": [],
        },
    }


def _get_pending_commands_for_injection() -> list:
    """Get pending commands from dashboard (without marking as delivered)."""
    try:
        res = requests.get(f'{_get_api_url()}/api/memory/ai-queue', timeout=2)
        if res.status_code == 200:
            data = res.json()
            return data.get('commands', [])[:3]  # Max 3
        return []
    except Exception:
        return []


def _get_new_rules() -> list:
    """Get custom rules that might be new."""
    try:
        res = requests.get(f'{_get_api_url()}/api/memory/rules', timeout=2)
        if res.status_code == 200:
            data = res.json()
            # Return only custom (non-default) rules
            rules = data.get('rules', [])
            return [r for r in rules if not r.get('default', False) and r.get('enabled', True)]
        return []
    except Exception:
        return []


def _get_recent_activities_for_handoff(editor: str, limit: int = 3) -> list:
    """Get recent activities for handoff summary between AIs."""
    try:
        res = requests.get(f'{_get_api_url()}/api/activity/feed?limit=20', timeout=2)
        if res.status_code != 200:
            return []

        data = res.json()
        activities = data.get('activities', [])

        # Filter to show what happened (not specific to editor since we track globally)
        summaries = []
        for a in activities[:limit * 2]:  # Get more to filter
            tool = a.get('tool', '')
            human_name = a.get('human_name', '')
            file_name = a.get('file', '').split('/')[-1] if a.get('file') else ''

            if tool == 'Edit' and file_name:
                diff = a.get('dif', {})
                added = diff.get('added', 0)
                if added > 0:
                    summaries.append(f"Edited {file_name} (+{added} lines)")
                else:
                    summaries.append(f"Edited {file_name}")
            elif tool == 'Write' and file_name:
                summaries.append(f"Created {file_name}")
            elif tool == 'Bash':
                cmd = a.get('command', '')[:30]
                if cmd:
                    summaries.append(f"Ran: {cmd}...")

            if len(summaries) >= limit:
                break

        return summaries
    except Exception:
        return []


def _build_context_header() -> str:
    """
    Build context header that gets injected into EVERY tool response.
    This is the core of "FixOnce in control".
    """
    lines = []
    session = _get_session()

    if not session.is_active():
        return ""

    # Load project data
    memory = _load_project(session.project_id)
    if not memory:
        return ""

    lr = memory.get('live_record', {})

    # 1. LIVE ERRORS (Always first - IMPOSSIBLE TO MISS)
    errors = _get_live_errors()
    if errors:
        lines.append("")
        lines.append("🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
        lines.append(f"⚠️ **{len(errors)} LIVE BROWSER ERRORS**")
        lines.append("🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
        for e in errors[:3]:
            msg = e.get('message', 'Unknown error')[:100]
            lines.append(f"  ❌ {msg}")
            # Show solution if available
            solution = e.get('solution')
            if solution:
                lines.append(f"     💡 FIX: {solution.get('text', '')[:80]}")
        if len(errors) > 3:
            lines.append(f"  ...and {len(errors) - 3} more")
        lines.append("")
        lines.append("**FIX THESE BEFORE DOING ANYTHING ELSE!**")
        lines.append("")

    # 1.5. PENDING COMMANDS (Dashboard → AI communication)
    pending_cmds = _get_pending_commands_for_injection()
    if pending_cmds:
        lines.append("")
        lines.append("📬 **PENDING COMMANDS FROM DASHBOARD:**")
        for cmd in pending_cmds:
            cmd_type = cmd.get('type', 'message')
            cmd_msg = cmd.get('message', '')[:100]
            lines.append(f"  → [{cmd_type}] {cmd_msg}")
        lines.append("**Use `get_pending_commands()` to process these!**")
        lines.append("")

    # 1.6. CUSTOM RULES (AI must follow these)
    custom_rules = _get_new_rules()
    if custom_rules:
        lines.append("")
        lines.append("📋 **ACTIVE RULES (you MUST follow):**")
        for rule in custom_rules:
            rule_text = rule.get('text', '')[:80]
            lines.append(f"  📌 {rule_text}")
        lines.append("")

    # 2. Current context (compact)
    project_name = memory.get('project_info', {}).get('name', session.project_id)
    goal = lr.get('intent', {}).get('current_goal', '')

    lines.append(f"📍 **{project_name}**" + (f" | 🎯 {goal}" if goal else ""))

    # 3. Active decisions (compact, one line)
    decisions = memory.get('decisions', [])
    if decisions:
        recent_dec = decisions[-1]  # Most recent
        dec_text = recent_dec.get('decision', '')[:50]
        lines.append(f"🔒 {dec_text}")

    lines.append("───────────────────────────────────────")

    return '\n'.join(lines)


_CONTEXT_HEADER_TOOLS = {
    "get_live_record",
    "get_policy_status",
    "get_stability_report",
    "check_and_report",
}


def _universal_gate(tool_name: str) -> tuple:
    """
    Universal gate for all MCP tools.

    Returns: (error_message, context_header)
    - If error_message is not None, tool should return it immediately
    - context_header should be prepended to tool response

    This replaces _require_session with auto-session + context injection.
    """
    current_mode = _get_fixonce_mode()

    if current_mode == MODE_OFF:
        return ("FixOnce is off. Proceed normally without FixOnce tools.", "")

    passive_blocked_tools = {
        "auto_init_session",
        "init_session",
        "sync_to_active_project",
        "update_live_record",
        "log_decision",
        "log_avoid",
        "supersede_decision",
        "update_component_status",
        "mark_component_stable",
        "rollback_component",
        "add_component_files",
        "auto_discover_components",
        "log_debug_session",
        "rebuild_semantic_index",
        "smart_file_operation",
        "mark_command_executed",
        "get_pending_commands",
        "highlight_element",
    }
    if current_mode == MODE_PASSIVE and tool_name in passive_blocked_tools:
        return (
            "FixOnce is in PASSIVE mode. Write/action tools are disabled until mode returns to FULL.",
            "",
        )

    init_tools = {"fo_init", "auto_init_session", "init_session", "sync_to_active_project"}
    if tool_name not in init_tools and not _is_session_initialized():
        return (_get_init_enforcement_error(), "")

    session = _get_session()

    # AUTO-SESSION: Recover project context after explicit init already happened.
    if not session.is_active():
        if _auto_create_session():
            session = _get_session()
        else:
            return ("Error: No active project session found. Call fo_init() again.", "")

    # Resolve actor for this tool call
    actor_identity = _resolve_actor_identity()
    agent_ctx = build_agent_context(tool_name)
    _compliance_state["editor"] = actor_identity["editor"]
    _persist_ai_connection(actor_identity, project_id=session.project_id)
    _compliance_state["agent_context"] = {
        "actor_name": agent_ctx.actor_name,
        "actor_source": agent_ctx.actor_source,
        "actor_confidence": agent_ctx.actor_confidence,
        "tool_name": agent_ctx.tool_name,
        "intent": agent_ctx.intent,
        "intent_detail": agent_ctx.intent_detail,
        "session_id": agent_ctx.session_id,
        "project_id": agent_ctx.project_id,
        "flow_classification": agent_ctx.flow_classification,
    }

    # Log tool call
    session.log_tool_call(tool_name)
    _sync_compliance()

    # REGISTER IN SESSION REGISTRY (Multi-AI Isolation)
    if _session_registry_available and session.is_active():
        try:
            ai_name = actor_identity.get("editor", "unknown")
            isolated_session = get_or_create_session(
                ai_name=ai_name,
                project_id=session.project_id,
                project_path=session.working_dir or ""
            )
            # Sync state to isolated session
            isolated_session.log_tool_call(tool_name)
            if session.initialized_at:
                isolated_session.mark_initialized()
            isolated_session.goal_updated = session.goal_updated
            isolated_session.decisions_displayed = session.decisions_displayed
        except Exception as e:
            _log(f"[FixOnce] SessionRegistry error: {e}")

    # UPDATE ACTIVE AI on every tool call (lightweight)
    _update_active_ai(actor_identity)

    # MCP Diet v3: repeated tool calls should not pay a dashboard/status header
    # tax. Deep resume and explicit diagnostic tools can still opt in.
    context = _build_context_header() if tool_name in _CONTEXT_HEADER_TOOLS else ""

    # Periodic protocol reminder (every 10 tool calls)
    context += _get_protocol_reminder()

    return (None, context)


def _update_active_ai(actor_identity: Optional[Dict[str, Any]] = None):
    """
    Update active_ais on every MCP tool call.
    PRIMARY MODEL: Only one AI is "primary" (currently active).
    Other AIs are marked as "historical" when a new AI takes over.
    """
    try:
        session = _get_session()
        if not session.project_id:
            return

        actor_identity = actor_identity or _resolve_actor_identity()
        detected_editor = actor_identity.get("editor", "unknown")
        actor_source = actor_identity.get("source", "fallback")
        actor_confidence = actor_identity.get("confidence", 0.0)
        attribution = _new_record_attribution("fo_init")
        if detected_editor == "unknown":
            return
        now = datetime.now()
        HISTORICAL_TIMEOUT_SECONDS = 60  # 1 minute to become historical

        # Check if we need to update
        project_id = session.project_id
        data = _load_project(project_id)
        if not data:
            return

        # Initialize active_ais if needed
        if "active_ais" not in data:
            data["active_ais"] = {}

        # Get this AI's current state
        ai_state = data["active_ais"].get(detected_editor, {})
        last_update = ai_state.get("last_activity", "")

        # Skip if same AI, already primary, and updated recently (30 seconds)
        if last_update and ai_state.get("is_primary"):
            try:
                last_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                if last_dt.tzinfo:
                    last_dt = last_dt.replace(tzinfo=None)
                if (now - last_dt).total_seconds() < 30:
                    return  # Skip update - too recent
            except:
                pass

        # Mark ALL other AIs as non-primary (historical)
        for ai_name in data["active_ais"]:
            if ai_name != detected_editor:
                data["active_ais"][ai_name]["is_primary"] = False

        # Get session tool calls count
        session = _get_session()
        session_tool_calls = len(session.tool_calls) if session else 0

        # Update this AI's state - make it PRIMARY
        if detected_editor not in data["active_ais"]:
            # New AI joining
            data["active_ais"][detected_editor] = {
                "started_at": now.isoformat(),
                "last_activity": now.isoformat(),
                "is_primary": True,
                "actor_source": actor_source,
                "actor_confidence": actor_confidence,
                "tool_calls": session_tool_calls,
                "actor": detected_editor,
                "session_id": attribution["session_id"],
                "tool_name": attribution["tool_name"],
            }
            _log(f"[MCP] AI Joined (primary): {detected_editor}")
        else:
            # Existing AI - update activity and make primary
            data["active_ais"][detected_editor]["last_activity"] = now.isoformat()
            data["active_ais"][detected_editor]["is_primary"] = True
            data["active_ais"][detected_editor]["actor_source"] = actor_source
            data["active_ais"][detected_editor]["actor_confidence"] = actor_confidence
            data["active_ais"][detected_editor]["tool_calls"] = session_tool_calls
            data["active_ais"][detected_editor]["actor"] = detected_editor
            data["active_ais"][detected_editor]["session_id"] = attribution["session_id"]
            data["active_ais"][detected_editor]["tool_name"] = attribution["tool_name"]

        # Clean up old historical AIs (no activity for 1 minute AND not primary)
        remove_ais = []
        for ai_name, ai_data in list(data["active_ais"].items()):
            if ai_data.get("is_primary"):
                continue  # Never remove primary
            try:
                last_act = datetime.fromisoformat(ai_data.get("last_activity", "").replace('Z', '+00:00'))
                if last_act.tzinfo:
                    last_act = last_act.replace(tzinfo=None)
                if (now - last_act).total_seconds() > HISTORICAL_TIMEOUT_SECONDS:
                    remove_ais.append(ai_name)
            except:
                pass

        for ai_name in remove_ais:
            _log(f"[MCP] AI Removed (historical timeout): {ai_name}")
            del data["active_ais"][ai_name]

        # Update ai_session for backward compatibility (most recent AI)
        if "ai_session" not in data:
            data["ai_session"] = {}

        old_editor = data["ai_session"].get("editor", "")
        data["ai_session"]["editor"] = detected_editor
        data["ai_session"]["last_activity"] = now.isoformat()
        data["ai_session"]["active"] = True
        data["ai_session"]["actor_source"] = actor_source
        data["ai_session"]["actor_confidence"] = actor_confidence
        data["ai_session"]["actor"] = detected_editor
        data["ai_session"]["session_id"] = attribution["session_id"]
        data["ai_session"]["tool_name"] = attribution["tool_name"]

        # Track handoff only if this is truly a different AI taking over
        # (not just parallel work)
        if old_editor and old_editor != detected_editor:
            # Check if old editor is still active
            old_ai_data = data["active_ais"].get(old_editor)
            if not old_ai_data:
                # Old editor timed out - this is a handoff
                if "ai_handoffs" not in data:
                    data["ai_handoffs"] = []
                data["ai_handoffs"].append(_create_handoff_record(
                    old_editor,
                    detected_editor,
                    now.isoformat(),
                    **_handoff_details(data),
                ))
                data["ai_handoffs"] = data["ai_handoffs"][-10:]

                data["ai_session"]["previous_ai"] = {
                    "editor": old_editor,
                    "started_at": data["ai_session"].get("started_at", ""),
                    "ended_at": now.isoformat()
                }
                _log(f"[MCP] AI Handoff: {old_editor} → {detected_editor}")

        _save_project(project_id, data)
        _persist_ai_connection(actor_identity, project_id=project_id)

    except Exception as e:
        # Don't break tool calls if update fails
        _log(f"[MCP] _update_active_ai error: {e}")


# Legacy function for backward compatibility
def _require_session(tool_name: str) -> Optional[str]:
    """
    DEPRECATED: Use _universal_gate instead.
    Kept for backward compatibility during transition.
    """
    error, _ = _universal_gate(tool_name)
    return error


def _require_project() -> str:
    """
    Get project_id from thread-local session.

    IMPORTANT: This is the NEW way to get project context.
    It NEVER reads from active_project.json.
    The session must be initialized via fo_init().

    Returns:
        project_id from the current session

    Raises:
        ValueError: If no session is active
    """
    session = _get_session()
    if not session or not session.working_dir:
        raise ValueError("No project context. Call fo_init(cwd) first.")
    return ProjectContext.from_path(session.working_dir)


def _get_browser_errors_reminder() -> str:
    """Get reminder about browser errors if there are any recent ones."""
    try:
        res = requests.get(f'{_get_api_url()}/api/live-errors?since=300', timeout=2)
        if res.status_code == 200:
            data = res.json()
            count = data.get('count', 0)
            gate_result = _evaluate_current_error_gate(
                tool_name="update_live_record",
                live_errors=count,
                auto_fix_ready=bool(_get_auto_fixes()),
            )
            if gate_result.level in {"warn", "block"}:
                return f"""

🚨 BROWSER ERRORS DETECTED: {count} errors!
═══════════════════════════════════════
You MUST call: fo_errors()
DO NOT ignore this - the user sees these errors!
═══════════════════════════════════════"""
        return ""
    except Exception:
        return ""


def _is_ai_context_mode_active() -> bool:
    """Check if AI Context Mode is active (simple check, no injection)."""
    # v1: Feature disabled
    return False


def _get_ai_context_injection() -> Optional[str]:
    """
    Get AI Context injection if mode is active AND elements are selected.

    This function implements the AI Context feature:
    - When user enables AI Context mode in dashboard
    - AND has selected element(s) using the FAB in browser
    - We inject this context into fo_init response
    - So the AI knows what "this/that/זה" refers to

    Returns:
        Formatted string with selected elements, or None if not applicable
    """
    # v1: Feature disabled
    return None

    try:
        # Check if AI Context mode is active
        mode_res = requests.get(f'{_get_api_url()}/api/ai-context-mode', timeout=1)
        if mode_res.status_code != 200:
            return None

        mode_data = mode_res.json()
        if not mode_data.get('active', False):
            return None

        # Get selected elements
        context_res = requests.get(f'{_get_api_url()}/api/browser-context', timeout=2)
        if context_res.status_code != 200:
            return None

        context_data = context_res.json()
        selected = context_data.get('selected_element')

        if not selected:
            return None

        # Extract element(s)
        elements = selected.get('elements', [])
        if not elements:
            el = selected.get('element')
            if el:
                elements = [el]

        if not elements:
            return None

        # Build injection
        lines = [
            "═══════════════════════════════════════",
            "## 🎯 AI CONTEXT ACTIVE - USER SELECTED ELEMENT(S)",
            "═══════════════════════════════════════",
            "",
            "**When user says \"this\", \"that\", \"זה\", \"את זה\" - they mean:**",
            ""
        ]

        for i, el in enumerate(elements[:3]):  # Max 3 elements
            selector = el.get('selector', 'N/A')
            tag = el.get('tagName', 'N/A')
            text = el.get('textContent', '')[:50]
            el_id = el.get('id', '')
            classes = el.get('className', '')[:30]

            if len(elements) > 1:
                lines.append(f"### Element {i+1}")

            lines.append(f"**Selector:** `{selector}`")
            lines.append(f"**Tag:** `{tag}`")

            if el_id:
                lines.append(f"**ID:** `{el_id}`")
            if classes:
                lines.append(f"**Classes:** `{classes}`")
            if text:
                lines.append(f"**Text:** \"{text}{'...' if len(el.get('textContent', '')) > 50 else ''}\"")

            # Show HTML snippet if available
            html = el.get('html', '')[:150]
            if html:
                lines.append(f"**HTML:** `{html}{'...' if len(el.get('html', '')) > 150 else ''}`")

            lines.append("")

        if len(elements) > 3:
            lines.append(f"_...and {len(elements) - 3} more elements_")
            lines.append("")

        lines.append("**Use this context when responding to user references.**")
        lines.append("═══════════════════════════════════════")
        lines.append("")

        return '\n'.join(lines)

    except Exception:
        return None


def _get_protocol_reminder() -> str:
    """Periodic reminder to use FixOnce tools during work."""
    session = _get_session()
    if not session.is_active():
        return ""

    tool_count = len(session.tool_calls)

    # Every 10 tool calls, subtle reminder
    if tool_count > 0 and tool_count % 10 == 0:
        return "\n💾 FixOnce: call fo_sync() after meaningful changes; fo_solved() after fixes"

    return ""


def _track_roi_event(event_type: str):
    """
    Track ROI event via Flask API.

    Events:
    - session_context: Session started with existing context
    - solution_reused: Past solution was found and applied
    - decision_used: Architectural decision was referenced
    - error_prevented: Avoid pattern prevented a mistake
    - insight_used: Existing insight was applied
    - error_caught_live: Browser error detected in real-time
    """
    try:
        requests.post(
            f"{_get_api_url()}/api/memory/roi/track",
            json={"event": event_type},
            timeout=2
        )
    except Exception:
        pass  # Silent fail - don't block MCP operations


def _log_mcp_activity(tool_name: str, details: dict = None):
    """
    Log MCP tool calls as activity for dashboard tracking.

    This enables visibility into AI memory operations like:
    - fo_sync (goal changes, insights)
    - fo_decide
    - fo_search

    Args:
        tool_name: Name of the MCP tool being called
        details: Optional dict with additional info (section, text, etc.)
    """
    try:
        session = _get_session()
        project_id = session.project_id if session.is_active() else "__global__"
        working_dir = session.working_dir if session.is_active() else ""

        # Get actor info
        actor_identity = _resolve_actor_identity()
        detected_editor = actor_identity.get("editor", "unknown")

        # Build activity entry
        activity = {
            "type": "mcp_tool",
            "tool": tool_name,
            "file": None,  # MCP tools don't have files
            "command": None,
            "cwd": working_dir,
            "project_id": project_id,
            "editor": detected_editor,
            "actor": detected_editor,
            "actor_source": actor_identity.get("source", "fallback"),
            "actor_confidence": actor_identity.get("confidence", 0.0),
            "timestamp": datetime.now().isoformat(),
            "human_name": _get_mcp_human_name(tool_name, details),
            "file_context": "memory",
            "mcp_details": details or {}
        }

        # Send to activity API
        requests.post(
            f"{_get_api_url()}/api/activity/log",
            json=activity,
            timeout=2
        )
    except Exception as e:
        # Silent fail - don't block MCP operations
        _log(f"[MCP] Activity log failed: {e}")


def _get_mcp_human_name(tool_name: str, details: dict = None) -> str:
    """Get human-readable name for MCP tool activity."""
    details = details or {}

    if tool_name == "update_live_record":
        section = details.get("section", "")
        if section == "intent":
            goal = details.get("goal", "")[:30]
            return f"Goal: {goal}..." if goal else "Updated goal"
        elif section == "lessons":
            if details.get("insight"):
                return "Added insight"
            elif details.get("failed_attempt"):
                return "Logged failed attempt"
            return "Updated lessons"
        elif section == "architecture":
            return "Updated architecture"
        return f"Updated {section}"

    elif tool_name == "log_decision":
        decision = details.get("decision", "")[:25]
        return f"Decision: {decision}..." if decision else "Logged decision"

    elif tool_name == "log_avoid":
        what = details.get("what", "")[:25]
        return f"Avoid: {what}..." if what else "Logged avoid pattern"

    elif tool_name == "search_past_solutions":
        query = details.get("query", "")[:20]
        return f"Search: {query}..." if query else "Searched solutions"

    elif tool_name == "auto_init_session":
        return "Session initialized"

    elif tool_name == "scan_project":
        return "Scanned project"

    elif tool_name == "update_component_status":
        name = details.get("name", "")[:20]
        status = details.get("status", "")
        status_icons = {"done": "🟢", "in_progress": "🟡", "blocked": "🔴", "not_started": "⚪",
                        "stable": "🟢", "building": "🟡", "broken": "🔴"}
        icon = status_icons.get(status, "⚙️")
        return f"{icon} {name}: {status}"

    elif tool_name == "mark_component_stable":
        name = details.get("name", "")[:20]
        return f"🔒 Marked stable: {name}"

    elif tool_name == "rollback_component":
        name = details.get("name", "")[:20]
        return f"🔄 Rollback: {name}"

    elif tool_name == "check_component_changes":
        name = details.get("name", "")[:20]
        return f"🔍 Checked: {name}"

    elif tool_name == "add_component_files":
        name = details.get("name", "")[:20]
        return f"📁 Added files to: {name}"

    elif tool_name == "stability_warning":
        component = details.get("component", "")[:20]
        return f"⚠️ Modified stable: {component}"

    elif tool_name == "get_stability_report":
        return "📊 Stability report"

    elif tool_name == "supersede_decision":
        old = details.get("old", "")[:20]
        return f"Superseded: {old}..."

    elif tool_name == "get_policy_status":
        return "Checked policy status"

    return tool_name.replace("_", " ").title()


# ============================================================
# MEMORY DECAY SYSTEM
# ============================================================

def _create_insight(
    text: str,
    linked_error: Optional[dict] = None,
    tool_name: str = "update_live_record",
) -> dict:
    """
    Create a new insight with full metadata for decay tracking.

    Fix #2: Auto-Link Incidents - if there's an active error, link it to this insight.
    """
    insight = {
        "text": text,
        "timestamp": datetime.now().isoformat(),
        "use_count": 0,
        "last_used": None,
        "importance": "medium"  # low/medium/high - auto-calculated
    }
    insight.update(_new_record_attribution(tool_name))

    # Fix #2: Link to active error if provided
    if linked_error:
        insight["linked_error"] = {
            "message": linked_error.get("message", "")[:200],
            "source": linked_error.get("source", ""),
            "timestamp": linked_error.get("timestamp", ""),
            "linked_at": datetime.now().isoformat()
        }

    return _attach_memory_quality_audit("insight", insight)


def _mark_insight_used(insight: dict) -> dict:
    """Mark an insight as used and update its importance."""
    insight["use_count"] = insight.get("use_count", 0) + 1
    insight["last_used"] = datetime.now().isoformat()

    # Track ROI: insight was used
    _track_roi_event("insight_used")

    # Auto-calculate importance based on use_count
    use_count = insight["use_count"]
    if use_count >= 5:
        insight["importance"] = "high"
    elif use_count >= 2:
        insight["importance"] = "medium"
    else:
        insight["importance"] = "low"

    return insight


def _normalize_insight(insight) -> dict:
    """Ensure insight has the new format with metadata."""
    if isinstance(insight, str):
        # Old format: just a string
        return _create_insight(insight)
    elif isinstance(insight, dict):
        # Might be old format with just 'text' or new format
        if "use_count" not in insight:
            # Old format with text/timestamp but no decay metadata
            text = insight.get("text", str(insight))
            new_insight = _create_insight(text)
            # Preserve original timestamp if it exists
            if "timestamp" in insight:
                new_insight["timestamp"] = insight["timestamp"]
            return new_insight
        return insight
    else:
        return _create_insight(str(insight))


_QUALITY_TEXT_FIELDS = {
    "solution": ("problem", "root_cause", "solution", "lesson_learned"),
    "solved_bug": ("problem", "root_cause", "solution", "lesson_learned"),
    "debug_session": ("problem", "root_cause", "solution", "lesson_learned"),
    "decision": ("decision", "reason", "expected_benefit"),
    "avoid": ("what", "reason"),
    "failed_attempt": ("text", "lesson_learned"),
    "insight": ("text",),
    "handoff": ("completed_work", "remaining_work", "risks", "next_action"),
    "intent": ("current_goal", "next_step"),
    "vision": ("text", "reason"),
}


def _memory_quality_text_present(record: Dict[str, Any], field: str) -> bool:
    value = record.get(field)
    if isinstance(value, str):
        return len(value.strip()) >= 10 and value.strip().lower() not in {
            "fixed bug", "solved issue", "completed task", "done", "fixed",
        }
    if isinstance(value, list):
        return bool(value)
    return value is not None


def _audit_memory_record(record_type: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """Generic, non-blocking quality audit for newly created memory records."""
    normalized_type = str(record_type or record.get("type") or "").lower().replace(" ", "_")
    issues = []
    required_fields = _QUALITY_TEXT_FIELDS.get(normalized_type, ())

    for field in required_fields:
        if not _memory_quality_text_present(record, field):
            issues.append(f"missing_{field}")

    timestamp = _coalesce_timestamp(record, "timestamp", "created_at", "resolved_at", "updated_at", "completed_at")
    if not timestamp:
        issues.append("missing_timestamp")

    if not record.get("actor") and not record.get("updated_by") and not record.get("last_actor"):
        issues.append("missing_actor")

    if normalized_type == "handoff":
        handoff_fields = ("completed_work", "remaining_work", "risks", "next_action")
        if any(not _memory_quality_text_present(record, field) for field in handoff_fields):
            issues.append("incomplete_handoff")

    meaningful_fields = [field for field in required_fields if _memory_quality_text_present(record, field)]
    score = 100
    if required_fields:
        score = int((len(meaningful_fields) / len(required_fields)) * 80) + 20
    score = max(0, score - max(0, len(issues) - (len(required_fields) - len(meaningful_fields))) * 5)

    return {
        "source_type": normalized_type or "memory",
        "checked_at": datetime.now().isoformat(),
        "status": "pass" if not issues else "needs_context",
        "confidence": "high" if not issues else "medium",
        "score": score,
        "issues": issues,
    }


def _attach_memory_quality_audit(record_type: str, record: Dict[str, Any]) -> Dict[str, Any]:
    normalized_type = str(record_type or record.get("type") or "memory").lower().replace(" ", "_")
    record.setdefault("source_type", normalized_type)
    record.setdefault("status", "active")
    record.setdefault("confidence", "medium")
    record["quality_audit"] = _audit_memory_record(record_type, record)
    return record


def _create_handoff_record(from_actor: str, to_actor: str, timestamp: Optional[str] = None, **details: Any) -> Dict[str, Any]:
    attribution = _new_record_attribution(details.get("tool_name", "fo_init"))
    record = {
        "from_actor": from_actor,
        "to_actor": to_actor,
        "from": from_actor,
        "to": to_actor,
        "timestamp": timestamp or datetime.now().isoformat(),
        "completed_work": details.get("completed_work", details.get("what_was_done", "")),
        "remaining_work": details.get("remaining_work", details.get("what_remains", "")),
        "risks": details.get("risks", details.get("current_risk", "")),
        "next_action": details.get("next_action", details.get("next_step", "")),
    }
    record.update(attribution)
    record["actor"] = to_actor or attribution["actor"]
    return _attach_memory_quality_audit("handoff", record)


def _handoff_details(memory: Dict[str, Any]) -> Dict[str, str]:
    """Derive a structured handoff from current durable work state."""
    intent = memory.get("live_record", {}).get("intent", {})
    resume = memory.get("resume_state", {}) or {}
    blockers = intent.get("blockers", [])
    if isinstance(blockers, list):
        risks = "; ".join(str(item) for item in blockers if item)
    else:
        risks = str(blockers or "")
    return {
        "completed_work": intent.get("last_change") or resume.get("last_completed_step", ""),
        "remaining_work": resume.get("active_task") or intent.get("current_goal", ""),
        "risks": risks or (
            resume.get("short_summary", "")
            if resume.get("current_status") == "blocked"
            else "No unresolved risk recorded."
        ),
        "next_action": intent.get("next_step") or resume.get("next_recommended_action", ""),
    }


_VISION_FIELDS = {
    "mission": "Mission",
    "long_term_goal": "Long-Term Goal",
    "current_direction": "Current Strategic Direction",
    "non_negotiables": "Non-Negotiables",
    "success_criteria": "Success Criteria",
    "out_of_scope": "Out Of Scope",
}


def _normalize_vision_key(key: str) -> str:
    normalized = str(key or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "goal": "long_term_goal",
        "long_term": "long_term_goal",
        "direction": "current_direction",
        "current_strategic_direction": "current_direction",
        "non_negotiable": "non_negotiables",
        "guardrail": "non_negotiables",
        "guardrails": "non_negotiables",
        "success": "success_criteria",
        "criteria": "success_criteria",
        "scope_exclusions": "out_of_scope",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _VISION_FIELDS else ""


def _ensure_vision_store(memory: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    live_record = memory.setdefault("live_record", {})
    vision = live_record.setdefault("vision", {})
    for key in _VISION_FIELDS:
        current = vision.get(key, [])
        if isinstance(current, str):
            current = [{"text": current}]
        elif isinstance(current, dict):
            current = [current]
        elif not isinstance(current, list):
            current = []
        normalized_items = []
        for item in current:
            if isinstance(item, str):
                item = {"text": item}
            if isinstance(item, dict):
                item.setdefault("source_type", "vision")
                item.setdefault("status", "active")
                normalized_items.append(item)
        vision[key] = normalized_items
    return vision


def _create_vision_record(text: str, reason: str = "", status: str = "active") -> Dict[str, Any]:
    record = {
        "id": f"vision_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
        "text": str(text or "").strip(),
        "reason": str(reason or "").strip(),
        "created_at": datetime.now().isoformat(),
        "status": status,
        "superseded_by": None,
        "reason_for_change": "",
    }
    record.update(_new_record_attribution("fo_vision"))
    return _attach_memory_quality_audit("vision", record)


def _active_vision_items(vision: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    items = vision.get(key, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get("status", "active") == "active"]


def _update_vision_memory(memory: Dict[str, Any], updates: Dict[str, Any], reason: str = "") -> int:
    vision = _ensure_vision_store(memory)
    changed = 0
    for raw_key, raw_value in updates.items():
        key = _normalize_vision_key(raw_key)
        if not key:
            continue
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        for value in values:
            if isinstance(value, dict):
                text = value.get("text") or value.get("value") or value.get("mission") or ""
                item_reason = value.get("reason", reason)
            else:
                text = str(value or "")
                item_reason = reason
            if not text.strip():
                continue
            new_record = _create_vision_record(text, item_reason)
            for existing in _active_vision_items(vision, key):
                existing["status"] = "superseded"
                existing["superseded_by"] = new_record["id"]
                existing["reason_for_change"] = item_reason or "Updated vision item."
            vision[key].append(new_record)
            changed += 1
    memory.setdefault("live_record", {})["vision"] = vision
    memory["live_record"]["updated_at"] = datetime.now().isoformat()
    return changed


def _format_vision_record(item: Dict[str, Any], mode: str = "compact") -> str:
    compact = (mode or "compact").lower() != "expanded"
    text = item.get("text", "")
    reason = item.get("reason", "")
    if compact:
        text = _compact_text(text, 260)
        reason = _compact_text(reason, 220)
    line = f"- {text}"
    if reason:
        line += f"\n  Why: {reason}"
    line += (
        "\n  Trust: "
        f"source_type=vision; actor={_memory_actor(item)}; "
        f"timestamp={_format_trust_timestamp(_coalesce_timestamp(item, 'created_at', 'timestamp'))}; "
        f"status={item.get('status', 'active')}; confidence={item.get('confidence', 'medium')}"
    )
    if item.get("superseded_by"):
        line += f"; superseded_by={item.get('superseded_by')}"
    if item.get("reason_for_change"):
        line += f"\n  Reason for change: {item.get('reason_for_change')}"
    return line


def _format_project_vision(memory: Dict[str, Any], mode: str = "compact") -> str:
    vision = _ensure_vision_store(memory)
    expanded = (mode or "compact").lower() == "expanded"
    lines = ["## Project Vision"]
    any_items = False

    for key in ("mission", "current_direction", "non_negotiables", "success_criteria", "long_term_goal", "out_of_scope"):
        items = vision.get(key, [])
        visible = [item for item in items if isinstance(item, dict) and (expanded or item.get("status", "active") == "active")]
        if not visible:
            continue
        any_items = True
        lines.append(f"### {_VISION_FIELDS[key]}")
        for item in visible:
            lines.append(_format_vision_record(item, mode=mode))

    if not any_items:
        lines.append("- No project vision recorded.")
    return "\n".join(lines)


def _audit_project_vision(memory: Dict[str, Any], stale_days: int = 180) -> Dict[str, Any]:
    vision = _ensure_vision_store(memory)
    issues = []
    now = datetime.now()

    required = ("mission", "success_criteria", "non_negotiables")
    for key in required:
        if not _active_vision_items(vision, key):
            issues.append(f"missing_{key}")

    for key, items in vision.items():
        for item in items:
            if not isinstance(item, dict) or item.get("status", "active") != "active":
                continue
            timestamp = _coalesce_timestamp(item, "created_at", "timestamp")
            if not timestamp:
                issues.append(f"{key}_missing_timestamp")
                continue
            try:
                created = datetime.fromisoformat(timestamp.replace("Z", ""))
                if (now - created).days > stale_days:
                    issues.append(f"{key}_stale")
            except Exception:
                issues.append(f"{key}_invalid_timestamp")

    active_non_negotiables = [item.get("text", "").lower() for item in _active_vision_items(vision, "non_negotiables")]
    for idx, text in enumerate(active_non_negotiables):
        for other in active_non_negotiables[idx + 1:]:
            text_tokens = _memory_tokens(text)
            other_tokens = _memory_tokens(other)
            if text_tokens & other_tokens and (
                ("must not" in text and "must " in other and "must not" not in other)
                or ("must not" in other and "must " in text and "must not" not in text)
            ):
                issues.append("conflicting_non_negotiables")

    return {
        "status": "pass" if not issues else "needs_context",
        "checked_at": datetime.now().isoformat(),
        "issues": sorted(set(issues)),
    }


_MEMORY_SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
    "could", "for", "from", "has", "have", "in", "is", "it", "not", "of",
    "on", "or", "that", "the", "this", "to", "was", "were", "with",
}

_SOLVED_BUG_PROBLEM_TERMS = {
    "bug", "broken", "crash", "crashed", "error", "exception", "fail", "failed",
    "failure", "hang", "invalid", "missing", "none", "null", "regression",
    "timeout", "traceback", "undefined",
}

_SOLVED_BUG_RESOLUTION_TERMS = {
    "commit", "committed", "fix", "fixed", "hardening", "no longer", "prevent",
    "prevented", "remove", "removed", "repair", "repaired", "resolve",
    "resolved", "restore", "restored", "success", "successful", "works",
    "working",
}


def _memory_tokens(text: str) -> set:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))
    words = re.findall(r"[a-z0-9_]+", normalized.lower())
    return set(words) - _MEMORY_SEARCH_STOPWORDS


def _memory_text_matches(query_lower: str, query_words: set, text: str) -> bool:
    text_lower = (text or "").lower()
    if not text_lower:
        return False
    if query_lower and query_lower in text_lower:
        return True
    text_words = _memory_tokens(text_lower)
    if not query_words:
        return False
    overlap = query_words & text_words
    if len(query_words) <= 2:
        return len(overlap) == len(query_words)
    return len(overlap) >= 2


def _looks_like_solved_bug_text(*parts: str) -> bool:
    text = " ".join(str(part or "") for part in parts).lower()
    if not text.strip():
        return False

    tokens = _memory_tokens(text)
    problem_hit = bool(tokens & _SOLVED_BUG_PROBLEM_TERMS)
    resolution_hit = bool(tokens & _SOLVED_BUG_RESOLUTION_TERMS) or any(
        phrase in text for phrase in _SOLVED_BUG_RESOLUTION_TERMS if " " in phrase
    )
    return problem_hit and resolution_hit


def _maybe_record_solved_bug_from_memory_event(
    memory: Dict[str, Any],
    source: str,
    problem: str,
    solution: str,
    files_changed: Optional[list] = None,
) -> bool:
    if not _looks_like_solved_bug_text(problem, solution):
        return False

    problem = (problem or solution or "").strip()[:240]
    solution = (solution or problem or "").strip()[:500]
    if not problem or not solution:
        return False

    debug_sessions = memory.setdefault("debug_sessions", [])
    candidate_key = _memory_tokens(f"{problem} {solution}")
    for existing in debug_sessions:
        existing_key = _memory_tokens(f"{existing.get('problem', '')} {existing.get('solution', '')}")
        if candidate_key and existing_key:
            overlap = candidate_key & existing_key
            if len(overlap) >= min(4, max(2, len(candidate_key) // 2)):
                return False

    record = {
        "id": f"fix_auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(debug_sessions) + 1}",
        "problem": problem,
        "root_cause": "",
        "solution": solution,
        "lesson_learned": "",
        "symptoms": [problem[:120]],
        "files_changed": files_changed or [],
        "resolved_at": datetime.now().isoformat(),
        "importance": "high",
        "reuse_count": 0,
        "source": source,
        "auto_classified": True,
    }
    record.update(_new_record_attribution(source))
    debug_sessions.append(_attach_memory_quality_audit("solution", record))
    return True


_TRUST_KEYWORDS_HIGH_VALUE = {
    "abandoned", "avoid", "blocked", "costly", "critical", "decision",
    "failed", "failure", "handoff", "lesson", "next", "problem", "reason",
    "repeat", "risk", "root", "solution", "success", "timeout",
}

_DO_NOT_REPEAT_TERMS = (
    "avoid", "never", "do not", "don't", "failed", "failure", "repeat",
    "repeated", "costly", "debugging loop", "risk", "blocked", "regression",
    "workaround",
)


def _coalesce_timestamp(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _format_trust_timestamp(timestamp: str) -> str:
    if not timestamp:
        return "timestamp unavailable"
    return str(timestamp).replace("T", " ")[:19]


def _memory_actor(item: Dict[str, Any]) -> str:
    actor = (
        item.get("actor")
        or item.get("created_by")
        or item.get("author")
        or item.get("editor")
        or item.get("ai")
        or item.get("last_actor")
        or item.get("delivered_to")
    )
    if not actor and isinstance(item.get("agent_context"), dict):
        actor = item["agent_context"].get("actor_name") or item["agent_context"].get("actor")
    return str(actor) if actor else "source unknown"


def _trust_status(category: str, item: Dict[str, Any]) -> str:
    if item.get("superseded"):
        return "superseded"
    if category == "handoff":
        return "historical"
    if category == "activity":
        return "historical"
    status = str(item.get("status") or item.get("state") or "").lower()
    if status in {"blocked", "failed", "unresolved", "open", "pending", "in_progress"}:
        return "unresolved"
    if status == "done":
        return "active"
    return "active"


def _trust_confidence(category: str, item: Dict[str, Any], timestamp: str = "") -> str:
    if item.get("superseded"):
        return "low"
    if category in {"decision", "avoid", "solved bug"}:
        return "high"
    if item.get("importance") == "high" or _safe_int(item.get("reuse_count") or item.get("use_count")) > 0:
        return "high"
    if timestamp:
        return "medium"
    return "low"


def _trust_reason(category: str, item: Dict[str, Any], fallback: str = "") -> str:
    reason = (
        item.get("reason")
        or item.get("root_cause")
        or item.get("solution")
        or item.get("desc")
        or item.get("detail")
        or fallback
    )
    if reason:
        return " ".join(str(reason).split())
    return "reason unavailable"


def _compact_text(text: Any, max_chars: int = 360) -> str:
    """Trim compact memory output without cutting in the middle of a sentence."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean

    window = clean[:max_chars]
    sentence_end = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
    if sentence_end >= max_chars // 2:
        return window[:sentence_end + 1]

    word_end = window.rfind(" ")
    if word_end >= max_chars // 2:
        return window[:word_end].rstrip() + "..."
    return window.rstrip() + "..."


def _stored_text_appears_incomplete(text: Any) -> bool:
    """Detect historical records that were already persisted with cut-off text."""
    clean = " ".join(str(text or "").split())
    if not clean:
        return False
    incomplete_patterns = [
        r"\([^)]*$",      # unclosed parenthesis
        r"\s(done|in)$",  # known historical mid-token status truncation
        r"\.\.\.$",       # explicit old truncation
        r":\s*$",         # label without content
    ]
    return any(re.search(pattern, clean) for pattern in incomplete_patterns)


def _memory_item(
    category: str,
    title: str,
    item: Dict[str, Any],
    detail: str = "",
    timestamp_keys: Optional[List[str]] = None,
    score: int = 0,
    fallback_reason: str = "",
) -> Dict[str, Any]:
    timestamp_keys = timestamp_keys or ["timestamp", "created_at", "resolved_at", "updated_at"]
    timestamp = _coalesce_timestamp(item, *timestamp_keys)
    title = " ".join(str(title or "").split())
    detail = " ".join(str(detail or "").split())
    return {
        "category": category,
        "title": title,
        "detail": detail,
        "timestamp": timestamp,
        "actor": _memory_actor(item),
        "why": _trust_reason(category, item, fallback_reason),
        "status": _trust_status(category, item),
        "confidence": _trust_confidence(category, item, timestamp),
        "score": score,
        "raw": item,
    }


def _memory_value_score(text: str, base: int = 0, reuse_count: int = 0, importance: str = "") -> int:
    tokens = _memory_tokens(text)
    score = base + reuse_count * 8
    score += sum(6 for keyword in _TRUST_KEYWORDS_HIGH_VALUE if keyword in tokens or keyword in text.lower())
    if importance == "high":
        score += 30
    elif importance == "medium":
        score += 10
    return score


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _top_memory_items(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    ranked = sorted(
        [item for item in items if item.get("title")],
        key=lambda item: (item.get("score", 0), item.get("timestamp", "")),
        reverse=True,
    )
    return ranked if limit is None else ranked[:limit]


def _format_trust_line(item: Dict[str, Any]) -> str:
    return _format_memory_item(item, mode="compact")


def _format_memory_item(item: Dict[str, Any], mode: str = "compact") -> str:
    compact = (mode or "compact").lower() != "expanded"
    title = item.get("title", "")
    detail = item.get("detail", "")
    why = item.get("why")
    if compact:
        title = _compact_text(title, 260)
        detail = _compact_text(detail, 320)
        why = _compact_text(why, 260)
    meta = (
        f"source_type={item.get('category')}; source={item.get('category')}; "
        f"actor={item.get('actor')}; "
        f"timestamp={_format_trust_timestamp(item.get('timestamp', ''))}; "
        f"when={_format_trust_timestamp(item.get('timestamp', ''))}; "
        f"status={item.get('status')}; confidence={item.get('confidence')}"
    )
    line = f"- {title}"
    if detail and detail != title:
        line += f" — {detail}"
    line += f"\n  Trust: {meta}"
    if why and why != "reason unavailable":
        line += f"\n  Why: {why}"
    if not compact and any(_stored_text_appears_incomplete(value) for value in (title, detail, why)):
        line += "\n  Note: stored text appears incomplete."
    return line


def _collect_core_trust_items(memory: Dict[str, Any], expanded: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    live_record = memory.get("live_record", {})
    lessons = live_record.get("lessons", {})
    architecture = live_record.get("architecture", {})

    decisions = []
    do_not_repeat = []
    solved_bugs = []
    risks = []
    recent_work = []
    handoffs = []

    for dec in memory.get("decisions", []):
        title = dec.get("decision", "")
        text = f"{title} {dec.get('reason', '')}"
        item = _memory_item(
            "decision",
            title,
            dec,
            detail=dec.get("reason", ""),
            timestamp_keys=["timestamp", "created_at", "updated_at"],
            score=_memory_value_score(text, base=80, importance=dec.get("importance", "")),
        )
        decisions.append(item)
        lowered = text.lower()
        if any(term in lowered for term in _DO_NOT_REPEAT_TERMS):
            do_not_repeat.append({**item, "category": "decision", "score": item["score"] + 20})

    for av in memory.get("avoid", []):
        title = av.get("what", "")
        text = f"{title} {av.get('reason', '')}"
        do_not_repeat.append(_memory_item(
            "avoid",
            title,
            av,
            detail=av.get("reason", ""),
            timestamp_keys=["timestamp", "created_at", "updated_at"],
            score=_memory_value_score(text, base=95, importance=av.get("importance", "high")),
        ))

    for attempt in lessons.get("failed_attempts", []):
        normalized = _normalize_insight(attempt)
        text = normalized.get("text", "")
        do_not_repeat.append(_memory_item(
            "insight",
            text,
            normalized,
            timestamp_keys=["timestamp", "created_at", "updated_at"],
            score=_memory_value_score(text, base=90, importance=normalized.get("importance", "")),
            fallback_reason="Previously recorded as a failed attempt.",
        ))

    for ds in memory.get("debug_sessions", []):
        problem = ds.get("problem", "")
        solution = ds.get("solution", "")
        text = f"{problem} {solution} {' '.join(ds.get('symptoms', []))}"
        solved = _memory_item(
            "solved bug",
            problem,
            ds,
            detail=solution,
            timestamp_keys=["resolved_at", "timestamp", "created_at", "updated_at"],
            score=_memory_value_score(
                text,
                base=85,
                reuse_count=_safe_int(ds.get("reuse_count")),
                importance=ds.get("importance", ""),
            ),
        )
        solved_bugs.append(solved)
        if _looks_like_solved_bug_text(problem, solution) or solved["score"] >= 110:
            do_not_repeat.append({**solved, "score": solved["score"] + 10})

    for insight in lessons.get("insights", []):
        normalized = _normalize_insight(insight)
        text = normalized.get("text", "")
        lowered = text.lower()
        candidate = _memory_item(
            "insight",
            text,
            normalized,
            timestamp_keys=["timestamp", "created_at", "updated_at", "last_used"],
            score=_memory_value_score(
                text,
                base=55,
                reuse_count=_safe_int(normalized.get("use_count")),
                importance=normalized.get("importance", ""),
            ),
            fallback_reason="Stored as a project lesson.",
        )
        if any(term in lowered for term in _DO_NOT_REPEAT_TERMS):
            do_not_repeat.append(candidate)
        if any(term in lowered for term in ("blocked", "remaining", "risk", "unresolved", "still", "unknown")):
            risks.append({**candidate, "status": "unresolved"})

    intent = live_record.get("intent", {})
    if intent:
        for key, label in (
            ("last_change", "Last meaningful work"),
            ("current_goal", "Project/current goal"),
            ("next_step", "Next step"),
        ):
            if intent.get(key):
                recent_work.append(_memory_item(
                    "activity",
                    f"{label}: {intent.get(key)}",
                    intent,
                    detail=intent.get("work_area", ""),
                    timestamp_keys=["updated_at", "timestamp"],
                    score=70 if key == "last_change" else 60,
                    fallback_reason="Current work context recorded by an agent.",
                ))

    for comp in architecture.get("components", []):
        comp_text = f"{comp.get('name', '')} {comp.get('status', '')} {comp.get('desc', '')}"
        comp_item = _memory_item(
            "component history",
            comp.get("name", ""),
            comp,
            detail=comp.get("desc", ""),
            timestamp_keys=["updated_at", "timestamp", "created_at"],
            score=_memory_value_score(comp_text, base=45),
            fallback_reason="Component status/history entry.",
        )
        if comp.get("status") in {"blocked", "in_progress"}:
            risks.append({**comp_item, "status": "unresolved"})
        if _looks_like_solved_bug_text(comp.get("name", ""), comp.get("desc", "")):
            solved_bugs.append({**comp_item, "category": "component history", "score": comp_item["score"] + 20})
        for hist in comp.get("history", []):
            if not isinstance(hist, dict):
                continue
            hist_text = f"{hist.get('action', '')} {hist.get('desc', '')}"
            hist_item = _memory_item(
                "component history",
                f"{comp.get('name', '')}: {hist.get('action', '')}",
                hist,
                detail=hist.get("desc", ""),
                timestamp_keys=["timestamp", "updated_at", "created_at"],
                score=_memory_value_score(hist_text, base=50),
                fallback_reason=f"History entry for component {comp.get('name', '')}.",
            )
            if _looks_like_solved_bug_text(hist.get("action", ""), hist.get("desc", "")):
                solved_bugs.append(hist_item)
            if any(term in hist_text.lower() for term in ("avoid", "failed", "do not", "don't", "never")):
                do_not_repeat.append(hist_item)

    ai_session = memory.get("ai_session", {})
    previous_ai = ai_session.get("previous_ai")
    if isinstance(previous_ai, dict) and previous_ai:
        handoffs.append(_memory_item(
            "handoff",
            f"{previous_ai.get('editor', 'unknown')} handed off to {ai_session.get('editor', 'unknown')}",
            {**previous_ai, "last_actor": previous_ai.get("editor")},
            detail=f"ended_at={previous_ai.get('ended_at', '')}",
            timestamp_keys=["ended_at", "started_at", "timestamp"],
            score=80,
            fallback_reason="Recorded as previous AI session handoff.",
        ))
    for handoff in memory.get("ai_handoffs", [])[-5:]:
        if isinstance(handoff, dict):
            from_actor = handoff.get("from_actor", handoff.get("from", "unknown"))
            to_actor = handoff.get("to_actor", handoff.get("to", "unknown"))
            detail = "; ".join(
                part for part in (
                    handoff.get("completed_work", ""),
                    handoff.get("remaining_work", ""),
                    handoff.get("next_action", ""),
                )
                if part
            )
            handoffs.append(_memory_item(
                "handoff",
                f"{from_actor} -> {to_actor}",
                {**handoff, "last_actor": to_actor},
                detail=detail,
                timestamp_keys=["timestamp", "created_at", "updated_at"],
                score=70,
                fallback_reason="Recorded multi-agent handoff.",
            ))

    activity_items = []
    if isinstance(memory.get("activity_log"), list):
        activity_items.extend(memory.get("activity_log", []))
    try:
        activity_file = USER_DATA_DIR / "activity_log.json"
        if activity_file.exists():
            activity_items.extend(json.loads(activity_file.read_text(encoding="utf-8")).get("activities", [])[:100])
    except Exception:
        pass
    for activity in activity_items[:100]:
        if not isinstance(activity, dict):
            continue
        text = " ".join(str(activity.get(key, "") or "") for key in ("human_name", "tool", "file", "cwd", "command", "file_context"))
        if not text.strip():
            continue
        item = _memory_item(
            "activity",
            activity.get("human_name") or activity.get("tool") or activity.get("command", ""),
            activity,
            detail=activity.get("file") or activity.get("cwd") or activity.get("file_context", ""),
            timestamp_keys=["timestamp", "created_at", "updated_at"],
            score=_memory_value_score(text, base=25),
            fallback_reason="Recent project activity.",
        )
        if item["score"] >= 55:
            recent_work.append(item)

    def limit(value: int) -> Optional[int]:
        return None if expanded else value

    return {
        "decisions": _top_memory_items([item for item in decisions if item.get("status") == "active"], limit(6)),
        "do_not_repeat": _top_memory_items(do_not_repeat, limit(7)),
        "solved_bugs": _top_memory_items(solved_bugs, limit(5)),
        "risks": _top_memory_items(risks, limit(5)),
        "recent_work": _top_memory_items(recent_work, limit(5)),
        "handoffs": _top_memory_items(handoffs, limit(3)),
    }


def _format_do_not_repeat_digest(memory: Dict[str, Any], limit: int = 7, mode: str = "compact") -> str:
    expanded = (mode or "compact").lower() == "expanded"
    items = _collect_core_trust_items(memory, expanded=expanded).get("do_not_repeat", [])
    if not expanded:
        items = items[:limit]
    if not items:
        return "No do-not-repeat items found."
    lines = [f"## Do Not Repeat ({'Expanded' if expanded else 'Compact'})"]
    for item in items:
        lines.append(_format_memory_item(item, mode=mode))
    return "\n".join(lines)


def _format_deep_project_brief(memory: Dict[str, Any], mode: str = "compact") -> str:
    expanded = (mode or "compact").lower() == "expanded"
    project_info = memory.get("project_info", {})
    live_record = memory.get("live_record", {})
    intent = live_record.get("intent", {})
    architecture = live_record.get("architecture", {})
    items = _collect_core_trust_items(memory, expanded=expanded)

    project_name = project_info.get("name") or "Unknown project"
    project_goal = intent.get("current_goal") or architecture.get("summary") or project_info.get("summary") or "project goal unavailable"
    work_area = intent.get("work_area") or "work area unavailable"
    last_work = intent.get("last_change") or "last meaningful work unavailable"
    next_step = intent.get("next_step") or "next step unavailable"

    lines = [
        f"# Deep Onboarding Brief: {project_name} ({'Expanded' if expanded else 'Compact'})",
        "",
        _format_project_vision(memory, mode=mode),
        "",
        "## Project Context",
        f"- Project goal: {project_goal}",
        f"- Current work area: {work_area}",
        f"- Last meaningful work: {last_work}",
        f"- Next step: {next_step}",
        "",
        "## Multi-Agent State",
    ]

    active_agents = []
    for name, state in memory.get("active_ais", {}).items():
        if not isinstance(state, dict):
            continue
        active_agents.append(
            f"{name} ({'primary' if state.get('is_primary') else 'active'}, "
            f"source={state.get('actor_source', 'none')}, "
            f"confidence={state.get('actor_confidence', 0.0)})"
        )
    lines.append(f"- Active agents: {', '.join(active_agents) if active_agents else 'None recorded.'}")

    attributable_records = []
    for collection in (
        memory.get("decisions", []),
        memory.get("avoid", []),
        memory.get("debug_sessions", []),
        live_record.get("lessons", {}).get("insights", []),
    ):
        attributable_records.extend(item for item in collection if isinstance(item, dict))
    attributable_records.extend(
        item for item in architecture.get("components", []) if isinstance(item, dict)
    )
    attributed = sum(
        1 for item in attributable_records
        if item.get("actor") or item.get("updated_by")
    )
    total = len(attributable_records)
    coverage = int((attributed / total) * 100) if total else 100
    lines.append(f"- Attribution coverage: {attributed}/{total} ({coverage}%)")

    recent_handoffs = [
        item for item in memory.get("ai_handoffs", [])
        if isinstance(item, dict)
    ][-3:]
    lines.append(f"- Recent handoffs: {len(recent_handoffs)}")
    for handoff in recent_handoffs:
        lines.append(
            f"  - {handoff.get('from_actor', handoff.get('from', 'unknown'))} -> "
            f"{handoff.get('to_actor', handoff.get('to', 'unknown'))}: "
            f"{handoff.get('next_action', handoff.get('next_step', 'No next action recorded.'))}"
        )

    severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    unresolved_conflicts = [
        conflict for conflict in memory.get("decision_conflicts", [])
        if isinstance(conflict, dict)
        and conflict.get("status", "open") == "open"
    ]
    unresolved_conflicts.sort(
        key=lambda conflict: (
            severity_rank.get(str(conflict.get("severity", "")).upper(), 0),
            conflict.get("last_seen") or conflict.get("updated_at") or "",
        ),
        reverse=True,
    )
    lines.append(f"- Unresolved conflicts: {len(unresolved_conflicts)}")
    for conflict in unresolved_conflicts[:3]:
        existing = conflict.get("existing_decision", {})
        proposed = conflict.get("proposed_decision", {})
        lines.append(
            f"  - {conflict.get('id', 'unknown-conflict')} "
            f"[{conflict.get('severity', 'UNKNOWN')}]: "
            f"existing=\"{_compact_text(existing.get('decision', ''), 100)}\" "
            f"(actor={existing.get('actor', 'unknown')}) vs "
            f"proposed=\"{_compact_text(proposed.get('decision', ''), 100)}\" "
            f"(actor={proposed.get('actor', 'unknown')}). "
            f"Recommended: supersede the existing decision, accept an override, "
            f"or resolve this conflict explicitly."
        )

    sections = [
        ("Decisions", items["decisions"]),
        ("Do Not Repeat", items["do_not_repeat"]),
        ("Solved Bugs", items["solved_bugs"]),
        ("Risks", items["risks"]),
        ("Recent Work", items["recent_work"]),
        ("Handoffs", items["handoffs"]),
    ]
    for title, section_items in sections:
        lines.extend(["", f"## {title}"])
        if not section_items:
            lines.append("- None recorded.")
            continue
        for item in section_items:
            lines.append(_format_memory_item(item, mode=mode))

    return "\n".join(lines)


def _calculate_insight_score(insight: dict) -> float:
    """
    Calculate a score for ranking insights.
    Higher score = more important/recent.
    """
    score = 0.0

    # Importance weight
    importance = insight.get("importance", "medium")
    if importance == "high":
        score += 100
    elif importance == "medium":
        score += 50
    else:
        score += 10

    # Use count bonus
    use_count = insight.get("use_count", 0)
    score += use_count * 10

    # Recency bonus (insights from last 7 days get boost)
    try:
        timestamp = insight.get("timestamp", "")
        if timestamp:
            created = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if created.tzinfo:
                created = created.replace(tzinfo=None)
            age_days = (datetime.now() - created).days
            if age_days <= 1:
                score += 50  # Today
            elif age_days <= 7:
                score += 30  # This week
            elif age_days <= 30:
                score += 10  # This month
    except Exception:
        pass

    return score


def _get_ranked_insights(insights: list, limit: int = 10) -> list:
    """Get top insights ranked by importance/recency/usage."""
    # Normalize all insights to new format
    normalized = [_normalize_insight(ins) for ins in insights]

    # Sort by score (highest first)
    ranked = sorted(normalized, key=_calculate_insight_score, reverse=True)

    return ranked[:limit]


def _should_archive_insight(insight: dict) -> bool:
    """
    Check if an insight should be archived (moved to cold storage).

    IMPORTANT: Decisions and avoid patterns should NEVER be archived.
    They are stored separately in memory['decisions'] and memory['avoid'],
    but this check ensures they're protected even if accidentally mixed in.
    """
    try:
        # NEVER archive decisions or avoid patterns - they are permanent institutional knowledge
        insight_type = insight.get("type", "insight")
        if insight_type in ("decision", "avoid", "failed_attempt"):
            return False

        # Never archive high-importance insights
        if insight.get("importance") == "high":
            return False

        # Never used and older than 30 days
        use_count = insight.get("use_count", 0)
        timestamp = insight.get("timestamp", "")

        if not timestamp:
            return False

        created = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if created.tzinfo:
            created = created.replace(tzinfo=None)
        age_days = (datetime.now() - created).days

        # Archive if: never used AND older than 30 days AND importance is low
        if use_count == 0 and age_days > 30 and insight.get("importance") == "low":
            return True

        # Archive if: not used in 60 days regardless (but only for low importance)
        last_used = insight.get("last_used")
        if last_used:
            last = datetime.fromisoformat(last_used.replace('Z', '+00:00'))
            if last.tzinfo:
                last = last.replace(tzinfo=None)
            unused_days = (datetime.now() - last).days
            if unused_days > 60 and insight.get("importance") != "medium":
                return True
        elif age_days > 60 and insight.get("importance") == "low":
            # Never used and very old - only for low importance
            return True

        return False
    except Exception:
        return False


def _get_session() -> SessionContext:
    """Get current session for this thread (never returns None)."""
    if not hasattr(_session_local, 'session') or _session_local.session is None:
        _session_local.session = SessionContext()
    return _session_local.session


def _set_session(project_id: str, working_dir: str):
    """Set session for current thread and update global state for dashboard."""
    _session_local.session = SessionContext(project_id, working_dir)
    # Sync to global state for Flask API (different thread)
    _compliance_state["session_active"] = True
    _compliance_state["initialized_at"] = datetime.now().isoformat()
    _compliance_state["project_id"] = project_id
    _compliance_state["last_session_init"] = datetime.now().isoformat()


def _clear_session():
    """Clear session for current thread and global state."""
    _session_local.session = SessionContext()
    # Clear global state
    _compliance_state["session_active"] = False
    _compliance_state["initialized_at"] = None
    _compliance_state["project_id"] = None


def _sync_compliance():
    """Sync session state to global _compliance_state for dashboard API."""
    session = _get_session()
    _compliance_state["session_active"] = session.is_active()
    _compliance_state["initialized_at"] = session.initialized_at
    _compliance_state["project_id"] = session.project_id
    _compliance_state["decisions_displayed"] = session.decisions_displayed
    _compliance_state["goal_updated"] = session.goal_updated
    _compliance_state["search_performed"] = session.search_performed
    _compliance_state["component_updated"] = session.component_updated
    _compliance_state["decision_logged"] = session.decision_logged
    _compliance_state["tool_calls_count"] = len(session.tool_calls)
    # Calculate and sync score
    score_data = session.get_compliance_score()
    _compliance_state["score"] = score_data["score"]
    _compliance_state["rules"] = score_data["rules"]
    # Persist to file for Flask API access
    _persist_compliance()


# ============================================================
# GIT UTILITIES
# ============================================================

def _get_git_commit_hash(working_dir: str) -> Optional[str]:
    """Get current git commit hash for a directory."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=no_window_creationflags(),
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]  # Short hash
        return None
    except Exception:
        return None


def _is_git_repo(working_dir: str) -> bool:
    """Check if directory is a git repository."""
    git_dir = Path(working_dir) / '.git'
    return git_dir.exists()


# ============================================================
# PROJECT INDEX (Cache with git hash invalidation)
# ============================================================

def _load_index() -> Dict[str, Any]:
    """Load project index from disk."""
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"version": 1, "projects": {}}


def _save_index(index: Dict[str, Any]):
    """Save project index to disk."""
    index["updated_at"] = datetime.now().isoformat()
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _get_cached_snapshot(project_id: str, working_dir: str) -> Optional[Dict[str, Any]]:
    """
    Get cached snapshot if valid.
    Returns None if:
    - Not in cache
    - Git hash changed (code changed)
    """
    index = _load_index()
    snapshot = index.get("projects", {}).get(project_id)

    if not snapshot:
        return None

    # Check git hash if it's a git repo
    if _is_git_repo(working_dir):
        current_hash = _get_git_commit_hash(working_dir)
        cached_hash = snapshot.get("git_commit_hash")

        if current_hash and cached_hash and current_hash != cached_hash:
            # Code changed - invalidate cache
            return None

    return snapshot


def _update_snapshot(project_id: str, working_dir: str, data: Dict[str, Any]):
    """Update project snapshot in index."""
    index = _load_index()

    lr = data.get('live_record', {})

    snapshot = {
        "project_id": project_id,
        "working_dir": working_dir,
        "name": data.get('project_info', {}).get('name', Path(working_dir).name),
        "git_commit_hash": _get_git_commit_hash(working_dir) if _is_git_repo(working_dir) else None,
        "summary": lr.get('architecture', {}).get('summary', ''),
        "stack": lr.get('architecture', {}).get('stack', ''),
        "current_goal": lr.get('intent', {}).get('current_goal', ''),
        "last_insight": (lr.get('lessons', {}).get('insights', []) or [''])[-1] if lr.get('lessons', {}).get('insights') else '',
        "decisions_count": len(data.get('decisions', [])),
        "avoid_count": len(data.get('avoid', [])),
        "indexed_at": datetime.now().isoformat()
    }

    if "projects" not in index:
        index["projects"] = {}

    index["projects"][project_id] = snapshot
    _save_index(index)


# ============================================================
# MCP SERVER
# ============================================================

mcp = FastMCP("fixonce")
_MCP_TOOL_TIMEOUT_SECONDS = 20
_FO_SYNC_TIMEOUT_SECONDS = 8
_SEMANTIC_SEARCH_TIMEOUT_SECONDS = 5
_tool_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fixonce-mcp-tool")
_mcp_health_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fixonce-mcp-health")
_original_mcp_tool = mcp.tool


def _mcp_error_log_file() -> Path:
    path = USER_DATA_DIR / "logs" / "mcp_errors.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _log_tool_exception(tool_name: str, exc: BaseException) -> None:
    message = f"[{datetime.now().isoformat()}] {tool_name}: {type(exc).__name__}: {exc}"
    _log(f"[MCPToolError] {message}")
    try:
        with _mcp_error_log_file().open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
            handle.write(traceback.format_exc())
            handle.write("\n")
    except Exception:
        pass


def _format_tool_error(tool_name: str, exc: BaseException) -> str:
    try:
        from core.mcp_session_health import classify_mcp_error, user_message_for_state, get_session_health
        if classify_mcp_error(exc).is_transport_failure:
            return user_message_for_state(get_session_health())
    except Exception:
        pass
    return (
        f"FixOnce MCP tool error in {tool_name}: "
        f"{type(exc).__name__}: {str(exc)[:300]}"
    )


def _mcp_actor_for_health() -> Dict[str, Any]:
    try:
        return _resolve_actor_identity()
    except Exception:
        return {"editor": "unknown", "source": "none", "confidence": 0.0}


def _record_mcp_tool_success(
    tool_name: str,
    *,
    resolve_actor: bool = True,
    wait_seconds: float = 0.2,
) -> None:
    actor_identity = _mcp_actor_for_health() if resolve_actor else {}
    session = _get_session()
    project_id = session.project_id if session and session.is_active() else None

    def record_success():
        try:
            from core.mcp_session_health import record_mcp_success

            record_mcp_success(tool_name=tool_name, actor_identity=actor_identity)
            if project_id:
                _persist_ai_connection(actor_identity, project_id=project_id)
        except Exception:
            pass

    try:
        future = _mcp_health_executor.submit(record_success)
        if wait_seconds > 0:
            future.result(timeout=wait_seconds)
    except Exception:
        pass


def _record_mcp_tool_failure(tool_name: str, exc: BaseException) -> Optional[str]:
    try:
        from core.mcp_session_health import classify_mcp_error, record_mcp_failure, user_message_for_state
        state = record_mcp_failure(
            exc,
            tool_name=tool_name,
            actor_identity=_mcp_actor_for_health(),
        )
        if classify_mcp_error(exc).is_transport_failure and state.get("state") == "session_lost":
            return user_message_for_state(state)
    except Exception:
        pass
    return None


def _run_tool_body(mcp_tool_name: str, func, *args, **kwargs):
    with contextlib.redirect_stdout(sys.stderr):
        try:
            if mcp_tool_name == "fo_init":
                _fo_init_trace_raw(
                    f"MCP_HANDLER_ENTER tool={mcp_tool_name} "
                    f"args_count={len(args)} kwargs_keys={list(kwargs.keys())}",
                    include_stack=True,
                )
            result = func(*args, **kwargs)
            if mcp_tool_name == "fo_init":
                _fo_init_trace_raw(
                    f"MCP_HANDLER_RESULT_READY type={type(result).__name__} "
                    f"length={len(result) if isinstance(result, str) else 'non-str'}"
                )
                _fo_init_trace_raw("MCP_RECORD_SUCCESS_SCHEDULE_BEFORE")
                _record_mcp_tool_success(mcp_tool_name, resolve_actor=True, wait_seconds=0)
                _fo_init_trace_raw("MCP_RECORD_SUCCESS_SCHEDULE_AFTER")
                return result
            _record_mcp_tool_success(mcp_tool_name)
            if mcp_tool_name == "fo_init":
                _fo_init_trace_raw("MCP_RECORD_SUCCESS_AFTER")
            return result
        except Exception as exc:
            if mcp_tool_name == "fo_init":
                _fo_init_trace_raw(f"MCP_HANDLER_EXCEPTION {type(exc).__name__}: {exc}", include_stack=True)
            _log_tool_exception(mcp_tool_name, exc)
            friendly = _record_mcp_tool_failure(mcp_tool_name, exc)
            if friendly:
                if mcp_tool_name == "fo_init":
                    _fo_init_trace_raw(f"MCP_HANDLER_FRIENDLY_ERROR length={len(friendly)}")
                return friendly
            formatted = _format_tool_error(mcp_tool_name, exc)
            if mcp_tool_name == "fo_init":
                _fo_init_trace_raw(f"MCP_HANDLER_FORMATTED_ERROR length={len(formatted)}")
            return formatted


def _run_tool_with_timeout(mcp_tool_name: str, func, timeout_seconds: int, *args, **kwargs):
    start = time.monotonic()
    if mcp_tool_name == "fo_sync":
        _mcp_process_event(
            f"fo_sync enter timeout={timeout_seconds}s "
            f"goal={kwargs.get('current_goal', '')!r} "
            f"work_area={kwargs.get('work_area', '')!r} "
            f"last_file={kwargs.get('last_file', '')!r}"
        )

    parent_session = _get_session()
    worker_session_ref = {}

    def run_with_current_session():
        if parent_session and parent_session.is_active():
            worker_session = SessionContext(parent_session.project_id, parent_session.working_dir)
            worker_session.initialized_at = parent_session.initialized_at
            worker_session.decisions_displayed = parent_session.decisions_displayed
            worker_session.goal_updated = parent_session.goal_updated
            worker_session.search_performed = parent_session.search_performed
            worker_session.component_updated = parent_session.component_updated
            worker_session.decision_logged = parent_session.decision_logged
            worker_session.tool_calls = list(parent_session.tool_calls)
            _session_local.session = worker_session
            worker_session_ref["session"] = worker_session
        return _run_tool_body(mcp_tool_name, func, *args, **kwargs)

    future = _tool_executor.submit(run_with_current_session)
    try:
        result = future.result(timeout=timeout_seconds)
        worker_session = worker_session_ref.get("session")
        if worker_session and parent_session:
            parent_session.goal_updated = worker_session.goal_updated
            parent_session.search_performed = worker_session.search_performed
            parent_session.component_updated = worker_session.component_updated
            parent_session.decision_logged = worker_session.decision_logged
            parent_session.tool_calls = list(worker_session.tool_calls)
        if mcp_tool_name == "fo_sync":
            duration = time.monotonic() - start
            _mcp_process_event(
                f"fo_sync normal return duration={duration:.3f}s "
                f"result_type={type(result).__name__}"
            )
        return result
    except FutureTimeoutError:
        duration = time.monotonic() - start
        _log(f"[MCPToolTimeout] {mcp_tool_name} exceeded {timeout_seconds}s")
        if mcp_tool_name == "fo_sync":
            _mcp_process_event(f"fo_sync timeout duration={duration:.3f}s limit={timeout_seconds}s")
        return (
            f"FixOnce MCP tool timeout in {mcp_tool_name}: "
            f"operation exceeded {timeout_seconds}s and was left in background."
        )
    except BaseException as exc:
        duration = time.monotonic() - start
        if mcp_tool_name == "fo_sync":
            _mcp_process_event(
                f"fo_sync exception duration={duration:.3f}s "
                f"{type(exc).__name__}: {exc}"
            )
        raise


def _safe_tool_handler(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tool_name = getattr(func, "__name__", "unknown_tool")
        timeout_seconds = _FO_SYNC_TIMEOUT_SECONDS if tool_name == "fo_sync" else _MCP_TOOL_TIMEOUT_SECONDS
        return _run_tool_with_timeout(tool_name, func, timeout_seconds, *args, **kwargs)
    return wrapper


def _safe_mcp_tool(*tool_args, **tool_kwargs):
    if tool_args and callable(tool_args[0]) and len(tool_args) == 1:
        safe_func = _safe_tool_handler(tool_args[0])
        _original_mcp_tool(safe_func, **tool_kwargs)
        return safe_func

    original_decorator = _original_mcp_tool(*tool_args, **tool_kwargs)

    def decorator(func):
        safe_func = _safe_tool_handler(func)
        original_decorator(safe_func)
        return safe_func

    return decorator


mcp.tool = _safe_mcp_tool


def _get_working_dir_from_port(port: int) -> Optional[str]:
    """Detect working directory from a running port using lsof."""
    try:
        # Get PID of process on port
        result = subprocess.run(
            ['lsof', '-i', f':{port}', '-t'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        pid = result.stdout.strip().split('\n')[0]

        # Get cwd of that process
        result = subprocess.run(
            ['lsof', '-p', pid],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None

        # Find cwd line
        for line in result.stdout.split('\n'):
            if ' cwd ' in line:
                # Extract path (last column)
                parts = line.split()
                if len(parts) >= 9:
                    path = parts[-1]
                    # Go up if we're in src/ or similar
                    if Path(path).name in ('src', 'dist', 'build', 'bin'):
                        path = str(Path(path).parent)
                    return path
        return None
    except Exception:
        return None


def _get_project_id(working_dir: str) -> str:
    """
    Convert working_dir to a safe project ID.

    IMPORTANT: This now delegates to ProjectContext.from_path()
    which is the SINGLE SOURCE OF TRUTH for project ID generation.
    """
    _fo_init_trace(f"PROJECT_METADATA_LOAD_BEFORE ProjectContext.from_path working_dir={working_dir!r}")
    _fo_init_trace(f"PROJECT_ID_BEFORE ProjectContext.from_path working_dir={working_dir!r}")
    project_id = ProjectContext.from_path(working_dir)
    _fo_init_trace(f"PROJECT_ID_AFTER project_id={project_id!r}")
    _fo_init_trace(f"PROJECT_METADATA_LOAD_AFTER project_id={project_id!r}")
    return project_id


def _get_project_path(project_id: str) -> Path:
    """Get path to project memory file."""
    return DATA_DIR / f"{project_id}.json"


def _load_project(project_id: str) -> Dict[str, Any]:
    """Load project memory with auto-recovery from backups."""
    path = _get_project_path(project_id)
    _fo_init_trace(
        f"FS_READ_PREPARE _load_project project_id={project_id!r} path={path} "
        f"safe_file={_safe_file_available}"
    )

    if _safe_file_available:
        # Use safe read with auto-recovery
        _fo_init_trace(f"FS_READ_BEFORE _load_project atomic_json_read path={path}")
        data = atomic_json_read(str(path), default={}, auto_recover=True)
        bases = getattr(_project_load_state, "bases", {})
        bases[project_id] = copy.deepcopy(data)
        _project_load_state.bases = bases
        _fo_init_trace(f"FS_READ_AFTER _load_project atomic_json_read path={path} keys={len(data) if isinstance(data, dict) else 'non-dict'}")
        return data

    # Fallback to regular json
    _fo_init_trace(f"FS_EXISTS_BEFORE _load_project path={path}")
    if path.exists():
        _fo_init_trace(f"FS_READ_BEFORE _load_project open path={path}")
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        bases = getattr(_project_load_state, "bases", {})
        bases[project_id] = copy.deepcopy(data)
        _project_load_state.bases = bases
        _fo_init_trace(f"FS_READ_AFTER _load_project open path={path} keys={len(data) if isinstance(data, dict) else 'non-dict'}")
        return data
    _fo_init_trace(f"FS_EXISTS_AFTER _load_project missing path={path}")
    return {}


def _merge_concurrent_value(base: Any, current: Any, updated: Any) -> Any:
    """Three-way merge preserving independent concurrent additions."""
    return merge_concurrent_value(base, current, updated)


def _record_identity(item: Dict[str, Any]) -> str:
    for field in ("id", "decision", "what", "problem", "text", "name"):
        value = item.get(field)
        if value:
            return f"{field}:{value}"
    return json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)


def _ensure_new_durable_attribution(
    base: Dict[str, Any],
    updated: Dict[str, Any],
    tool_name: str = "memory_write",
) -> None:
    """Attach provenance only to records created after the loaded base."""
    apply_new_record_defaults(
        base,
        updated,
        attribution=_new_record_attribution(tool_name),
        tool_name=tool_name,
    )


def _save_project(project_id: str, data: Dict[str, Any]):
    """Save project memory with auto-backup (to V2 canonical storage)."""
    path = _get_project_path(project_id)
    _fo_init_trace(
        f"FS_WRITE_PREPARE _save_project project_id={project_id!r} path={path} "
        f"safe_file={_safe_file_available}"
    )

    if _safe_file_available:
        bases = getattr(_project_load_state, "bases", {})
        base = bases.get(project_id, {})
        _fo_init_trace(f"FS_WRITE_BEFORE _save_project durable_memory_write path={path}")
        saved_data = durable_memory_write(
            path,
            updated=data,
            base=base,
            attribution=_new_record_attribution("memory_write"),
            tool_name="memory_write",
            create_backup=True,
        )
        bases[project_id] = copy.deepcopy(saved_data)
        _project_load_state.bases = bases
        data = saved_data
        _fo_init_trace(f"FS_WRITE_AFTER _save_project durable_memory_write path={path}")
    else:
        # Fallback to regular json
        _fo_init_trace(f"FS_WRITE_BEFORE _save_project open path={path}")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _fo_init_trace(f"FS_WRITE_AFTER _save_project open path={path}")

    # Update index snapshot
    session = _get_session()
    if session.working_dir:
        _fo_init_trace("_save_project update_snapshot_before")
        _update_snapshot(project_id, session.working_dir, data)
        _fo_init_trace("_save_project update_snapshot_after")
        _persist_portable_team_memory(project_id, session.working_dir, data)


def _persist_portable_team_memory(
    project_id: str,
    working_dir: str,
    memory: Dict[str, Any],
) -> None:
    """Persist bounded team state inside the repository for future agents."""
    if not working_dir:
        return
    audit = list(memory.get("agent_audit", []))[-200:]
    handoffs = list(memory.get("ai_handoffs", []))[-50:]
    conflicts = bound_conflicts(memory.get("decision_conflicts", []))
    if not audit and not handoffs and not conflicts:
        return
    path = Path(working_dir) / ".fixonce" / "team_memory.json"
    try:
        from core.committed_knowledge import sanitize_portable_value
        audit = sanitize_portable_value(audit)
        handoffs = sanitize_portable_value(handoffs)
        conflicts = sanitize_portable_value(conflicts)
    except ImportError:
        pass
    if _safe_file_available:
        def merge_portable(current):
            current = dict(current or {})

            def merge_records(existing, incoming, key_fields, limit):
                merged = list(existing or [])
                known = {
                    tuple(item.get(field) for field in key_fields)
                    for item in merged
                    if isinstance(item, dict)
                }
                for item in incoming:
                    if not isinstance(item, dict):
                        continue
                    key = tuple(item.get(field) for field in key_fields)
                    if key not in known:
                        merged.append(item)
                        known.add(key)
                return merged[-limit:]

            current.update({
                "fixonce_version": "1.0",
                "project_id": project_id,
                "updated_at": datetime.now().isoformat(),
            })
            current["agent_audit"] = merge_records(
                current.get("agent_audit"),
                audit,
                ("timestamp", "session_id", "gate"),
                200,
            )
            current["handoffs"] = merge_records(
                current.get("handoffs"),
                handoffs,
                ("timestamp", "from_actor", "to_actor", "next_action"),
                50,
            )
            existing_conflicts = {
                item.get("id"): item
                for item in current.get("decision_conflicts", [])
                if isinstance(item, dict) and item.get("id")
            }
            for item in conflicts:
                if isinstance(item, dict) and item.get("id"):
                    existing_conflicts[item["id"]] = item
            current["decision_conflicts"] = bound_conflicts(
                existing_conflicts.values()
            )
            return current

        atomic_json_update(
            str(path),
            merge_portable,
            default={},
            create_backup=False,
        )


def _init_project_memory(working_dir: str) -> Dict[str, Any]:
    """Create empty project memory."""
    try:
        from managers.multi_project_manager import infer_project_provenance
        provenance = infer_project_provenance(Path(working_dir).name, working_dir)
    except Exception:
        provenance = "user"

    return {
        "project_info": {
            "working_dir": working_dir,
            "name": Path(working_dir).name,
            "provenance": provenance,
            "created_at": datetime.now().isoformat()
        },
        "live_record": {
            "gps": {
                "working_dir": working_dir,
                "active_ports": [],
                "url": "",
                "environment": "dev"
            },
            "architecture": {
                "summary": "",
                "stack": "",
                "key_flows": []
            },
            "intent": {
                "current_goal": "",
                "next_step": "",
                "blockers": []
            },
            "lessons": {
                "insights": [],
                "failed_attempts": []
            }
        },
        "decisions": [],
        "decision_conflicts": [],
        "avoid": [],
        "errors": []
    }


def _is_meaningful_project(data: Dict[str, Any]) -> bool:
    """Check if project has meaningful data."""
    lr = data.get('live_record', {})

    # Has architecture info?
    arch = lr.get('architecture', {})
    if arch.get('summary', '').strip() or arch.get('description', '').strip() or arch.get('stack', '').strip():
        return True

    # Has lessons?
    if lr.get('lessons', {}).get('insights', []):
        return True

    # Has decisions?
    if data.get('decisions', []):
        return True

    return False


def _find_and_migrate_legacy_project(new_project_id: str, working_dir: str) -> Optional[Dict[str, Any]]:
    """
    Search for legacy project files with the same name but a different hash.

    Handles ID changes caused by:
    - git remote URL changes
    - Migration between hash strategies (path → git_remote, etc.)
    - Repository renames

    Safety: only migrates if the old file's working_dir is empty or matches.

    Returns migrated data dict, or None if no legacy data found.
    """
    name_prefix = new_project_id.rsplit('_', 1)[0]
    if not name_prefix:
        return None

    candidates = []
    for f in DATA_DIR.glob(f"{name_prefix}_*.json"):
        if '.migrated' in f.name:
            continue
        candidate_id = f.stem
        if candidate_id == new_project_id:
            continue
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception:
            continue

        if not _is_meaningful_project(data):
            continue

        old_wd = data.get('project_info', {}).get('working_dir', '')
        old_gps_wd = data.get('live_record', {}).get('gps', {}).get('working_dir', '')
        effective_old_wd = old_wd or old_gps_wd

        if effective_old_wd and effective_old_wd != working_dir:
            continue

        decisions = len(data.get('decisions', []))
        insights = len(data.get('live_record', {}).get('lessons', {}).get('insights', []))
        solutions = len(data.get('solutions_history', []))
        candidates.append((f, candidate_id, data, decisions + insights + solutions))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[3], reverse=True)
    best_file, old_id, old_data, _ = candidates[0]

    new_data = _init_project_memory(working_dir)

    for key in ['decisions', 'avoid', 'solutions_history', 'active_issues', 'stats', 'roi']:
        if old_data.get(key):
            new_data[key] = old_data[key]

    old_lr = old_data.get('live_record', {})
    new_lr = new_data['live_record']
    for section in ['architecture', 'intent', 'lessons']:
        old_section = old_lr.get(section, {})
        if section == 'lessons':
            if old_section.get('insights') or old_section.get('failed_attempts'):
                new_lr[section] = old_section
        elif section == 'architecture':
            if old_section.get('summary') or old_section.get('stack') or old_section.get('key_flows'):
                new_lr[section] = old_section
        elif section == 'intent':
            if old_section.get('current_goal'):
                new_lr[section] = old_section

    if old_data.get('project_info', {}).get('created_at'):
        new_data['project_info']['created_at'] = old_data['project_info']['created_at']

    # Migrate embeddings directory if it exists
    old_embeddings = DATA_DIR / f"{old_id}.embeddings"
    new_embeddings = DATA_DIR / f"{new_project_id}.embeddings"
    if old_embeddings.is_dir() and not new_embeddings.exists():
        try:
            old_embeddings.rename(new_embeddings)
        except Exception as e:
            _log(f"[MCP] Failed to migrate embeddings: {e}")

    # Archive old project file
    try:
        archive_path = best_file.with_suffix('.migrated.json')
        best_file.rename(archive_path)
    except Exception:
        pass

    _log(f"[MCP] Migrated project data: {old_id} → {new_project_id}")
    return new_data


def _get_recent_activity_summary(working_dir: str, limit: int = 5) -> str:
    """Get recent activity summary for init_session response."""
    activity_file = USER_DATA_DIR / "activity_log.json"

    if not activity_file.exists():
        return ""

    try:
        with open(activity_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        activities = data.get('activities', [])
        if not activities:
            return ""

        # Filter to current project
        project_activities = []
        for act in activities:
            file_path = act.get('file', '')
            cwd = act.get('cwd', '')
            if working_dir and (file_path.startswith(working_dir) or cwd.startswith(working_dir)):
                project_activities.append(act)

        if not project_activities:
            return ""

        # Take last N
        recent = project_activities[:limit]

        lines = ["**📋 Recent Activity:**"]
        for act in recent:
            human_name = act.get('human_name', '')
            file_path = act.get('file', '')
            file_name = file_path.split('/')[-1] if file_path else ''

            if human_name and file_name:
                lines.append(f"  • {human_name} ({file_name})")
            elif file_name:
                lines.append(f"  • {file_name}")
            elif act.get('command'):
                lines.append(f"  • `{act['command'][:30]}`")

        return '\n'.join(lines)

    except Exception:
        return ""


# ============================================================
# MCP TOOLS
# ============================================================

def _get_active_port_from_dashboard() -> Optional[int]:
    """Read active project port from dashboard."""
    try:
        # User-specific active project file
        active_file = USER_DATA_DIR / "active_project.json"

        if active_file.exists():
            with open(active_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Extract port from "localhost-5000" or "localhost:5000"
                active_id = data.get('active_id', '') or data.get('display_name', '')
                for sep in ['-', ':']:
                    if sep in active_id:
                        try:
                            return int(active_id.split(sep)[-1])
                        except ValueError:
                            pass
        return None
    except Exception:
        return None


# NOTE: auto_init_session is now INTERNAL ONLY (not exposed as MCP tool).
# Use fo_init() as the public init tool.
def auto_init_session(cwd: str = "", sync_to_active: bool = False) -> str:
    """
    INTERNAL: Initialize session for the current project.
    For external use, call fo_init() instead.

    Phase 1: Uses boundary detection as single source of truth.
    - Detects actual project root from cwd (not just uses cwd directly)
    - Compares against active project
    - Triggers boundary transition if needed

    Args:
        cwd: Optional current working directory from Claude Code
        sync_to_active: If True, join the currently active project regardless of cwd.
                       Use this for Multi-AI sync (e.g., Cursor joining Claude's project)

    Returns:
        Session info with project details
    """
    mode = _get_fixonce_mode()
    if mode == MODE_OFF:
        return "FixOnce is off. Proceed normally without FixOnce tools."
    if mode == MODE_PASSIVE:
        return "FixOnce is in PASSIVE mode. Session initialization is disabled."

    # Multi-AI Sync: If sync_to_active is True, use the active project
    if sync_to_active:
        try:
            from core.boundary_detector import _load_active_project
            active = _load_active_project()
            active_working_dir = active.get("working_dir")
            if active_working_dir and os.path.isdir(active_working_dir):
                _log(f"[MCP] Multi-AI Sync: Joining active project at {active_working_dir}")
                _debug_log(f"SYNC_TO_ACTIVE: joining {active_working_dir}")
                return _do_init_session(active_working_dir)
        except Exception as e:
            _log(f"[MCP] Multi-AI Sync failed: {e}")

    # DEBUG: Log what cwd is received
    import sys
    _log(f"[MCP DEBUG] auto_init_session called with cwd='{cwd}'", file=sys.stderr)
    _debug_log(f"auto_init_session cwd='{cwd}'")

    working_dir = None
    boundary_triggered = False

    # Phase 1: Use boundary detection to find actual project root
    if BOUNDARY_DETECTION_ENABLED and cwd and os.path.isdir(cwd):
        # Find the actual project root from cwd
        project_root, marker, confidence = find_project_root(cwd)

        if project_root and confidence in ("high", "medium"):
            # We found a valid project root
            # Check if it's different from current active project
            from core.boundary_detector import _load_active_project
            active = _load_active_project()
            active_working_dir = active.get("working_dir")

            if active_working_dir:
                # Compare: is this a different project?
                if not is_within_boundary(project_root, active_working_dir):
                    # Different project! Check if we should switch
                    # Create a synthetic boundary event for the session start
                    _log(f"[MCP] Session init boundary check:")
                    _log(f"  CWD: {cwd}")
                    _log(f"  Detected root: {project_root}")
                    _log(f"  Active project: {active_working_dir}")
                    _log(f"  Confidence: {confidence}")

                    # Trigger boundary transition
                    from core.boundary_detector import _get_project_id_from_path, _load_boundary_state, _is_cooldown_active

                    state = _load_boundary_state()
                    new_project_id = _get_project_id_from_path(project_root)

                    # Check cooldown and anti-ping-pong
                    if not _is_cooldown_active(state) and state.get("last_switch_from") != new_project_id:
                        event = BoundaryEvent(
                            old_project_id=active.get("active_id", ""),
                            old_working_dir=active_working_dir,
                            new_project_id=new_project_id,
                            new_working_dir=project_root,
                            file_path=cwd,
                            reason="session_init",
                            confidence=confidence,
                            timestamp=datetime.now().isoformat()
                        )
                        handle_boundary_transition(event)
                        boundary_triggered = True
                        _log(f"  Action: SWITCH to {project_root}")

            working_dir = project_root
        elif _is_valid_project_dir(cwd):
            # No strong marker but cwd itself is valid
            working_dir = cwd

    # Fallback: cwd if valid project directory
    if not working_dir:
        home_dir = str(Path.home())
        if cwd and os.path.isdir(cwd) and cwd != home_dir and _is_valid_project_dir(cwd):
            working_dir = cwd

    # WORKSPACE-BASED IDENTITY: cwd is required, no fallback to global state
    # active_project.json is updated as side-effect but NOT used for routing
    if working_dir:
        return _do_init_session(working_dir)

    # No valid workspace - return clear, actionable error
    home_dir = str(Path.home())
    is_home = cwd == home_dir if cwd else True

    if is_home:
        return f"""🏠 You're in your home directory ({home_dir}).

FixOnce needs a project folder to work with.

**What to do:**
1. Close this terminal
2. Open from a project folder to continue.

Or call `fo_init(cwd="/path/to/project")` from your project folder.

---
🏠 אתה בתיקיית הבית. FixOnce צריך תיקיית פרויקט.
פתח מתוך תיקיית פרויקט כדי להמשיך."""
    else:
        return f"""📁 This folder doesn't look like a project: {cwd}

FixOnce needs a project folder with files like:
.git, package.json, requirements.txt, etc.

**What to do:**
Navigate to your project root and try again, or:
`fo_init(cwd="/path/to/your/project")`"""


def _is_valid_project_dir(path: str) -> bool:
    """Check if path is a valid project directory (not home, not root, has project files)."""
    p = Path(path)

    # Reject home directory and root
    if str(p) == str(Path.home()) or str(p) == "/":
        return False

    # Check for common project markers
    project_markers = [
        '.git', 'package.json', 'pyproject.toml', 'Cargo.toml',
        'go.mod', 'pom.xml', 'build.gradle', 'Makefile',
        'requirements.txt', 'setup.py', '.project', 'CLAUDE.md'
    ]

    for marker in project_markers:
        if (p / marker).exists():
            return True

    # Check if it has source files (not just random dir)
    source_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java', '.rb'}
    try:
        for f in p.iterdir():
            if f.is_file() and f.suffix in source_extensions:
                return True
    except PermissionError:
        pass

    return False


def _resolve_init_working_dir(path: str) -> Optional[str]:
    """Resolve the working directory used by fo_init/init_session."""
    _fo_init_trace(f"RESOLVE_WORKING_DIR_ENTER path={path!r}")
    _fo_init_trace(f"FS_ISDIR_BEFORE _resolve_init_working_dir path={path!r}")
    if not path or not os.path.isdir(path):
        _fo_init_trace(f"FS_ISDIR_AFTER invalid path={path!r}")
        return None
    _fo_init_trace(f"FS_ISDIR_AFTER valid path={path!r}")

    if BOUNDARY_DETECTION_ENABLED:
        _fo_init_trace(f"BOUNDARY_DETECTION_BEFORE find_project_root path={path!r}")
        project_root, marker, confidence = find_project_root(path)
        _fo_init_trace(
            f"BOUNDARY_DETECTION_AFTER project_root={project_root!r} "
            f"marker={marker!r} confidence={confidence!r}"
        )
        if project_root and confidence in ("high", "medium"):
            _fo_init_trace(f"RESOLVE_WORKING_DIR_RETURN boundary project_root={project_root!r}")
            return project_root

    _fo_init_trace(f"VALID_PROJECT_BEFORE _is_valid_project_dir path={path!r}")
    if _is_valid_project_dir(path):
        _fo_init_trace(f"VALID_PROJECT_AFTER true path={path!r}")
        return path

    _fo_init_trace(f"VALID_PROJECT_AFTER false path={path!r}")
    return None


def _get_working_dir_from_recent_activity() -> Optional[str]:
    """Get the most recent project directory from activity log."""
    try:
        activity_file = USER_DATA_DIR / "activity_log.json"
        if not activity_file.exists():
            return None

        with open(activity_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        activities = data.get('activities', [])
        if not activities:
            return None

        # Find the most recent activity with a valid cwd
        for act in activities:
            cwd = act.get('cwd', '')
            if cwd and os.path.isdir(cwd) and _is_valid_project_dir(cwd):
                return cwd

        return None
    except Exception:
        return None


def _do_init_session(working_dir: str) -> str:
    """Internal init session logic - thread-safe, no global state."""
    if not working_dir or not os.path.isdir(working_dir):
        return f"Error: Invalid working directory: {working_dir}"

    project_id = _get_project_id(working_dir)

    # Set thread-local session
    _set_session(project_id, working_dir)

    # Persist session to file for recovery after MCP restart
    _persist_session(project_id, working_dir)

    # Mark session as initialized for compliance tracking
    session = _get_session()
    session.mark_initialized()
    session.log_tool_call("auto_init_session")

    # Mark global session as initialized (for cross-tool reminder)
    _mark_session_initialized()

    # Update global compliance state for dashboard
    _compliance_state["last_session_init"] = datetime.now().isoformat()
    actor_identity = _resolve_actor_identity()
    _compliance_state["editor"] = actor_identity.get("editor", "unknown")

    # REGISTER IN SESSION REGISTRY (Multi-AI Isolation)
    if _session_registry_available:
        try:
            ai_name = actor_identity.get("editor", "unknown")
            isolated_session = get_or_create_session(
                ai_name=ai_name,
                project_id=project_id,
                project_path=working_dir
            )
            isolated_session.mark_initialized()
            isolated_session.log_tool_call("auto_init_session")
            _log(f"[FixOnce] Registered session: {ai_name} on {project_id}")
        except Exception as e:
            _log(f"[FixOnce] SessionRegistry error in init: {e}")

    # Update active_ais for Multi-Active support
    _update_active_ai()

    # Seed the dashboard selection once. Session routing remains workspace-local,
    # so concurrent AIs cannot move an existing dashboard selection.
    try:
        from managers.multi_project_manager import ensure_dashboard_project
        ensure_dashboard_project(
            project_id=project_id,
            detected_from="auto_init",
            display_name=Path(working_dir).name,
            working_dir=working_dir
        )
    except Exception as e:
        _log(f"[FixOnce] Failed to update active project: {e}")

    # Track ROI: session with context
    _track_roi_event("session_context")

    # Check cache first (with git hash validation)
    cached = _get_cached_snapshot(project_id, working_dir)
    if cached and _is_meaningful_snapshot(cached):
        # Still update ai_session for cached projects
        actor_identity = _resolve_actor_identity()
        detected_editor = actor_identity.get("editor", "unknown")
        data = _load_project(project_id)
        if data:
            # Track previous AI for handoff (Multi-AI Sync) - also in cache path
            previous_ai = None
            if data.get("ai_session") and data["ai_session"].get("editor"):
                prev_editor = data["ai_session"].get("editor")
                prev_started = data["ai_session"].get("started_at")
                if prev_editor and prev_started:
                    previous_ai = {
                        "editor": prev_editor,
                        "started_at": prev_started,
                        "ended_at": datetime.now().isoformat()
                    }

            data["ai_session"] = {
                "active": True,
                "editor": detected_editor,
                "started_at": datetime.now().isoformat(),
                "briefing_sent": False,
                "actor_source": actor_identity.get("source", "fallback"),
                "actor_confidence": actor_identity.get("confidence", 0.0),
                "previous_ai": previous_ai,
                **_new_record_attribution("fo_init"),
            }

            # Track handoff history
            if "ai_handoffs" not in data:
                data["ai_handoffs"] = []
            if previous_ai and previous_ai["editor"] != detected_editor:
                data["ai_handoffs"].append(_create_handoff_record(
                    previous_ai["editor"],
                    detected_editor,
                    **_handoff_details(data),
                ))
                data["ai_handoffs"] = data["ai_handoffs"][-10:]

            _save_project(project_id, data)
        return _format_minimal_init(working_dir)

    # Load or create project (with legacy migration)
    data = _load_project(project_id)
    migrated = False
    if not data or not _is_meaningful_project(data):
        legacy_data = _find_and_migrate_legacy_project(project_id, working_dir)
        if legacy_data:
            if data:
                for key in ('ai_session', 'active_ais', 'ai_handoffs'):
                    if data.get(key):
                        legacy_data[key] = data[key]
            data = legacy_data
            migrated = True
        elif not data:
            data = _init_project_memory(working_dir)

    # Track previous AI for handoff (Multi-AI Sync)
    previous_ai = None
    if data.get("ai_session") and data["ai_session"].get("editor"):
        prev_editor = data["ai_session"].get("editor")
        prev_started = data["ai_session"].get("started_at")
        if prev_editor and prev_started:
            previous_ai = {
                "editor": prev_editor,
                "started_at": prev_started,
                "ended_at": datetime.now().isoformat()
            }

    # Update ai_session with detected editor
    actor_identity = _resolve_actor_identity()
    detected_editor = actor_identity.get("editor", "unknown")
    data["ai_session"] = {
        "active": True,
        "editor": detected_editor,
        "started_at": datetime.now().isoformat(),
        "briefing_sent": False,
        "actor_source": actor_identity.get("source", "fallback"),
        "actor_confidence": actor_identity.get("confidence", 0.0),
        "previous_ai": previous_ai,  # Track handoff
        **_new_record_attribution("fo_init"),
    }

    # Keep history of AI handoffs
    if "ai_handoffs" not in data:
        data["ai_handoffs"] = []
    if previous_ai and previous_ai["editor"] != detected_editor:
        data["ai_handoffs"].append(_create_handoff_record(
            previous_ai["editor"],
            detected_editor,
            **_handoff_details(data),
        ))
        # Keep last 10 handoffs
        data["ai_handoffs"] = data["ai_handoffs"][-10:]

    _save_project(project_id, data)

    # Determine status
    status = "existing" if _is_meaningful_project(data) else "new"

    # Update index
    _update_snapshot(project_id, working_dir, data)

    # Return minimal response
    return _format_minimal_init(working_dir)


def _is_meaningful_snapshot(snapshot: Dict[str, Any]) -> bool:
    """Check if snapshot has meaningful data."""
    return bool(
        snapshot.get('summary') or
        snapshot.get('current_goal') or
        snapshot.get('last_insight') or
        snapshot.get('decisions_count', 0) > 0
    )


def _get_browser_errors_summary(limit: int = 3) -> Optional[str]:
    """Get summary of recent browser errors for init response with auto-injected solutions."""
    try:
        res = requests.get(f'{_get_api_url()}/api/live-errors', timeout=2)
        if res.status_code != 200:
            return None

        data = res.json()
        errors = data.get('errors', [])

        if not errors:
            return None

        lines = ["### ⚠️ Browser Errors Detected"]
        solutions_found = 0
        injected_solutions = set()  # Prevent duplicates

        for err in errors[:limit]:
            msg = err.get('message', err.get('error', 'Unknown'))
            msg_short = msg[:60] if len(msg) > 60 else msg
            source = err.get('source', err.get('url', ''))
            source_short = source.split('/')[-1][:30] if source else 'Browser'
            lines.append(f"• **{source_short}**: {msg_short}")

            # Auto-Inject Solutions (with quality controls)
            solution = _find_solution_for_error(msg)
            if solution:
                solution_key = solution['text'][:50]
                if solution_key not in injected_solutions:
                    solutions_found += 1
                    injected_solutions.add(solution_key)
                    lines.append(f"  💡 **Solved before ({solution['similarity']}%):** {solution['text'][:80]}...")

        if solutions_found > 0:
            lines.append(f"\n✅ **{solutions_found} known fix(es).** Apply them.")

        if len(errors) > limit:
            lines.append(f"_...and {len(errors) - limit} more. Use `fo_errors()` for full list._")

        return '\n'.join(lines)
    except Exception:
        return None


def _check_stable_component_impact(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Check if a file belongs to a STABLE component.

    Returns:
        None if no stable component affected
        Dict with component info if affected: {"name": ..., "commit": ..., "files": [...]}
    """
    try:
        session = _get_session()
        if not session.is_active():
            return None

        memory = _load_project(session.project_id)
        arch = memory.get("live_record", {}).get("architecture", {})
        components = arch.get("components", [])

        # Normalize file path for comparison
        file_path_normalized = file_path.replace("\\", "/")
        if file_path_normalized.startswith("./"):
            file_path_normalized = file_path_normalized[2:]

        for comp in components:
            # Only check stable components with checkpoints
            if comp.get("status") not in ["stable", "done"]:
                continue
            if not comp.get("last_stable"):
                continue

            comp_files = comp.get("files", [])
            for cf in comp_files:
                cf_normalized = cf.replace("\\", "/")
                if cf_normalized.startswith("./"):
                    cf_normalized = cf_normalized[2:]

                # Check if file matches (exact or ends with)
                if (file_path_normalized == cf_normalized or
                    file_path_normalized.endswith("/" + cf_normalized) or
                    cf_normalized.endswith("/" + file_path_normalized)):
                    return {
                        "name": comp.get("name"),
                        "commit": comp.get("last_stable", {}).get("commit_short", "unknown"),
                        "files": comp_files
                    }

        return None
    except Exception:
        return None


def _log_stable_component_modification(component_name: str, file_path: str, actor: str = "AI") -> None:
    """Log when AI modifies a stable component."""
    try:
        session = _get_session()
        if not session.is_active():
            return

        memory = _load_project(session.project_id)

        # Add to activity log in memory
        activity = {
            "type": "stability_warning",
            "action": f"Modified stable component: {component_name}",
            "file": file_path,
            "actor": actor,
            "timestamp": datetime.now().isoformat(),
            "severity": "warning"
        }

        if "activity_log" not in memory:
            memory["activity_log"] = []
        memory["activity_log"].append(activity)

        # Keep last 100 activities
        if len(memory["activity_log"]) > 100:
            memory["activity_log"] = memory["activity_log"][-100:]

        _save_project(session.project_id, memory)

        # Send to activity API for dashboard visibility
        actor_identity = _resolve_actor_identity()
        detected_editor = actor_identity.get("editor", "unknown")

        api_activity = {
            "type": "stability_warning",
            "tool": "stability_warning",
            "file": file_path,
            "cwd": session.working_dir,
            "project_id": session.project_id,
            "editor": detected_editor,
            "actor": detected_editor,
            "timestamp": datetime.now().isoformat(),
            "human_name": f"⚠️ Modified stable: {component_name}",
            "action": f"Modified stable component: {component_name}",
            "file_context": "stability",
            "mcp_details": {
                "component": component_name,
                "file": file_path
            }
        }

        requests.post(
            f"{_get_api_url()}/api/activity/log",
            json=api_activity,
            timeout=2
        )
    except Exception:
        pass


def _format_from_snapshot(snapshot: Dict[str, Any], working_dir: str) -> str:
    """Format init response from cached snapshot."""
    lines = []

    # LIVE ERRORS FIRST (Universal Gate principle) + AUTO-INJECT SOLUTIONS
    live_errors = _get_live_errors()
    if live_errors:
        lines.append("═══════════════════════════════════════")
        lines.append(f"## ⚠️ {len(live_errors)} LIVE ERRORS - FIX BEFORE PROCEEDING")
        lines.append("═══════════════════════════════════════")

        solutions_found = 0
        injected_solutions = set()  # Prevent duplicates

        for e in live_errors[:3]:
            msg = e.get('message', 'Unknown error')
            msg_short = msg[:70] if len(msg) > 70 else msg
            lines.append(f"• {msg_short}")

            # Auto-Inject Solutions (with quality controls)
            solution = _find_solution_for_error(msg)
            if solution:
                solution_key = solution['text'][:50]
                if solution_key not in injected_solutions:
                    solutions_found += 1
                    injected_solutions.add(solution_key)
                    lines.append(f"  💡 **Solved before ({solution['similarity']}%):** {solution['text'][:100]}...")

        if len(live_errors) > 3:
            lines.append(f"• ...and {len(live_errors) - 3} more")

        if solutions_found > 0:
            lines.append("")
            lines.append(f"✅ **{solutions_found} known fix(es).** Apply them.")
        else:
            lines.append("")
            lines.append("**You MUST address these errors before doing anything else.**")
        lines.append("")

    # Project info
    lines.extend([
        f"## Project: {snapshot.get('name', Path(working_dir).name)}",
        f"**Status:** EXISTING",
        f"**Path:** `{working_dir}`",
        ""
    ])

    # DECISIONS FIRST - Load from project file (not cached in snapshot)
    project_id = _get_project_id(working_dir)
    data = _load_project(project_id)
    all_decisions = data.get('decisions', []) if data else []
    # Filter out superseded decisions - only show active ones
    decisions = [d for d in all_decisions if not d.get('superseded')]
    superseded_count = len(all_decisions) - len(decisions)

    if decisions:
        lines.append("---")
        lines.append("## 🚨 ACTIVE DECISIONS - YOU MUST RESPECT THESE")
        lines.append("")
        lines.append("**STOP before any change that contradicts these decisions!**")
        lines.append("**Ask user for explicit override approval if request conflicts.**")
        lines.append("")
        # MCP DIET: Limit to 8 most recent decisions (same as _format_init_response)
        MAX_DECISIONS = 8
        decisions_to_show = decisions[-MAX_DECISIONS:]
        for dec in decisions_to_show:
            # Truncate long decisions
            dec_text = dec.get('decision', '')[:100]
            reason_text = dec.get('reason', '')[:80]
            lines.append(f"🔒 **{dec_text}**")
            lines.append(f"   _Reason: {reason_text}_")
            lines.append("")
        hidden_count = len(decisions) - len(decisions_to_show) + superseded_count
        if hidden_count > 0:
            lines.append(f"_(...{hidden_count} more decisions. Use `get_policy_status()` for full list)_")
            lines.append("")
        lines.append("---")
        lines.append("")

        # Mark decisions as displayed for compliance tracking
        session = _get_session()
        session.mark_decisions_displayed()
        _sync_compliance()

        # Track ROI: decisions enforced this session (track once per init, not per decision)
        if len(decisions) > 0:
            _track_roi_event("decision_used")

    # PROJECT RULES - User-defined behavioral rules
    project_rules = data.get('project_rules', []) if data else []
    enabled_rules = [r for r in project_rules if r.get('enabled', True)]
    if enabled_rules:
        lines.append("---")
        lines.append("## 📋 PROJECT RULES - FOLLOW THESE")
        lines.append("")
        for rule in enabled_rules:
            text = rule.get('text', '')
            is_default = rule.get('default', False)
            marker = "📌" if is_default else "✏️"
            lines.append(f"{marker} {text}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # INSIGHTS - Check these BEFORE researching anything!
    # Use Memory Decay ranking to show most important insights
    insights = data.get('live_record', {}).get('lessons', {}).get('insights', []) if data else []
    if insights:
        # Get top 5 ranked insights (by importance, use_count, recency)
        top_insights = _get_ranked_insights(insights, limit=5)

        lines.append("---")
        lines.append("## 🧠 STORED INSIGHTS - CHECK BEFORE RESEARCHING")
        lines.append("")
        lines.append("**YOU ARE FORBIDDEN from external research if relevant insight exists below!**")
        lines.append("**If relevant → use it. If not → proceed with research.**")
        lines.append("")
        for ins in top_insights:
            text = ins.get('text', '')
            importance = ins.get('importance', 'medium')
            use_count = ins.get('use_count', 0)

            # Show importance indicator
            if importance == 'high':
                prefix = "🔥"  # Hot/important
            elif use_count > 0:
                prefix = "✓"   # Used before
            else:
                prefix = "💡"  # Regular

            lines.append(f"{prefix} {text}")

        if len(insights) > 5:
            lines.append(f"_...and {len(insights) - 5} more. Use `fo_search()` to find specific ones._")
        lines.append("")
        lines.append("---")
        lines.append("")

    if snapshot.get('current_goal'):
        lines.append(f"**Last Goal:** {snapshot['current_goal']}")

    if snapshot.get('summary'):
        lines.append(f"**Architecture:** {snapshot['summary']}")

    if snapshot.get('last_insight'):
        lines.append(f"**Last Insight:** {snapshot['last_insight']}")

    # Show git status if available
    if snapshot.get('git_commit_hash'):
        lines.append(f"**Git:** `{snapshot['git_commit_hash']}`")

    # Multi-AI Handoff Summary
    ai_session = data.get("ai_session", {}) if data else {}
    previous_ai = ai_session.get("previous_ai")
    current_editor = ai_session.get("editor", "unknown")

    if previous_ai and previous_ai.get("editor") != current_editor:
        prev_editor = previous_ai.get("editor", "unknown").capitalize()
        prev_started = previous_ai.get("started_at", "")

        # Calculate time ago
        time_ago = ""
        if prev_started:
            try:
                started_dt = datetime.fromisoformat(prev_started.replace('Z', '+00:00'))
                diff = datetime.now() - started_dt.replace(tzinfo=None)
                mins = int(diff.total_seconds() // 60)
                if mins < 60:
                    time_ago = f"{mins} min"
                elif mins < 1440:
                    time_ago = f"{mins // 60}h"
                else:
                    time_ago = f"{mins // 1440}d"
            except:
                pass

        lines.append("")
        lines.append("---")
        lines.append(f"## 🔄 Handoff from {prev_editor}")
        if time_ago:
            lines.append(f"**{prev_editor}** worked here {time_ago} ago.")

        # Show recent activity from previous AI
        recent_activities = _get_recent_activities_for_handoff(prev_editor.lower(), limit=3)
        if recent_activities:
            lines.append("**Last actions:**")
            for act in recent_activities:
                lines.append(f"• {act}")
        lines.append("")

    # AI Queue - errors/tasks sent from dashboard
    ai_queue = data.get("ai_queue", []) if data else []
    pending_items = [q for q in ai_queue if q.get("status") == "pending"]

    # Separate action commands from regular items
    action_commands = [q for q in pending_items if q.get("type") == "action_command"]
    other_items = [q for q in pending_items if q.get("type") != "action_command"]

    # Show action commands first (user requested action from dashboard)
    if action_commands:
        lines.append("═══════════════════════════════════════")
        lines.append("## 🚀 ACTION REQUESTED FROM DASHBOARD")
        lines.append("═══════════════════════════════════════")
        lines.append("")
        lines.append("The user clicked an action button in the FixOnce dashboard.")
        lines.append("**Execute the following request:**")
        lines.append("")

        for cmd in action_commands[:1]:  # Show only the most recent command
            cmd_id = cmd.get("id", "unknown")
            msg = cmd.get("message", "")
            lines.append(f"**Command ID:** `{cmd_id}`")
            lines.append("```")
            lines.append(msg)
            lines.append("```")

        lines.append("")
        lines.append("**This is a HIGH PRIORITY request. Execute it now.**")
        lines.append("**After completing, call:** `mark_command_executed(command_id, result, details)`")
        lines.append("")

    # Show other queued items
    if other_items:
        lines.append("---")
        lines.append("## 🎯 QUEUED FOR YOU")
        for item in other_items[:3]:
            item_type = item.get("type", "task")
            msg = item.get("message", "")[:80]
            source = item.get("source", "")
            line_num = item.get("line", "")

            if item_type == "error":
                lines.append(f"⚠️ **Error:** `{msg}`")
                if source:
                    loc = source + (f":{line_num}" if line_num else "")
                    lines.append(f"   📍 {loc}")
            else:
                lines.append(f"📋 **Task:** {msg}")

        lines.append("")
        lines.append("**Fix these first, then mark as handled.**")
        lines.append("")

        # Mark items as delivered (old code used "shown", now using security layer status)
        now = datetime.now().isoformat()
        for item in pending_items[:3]:
            item["status"] = "delivered"
            item["delivered_at"] = now
            item["delivered_to"] = _detect_editor()
        _save_project(snapshot.get("project_id") or _get_project_id(working_dir), data)

    # Fix #3: Session State Visibility
    session = _get_session()
    if session and session.initialized_at:
        session_id = hashlib.md5(f"{session.project_id}_{session.initialized_at}".encode()).hexdigest()[:8]
        start_time = session.initialized_at[:19].replace('T', ' ')
        tools_count = len(session.tool_calls)
        lines.append(f"**Session:** `{session_id}` | Started: {start_time} | Tools: {tools_count}")

    # Resume State - show if there's pending work from last session
    if _resume_state_available:
        try:
            resume_state = _get_resume_state(project_id)
            if resume_state:
                resume_section = format_resume_for_init(resume_state)
                if resume_section:
                    lines.append("")
                    lines.append(resume_section)
        except Exception as e:
            _log(f"[FixOnce] Resume state error in snapshot: {e}")

    lines.append("")
    lines.append("_Ask: 'נמשיך מכאן?'_")

    # Add recent activity
    activity_info = _get_recent_activity_summary(working_dir, limit=5)
    if activity_info:
        lines.append("")
        lines.append(activity_info)

    # Add browser errors if any
    errors_info = _get_browser_errors_summary(limit=3)
    if errors_info:
        lines.append("")
        lines.append(errors_info)

    # Add AI Context injection if active and elements selected
    ai_context = _get_ai_context_injection()
    if ai_context:
        lines.append("")
        lines.append(ai_context)

    return '\n'.join(lines)


def _format_init_response(data: Dict[str, Any], status: str, working_dir: str) -> str:
    """Format init session response with structured resume_context."""
    project_name = data.get('project_info', {}).get('name', Path(working_dir).name)

    lines = []

    # BUILD STRUCTURED RESUME CONTEXT (if available)
    resume_context = None
    suggested_opening = None

    if _resume_context_available and status != "new":
        try:
            # Get git hash for checkpoint
            git_hash = None
            try:
                result = subprocess.run(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=working_dir,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=no_window_creationflags(),
                )
                if result.returncode == 0:
                    git_hash = result.stdout.strip()
            except:
                pass

            # Build structured context from real saved state
            resume_context = build_resume_context(data, working_dir, git_hash)

            # Build human-readable opening from that context
            suggested_opening = build_suggested_opening(resume_context, language='he')

            # Add structured JSON block at the beginning
            lines.append("<!-- RESUME_CONTEXT_START -->")
            lines.append("```json")
            context_output = {
                "resume_context": resume_context,
                "suggested_opening": suggested_opening
            }
            lines.append(json.dumps(context_output, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("<!-- RESUME_CONTEXT_END -->")
            lines.append("")

        except Exception as e:
            _log(f"[FixOnce] Resume context build error: {e}")

    # LIVE ERRORS FIRST (Universal Gate principle) + AUTO-INJECT SOLUTIONS
    live_errors = _get_live_errors()
    if live_errors:
        lines.append("═══════════════════════════════════════")
        lines.append(f"## ⚠️ {len(live_errors)} LIVE ERRORS - FIX BEFORE PROCEEDING")
        lines.append("═══════════════════════════════════════")

        solutions_found = 0
        injected_solutions = set()  # Prevent duplicates

        for e in live_errors[:3]:
            msg = e.get('message', 'Unknown error')
            msg_short = msg[:70] if len(msg) > 70 else msg
            lines.append(f"• {msg_short}")

            # Auto-Inject Solutions (with quality controls)
            solution = _find_solution_for_error(msg)
            if solution:
                solution_key = solution['text'][:50]
                if solution_key not in injected_solutions:
                    solutions_found += 1
                    injected_solutions.add(solution_key)
                    lines.append(f"  💡 **Solved before ({solution['similarity']}%):** {solution['text'][:100]}...")

        if len(live_errors) > 3:
            lines.append(f"• ...and {len(live_errors) - 3} more")

        if solutions_found > 0:
            lines.append("")
            lines.append(f"✅ **{solutions_found} known fix(es).** Apply them.")
        else:
            lines.append("")
            lines.append("**You MUST address these errors before doing anything else.**")
        lines.append("")

    # Project info
    lines.extend([
        f"## Project: {project_name}",
        f"**Status:** {status.upper()}",
        f"**Path:** `{working_dir}`",
        ""
    ])

    # Fix #3: Session State Visibility
    session = _get_session()
    if session and session.initialized_at:
        session_id = hashlib.md5(f"{session.project_id}_{session.initialized_at}".encode()).hexdigest()[:8]
        start_time = session.initialized_at[:19].replace('T', ' ')
        tools_count = len(session.tool_calls)
        lines.append(f"**Session:** `{session_id}` | Started: {start_time} | Tools: {tools_count}")
        lines.append("")

    # Resume State - show if there's pending work from last session
    if _resume_state_available:
        try:
            project_id = _get_project_id(working_dir)
            resume_state = _get_resume_state(project_id)
            if resume_state:
                resume_section = format_resume_for_init(resume_state)
                if resume_section:
                    lines.append(resume_section)
        except Exception as e:
            _log(f"[FixOnce] Resume state error: {e}")

    # Multi-AI Handoff Summary
    ai_session = data.get("ai_session", {})
    previous_ai = ai_session.get("previous_ai")
    current_editor = ai_session.get("editor", "unknown")

    if previous_ai and previous_ai.get("editor") != current_editor:
        prev_editor = previous_ai.get("editor", "unknown").capitalize()
        prev_started = previous_ai.get("started_at", "")

        # Calculate how long ago
        if prev_started:
            try:
                prev_time = datetime.fromisoformat(prev_started.replace('Z', '+00:00'))
                now = datetime.now()
                if prev_time.tzinfo:
                    now = datetime.now(prev_time.tzinfo)
                diff_mins = int((now - prev_time).total_seconds() / 60)

                if diff_mins < 60:
                    time_ago = f"{diff_mins} דקות"
                elif diff_mins < 1440:
                    time_ago = f"{diff_mins // 60} שעות"
                else:
                    time_ago = f"{diff_mins // 1440} ימים"

                lines.append("---")
                lines.append(f"## 🔄 Handoff from {prev_editor}")
                lines.append(f"**{prev_editor}** worked here {time_ago} ago.")
                lines.append("")

                # Show recent activity from that AI
                recent_activities = _get_recent_activities_for_handoff(prev_editor.lower(), limit=3)
                if recent_activities:
                    lines.append("**Last actions:**")
                    for act in recent_activities:
                        lines.append(f"• {act}")
                    lines.append("")
                lines.append("---")
                lines.append("")
            except:
                pass  # Skip handoff if timestamp parsing fails

    # AI Queue - errors/tasks/commands sent from dashboard
    # Security Layer: Session Scope Guard + Explicit Marker Lock
    ai_queue = data.get("ai_queue", [])
    pending_items = [q for q in ai_queue if q.get("status") == "pending"]

    # Get current session ID for scope validation
    current_project_id = _get_project_id(working_dir)
    current_session_id = hashlib.md5(
        f"{current_project_id}_{session.initialized_at}".encode()
    ).hexdigest()[:8] if session.initialized_at else None

    # Filter items by scope (Session Scope Guard)
    # Only show commands meant for this project/session
    valid_items = []
    skipped_items = []
    for item in pending_items:
        item_project = item.get("project_id")
        item_session = item.get("session_id")

        # Scope validation: skip if command is for different project
        if item_project and item_project != current_project_id:
            skipped_items.append(item)
            continue

        # Session validation: warn but still show if different session
        # (user might have restarted AI but command is still valid)
        if item_session and item_session != current_session_id:
            item["_session_mismatch"] = True

        valid_items.append(item)

    # Separate action commands from regular items
    action_commands = [q for q in valid_items if q.get("type") == "action_command"]
    other_items = [q for q in valid_items if q.get("type") != "action_command"]

    # Show action commands first (user requested action from dashboard)
    if action_commands:
        lines.append("═══════════════════════════════════════")
        lines.append("## 🚀 ACTION REQUESTED FROM DASHBOARD")
        lines.append("═══════════════════════════════════════")
        lines.append("")
        lines.append("The user clicked an action button in the FixOnce dashboard.")
        lines.append("**Execute the following request:**")
        lines.append("")

        for cmd in action_commands[:1]:  # Show only the most recent command
            cmd_id = cmd.get("id", "unknown")
            msg = cmd.get("message", "")
            session_warning = " ⚠️ (different session)" if cmd.get("_session_mismatch") else ""
            lines.append(f"**Command ID:** `{cmd_id}`{session_warning}")
            lines.append("```")
            lines.append(msg)
            lines.append("```")

        lines.append("")
        lines.append("**This is a HIGH PRIORITY request. Execute it now.**")
        lines.append("")

    # Show other queued items
    if other_items:
        lines.append("---")
        lines.append("## 🎯 QUEUED FOR YOU")
        for item in other_items[:3]:
            item_id = item.get("id", "")
            item_type = item.get("type", "task")
            msg = item.get("message", "")[:80]
            source = item.get("source", "")
            line_num = item.get("line", "")

            if item_type == "error":
                lines.append(f"⚠️ **Error** `[{item_id}]`: `{msg}`")
                if source:
                    loc = source + (f":{line_num}" if line_num else "")
                    lines.append(f"   📍 {loc}")
            else:
                lines.append(f"📋 **Task** `[{item_id}]`: {msg}")

        lines.append("")
        lines.append("**Fix these first, then mark as handled.**")
        lines.append("")

    # Mark valid items as delivered with full audit trail (Explicit Marker Lock)
    if valid_items:
        project_id = _get_project_id(working_dir)
        now = datetime.now().isoformat()
        detected_editor = _detect_editor()

        # Initialize audit log if needed
        if "command_audit" not in data:
            data["command_audit"] = []

        for item in valid_items:
            # Mark as delivered (one-time delivery)
            item["status"] = "delivered"
            item["delivered_at"] = now
            item["delivered_to"] = detected_editor

            # Add audit entry
            audit_entry = {
                "id": item.get("id", "unknown"),
                "action": "delivered",
                "delivered_to": detected_editor,
                "timestamp": now,
                "session_id": current_session_id
            }
            audit_entry.update(_new_record_attribution("fo_init"))
            data["command_audit"].append(audit_entry)

        # Keep audit log bounded
        data["command_audit"] = data["command_audit"][-50:]
        _save_project(project_id, data)

    # Log skipped items (wrong project scope)
    if skipped_items:
        lines.append(f"_(Skipped {len(skipped_items)} commands from other projects)_")
        lines.append("")

    if status == "new":
        # New project onboarding - bilingual, welcoming
        lines.append("---")
        lines.append("## 🆕 New Project")
        lines.append("")
        lines.append("**FixOnce is now connected to this project.**")
        lines.append("")
        lines.append("From now on, I will remember:")
        lines.append("- 🔒 **Decisions** — architectural choices and their reasons")
        lines.append("- 💡 **Insights** — what we learned during development")
        lines.append("- ⚠️ **Avoid patterns** — mistakes we shouldn't repeat")
        lines.append("- 🐛 **Solutions** — how we fixed errors")
        lines.append("")
        lines.append("This knowledge persists across sessions, so we never lose context.")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("**Want me to scan the project?** I can detect the tech stack and structure.")
        lines.append("")
        lines.append("_Just say: 'scan' or 'סרוק'_")
        lines.append("")
    else:
        # Show existing context
        lr = data.get('live_record', {})

        # DECISIONS FIRST - Most important for respecting past choices
        all_decisions = data.get('decisions', [])
        # Filter out superseded decisions - only show active ones
        decisions = [d for d in all_decisions if not d.get('superseded')]
        superseded_count = len(all_decisions) - len(decisions)

        if decisions:
            lines.append("---")
            lines.append("## 🚨 ACTIVE DECISIONS - YOU MUST RESPECT THESE")
            lines.append("")
            lines.append("**STOP before any change that contradicts these decisions!**")
            lines.append("**Ask user for explicit override approval if request conflicts.**")
            lines.append("")
            # MCP DIET: Limit to 8 most recent decisions
            MAX_DECISIONS = 8
            decisions_to_show = decisions[-MAX_DECISIONS:]
            for dec in decisions_to_show:
                # Truncate long decisions
                dec_text = dec.get('decision', '')[:100]
                reason_text = dec.get('reason', '')[:80]
                lines.append(f"🔒 **{dec_text}**")
                lines.append(f"   _Reason: {reason_text}_")
                lines.append("")
            hidden_count = len(decisions) - len(decisions_to_show) + superseded_count
            if hidden_count > 0:
                lines.append(f"_(...{hidden_count} more decisions. Use `get_policy_status()` for full list)_")
                lines.append("")
            lines.append("---")
            lines.append("")

            # Mark decisions as displayed for compliance tracking
            session = _get_session()
            session.mark_decisions_displayed()
            _sync_compliance()

        # PROJECT RULES - User-defined behavioral rules
        project_rules = data.get('project_rules', [])
        enabled_rules = [r for r in project_rules if r.get('enabled', True)]
        if enabled_rules:
            lines.append("---")
            lines.append("## 📋 PROJECT RULES - FOLLOW THESE")
            lines.append("")
            for rule in enabled_rules:
                text = rule.get('text', '')
                is_default = rule.get('default', False)
                marker = "📌" if is_default else "✏️"
                lines.append(f"{marker} {text}")
            lines.append("")
            lines.append("---")
            lines.append("")

        # INSIGHTS - Check these BEFORE researching anything!
        # Use Memory Decay ranking to show most important insights
        insights = lr.get('lessons', {}).get('insights', [])
        if insights:
            # Get top 5 ranked insights (by importance, use_count, recency)
            top_insights = _get_ranked_insights(insights, limit=5)

            lines.append("---")
            lines.append("## 🧠 STORED INSIGHTS - CHECK BEFORE RESEARCHING")
            lines.append("")
            lines.append("**YOU ARE FORBIDDEN from external research if relevant insight exists below!**")
            lines.append("**If relevant → use it. If not → proceed with research.**")
            lines.append("")
            for ins in top_insights:
                text = ins.get('text', '')
                importance = ins.get('importance', 'medium')
                use_count = ins.get('use_count', 0)

                # Show importance indicator
                if importance == 'high':
                    prefix = "🔥"  # Hot/important
                elif use_count > 0:
                    prefix = "✓"   # Used before
                else:
                    prefix = "💡"  # Regular

                lines.append(f"{prefix} {text}")

            if len(insights) > 5:
                lines.append(f"_...and {len(insights) - 5} more. Use `fo_search()` to find specific ones._")
            lines.append("")
            lines.append("---")
            lines.append("")

        intent = lr.get('intent', {})
        if intent.get('current_goal'):
            lines.append(f"**Last Goal:** {intent['current_goal']}")

        arch = lr.get('architecture', {})
        if arch.get('summary'):
            lines.append(f"**Architecture:** {arch['summary']}")

        avoid = data.get('avoid', [])
        if avoid:
            lines.append(f"**Avoid:** {avoid[-1].get('what', '')}")

        lines.append("")
        lines.append("_Ask: 'נמשיך מכאן?'_")

    # Add recent activity
    activity_info = _get_recent_activity_summary(working_dir, limit=5)
    if activity_info:
        lines.append("")
        lines.append(activity_info)

    # Add browser errors if any
    errors_info = _get_browser_errors_summary(limit=3)
    if errors_info:
        lines.append("")
        lines.append(errors_info)

    # Add AI Context injection if active and elements selected
    ai_context = _get_ai_context_injection()
    if ai_context:
        lines.append("")
        lines.append(ai_context)

    return '\n'.join(lines)


@mcp.tool()
def init_session(working_dir: str = "", port: int = 0) -> str:
    """
    Initialize FixOnce session for the current project.

    Phase 1: Uses boundary detection to find actual project root.

    Args:
        working_dir: The absolute path to the project directory (use cwd)
        port: OR a port number - will auto-detect the working directory from it

    Returns:
        Session info with project_status ('new' or 'existing')
    """
    mode = _get_fixonce_mode()
    if mode == MODE_OFF:
        return "FixOnce is off. Proceed normally without FixOnce tools."
    if mode == MODE_PASSIVE:
        return "FixOnce is in PASSIVE mode. Session initialization is disabled."

    # If port given, detect working_dir from it
    if port and not working_dir:
        detected = _get_working_dir_from_port(port)
        if detected:
            working_dir = detected
        else:
            return f"Error: Could not detect project directory from port {port}. Is a server running?"

    resolved_dir = _resolve_init_working_dir(working_dir)
    if resolved_dir and resolved_dir != working_dir:
        _log(f"[MCP] init_session: {working_dir} → {resolved_dir}")

    if not resolved_dir:
        return f"Error: Invalid project directory: {working_dir}"

    return _do_init_session(resolved_dir)


@mcp.tool()
def detect_project_from_port(port: int) -> str:
    """
    Detect which project directory is running on a given port.

    Args:
        port: The port number to check (e.g., 5000, 3000)

    Returns:
        The detected project path, or error message
    """
    detected = _get_working_dir_from_port(port)
    if detected:
        return f"Port {port} → `{detected}`"
    else:
        return f"No process found on port {port}"


@mcp.tool()
def scan_project() -> str:
    """
    Scan the current project directory.
    Use this for NEW projects after user approves.

    Returns:
        Scan results (technologies, structure, etc.)
    """
    session = _get_session()
    if not session.is_active():
        return "Error: No active session. Call fo_init() first."

    working_dir = session.working_dir

    lines = [f"# Scanning: {Path(working_dir).name}", ""]

    # Detect technologies
    tech_files = {
        'package.json': 'Node.js/JavaScript',
        'requirements.txt': 'Python',
        'pyproject.toml': 'Python',
        'Cargo.toml': 'Rust',
        'go.mod': 'Go',
        'pom.xml': 'Java',
        'Gemfile': 'Ruby',
        'tsconfig.json': 'TypeScript',
        'docker-compose.yml': 'Docker',
        'Dockerfile': 'Docker'
    }

    found_tech = []
    for file, tech in tech_files.items():
        if os.path.exists(os.path.join(working_dir, file)):
            found_tech.append(tech)

    if found_tech:
        lines.append(f"**Stack:** {', '.join(set(found_tech))}")
        lines.append("")

    # List directories
    lines.append("**Structure:**")
    try:
        dirs = sorted([d for d in os.listdir(working_dir)
                      if os.path.isdir(os.path.join(working_dir, d))
                      and not d.startswith('.')])[:10]
        for d in dirs:
            lines.append(f"- 📁 {d}/")
    except Exception as e:
        lines.append(f"_Error reading directory: {e}_")

    lines.append("")

    # Check for README
    for readme in ['README.md', 'README.txt', 'README']:
        readme_path = os.path.join(working_dir, readme)
        if os.path.exists(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read(500)
                lines.append("**README preview:**")
                lines.append(f"```\n{content}\n```")
            except:
                pass
            break

    lines.append("")
    lines.append("---")
    lines.append("Now call `fo_sync()` to save this info.")

    return '\n'.join(lines)


@mcp.tool()
def update_live_record(section: str, data: str) -> str:
    """
    Update a section of the Live Record.

    Args:
        section: One of 'gps', 'architecture', 'intent', 'lessons', 'vision'
        data: JSON string with the data to update

    For 'lessons', use: {"insight": "..."} or {"failed_attempt": "..."}
    These APPEND to the list.

    For 'architecture', use: {"summary": "...", "stack": "...", "key_flows": [...]}
    - summary: Short description of what this project is
    - stack: Technologies used (e.g., "React, Node.js, MongoDB")
    - key_flows: Main user flows or features

    For 'intent', use: {"current_goal": "...", "work_area": "...", "why": "...", "last_change": "...", "last_file": "..."}
    - current_goal: What we're currently working on
    - work_area: Feature/module area (e.g., "session resume / opening UX")
    - why: Why this work matters
    - last_change: Description of the most recent change
    - last_file: Last file that was worked on
    - next_step: What should be done next

    For 'vision', use project-level purpose and guardrails:
    {"mission": "...", "current_direction": "...", "non_negotiables": ["..."], "success_criteria": ["..."], "out_of_scope": ["..."], "reason": "..."}

    For other sections, data REPLACES the section.
    """
    error, context = _universal_gate("update_live_record")
    if error:
        return error

    session = _get_session()
    # Track goal updates for compliance
    if section == 'intent':
        session.mark_goal_updated()
        _sync_compliance()

    try:
        update_data = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError:
        return f"Error: Invalid JSON: {data}"
    if not isinstance(update_data, dict):
        return "Error: data must be a JSON object."

    project_id = session.project_id
    memory = _load_project(project_id)

    if 'live_record' not in memory:
        memory['live_record'] = {}

    lr = memory['live_record']

    # PRE-ACTION INTELLIGENCE: Track any warnings
    pre_action_warning = ""

    if section == 'lessons':
        # APPEND mode with Memory Decay tracking
        if 'lessons' not in lr:
            lr['lessons'] = {'insights': [], 'failed_attempts': [], 'archived': []}

        if 'insight' in update_data:
            # PRE-ACTION: Check for similar existing insights
            new_text = update_data['insight'].lower()
            for existing in lr['lessons'].get('insights', []):
                existing_text = _normalize_insight(existing).get('text', '').lower()
                # Check for significant word overlap
                new_words = set(new_text.split())
                existing_words = set(existing_text.split())
                overlap = new_words & existing_words - {'the', 'a', 'is', 'in', 'to', 'and', 'of'}
                if len(overlap) >= 4:  # At least 4 meaningful words in common
                    pre_action_warning = f"\n💡 **Similar insight exists:** {existing_text[:50]}..."
                    break

            # Fix #2: Auto-Link Incidents - check for active errors
            active_errors = _get_live_errors()
            linked_error = active_errors[0] if active_errors else None

            # Create insight with full decay metadata (+ linked error if exists)
            new_insight = _create_insight(update_data['insight'], linked_error=linked_error)
            lr['lessons']['insights'].append(new_insight)

            # Auto-index for semantic search
            semantic = _load_project_semantic()
            if semantic:
                try:
                    semantic["index_insight"](project_id, update_data['insight'])
                except Exception as e:
                    _log(f"[SemanticIndex] Failed to index insight: {e}")

            # Fix #2: Notify about the link
            if linked_error:
                pre_action_warning += f"\n🔗 **Auto-linked to error:** {linked_error.get('message', '')[:50]}..."

            _maybe_record_solved_bug_from_memory_event(
                memory,
                source="auto_classified:insight",
                problem=update_data.get('insight', ''),
                solution=update_data.get('insight', ''),
            )

        if 'failed_attempt' in update_data:
            # Failed attempts also get metadata - marked as type to prevent decay
            new_attempt = _create_insight(update_data['failed_attempt'])
            new_attempt['type'] = 'failed_attempt'  # Will NEVER be archived
            lr['lessons']['failed_attempts'].append(new_attempt)
    elif section == 'vision':
        reason = update_data.get("reason", "") if isinstance(update_data, dict) else ""
        vision_updates = {
            key: value
            for key, value in update_data.items()
            if _normalize_vision_key(key)
        }
        changed = _update_vision_memory(memory, vision_updates, reason=reason)
        audit = _audit_project_vision(memory)
        pre_action_warning += f"\nVision audit: {audit['status']}"
        if audit.get("issues"):
            pre_action_warning += f" ({', '.join(audit['issues'])})"
        if changed == 0:
            pre_action_warning += "\nNo valid vision fields were provided."
    elif section == 'intent':
        # INTENT mode - track goal history
        if 'intent' not in lr:
            lr['intent'] = {}

        # POLICY ENFORCEMENT: Check for blocked components when setting new goal
        new_goal = update_data.get('current_goal', '')
        if new_goal and _policy_available:
            components = lr.get('architecture', {}).get('components', [])
            blocked_relevant = check_blocked_components(new_goal, components)
            gate_result = _evaluate_current_risk_gate(
                tool_name="update_live_record",
                blocked_components_relevant=len(blocked_relevant)
            )
            if gate_result.level in {"warn", "block"}:
                blocked_names = [b['name'] for b in blocked_relevant]
                pre_action_warning += f"\n⚠️ **BLOCKED COMPONENTS MAY AFFECT THIS GOAL:**\n"
                for b in blocked_relevant:
                    pre_action_warning += f"  🔴 **{b['name']}**: {b.get('desc', '')[:50]}\n"
                pre_action_warning += "Consider unblocking these first, or adjust the goal."

        # Save previous goal to history before replacing
        old_goal = lr['intent'].get('current_goal', '')
        if old_goal and old_goal != update_data.get('current_goal', ''):
            if 'goal_history' not in lr['intent']:
                lr['intent']['goal_history'] = []
            lr['intent']['goal_history'].insert(0, {
                'goal': old_goal,
                'completed_at': datetime.now().isoformat(),
                **_new_record_attribution("update_live_record"),
            })
            # Keep only last 5 goals
            lr['intent']['goal_history'] = lr['intent']['goal_history'][:5]

        # Update intent with new data
        lr['intent'].update(update_data)
        lr['intent'].update(_new_record_attribution("update_live_record"))
        # Always update timestamp when intent changes
        lr['intent']['updated_at'] = datetime.now().isoformat()
        _maybe_record_solved_bug_from_memory_event(
            memory,
            source="auto_classified:intent",
            problem=update_data.get('current_goal') or update_data.get('last_change', ''),
            solution=" ".join(
                str(update_data.get(key, ""))
                for key in ("last_change", "why", "next_step", "last_file")
                if update_data.get(key)
            ),
            files_changed=[update_data.get('last_file', '')] if update_data.get('last_file') else [],
        )
    else:
        # REPLACE mode for other sections
        if section not in lr:
            lr[section] = {}
        lr[section].update(update_data)

    lr['updated_at'] = datetime.now().isoformat()
    _save_project(project_id, memory)

    # Log MCP activity for dashboard
    _log_mcp_activity("update_live_record", {
        "section": section,
        "goal": update_data.get("current_goal", "") if section == "intent" else "",
        "insight": update_data.get("insight", "")[:50] if section == "lessons" else "",
        "failed_attempt": bool(update_data.get("failed_attempt")) if section == "lessons" else False
    })

    # Add browser errors reminder if any
    reminder = _get_browser_errors_reminder()

    # ALWAYS prepend context header (shows live errors!)
    return context + f"Updated {section}{pre_action_warning}{reminder}"


def _normalize_next_step(next_step: str) -> str:
    """
    Normalize next_step to be a short, single continuation prompt.

    Rules:
    - One short actionable continuation only
    - No numbered lists
    - No multi-step instructions
    - Max ~80 chars
    """
    import re

    if not next_step:
        return ""

    text = next_step.strip()

    # If it's a numbered list, extract just the first item's action
    # Pattern: "1) Action 2) Action" or "1. Action 2. Action"
    numbered_pattern = r'^[1-9][).]\s*'
    if re.match(numbered_pattern, text):
        # Split on numbered items and take just the first action
        parts = re.split(r'\s+[2-9][).]\s*', text, maxsplit=1)
        text = re.sub(numbered_pattern, '', parts[0]).strip()

    # Remove common verbose prefixes
    verbose_prefixes = [
        'Continue with:', 'Continue to:', 'Next:', 'Then:',
        'You should:', 'Please:', 'Now:', 'First:'
    ]
    for prefix in verbose_prefixes:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()

    # Truncate to reasonable length (aim for ~80 chars)
    if len(text) > 100:
        # Try to cut at a natural break point
        cut_point = text.rfind(' ', 0, 80)
        if cut_point > 40:
            text = text[:cut_point].rstrip('.,;:')
        else:
            text = text[:80].rstrip('.,;:')

    return text


@mcp.tool()
def update_work_context(
    current_goal: str = "",
    work_area: str = "",
    why: str = "",
    last_change: str = "",
    last_file: str = "",
    next_step: str = ""
) -> str:
    """
    Update work context for better session continuity.

    This tool updates the structured context that appears in opening messages.
    Call this when starting new work or after completing a significant change.

    Args:
        current_goal: What you're currently working on (e.g., "Improve opening UX")
        work_area: Feature/module area (e.g., "session resume / opening UX")
        why: Why this work matters (e.g., "Users should feel the AI remembers them")
        last_change: What was just done (e.g., "Added work_area field to opening message")
        last_file: Last file worked on (e.g., "CLAUDE.md")
        next_step: Short continuation prompt (e.g., "Test the fix", "Verify dashboard opens")
                   NOT numbered lists or multi-step instructions

    At minimum, update current_goal when starting new work.
    Update last_change and last_file after completing changes.
    """
    return _update_work_context_impl(
        tool_name="update_work_context",
        current_goal=current_goal,
        work_area=work_area,
        why=why,
        last_change=last_change,
        last_file=last_file,
        next_step=next_step,
    )


def _update_work_context_impl(
    tool_name: str,
    current_goal: str = "",
    work_area: str = "",
    why: str = "",
    last_change: str = "",
    last_file: str = "",
    next_step: str = "",
) -> str:
    """Internal implementation shared by update_work_context and fo_sync."""
    error, context = _universal_gate(tool_name)
    if error:
        return error

    session = _get_session()

    # Build update data from non-empty fields
    update_data = {}
    if current_goal:
        update_data['current_goal'] = current_goal
    if work_area:
        update_data['work_area'] = work_area
    if why:
        update_data['why'] = why
    if last_change:
        update_data['last_change'] = last_change
    if last_file:
        update_data['last_file'] = last_file

    if not update_data and not next_step:
        return "Error: No fields provided to update"

    # Always refresh next_step (clear stale values)
    update_data['next_step'] = _normalize_next_step(next_step) if next_step else ""
    update_data.update(_new_record_attribution(tool_name))

    # Update the intent section
    project_id = session.project_id
    memory = _load_project(project_id)

    if 'live_record' not in memory:
        memory['live_record'] = {}
    if 'intent' not in memory['live_record']:
        memory['live_record']['intent'] = {}

    # Track goal updates for compliance
    if current_goal:
        session.mark_goal_updated()
        _sync_compliance()

    memory['live_record']['intent'].update(update_data)
    memory['live_record']['intent']['updated_at'] = datetime.now().isoformat()
    memory['live_record']['updated_at'] = datetime.now().isoformat()

    _save_project(project_id, memory)
    _evaluate_current_completion_gate(
        tool_name=tool_name,
        significant_work_completed=True,
        sync_recorded=True,
    )

    # Keep sync quiet: dashboard reads fresh intent directly from project memory,
    # so logging every sync call adds noise without improving continuity.
    return "Synced."


def _lightweight_tool_gate(tool_name: str, sync_compliance: bool = True) -> Optional[str]:
    """Minimal session gate for hot-path tools that must not block on context assembly."""
    current_mode = _get_fixonce_mode()
    if current_mode == MODE_OFF:
        return "FixOnce is off. Proceed normally without FixOnce tools."
    if current_mode == MODE_PASSIVE:
        return "FixOnce is in PASSIVE mode. Write/action tools are disabled until mode returns to FULL."
    if not _is_session_initialized():
        return _get_init_enforcement_error()

    session = _get_session()
    if not session.is_active() and not _auto_create_session():
        return "Error: No active project session found. Call fo_init() again."

    session = _get_session()
    try:
        session.log_tool_call(tool_name)
        if sync_compliance:
            _sync_compliance()
    except Exception as exc:
        _log(f"[FixOnce] Lightweight gate compliance update failed: {exc}")

    return None


def _load_project_lightweight(project_id: str) -> Dict[str, Any]:
    path = _get_project_path(project_id)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    bases = getattr(_project_load_state, "bases", {})
    bases[project_id] = copy.deepcopy(data)
    _project_load_state.bases = bases
    return data


def _save_project_lightweight(project_id: str, data: Dict[str, Any]) -> None:
    path = _get_project_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _safe_file_available:
        bases = getattr(_project_load_state, "bases", {})
        base = bases.get(project_id, {})
        saved_data = durable_memory_write(
            path,
            updated=data,
            base=base,
            attribution=_new_record_attribution("memory_write"),
            tool_name="memory_write",
            create_backup=False,
        )
        bases[project_id] = copy.deepcopy(saved_data)
        _project_load_state.bases = bases
        return
    fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except Exception:
            pass
        raise


def _update_work_context_lightweight(
    tool_name: str,
    current_goal: str = "",
    work_area: str = "",
    why: str = "",
    last_change: str = "",
    last_file: str = "",
    next_step: str = "",
) -> str:
    error = _lightweight_tool_gate(tool_name)
    if error:
        return error

    update_data = {}
    if current_goal:
        update_data['current_goal'] = current_goal
    if work_area:
        update_data['work_area'] = work_area
    if why:
        update_data['why'] = why
    if last_change:
        update_data['last_change'] = last_change
    if last_file:
        update_data['last_file'] = last_file

    if not update_data and not next_step:
        return "Error: No fields provided to update"

    update_data['next_step'] = _normalize_next_step(next_step) if next_step else ""
    update_data.update(_new_record_attribution(tool_name))

    session = _get_session()
    if current_goal:
        session.mark_goal_updated()
        _sync_compliance()

    memory = _load_project_lightweight(session.project_id)
    memory.setdefault('live_record', {})
    memory['live_record'].setdefault('intent', {})
    memory['live_record']['intent'].update(update_data)
    memory['live_record']['intent']['updated_at'] = datetime.now().isoformat()
    memory['live_record']['updated_at'] = datetime.now().isoformat()
    _maybe_record_solved_bug_from_memory_event(
        memory,
        source="auto_classified:fo_sync",
        problem=update_data.get('current_goal') or update_data.get('last_change', ''),
        solution=" ".join(
            str(update_data.get(key, ""))
            for key in ("last_change", "why", "next_step", "last_file")
            if update_data.get(key)
        ),
        files_changed=[update_data.get('last_file', '')] if update_data.get('last_file') else [],
    )

    _save_project_lightweight(session.project_id, memory)

    # Update AI connection activity so dashboard reflects ongoing work
    _persist_ai_connection(_resolve_actor_identity(), project_id=session.project_id)

    # Log to activity feed for dashboard visibility
    _log_mcp_activity(tool_name, {
        "last_change": update_data.get("last_change", ""),
        "next_step": update_data.get("next_step", ""),
    })

    return "Synced."


@mcp.tool()
def sync_to_active_project() -> str:
    """
    Sync this AI to the currently active project.

    Use this when:
    - You're in Cursor but want to join the project Claude is working on
    - You opened the wrong folder but want to work on the active FixOnce project
    - You want to enable Multi-AI collaboration

    This will:
    1. Find the active project from FixOnce dashboard
    2. Initialize session for that project
    3. Show handoff info from previous AI (if different)

    Returns:
        Session info for the active project with handoff summary
    """
    try:
        from core.boundary_detector import _load_active_project
        active = _load_active_project()
        active_working_dir = active.get("working_dir")
        active_id = active.get("active_id")

        if not active_working_dir or not os.path.isdir(active_working_dir):
            return """❌ No active project found.

Use the FixOnce dashboard to select a project first,
or call init_session(working_dir="/path/to/project")"""

        # Get current editor
        detected_editor = _detect_editor()

        # Log the sync
        _log(f"[MCP] Multi-AI Sync: {detected_editor} joining project at {active_working_dir}")

        # Initialize with the active project
        return _do_init_session(active_working_dir)

    except Exception as e:
        return f"❌ Sync failed: {str(e)}"


@mcp.tool()
def get_live_record() -> str:
    """Get the current Live Record (summarized to save tokens)."""
    error, context = _universal_gate("get_live_record")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)
    lr = memory.get('live_record', {})

    # === MCP DIET v2: Aggressive but smart summarization ===

    # 1. Components: Only show non-stable/non-done (these need attention)
    all_components = lr.get("architecture", {}).get("components", [])
    STABLE_STATUSES = {"stable", "done"}
    active_components = [
        {"name": c.get("name"), "status": c.get("status")}
        for c in all_components
        if c.get("status") not in STABLE_STATUSES
    ]
    stable_count = len(all_components) - len(active_components)

    # 2. Insights: Strip metadata, keep only text and linked_error
    all_insights = lr.get("lessons", {}).get("insights", [])
    recent_insights = [
        {"text": ins.get("text")} | ({"linked_error": ins["linked_error"]} if ins.get("linked_error") else {})
        for ins in all_insights[-5:]
    ]

    # 3. Failed attempts: Same treatment
    all_failed = lr.get("lessons", {}).get("failed_attempts", [])
    recent_failed = [{"text": f.get("text")} for f in all_failed[-3:]]

    # 4. Intent: Limit goal_history to 3
    intent = lr.get("intent", {}).copy()
    if "goal_history" in intent:
        intent["goal_history"] = intent["goal_history"][-3:]

    summarized = {
        "gps": lr.get("gps", {}),
        "intent": intent,
        "architecture": {
            "summary": lr.get("architecture", {}).get("summary", ""),
            "stack": lr.get("architecture", {}).get("stack", ""),
            "components": active_components,
            "stable_count": stable_count
        },
        "lessons": {
            "insights": {"recent": recent_insights, "total": len(all_insights)},
            "failed_attempts": {"recent": recent_failed, "total": len(all_failed)}
        }
    }

    # Context header + summarized data
    return context + json.dumps(summarized, indent=2, ensure_ascii=False)


@mcp.tool()
def log_decision(decision: str, reason: str, force: bool = False) -> str:
    """
    Log an architectural decision. Decisions NEVER decay - they are permanent.

    Args:
        decision: The decision text
        reason: Why this decision was made
        force: If True, override conflict detection and log anyway

    Returns:
        Success message or BLOCK message if conflict detected
    """
    error, context = _universal_gate("log_decision")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    if 'decisions' not in memory:
        memory['decisions'] = []

    # POLICY ENFORCEMENT: Check for conflicts
    policy_message = ""
    if _policy_available:
        # Filter to active decisions only for validation
        active_decisions = [d for d in memory['decisions'] if not d.get('superseded')]

        # Extract vision non-negotiables and avoid patterns for validation
        vision = _ensure_vision_store(memory)
        non_negotiables = _active_vision_items(vision, "non_negotiables")
        avoid_patterns = [p for p in memory.get("avoid", []) if isinstance(p, dict)]

        decision_gate_evaluator = None
        if _intervention_policy_available:
            decision_gate_evaluator = lambda ctx: _evaluate_current_decision_conflict_gate(
                tool_name="log_decision",
                decision_conflict_severity=ctx.decision_conflict_severity,
                conflicts=ctx.extra.get("conflicts", []),
                intent=decision,
            )
        is_valid, message, conflicts = validate_decision(
            decision, reason, active_decisions,
            non_negotiables=non_negotiables,
            avoid_patterns=avoid_patterns,
            force=force, gate_evaluator=decision_gate_evaluator
        )

        _log(f"[PolicyEngine] Validating: {decision[:50]}...")
        _log(f"[PolicyEngine] Against {len(active_decisions)} active decisions")
        _log(f"[PolicyEngine] Result: is_valid={is_valid}, conflicts={len(conflicts)}")

        if conflicts:
            _persist_detected_decision_conflicts(
                session.project_id,
                conflicts,
                decision,
                reason,
                resolve_as_override=bool(force),
            )

        if not is_valid:
            # BLOCK the decision - return error
            return context + f"\n{message}\n\nDecision NOT logged."

        if conflicts:
            policy_message = f"\n{message}"

    else:
        # Fallback: simple word overlap check
        decision_lower = decision.lower()
        for existing in memory['decisions']:
            if existing.get("superseded"):
                continue
            existing_text = existing.get('decision', '').lower()
            decision_words = set(decision_lower.split())
            existing_words = set(existing_text.split())
            overlap = decision_words & existing_words
            if len(overlap) >= 3:
                policy_message = f"\n⚠️ **Similar decision exists:** {existing.get('decision', '')[:60]}..."
                break

    # Log the decision
    decision_record = {
        "type": "decision",
        "decision": decision,
        "reason": reason,
        "expected_benefit": "",
        "timestamp": datetime.now().isoformat(),
        "importance": "permanent",
        "forced": force if force else None
    }
    decision_record.update(_new_record_attribution("fo_decide"))
    memory['decisions'].append(_attach_memory_quality_audit("decision", decision_record))
    _maybe_record_solved_bug_from_memory_event(
        memory,
        source="auto_classified:decision",
        problem=decision,
        solution=reason or decision,
    )

    _save_project(session.project_id, memory)

    # Log MCP activity for dashboard
    _log_mcp_activity("log_decision", {
        "decision": decision[:50],
        "reason": reason[:50],
        "forced": force
    })

    # Auto-index for semantic search
    semantic = _load_project_semantic()
    if semantic:
        try:
            semantic["index_decision"](session.project_id, decision, reason)
        except Exception as e:
            _log(f"[SemanticIndex] Failed to index decision: {e}")

    return context + f"Logged decision: {decision}" + policy_message


@mcp.tool()
def log_avoid(what: str, reason: str) -> str:
    """Log something to avoid. Avoid patterns NEVER decay - they are permanent."""
    error, context = _universal_gate("log_avoid")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    if 'avoid' not in memory:
        memory['avoid'] = []

    avoid_record = {
        "type": "avoid",  # Marked as avoid - will NEVER be archived
        "what": what,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "importance": "permanent"  # Avoid patterns never decay
    }
    avoid_record.update(_new_record_attribution("fo_decide"))
    memory['avoid'].append(_attach_memory_quality_audit("avoid", avoid_record))

    _save_project(session.project_id, memory)

    # Log MCP activity for dashboard
    _log_mcp_activity("log_avoid", {
        "what": what[:50],
        "reason": reason[:50]
    })

    # Auto-index for semantic search
    semantic = _load_project_semantic()
    if semantic:
        try:
            semantic["index_avoid"](session.project_id, what, reason)
        except Exception as e:
            _log(f"[SemanticIndex] Failed to index avoid: {e}")

    return context + f"Logged avoid: {what}"


@mcp.tool()
def supersede_decision(
    old_decision: str,
    new_decision: str = "",
    new_reason: str = "",
    supersede_reason: str = ""
) -> str:
    """
    Supersede (replace) an existing decision with a new one.

    Use this when:
    - A previous decision was wrong or outdated
    - Requirements changed and old decision no longer applies
    - You need to resolve a policy conflict

    Args:
        old_decision: Text of the decision to supersede (partial match OK)
        new_decision: The new decision (optional - leave empty to just deprecate)
        new_reason: Reason for the new decision
        supersede_reason: Why the old decision is being superseded

    Returns:
        Success message or error if decision not found
    """
    error, context = _universal_gate("supersede_decision")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    if 'decisions' not in memory or not memory['decisions']:
        return context + "No decisions found to supersede."

    if not _policy_available:
        return context + "Policy engine not available. Cannot supersede decisions."

    attribution = _new_record_attribution("fo_decide")
    success, message, updated_decisions = do_supersede(
        memory['decisions'],
        old_decision,
        new_decision,
        new_reason,
        supersede_reason or "Superseded via MCP tool",
        attribution=attribution,
    )

    if not success:
        return context + f"❌ {message}"

    memory['decisions'] = updated_decisions
    memory, _ = resolve_decision_conflicts(
        memory,
        status="superseded",
        action="decision_superseded",
        reason=supersede_reason or "Superseded via MCP tool",
        attribution=attribution,
        existing_decision_text=old_decision,
    )
    _save_project(session.project_id, memory)

    # Log MCP activity
    _log_mcp_activity("supersede_decision", {
        "old": old_decision[:30],
        "new": new_decision[:30] if new_decision else "(deprecated)"
    })

    result = f"✅ {message}"
    if new_decision:
        result += f"\n📝 New decision: {new_decision}"

    return context + result


@mcp.tool()
def get_policy_status() -> str:
    """
    Get current policy status including active decisions, conflicts, and blocked components.

    Returns summary of:
    - Active vs superseded decisions
    - Blocked components that need attention
    - Any detected policy issues
    """
    error, context = _universal_gate("get_policy_status")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    decisions = memory.get('decisions', [])
    components = memory.get('live_record', {}).get('architecture', {}).get('components', [])

    if _policy_available:
        status = format_policy_status(decisions, components)
    else:
        active = [d for d in decisions if not d.get('superseded')]
        superseded = [d for d in decisions if d.get('superseded')]
        blocked = [c for c in components if c.get('status') == 'blocked']

        status = f"## Policy Status\n\n"
        status += f"**Active Decisions:** {len(active)}\n"
        status += f"**Superseded:** {len(superseded)}\n"
        status += f"**Blocked Components:** {len(blocked)}"

        if blocked:
            status += "\n\n### ⚠️ Blocked Components\n"
            for comp in blocked:
                status += f"- **{comp.get('name')}**: {comp.get('desc', 'No description')}\n"

    return context + status


@mcp.tool()
def update_component_status(name: str, status: str, desc: str = "") -> str:
    """
    Update a component's status in the System Tree.

    Use this at the end of tasks to reflect progress:
    - When you finish implementing something → status="done"
    - When you start working on something → status="in_progress"
    - When something is blocked → status="blocked"
    - When something is planned but not started → status="not_started"

    If the component doesn't exist, it will be created.

    Args:
        name: Component name (e.g., "Policy Engine", "Dashboard")
        status: One of: "done", "in_progress", "not_started", "blocked"
        desc: Optional description update
    """
    error, context = _universal_gate("update_component_status")
    if error:
        return error

    valid_statuses = ["done", "in_progress", "not_started", "blocked"]
    if status not in valid_statuses:
        return f"❌ Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"

    session = _get_session()
    memory = _load_project(session.project_id)
    attribution = _new_record_attribution("fo_component")

    # Ensure live_record and architecture exist
    if 'live_record' not in memory:
        memory['live_record'] = {}
    if 'architecture' not in memory['live_record']:
        memory['live_record']['architecture'] = {"components": [], "key_flows": [], "summary": "", "stack": ""}

    arch = memory['live_record']['architecture']
    if 'components' not in arch:
        arch['components'] = []

    components = arch['components']

    # Find existing component or create new one
    found = False
    for comp in components:
        if comp.get('name', '').lower() == name.lower():
            old_status = comp.get('status', 'unknown')
            comp['status'] = status
            if desc:
                comp['desc'] = desc
            comp['updated_at'] = datetime.now().isoformat()
            comp['updated_by'] = attribution["actor"]
            comp['update_source'] = attribution["actor_source"]
            comp.update(attribution)
            found = True
            action = f"Updated '{name}': {old_status} → {status}"
            break

    if not found:
        # Create new component
        new_comp = {
            "name": name,
            "status": status,
            "desc": desc or f"Added by AI",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "updated_by": attribution["actor"],
            "update_source": attribution["actor_source"],
        }
        new_comp.update(attribution)
        components.append(new_comp)
        action = f"Created '{name}' with status: {status}"

    # Keep max 30 components (newest ones if over limit)
    if len(components) > 30:
        arch['components'] = components[-30:]
    else:
        arch['components'] = components
    arch['updated_at'] = datetime.now().isoformat()
    if status == "done":
        _maybe_record_solved_bug_from_memory_event(
            memory,
            source="auto_classified:component_status",
            problem=name,
            solution=desc or action,
        )

    _save_project(session.project_id, memory)

    # Log MCP activity for dashboard
    _log_mcp_activity("update_component_status", {
        "name": name,
        "status": status
    })
    _evaluate_current_completion_gate(
        tool_name="update_component_status",
        component_changed=True,
        component_status_updated=True,
    )

    # Status icons for display
    icons = {"done": "🟢", "in_progress": "🟡", "not_started": "⚪", "blocked": "🔴",
             "stable": "🟢", "building": "🟡", "broken": "🔴"}
    icon = icons.get(status, "⚪")

    return context + f"{icon} {action}"


@mcp.tool()
def mark_component_stable(name: str, files: str = "") -> str:
    """
    Mark a component as STABLE and create a checkpoint for rollback.

    This records the current git commit as the "last known good" state.
    If the component breaks later, you can rollback to this checkpoint.

    Args:
        name: Component name (e.g., "API Server", "Dashboard")
        files: Comma-separated list of files belonging to this component (optional)
               Example: "src/api/server.py,src/api/routes.py"

    Returns:
        Confirmation with commit hash
    """
    error, context = _universal_gate("mark_component_stable")
    if error:
        return error

    from core.component_stability import (
        mark_component_stable as do_mark_stable,
        add_files_to_component,
        get_current_commit
    )

    session = _get_session()
    memory = _load_project(session.project_id)
    actor_identity = _resolve_actor_identity()

    # Get project path for git operations
    gps = memory.get("live_record", {}).get("gps", {})
    repo_path = gps.get("working_dir", "")

    if not repo_path:
        return context + "[ERROR] No project path. Run fo_init first."

    # Find component
    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    found_idx = None
    for i, comp in enumerate(components):
        if comp.get("name", "").lower() == name.lower():
            found_idx = i
            break

    if found_idx is None:
        return context + f"[ERROR] Component '{name}' not found. Create it first with update_component_status."

    component = components[found_idx]

    # Add files if provided
    if files:
        file_list = [f.strip() for f in files.split(",") if f.strip()]
        component = add_files_to_component(component, file_list)

    # Mark as stable and record commit
    marked_by = actor_identity.get("editor", "unknown")
    component = do_mark_stable(component, repo_path, marked_by)

    # Save back
    components[found_idx] = component
    arch["components"] = components
    arch["updated_at"] = datetime.now().isoformat()
    memory["live_record"]["architecture"] = arch
    _save_project(session.project_id, memory)

    # Log activity
    _log_mcp_activity("mark_component_stable", {"name": name})

    # Build response
    last_stable = component.get("last_stable", {})
    commit_short = last_stable.get("commit_short", "unknown")
    file_count = len(component.get("files", []))

    result = f"[STABLE] {name} marked as stable\n"
    result += f"Checkpoint: {commit_short}\n"
    if file_count > 0:
        result += f"Files tracked: {file_count}\n"
    result += "You can now rollback to this state if needed."

    return context + result


@mcp.tool()
def rollback_component(name: str, mode: str = "files") -> str:
    """
    Rollback a component to its last stable state.

    Two modes available:
    - "files": Restore specific files to their stable state (default)
    - "branch": Create a new branch from the stable commit

    Args:
        name: Component name to rollback
        mode: "files" (restore files) or "branch" (create rollback branch)

    Returns:
        Result of rollback operation
    """
    error, context = _universal_gate("rollback_component")
    if error:
        return error

    from core.component_stability import (
        rollback_files,
        create_rollback_branch
    )

    session = _get_session()
    memory = _load_project(session.project_id)

    # Get project path
    gps = memory.get("live_record", {}).get("gps", {})
    repo_path = gps.get("working_dir", "")

    if not repo_path:
        return context + "[ERROR] No project path. Run fo_init first."

    # Find component
    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    component = None
    for comp in components:
        if comp.get("name", "").lower() == name.lower():
            component = comp
            break

    if not component:
        return context + f"[ERROR] Component '{name}' not found."

    # Check if has stable checkpoint
    last_stable = component.get("last_stable")
    if not last_stable:
        return context + f"[ERROR] No stable checkpoint for '{name}'. Mark it stable first."

    commit_hash = last_stable.get("commit_hash")
    if not commit_hash:
        return context + f"[ERROR] Invalid checkpoint for '{name}'."

    # Perform rollback based on mode
    if mode == "branch":
        result = create_rollback_branch(repo_path, commit_hash)
        if result["success"]:
            return context + f"[OK] Created rollback branch: {result['branch']}\nFrom commit: {commit_hash[:8]}"
        else:
            return context + f"[ERROR] Failed to create branch: {result.get('error', 'Unknown error')}"

    else:  # files mode
        files = component.get("files", [])
        if not files:
            return context + f"[ERROR] No files tracked for '{name}'. Add files with mark_component_stable first."

        result = rollback_files(repo_path, commit_hash, files)

        if result["success"]:
            restored_count = len(result["restored"])
            return context + f"[OK] Restored {restored_count} files to stable state\nCommit: {commit_hash[:8]}\nFiles: {', '.join(result['restored'][:5])}{'...' if restored_count > 5 else ''}"
        else:
            error_msgs = [e["error"] for e in result["errors"][:3]]
            return context + f"[ERROR] Rollback failed:\n" + "\n".join(error_msgs)


@mcp.tool()
def check_component_changes(name: str) -> str:
    """
    Check if a stable component has been modified since its checkpoint.

    Use this before AI modifies a stable component to warn the user.

    Args:
        name: Component name to check

    Returns:
        Status: unchanged, modified (with list of changed files), or no checkpoint
    """
    error, context = _universal_gate("check_component_changes")
    if error:
        return error

    from core.component_stability import check_component_stability

    session = _get_session()
    memory = _load_project(session.project_id)

    # Get project path
    gps = memory.get("live_record", {}).get("gps", {})
    repo_path = gps.get("working_dir", "")

    # Find component
    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    component = None
    for comp in components:
        if comp.get("name", "").lower() == name.lower():
            component = comp
            break

    if not component:
        return context + f"[ERROR] Component '{name}' not found."

    if not component.get("last_stable"):
        return context + f"[INFO] '{name}' has no stable checkpoint. Nothing to compare."

    result = check_component_stability(component, repo_path)

    if not result["is_stable"]:
        return context + f"[INFO] '{name}' is not marked as stable (status: {component.get('status', 'unknown')})"

    if result["modified_since_checkpoint"]:
        changed = result["changed_files"]
        msg = f"[WARNING] '{name}' has been modified since stable checkpoint!\n"
        msg += f"Changed files ({len(changed)}):\n"
        for f in changed[:10]:
            msg += f"  - {f}\n"
        if len(changed) > 10:
            msg += f"  ... and {len(changed) - 10} more\n"
        msg += "\nYou can rollback with: rollback_component(\"{name}\")"
        return context + msg

    return context + f"[OK] '{name}' is stable and unchanged since checkpoint."


@mcp.tool()
def add_component_files(name: str, files: str) -> str:
    """
    Add files to a component's tracked file list.

    These files will be restored when you rollback the component.

    Args:
        name: Component name
        files: Comma-separated list of file paths
               Example: "src/api/server.py,src/api/routes.py"

    Returns:
        Updated file list
    """
    error, context = _universal_gate("add_component_files")
    if error:
        return error

    from core.component_stability import add_files_to_component

    session = _get_session()
    memory = _load_project(session.project_id)

    # Find component
    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    found_idx = None
    for i, comp in enumerate(components):
        if comp.get("name", "").lower() == name.lower():
            found_idx = i
            break

    if found_idx is None:
        return context + f"[ERROR] Component '{name}' not found."

    # Parse and add files
    file_list = [f.strip() for f in files.split(",") if f.strip()]
    if not file_list:
        return context + "[ERROR] No valid files provided."

    component = components[found_idx]
    component = add_files_to_component(component, file_list)
    component["updated_at"] = datetime.now().isoformat()

    # Save
    components[found_idx] = component
    arch["components"] = components
    memory["live_record"]["architecture"] = arch
    _save_project(session.project_id, memory)

    all_files = component.get("files", [])
    return context + f"[OK] Added {len(file_list)} files to '{name}'\nTotal tracked: {len(all_files)}"


@mcp.tool()
def get_stability_report() -> str:
    """
    Get a summary of component stability across the project.

    Shows:
    - How many components are stable/building/broken
    - Which have checkpoints (can rollback)
    - Which track files

    Returns:
        Stability report
    """
    error, context = _universal_gate("get_stability_report")
    if error:
        return error

    from core.component_stability import get_stability_summary

    session = _get_session()
    memory = _load_project(session.project_id)

    arch = memory.get("live_record", {}).get("architecture", {})
    components = arch.get("components", [])

    if not components:
        return context + "[INFO] No components defined yet."

    summary = get_stability_summary(components)

    report = "## Component Stability Report\n\n"
    report += f"Total components: {summary['total']}\n"
    report += f"  Stable: {summary['stable']}\n"
    report += f"  Building: {summary['building']}\n"
    report += f"  Broken: {summary['broken']}\n"
    report += f"\nWith checkpoints (can rollback): {summary['with_checkpoints']}\n"
    report += f"With file tracking: {summary['with_files']}\n"

    # List components with their status
    report += "\n### Components:\n"
    icons = {"stable": "[OK]", "done": "[OK]", "building": "[...]", "in_progress": "[...]",
             "broken": "[X]", "blocked": "[X]", "not_started": "[ ]"}

    for comp in components:
        status = comp.get("status", "building")
        icon = icons.get(status, "[ ]")
        name = comp.get("name", "Unknown")
        has_checkpoint = "[checkpoint]" if comp.get("last_stable") else ""
        file_count = len(comp.get("files", []))
        files_info = f"[{file_count} files]" if file_count > 0 else ""

        report += f"  {icon} {name} {has_checkpoint} {files_info}\n"

    return context + report


@mcp.tool()
def auto_discover_components(apply: bool = False) -> str:
    """
    Automatically discover components from the codebase.

    Scans the project's source code and identifies:
    - API modules and blueprints
    - Major classes (Managers, Engines, Providers)
    - Extension files
    - Dashboard files

    Args:
        apply: If True, add discovered components to the System Tree

    Returns:
        List of discovered components with suggestions
    """
    error, context = _universal_gate("auto_discover_components")
    if error:
        return error

    try:
        from core.auto_discovery import suggest_components

        session = _get_session()
        memory = _load_project(session.project_id)

        # Get project path
        gps = memory.get("live_record", {}).get("gps", {})
        project_path = gps.get("working_dir", "")

        if not project_path:
            return context + "❌ No project path found. Run fo_init first."

        # Get existing components
        existing = memory.get("live_record", {}).get("architecture", {}).get("components", [])

        # Run discovery
        result = suggest_components(project_path, existing)

        if "error" in result:
            return context + f"❌ {result['error']}"

        suggestions = result.get("suggestions", [])

        if not suggestions:
            return context + f"✅ No new components found. All {len(existing)} components are up to date."

        # Apply if requested
        if apply:
            arch = memory.setdefault("live_record", {}).setdefault("architecture", {})
            components = arch.setdefault("components", [])

            for suggestion in suggestions:
                new_comp = {
                    "name": suggestion["name"],
                    "status": suggestion.get("suggested_status", "done"),
                    "desc": suggestion.get("suggested_desc", "Auto-discovered"),
                    "source": suggestion.get("source", ""),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "auto_discovered": True
                }
                components.append(new_comp)

            arch["updated_at"] = datetime.now().isoformat()
            _save_project(session.project_id, memory)

            _log_mcp_activity("auto_discover_components", {
                "added": len(suggestions),
                "applied": True
            })

            return context + f"✅ Added {len(suggestions)} components:\n" + "\n".join(
                f"  🟢 {s['name']} ({s.get('source', 'unknown')})" for s in suggestions
            )

        # Just show suggestions
        lines = [f"🔍 Found {len(suggestions)} new components:\n"]
        for s in suggestions:
            conf = "⭐" if s.get("confidence") == "high" else "○"
            lines.append(f"  {conf} {s['name']} - {s.get('source', 'unknown')}")

        lines.append(f"\nRun with apply=True to add them to the System Tree.")

        return context + "\n".join(lines)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return context + f"❌ Error: {e}"


@mcp.tool()
def get_latest_changes() -> str:
    """
    Get the latest changes - unified source of truth.

    Returns canonical "latest change" using this priority:
    1. Activity feed (file edits < 10 min)
    2. Git commit (< 30 min)
    3. Current goal (fallback)

    Use this when user asks "what's the latest change" or "what happened recently".
    """
    error, context = _universal_gate("get_latest_changes")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id) if session.project_id else {}
    now = datetime.now()

    result = {
        "latest_activity": None,
        "latest_git": None,
        "latest_goal": None,
        "canonical": None
    }

    # 1. Check activity log (canonical path: USER_DATA_DIR / "activity_log.json")
    try:
        activity_file = USER_DATA_DIR / "activity_log.json"
        if activity_file.exists():
            with open(activity_file, 'r', encoding='utf-8') as f:
                activity_data = json.load(f)
            activities = activity_data.get("activities", [])
            if activities:
                latest = activities[-1]
                result["latest_activity"] = {
                    "file": latest.get("human_name") or latest.get("file"),
                    "tool": latest.get("tool"),
                    "timestamp": latest.get("timestamp"),
                    "actor": latest.get("editor", "unknown")
                }
    except:
        pass

    # 2. Check git
    try:
        working_dir = memory.get("project_info", {}).get("working_dir")
        if working_dir and Path(working_dir).exists():
            import subprocess
            git_result = subprocess.run(
                ["git", "log", "-1", "--format=%s|%ai"],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=no_window_creationflags(),
            )
            if git_result.returncode == 0 and git_result.stdout.strip():
                parts = git_result.stdout.strip().split("|")
                if len(parts) >= 2:
                    result["latest_git"] = {
                        "message": parts[0],
                        "timestamp": parts[1]
                    }
    except:
        pass

    # 3. Get current goal
    intent = memory.get("live_record", {}).get("intent", {})
    result["latest_goal"] = intent.get("current_goal")

    # Determine canonical latest
    canonical_text = None
    canonical_source = None

    # Priority 1: Activity (< 10 min)
    if result["latest_activity"]:
        try:
            act_ts = result["latest_activity"]["timestamp"]
            act_dt = datetime.fromisoformat(act_ts.replace('Z', ''))
            if (now - act_dt).total_seconds() < 600:
                canonical_text = f"נערך {result['latest_activity']['file']}"
                canonical_source = "activity"
        except:
            pass

    # Priority 2: Git (< 30 min)
    if not canonical_text and result["latest_git"]:
        try:
            git_ts = result["latest_git"]["timestamp"]
            git_dt = datetime.strptime(git_ts.split()[0] + " " + git_ts.split()[1], "%Y-%m-%d %H:%M:%S")
            if (now - git_dt).total_seconds() < 1800:
                canonical_text = f"commit: {result['latest_git']['message'][:50]}"
                canonical_source = "git"
        except:
            pass

    # Priority 3: Goal (fallback)
    if not canonical_text and result["latest_goal"]:
        canonical_text = f"מטרה: {result['latest_goal']}"
        canonical_source = "intent"

    if not canonical_text:
        canonical_text = "אין פעילות אחרונה"
        canonical_source = "none"

    result["canonical"] = {
        "text": canonical_text,
        "source": canonical_source
    }

    # Format output
    output = f"""📊 Latest Changes (Unified):

🎯 Canonical: {canonical_text}
   (source: {canonical_source})

📝 Activity: {result['latest_activity']['file'] if result['latest_activity'] else 'None'}
🔀 Git: {result['latest_git']['message'][:40] if result['latest_git'] else 'None'}
🎯 Goal: {result['latest_goal'] or 'None'}
"""
    return context + output


@mcp.tool()
def log_debug_session(
    problem: str,
    root_cause: str,
    solution: str,
    files_changed: str = "",
    symptoms: str = "",
    lesson_learned: str = "",
) -> str:
    """
    Log a completed debug session. Use this when:
    1. There was a REAL problem (not just a question)
    2. There was a debugging PROCESS (investigation, trial/error)
    3. There is a CLEAR solution (not just "it works now")
    4. Files were CHANGED to fix it

    This creates a structured problem→solution record that prevents
    repeating the same debugging session in the future.

    Args:
        problem: Short description of the problem (e.g., "Cursor לא מזהה MCP tools")
        root_cause: The actual cause found (e.g., "Cursor requires project folder to be open")
        solution: What fixed it (e.g., "Open project folder, start new chat")
        files_changed: Comma-separated list of files that were modified
        symptoms: Comma-separated list of error messages/symptoms seen
        lesson_learned: What future agents should learn from this fix
    """
    error, context = _universal_gate("log_debug_session")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    # Initialize debug_sessions if needed
    if 'debug_sessions' not in memory:
        memory['debug_sessions'] = []

    # Parse comma-separated strings to lists
    files_list = [f.strip() for f in files_changed.split(",") if f.strip()] if files_changed else []
    symptoms_list = [s.strip() for s in symptoms.split(",") if s.strip()] if symptoms else []

    # Create debug session
    debug_session = {
        "id": f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "problem": problem,
        "root_cause": root_cause,
        "solution": solution,
        "lesson_learned": lesson_learned,
        "symptoms": symptoms_list,
        "files_changed": files_list,
        "resolved_at": datetime.now().isoformat(),
        "importance": "high"  # Debug sessions are always important
    }
    debug_session.update(_new_record_attribution("fo_solved"))
    _attach_memory_quality_audit("debug_session", debug_session)

    # Check for duplicate/similar debug sessions
    problem_lower = problem.lower()
    for existing in memory['debug_sessions']:
        existing_problem = existing.get('problem', '').lower()
        # Simple word overlap check
        problem_words = set(problem_lower.split())
        existing_words = set(existing_problem.split())
        overlap = problem_words & existing_words
        if len(overlap) >= 3:
            return context + f"⚠️ Similar debug session already exists: '{existing.get('problem', '')[:50]}...'\nNot creating duplicate."

    memory['debug_sessions'].append(debug_session)

    # Mark related insights as consolidated (optional cleanup)
    # Find insights from today that might be related
    today = datetime.now().strftime('%Y-%m-%d')
    consolidated_count = 0
    if 'live_record' in memory and 'lessons' in memory['live_record']:
        insights = memory['live_record']['lessons'].get('insights', [])
        for i, insight in enumerate(insights):
            if isinstance(insight, dict):
                insight_time = insight.get('timestamp', '')
                insight_text = insight.get('text', '').lower()
                # Check if insight is from today and related to this debug session
                if today in insight_time:
                    # Check word overlap with problem or solution
                    insight_words = set(insight_text.split())
                    problem_words = set(problem_lower.split())
                    solution_words = set(solution.lower().split())
                    if len(insight_words & problem_words) >= 2 or len(insight_words & solution_words) >= 2:
                        insight['consolidated_into'] = debug_session['id']
                        consolidated_count += 1

    _save_project(session.project_id, memory)

    result = f"""✅ Debug session logged!

🐛 **Problem:** {problem}
🎯 **Root cause:** {root_cause}
✅ **Solution:** {solution}
📁 **Files:** {', '.join(files_list) if files_list else 'None specified'}
"""
    if lesson_learned:
        result += f"🧠 **Lesson learned:** {lesson_learned}\n"
    if consolidated_count > 0:
        result += f"\n📦 Consolidated {consolidated_count} related insights into this session."

    return context + result


@mcp.tool()
def solution_applied(
    error_message: str,
    solution: str,
    files_changed: str = ""
) -> str:
    """
    Quick way to record that you fixed an error.

    Call this AFTER you fix a browser error or bug. This creates a
    solution record that will be:
    1. Stored in project memory
    2. Committed to .fixonce/solutions.json
    3. Surfaced next time a similar error appears

    This is simpler than log_debug_session() - use this for quick fixes.

    Args:
        error_message: The error message you just fixed (copy from browser errors)
        solution: What you did to fix it (1-2 sentences)
        files_changed: Comma-separated list of files you modified

    Example:
        solution_applied(
            "Cannot read property 'map' of undefined",
            "Added null check before mapping the array",
            "src/components/List.tsx"
        )
    """
    error, context = _universal_gate("solution_applied")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    # Initialize debug_sessions if needed
    if 'debug_sessions' not in memory:
        memory['debug_sessions'] = []

    # Parse files
    files_list = [f.strip() for f in files_changed.split(",") if f.strip()] if files_changed else []
    # Create solution record (same structure as debug_session for compatibility)
    solution_record = {
        "id": f"fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "problem": error_message[:200],  # Truncate long errors
        "root_cause": "",  # Not required for quick fixes
        "solution": solution,
        "lesson_learned": "",
        "symptoms": [error_message[:100]],  # Use error as symptom for matching
        "files_changed": files_list,
        "resolved_at": datetime.now().isoformat(),
        "importance": "high",  # All fixes are important
        "reuse_count": 0
    }
    attribution = _new_record_attribution("fo_solved")
    solution_record.update(attribution)
    _attach_memory_quality_audit("solution", solution_record)

    # Check for duplicate (same error already solved)
    error_lower = error_message.lower()[:100]
    for existing in memory['debug_sessions']:
        existing_problem = existing.get('problem', '').lower()[:100]
        if error_lower in existing_problem or existing_problem in error_lower:
            # Update reuse_count instead of creating duplicate
            existing['reuse_count'] = existing.get('reuse_count', 0) + 1
            existing['solution'] = solution  # Update with latest solution
            existing['files_changed'] = files_list or existing.get('files_changed', [])
            existing.setdefault("actor", attribution["actor"])
            existing.setdefault("actor_source", attribution["actor_source"])
            existing.setdefault("actor_confidence", attribution["actor_confidence"])
            existing.setdefault("session_id", attribution["session_id"])
            existing.setdefault("tool_name", attribution["tool_name"])
            _attach_memory_quality_audit("solution", existing)
            _save_project(session.project_id, memory)
            # Minimal response
            return "Solution updated."

    memory['debug_sessions'].append(solution_record)
    _save_project(session.project_id, memory)

    # Also save to semantic engine for auto-apply matching
    try:
        from core.semantic_engine import get_engine
        from config import PERSONAL_DB_PATH
        engine = get_engine(PERSONAL_DB_PATH)
        engine.save_solution(error_message, solution)
        _log(f"[fo_solved] Saved to semantic engine: {error_message[:50]}...")
    except Exception as e:
        _log(f"[fo_solved] Semantic engine save failed: {e}")

    # Track ROI
    _track_roi_event("solution_saved")

    # Log activity for dashboard Recent line
    try:
        import requests
        # Shorten error for display (first meaningful part)
        short_error = error_message.split('\n')[0][:50].strip()
        if len(error_message) > 50:
            short_error += '...'

        requests.post(
            "http://localhost:5000/api/activity/log",
            json={
                "type": "mcp_tool",
                "tool": "fo_solved",
                "human_name": f"Fixed: {short_error}",
                "file_context": "fix",
                "project_id": session.project_id,
                "cwd": session.cwd,
                "editor": attribution["actor"],
                "actor_source": attribution["actor_source"],
                "actor_confidence": attribution["actor_confidence"],
            },
            timeout=2
        )
    except Exception:
        pass  # Don't fail the main operation

    _evaluate_current_completion_gate(
        tool_name="solution_applied",
        bug_fix_completed=True,
        fo_solved_called=True,
    )

    # Minimal response (no context header noise)
    return "Solution saved."


def _calculate_similarity(query: str, text: str) -> int:
    """Calculate simple word-based similarity percentage."""
    query_words = _memory_tokens(query)
    text_words = _memory_tokens(text)
    if not query_words:
        return 0
    matches = len(query_words & text_words)
    return min(100, int((matches / len(query_words)) * 100))


def _find_solution_for_error(error_message: str, min_similarity: int = 50, min_keyword_matches: int = 2) -> Optional[dict]:
    """
    Auto-find a matching solution for an error message.

    This is the core of Fix #1: Auto-Inject Solutions.
    When an error is detected, automatically search for existing solutions.

    Quality controls:
    - Requires minimum 2 keyword matches to avoid false positives
    - Higher similarity threshold (50%) for better precision

    Args:
        error_message: The error message to search for
        min_similarity: Minimum similarity % to consider a match (default 50)
        min_keyword_matches: Minimum keyword matches required (default 2)

    Returns:
        Dict with solution info if found, None otherwise
    """
    session = _get_session()
    if not session or not session.project_id:
        return None

    try:
        memory = _load_project(session.project_id)
        if not memory:
            return None

        lessons = memory.get('live_record', {}).get('lessons', {})
        insights = lessons.get('insights', [])

        if not insights:
            return None

        # Extract keywords from error message (remove common noise)
        error_lower = error_message.lower()
        noise_words = {'error', 'failed', 'cannot', 'undefined', 'null', 'is', 'not',
                       'the', 'a', 'an', 'to', 'of', 'in', 'at', 'on', 'for', 'with',
                       'file', 'found', 'could', 'was', 'been', 'has', 'have', 'from'}
        error_words = set(error_lower.split()) - noise_words

        best_match = None
        best_score = 0
        best_keyword_matches = 0

        for insight in insights:
            normalized = _normalize_insight(insight)
            text = normalized.get('text', '').lower()

            # Calculate similarity
            similarity = _calculate_similarity(error_message, text)

            # Count keyword matches (quality gate #1: avoid false positives)
            text_words = set(text.split())
            keyword_matches = len(error_words & text_words)

            # Skip if not enough keyword matches
            if keyword_matches < min_keyword_matches:
                continue

            bonus = keyword_matches * 10
            total_score = similarity + bonus

            if total_score > best_score and total_score >= min_similarity:
                best_score = total_score
                use_count = normalized.get('use_count', 0)
                timestamp = normalized.get('timestamp', '')
                linked_error = normalized.get('linked_error')

                best_match = {
                    'text': normalized.get('text', ''),
                    'similarity': min(100, total_score),
                    'confidence': min(95, 50 + (use_count * 10)),
                    'date': timestamp[:10] if timestamp else 'unknown',
                    'use_count': use_count,
                    'linked_error': linked_error  # Fix #2: Include linked error info
                }

        # Also search debug_sessions (solutions) - these are higher quality
        debug_sessions = memory.get('debug_sessions', [])
        for session in debug_sessions:
            problem = session.get('problem', '').lower()
            solution = session.get('solution', '')
            symptoms = [s.lower() for s in session.get('symptoms', [])]

            # Check keyword matches in problem
            problem_words = set(problem.split()) - noise_words
            keyword_matches = len(error_words & problem_words)

            # Also check symptoms
            symptom_match = any(s in error_lower for s in symptoms if s)

            if keyword_matches >= min_keyword_matches or symptom_match:
                similarity = _calculate_similarity(error_message, problem)
                bonus = keyword_matches * 15  # Higher bonus for debug sessions
                if symptom_match:
                    bonus += 20
                total_score = similarity + bonus

                if total_score > best_score and total_score >= min_similarity:
                    best_score = total_score
                    best_match = {
                        'text': f"Problem: {session.get('problem', '')}\nSolution: {solution}",
                        'similarity': min(100, total_score),
                        'confidence': 90,  # High confidence for debug sessions
                        'date': session.get('resolved_at', '')[:10] if session.get('resolved_at') else 'unknown',
                        'use_count': session.get('reuse_count', 1),
                        'source': 'debug_session',
                        'files_changed': session.get('files_changed', [])
                    }

        gate_result = _evaluate_current_repeat_bug_gate(
            tool_name="_find_solution_for_error",
            similar_past_solution_found=bool(best_match)
        )
        if gate_result.level == "warn":
            return best_match
        return None

    except Exception:
        return None


def _format_smart_override(insight: dict, query: str) -> dict:
    """Format insight as Smart Override with metadata."""
    text = insight.get('text', '')
    timestamp = insight.get('timestamp', insight.get('last_used', ''))
    use_count = insight.get('use_count', 0)

    # Calculate confidence based on use_count and recency
    confidence = min(95, 50 + (use_count * 10))
    similarity = _calculate_similarity(query, text)

    # Extract date
    date_str = timestamp[:10] if timestamp else "unknown"

    return {
        "text": text,
        "confidence": confidence,
        "similarity": similarity,
        "timestamp": timestamp,
        "date": date_str,
        "use_count": use_count,
        "type": "insight",
        "actor": _memory_actor(insight),
        "status": _trust_status("insight", insight),
    }


def _search_result_priority(item: Dict[str, Any]) -> int:
    item_type = str(item.get("type", "")).lower()
    return {
        "solution": 500,
        "solved bug": 500,
        "avoid": 450,
        "decision": 425,
        "failed_attempt": 400,
        "component_history": 250,
        "insight": 200,
        "context_update": 100,
        "activity": 50,
    }.get(item_type, 150)


def _search_specificity_score(query_words: set, item: Dict[str, Any]) -> int:
    """Prefer records that match specific query terms over generic process memories."""
    text = str(item.get("text", ""))
    text_words = _memory_tokens(text)
    if not query_words or not text_words:
        return 0

    overlap = query_words & text_words
    score = len(overlap) * 20
    if len(overlap) == len(query_words):
        score += 80

    diagnostic_terms = {
        "bug", "broken", "crash", "error", "exception", "fail", "failure",
        "invalid", "missing", "null", "regression", "timeout", "traceback",
        "undefined",
    }
    score += len(overlap & diagnostic_terms) * 25

    rare_specific_terms = {
        token for token in query_words
        if len(token) >= 6 and token not in diagnostic_terms
    }
    score += len(overlap & rare_specific_terms) * 15

    item_type = str(item.get("type", "")).lower()
    if item_type in {"solution", "solved bug"} and (overlap & (diagnostic_terms | rare_specific_terms)):
        score += 60
    if item_type in {"decision", "context_update"} and not (overlap & (diagnostic_terms | rare_specific_terms)):
        score -= 20
    return score


def _search_match(
    text: str,
    match_type: str,
    similarity: int,
    confidence: Any,
    source: Optional[Dict[str, Any]] = None,
    timestamp_keys: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    source = source or {}
    timestamp_keys = timestamp_keys or ["timestamp", "created_at", "resolved_at", "updated_at"]
    timestamp = _coalesce_timestamp(source, *timestamp_keys)
    item = {
        "text": text,
        "confidence": confidence,
        "similarity": similarity,
        "timestamp": timestamp,
        "date": timestamp[:10] if timestamp else "unknown",
        "actor": _memory_actor(source),
        "status": _trust_status(match_type, source),
        "type": match_type,
    }
    item.update(extra)
    return item


def _format_search_provenance(item: Dict[str, Any]) -> str:
    return (
        "Trust: "
        f"source_type={item.get('type', 'memory')}; "
        f"actor={item.get('actor', 'source unknown')}; "
        f"timestamp={_format_trust_timestamp(item.get('timestamp') or item.get('date', ''))}; "
        f"status={item.get('status', 'active')}; "
        f"confidence={item.get('confidence', 'unknown')}"
    )


def _format_search_result_text(item: Dict[str, Any], mode: str = "compact") -> str:
    text = item.get("text", "")
    if (mode or "compact").lower() == "expanded":
        return str(text)
    return _compact_text(text, 420)


@mcp.tool()
def search_past_solutions(query: str, mode: str = "compact") -> str:
    """Search for past solutions matching the query."""
    error = _lightweight_tool_gate("search_past_solutions", sync_compliance=False)
    if error:
        return error
    context = ""

    session = _get_session()
    memory = _load_project_lightweight(session.project_id)

    # Search in lessons
    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    failed = lessons.get('failed_attempts', [])

    query_lower = query.lower()
    query_words = _memory_tokens(query_lower)
    matched_insights = []
    matched_indices = []
    memory_changed = False

    # === SEMANTIC SEARCH (if available) ===
    semantic_results = []
    semantic = _load_project_semantic(allow_cold_start=False)
    if semantic:
        try:
            future = _tool_executor.submit(
                semantic["search_project"],
                session.project_id,
                query,
                k=5,
                min_score=0.3,
            )
            semantic_results = future.result(timeout=_SEMANTIC_SEARCH_TIMEOUT_SECONDS)
            if isinstance(semantic_results, str):
                _log(f"[SemanticSearch] Error result: {semantic_results}")
                semantic_results = []
            _log(f"[SemanticSearch] Found {len(semantic_results)} results for '{query}'")
        except FutureTimeoutError:
            _log(f"[SemanticSearch] Timeout after {_SEMANTIC_SEARCH_TIMEOUT_SECONDS}s, falling back to string match")
            semantic_results = []
        except Exception as e:
            _log(f"[SemanticSearch] Error: {e}, falling back to string match")
            semantic_results = []

    # If semantic search found results, use them
    if semantic_results:
        for result in semantic_results:
            # Find the original insight to update use count
            for i, insight in enumerate(insights):
                normalized = _normalize_insight(insight)
                if normalized.get('text', '') == result.text:
                    override = _format_smart_override(normalized, query)
                    # Add semantic score
                    override['similarity'] = int(result.score * 100)
                    matched_insights.append(override)
                    matched_indices.append(i)
                    _mark_insight_used(normalized)
                    insights[i] = normalized
                    break
            else:
                # Result from index but not in current insights (decision/avoid)
                matched_insights.append(_search_match(
                    result.text,
                    result.metadata.get('doc_type', 'insight'),
                    int(result.score * 100),
                    80,
                    result.metadata,
                    timestamp_keys=["created_at", "timestamp", "updated_at"],
                    use_count=0,
                ))

    # === FALLBACK: String matching (if no semantic results) ===
    if not matched_insights:
        for i, insight in enumerate(insights):
            normalized = _normalize_insight(insight)
            insight_text = normalized.get('text', '')

            if _memory_text_matches(query_lower, query_words, insight_text):
                override = _format_smart_override(normalized, query)
                matched_insights.append(override)
                matched_indices.append(i)
                _mark_insight_used(normalized)
                insights[i] = normalized

    # Search failed attempts (always string match) - add to matched_insights for visibility
    for attempt in failed:
        normalized = _normalize_insight(attempt)
        attempt_text = normalized.get('text', '')

        if _memory_text_matches(query_lower, query_words, attempt_text):
            # Exact substring match = high similarity (beats semantic guesses)
            matched_insights.append(_search_match(
                f"❌ **Failed attempt:** {attempt_text}",
                "failed_attempt",
                85,  # Exact match beats semantic
                90,
                normalized,
                use_count=normalized.get('use_count', 0),
            ))

    # === CRITICAL: Search debug_sessions (solutions from solution_applied) ===
    debug_sessions = memory.get('debug_sessions', [])
    noise_words = {'error', 'failed', 'cannot', 'undefined', 'null', 'is', 'not',
                   'the', 'a', 'an', 'to', 'of', 'in', 'at', 'on', 'for', 'with',
                   'file', 'found', 'could', 'was', 'been', 'has', 'have', 'from'}
    query_words = query_words - noise_words

    for ds in debug_sessions:
        problem = ds.get('problem', '').lower()
        solution = ds.get('solution', '')
        root_cause = ds.get("root_cause", "")
        lesson_learned = ds.get("lesson_learned", "")
        symptoms = [s.lower() for s in ds.get('symptoms', [])]
        combined = f"{problem} {root_cause} {solution} {lesson_learned} {' '.join(symptoms)}"

        # Check for keyword matches
        problem_words = _memory_tokens(problem) - noise_words
        keyword_matches = len(query_words & problem_words)

        # Also check symptoms
        symptom_match = any(s in query_lower for s in symptoms if s)

        # Match if enough keyword overlap or symptom match
        if keyword_matches >= 2 or symptom_match or _memory_text_matches(query_lower, query_words, combined):
            similarity = max(_calculate_similarity(query, problem), _calculate_similarity(query, solution))
            text = f"🐛 **Problem:** {ds.get('problem', '')}"
            if root_cause:
                text += f"\n🧭 **Root cause:** {root_cause}"
            text += f"\n✅ **Solution:** {solution}"
            if lesson_learned:
                text += f"\n🧠 **Lesson learned:** {lesson_learned}"
            matched_insights.append(_search_match(
                text,
                "solution",
                max(similarity, 70 if symptom_match else 50),
                90,
                ds,
                timestamp_keys=["resolved_at", "timestamp", "created_at", "updated_at"],
                use_count=ds.get('reuse_count', 1),
                files_changed=ds.get('files_changed', []),
            ))
            # Update reuse count
            ds['reuse_count'] = ds.get('reuse_count', 0) + 1
            memory_changed = True

    # === Search DECISIONS ===
    decisions = memory.get('decisions', [])
    for dec in decisions:
        if dec.get('superseded'):
            continue  # Skip superseded decisions

        dec_text = dec.get('decision', '').lower()
        dec_reason = dec.get('reason', '').lower()
        combined = f"{dec_text} {dec_reason}"

        # Check for keyword matches in decision or reason
        if _memory_text_matches(query_lower, query_words, combined):
            # Exact substring match = high similarity (beats semantic guesses)
            matched_insights.append(_search_match(
                f"🔒 **Decision:** {dec.get('decision', '')}\n📝 **Reason:** {dec.get('reason', '')}",
                "decision",
                max(70, _calculate_similarity(query, combined)),
                95,
                dec,
                use_count=0,
            ))

    # === Search AVOID patterns ===
    avoids = memory.get('avoid', [])
    for av in avoids:
        av_text = av.get('what', '').lower()
        av_reason = av.get('reason', '').lower()
        combined = f"{av_text} {av_reason}"

        if _memory_text_matches(query_lower, query_words, combined):
            # Exact substring match = high similarity (beats semantic guesses)
            matched_insights.append(_search_match(
                f"⛔ **Avoid:** {av.get('what', '')}\n📝 **Reason:** {av.get('reason', '')}",
                "avoid",
                max(70, _calculate_similarity(query, combined)),
                95,
                av,
                use_count=0,
            ))

    # === Search current intent and goal history ===
    intent = memory.get('live_record', {}).get('intent', {})
    intent_parts = [
        intent.get('current_goal', ''),
        intent.get('work_area', ''),
        intent.get('why', ''),
        intent.get('last_change', ''),
        intent.get('last_file', ''),
        intent.get('next_step', ''),
    ]
    for item in intent.get('goal_history', []):
        if isinstance(item, dict):
            intent_parts.append(item.get('goal', ''))
    intent_text = " ".join(str(part or "") for part in intent_parts)
    if _memory_text_matches(query_lower, query_words, intent_text):
        matched_insights.append(_search_match(
            f"🎯 **Context update:** {intent_text[:300]}",
            "context_update",
            max(55, _calculate_similarity(query, intent_text)),
            75,
            intent,
            timestamp_keys=["updated_at", "timestamp", "created_at"],
            use_count=0,
        ))

    # === Search component history ===
    components = memory.get('live_record', {}).get('architecture', {}).get('components', [])
    for comp in components:
        comp_parts = [comp.get('name', ''), comp.get('status', ''), comp.get('desc', '')]
        for hist in comp.get('history', []):
            if isinstance(hist, dict):
                comp_parts.extend([hist.get('action', ''), hist.get('desc', '')])
        comp_text = " ".join(str(part or "") for part in comp_parts)
        if _memory_text_matches(query_lower, query_words, comp_text):
            matched_insights.append(_search_match(
                f"🧩 **Component history:** {comp.get('name', '')}\n{comp.get('desc', '')}",
                "component_history",
                max(60, _calculate_similarity(query, comp_text)),
                80,
                comp,
                timestamp_keys=["updated_at", "timestamp", "created_at"],
                use_count=0,
            ))

    # === Search recent activity without converting it into solved bugs ===
    activity_items = memory.get('activity_log', [])
    try:
        activity_file = USER_DATA_DIR / "activity_log.json"
        if activity_file.exists():
            with activity_file.open("r", encoding="utf-8") as handle:
                activity_items.extend(json.load(handle).get("activities", [])[:100])
    except Exception:
        activity_items = memory.get('activity_log', [])
    for activity in activity_items[:100]:
        if not isinstance(activity, dict):
            continue
        activity_text = " ".join(
            str(activity.get(key, "") or "")
            for key in ("human_name", "tool", "file", "cwd", "command", "file_context")
        )
        if _memory_text_matches(query_lower, query_words, activity_text):
            matched_insights.append(_search_match(
                f"📌 **Activity:** {activity_text[:300]}",
                "activity",
                max(50, _calculate_similarity(query, activity_text)),
                65,
                activity,
                use_count=0,
            ))

    # Save updated use counts
    if matched_indices or memory_changed:
        _save_project_lightweight(session.project_id, memory)

    if matched_insights:
        _track_roi_event("solution_reused")

        # Minimal output - just the best match
        matched_insights.sort(
            key=lambda item: (
                _search_result_priority(item),
                _search_specificity_score(query_words, item),
                item.get('similarity', 0),
                item.get('confidence', 0),
            ),
            reverse=True,
        )
        best = matched_insights[0]
        expanded = (mode or "compact").lower() == "expanded"
        lines = [f"Found {len(matched_insights)} match(es). Best ({best['similarity']}%, {best.get('type', 'memory')}):"]
        lines.append(f"> {_format_search_result_text(best, mode)}")
        lines.append(_format_search_provenance(best))
        if expanded and len(matched_insights) > 1:
            lines.append("")
            lines.append("## Additional Matches")
            for item in matched_insights[1:5]:
                lines.append(f"- ({item.get('type', 'memory')}, {item.get('similarity', 0)}%) {_format_search_result_text(item, mode)}")
                lines.append(f"  {_format_search_provenance(item)}")
        return '\n'.join(lines)

    else:
        return "No matches. Investigate manually."


@mcp.tool()
def get_recent_activity(limit: int = 10) -> str:
    """
    Get recent Claude activity from the dashboard.

    Shows what files were edited, commands run, etc.
    Useful for understanding recent context and what changed.

    Args:
        limit: Max number of activities to return (default 10)

    Returns:
        Recent activity list with timestamps and human-readable names
    """
    session = _get_session()
    activity_file = USER_DATA_DIR / "activity_log.json"

    if not activity_file.exists():
        return "No activity log found."

    try:
        with open(activity_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        all_activities = data.get('activities', [])

        if not all_activities:
            return "No recent activity."

        # Filter to current project only if session active
        working_dir = session.working_dir if session.is_active() else ""

        if working_dir:
            # Only show activities from current project
            project_activities = []
            for act in all_activities:
                file_path = act.get('file') or ''
                cwd = act.get('cwd') or ''
                if file_path.startswith(working_dir) or cwd.startswith(working_dir):
                    project_activities.append(act)
            activities = project_activities[:limit]
        else:
            activities = all_activities[:limit]

        if not activities:
            return "No recent activity for this project."

        lines = ["## Recent Activity\n"]

        for act in activities:
            file_path = act.get('file', '')
            human_name = act.get('human_name', '')
            tool = act.get('tool', '')
            timestamp = act.get('timestamp', '')[:16].replace('T', ' ')

            # Format the activity
            if file_path:
                file_name = file_path.split('/')[-1]
                display = human_name if human_name else file_name
                lines.append(f"• **{display}** ({file_name}) - {tool} - {timestamp}")
            elif act.get('command'):
                cmd = act.get('command', '')[:40]
                lines.append(f"• `{cmd}` - {timestamp}")

        return '\n'.join(lines)

    except Exception as e:
        return f"Error reading activity: {e}"


@mcp.tool()
def rebuild_semantic_index() -> str:
    """
    Rebuild semantic search index from existing project memory.

    Use this when:
    - First time enabling semantic search on existing project
    - Index seems out of sync
    - After model upgrade

    Returns:
        Stats about the rebuild
    """
    error, context = _universal_gate("rebuild_semantic_index")
    if error:
        return error

    semantic = _load_project_semantic()
    if not semantic:
        return context + "❌ Semantic search not available. Install fastembed: pip install fastembed"

    session = _get_session()

    try:
        result = semantic["rebuild_project_index"](session.project_id)
        if result.get('status') == 'ok':
            return context + f"""## ✅ Semantic Index Rebuilt

**Project:** {result.get('project_id')}
**Documents indexed:** {result.get('documents_indexed')}

Index is now ready for semantic search."""
        else:
            return context + f"❌ Rebuild failed: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return context + f"❌ Error rebuilding index: {e}"


# NOTE: get_browser_errors is INTERNAL (called by fo_errors).
# Not exposed as MCP tool to avoid FunctionTool collision.
def get_browser_errors(limit: int = 10) -> str:
    """
    INTERNAL: Get recent browser errors captured by the FixOnce Chrome extension.
    For external use, call fo_errors() instead.

    These are JavaScript errors, network errors, and console errors from
    the user's browser. Use this to proactively help fix frontend issues.

    Args:
        limit: Max number of errors to return (default 10)

    Returns:
        Recent browser errors with messages, sources, and timestamps
    """
    error = _lightweight_tool_gate("get_browser_errors", sync_compliance=False)
    if error:
        return error

    try:
        # Try to fetch from the dashboard API
        res = requests.get(f'{_get_api_url()}/api/live-errors', timeout=3)
        if res.status_code != 200:
            return "No browser errors available (dashboard not running or no errors)."

        data = res.json()
        errors = data.get('errors', [])

        # Classify errors: real vs test/noise
        def is_test_error(err):
            url = err.get('url', '')
            file = err.get('file', '')
            # Test markers: empty URL, test.local, empty file with no URL
            if not url and not file:
                return True
            if 'test.local' in url or 'localhost:0' in url:
                return True
            if url == 'http://test.local' or url == 'https://test.local':
                return True
            return False

        real_errors = [e for e in errors if not is_test_error(e)]
        test_errors = [e for e in errors if is_test_error(e)]

        if not real_errors:
            if test_errors:
                return f"{len(test_errors)} test/noise error(s) only. Safe to ignore or clear."
            return "No browser errors captured."

        # Track ROI: errors caught in real-time
        _track_roi_event("error_caught_live")

        # Auto-populate pending_fixes from previous_solution
        try:
            from core.pending_fixes import add_pending_fix
            for err in real_errors:
                prev = err.get('previous_solution') or err.get('matched_solution')
                if prev and prev.get('solution'):
                    score = prev.get('similarity_score', prev.get('score', 0))
                    confidence = int(score * 100) if score <= 1 else int(score)
                    add_pending_fix(
                        error_message=err.get('message', '')[:500],
                        solution_text=prev['solution'],
                        confidence=confidence,
                        similarity=confidence,
                        source=prev.get('source', 'semantic'),
                        error_id=f"err_{hash(err.get('message', ''))}"
                    )
        except Exception as e:
            _log(f"[get_browser_errors] pending_fixes error: {e}")

        lines = []

        # Real errors first
        if real_errors:
            for err in real_errors[:limit]:
                msg = err.get('message', err.get('error', 'Unknown error'))[:80]
                lines.append(f"• {msg}")

        if test_errors and real_errors:
            lines.append(f"(+ {len(test_errors)} test errors)")

        if not lines:
            return "No browser errors captured."

        return f"{len(real_errors)} error(s):\n" + "\n".join(lines)

    except requests.exceptions.RequestException:
        return "Could not connect to dashboard. Make sure FixOnce server is running."
    except Exception as e:
        return f"Error fetching browser errors: {e}"


@mcp.tool()
def get_browser_context() -> str:
    """
    Get the element user selected in browser + recent errors.

    Use this when the user says "this element", "the button", "fix this",
    or refers to something visible in their browser.

    The user selects elements using the FixOnce Chrome extension's
    "Select Element" feature.

    Returns:
        Selected element with HTML, CSS, and selector path + recent errors
    """
    # v1: Feature disabled - AI Context Mode is planned for v2
    return "AI Context Mode is disabled in v1. This feature will be available in a future version."

    error, _ = _universal_gate("get_browser_context")
    if error:
        return error

    try:
        res = requests.get(f'{_get_api_url()}/api/browser-context', timeout=3)
        if res.status_code != 200:
            return "No browser context available."

        data = res.json()
        selected = data.get('selected_element')
        errors = data.get('recent_errors', [])

        lines = ["## Browser Context\n"]

        if selected:
            # Handle both 'element' (old) and 'elements' (new array format)
            elements = selected.get('elements', [])
            el = elements[0] if elements else selected.get('element', {})

            if not el:
                lines.append("_No element data._")
            else:
                lines.append("### 🎯 Selected Element\n")
                lines.append(f"**Selector:** `{el.get('selector', 'N/A')}`")
                lines.append(f"**Tag:** `{el.get('tagName', 'N/A')}`")

                if el.get('id'):
                    lines.append(f"**ID:** `{el.get('id')}`")
                if el.get('classes'):
                    lines.append(f"**Classes:** `{' '.join(el.get('classes', []))}`")

                lines.append(f"\n**HTML:**\n```html\n{el.get('html', '')[:500]}\n```")

                css = el.get('css', {})
                if css:
                    lines.append("\n**Key CSS Properties:**")
                    for prop, value in list(css.items())[:8]:
                        lines.append(f"- `{prop}`: `{value}`")

                rect = el.get('rect', {})
                if rect:
                    lines.append(f"\n**Dimensions:** {rect.get('width', 0)}x{rect.get('height', 0)}px")

                # Get URL from element or parent
                url = el.get('url') or selected.get('url', 'N/A')
                timestamp = el.get('timestamp') or selected.get('timestamp', '')
                selector = el.get('selector', '')
                lines.append(f"\n**Page URL:** {url}")
                lines.append(f"**Captured:** {timestamp[:16].replace('T', ' ') if timestamp else 'N/A'}")

                # Auto-confirm selection with a short, visibility-guarded ack.
                # This keeps immediate UX feedback while avoiding stale highlights
                # when the UI changed (e.g., modal already closed).
                if selector:
                    selection_key = f"{selector}|{timestamp or ''}"
                    last_key = getattr(get_browser_context, "_last_auto_highlight_key", "")

                    is_fresh = True
                    if timestamp:
                        try:
                            ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                            age_sec = (datetime.now(ts.tzinfo) - ts).total_seconds()
                            is_fresh = age_sec <= 5
                        except Exception:
                            is_fresh = True

                    if selection_key != last_key and is_fresh:
                        try:
                            requests.post(
                                f'{_get_api_url()}/api/highlight-element',
                                json={
                                    "selector": selector,
                                    "message": "Selection received",
                                    "mode": "ack",
                                    "duration_ms": 900,
                                    "require_visible": True,
                                    "allow_context_open": False
                                },
                                timeout=2
                            )
                            setattr(get_browser_context, "_last_auto_highlight_key", selection_key)
                        except Exception:
                            pass
        else:
            lines.append("_No element selected. User can click 'Select Element' in FixOnce extension._")

        if errors:
            lines.append("\n### 🔴 Recent Errors\n")
            for err in errors[:5]:
                lines.append(f"- **{err.get('type', 'error')}:** {err.get('message', '')[:100]}")
        else:
            lines.append("\n_No recent browser errors._")

        return '\n'.join(lines)

    except requests.exceptions.RequestException:
        return "Could not connect to dashboard. Make sure FixOnce server is running."
    except Exception as e:
        return f"Error fetching browser context: {e}"


@mcp.tool()
def highlight_element(selector: str, message: str = "", mode: str = "ack", duration_ms: int = 0) -> str:
    """
    Highlight an element in the user's browser.

    Use this to point to or track work on an element in the user's browser.

    Args:
        selector: CSS selector for the element (e.g., "#submit-btn", ".error-message")
        message: Short message to show in tooltip (max 100 chars)
        mode: One of: ack, working, done, clear
        duration_ms: Optional custom duration in milliseconds

    Returns:
        Confirmation that highlight was queued
    """
    # v1: Feature disabled - AI Context Mode is planned for v2
    return "AI Context Mode is disabled in v1. This feature will be available in a future version."

    error, _ = _universal_gate("highlight_element")
    if error:
        return error

    try:
        res = requests.post(
            f'{_get_api_url()}/api/highlight-element',
            json={
                "selector": selector,
                "message": message[:100] if message else "",
                "mode": mode,
                "duration_ms": max(0, int(duration_ms or 0))
            },
            timeout=3
        )
        if res.status_code == 200:
            suffix = f" ({mode})" if mode else ""
            return f"✨ Highlighting{suffix} `{selector}` with message: '{message}'" if message else f"✨ Highlighting{suffix} `{selector}`"
        else:
            return f"Failed to queue highlight: {res.text}"

    except requests.exceptions.RequestException:
        return "Could not connect to dashboard. Make sure FixOnce server is running."
    except Exception as e:
        return f"Error highlighting element: {e}"


@mcp.tool()
def get_protocol_compliance() -> str:
    """
    Get current protocol compliance status.

    Use this to check if you're following FixOnce protocol correctly.
    Returns status of: session init, decisions display, goal updates.
    """
    session = _get_session()
    score_data = session.get_compliance_score()
    score = score_data["score"]

    # Score bar visualization
    filled = score // 10
    empty = 10 - filled
    bar = "█" * filled + "░" * empty

    lines = [f"## Protocol Compliance: {bar} {score}%\n"]

    # Rules checklist
    for rule in score_data["rules"]:
        icon = "✅" if rule["passed"] else ("❌" if rule["required"] else "⚠️")
        req = " (required)" if rule["required"] else ""
        lines.append(f"{icon} {rule['name']}{req}")

    advisory = score_data.get("advisory") or []
    if advisory:
        lines.append("\nAdvisory only:")
        for item in advisory:
            icon = "✓" if item.get("active") else "·"
            lines.append(f"{icon} {item['name']} ({item['scope']})")

    # Tool calls
    lines.append(f"\n📊 Tool calls this session: {score_data['tool_calls']}")

    # Violations
    if _compliance_state["violations"]:
        lines.append("\n### ⚠️ Recent Violations:")
        for v in _compliance_state["violations"][-5:]:
            lines.append(f"- {v['type']}: {v['tool']} at {v['timestamp']}")

    return '\n'.join(lines)


@mcp.tool()
def run_memory_cleanup() -> str:
    """
    Run memory decay cleanup - archive old/unused insights.

    This tool:
    - Archives low-importance insights not used in 60+ days
    - Archives never-used low-importance insights older than 30 days
    - Shows memory statistics

    PROTECTED (never archived):
    - Decisions (log_decision) - permanent institutional knowledge
    - Avoid patterns (log_avoid) - permanent warnings
    - Failed attempts - prevent repeating mistakes
    - High-importance insights

    Run this periodically to keep memory clean and relevant.
    """
    error = _require_session("run_memory_cleanup")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    archived = lessons.get('archived', [])

    if not insights:
        return "No insights to process."

    # Normalize all insights
    normalized = [_normalize_insight(ins) for ins in insights]

    # Separate active from archived
    still_active = []
    newly_archived = []

    for ins in normalized:
        if _should_archive_insight(ins):
            newly_archived.append(ins)
        else:
            still_active.append(ins)

    # Update memory
    lessons['insights'] = still_active
    lessons['archived'] = archived + newly_archived
    memory['live_record']['lessons'] = lessons

    _save_project(session.project_id, memory)

    # Build stats report
    lines = ["## Memory Cleanup Report\n"]

    # Show protected items count
    decisions_count = len(memory.get('decisions', []))
    avoid_count = len(memory.get('avoid', []))
    failed_count = len(lessons.get('failed_attempts', []))

    lines.append("### 🔒 Protected (Never Archived)")
    lines.append(f"- **Decisions:** {decisions_count}")
    lines.append(f"- **Avoid Patterns:** {avoid_count}")
    lines.append(f"- **Failed Attempts:** {failed_count}")
    lines.append("")

    lines.append("### 📊 Insights")
    lines.append(f"**Active:** {len(still_active)}")
    lines.append(f"**Newly Archived:** {len(newly_archived)}")
    lines.append(f"**Total Archived:** {len(lessons['archived'])}")

    if newly_archived:
        lines.append("\n### Archived Insights:")
        for ins in newly_archived[:5]:
            text = ins.get('text', '')[:50]
            lines.append(f"- {text}...")

    # Show top insights by importance
    if still_active:
        lines.append("\n### Top Active Insights:")
        top = _get_ranked_insights(still_active, limit=3)
        for ins in top:
            text = ins.get('text', '')[:50]
            importance = ins.get('importance', 'medium')
            use_count = ins.get('use_count', 0)
            lines.append(f"- 🔥 [{importance}] (used {use_count}x) {text}...")

    return '\n'.join(lines)


@mcp.tool()
def get_memory_stats() -> str:
    """
    Get memory statistics for the current project.

    Shows:
    - Total insights (active vs archived)
    - Importance distribution
    - Usage statistics
    - Recommendations for cleanup
    """
    error = _require_session("get_memory_stats")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)

    lessons = memory.get('live_record', {}).get('lessons', {})
    insights = lessons.get('insights', [])
    archived = lessons.get('archived', [])
    failed = lessons.get('failed_attempts', [])
    decisions = memory.get('decisions', [])

    lines = ["## Memory Statistics\n"]

    # Totals
    lines.append(f"**Active Insights:** {len(insights)}")
    lines.append(f"**Archived Insights:** {len(archived)}")
    lines.append(f"**Failed Attempts:** {len(failed)}")
    lines.append(f"**Decisions:** {len(decisions)}")

    if insights:
        # Normalize for stats
        normalized = [_normalize_insight(ins) for ins in insights]

        # Importance distribution
        high = sum(1 for i in normalized if i.get('importance') == 'high')
        medium = sum(1 for i in normalized if i.get('importance') == 'medium')
        low = sum(1 for i in normalized if i.get('importance') == 'low')

        lines.append(f"\n**Importance Distribution:**")
        lines.append(f"- 🔥 High: {high}")
        lines.append(f"- 💡 Medium: {medium}")
        lines.append(f"- ⚪ Low: {low}")

        # Usage stats
        used = sum(1 for i in normalized if i.get('use_count', 0) > 0)
        never_used = len(normalized) - used
        total_uses = sum(i.get('use_count', 0) for i in normalized)

        lines.append(f"\n**Usage Statistics:**")
        lines.append(f"- Used at least once: {used}")
        lines.append(f"- Never used: {never_used}")
        lines.append(f"- Total usage count: {total_uses}")

        # Recommendations
        lines.append(f"\n**Recommendations:**")
        if never_used > 10:
            lines.append(f"⚠️ {never_used} insights never used - consider running `run_memory_cleanup()`")
        if len(insights) > 50:
            lines.append(f"⚠️ Memory growing large ({len(insights)} insights) - consider cleanup")
        if never_used == 0 and len(insights) < 50:
            lines.append("✅ Memory is healthy - no action needed")

    return '\n'.join(lines)


@mcp.tool()
def get_impact_stats() -> str:
    """
    Get FixOnce impact statistics.

    Shows how FixOnce is saving time:
    - Time saved (estimated minutes)
    - Solutions reused (vs debugging from scratch)
    - Decisions applied (preventing wrong direction)
    - Errors prevented (avoid patterns)
    - Sessions with context (handover continuity)

    Use this to report impact to the user.
    """
    try:
        res = requests.get(f'{_get_api_url()}/api/memory/roi', timeout=3)
        if res.status_code != 200:
            return "Could not fetch impact stats"

        roi = res.json()

        time_saved = roi.get('time_saved_minutes', 0)
        reused = roi.get('solutions_reused', 0)
        decisions = roi.get('decisions_referenced', 0)
        prevented = roi.get('errors_prevented', 0)
        sessions = roi.get('sessions_with_context', 0)
        errors_live = roi.get('errors_caught_live', 0)
        insights = roi.get('insights_used', 0)

        # Format time
        if time_saved < 60:
            time_str = f"{time_saved} minutes"
        else:
            hours = time_saved // 60
            mins = time_saved % 60
            time_str = f"{hours}h {mins}m" if mins else f"{hours} hours"

        lines = [
            "## ⚡ FixOnce Impact\n",
            f"**🕐 Time Saved:** {time_str}\n"
        ]

        # Breakdown
        lines.append("**Breakdown:**")
        if reused > 0:
            lines.append(f"- 🔍 {reused} solutions reused (saved ~{reused * 10}m)")
        if decisions > 0:
            lines.append(f"- 🔒 {decisions} decisions applied (saved ~{decisions * 20}m)")
        if prevented > 0:
            lines.append(f"- 🛡️ {prevented} errors prevented (saved ~{prevented * 30}m)")
        if sessions > 0:
            lines.append(f"- 🔄 {sessions} sessions with context (saved ~{sessions * 10}m)")
        if errors_live > 0:
            lines.append(f"- ⚡ {errors_live} live errors caught")
        if insights > 0:
            lines.append(f"- 💡 {insights} insights used")

        if reused == 0 and decisions == 0 and prevented == 0 and sessions == 0:
            lines.append("- Building impact... (use search, log decisions, work across sessions)")

        return '\n'.join(lines)

    except Exception as e:
        return f"Error getting impact stats: {e}"


# ============================================================
# SMART TOOLS - File operations with automatic error checking
# ============================================================
# These tools wrap file operations and automatically check for
# browser errors after each operation. Claude should use these
# instead of regular Edit/Write when working on web projects.
# ============================================================

import time

def _get_new_errors_since(timestamp: str) -> list:
    """Get errors that occurred after the given timestamp."""
    try:
        res = requests.get(f'{_get_api_url()}/api/live-errors?since=10', timeout=2)
        if res.status_code == 200:
            data = res.json()
            errors = data.get('errors', [])
            # Filter to errors after timestamp
            new_errors = []
            for e in errors:
                err_time = e.get('timestamp', '')
                if err_time > timestamp:
                    new_errors.append(e)
            return new_errors
        return []
    except Exception:
        return []


def _format_error_alert(errors: list) -> str:
    """Format errors as an alert message."""
    if not errors:
        return ""

    lines = [
        "",
        "═══════════════════════════════════════",
        f"🚨 **{len(errors)} NEW ERROR(S) DETECTED!**",
        "═══════════════════════════════════════"
    ]

    for e in errors[:5]:
        msg = e.get('message', 'Unknown error')[:80]
        source = e.get('source', '')
        if source:
            source_short = source.split('/')[-1][:20]
            lines.append(f"• [{source_short}] {msg}")
        else:
            lines.append(f"• {msg}")

    if len(errors) > 5:
        lines.append(f"• ...and {len(errors) - 5} more")

    lines.append("")
    lines.append("**⚠️ FIX THESE BEFORE CONTINUING!**")
    lines.append("═══════════════════════════════════════")

    return '\n'.join(lines)


@mcp.tool()
def smart_file_operation(
    operation: str,
    file_path: str,
    content: str = "",
    description: str = ""
) -> str:
    """
    Execute a file operation and automatically check for browser errors.

    USE THIS instead of regular Edit/Write when working on web projects!
    After the operation, waits briefly and checks if any new browser errors appeared.

    Args:
        operation: "read", "write", "append", or "info"
        file_path: Path to the file
        content: Content to write (for write/append operations)
        description: What this change does (for logging)

    Returns:
        Operation result + any new browser errors detected

    Example:
        smart_file_operation("write", "game.js", "function startGame() {...}", "Added start function")
    """
    error, context = _universal_gate("smart_file_operation")
    if error:
        return error

    # Record timestamp before operation
    before_time = datetime.now().isoformat()

    result_lines = [context]

    try:
        path = Path(file_path)

        if operation == "read":
            if path.exists():
                content = path.read_text(encoding='utf-8')
                result_lines.append(f"📄 Read {len(content)} chars from {file_path}")
                result_lines.append("```")
                result_lines.append(content[:2000])
                if len(content) > 2000:
                    result_lines.append(f"... ({len(content) - 2000} more chars)")
                result_lines.append("```")
            else:
                result_lines.append(f"❌ File not found: {file_path}")

        elif operation == "write":
            # Check if this affects a stable component BEFORE writing
            stable_impact = _check_stable_component_impact(file_path)
            gate_result = _evaluate_current_risk_gate(
                tool_name="smart_file_operation",
                stable_component_touched=bool(stable_impact)
            )
            if gate_result.level in {"warn", "block"}:
                result_lines.append("")
                result_lines.append(f"⚠️ **STABILITY WARNING**: This file belongs to stable component '{stable_impact['name']}'")
                result_lines.append(f"   Checkpoint: {stable_impact['commit']}")
                result_lines.append(f"   Consider: rollback_component(\"{stable_impact['name']}\") if issues occur")
                result_lines.append("")
                # Log this modification
                _log_stable_component_modification(stable_impact['name'], file_path, "AI")

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            result_lines.append(f"✅ Wrote {len(content)} chars to {file_path}")
            if description:
                result_lines.append(f"📝 {description}")

        elif operation == "append":
            # Check if this affects a stable component BEFORE appending
            stable_impact = _check_stable_component_impact(file_path)
            gate_result = _evaluate_current_risk_gate(
                tool_name="smart_file_operation",
                stable_component_touched=bool(stable_impact)
            )
            if gate_result.level in {"warn", "block"}:
                result_lines.append("")
                result_lines.append(f"⚠️ **STABILITY WARNING**: This file belongs to stable component '{stable_impact['name']}'")
                result_lines.append(f"   Checkpoint: {stable_impact['commit']}")
                result_lines.append(f"   Consider: rollback_component(\"{stable_impact['name']}\") if issues occur")
                result_lines.append("")
                # Log this modification
                _log_stable_component_modification(stable_impact['name'], file_path, "AI")

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(content)
            result_lines.append(f"✅ Appended {len(content)} chars to {file_path}")
            if description:
                result_lines.append(f"📝 {description}")

        elif operation == "info":
            if path.exists():
                stat = path.stat()
                result_lines.append(f"📄 {file_path}")
                result_lines.append(f"   Size: {stat.st_size} bytes")
                result_lines.append(f"   Modified: {datetime.fromtimestamp(stat.st_mtime).isoformat()}")
            else:
                result_lines.append(f"❌ File not found: {file_path}")

        else:
            result_lines.append(f"❌ Unknown operation: {operation}")
            return '\n'.join(result_lines)

    except Exception as e:
        result_lines.append(f"❌ Error: {e}")
        return '\n'.join(result_lines)

    # Wait for browser to potentially throw errors
    time.sleep(1.5)

    # Check for new errors
    new_errors = _get_new_errors_since(before_time)

    if new_errors:
        result_lines.append(_format_error_alert(new_errors))

        # Log this as a potential issue
        session = _get_session()
        if session.is_active():
            # Track that we caught an error
            _track_roi_event("error_prevented")
    else:
        result_lines.append("")
        result_lines.append("✅ No new browser errors detected")

    return '\n'.join(result_lines)


@mcp.tool()
def check_and_report() -> str:
    """
    Quick check for browser errors and project status.

    Call this periodically while working to catch any errors early.
    Returns a compact status report.
    """
    error, context = _universal_gate("check_and_report")
    if error:
        return error

    lines = [context]

    # Check browser errors
    errors = _get_live_errors()

    if errors:
        lines.append(f"🚨 **{len(errors)} BROWSER ERRORS:**")
        for e in errors[:3]:
            msg = e.get('message', 'Unknown')[:60]
            lines.append(f"  • {msg}")
        if len(errors) > 3:
            lines.append(f"  • ...and {len(errors) - 3} more")
        lines.append("")
        lines.append("**Use `fo_errors()` for details.**")
    else:
        lines.append("✅ No browser errors")

    # Add goal reminder
    session = _get_session()
    if session.is_active():
        memory = _load_project(session.project_id)
        if memory:
            goal = memory.get('live_record', {}).get('intent', {}).get('current_goal', '')
            if goal:
                lines.append("")
                lines.append(f"🎯 Current goal: {goal}")

    # Check AI Context mode
    ai_context = _get_ai_context_injection()
    if ai_context:
        lines.append("")
        lines.append("🎯 **AI Context ACTIVE** - User has selected element(s)")
        lines.append("   When they say \"this/that/זה\" → use the selected element")

    return '\n'.join(lines)


@mcp.tool()
def generate_context() -> str:
    """
    Generate the universal context file (.fixonce/CONTEXT.md).

    This file can be read by ANY AI - not just those with MCP access.
    It's auto-generated on every memory change, but you can also
    trigger manual generation with this tool.

    Returns:
        Path to the generated file, or error if failed.
    """
    error, context = _universal_gate("generate_context")
    if error:
        return error

    session = _get_session()
    if not session.is_active():
        return "Error: No active session. Call fo_init first."

    memory = _load_project(session.project_id)
    if not memory:
        return "Error: Could not load project memory."

    working_dir = memory.get('project_info', {}).get('working_dir', '')
    if not working_dir:
        return "Error: No working_dir in project_info."

    try:
        from core.context_generator import generate_context_file
        context_path = generate_context_file(memory, working_dir)
        return f"✅ Context file generated:\n`{context_path}`\n\nAny AI can now read this file to get project context."
    except Exception as e:
        return f"Error generating context: {e}"


# ============================================================
# COMMAND EXECUTION ACKNOWLEDGMENT
# ============================================================

@mcp.tool()
def mark_command_executed(command_id: str, result: str = "success", details: str = "") -> str:
    """
    Mark a dashboard command as executed (completed).

    Call this AFTER you finish executing a command from the dashboard.
    This completes the audit trail: queued → delivered → executed.

    Args:
        command_id: The command ID shown in the action request (e.g., "a1b2c3d4")
        result: "success", "failed", or "partial"
        details: Optional details about the execution result

    Returns:
        Confirmation message
    """
    error, context = _universal_gate("mark_command_executed")
    if error:
        return error

    session = _get_session()
    if not session.is_active():
        return "Error: No active session."

    memory = _load_project(session.project_id)
    if not memory:
        return "Error: Could not load project memory."

    # Find the command in the queue
    ai_queue = memory.get("ai_queue", [])
    command = None
    for item in ai_queue:
        if item.get("id") == command_id:
            command = item
            break

    if not command:
        # Command might have been cleaned up, just log to audit
        pass
    else:
        # EXECUTION LOCK: Only allow marking if status is "delivered"
        current_status = command.get("status", "")
        gate_result = _evaluate_current_risk_gate(
            tool_name="mark_command_executed",
            lock_violation=(current_status != "delivered")
        )
        if gate_result.level == "block":
            return f"❌ Cannot mark command `{command_id}` as executed.\nCurrent status: `{current_status}` (must be `delivered`).\n(📌 FixOnce: execution lock rejected)"

        # Update command status
        command["status"] = "executed" if result == "success" else f"executed_{result}"
        command["executed_at"] = datetime.now().isoformat()
        command["execution_result"] = result
        command["execution_details"] = details

    # Add to audit log
    if "command_audit" not in memory:
        memory["command_audit"] = []

    audit_entry = {
        "id": command_id,
        "action": "executed",
        "result": result,
        "details": details[:200] if details else "",
        "timestamp": datetime.now().isoformat(),
        "executed_by": _detect_editor()
    }
    audit_entry.update(_new_record_attribution("mark_command_executed"))
    memory["command_audit"].append(audit_entry)

    # Keep audit bounded
    memory["command_audit"] = memory["command_audit"][-50:]

    _save_project(session.project_id, memory)

    result_emoji = "✅" if result == "success" else "⚠️" if result == "partial" else "❌"
    return f"{result_emoji} Command `{command_id}` marked as {result}.\n(📌 FixOnce: execution logged)"


@mcp.tool()
def get_pending_commands(mark_delivered: bool = True) -> str:
    """
    Get pending commands from the dashboard AI queue.

    Use this to receive messages/commands sent from the FixOnce dashboard.
    When user clicks "Send to AI" or uses action buttons, commands are queued here.

    Args:
        mark_delivered: If True (default), mark retrieved commands as "delivered"
                       so they won't be returned again.

    Returns:
        Pending commands with their messages, or "No pending commands."
    """
    error, context = _universal_gate("get_pending_commands")
    if error:
        return error

    session = _get_session()
    if not session.is_active():
        return "Error: No active session."

    memory = _load_project(session.project_id)
    if not memory:
        return "Error: Could not load project memory."

    # Get pending commands
    ai_queue = memory.get("ai_queue", [])
    pending = [cmd for cmd in ai_queue if cmd.get("status") == "pending"]

    if not pending:
        return "No pending commands."

    # Build response
    lines = ["## 🚀 ACTION REQUESTED FROM DASHBOARD\n"]

    for cmd in pending:
        cmd_id = cmd.get("id", "unknown")
        cmd_type = cmd.get("type", "unknown")
        message = cmd.get("message", "")
        source = cmd.get("source", "dashboard")
        queued_at = cmd.get("queued_at", "")

        lines.append(f"**Command ID:** `{cmd_id}`")
        lines.append(f"**Type:** {cmd_type}")
        lines.append(f"**Source:** {source}")
        if queued_at:
            lines.append(f"**Queued:** {queued_at}")
        lines.append("")
        lines.append("**Message:**")
        lines.append(message)
        lines.append("")
        lines.append("---")
        lines.append("")

        # Mark as delivered
        if mark_delivered:
            cmd["status"] = "delivered"
            cmd["delivered_at"] = datetime.now().isoformat()
            cmd["delivered_to"] = _detect_editor()

    # Save if we marked any as delivered
    if mark_delivered and pending:
        _save_project(session.project_id, memory)

    lines.append(f"_Call `mark_command_executed(command_id=\"{pending[0].get('id')}\", result=\"success\")` when done._")

    return "\n".join(lines)


# ============================================================
# SESSION RESUME STATE
# ============================================================

@mcp.tool()
def save_resume_state(
    active_task: str,
    last_completed_step: str = "",
    current_status: str = "in_progress",
    next_recommended_action: str = "",
    short_summary: str = ""
) -> str:
    """
    Save the current work state for resuming after restart.

    Call this BEFORE:
    - Restarting Claude/MCP
    - Closing a session
    - Major refactors
    - When a clear next action is defined

    Args:
        active_task: What task is currently in progress
        last_completed_step: The last step that was completed
        current_status: One of: in_progress, waiting_for_restart, blocked, paused, completed
        next_recommended_action: What should be done next
        short_summary: Human-readable summary of where we stopped

    Returns:
        Confirmation of saved state
    """
    error = _require_session("save_resume_state")
    if error:
        return error

    if not _resume_state_available:
        return "Error: Resume state module not available."

    session = _get_session()

    result = _save_resume_state(
        project_id=session.project_id,
        active_task=active_task,
        last_completed_step=last_completed_step,
        current_status=current_status,
        next_recommended_action=next_recommended_action,
        short_summary=short_summary,
        attribution=_new_record_attribution("save_resume_state"),
    )

    if "error" in result:
        return f"Error: {result['error']}"

    lines = ["## ✅ Resume State Saved\n"]
    lines.append(f"**Task:** {active_task}")
    if last_completed_step:
        lines.append(f"**Last step:** {last_completed_step}")
    lines.append(f"**Status:** {current_status}")
    if next_recommended_action:
        lines.append(f"**Next action:** {next_recommended_action}")
    lines.append("")
    lines.append("_This state will be shown automatically when you start a new session._")

    return "\n".join(lines)


@mcp.tool()
def get_resume_state() -> str:
    """
    Get the current resume state for this project.

    Returns the saved work state, or indicates if none exists.
    """
    error = _require_session("get_resume_state")
    if error:
        return error

    if not _resume_state_available:
        return "Error: Resume state module not available."

    session = _get_session()
    resume_state = _get_resume_state(session.project_id)

    if not resume_state:
        return "No resume state saved for this project."

    lines = ["## 🔄 Current Resume State\n"]
    lines.append(f"**Task:** {resume_state.get('active_task', 'N/A')}")

    if resume_state.get('last_completed_step'):
        lines.append(f"**Last completed:** {resume_state['last_completed_step']}")

    status = resume_state.get('current_status', 'unknown')
    status_emoji = {
        "in_progress": "🔵",
        "waiting_for_restart": "⏳",
        "blocked": "🔴",
        "paused": "⏸️",
        "completed": "✅"
    }
    emoji = status_emoji.get(status, "")
    lines.append(f"**Status:** {emoji} {status}")

    if resume_state.get('next_recommended_action'):
        lines.append(f"**Next action:** {resume_state['next_recommended_action']}")

    if resume_state.get('short_summary'):
        lines.append("")
        lines.append(f"_{resume_state['short_summary']}_")

    if resume_state.get('updated_at'):
        lines.append("")
        lines.append(f"_Saved at: {resume_state['updated_at'][:19]}_")

    return "\n".join(lines)


@mcp.tool()
def clear_resume_state() -> str:
    """
    Clear the resume state (task completed, no longer relevant).

    Call this when the active task is fully completed.
    """
    error = _require_session("clear_resume_state")
    if error:
        return error

    if not _resume_state_available:
        return "Error: Resume state module not available."

    session = _get_session()
    success = _clear_resume_state(session.project_id)

    if success:
        return "✅ Resume state cleared. No pending work state."
    else:
        return "No resume state to clear."


# ============================================================
# SIMPLIFIED API - 8 Core Tools (v2.0)
# ============================================================
# These 8 tools replace the 45+ tools for a cleaner AI experience.
# Old tools still work but are not documented in CLAUDE.md.

def _format_minimal_init(working_dir: str) -> str:
    """
    Format the final human-visible session opener.
    This is the single source of truth for fo_init/sync openers.

    Priority: auto-fixes > errors > continuation context
    Data source: Uses FRESHER of intent vs resume_state (by timestamp)
    """
    from pathlib import Path
    from datetime import datetime

    _fo_init_trace(f"FORMAT_INIT_ENTER working_dir={working_dir!r}")
    project_name = Path(working_dir).name
    _fo_init_trace(f"FORMAT_INIT_PROJECT_NAME project_name={project_name!r}")
    project_id = _get_project_id(working_dir)
    _fo_init_trace(f"FORMAT_INIT_LOAD_PROJECT_BEFORE project_id={project_id!r}")
    data = _load_project(project_id)
    _fo_init_trace(f"FORMAT_INIT_LOAD_PROJECT_AFTER has_data={bool(data)}")

    _fo_init_trace("FORMAT_INIT_AUTO_FIXES_BEFORE")
    auto_fixes = _get_auto_fixes()
    _fo_init_trace(f"FORMAT_INIT_AUTO_FIXES_AFTER count={len(auto_fixes)}")
    _fo_init_trace("FORMAT_INIT_LIVE_ERRORS_BEFORE")
    live_errors = _get_live_errors()
    _fo_init_trace(f"FORMAT_INIT_LIVE_ERRORS_AFTER count={len(live_errors)}")
    _fo_init_trace("FORMAT_INIT_ERROR_GATE_BEFORE")
    gate_result = _evaluate_current_error_gate(
        tool_name="fo_init",
        live_errors=len(live_errors),
        auto_fix_ready=bool(auto_fixes),
    )
    _fo_init_trace(f"FORMAT_INIT_ERROR_GATE_AFTER level={gate_result.level!r}")

    if gate_result.level == "block":
        _fo_init_trace("FORMAT_INIT_RETURN action_required_fo_apply")
        return f"🧠 Back to {project_name}\n\nACTION_REQUIRED: fo_apply\n\nReady."

    if gate_result.level == "warn":
        _fo_init_trace("FORMAT_INIT_RETURN action_required_fo_errors")
        return f"🧠 Back to {project_name}\n\nACTION_REQUIRED: fo_errors\n\nReady."

    # Get both data sources
    resume_state = None
    if _resume_state_available:
        try:
            _fo_init_trace("RESUME_STATE_LOAD_BEFORE")
            _fo_init_trace("FORMAT_INIT_RESUME_STATE_BEFORE")
            resume_state = _get_resume_state(project_id)
            _fo_init_trace(f"FORMAT_INIT_RESUME_STATE_AFTER exists={bool(resume_state)}")
            _fo_init_trace(f"RESUME_STATE_LOAD_AFTER exists={bool(resume_state)}")
        except Exception as exc:
            _fo_init_trace(f"FORMAT_INIT_RESUME_STATE_ERROR {type(exc).__name__}: {exc}", include_stack=True)
            _fo_init_trace("RESUME_STATE_LOAD_AFTER error")
            pass

    intent = data.get("live_record", {}).get("intent", {}) if data else {}
    _fo_init_trace(f"FORMAT_INIT_INTENT_LOADED keys={list(intent.keys()) if isinstance(intent, dict) else 'non-dict'}")

    # Determine which source is fresher (intent from fo_sync, resume_state from save_resume_state)
    def parse_timestamp(ts):
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except:
            return None

    def clean_text(value: str, limit: int = 140) -> str:
        if not value:
            return ""
        value = " ".join(str(value).strip().split())
        if len(value) <= limit:
            return value
        return value[:limit - 1].rstrip() + "…"

    intent_time = parse_timestamp(intent.get("updated_at"))
    resume_time = parse_timestamp(resume_state.get("updated_at") if resume_state else None)
    now = datetime.now(intent_time.tzinfo) if intent_time and intent_time.tzinfo else datetime.now()

    # Use fresher source, default to intent (more commonly updated via fo_sync)
    use_intent_first = True
    if resume_time and intent_time:
        use_intent_first = intent_time >= resume_time
    elif resume_time and not intent_time:
        use_intent_first = False

    # Extract continuation data based on freshness
    if use_intent_first:
        last_thing = intent.get("last_change") or (resume_state.get("last_completed_step") if resume_state else None)
        next_thing = intent.get("next_step") or (resume_state.get("next_recommended_action") if resume_state else None)
    else:
        last_thing = (resume_state.get("last_completed_step") if resume_state else None) or intent.get("last_change")
        next_thing = (resume_state.get("next_recommended_action") if resume_state else None) or intent.get("next_step")

    # Fallback for next_thing
    if not next_thing and resume_state and resume_state.get("active_task"):
        next_thing = resume_state['active_task']

    # Add grounded context fields so the opening reflects real saved state.
    current_goal = intent.get("current_goal", "")
    work_area = intent.get("work_area", "")
    last_file = intent.get("last_file", "")
    short_summary = resume_state.get("short_summary") if resume_state else ""

    last_thing = clean_text(last_thing)
    next_thing = clean_text(next_thing)
    current_goal = clean_text(current_goal, limit=110)
    work_area = clean_text(work_area, limit=80)
    last_file = clean_text(last_file, limit=90)
    short_summary = clean_text(short_summary)

    freshest_time = intent_time if use_intent_first else resume_time
    stale_context = False
    if freshest_time:
        try:
            stale_context = (now - freshest_time).days >= 14
        except:
            stale_context = False

    # Build final opener with explicit grounding and stable formatting.
    line1 = f"🧠 Back to {project_name}"

    context_bits = []
    if current_goal:
        context_bits.append(current_goal)
    if work_area:
        context_bits.append(f"Area: {work_area}")
    elif short_summary and not current_goal:
        context_bits.append(short_summary)

    if stale_context and context_bits:
        line2 = "Last recorded: " + " / ".join(context_bits)
    elif context_bits:
        line2 = "\n".join(context_bits)
    else:
        line2 = ""

    detail_lines = []
    if last_thing:
        detail_lines.append(f"Last:\n{last_thing}.")
    elif last_file:
        detail_lines.append(f"Last file:\n{last_file}.")

    if next_thing:
        detail_lines.append(f"Next:\n{next_thing}.")

    lines = [line1, ""]
    if line2:
        lines.append(line2)
        lines.append("")
    if detail_lines:
        lines.extend(detail_lines)
        lines.append("")
    elif not line2:
        lines.extend(["Ready to continue.", ""])

    # Compact memory summary (counts only, no details)
    try:
        from core.committed_knowledge import read_committed_knowledge
        ck = read_committed_knowledge(working_dir)
        d_count = len(ck.get("decisions", []))
        s_count = len(ck.get("solutions", []))
        a_count = len(ck.get("avoid", []))
        if d_count or s_count or a_count:
            lines.append(f"📊 Memory: {d_count} Decisions · {s_count} Solved Bugs · {a_count} Avoid Patterns")
            lines.append("")
    except Exception:
        pass  # Silent fallback if committed knowledge unavailable

    # Protocol reminder: inform user that progress is tracked
    lines.append("💾 Progress synced automatically")
    lines.append("")

    lines.append("Ready.")

    result = "\n".join(lines)
    _fo_init_trace(f"FORMAT_INIT_RETURN_OK length={len(result)}")
    return result


@mcp.tool()
def fo_init(cwd: str = "") -> str:
    """
    Initialize FixOnce session. MUST be called first.

    Returns the final human-visible session opener, including Ready.
    Agents should display this opener exactly once and not paraphrase it.

    Args:
        cwd: Current working directory (usually provided by Claude Code)
    """
    with _FoInitTraceScope(cwd):
        _fo_init_trace("FO_INIT_BODY_ENTER")
        _fo_init_trace("FO_INIT_MODE_BEFORE")
        mode = _get_fixonce_mode()
        _fo_init_trace(f"FO_INIT_MODE_AFTER mode={mode!r}")
        if mode == MODE_OFF:
            _fo_init_trace("FO_INIT_RETURN mode_off")
            return "FixOnce is off."
        if mode == MODE_PASSIVE:
            _fo_init_trace("FO_INIT_RETURN mode_passive")
            return "FixOnce is in PASSIVE mode."

        _fo_init_trace("FO_INIT_RESOLVE_WORKING_DIR_BEFORE")
        working_dir = _resolve_init_working_dir(cwd)
        _fo_init_trace(f"FO_INIT_RESOLVE_WORKING_DIR_AFTER working_dir={working_dir!r}")

        if not working_dir:
            _fo_init_trace("FO_INIT_RETURN no_project_folder")
            return "Open from a project folder to continue."

        # Initialize session (all the background work)
        _fo_init_trace("FO_INIT_PROJECT_ID_BEFORE")
        project_id = _get_project_id(working_dir)
        _fo_init_trace(f"FO_INIT_PROJECT_ID_AFTER project_id={project_id!r}")
        _fo_init_trace("FO_INIT_SET_SESSION_BEFORE")
        _set_session(project_id, working_dir)
        _fo_init_trace("FO_INIT_SET_SESSION_AFTER")
        _fo_init_trace("FO_INIT_PERSIST_SESSION_BEFORE")
        _persist_session(project_id, working_dir)
        _fo_init_trace("FO_INIT_PERSIST_SESSION_AFTER")
        _fo_init_trace("FO_INIT_GET_SESSION_BEFORE")
        session = _get_session()
        _fo_init_trace(f"FO_INIT_GET_SESSION_AFTER session_exists={bool(session)}")
        _fo_init_trace("FO_INIT_MARK_INITIALIZED_BEFORE")
        session.mark_initialized()
        _fo_init_trace("FO_INIT_MARK_INITIALIZED_AFTER")
        _fo_init_trace("FO_INIT_LOG_TOOL_CALL_BEFORE")
        session.log_tool_call("fo_init")
        _fo_init_trace("FO_INIT_LOG_TOOL_CALL_AFTER")
        _fo_init_trace("FO_INIT_MARK_GLOBAL_INITIALIZED_BEFORE")
        _mark_session_initialized()
        _fo_init_trace("FO_INIT_MARK_GLOBAL_INITIALIZED_AFTER")

        # Seed dashboard selection only when the user has not selected a project.
        try:
            _fo_init_trace("FO_INIT_ACTIVE_PROJECT_IMPORT_BEFORE")
            from managers.multi_project_manager import ensure_dashboard_project
            _fo_init_trace("FO_INIT_ACTIVE_PROJECT_IMPORT_AFTER")
            _fo_init_trace("ACTIVE_PROJECT_LOAD_OR_WRITE_BEFORE ensure_dashboard_project")
            _fo_init_trace("FO_INIT_ACTIVE_PROJECT_SET_BEFORE")
            ensure_dashboard_project(
                project_id=project_id,
                detected_from="fo_init",
                display_name=Path(working_dir).name,
                working_dir=working_dir
            )
            _fo_init_trace("FO_INIT_ACTIVE_PROJECT_SET_AFTER")
            _fo_init_trace("ACTIVE_PROJECT_LOAD_OR_WRITE_AFTER ensure_dashboard_project")
        except Exception as exc:
            _fo_init_trace(f"FO_INIT_ACTIVE_PROJECT_ERROR {type(exc).__name__}: {exc}", include_stack=True)
            pass

        _persist_ai_connection(_resolve_actor_identity(), project_id=project_id)

        # Return minimal formatted output
        _fo_init_trace("FO_INIT_FORMAT_RESPONSE_BEFORE")
        result = _format_minimal_init(working_dir)
        _fo_init_trace(f"FO_INIT_FORMAT_RESPONSE_AFTER length={len(result)}")
        _fo_init_trace("FO_INIT_RETURN_TO_FASTMCP_BEFORE")
        return result


@mcp.tool()
def fo_sync(
    goal: str = "",
    work_area: str = "",
    last_change: str = "",
    last_file: str = "",
    why: str = "",
    next_step: str = ""
) -> str:
    """
    Sync work context with FixOnce. Call after changes or when starting new work.

    Args:
        goal: Current goal (e.g., "Fix login bug")
        work_area: Feature/module area (e.g., "authentication")
        last_change: What was just done (e.g., "Added validation")
        last_file: Last file modified
        why: Why this work matters
        next_step: Short continuation prompt (e.g., "Test the fix", "Check error flow")
                   NOT numbered lists - just one actionable next step
    """
    return _run_tool_with_timeout(
        "fo_sync",
        _update_work_context_lightweight,
        _FO_SYNC_TIMEOUT_SECONDS,
        tool_name="fo_sync",
        current_goal=goal,
        work_area=work_area,
        last_change=last_change,
        last_file=last_file,
        why=why,
        next_step=next_step,
    )


@mcp.tool()
def fo_decide(text: str, reason: str, action: str = "add") -> str:
    """
    Record a decision, avoid pattern, or supersede existing decision.

    Args:
        text: The decision or avoid text
        reason: Why this decision was made
        action: "add" (default), "avoid", "supersede:OLD_TEXT", or
                "resolve:CONFLICT_ID"

    Examples:
        fo_decide("Use PostgreSQL", "Better for our scale")
        fo_decide("Never use eval()", "Security risk", action="avoid")
        fo_decide("Use MySQL", "Changed requirements", action="supersede:Use PostgreSQL")
    """
    if action == "avoid":
        return log_avoid(text, reason)
    elif action.startswith("resolve:"):
        conflict_id = action[len("resolve:"):].strip()
        if not conflict_id:
            return "Error: conflict id is required."
        return _resolve_decision_conflict_by_id(conflict_id, reason or text)
    elif action.startswith("supersede:"):
        old_text = action[10:]  # Remove "supersede:" prefix
        return supersede_decision(
            old_decision=old_text,
            new_decision=text,
            new_reason=reason,
            supersede_reason=reason,
        )
    else:
        return log_decision(text, reason)


@mcp.tool()
def fo_search(query: str, mode: str = "compact") -> str:
    """
    Search FixOnce memory for past solutions, decisions, and insights.

    IMPORTANT: Call this BEFORE trying to fix any error!

    Args:
        query: Search query (error message, topic, or keywords)
        mode: "compact" for concise recall, "expanded" for complete matched records
    """
    return search_past_solutions(query, mode=mode)


@mcp.tool()
def fo_brief(mode: str = "compact") -> str:
    """
    Return a deep onboarding brief for a new agent.

    This is intentionally deeper than fo_init and grouped by trust category:
    Decisions, Do Not Repeat, Solved Bugs, Risks, Recent Work, and Handoffs.

    Args:
        mode: "compact" for concise onboarding, "expanded" for full item text and all ranked records.
    """
    error, context = _universal_gate("fo_brief")
    if error:
        return error

    session = _get_session()
    memory = _load_project_lightweight(session.project_id)
    if not memory:
        return "No project memory found."
    return context + _format_deep_project_brief(memory, mode=mode)


@mcp.tool()
def fo_do_not_repeat(mode: str = "compact") -> str:
    """
    Return the compact do-not-repeat digest for future agents.

    Args:
        mode: "compact" for concise digest, "expanded" for full item text and all ranked records.
    """
    error, context = _universal_gate("fo_do_not_repeat")
    if error:
        return error

    session = _get_session()
    memory = _load_project_lightweight(session.project_id)
    if not memory:
        return "No project memory found."
    return context + _format_do_not_repeat_digest(memory, mode=mode)


@mcp.tool()
def fo_vision(action: str = "show", field: str = "", text: str = "", reason: str = "", mode: str = "compact") -> str:
    """
    Manage project-level vision memory.

    Args:
        action: "show", "audit", or "set"
        field: Vision field for set: mission, long_term_goal, current_direction,
               non_negotiables, success_criteria, or out_of_scope
        text: Vision text for set
        reason: Why this vision item is being added or changed
        mode: "compact" or "expanded"
    """
    error, context = _universal_gate("fo_vision")
    if error:
        return error

    session = _get_session()
    memory = _load_project(session.project_id)
    normalized_action = (action or "show").strip().lower()

    if normalized_action == "audit":
        audit = _audit_project_vision(memory)
        return context + json.dumps(audit, indent=2, ensure_ascii=False)

    if normalized_action == "set":
        key = _normalize_vision_key(field)
        if not key:
            return context + "Error: Unknown vision field."
        if not str(text or "").strip():
            return context + "Error: Vision text is required."
        _update_vision_memory(memory, {key: text}, reason=reason)
        _save_project(session.project_id, memory)
        audit = _audit_project_vision(memory)
        return context + f"Vision updated: {_VISION_FIELDS[key]}\nVision audit: {audit['status']}"

    if normalized_action != "show":
        return context + "Error: action must be show, audit, or set."

    return context + _format_project_vision(memory, mode=mode)


@mcp.tool()
def fo_solved(error: str, solution: str, files: str = "") -> str:
    """
    Record that you fixed an error. Saves solution for future use.

    Call this AFTER successfully fixing a bug.

    Args:
        error: The error message that was fixed
        solution: What you did to fix it (1-2 sentences)
        files: Comma-separated list of files changed
    """
    return solution_applied(error_message=error, solution=solution, files_changed=files)


@mcp.tool()
def fo_errors(limit: int = 5) -> str:
    """
    Get browser errors captured by FixOnce extension.

    Call this proactively when working on web projects.
    Returns errors AND any auto-fixes ready to apply.

    Args:
        limit: Max errors to return (default 5)
    """
    lines = []
    auto_fixes = []

    # Check for auto-fixes first
    try:
        from core.pending_fixes import get_auto_fixes, get_suggested_fixes

        auto_fixes = get_auto_fixes()
        suggested_fixes = get_suggested_fixes()

        if auto_fixes:
            lines.append(f"**AUTO-FIX READY** — call `fo_apply()` now (mandatory)")
            for fix in auto_fixes[:3]:
                lines.append(f"• {fix['error_message'][:50]}...")
            lines.append("")

        if suggested_fixes:
            lines.append(f"**{len(suggested_fixes)} suggested fix(es):**")
            for fix in suggested_fixes[:3]:
                lines.append(f"• {fix['error_message'][:60]} ({fix['confidence']}%)")
            lines.append("")

    except Exception as e:
        _log(f"[fo_errors] pending_fixes error: {e}")

    # Get browser errors
    errors_output = get_browser_errors(limit=limit)

    if lines:
        return "\n".join(lines) + errors_output
    return errors_output


@mcp.tool()
def fo_apply(fix_id: str = "") -> str:
    """
    Apply pending auto-fixes.

    Call this after fo_errors() shows auto-fixes ready.
    Without fix_id, applies ALL auto-fixes (confidence ≥90%).

    Args:
        fix_id: Specific fix ID to apply, or empty for all auto-fixes

    Returns:
        Instructions for what to fix
    """
    error, _ = _universal_gate("fo_apply")
    if error:
        return error

    try:
        from core.pending_fixes import get_auto_fixes, mark_fix_applied

        auto_fixes = get_auto_fixes()

        repeat_gate_result = _evaluate_current_repeat_bug_gate(
            tool_name="fo_apply",
            similar_past_solution_found=bool(auto_fixes)
        )

        if not auto_fixes or repeat_gate_result.level == "silent":
            return "No auto-fixes pending. Run `fo_errors()` first."

        # Filter by fix_id if provided
        if fix_id:
            auto_fixes = [f for f in auto_fixes if f["id"] == fix_id]
            if not auto_fixes:
                return f"Fix '{fix_id}' not found or not auto-applicable."

        lines = []

        for fix in auto_fixes:
            # Concise fix format
            lines.append(f"**Fix:** {fix['solution_text'][:100]}")
            if fix.get("files"):
                files_str = ", ".join(fix["files"]) if isinstance(fix["files"], list) else fix["files"]
                lines.append(f"**File:** {files_str}")
            lines.append("")

            # Mark as applied
            mark_fix_applied(fix["id"], success=True)

        completion_gate_result = _evaluate_current_completion_gate(
            tool_name="fo_apply",
            bug_fix_completed=True,
            fo_solved_called=False,
        )
        if completion_gate_result.level == "warn":
            lines.append("Run `fo_solved(error, solution)` when done.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error applying fixes: {e}"


@mcp.tool()
def fo_component(
    action: str,
    name: str = "",
    status: str = "",
    files: str = "",
    desc: str = ""
) -> str:
    """
    Manage component stability tracking.

    Args:
        action: One of: "status", "stable", "check", "add_files", "report", "discover", "rollback"
        name: Component name (required for most actions)
        status: New status for "status" action: "done", "in_progress", "blocked", "not_started"
        files: Comma-separated file list for "stable" or "add_files"
        desc: Description for "status" action

    Examples:
        fo_component("status", "Auth", status="done", desc="Login working")
        fo_component("stable", "Auth", files="src/auth.py,src/login.py")
        fo_component("check", "Auth")
        fo_component("report")
        fo_component("discover")
    """
    if action == "status":
        return update_component_status(name=name, status=status, desc=desc)
    elif action == "stable":
        return mark_component_stable(name=name, files=files)
    elif action == "check":
        return check_component_changes(name=name)
    elif action == "add_files":
        return add_component_files(name=name, files=files)
    elif action == "report":
        return get_stability_report()
    elif action == "discover":
        return auto_discover_components(apply=True)
    elif action == "rollback":
        return rollback_component(name=name)
    else:
        return f"Unknown action: {action}. Use: status, stable, check, add_files, report, discover, rollback"


@mcp.tool()
def fo_browser(action: str = "context", selector: str = "", message: str = "") -> str:
    """
    Browser context for AI Context mode.

    Args:
        action: "context" (get selected elements) or "highlight" (highlight element)
        selector: CSS selector for highlight action
        message: Message to show on highlight

    Examples:
        fo_browser("context")  # Get element user selected
        fo_browser("highlight", selector=".btn-submit", message="This button")
    """
    if action == "context":
        return get_browser_context()
    elif action == "highlight":
        return highlight_element(selector=selector, message=message)
    else:
        return f"Unknown action: {action}. Use: context, highlight"


# ============================================================
# COMPLIANCE API (For Dashboard Widget)
# ============================================================

def get_compliance_for_api() -> dict:
    """Get compliance status for dashboard API.

    Loads from file since Flask runs in different process than MCP.
    """
    # Load from file (shared between MCP and Flask processes)
    state = _load_compliance()
    return {
        "session_initialized": state.get("session_active", False),
        "initialized_at": state.get("initialized_at"),
        "decisions_displayed": state.get("decisions_displayed", False),
        "goal_updated": state.get("goal_updated", False),
        "search_performed": state.get("search_performed", False),
        "component_updated": state.get("component_updated", False),
        "decision_logged": state.get("decision_logged", False),
        "tool_calls_count": state.get("tool_calls_count", 0),
        "score": state.get("score", 0),
        "rules": state.get("rules", []),
        "last_session_init": state.get("last_session_init"),
        "violations": state.get("violations", [])[-5:],
        "editor": state.get("editor"),
        "project_id": state.get("project_id")
    }


if __name__ == "__main__":
    _install_mcp_process_event_probes()
    _mcp_process_identity("mcp main starting")
    try:
        _mcp_process_event("mcp.run entering")
        original_stdout = sys.stdout
        sys.stdout = _FoInitStdoutTraceProxy(original_stdout)
        try:
            mcp.run(show_banner=False)
        finally:
            sys.stdout = original_stdout
        _mcp_process_event("mcp.run returned without exception")
        try:
            from core.mcp_session_health import mark_session_lost
            mark_session_lost("MCP process exited; client transport closed", actor_identity=_mcp_actor_for_health())
        except Exception:
            pass
    except KeyboardInterrupt:
        _mcp_process_event("mcp.run interrupted by KeyboardInterrupt")
        try:
            from core.mcp_session_health import mark_session_lost
            mark_session_lost("MCP process interrupted by KeyboardInterrupt", actor_identity=_mcp_actor_for_health())
        except Exception:
            pass
        raise
    except BaseException as exc:
        _mcp_process_event(f"mcp.run crashed {type(exc).__name__}: {exc}")
        try:
            from core.mcp_session_health import mark_session_lost
            mark_session_lost(f"MCP process crashed: {type(exc).__name__}: {exc}", actor_identity=_mcp_actor_for_health())
        except Exception:
            pass
        traceback.print_exc(file=sys.stderr)
        raise
    finally:
        _mcp_process_event("mcp main finally reached")
