"""
Compatibility helpers around the explicit install state machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import DATA_DIR  # compatibility for tests patching install-state data dir
from core.port_manager import get_runtime_state
import core.install_state_machine as install_state_machine

InstallState = install_state_machine.InstallState


def _resolve_data_dir(data_dir: Optional[Path] = None) -> Path:
    return data_dir or DATA_DIR


def is_fixonce_installed(request_port: Optional[int] = None, data_dir: Optional[Path] = None) -> bool:
    """Return True when FixOnce is actually ready for the current runtime."""
    install_state_machine.get_runtime_state = get_runtime_state
    return install_state_machine.is_fixonce_ready(request_port=request_port, data_dir=_resolve_data_dir(data_dir))


def get_install_snapshot(request_port: Optional[int] = None, data_dir: Optional[Path] = None):
    """Expose the resolved snapshot for API/UI callers."""
    install_state_machine.get_runtime_state = get_runtime_state
    return install_state_machine.resolve_install_snapshot(request_port=request_port, data_dir=_resolve_data_dir(data_dir))


def mark_install_state(
    state: InstallState,
    data_dir: Optional[Path] = None,
    *,
    detail: str = "",
    install_dir: str = "",
    runtime_port: Optional[int] = None,
    runtime_pid: Optional[int] = None,
    metadata: Optional[dict] = None,
):
    """Persist an explicit installer state transition."""
    return install_state_machine.persist_snapshot(
        state,
        data_dir=_resolve_data_dir(data_dir),
        detail=detail,
        install_dir=install_dir,
        runtime_port=runtime_port,
        runtime_pid=runtime_pid,
        metadata=metadata,
    )


def load_install_snapshot(data_dir: Optional[Path] = None):
    """Expose raw snapshot loading for tests and diagnostics."""
    return install_state_machine.load_snapshot(data_dir=_resolve_data_dir(data_dir))
