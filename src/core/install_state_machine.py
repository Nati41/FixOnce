"""
Explicit installation state machine for FixOnce onboarding.

This module owns the persisted installer state in ~/.fixonce/install_state.json
and resolves whether the product is actually ready by combining that state with
the canonical runtime file.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from config import DATA_DIR
from core.port_manager import get_runtime_state


class InstallState(str, Enum):
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLING = "INSTALLING"
    STARTING = "STARTING"
    WAITING_HEALTH = "WAITING_HEALTH"
    READY = "READY"
    RECOVERY = "RECOVERY"
    FAILED = "FAILED"


@dataclass
class InstallSnapshot:
    state: InstallState = InstallState.NOT_INSTALLED
    updated_at: Optional[str] = None
    detail: str = ""
    install_dir: str = ""
    runtime_port: Optional[int] = None
    runtime_pid: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def installed(self) -> bool:
        return self.state == InstallState.READY


def _resolve_data_dir(data_dir: Optional[Path]) -> Path:
    return data_dir or DATA_DIR


def _state_file(data_dir: Optional[Path] = None) -> Path:
    return _resolve_data_dir(data_dir) / "install_state.json"


def _coerce_state(value: Any) -> InstallState:
    if isinstance(value, InstallState):
        return value
    try:
        return InstallState(str(value))
    except ValueError:
        return InstallState.NOT_INSTALLED


def _runtime_matches_request_port(runtime_state: Optional[Dict[str, Any]], request_port: Optional[int]) -> bool:
    if not runtime_state:
        return False

    runtime_port = runtime_state.get("port")
    try:
        runtime_port = int(runtime_port)
    except (TypeError, ValueError):
        return False

    if request_port is None:
        return True

    return runtime_port == request_port


def load_snapshot(data_dir: Optional[Path] = None) -> InstallSnapshot:
    path = _state_file(data_dir)
    if not path.exists():
        return InstallSnapshot()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return InstallSnapshot(state=InstallState.FAILED, detail="Invalid install_state.json")

    metadata = payload.get("metadata") or {}
    if payload.get("installed") is True and "state" not in payload:
        metadata = {**metadata, "legacy_installed": True}
        return InstallSnapshot(
            state=InstallState.READY,
            updated_at=payload.get("installed_at") or payload.get("updated_at"),
            detail=str(payload.get("detail", "Legacy install marker is present")),
            install_dir=str(payload.get("install_dir", "")),
            runtime_port=payload.get("runtime_port"),
            runtime_pid=payload.get("runtime_pid"),
            metadata=metadata,
        )

    return InstallSnapshot(
        state=_coerce_state(payload.get("state")),
        updated_at=payload.get("updated_at"),
        detail=str(payload.get("detail", "")),
        install_dir=str(payload.get("install_dir", "")),
        runtime_port=payload.get("runtime_port"),
        runtime_pid=payload.get("runtime_pid"),
        metadata=metadata,
    )


def persist_snapshot(
    state: InstallState,
    data_dir: Optional[Path] = None,
    *,
    detail: str = "",
    install_dir: str = "",
    runtime_port: Optional[int] = None,
    runtime_pid: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> InstallSnapshot:
    snapshot = InstallSnapshot(
        state=state,
        updated_at=datetime.now().isoformat(),
        detail=detail,
        install_dir=install_dir,
        runtime_port=runtime_port,
        runtime_pid=runtime_pid,
        metadata=metadata or {},
    )

    path = _state_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(snapshot), indent=2), encoding="utf-8")
    return snapshot


def resolve_install_snapshot(request_port: Optional[int] = None, data_dir: Optional[Path] = None) -> InstallSnapshot:
    snapshot = load_snapshot(data_dir)
    runtime_state = get_runtime_state()

    if _runtime_matches_request_port(runtime_state, request_port):
        snapshot.state = InstallState.READY
        snapshot.runtime_port = int(runtime_state["port"])
        snapshot.runtime_pid = int(runtime_state["pid"])
        if not snapshot.updated_at:
            snapshot.updated_at = datetime.now().isoformat()
        if not snapshot.detail:
            snapshot.detail = "Canonical runtime is healthy"
        return snapshot

    if snapshot.state == InstallState.READY and snapshot.metadata.get("active_install_flow"):
        snapshot.state = InstallState.STARTING
        if not snapshot.detail:
            snapshot.detail = "Runtime not available yet"

    return snapshot


def is_fixonce_ready(request_port: Optional[int] = None, data_dir: Optional[Path] = None) -> bool:
    return resolve_install_snapshot(request_port=request_port, data_dir=data_dir).installed
