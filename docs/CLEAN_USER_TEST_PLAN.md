# Clean User Test Plan

This document describes how to test the new FixOnce installation flow from scratch.

## Prerequisites

1. macOS, Linux, or Windows machine
2. Python 3.10+ installed
3. One of: Claude Code, Cursor, or Codex installed

## Step 1: Clean Previous Installation

Remove all traces of previous FixOnce installation:

```bash
# Remove old FixOnce directories
rm -rf ~/FixOnce
rm -rf ~/Desktop/FixOnce
rm -rf ~/Downloads/FixOnce

# Remove user data
rm -rf ~/.fixonce

# Remove LaunchAgent (macOS)
launchctl unload ~/Library/LaunchAgents/com.fixonce.server.plist 2>/dev/null
rm -f ~/Library/LaunchAgents/com.fixonce.server.plist

# Remove MCP configurations
# Claude Code
claude mcp remove fixonce -s user 2>/dev/null
# Or manually edit ~/.claude.json and remove "fixonce" from mcpServers

# Cursor - remove fixonce from ~/.cursor/mcp.json

# Codex - remove fixonce sections from ~/.codex/config.toml
```

## Step 2: Test AI Install Flow

### 2.1 Download
1. Open the install page (website/public/install.html or http://localhost:5000/install)
2. Click "Download FixOnce"
3. Extract to Desktop or Downloads

### 2.2 Copy AI Prompt
1. Click "Copy AI Setup Instructions"
2. Verify clipboard contains the full installation prompt

### 2.3 Run AI Install
1. Open Claude Code, Cursor, or Codex
2. Paste the installation prompt
3. Let AI execute the installation

### 2.4 Verify Results
- [ ] Virtual environment created (venv/)
- [ ] Dependencies installed (flask, fastmcp, etc.)
- [ ] Server starts without errors
- [ ] Health endpoint responds: `curl http://localhost:5000/api/health`
- [ ] MCP configuration created with correct paths
- [ ] FASTMCP_CHECK_FOR_UPDATES = "off" (NOT "false")
- [ ] Timestamped backup created for any modified config files

### 2.5 Test MCP Connection
1. Open a NEW chat session in the AI tool
2. Say "hi"
3. FixOnce should respond with session initialization
4. Verify tools like `fo_init` work

## Step 3: Test Terminal Install Flow

### 3.1 Clean Again
Repeat Step 1 to reset

### 3.2 Terminal Install
```bash
cd ~/Desktop/FixOnce
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python src/server.py --flask-only
```

### 3.3 Verify
- [ ] Server starts on port 5000 (or next available)
- [ ] Dashboard accessible at http://localhost:5000
- [ ] Manual MCP configuration needed (expected for terminal install)

## Pass/Fail Criteria

### PASS if:
- Both install flows complete without errors
- Server runs and responds to health checks
- MCP connection works in new AI session
- No hardcoded paths (all paths are machine-relative)
- FASTMCP_CHECK_FOR_UPDATES never set to "false"

### FAIL if:
- Python version check skipped
- Dependencies fail silently
- MCP config has invalid JSON/TOML
- Server fails to start
- AI prompt contains hardcoded paths
- Any step silently fails without user notification

## Test Results

| Test | Date | Result | Notes |
|------|------|--------|-------|
| AI Install (macOS) | | | |
| AI Install (Windows) | | | |
| Terminal Install (macOS) | | | |
| Terminal Install (Windows) | | | |
| MCP Connection (Claude Code) | | | |
| MCP Connection (Cursor) | | | |
| MCP Connection (Codex) | | | |
