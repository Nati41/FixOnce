#!/bin/bash
#
# NatiDebugger - AI Editors Setup Script
# Configures MCP connection for all supported AI tools
#

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get the absolute path to the MCP server
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MCP_SERVER="$SCRIPT_DIR/server/mcp_memory_server.py"

echo ""
echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         FixOnce - AI Editors Setup                        ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check MCP server exists
if [ ! -f "$MCP_SERVER" ]; then
    echo -e "${RED}[ERROR] MCP server not found at: $MCP_SERVER${NC}"
    exit 1
fi

echo -e "${GREEN}[OK]${NC} MCP Server: $MCP_SERVER"
echo ""

configured=0
skipped=0

add_configured() { configured=$((configured + 1)); }
add_skipped() { skipped=$((skipped + 1)); }

# ============================================================================
# Claude Code (~/.claude.json)
# ============================================================================
setup_claude() {
    echo -e "${YELLOW}[1/4]${NC} Claude Code..."

    CONFIG_FILE="$HOME/.claude.json"

    if [ -f "$CONFIG_FILE" ]; then
        # Check if already configured
        if grep -q "fixonce\|nati-memory" "$CONFIG_FILE" 2>/dev/null; then
            echo -e "      ${GREEN}Already configured${NC}"
            return 0
        fi

        # Backup existing
        cp "$CONFIG_FILE" "$CONFIG_FILE.backup"

        # Add to existing config using Python
        python3 << EOF
import json
with open("$CONFIG_FILE", "r") as f:
    config = json.load(f)
if "mcpServers" not in config:
    config["mcpServers"] = {}
config["mcpServers"]["fixonce"] = {
    "command": "python3",
    "args": ["$MCP_SERVER"]
}
with open("$CONFIG_FILE", "w") as f:
    json.dump(config, f, indent=2)
EOF
        echo -e "      ${GREEN}Updated${NC} (backup: .claude.json.backup)"
        add_configured
    else
        # Create new config
        cat > "$CONFIG_FILE" << EOF
{
  "mcpServers": {
    "fixonce": {
      "command": "python3",
      "args": ["$MCP_SERVER"]
    }
  }
}
EOF
        echo -e "      ${GREEN}Created${NC}"
        add_configured
    fi
}

# ============================================================================
# Cursor (~/.cursor/mcp.json)
# ============================================================================
setup_cursor() {
    echo -e "${YELLOW}[2/4]${NC} Cursor..."

    CONFIG_DIR="$HOME/.cursor"
    CONFIG_FILE="$CONFIG_DIR/mcp.json"

    # Check if Cursor is installed
    if [ ! -d "$CONFIG_DIR" ] && [ ! -d "/Applications/Cursor.app" ]; then
        echo -e "      ${BLUE}Not installed, skipping${NC}"
        add_skipped
        return 0
    fi

    mkdir -p "$CONFIG_DIR"

    if [ -f "$CONFIG_FILE" ]; then
        if grep -q "fixonce" "$CONFIG_FILE" 2>/dev/null; then
            echo -e "      ${GREEN}Already configured${NC}"
            return 0
        fi

        cp "$CONFIG_FILE" "$CONFIG_FILE.backup"

        python3 << EOF
import json
with open("$CONFIG_FILE", "r") as f:
    config = json.load(f)
if "mcpServers" not in config:
    config["mcpServers"] = {}
config["mcpServers"]["fixonce"] = {
    "command": "python3",
    "args": ["$MCP_SERVER"]
}
with open("$CONFIG_FILE", "w") as f:
    json.dump(config, f, indent=2)
EOF
        echo -e "      ${GREEN}Updated${NC}"
        add_configured
    else
        cat > "$CONFIG_FILE" << EOF
{
  "mcpServers": {
    "fixonce": {
      "command": "python3",
      "args": ["$MCP_SERVER"]
    }
  }
}
EOF
        echo -e "      ${GREEN}Created${NC}"
        add_configured
    fi
}

# ============================================================================
# VS Code + Continue (~/.continue/config.json)
# ============================================================================
setup_continue() {
    echo -e "${YELLOW}[3/4]${NC} VS Code + Continue..."

    CONFIG_DIR="$HOME/.continue"
    CONFIG_FILE="$CONFIG_DIR/config.json"

    if [ ! -d "$CONFIG_DIR" ]; then
        echo -e "      ${BLUE}Continue not installed, skipping${NC}"
        add_skipped
        return 0
    fi

    if [ -f "$CONFIG_FILE" ]; then
        if grep -q "fixonce" "$CONFIG_FILE" 2>/dev/null; then
            echo -e "      ${GREEN}Already configured${NC}"
            return 0
        fi

        cp "$CONFIG_FILE" "$CONFIG_FILE.backup"

        python3 << EOF
import json
with open("$CONFIG_FILE", "r") as f:
    config = json.load(f)
if "experimental" not in config:
    config["experimental"] = {}
if "modelContextProtocolServers" not in config["experimental"]:
    config["experimental"]["modelContextProtocolServers"] = []
config["experimental"]["modelContextProtocolServers"].append({
    "name": "fixonce",
    "transport": {
        "type": "stdio",
        "command": "python3",
        "args": ["$MCP_SERVER"]
    }
})
with open("$CONFIG_FILE", "w") as f:
    json.dump(config, f, indent=2)
EOF
        echo -e "      ${GREEN}Updated${NC}"
        add_configured
    else
        echo -e "      ${BLUE}No config.json found, skipping${NC}"
        add_skipped
    fi
}

# ============================================================================
# Windsurf (~/.windsurf/mcp.json or ~/.codeium/windsurf/mcp.json)
# ============================================================================
setup_windsurf() {
    echo -e "${YELLOW}[4/4]${NC} Windsurf..."

    # Try both possible locations
    CONFIG_DIR="$HOME/.windsurf"
    if [ ! -d "$CONFIG_DIR" ]; then
        CONFIG_DIR="$HOME/.codeium/windsurf"
    fi

    if [ ! -d "$CONFIG_DIR" ] && [ ! -d "/Applications/Windsurf.app" ]; then
        echo -e "      ${BLUE}Not installed, skipping${NC}"
        add_skipped
        return 0
    fi

    mkdir -p "$CONFIG_DIR"
    CONFIG_FILE="$CONFIG_DIR/mcp.json"

    if [ -f "$CONFIG_FILE" ]; then
        if grep -q "fixonce" "$CONFIG_FILE" 2>/dev/null; then
            echo -e "      ${GREEN}Already configured${NC}"
            return 0
        fi

        cp "$CONFIG_FILE" "$CONFIG_FILE.backup"

        python3 << EOF
import json
with open("$CONFIG_FILE", "r") as f:
    config = json.load(f)
if "mcpServers" not in config:
    config["mcpServers"] = {}
config["mcpServers"]["fixonce"] = {
    "command": "python3",
    "args": ["$MCP_SERVER"]
}
with open("$CONFIG_FILE", "w") as f:
    json.dump(config, f, indent=2)
EOF
        echo -e "      ${GREEN}Updated${NC}"
        add_configured
    else
        cat > "$CONFIG_FILE" << EOF
{
  "mcpServers": {
    "fixonce": {
      "command": "python3",
      "args": ["$MCP_SERVER"]
    }
  }
}
EOF
        echo -e "      ${GREEN}Created${NC}"
        add_configured
    fi
}

# Run all setups
setup_claude
setup_cursor
setup_continue
setup_windsurf

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${GREEN}Configured:${NC} $configured editors"
echo -e "  ${BLUE}Skipped:${NC}    $skipped (not installed)"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo "  1. Restart your AI editor(s)"
echo "  2. Make sure NatiDebugger server is running:"
echo -e "     ${GREEN}python3 $SCRIPT_DIR/server/server.py${NC}"
echo ""
echo -e "  ${YELLOW}Available MCP tools:${NC}"
echo "  - get_project_context()     - View all memory"
echo "  - get_active_issues()       - See active errors"
echo "  - search_solutions(query)   - Find past solutions"
echo "  - update_solution_status()  - Mark as resolved"
echo ""
