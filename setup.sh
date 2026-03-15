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
pip3 install -q -r "$FIXONCE_DIR/requirements.txt" 2>/dev/null || {
    echo "  pip3 failed. Trying pip..."
    pip install -q -r "$FIXONCE_DIR/requirements.txt"
}
echo -e "  ${GREEN}✓${NC} Dependencies installed"

# Step 2: Configure MCP for Cursor
echo -e "${DIM}[2/3]${NC} Configuring AI editors..."

CURSOR_MCP="$HOME/.cursor/mcp.json"
CLAUDE_MCP="$HOME/.claude/settings.json"
CODEX_MCP="$HOME/.codex/config.toml"
MCP_SERVER_PATH="$FIXONCE_DIR/src/mcp_server/mcp_memory_server_v2.py"
PYTHON_PATH="$(which python3 2>/dev/null || which python)"
PROJECT_CODEX_MCP="$FIXONCE_DIR/.codex/config.toml"

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

# Codex
if command -v codex >/dev/null 2>&1 || [ -d "$HOME/.codex" ]; then
    mkdir -p "$(dirname "$CODEX_MCP")"
    python3 - << PY
from pathlib import Path
import re

path = Path("$CODEX_MCP")
server_name = "fixonce"
command = "$PYTHON_PATH"
server_path = "$MCP_SERVER_PATH"
pythonpath = "$FIXONCE_DIR/src"

content = path.read_text(encoding="utf-8") if path.exists() else ""
for pattern in (
    rf'(?ms)^\\[mcp_servers\\.{re.escape(server_name)}\\]\\n(?:.*\\n)*?(?=^\\[|\\Z)',
    rf'(?ms)^\\[mcp_servers\\.{re.escape(server_name)}\\.env\\]\\n(?:.*\\n)*?(?=^\\[|\\Z)',
):
    content = re.sub(pattern, '', content)
content = content.strip()

block = (
    f'[mcp_servers.{server_name}]\\n'
    f'command = "{command}"\\n'
    f'args = ["{server_path}"]\\n\\n'
    f'[mcp_servers.{server_name}.env]\\n'
    f'PYTHONPATH = "{pythonpath}"\\n'
)

path.write_text((content + "\\n\\n" + block if content else block), encoding="utf-8")
PY
    echo -e "  ${GREEN}✓${NC} Codex MCP configured"
else
    echo -e "  ${DIM}–${NC} Codex not found, skipping"
fi

# Project-level Codex config
mkdir -p "$(dirname "$PROJECT_CODEX_MCP")"
python3 - << PY
from pathlib import Path

path = Path("$PROJECT_CODEX_MCP")
command = "$PYTHON_PATH"
server_path = "$MCP_SERVER_PATH"
pythonpath = "$FIXONCE_DIR/src"

path.write_text(
    '[mcp_servers.fixonce]\\n'
    f'command = "{command}"\\n'
    f'args = ["{server_path}"]\\n\\n'
    '[mcp_servers.fixonce.env]\\n'
    f'PYTHONPATH = "{pythonpath}"\\n',
    encoding="utf-8"
)
PY
echo -e "  ${GREEN}✓${NC} Project Codex MCP configured"

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
echo -e "  Dashboard: ${BLUE}http://localhost:5000/lite${NC}"
echo ""
