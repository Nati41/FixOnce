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

# Installation data directory (templates, dashboard, static files)
# This is shared across users - READ ONLY
INSTALL_DATA_DIR = PROJECT_ROOT / "data"

# User-specific data directory (~/.fixonce/)
# This is private per user - READ/WRITE
def get_user_data_dir() -> Path:
    """Get the user-specific data directory."""
    user_dir = Path.home() / ".fixonce"
    user_dir.mkdir(exist_ok=True)
    return user_dir

# Use Windows bootstrap for EXE mode, user home for normal operation
if getattr(sys, 'frozen', False):
    # Running as PyInstaller EXE - import bootstrap module
    try:
        from src.windows_bootstrap import get_data_dir
        USER_DATA_DIR = get_data_dir()
    except ImportError:
        from windows_bootstrap import get_data_dir
        USER_DATA_DIR = get_data_dir()
else:
    # Running as script - use user's home directory
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
# Version
# ---------------------------------------------------------------------------
VERSION = "1.0"
APP_NAME = "FixOnce"
