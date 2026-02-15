#!/bin/bash
# FixOnce Uninstaller for Mac/Linux

set -e

echo ""
echo "🧠 FixOnce Uninstaller"
echo "======================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}This will remove FixOnce from your system.${NC}"
echo ""
echo "What will be removed:"
echo "  - LaunchAgent (auto-start)"
echo "  - MCP configuration from Claude/Cursor"
echo "  - Desktop/Dock shortcuts"
echo ""
echo "What will NOT be removed:"
echo "  - FixOnce folder (your data is safe)"
echo "  - Chrome extension (remove manually)"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""

# Stop server
echo "[1/5] Stopping FixOnce server..."
pkill -f "server.py" 2>/dev/null || true
pkill -f "mcp_memory_server" 2>/dev/null || true
echo -e "  ${GREEN}✓${NC} Server stopped"

# Remove LaunchAgent
echo "[2/5] Removing auto-start..."
PLIST_PATH="$HOME/Library/LaunchAgents/com.fixonce.server.plist"
if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo -e "  ${GREEN}✓${NC} LaunchAgent removed"
else
    echo -e "  ${YELLOW}⚠${NC} LaunchAgent not found (already removed?)"
fi

# Remove MCP config from Claude
echo "[3/5] Removing MCP from Claude Code..."
CLAUDE_CONFIG="$HOME/.claude.json"
if [ -f "$CLAUDE_CONFIG" ]; then
    # Use Python to safely remove just the fixonce entry
    python3 -c "
import json
try:
    with open('$CLAUDE_CONFIG', 'r') as f:
        config = json.load(f)
    if 'mcpServers' in config and 'fixonce' in config['mcpServers']:
        del config['mcpServers']['fixonce']
        with open('$CLAUDE_CONFIG', 'w') as f:
            json.dump(config, f, indent=2)
        print('  ✓ Removed from Claude Code')
    else:
        print('  ⚠ Not configured in Claude Code')
except Exception as e:
    print(f'  ⚠ Could not update Claude config: {e}')
"
else
    echo -e "  ${YELLOW}⚠${NC} Claude config not found"
fi

# Remove MCP config from Cursor
echo "[4/5] Removing MCP from Cursor..."
CURSOR_CONFIG="$HOME/.cursor/mcp.json"
if [ -f "$CURSOR_CONFIG" ]; then
    python3 -c "
import json
try:
    with open('$CURSOR_CONFIG', 'r') as f:
        config = json.load(f)
    if 'mcpServers' in config and 'fixonce' in config['mcpServers']:
        del config['mcpServers']['fixonce']
        with open('$CURSOR_CONFIG', 'w') as f:
            json.dump(config, f, indent=2)
        print('  ✓ Removed from Cursor')
    else:
        print('  ⚠ Not configured in Cursor')
except Exception as e:
    print(f'  ⚠ Could not update Cursor config: {e}')
"
else
    echo -e "  ${YELLOW}⚠${NC} Cursor config not found"
fi

# Remove from Dock (best effort)
echo "[5/5] Cleaning up..."
# Note: Removing from Dock programmatically is complex, just inform user
echo -e "  ${YELLOW}⚠${NC} If FixOnce is in your Dock, right-click → Remove from Dock"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✓ Uninstall Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Your data in $SCRIPT_DIR/data is preserved."
echo "To completely remove FixOnce, delete the folder:"
echo "  rm -rf \"$SCRIPT_DIR\""
echo ""
echo "To remove Chrome extension:"
echo "  chrome://extensions/ → Find FixOnce → Remove"
echo ""
