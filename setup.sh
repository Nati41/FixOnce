#!/bin/bash
# FixOnce Setup — 60-second install
# Usage: curl -sL <url> | bash  OR  bash setup.sh

set -e

FIXONCE_DIR="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'
BLUE='\033[0;34m'
DIM='\033[2m'
NC='\033[0m'

echo ""
echo -e "${BLUE}  FixOnce — AI Memory Layer${NC}"
echo -e "${DIM}  Your AI never forgets.${NC}"
echo ""

# Step 1: Install dependencies
echo -e "${DIM}[1/3]${NC} Installing dependencies..."
pip3 install -q flask flask-cors requests fastmcp scikit-learn watchdog 2>/dev/null || {
    echo "  pip3 failed. Trying pip..."
    pip install -q flask flask-cors requests fastmcp scikit-learn watchdog
}
echo -e "  ${GREEN}✓${NC} Dependencies installed"

# Step 2: Configure MCP for Cursor
echo -e "${DIM}[2/3]${NC} Configuring AI editors..."

CURSOR_MCP="$HOME/.cursor/mcp.json"
CLAUDE_MCP="$HOME/.claude/settings.json"
MCP_SERVER_PATH="$FIXONCE_DIR/src/mcp_server/mcp_memory_server_v2.py"
PYTHON_PATH="$(which python3 2>/dev/null || which python)"

# Cursor
if [ -d "$HOME/.cursor" ]; then
    mkdir -p "$(dirname "$CURSOR_MCP")"

    if [ -f "$CURSOR_MCP" ]; then
        # Check if fixonce already configured
        if grep -q "fixonce" "$CURSOR_MCP" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} Cursor MCP already configured"
        else
            # Add fixonce to existing config
            python3 -c "
import json
with open('$CURSOR_MCP', 'r') as f:
    config = json.load(f)
config.setdefault('mcpServers', {})['fixonce'] = {
    'command': '$PYTHON_PATH',
    'args': ['$MCP_SERVER_PATH']
}
with open('$CURSOR_MCP', 'w') as f:
    json.dump(config, f, indent=2)
"
            echo -e "  ${GREEN}✓${NC} Cursor MCP configured"
        fi
    else
        cat > "$CURSOR_MCP" << MCPEOF
{
  "mcpServers": {
    "fixonce": {
      "command": "$PYTHON_PATH",
      "args": ["$MCP_SERVER_PATH"]
    }
  }
}
MCPEOF
        echo -e "  ${GREEN}✓${NC} Cursor MCP configured"
    fi
else
    echo -e "  ${DIM}–${NC} Cursor not found, skipping"
fi

# Claude Code
if [ -d "$HOME/.claude" ]; then
    mkdir -p "$(dirname "$CLAUDE_MCP")"

    if [ -f "$CLAUDE_MCP" ]; then
        if grep -q "fixonce" "$CLAUDE_MCP" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} Claude Code already configured"
        else
            python3 -c "
import json
with open('$CLAUDE_MCP', 'r') as f:
    config = json.load(f)
config.setdefault('mcpServers', {})['fixonce'] = {
    'command': '$PYTHON_PATH',
    'args': ['$MCP_SERVER_PATH']
}
with open('$CLAUDE_MCP', 'w') as f:
    json.dump(config, f, indent=2)
"
            echo -e "  ${GREEN}✓${NC} Claude Code configured"
        fi
    else
        mkdir -p "$HOME/.claude"
        cat > "$CLAUDE_MCP" << MCPEOF
{
  "mcpServers": {
    "fixonce": {
      "command": "$PYTHON_PATH",
      "args": ["$MCP_SERVER_PATH"]
    }
  }
}
MCPEOF
        echo -e "  ${GREEN}✓${NC} Claude Code configured"
    fi
else
    echo -e "  ${DIM}–${NC} Claude Code not found, skipping"
fi

# Step 3: Start server
echo -e "${DIM}[3/3]${NC} Starting FixOnce server..."
python3 "$FIXONCE_DIR/src/server.py" &
SERVER_PID=$!
sleep 2

if kill -0 $SERVER_PID 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Server running on http://localhost:5000"
else
    echo -e "  Server failed to start. Run manually: python3 src/server.py"
fi

echo ""
echo -e "${GREEN}  ✓ FixOnce is ready!${NC}"
echo ""
echo "  Next steps:"
echo "  1. Reload Cursor (Cmd+Shift+P → Reload Window)"
echo "  2. Open any project and start chatting"
echo "  3. FixOnce will automatically remember everything"
echo ""
echo -e "  Dashboard: ${BLUE}http://localhost:5000/v3${NC}"
echo ""
