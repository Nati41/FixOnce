#!/bin/bash
# FixOnce Hook: SessionEnd
# Notifies FixOnce when a Claude session ends

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

# Notify FixOnce
curl -s -X POST "http://localhost:$FIXONCE_PORT/api/activity/session" \
  -H "Content-Type: application/json" \
  -d "{
    \"event\": \"end\",
    \"session_id\": \"$SESSION_ID\",
    \"cwd\": \"$CWD\",
    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" 2>/dev/null || true

exit 0
