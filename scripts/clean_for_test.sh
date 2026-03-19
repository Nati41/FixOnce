#!/bin/bash
# FixOnce - Clean User Test Script
# Resets the system to simulate a brand new user
#
# Usage: ./scripts/clean_for_test.sh
#
# WARNING: This will DELETE all user data!

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo ""
echo "=========================================="
echo "  FixOnce Clean User Test Reset"
echo "=========================================="
echo ""
echo -e "${YELLOW}WARNING: This will delete ALL FixOnce user data!${NC}"
echo ""
echo "This script will:"
echo "  1. Stop any running FixOnce server"
echo "  2. Remove ~/.fixonce/ (all user data)"
echo "  3. Unload LaunchAgent (macOS)"
echo "  4. Reset to fresh install state"
echo ""
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "[1/4] Stopping FixOnce server..."
pkill -f "python.*server.py" 2>/dev/null || true
pkill -f "FixOnce" 2>/dev/null || true

echo "[2/4] Removing user data (~/.fixonce/)..."
rm -rf ~/.fixonce/

echo "[3/4] Unloading LaunchAgent (macOS)..."
if [ -f ~/Library/LaunchAgents/com.fixonce.server.plist ]; then
    launchctl unload ~/Library/LaunchAgents/com.fixonce.server.plist 2>/dev/null || true
    rm -f ~/Library/LaunchAgents/com.fixonce.server.plist
fi

echo "[4/4] Creating minimal user data structure..."
# Create ~/.fixonce with minimal structure needed for dashboard to work
mkdir -p ~/.fixonce/projects_v2
mkdir -p ~/.fixonce/logs

# Mark as installed (since we're running from source, not fresh download)
echo '{"installed": true, "installed_at": "'$(date -Iseconds)'", "source": "clean_test"}' > ~/.fixonce/install_state.json

echo ""
echo -e "${GREEN}Done! System reset to clean state.${NC}"
echo ""
echo "Next steps:"
echo "  1. Start fresh: python src/server.py"
echo "  2. Open new AI session (Claude/Cursor/Codex)"
echo "  3. Verify dashboard shows: 'No active project yet'"
echo "  4. Start working on a project"
echo ""
