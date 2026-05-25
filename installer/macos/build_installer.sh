#!/bin/bash
# ============================================================
# FixOnce macOS Installer Builder
# Creates FixOnce Installer.app and packages it into a DMG
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
APP_NAME="FixOnce Installer"
DMG_NAME="FixOnce-Installer"
VERSION=$(cat "$PROJECT_ROOT/src/version.py" 2>/dev/null | grep -o '"[^"]*"' | tr -d '"' || echo "1.0.0")

echo "========================================"
echo "  FixOnce macOS Installer Builder"
echo "  Version: $VERSION"
echo "========================================"
echo ""

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# ============================================================
# Step 1: Create .app bundle structure
# ============================================================
echo "[1/5] Creating app bundle structure..."

APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
CONTENTS="$APP_BUNDLE/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

mkdir -p "$MACOS"
mkdir -p "$RESOURCES"

# ============================================================
# Step 2: Create Info.plist
# ============================================================
echo "[2/5] Creating Info.plist..."

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>FixOnce Installer</string>
    <key>CFBundleDisplayName</key>
    <string>FixOnce Installer</string>
    <key>CFBundleIdentifier</key>
    <string>com.fixonce.installer</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>installer</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
    <key>NSHumanReadableCopyright</key>
    <string>Copyright 2026 FixOnce. All rights reserved.</string>
</dict>
</plist>
PLIST

# ============================================================
# Step 3: Copy FixOnce source files
# ============================================================
echo "[3/5] Copying FixOnce files..."

# Copy essential directories
cp -R "$PROJECT_ROOT/src" "$RESOURCES/"
cp -R "$PROJECT_ROOT/scripts" "$RESOURCES/"
cp -R "$PROJECT_ROOT/data" "$RESOURCES/"
cp -R "$PROJECT_ROOT/extension" "$RESOURCES/" 2>/dev/null || true
cp "$PROJECT_ROOT/requirements.txt" "$RESOURCES/"
cp "$PROJECT_ROOT/CLAUDE.md" "$RESOURCES/" 2>/dev/null || true

# Clean up __pycache__ and .pyc files
find "$RESOURCES" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$RESOURCES" -name "*.pyc" -delete 2>/dev/null || true
find "$RESOURCES" -name ".DS_Store" -delete 2>/dev/null || true

# ============================================================
# Step 4: Create main executable
# ============================================================
echo "[4/5] Creating installer executable..."

cat > "$MACOS/installer" << 'INSTALLER_SCRIPT'
#!/bin/bash
# ============================================================
# FixOnce Installer - Main Executable
# ============================================================

# Get the Resources directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES="$SCRIPT_DIR/../Resources"

# Installation target
INSTALL_DIR="$HOME/FixOnce"
LOG_FILE="/tmp/fixonce_install.log"

# Colors for terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================
# Helper Functions
# ============================================================

log() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

show_dialog() {
    osascript -e "display dialog \"$1\" with title \"FixOnce Installer\" buttons {\"OK\"} default button \"OK\" with icon note"
}

show_error() {
    osascript -e "display dialog \"$1\" with title \"FixOnce Installer\" buttons {\"OK\"} default button \"OK\" with icon stop"
}

show_progress() {
    osascript -e "display notification \"$1\" with title \"FixOnce Installer\""
}

ask_continue() {
    result=$(osascript -e 'display dialog "'"$1"'" with title "FixOnce Installer" buttons {"Cancel", "Continue"} default button "Continue" with icon caution' 2>/dev/null)
    if [[ "$result" == *"Cancel"* ]]; then
        return 1
    fi
    return 0
}

write_install_state() {
    local state="$1"
    local detail="${2:-}"
    local install_state_dir="$HOME/.fixonce"
    local install_state_file="$install_state_dir/install_state.json"
    mkdir -p "$install_state_dir"

    python3 - "$install_state_file" "$state" "$detail" "$INSTALL_DIR" << 'PY'
import json
import sys
from datetime import datetime, timezone

target, state, detail, install_dir = sys.argv[1:]
payload = {
    "state": state,
    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "detail": detail,
    "install_dir": install_dir,
    "metadata": {"source": "macos_installer_app"},
}

with open(target, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
PY
}

# ============================================================
# Pre-flight Checks
# ============================================================

# Global: selected Python interpreter (set by preflight)
SELECTED_PYTHON=""
SELECTED_PYTHON_VERSION=""

preflight() {
    log "${BLUE}Running pre-flight checks...${NC}"

    # ========== PYTHON DISCOVERY ==========
    # Find Python >= 3.10 with absolute path
    # Priority: python3.13, python3.12, python3.11, python3.10, then python3 if version OK
    log "  Searching for Python >= 3.10..."

    PYTHON_CANDIDATES=(
        "/usr/local/bin/python3.13"
        "/opt/homebrew/bin/python3.13"
        "/usr/local/bin/python3.12"
        "/opt/homebrew/bin/python3.12"
        "/usr/local/bin/python3.11"
        "/opt/homebrew/bin/python3.11"
        "/usr/local/bin/python3.10"
        "/opt/homebrew/bin/python3.10"
        "/usr/local/bin/python3"
        "/opt/homebrew/bin/python3"
        "/usr/bin/python3"
    )

    for candidate in "${PYTHON_CANDIDATES[@]}"; do
        if [ -x "$candidate" ]; then
            # Get version
            VERSION=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
            MAJOR=$("$candidate" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)
            MINOR=$("$candidate" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)

            if [ -n "$MAJOR" ] && [ -n "$MINOR" ]; then
                log "    Found: $candidate (Python $VERSION)"

                # Check version >= 3.10
                if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; then
                    SELECTED_PYTHON="$candidate"
                    SELECTED_PYTHON_VERSION="$VERSION"
                    log "  ${GREEN}✓${NC} Selected: $SELECTED_PYTHON (Python $SELECTED_PYTHON_VERSION)"
                    break
                else
                    log "    ${YELLOW}!${NC} Skipping $candidate (Python $VERSION < 3.10)"
                fi
            fi
        fi
    done

    # Fail if no suitable Python found
    if [ -z "$SELECTED_PYTHON" ]; then
        log "${RED}✗${NC} No Python >= 3.10 found!"
        show_error "Python 3.10 or higher is required.\n\nFound interpreters are too old.\n\nInstall Python 3.10+ from:\n• python.org\n• brew install python@3.12"
        exit 1
    fi

    # ========== OTHER CHECKS ==========
    # Check if already installed
    if [ -d "$INSTALL_DIR" ]; then
        if ! ask_continue "FixOnce is already installed at:\n$INSTALL_DIR\n\nDo you want to upgrade/reinstall?"; then
            log "Installation cancelled by user"
            exit 0
        fi
        log "${YELLOW}!${NC} Existing installation will be updated"
    fi

    # Check disk space (need at least 100MB)
    FREE_SPACE=$(df -m "$HOME" | awk 'NR==2 {print $4}')
    if [ "$FREE_SPACE" -lt 100 ]; then
        show_error "Not enough disk space.\n\nRequired: 100MB\nAvailable: ${FREE_SPACE}MB"
        exit 1
    fi
    log "${GREEN}✓${NC} Disk space OK (${FREE_SPACE}MB free)"

    # Check write permissions
    if ! touch "$HOME/.fixonce_test" 2>/dev/null; then
        show_error "Cannot write to home directory.\n\nPlease check permissions for:\n$HOME"
        exit 1
    fi
    rm -f "$HOME/.fixonce_test"
    log "${GREEN}✓${NC} Write permissions OK"

    log "${GREEN}Pre-flight checks passed${NC}"
}

# ============================================================
# Installation (Complete Purge + Fresh Copy)
# ============================================================

install_files() {
    log "${BLUE}Installing FixOnce...${NC}"
    write_install_state "INSTALLING" "Copying application files"

    # ========== COMPLETE PURGE ==========
    # Remove any existing installation to ensure clean state
    if [ -d "$INSTALL_DIR" ]; then
        log "  Removing old installation at $INSTALL_DIR..."
        rm -rf "$INSTALL_DIR"
    fi

    # Remove old CLI symlink
    if [ -L "/usr/local/bin/fixonce" ] || [ -f "/usr/local/bin/fixonce" ]; then
        log "  Removing old CLI symlink..."
        rm -f "/usr/local/bin/fixonce" 2>/dev/null || sudo rm -f "/usr/local/bin/fixonce" 2>/dev/null || true
    fi

    # ========== FRESH INSTALL ==========
    log "  Creating fresh installation directory..."
    mkdir -p "$INSTALL_DIR"

    # Copy ALL files using cp -a (preserves attributes, follows structure)
    log "  Copying source files..."
    cp -a "$RESOURCES/src" "$INSTALL_DIR/"
    cp -a "$RESOURCES/scripts" "$INSTALL_DIR/"
    cp -a "$RESOURCES/data" "$INSTALL_DIR/"
    cp -a "$RESOURCES/extension" "$INSTALL_DIR/" 2>/dev/null || true
    cp -a "$RESOURCES/requirements.txt" "$INSTALL_DIR/"
    cp -a "$RESOURCES/CLAUDE.md" "$INSTALL_DIR/" 2>/dev/null || true

    # ========== VERIFY COPY ==========
    log "  Verifying installation..."

    # Check critical files exist
    CRITICAL_FILES=(
        "src/config.py"
        "src/server.py"
        "src/version.py"
        "src/mcp_server/mcp_memory_server_v2.py"
        "src/core/port_manager.py"
        "scripts/install.py"
        "requirements.txt"
        "data/dashboard.html"
    )

    MISSING_FILES=""
    for file in "${CRITICAL_FILES[@]}"; do
        if [ ! -f "$INSTALL_DIR/$file" ]; then
            MISSING_FILES="$MISSING_FILES\n  - $file"
        fi
    done

    if [ -n "$MISSING_FILES" ]; then
        log "${RED}✗${NC} Copy failed! Missing files:$MISSING_FILES"
        show_error "Installation failed: Source files not copied correctly.\n\nMissing files:$MISSING_FILES\n\nPlease re-download the installer."
        exit 1
    fi

    # Verify config.py has Path.home() (not hardcoded paths)
    if ! grep -q "Path.home()" "$INSTALL_DIR/src/config.py"; then
        log "${RED}✗${NC} config.py doesn't use Path.home() - wrong version!"
        show_error "Installation failed: Wrong version of config.py bundled."
        exit 1
    fi

    log "${GREEN}✓${NC} Files copied and verified at $INSTALL_DIR"

    # ========== USER DATA DIRECTORY ==========
    # Create user-specific data directory
    USER_DATA="$HOME/.fixonce"
    mkdir -p "$USER_DATA"
    mkdir -p "$USER_DATA/projects_v2"
    mkdir -p "$USER_DATA/logs"

    log "${GREEN}✓${NC} User data directory created at $USER_DATA"

    # Create .fixonce metadata in INSTALL_DIR for project detection
    mkdir -p "$INSTALL_DIR/.fixonce"
    PROJECT_ID="FixOnce_$(openssl rand -hex 4)"
    cat > "$INSTALL_DIR/.fixonce/metadata.json" << EOF
{
  "fixonce_version": "$VERSION",
  "project_id": "$PROJECT_ID",
  "name": "FixOnce",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "working_dir_original": "$INSTALL_DIR"
}
EOF
    log "${GREEN}✓${NC} Created project metadata"
}

# ============================================================
# Install Python Dependencies
# ============================================================

install_dependencies() {
    log "${BLUE}Installing Python dependencies...${NC}"
    write_install_state "INSTALLING" "Installing application dependencies"

    cd "$INSTALL_DIR"

    # Verify requirements.txt exists
    if [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
        log "${RED}✗${NC} requirements.txt not found!"
        show_error "Installation failed: requirements.txt missing.\n\nPlease re-download the installer."
        exit 1
    fi

    # Create virtual environment using SELECTED_PYTHON (set by preflight)
    # Always recreate to ensure correct Python version
    if [ -d "$INSTALL_DIR/venv" ]; then
        log "  Removing old venv (may have wrong Python version)..."
        rm -rf "$INSTALL_DIR/venv"
    fi

    log "  Creating virtual environment with $SELECTED_PYTHON..."
    if ! "$SELECTED_PYTHON" -m venv "$INSTALL_DIR/venv"; then
        log "${RED}✗${NC} Failed to create virtual environment"
        show_error "Installation failed: Could not create Python virtual environment.\n\nUsed: $SELECTED_PYTHON\n\nTry: brew install python@3.12"
        exit 1
    fi
    log "${GREEN}✓${NC} Created virtual environment"

    # Use absolute paths for venv python/pip
    VENV_PYTHON="$INSTALL_DIR/venv/bin/python"
    VENV_PIP="$INSTALL_DIR/venv/bin/pip"

    # Verify venv python exists
    if [ ! -f "$VENV_PYTHON" ]; then
        log "${RED}✗${NC} venv Python not found at $VENV_PYTHON"
        show_error "Installation failed: Virtual environment is corrupted.\n\nTry deleting ~/FixOnce/venv and reinstalling."
        exit 1
    fi

    # Verify venv Python version >= 3.10
    VENV_VERSION=$("$VENV_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
    VENV_MAJOR=$("$VENV_PYTHON" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)
    VENV_MINOR=$("$VENV_PYTHON" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)

    log "  venv Python version: $VENV_VERSION"

    if [ "$VENV_MAJOR" -ne 3 ] || [ "$VENV_MINOR" -lt 10 ]; then
        log "${RED}✗${NC} venv Python $VENV_VERSION < 3.10 - fastmcp won't work!"
        show_error "Virtual environment created with wrong Python.\n\nvenv Python: $VENV_VERSION (need >= 3.10)\n\nInstall Python 3.10+:\nbrew install python@3.12"
        exit 1
    fi
    log "${GREEN}✓${NC} venv Python $VENV_VERSION >= 3.10"

    # Upgrade pip first
    log "  Upgrading pip..."
    if ! "$VENV_PYTHON" -m pip install --upgrade pip 2>&1 | tee -a "$LOG_FILE"; then
        log "${YELLOW}!${NC} pip upgrade failed (continuing anyway)"
    fi

    # Install dependencies with explicit path and error checking
    log "  Installing dependencies from requirements.txt..."
    if ! "$VENV_PYTHON" -m pip install -r "$INSTALL_DIR/requirements.txt" 2>&1 | tee -a "$LOG_FILE"; then
        log "${RED}✗${NC} pip install failed!"
        show_error "Installation failed: Could not install Python dependencies.\n\nCheck the log at:\n$LOG_FILE\n\nCommon fixes:\n• Check internet connection\n• Try: pip install flask flask-cors"
        exit 1
    fi

    # Verify critical packages are installed
    log "  Verifying packages..."
    MISSING_PACKAGES=""

    # Check each package individually with logging
    # flask
    if "$VENV_PYTHON" -c "import flask" 2>/dev/null; then
        log "    ${GREEN}✓${NC} flask"
    else
        log "    ${RED}✗${NC} flask"
        MISSING_PACKAGES="$MISSING_PACKAGES flask"
    fi

    # flask_cors
    if "$VENV_PYTHON" -c "from flask_cors import CORS" 2>/dev/null; then
        log "    ${GREEN}✓${NC} flask-cors"
    else
        log "    ${RED}✗${NC} flask-cors"
        MISSING_PACKAGES="$MISSING_PACKAGES flask-cors"
    fi

    # requests
    if "$VENV_PYTHON" -c "import requests" 2>/dev/null; then
        log "    ${GREEN}✓${NC} requests"
    else
        log "    ${RED}✗${NC} requests"
        MISSING_PACKAGES="$MISSING_PACKAGES requests"
    fi

    # fastmcp (MCP server)
    if "$VENV_PYTHON" -c "from fastmcp import FastMCP" 2>/dev/null; then
        log "    ${GREEN}✓${NC} fastmcp"
    else
        log "    ${RED}✗${NC} fastmcp"
        MISSING_PACKAGES="$MISSING_PACKAGES fastmcp"
    fi

    # watchdog (optional but helpful)
    if "$VENV_PYTHON" -c "import watchdog" 2>/dev/null; then
        log "    ${GREEN}✓${NC} watchdog"
    else
        log "    ${YELLOW}!${NC} watchdog (optional)"
    fi

    if [ -n "$MISSING_PACKAGES" ]; then
        log "${RED}✗${NC} Missing packages:$MISSING_PACKAGES"
        log "  Attempting manual install..."
        # Try to install missing packages
        "$VENV_PYTHON" -m pip install $MISSING_PACKAGES 2>&1 | tee -a "$LOG_FILE"

        # Re-verify EACH package
        log "  Re-verifying after manual install..."
        STILL_MISSING=""

        if ! "$VENV_PYTHON" -c "import flask" 2>/dev/null; then
            STILL_MISSING="$STILL_MISSING flask"
        fi
        if ! "$VENV_PYTHON" -c "from flask_cors import CORS" 2>/dev/null; then
            STILL_MISSING="$STILL_MISSING flask-cors"
        fi
        if ! "$VENV_PYTHON" -c "import requests" 2>/dev/null; then
            STILL_MISSING="$STILL_MISSING requests"
        fi
        if ! "$VENV_PYTHON" -c "from fastmcp import FastMCP" 2>/dev/null; then
            STILL_MISSING="$STILL_MISSING fastmcp"
        fi

        if [ -n "$STILL_MISSING" ]; then
            log "${RED}✗${NC} Still missing after retry:$STILL_MISSING"
            show_error "Installation incomplete: Some packages failed to install.\n\nMissing:$STILL_MISSING\n\nTry running:\n$VENV_PIP install flask flask-cors fastmcp requests"
            exit 1
        fi

        log "${GREEN}✓${NC} Manual install succeeded"
    fi

    log "${GREEN}✓${NC} Dependencies installed and verified"
}

# ============================================================
# Configure MCP
# ============================================================

configure_mcp() {
    log "${BLUE}Configuring MCP integration...${NC}"

    # Run the existing install.py MCP configuration
    cd "$INSTALL_DIR"
    source venv/bin/activate

    python3 scripts/install.py --mcp-only 2>/dev/null || {
        # Fallback: configure manually
        CLAUDE_CONFIG="$HOME/.claude.json"
        MCP_ENTRY='{
  "mcpServers": {
    "fixonce": {
      "command": "'"$INSTALL_DIR"'/venv/bin/fastmcp",
      "args": ["run", "'"$INSTALL_DIR"'/src/mcp_server/mcp_memory_server_v2.py", "--transport", "stdio"],
      "env": {
        "PYTHONPATH": "'"$INSTALL_DIR"'/src",
        "FASTMCP_CHECK_FOR_UPDATES": "off",
        "FASTMCP_SHOW_CLI_BANNER": "false"
      }
    }
  }
}'

        if [ -f "$CLAUDE_CONFIG" ]; then
            # Backup existing config
            cp "$CLAUDE_CONFIG" "$CLAUDE_CONFIG.backup.$(date +%s)"
            log "${YELLOW}!${NC} Backed up existing Claude config"
        fi

        # For now, just note that MCP needs manual setup
        log "${YELLOW}!${NC} MCP configuration may need manual setup"
    }

    log "${GREEN}✓${NC} MCP configuration complete"
}

# ============================================================
# Setup LaunchAgent (creates plist but does NOT load yet)
# ============================================================

setup_launchagent() {
    log "${BLUE}Setting up auto-start...${NC}"
    write_install_state "STARTING" "Preparing automatic startup"

    LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
    PLIST_FILE="$LAUNCH_AGENTS/com.fixonce.server.plist"
    USER_LOGS="$HOME/.fixonce/logs"

    mkdir -p "$LAUNCH_AGENTS"
    mkdir -p "$USER_LOGS"

    # Unload any existing agent first
    launchctl unload "$PLIST_FILE" 2>/dev/null || true

    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fixonce.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/venv/bin/python</string>
        <string>$INSTALL_DIR/src/server.py</string>
        <string>--flask-only</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$USER_LOGS/server.log</string>
    <key>StandardErrorPath</key>
    <string>$USER_LOGS/server.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

    touch "$USER_LOGS/server.log" "$USER_LOGS/server.error.log"
    log "${GREEN}✓${NC} Auto-start service prepared"
}

# ============================================================
# Startup Recovery: load service, wait for readiness, retry once
# ============================================================

clear_stale_runtime_state() {
    local runtime_file="$HOME/.fixonce/runtime.json"
    local lock_file="$HOME/.fixonce/server.lock"

    if [ -f "$runtime_file" ]; then
        local runtime_pid
        runtime_pid=$(python3 -c "import json; import pathlib; p=pathlib.Path('$runtime_file'); data=json.loads(p.read_text()) if p.exists() else {}; print(data.get('pid',''))" 2>/dev/null)
        if [ -n "$runtime_pid" ] && ! kill -0 "$runtime_pid" 2>/dev/null; then
            rm -f "$runtime_file"
        fi
    fi

    if [ -f "$lock_file" ]; then
        local lock_pid
        lock_pid=$(cat "$lock_file" 2>/dev/null || true)
        if [ -n "$lock_pid" ] && ! kill -0 "$lock_pid" 2>/dev/null; then
            rm -f "$lock_file"
        fi
    fi
}

load_launchagent_service() {
    PLIST_FILE="$HOME/Library/LaunchAgents/com.fixonce.server.plist"
    local domain="gui/$(id -u)"
    local label="com.fixonce.server"

    launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
    launchctl unload "$PLIST_FILE" >/dev/null 2>&1 || true

    if launchctl bootstrap "$domain" "$PLIST_FILE" >/tmp/fixonce_launchctl.log 2>&1; then
        launchctl kickstart -k "$domain/$label" >> /tmp/fixonce_launchctl.log 2>&1 || true
        return 0
    fi

    if launchctl load "$PLIST_FILE" >> /tmp/fixonce_launchctl.log 2>&1; then
        return 0
    fi

    return 1
}

discover_runtime_port() {
    local runtime_file="$HOME/.fixonce/runtime.json"
    if [ -f "$runtime_file" ]; then
        python3 -c "import json; print(json.load(open('$runtime_file')).get('port', ''))" 2>/dev/null
        return
    fi

    for p in 5000 5001 5002 5003 5004 5005 5006 5007 5008 5009; do
        if curl -fsS --connect-timeout 1 "http://localhost:$p/api/health" >/dev/null 2>&1; then
            echo "$p"
            return
        fi
    done
}

validate_runtime_ownership() {
    local port="$1"
    local expected_user="$2"
    local expected_install_dir="$3"
    local runtime_file="$HOME/.fixonce/runtime.json"

    python3 - "$runtime_file" "$port" "$expected_user" "$expected_install_dir" << 'PY'
import json
import os
import pathlib
import sys
import urllib.request

runtime_file = pathlib.Path(sys.argv[1])
port = int(sys.argv[2])
expected_user = sys.argv[3]
expected_install_dir = os.path.realpath(sys.argv[4])

if not runtime_file.exists():
    print("runtime.json is missing")
    sys.exit(1)

try:
    runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"runtime.json is invalid: {exc}")
    sys.exit(1)

runtime_port = runtime.get("port")
runtime_user = runtime.get("user")
runtime_install_path = runtime.get("install_path")

if runtime_port != port:
    print(f"runtime port mismatch: expected {port}, got {runtime_port}")
    sys.exit(1)

if runtime_user != expected_user:
    print(f"runtime user mismatch: expected {expected_user}, got {runtime_user}")
    sys.exit(1)

if os.path.realpath(runtime_install_path or "") != expected_install_dir:
    print(
        f"runtime install_path mismatch: expected {expected_install_dir}, "
        f"got {os.path.realpath(runtime_install_path or '')}"
    )
    sys.exit(1)

try:
    with urllib.request.urlopen(f"http://localhost:{port}/api/ping", timeout=2) as response:
        ping = json.loads(response.read().decode("utf-8"))
except Exception as exc:
    print(f"/api/ping failed: {exc}")
    sys.exit(1)

if ping.get("service") != "fixonce":
    print(f"unexpected service identity: {ping.get('service')}")
    sys.exit(1)

if ping.get("user") != expected_user:
    print(f"ping user mismatch: expected {expected_user}, got {ping.get('user')}")
    sys.exit(1)

if os.path.realpath(ping.get("install_path") or "") != expected_install_dir:
    print(
        f"ping install_path mismatch: expected {expected_install_dir}, "
        f"got {os.path.realpath(ping.get('install_path') or '')}"
    )
    sys.exit(1)

print("ok")
PY
}

wait_for_runtime_health() {
    local max_attempts="${1:-30}"
    local attempt=0
    local current_user="$(whoami)"

    while [ $attempt -lt $max_attempts ]; do
        attempt=$((attempt + 1))
        sleep 1

        local runtime_port
        runtime_port=$(discover_runtime_port)
        if [ -n "$runtime_port" ] && curl -fsS --connect-timeout 1 "http://localhost:$runtime_port/api/health" >/dev/null 2>&1; then
            local ownership_result
            if ownership_result=$(validate_runtime_ownership "$runtime_port" "$current_user" "$INSTALL_DIR" 2>&1); then
                echo "$runtime_port"
                return 0
            fi
            echo "$ownership_result" >> /tmp/fixonce_launchctl.log
        fi

        if [ $((attempt % 5)) -eq 0 ]; then
            log "  Waiting for FixOnce to finish starting... ($attempt/$max_attempts)"
        fi
    done

    return 1
}

inspect_startup_failure() {
    local user_logs="$HOME/.fixonce/logs"
    local launchctl_log="/tmp/fixonce_launchctl.log"
    local runtime_file="$HOME/.fixonce/runtime.json"

    log "  Last launchctl output:"
    tail -10 "$launchctl_log" 2>/dev/null | while read line; do
        log "    $line"
    done

    if [ -f "$runtime_file" ]; then
        log "  Current runtime.json:"
        tail -20 "$runtime_file" 2>/dev/null | while read line; do
            log "    $line"
        done
    fi

    log "  Last server log lines:"
    tail -10 "$user_logs/server.log" 2>/dev/null | while read line; do
        log "    $line"
    done

    log "  Last server error log lines:"
    tail -10 "$user_logs/server.error.log" 2>/dev/null | while read line; do
        log "    $line"
    done
}

verify_and_enable_service() {
    log "${BLUE}Starting FixOnce in the background...${NC}"
    write_install_state "WAITING_HEALTH" "Starting FixOnce services"

    local port=""
    local attempt=1
    local max_attempts=2

    while [ $attempt -le $max_attempts ]; do
        if [ $attempt -gt 1 ]; then
            log "${YELLOW}!${NC} First startup attempt did not become ready. Repairing and retrying..."
            write_install_state "RECOVERY" "Retrying background startup"
            setup_launchagent
        fi

        clear_stale_runtime_state

        if ! load_launchagent_service; then
            log "${RED}✗${NC} Could not load the auto-start service"
            inspect_startup_failure
            attempt=$((attempt + 1))
            continue
        fi

        if port=$(wait_for_runtime_health 35); then
            log "${GREEN}✓${NC} FixOnce is ready on port $port"
            write_install_state "READY" "FixOnce is ready"
            mkdir -p "$HOME/.fixonce"
            cat > "$HOME/.fixonce/config.json" << EOF
{
  "port": $port,
  "user": "$(whoami)",
  "install_dir": "$INSTALL_DIR",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
            return 0
        fi

        log "${YELLOW}!${NC} FixOnce did not become ready after startup attempt $attempt"
        inspect_startup_failure
        attempt=$((attempt + 1))
    done

    write_install_state "FAILED" "Automatic startup failed after retry"
    return 1
}

open_dashboard() {
    log "${BLUE}Opening FixOnce...${NC}"

    local port
    port=$(discover_runtime_port)

    if [ -z "$port" ]; then
        log "${YELLOW}!${NC} Could not determine the FixOnce address yet"
        return 1
    fi

    DASHBOARD_URL="http://localhost:$port"
    log "  Opening: $DASHBOARD_URL"
    open "$DASHBOARD_URL"
    log "${GREEN}✓${NC} FixOnce opened at $DASHBOARD_URL"
}

# ============================================================
# Create CLI symlink
# ============================================================

create_cli() {
    log "${BLUE}Creating CLI command...${NC}"

    CLI_SCRIPT="$INSTALL_DIR/fixonce"

    cat > "$CLI_SCRIPT" << 'CLISCRIPT'
#!/bin/bash
# FixOnce CLI - Multi-user aware with self-healing

FIXONCE_DIR="$HOME/FixOnce"
VENV_PYTHON="$FIXONCE_DIR/venv/bin/python"
VENV_PIP="$FIXONCE_DIR/venv/bin/pip"
PLIST="$HOME/Library/LaunchAgents/com.fixonce.server.plist"
CONFIG_FILE="$HOME/.fixonce/config.json"
CURRENT_USER=$(whoami)

# Check if dependencies are installed
check_deps() {
    if [ ! -f "$VENV_PYTHON" ]; then
        echo "ERROR: Virtual environment not found at $FIXONCE_DIR/venv"
        echo "Try reinstalling FixOnce."
        return 1
    fi

    MISSING=""
    # Check flask
    if ! "$VENV_PYTHON" -c "import flask" 2>/dev/null; then
        MISSING="$MISSING flask"
    fi
    # Check flask-cors
    if ! "$VENV_PYTHON" -c "from flask_cors import CORS" 2>/dev/null; then
        MISSING="$MISSING flask-cors"
    fi
    # Check requests
    if ! "$VENV_PYTHON" -c "import requests" 2>/dev/null; then
        MISSING="$MISSING requests"
    fi
    # Check fastmcp (MCP server)
    if ! "$VENV_PYTHON" -c "from fastmcp import FastMCP" 2>/dev/null; then
        MISSING="$MISSING fastmcp"
    fi

    if [ -n "$MISSING" ]; then
        echo "WARNING: Missing Python packages:$MISSING"
        return 1
    fi
    return 0
}

# Self-healing: install missing dependencies
repair_deps() {
    echo "Repairing dependencies..."
    if [ ! -f "$FIXONCE_DIR/requirements.txt" ]; then
        echo "ERROR: requirements.txt not found"
        return 1
    fi

    echo "Running: pip install -r requirements.txt"
    "$VENV_PYTHON" -m pip install -r "$FIXONCE_DIR/requirements.txt"

    if check_deps; then
        echo "Dependencies repaired successfully!"
        return 0
    else
        echo "Repair failed. Try manual fix:"
        echo "  $VENV_PIP install flask flask-cors fastmcp requests"
        return 1
    fi
}

# Find our port (checks user ownership via /api/ping)
find_my_port() {
    # First check saved config
    if [ -f "$CONFIG_FILE" ]; then
        SAVED_PORT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('port', ''))" 2>/dev/null)
        if [ -n "$SAVED_PORT" ]; then
            OWNER=$(curl -s "http://localhost:$SAVED_PORT/api/ping" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
            INSTALL_PATH=$(curl -s "http://localhost:$SAVED_PORT/api/ping" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('install_path',''))" 2>/dev/null)
            if [ "$OWNER" = "$CURRENT_USER" ] && [ "$(python3 -c "import os; print(os.path.realpath('$INSTALL_PATH'))" 2>/dev/null)" = "$(python3 -c "import os; print(os.path.realpath('$FIXONCE_DIR'))")" ]; then
                echo "$SAVED_PORT"
                return
            fi
        fi
    fi

    # Scan ports to find ours
    for p in 5000 5001 5002 5003 5004 5005 5006 5007 5008 5009; do
        RESPONSE=$(curl -s "http://localhost:$p/api/ping" 2>/dev/null)
        if echo "$RESPONSE" | grep -q '"service":"fixonce"'; then
            OWNER=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
            INSTALL_PATH=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('install_path',''))" 2>/dev/null)
            if [ "$OWNER" = "$CURRENT_USER" ] && [ "$(python3 -c "import os; print(os.path.realpath('$INSTALL_PATH'))" 2>/dev/null)" = "$(python3 -c "import os; print(os.path.realpath('$FIXONCE_DIR'))")" ]; then
                echo "$p"
                return
            fi
        fi
    done
}

case "$1" in
    start)
        # Check deps before starting
        if ! check_deps; then
            echo ""
            read -p "Would you like to repair dependencies? [y/N] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                repair_deps || exit 1
            else
                exit 1
            fi
        fi

        launchctl load "$PLIST" 2>/dev/null
        sleep 2
        PORT=$(find_my_port)
        if [ -n "$PORT" ]; then
            echo "FixOnce started on port $PORT"
        else
            echo "FixOnce may have failed to start. Check: fixonce doctor"
        fi
        ;;
    stop)
        launchctl unload "$PLIST" 2>/dev/null
        echo "FixOnce stopped"
        ;;
    restart)
        launchctl unload "$PLIST" 2>/dev/null
        sleep 1
        launchctl load "$PLIST"
        sleep 2
        PORT=$(find_my_port)
        echo "FixOnce restarted on port ${PORT:-?}"
        ;;
    status)
        PORT=$(find_my_port)
        if [ -n "$PORT" ]; then
            echo "FixOnce is running on port $PORT (user: $CURRENT_USER)"
        else
            echo "FixOnce is not running for user $CURRENT_USER"
            # Check if it's a dependency issue
            if ! check_deps; then
                echo "Run 'fixonce repair' to fix missing dependencies"
            fi
        fi
        ;;
    port)
        echo "Port status:"
        for p in 5000 5001 5002 5003 5004 5005; do
            RESPONSE=$(curl -s "http://localhost:$p/api/ping" 2>/dev/null)
            if echo "$RESPONSE" | grep -q '"service":"fixonce"'; then
                OWNER=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
                if [ "$OWNER" = "$CURRENT_USER" ]; then
                    echo "  Port $p: FixOnce (yours)"
                else
                    echo "  Port $p: FixOnce (user: $OWNER)"
                fi
            fi
        done
        ;;
    repair)
        repair_deps
        ;;
    doctor)
        # Check deps first
        if ! check_deps; then
            echo "Dependencies missing - attempting repair first..."
            repair_deps
        fi
        cd "$FIXONCE_DIR"
        "$VENV_PYTHON" scripts/install.py --doctor
        echo ""
        echo "Log files: ~/.fixonce/logs/"
        ls -la "$HOME/.fixonce/logs/" 2>/dev/null || echo "  (no logs yet)"
        ;;
    logs)
        LOG_DIR="$HOME/.fixonce/logs"
        if [ ! -d "$LOG_DIR" ]; then
            echo "No logs directory found at $LOG_DIR"
            exit 1
        fi
        echo "=== Server Log (last 20 lines) ==="
        tail -20 "$LOG_DIR/server.log" 2>/dev/null || echo "(empty)"
        echo ""
        echo "=== Error Log (last 20 lines) ==="
        tail -20 "$LOG_DIR/server.error.log" 2>/dev/null || echo "(empty)"
        echo ""
        echo "Log files: $LOG_DIR/"
        ;;
    dashboard)
        PORT=$(find_my_port)
        if [ -n "$PORT" ]; then
            open "http://localhost:$PORT"
        else
            echo "FixOnce server not found."
            if ! check_deps; then
                echo "Dependencies missing. Run: fixonce repair"
            else
                echo "Try: fixonce start"
            fi
            exit 1
        fi
        ;;
    *)
        echo "Usage: fixonce {start|stop|restart|status|port|repair|doctor|logs|dashboard}"
        echo ""
        echo "Commands:"
        echo "  start      Start FixOnce server"
        echo "  stop       Stop FixOnce server"
        echo "  restart    Restart FixOnce server"
        echo "  status     Show if FixOnce is running"
        echo "  port       Show port allocation for all users"
        echo "  repair     Reinstall Python dependencies"
        echo "  doctor     Run diagnostics"
        echo "  logs       Show server logs"
        echo "  dashboard  Open dashboard in browser"
        exit 1
        ;;
esac
CLISCRIPT

    chmod +x "$CLI_SCRIPT"

    # Create symlink in /usr/local/bin if possible
    if [ -w "/usr/local/bin" ]; then
        ln -sf "$CLI_SCRIPT" /usr/local/bin/fixonce
        log "${GREEN}✓${NC} CLI installed: fixonce"
    else
        log "${YELLOW}!${NC} Run 'sudo ln -s $CLI_SCRIPT /usr/local/bin/fixonce' for global CLI"
    fi
}

# ============================================================
# Main Installation Flow
# ============================================================

main() {
    echo "" > "$LOG_FILE"
    write_install_state "NOT_INSTALLED" "Installer opened"

    log ""
    log "${BLUE}========================================"
    log "  FixOnce Installer"
    log "========================================${NC}"
    log ""

    # Show welcome dialog
    osascript -e 'display dialog "Install FixOnce\n\nThis setup will:\n• Install FixOnce\n• Connect your AI tools\n• Start FixOnce automatically\n• Open FixOnce when ready\n\nClick Continue to begin." with title "FixOnce Installer" buttons {"Cancel", "Continue"} default button "Continue" with icon note' 2>/dev/null || exit 0

    # Run installation steps
    preflight
    install_files
    install_dependencies
    configure_mcp
    setup_launchagent      # Creates plist but doesn't load
    create_cli

    # Health gate: verify server works BEFORE enabling LaunchAgent
    if ! verify_and_enable_service; then
        log "${RED}Installation failed: Server health check failed${NC}"
        log "Automatic startup could not be completed."
        log ""
        log "Installer checked:"
        log "  1. Background service loading"
        log "  2. Startup retry and repair"
        log "  3. Server logs in $HOME/.fixonce/logs/"
        show_error "FixOnce could not finish starting automatically.\n\nThe installer retried startup and collected logs.\n\nSee:\n$HOME/.fixonce/logs/\n\nYou should not need Terminal for normal installs, so this needs follow-up."
        exit 1
    fi

    open_dashboard

    log ""
    log "${GREEN}========================================"
    log "  Installation Complete!"
    log "========================================${NC}"
    log ""
    log "FixOnce is now installed and ready."
    log ""
    log "Quick commands:"
    log "  fixonce status    - Check FixOnce"
    log "  fixonce dashboard - Open FixOnce"
    log "  fixonce doctor    - Run diagnostics"
    log ""

    # Show success dialog
    osascript -e 'display dialog "FixOnce ready\n\nFixOnce is installed and running.\n\nYou can now open Claude, Cursor, or Codex.\n\nAdvanced:\n• fixonce dashboard\n• fixonce doctor" with title "FixOnce Installer" buttons {"Done"} default button "Done" with icon note'
}

# Run main
main 2>&1 | tee -a "$LOG_FILE"
INSTALLER_SCRIPT

chmod +x "$MACOS/installer"

# ============================================================
# Step 5: Create DMG
# ============================================================
echo "[5/5] Creating DMG..."

DMG_PATH="$BUILD_DIR/$DMG_NAME.dmg"
DMG_TEMP="$BUILD_DIR/dmg_temp"

mkdir -p "$DMG_TEMP"
cp -R "$APP_BUNDLE" "$DMG_TEMP/"

# Create a symbolic link to Applications
ln -s /Applications "$DMG_TEMP/Applications"

# Create README
cat > "$DMG_TEMP/README.txt" << 'README'
FixOnce Installer
=================

To install FixOnce:
1. Double-click "FixOnce Installer.app"
2. Follow the on-screen instructions
3. The Dashboard will open automatically when done

Requirements:
- macOS 10.15 or later
- Python 3.8 or later (usually pre-installed)

After installation:
- FixOnce will start automatically on login
- Use 'fixonce' command in Terminal for control
- Dashboard at http://localhost:5000

For help: https://github.com/Nati41/FixOnce
README

# Create DMG
hdiutil create -volname "FixOnce Installer" \
    -srcfolder "$DMG_TEMP" \
    -ov -format UDZO \
    "$DMG_PATH"

# Clean up
rm -rf "$DMG_TEMP"

echo ""
echo "========================================"
echo "  Build Complete!"
echo "========================================"
echo ""
echo "Output: $DMG_PATH"
echo "Size: $(du -h "$DMG_PATH" | cut -f1)"
echo ""
echo "To test: open \"$DMG_PATH\""
echo ""
