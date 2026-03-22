#!/bin/bash
# FixOnce Hook: SessionStart
# CRITICAL: Reminds Claude to connect to FixOnce on every session

# Read hook input from stdin
INPUT=$(cat)

CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

# Get canonical port from runtime.json (SINGLE SOURCE OF TRUTH)
FIXONCE_PORT=5000
RUNTIME_FILE="$HOME/.fixonce/runtime.json"
if [ -f "$RUNTIME_FILE" ]; then
  RUNTIME_PORT=$(jq -r '.port // empty' "$RUNTIME_FILE" 2>/dev/null)
  if [ -n "$RUNTIME_PORT" ]; then
    FIXONCE_PORT="$RUNTIME_PORT"
  fi
fi

# Notify FixOnce server
curl -s -X POST "http://localhost:$FIXONCE_PORT/api/activity/session" \
  -H "Content-Type: application/json" \
  -d "{
    \"event\": \"start\",
    \"session_id\": \"$SESSION_ID\",
    \"cwd\": \"$CWD\",
    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" 2>/dev/null || true

# OUTPUT A REMINDER TO CLAUDE - This message appears in Claude's context
echo "🧠 FixOnce: BEFORE responding to user, you MUST call auto_init_session(cwd=\"$CWD\") to connect. This is mandatory - do not skip this step."

exit 0
