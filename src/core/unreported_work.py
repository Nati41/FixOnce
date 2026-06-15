"""Operational state for meaningful AI work that has not been synced."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from config import USER_DATA_DIR


STATE_FILE = USER_DATA_DIR / "unreported_work.json"
SUPPORTED_ACTORS = {"claude", "codex"}
SYNC_TOOLS = {"fo_sync", "fo_solved", "fo_decide"}

# Files that don't represent meaningful project work
INSIGNIFICANT_PATH_PATTERNS = [
    r"\.claude\.json$",
    r"\.claude/",
    r"claude_desktop_config\.json$",
    r"\.cursor/",
    r"\.codex/",
    r"website/",
    r"screenshots?/",
    r"\.png$",
    r"\.jpg$",
    r"\.jpeg$",
    r"\.gif$",
    r"\.ico$",
    r"\.svg$",
    r"\.webp$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    r"\.min\.(js|css)$",
    r"dist/",
    r"build/",
    r"node_modules/",
    r"__pycache__/",
    r"\.pyc$",
    r"\.DS_Store$",
]
_INSIGNIFICANT_RE = re.compile("|".join(INSIGNIFICANT_PATH_PATTERNS), re.IGNORECASE)

# Minimum significant files before showing warning
SIGNIFICANCE_THRESHOLD = 3


def is_significant_path(file_path: str) -> bool:
    """Check if a file path represents meaningful project work."""
    if not file_path:
        return False
    return not bool(_INSIGNIFICANT_RE.search(file_path))
_LOCK = threading.Lock()
_PROCESS_LOCK_TIMEOUT_SECONDS = 0.25


def _now() -> str:
    return datetime.now().isoformat()


def _key(project_id: str, actor: str) -> str:
    return f"{project_id}:{actor}"


def _default_payload() -> Dict[str, Any]:
    return {"version": 1, "updated_at": None, "entries": {}}


def _read_payload() -> Dict[str, Any]:
    try:
        if STATE_FILE.exists():
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("entries"), dict):
                return payload
    except Exception:
        pass
    return _default_payload()


@contextmanager
def _process_lock():
    lock_path = STATE_FILE.with_suffix(".work.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _PROCESS_LOCK_TIMEOUT_SECONDS
    fd = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 5:
                    lock_path.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not acquire operational state lock: {lock_path}")
            time.sleep(0.01)

    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except OSError:
            pass


def _update_payload(mutator) -> Dict[str, Any]:
    with _LOCK, _process_lock():
        payload = _read_payload()
        mutator(payload)
        payload["version"] = 1
        payload["updated_at"] = _now()
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            dir=STATE_FILE.parent,
            prefix=f".{STATE_FILE.stem}_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, STATE_FILE)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
        return payload


def _normalize_actor(actor: str) -> str:
    return str(actor or "").strip().lower()


def mark_work(
    project_id: str,
    actor: str,
    kind: str,
    *,
    file_path: str = "",
    command: str = "",
    session_id: str = "",
    source: str = "",
) -> Optional[Dict[str, Any]]:
    """Mark a supported actor/project pair dirty after meaningful work."""
    normalized_actor = _normalize_actor(actor)
    if normalized_actor not in SUPPORTED_ACTORS or not project_id or project_id == "__global__":
        return None

    timestamp = _now()
    result = {}
    path_is_significant = is_significant_path(file_path)

    def mutate(payload):
        nonlocal result
        entries = payload.setdefault("entries", {})
        entry = entries.get(_key(project_id, normalized_actor), {})
        sequence = int(entry.get("last_work_seq") or 0) + 1
        files = list(entry.get("files") or [])
        significant_files = list(entry.get("significant_files") or [])

        if file_path and file_path not in files:
            files.append(file_path)
        if file_path and path_is_significant and file_path not in significant_files:
            significant_files.append(file_path)

        entry.update({
            "project_id": project_id,
            "actor": normalized_actor,
            "session_id": session_id or entry.get("session_id", ""),
            "dirty": True,
            "dirty_since": entry.get("dirty_since") or timestamp,
            "last_work_at": timestamp,
            "last_work_kind": kind,
            "last_work_seq": sequence,
            "last_sync_at": entry.get("last_sync_at"),
            "last_sync_tool": entry.get("last_sync_tool"),
            "last_sync_seq": int(entry.get("last_sync_seq") or 0),
            "files": files[-20:],
            "significant_files": significant_files[-20:],
            "command": command[:500],
            "source": source,
        })
        entries[_key(project_id, normalized_actor)] = entry
        result = dict(entry)

    _update_payload(mutate)
    return result


def mark_synced(
    project_id: str,
    actor: str,
    tool_name: str,
    *,
    session_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Clear dirty state after an approved FixOnce sync tool succeeds."""
    normalized_actor = _normalize_actor(actor)
    if (
        normalized_actor not in SUPPORTED_ACTORS
        or tool_name not in SYNC_TOOLS
        or not project_id
        or project_id == "__global__"
    ):
        return None

    timestamp = _now()
    result = {}

    def mutate(payload):
        nonlocal result
        entries = payload.setdefault("entries", {})
        entry = entries.get(_key(project_id, normalized_actor), {
            "project_id": project_id,
            "actor": normalized_actor,
            "last_work_seq": 0,
            "files": [],
            "significant_files": [],
        })
        entry.update({
            "session_id": session_id or entry.get("session_id", ""),
            "dirty": False,
            "dirty_since": None,
            "last_sync_at": timestamp,
            "last_sync_tool": tool_name,
            "last_sync_seq": int(entry.get("last_work_seq") or 0),
            "files": [],
            "significant_files": [],
            "command": "",
        })
        entries[_key(project_id, normalized_actor)] = entry
        result = dict(entry)

    _update_payload(mutate)
    return result


def should_show_unsynced_warning(work_state: Dict[str, Any]) -> bool:
    """Check if work state warrants showing an unsynced warning to the user."""
    if not work_state.get("dirty"):
        return False

    significant_files = work_state.get("significant_files") or []
    if len(significant_files) >= SIGNIFICANCE_THRESHOLD:
        return True

    return False


def get_state(project_id: str, actor: str) -> Dict[str, Any]:
    normalized_actor = _normalize_actor(actor)
    payload = _read_payload()
    entry = payload.get("entries", {}).get(_key(project_id, normalized_actor), {})
    return dict(entry)


def get_actor_states(actor: str) -> list[Dict[str, Any]]:
    normalized_actor = _normalize_actor(actor)
    payload = _read_payload()
    entries = payload.get("entries", {}).values()
    return [
        dict(entry)
        for entry in entries
        if entry.get("actor") == normalized_actor
    ]


def get_latest_actor_state(actor: str, project_id: str = "") -> Dict[str, Any]:
    if project_id:
        return get_state(project_id, actor)
    states = get_actor_states(actor)
    return max(states, key=lambda item: item.get("last_work_at") or item.get("last_sync_at") or "", default={})


def get_project_states(project_id: str) -> list[Dict[str, Any]]:
    payload = _read_payload()
    return [
        dict(entry)
        for entry in payload.get("entries", {}).values()
        if entry.get("project_id") == project_id
    ]
