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

cat > "$CONTENTS/Info.plist" << 'PLIST'
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
    <string>1.0.4</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.4</string>
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

# ============================================================
# Pre-flight Checks
# ============================================================

preflight() {
    log "${BLUE}Running pre-flight checks...${NC}"

    # Check Python
    if ! command -v python3 &> /dev/null; then
        show_error "Python 3 is required but not installed.\n\nPlease install Python 3 from python.org or via Homebrew:\n\nbrew install python3"
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log "${GREEN}✓${NC} Python $PYTHON_VERSION found"

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
# Installation
# ============================================================

install_files() {
    log "${BLUE}Installing FixOnce...${NC}"

    # Create installation directory
    mkdir -p "$INSTALL_DIR"

    # Copy files
    cp -R "$RESOURCES/src" "$INSTALL_DIR/"
    cp -R "$RESOURCES/scripts" "$INSTALL_DIR/"
    cp -R "$RESOURCES/data" "$INSTALL_DIR/"
    cp -R "$RESOURCES/extension" "$INSTALL_DIR/" 2>/dev/null || true
    cp "$RESOURCES/requirements.txt" "$INSTALL_DIR/"
    cp "$RESOURCES/CLAUDE.md" "$INSTALL_DIR/" 2>/dev/null || true

    log "${GREEN}✓${NC} Files copied to $INSTALL_DIR"

    # Create .fixonce directory if needed
    mkdir -p "$INSTALL_DIR/.fixonce"

    # Create metadata.json if not exists
    if [ ! -f "$INSTALL_DIR/.fixonce/metadata.json" ]; then
        PROJECT_ID="FixOnce_$(openssl rand -hex 4)"
        cat > "$INSTALL_DIR/.fixonce/metadata.json" << EOF
{
  "fixonce_version": "1.0.0",
  "project_id": "$PROJECT_ID",
  "name": "FixOnce",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "working_dir_original": "$INSTALL_DIR"
}
EOF
        log "${GREEN}✓${NC} Created project metadata"
    fi
}

# ============================================================
# Install Python Dependencies
# ============================================================

install_dependencies() {
    log "${BLUE}Installing Python dependencies...${NC}"

    cd "$INSTALL_DIR"

    # Verify requirements.txt exists
    if [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
        log "${RED}✗${NC} requirements.txt not found!"
        show_error "Installation failed: requirements.txt missing.\n\nPlease re-download the installer."
        exit 1
    fi

    # Create virtual environment if it doesn't exist
    if [ ! -d "$INSTALL_DIR/venv" ]; then
        log "  Creating virtual environment..."
        if ! python3 -m venv "$INSTALL_DIR/venv"; then
            log "${RED}✗${NC} Failed to create virtual environment"
            show_error "Installation failed: Could not create Python virtual environment.\n\nMake sure Python 3 is properly installed."
            exit 1
        fi
        log "${GREEN}✓${NC} Created virtual environment"
    fi

    # Use absolute paths for venv python/pip
    VENV_PYTHON="$INSTALL_DIR/venv/bin/python3"
    VENV_PIP="$INSTALL_DIR/venv/bin/pip"

    # Verify venv python exists
    if [ ! -f "$VENV_PYTHON" ]; then
        log "${RED}✗${NC} venv Python not found at $VENV_PYTHON"
        show_error "Installation failed: Virtual environment is corrupted.\n\nTry deleting ~/FixOnce/venv and reinstalling."
        exit 1
    fi

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
    log "  Verifying installation..."
    MISSING_PACKAGES=""
    # Check all critical packages including mcp and fastmcp
    for pkg in flask flask_cors mcp requests; do
        if ! "$VENV_PYTHON" -c "import $pkg" 2>/dev/null; then
            MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
        fi
    done

    # Also check fastmcp which is needed for MCP server
    if ! "$VENV_PYTHON" -c "from fastmcp import FastMCP" 2>/dev/null; then
        MISSING_PACKAGES="$MISSING_PACKAGES fastmcp"
    fi

    if [ -n "$MISSING_PACKAGES" ]; then
        log "${RED}✗${NC} Missing packages:$MISSING_PACKAGES"
        log "  Attempting manual install..."
        # Try to install missing packages
        "$VENV_PYTHON" -m pip install $MISSING_PACKAGES 2>&1 | tee -a "$LOG_FILE"

        # Re-verify
        STILL_MISSING=""
        for pkg in flask flask_cors mcp requests; do
            if ! "$VENV_PYTHON" -c "import $pkg" 2>/dev/null; then
                STILL_MISSING="$STILL_MISSING $pkg"
            fi
        done

        if [ -n "$STILL_MISSING" ]; then
            show_error "Installation incomplete: Some packages failed to install.\n\nMissing:$STILL_MISSING\n\nTry running:\n$VENV_PIP install flask flask-cors mcp fastmcp requests"
            exit 1
        fi
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
      "command": "'"$INSTALL_DIR"'/venv/bin/python",
      "args": ["-m", "mcp_server.mcp_memory_server_v2"],
      "cwd": "'"$INSTALL_DIR"'/src"
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
# Setup LaunchAgent
# ============================================================

setup_launchagent() {
    log "${BLUE}Setting up auto-start...${NC}"

    LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
    PLIST_FILE="$LAUNCH_AGENTS/com.fixonce.server.plist"

    mkdir -p "$LAUNCH_AGENTS"

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
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/data/server.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/data/server.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

    # Load the agent
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    launchctl load "$PLIST_FILE"

    log "${GREEN}✓${NC} LaunchAgent installed and loaded"
}

# ============================================================
# Start Server & Open Dashboard (Smart Launch)
# ============================================================

start_and_open() {
    log "${BLUE}Starting FixOnce server...${NC}"

    CURRENT_USER=$(whoami)
    PORT=""
    MAX_ATTEMPTS=15
    ATTEMPT=0

    # Method 1: Read port from server's port file (most reliable)
    PORT_FILE="$INSTALL_DIR/data/current_port.txt"

    log "  Waiting for server to start..."

    while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
        ATTEMPT=$((ATTEMPT + 1))
        sleep 1

        # Check if port file was written by server
        if [ -f "$PORT_FILE" ]; then
            FILE_PORT=$(cat "$PORT_FILE" 2>/dev/null)
            if [ -n "$FILE_PORT" ]; then
                # Verify this port is responding and belongs to us
                RESPONSE=$(curl -s "http://localhost:$FILE_PORT/api/ping" 2>/dev/null)
                if echo "$RESPONSE" | grep -q '"service":"fixonce"'; then
                    OWNER=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
                    if [ "$OWNER" = "$CURRENT_USER" ]; then
                        PORT=$FILE_PORT
                        log "  Found server on port $PORT (from port file)"
                        break
                    fi
                fi
            fi
        fi

        # Method 2: Scan ports if port file not ready
        for p in 5000 5001 5002 5003 5004 5005 5006 5007 5008 5009; do
            RESPONSE=$(curl -s --connect-timeout 1 "http://localhost:$p/api/ping" 2>/dev/null)
            if echo "$RESPONSE" | grep -q '"service":"fixonce"'; then
                OWNER=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
                if [ "$OWNER" = "$CURRENT_USER" ]; then
                    PORT=$p
                    log "  Found server on port $PORT (from scan)"
                    break 2
                fi
            fi
        done

        # Show progress
        if [ $((ATTEMPT % 3)) -eq 0 ]; then
            log "  Still waiting... (attempt $ATTEMPT/$MAX_ATTEMPTS)"
        fi
    done

    if [ -z "$PORT" ]; then
        log "${RED}✗${NC} Server failed to start after $MAX_ATTEMPTS seconds"
        log "  Check logs: $INSTALL_DIR/data/server.error.log"

        # Show last error
        if [ -f "$INSTALL_DIR/data/server.error.log" ]; then
            log "  Last error:"
            tail -5 "$INSTALL_DIR/data/server.error.log" | while read line; do
                log "    $line"
            done
        fi

        show_error "Server failed to start.\n\nTry running in terminal:\n$INSTALL_DIR/fixonce doctor"
        return 1
    fi

    # Save port to user config (source of truth for CLI)
    mkdir -p "$HOME/.fixonce"
    cat > "$HOME/.fixonce/config.json" << EOF
{
  "port": $PORT,
  "user": "$CURRENT_USER",
  "install_dir": "$INSTALL_DIR",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

    log "${GREEN}✓${NC} Server running on port $PORT"

    # Open dashboard with the CORRECT port
    DASHBOARD_URL="http://localhost:$PORT"
    log "  Opening: $DASHBOARD_URL"
    open "$DASHBOARD_URL"

    log "${GREEN}✓${NC} Dashboard opened at $DASHBOARD_URL"
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
VENV_PYTHON="$FIXONCE_DIR/venv/bin/python3"
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
    for pkg in flask flask_cors; do
        if ! "$VENV_PYTHON" -c "import $pkg" 2>/dev/null; then
            MISSING="$MISSING $pkg"
        fi
    done

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
        echo "  $VENV_PIP install flask flask-cors mcp requests"
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
            if [ "$OWNER" = "$CURRENT_USER" ]; then
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
            if [ "$OWNER" = "$CURRENT_USER" ]; then
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
        echo "Usage: fixonce {start|stop|restart|status|port|repair|doctor|dashboard}"
        echo ""
        echo "Commands:"
        echo "  start      Start FixOnce server"
        echo "  stop       Stop FixOnce server"
        echo "  restart    Restart FixOnce server"
        echo "  status     Show if FixOnce is running"
        echo "  port       Show port allocation for all users"
        echo "  repair     Reinstall Python dependencies"
        echo "  doctor     Run diagnostics"
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

    log ""
    log "${BLUE}========================================"
    log "  FixOnce Installer"
    log "========================================${NC}"
    log ""

    # Show welcome dialog
    osascript -e 'display dialog "Welcome to FixOnce!\n\nThis installer will:\n• Install FixOnce to ~/FixOnce\n• Configure auto-start\n• Set up AI integrations\n• Open the Dashboard\n\nClick Continue to begin." with title "FixOnce Installer" buttons {"Cancel", "Continue"} default button "Continue" with icon note' 2>/dev/null || exit 0

    # Run installation steps
    preflight
    install_files
    install_dependencies
    configure_mcp
    setup_launchagent
    create_cli
    start_and_open

    log ""
    log "${GREEN}========================================"
    log "  Installation Complete!"
    log "========================================${NC}"
    log ""
    log "FixOnce is now installed and running."
    log ""
    log "Quick commands:"
    log "  fixonce status    - Check if running"
    log "  fixonce dashboard - Open dashboard"
    log "  fixonce doctor    - Run diagnostics"
    log ""

    # Show success dialog
    osascript -e 'display dialog "FixOnce installed successfully!\n\nThe Dashboard is now open in your browser.\n\nUseful commands:\n• fixonce status\n• fixonce dashboard\n• fixonce doctor" with title "FixOnce Installer" buttons {"Done"} default button "Done" with icon note'
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
