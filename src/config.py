"""
FixOnce Configuration
Central configuration for all server components.

MULTI-USER ARCHITECTURE:
- INSTALL_DATA_DIR: Installation assets (dashboard.html, templates) - shared, read-only
- USER_DATA_DIR: Per-user data (~/.fixonce/) - private, read-write
- DATA_DIR: Legacy alias pointing to USER_DATA_DIR for compatibility
"""

import sys
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths - Multi-User Safe
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).parent
PROJECT_ROOT = SRC_DIR.parent

def get_install_data_dir() -> Path:
    """Get installation assets directory for source and PyInstaller layouts."""
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "data")

    executable_dir = Path(sys.executable).resolve().parent
    candidates.extend([
        executable_dir / "_internal" / "data",
        executable_dir / "data",
        Path.cwd() / "_internal" / "data",
        Path.cwd() / "data",
    ])

    for parent in [SRC_DIR, *SRC_DIR.parents]:
        candidates.extend([
            parent / "data",
            parent / "_internal" / "data",
        ])

    seen = set()
    unique_candidates = []
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(candidate)

    for candidate in unique_candidates:
        if (candidate / "dashboard.html").exists():
            return candidate

    return unique_candidates[0]


# Installation data directory (templates, dashboard, static files)
# This is shared across users - READ ONLY
INSTALL_DATA_DIR = get_install_data_dir()

# User-specific data directory (~/.fixonce/)
# This is private per user - READ/WRITE
def get_user_data_dir() -> Path:
    """Get the user-specific data directory."""
    override = os.environ.get("FIXONCE_USER_DATA_DIR", "").strip()
    user_dir = Path(override).expanduser() if override else Path.home() / ".fixonce"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir

# User runtime state must always live in ~/.fixonce, including Windows EXE mode.
# Installation assets may be bundled elsewhere, but install_state.json is per-user.
USER_DATA_DIR = get_user_data_dir()

# DATA_DIR now points to USER data (private per user)
# For templates/dashboard, use INSTALL_DATA_DIR
DATA_DIR = USER_DATA_DIR

# Ensure user data directory exists with subdirectories
(USER_DATA_DIR / "projects_v2").mkdir(exist_ok=True)
(USER_DATA_DIR / "logs").mkdir(exist_ok=True)

# Legacy alias for compatibility
SERVER_DIR = SRC_DIR

# Database paths - USER SPECIFIC
PERSONAL_DB_PATH = USER_DATA_DIR / "personal_solutions.db"
TEAM_DB_PATH = None  # Set to a shared path for team DB

# Memory file - USER SPECIFIC
MEMORY_FILE = USER_DATA_DIR / "project_memory.json"

# Template file - from INSTALLATION (read-only)
MEMORY_TEMPLATE = INSTALL_DATA_DIR / "project_memory.template.json"

# ---------------------------------------------------------------------------
# Server Configuration
# ---------------------------------------------------------------------------
DEFAULT_PORT = 5000
MAX_PORT_ATTEMPTS = 10

# ---------------------------------------------------------------------------
# Error Log Configuration
# ---------------------------------------------------------------------------
MAX_ERROR_LOG_SIZE = 50  # Maximum errors to keep in memory

# ---------------------------------------------------------------------------
# Version (imported from version.py - single source of truth)
# ---------------------------------------------------------------------------
from version import VERSION
APP_NAME = "FixOnce"
