#!/bin/bash
# ============================================================
# FixOnce macOS Uninstaller
# Removes FixOnce from /Applications and cleans up LaunchAgents
# ============================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

APPLICATIONS_DIR="/Applications"
APP_NAME="FixOnce.app"
TARGET_APP="$APPLICATIONS_DIR/$APP_NAME"
USER_DATA_DIR="$HOME/.fixonce"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

# All possible LaunchAgent labels (old and new)
LAUNCH_AGENT_LABELS=(
    "com.fixonce.app"
    "com.fixonce.server"
    "com.fixonce.tray"
    "com.fixonce.menubar"
)

echo ""
echo "=============================================="
echo "  FixOnce macOS Uninstaller"
echo "=============================================="
echo ""

# Check for --purge flag
PURGE=false
if [ "$1" = "--purge" ]; then
    PURGE=true
    echo -e "${YELLOW}Warning: --purge flag detected${NC}"
    echo "This will also remove all user data from $USER_DATA_DIR"
    echo ""
    read -p "Are you sure? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

echo -e "${BLUE}[1/4]${NC} Stopping FixOnce processes..."
pkill -f "FixOnce" 2>/dev/null || true
pkill -f "app_launcher.py" 2>/dev/null || true
pkill -f "menubar_app.py" 2>/dev/null || true
pkill -f "server.py" 2>/dev/null || true
pkill -f "mcp_memory_server" 2>/dev/null || true
echo -e "  ${GREEN}Done${NC}"

echo -e "${BLUE}[2/4]${NC} Unloading LaunchAgents..."
for label in "${LAUNCH_AGENT_LABELS[@]}"; do
    plist_path="$LAUNCH_AGENTS_DIR/${label}.plist"
    launchctl unload "$plist_path" 2>/dev/null || true
    launchctl remove "$label" 2>/dev/null || true
    if [ -f "$plist_path" ]; then
        rm -f "$plist_path"
        echo "  Removed: $plist_path"
    fi
done
echo -e "  ${GREEN}Done${NC}"

echo -e "${BLUE}[3/4]${NC} Removing /Applications/FixOnce.app..."
if [ -d "$TARGET_APP" ]; then
    rm -rf "$TARGET_APP"
    echo "  Removed: $TARGET_APP"
else
    echo "  Not found (already removed)"
fi
echo -e "  ${GREEN}Done${NC}"

if [ "$PURGE" = true ]; then
    echo -e "${BLUE}[4/4]${NC} Removing user data (--purge)..."
    if [ -d "$USER_DATA_DIR" ]; then
        rm -rf "$USER_DATA_DIR"
        echo "  Removed: $USER_DATA_DIR"
    else
        echo "  Not found (already removed)"
    fi
    echo -e "  ${GREEN}Done${NC}"
else
    echo -e "${BLUE}[4/4]${NC} Preserving user data..."
    echo "  User data preserved at: $USER_DATA_DIR"
    echo "  To remove, run with --purge flag"
    echo -e "  ${GREEN}Done${NC}"
fi

echo ""
echo "=============================================="
echo -e "  ${GREEN}Uninstallation complete!${NC}"
echo "=============================================="
echo ""

if [ "$PURGE" = false ]; then
    echo "Your project memories and settings are preserved in:"
    echo "  $USER_DATA_DIR"
    echo ""
    echo "To completely remove all data:"
    echo "  $0 --purge"
fi
