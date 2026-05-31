"""
MCP session health state shared by MCP tools, APIs, dashboard, and diagnostics.

This tracks the AI-client <-> FixOnce MCP session, not the local FixOnce app.
The local server can be healthy while a specific AI chat has lost its MCP
transport.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from config import USER_DATA_DIR


STATE_CONNECTED = "connected"
STATE_DEGRADED = "degraded"
STATE_RECONNECTING = "reconnecting"
STATE_SESSION_LOST = "session_lost"
STATE_UNKNOWN = "unknown"

VALID_STATES = {
    STATE_CONNECTED,
    STATE_DEGRADED,
    STATE_RECONNECTING,
    STATE_SESSION_LOST,
    STATE_UNKNOWN,
}

SESSION_LOST_THRESHOLD = 2
STATE_FILE = USER_DATA_DIR / "mcp_session_health.json"
LOG_FILE = USER_DATA_DIR / "logs" / "mcp_session_health.jsonl"

TRANSPORT_PATTERNS = (
    r"transport\s+closed",
    r"broken\s+pipe",
    r"\beof\b",
    r"connection\s+reset",
    r"connection\s+aborted",
    r"process\s+exited",
    r"stdio\s+closed",
    r"stdin\s+closed",
    r"stdout\s+closed",
    r"session\s+invalid",
    r"invalid\s+session",
    r"no\s+valid\s+session\s+id",
    r"client\s+.*gone",
    r"tool\s+call\s+failed",
    r"connection\s+closed",
)


@dataclass
class MCPErrorClassification:
    is_transport_failure: bool
    normalized_message: str
    category: str


def _now() -> str:
    return datetime.now().isoformat()


def _default_state() -> Dict[str, Any]:
    return {
        "state": STATE_UNKNOWN,
        "consecutive_failures": 0,
        "last_success_at": None,
        "last_failure_at": None,
        "last_error": None,
        "last_error_category": None,
        "last_actor": None,
        "last_actor_source": None,
        "last_tool": None,
        "warning_generation": 0,
        "warning_acknowledged_generation": 0,
        "updated_at": _now(),
    }


def _read_state() -> Dict[str, Any]:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            state = _default_state()
            state.update({k: v for k, v in data.items() if k in state})
            if state.get("state") not in VALID_STATES:
                state["state"] = STATE_UNKNOWN
            return state
    except Exception:
        pass
    return _default_state()


def _write_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _log_event(event: str, **fields: Any) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": _now(),
            "event": event,
            **{k: v for k, v in fields.items() if v is not None},
        }
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def normalize_error_message(error: Any) -> str:
    raw = str(error or "").strip()
    raw = re.sub(r"\s+", " ", raw)
    return raw[:500]


def classify_mcp_error(error: Any) -> MCPErrorClassification:
    message = normalize_error_message(error)
    lowered = message.lower()
    is_transport = any(re.search(pattern, lowered) for pattern in TRANSPORT_PATTERNS)
    if is_transport:
        return MCPErrorClassification(True, message, "transport")
    if "timeout" in lowered or "timed out" in lowered:
        return MCPErrorClassification(False, message, "timeout")
    return MCPErrorClassification(False, message, "tool_error")


def _actor_hint(actor: Optional[str]) -> str:
    actor = (actor or "unknown").strip().lower()
    if actor == "codex":
        return "For Codex, open a new Codex chat or restart Codex."
    if actor == "cursor":
        return "For Cursor, toggle the FixOnce MCP server off and on in Settings, then reload or open a new chat if needed."
    if actor == "claude":
        return "For Claude, restart or reopen the Claude chat after reconnecting the FixOnce MCP server."
    return "If your client supports MCP reconnect, toggle the FixOnce MCP server off and on. Otherwise restart or reconnect the MCP host."


def user_message_for_state(state: Optional[Dict[str, Any]] = None) -> str:
    state = state or _read_state()
    actor = state.get("last_actor")
    return (
        "FixOnce lost the MCP connection for this chat/session. "
        "You can continue editing project files, but FixOnce memory, sync, dashboard live updates, "
        "and MCP tools may not update from this current chat. "
        "To reconnect FixOnce, open a new AI chat, restart/reopen the current chat, or reload the MCP client. "
        f"{_actor_hint(actor)}"
    )


def dashboard_message_for_state(state: Optional[Dict[str, Any]] = None) -> str:
    state = state or _read_state()
    if state.get("state") == STATE_SESSION_LOST:
        return (
            "FixOnce is running, but this AI chat lost its MCP connection. "
            "Open a new chat or reconnect your MCP client to resume FixOnce tools."
        )
    if state.get("state") == STATE_DEGRADED:
        return "FixOnce detected MCP connection trouble. If it continues, reconnect the AI chat or MCP client."
    if state.get("state") == STATE_CONNECTED:
        return "MCP connection active."
    return "MCP session status is unknown."


def get_session_health() -> Dict[str, Any]:
    state = _read_state()
    return {
        **state,
        "message": dashboard_message_for_state(state),
        "user_message": user_message_for_state(state) if state.get("state") == STATE_SESSION_LOST else None,
        "is_session_lost": state.get("state") == STATE_SESSION_LOST,
        "needs_reconnect": state.get("state") in {STATE_DEGRADED, STATE_RECONNECTING, STATE_SESSION_LOST},
    }


def record_mcp_success(tool_name: str = "", actor_identity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    previous = _read_state()
    actor_identity = actor_identity or {}
    state = previous.copy()
    state.update({
        "state": STATE_CONNECTED,
        "consecutive_failures": 0,
        "last_success_at": _now(),
        "last_actor": actor_identity.get("editor") or previous.get("last_actor"),
        "last_actor_source": actor_identity.get("source") or previous.get("last_actor_source"),
        "last_tool": tool_name or previous.get("last_tool"),
        "updated_at": _now(),
    })
    if previous.get("state") in {STATE_DEGRADED, STATE_RECONNECTING, STATE_SESSION_LOST}:
        _log_event(
            "successful_reconnection",
            previous_state=previous.get("state"),
            actor=state.get("last_actor"),
            actor_source=state.get("last_actor_source"),
            tool=tool_name,
        )
    _write_state(state)
    return state


def record_mcp_failure(
    error: Any,
    tool_name: str = "",
    actor_identity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    classification = classify_mcp_error(error)
    previous = _read_state()
    actor_identity = actor_identity or {}
    state = previous.copy()

    if classification.is_transport_failure:
        failures = int(previous.get("consecutive_failures") or 0) + 1
        next_state = STATE_SESSION_LOST if failures >= SESSION_LOST_THRESHOLD else STATE_DEGRADED
    else:
        failures = int(previous.get("consecutive_failures") or 0)
        next_state = previous.get("state") if previous.get("state") in VALID_STATES else STATE_UNKNOWN

    state.update({
        "state": next_state,
        "consecutive_failures": failures,
        "last_failure_at": _now(),
        "last_error": classification.normalized_message,
        "last_error_category": classification.category,
        "last_actor": actor_identity.get("editor") or previous.get("last_actor"),
        "last_actor_source": actor_identity.get("source") or previous.get("last_actor_source"),
        "last_tool": tool_name or previous.get("last_tool"),
        "updated_at": _now(),
    })

    if next_state != previous.get("state"):
        if next_state == STATE_DEGRADED:
            _log_event(
                "degraded_state",
                actor=state.get("last_actor"),
                actor_source=state.get("last_actor_source"),
                tool=tool_name,
                normalized_error=classification.normalized_message,
            )
        elif next_state == STATE_SESSION_LOST:
            state["warning_generation"] = int(previous.get("warning_generation") or 0) + 1
            _log_event(
                "session_lost_state",
                actor=state.get("last_actor"),
                actor_source=state.get("last_actor_source"),
                tool=tool_name,
                normalized_error=classification.normalized_message,
                consecutive_failures=failures,
            )
    elif classification.is_transport_failure and failures == 1:
        _log_event(
            "first_transport_failure",
            actor=state.get("last_actor"),
            actor_source=state.get("last_actor_source"),
            tool=tool_name,
            normalized_error=classification.normalized_message,
        )

    _write_state(state)
    return state


def mark_recovery_attempt(actor: Optional[str] = None, source: str = "dashboard") -> Dict[str, Any]:
    state = _read_state()
    state.update({
        "state": STATE_RECONNECTING,
        "updated_at": _now(),
    })
    _write_state(state)
    _log_event("recovery_attempt", actor=actor or state.get("last_actor"), source=source)
    return state


def mark_session_lost(
    reason: str,
    actor_identity: Optional[Dict[str, Any]] = None,
    tool_name: str = "",
) -> Dict[str, Any]:
    actor_identity = actor_identity or {}
    previous = _read_state()
    state = previous.copy()
    normalized = normalize_error_message(reason)
    state.update({
        "state": STATE_SESSION_LOST,
        "consecutive_failures": max(int(previous.get("consecutive_failures") or 0), SESSION_LOST_THRESHOLD),
        "last_failure_at": _now(),
        "last_error": normalized,
        "last_error_category": "transport",
        "last_actor": actor_identity.get("editor") or previous.get("last_actor"),
        "last_actor_source": actor_identity.get("source") or previous.get("last_actor_source"),
        "last_tool": tool_name or previous.get("last_tool"),
        "updated_at": _now(),
    })
    if previous.get("state") != STATE_SESSION_LOST:
        state["warning_generation"] = int(previous.get("warning_generation") or 0) + 1
        _log_event(
            "session_lost_state",
            actor=state.get("last_actor"),
            actor_source=state.get("last_actor_source"),
            tool=tool_name,
            normalized_error=normalized,
            source="process_lifecycle",
        )
    _write_state(state)
    return state


def mark_warning_acknowledged() -> Dict[str, Any]:
    state = _read_state()
    state["warning_acknowledged_generation"] = state.get("warning_generation", 0)
    state["updated_at"] = _now()
    _write_state(state)
    return state
