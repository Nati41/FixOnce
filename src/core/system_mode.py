"""
Global FixOnce operating mode management.

Modes:
- full: all features enabled
- passive: read/observe only, no active interventions
- off: FixOnce tooling disabled
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict

from config import DATA_DIR

SYSTEM_MODE_FILE = DATA_DIR / "system_mode.json"
LEGACY_ENABLED_FILE = DATA_DIR / "fixonce_enabled.json"

MODE_FULL = "full"
MODE_PASSIVE = "passive"
MODE_OFF = "off"
VALID_MODES = {MODE_FULL, MODE_PASSIVE, MODE_OFF}

_lock = Lock()


def _read_json(path: Path) -> Dict:
    try:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_json(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_system_mode() -> Dict[str, str]:
    """Get current global FixOnce mode with metadata."""
    with _lock:
        data = _read_json(SYSTEM_MODE_FILE)
        mode = str(data.get("mode", MODE_FULL)).strip().lower()

        if mode in VALID_MODES:
            return {
                "mode": mode,
                "updated_at": data.get("updated_at"),
                "updated_by": data.get("updated_by", "unknown"),
            }

        # Backward compatibility with legacy enabled toggle.
        legacy = _read_json(LEGACY_ENABLED_FILE)
        enabled = bool(legacy.get("enabled", True))
        mode = MODE_FULL if enabled else MODE_OFF
        return {
            "mode": mode,
            "updated_at": data.get("updated_at") or legacy.get("updated_at"),
            "updated_by": data.get("updated_by") or legacy.get("updated_by", "legacy"),
        }


def set_system_mode(mode: str, updated_by: str = "dashboard") -> Dict[str, str]:
    """Persist global mode and keep legacy enabled flag aligned."""
    normalized = str(mode or "").strip().lower()
    if normalized not in VALID_MODES:
        raise ValueError(f"Invalid mode '{mode}'. Valid: {sorted(VALID_MODES)}")

    payload = {
        "mode": normalized,
        "updated_at": datetime.now().isoformat(),
        "updated_by": updated_by,
    }

    with _lock:
        _write_json(SYSTEM_MODE_FILE, payload)
        _write_json(
            LEGACY_ENABLED_FILE,
            {
                "enabled": normalized != MODE_OFF,
                "updated_at": payload["updated_at"],
                "updated_by": updated_by,
            },
        )

    return payload

