"""
FixOnce installation state helpers.

Backend routes should treat a healthy canonical runtime as installed even when
install_state.json is missing, so dashboard access matches installer UI logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config import DATA_DIR
from core.port_manager import get_runtime_state


def _resolve_data_dir(data_dir: Optional[Path]) -> Path:
    """Resolve data dir at call time so tests and runtime patches stay effective."""
    return data_dir or DATA_DIR


def _read_install_state(data_dir: Optional[Path] = None) -> bool:
    """Return True when install_state.json explicitly marks installation done."""
    state_file = _resolve_data_dir(data_dir) / "install_state.json"
    if not state_file.exists():
        return False

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return False

    return bool(state.get("installed", False))


def _runtime_matches_request_port(request_port: Optional[int]) -> bool:
    """
    Treat a live canonical runtime on the current port as installed.

    This keeps backend routing aligned with the installer UI on dynamic ports
    without changing static website download behavior.
    """
    runtime_state = get_runtime_state()
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


def is_fixonce_installed(request_port: Optional[int] = None, data_dir: Optional[Path] = None) -> bool:
    """Return True when install state or canonical runtime indicates a ready install."""
    return _read_install_state(data_dir=data_dir) or _runtime_matches_request_port(request_port)
