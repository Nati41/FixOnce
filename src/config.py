"""
FixOnce Configuration
Central configuration for all server components.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).parent
PROJECT_DIR = SRC_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

# Legacy alias for compatibility
SERVER_DIR = SRC_DIR

# Database paths
PERSONAL_DB_PATH = DATA_DIR / "personal_solutions.db"
TEAM_DB_PATH = None  # Set to a shared path for team DB, e.g.: Path("/shared/team_solutions.db")

# Memory file
MEMORY_FILE = DATA_DIR / "project_memory.json"

# Template file
MEMORY_TEMPLATE = DATA_DIR / "project_memory.template.json"

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
VERSION = "3.1"
APP_NAME = "FixOnce"
