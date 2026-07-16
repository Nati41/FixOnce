#!/bin/bash
# FixOnce Hook: SessionStart
# CRITICAL: Reminds Claude to connect to FixOnce on every session
# OUTPUT: Only the intended reminder text. Never raw HTML, 404s, or server errors.

# Read hook input from stdin
INPUT=$(cat)

CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Get canonical port from runtime.json (SINGLE SOURCE OF TRUTH)
FIXONCE_PORT=5000
RUNTIME_FILE="$HOME/.fixonce/runtime.json"
SERVER_AVAILABLE=false

if [ -f "$RUNTIME_FILE" ]; then
  RUNTIME_PORT=$(jq -r '.port // empty' "$RUNTIME_FILE" 2>/dev/null)
  if [ -n "$RUNTIME_PORT" ]; then
    FIXONCE_PORT="$RUNTIME_PORT"
  fi

  # Check if server is actually responding (suppress ALL output)
  PING_RESULT=$(curl -s --connect-timeout 2 "http://localhost:$FIXONCE_PORT/api/ping" 2>/dev/null)
  if echo "$PING_RESULT" | grep -q '"service":"fixonce"' 2>/dev/null; then
    SERVER_AVAILABLE=true
  fi
fi

# Output ONLY intended messages - never raw HTTP responses
if [ "$SERVER_AVAILABLE" = true ]; then
  echo "🧠 FixOnce: BEFORE responding to user, you MUST call fo_init(cwd=\"$CWD\") to connect. This is mandatory - do not skip this step."
else
  # Server unavailable - warn the agent
  echo "⚠️ FixOnce server is unavailable."
  echo ""
  echo "Project memory may NOT be recorded."
  echo ""
  echo "Call fo_init(cwd=\"$CWD\")."
  echo ""
  echo "If fo_init is unavailable or fails:"
  echo "  Do not continue silently. Notify the user before meaningful work."
  echo "  1. Ensure FixOnce is running."
  echo "  2. Open a NEW AI conversation."
fi

exit 0
