#!/bin/bash
# FixOnce Hook: SessionEnd
# Notifies FixOnce when a Claude session ends

# Read hook input from stdin
INPUT=$(cat)

CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

# Notify FixOnce
curl -s -X POST "http://localhost:5000/api/activity/session" \
  -H "Content-Type: application/json" \
  -d "{
    \"event\": \"end\",
    \"session_id\": \"$SESSION_ID\",
    \"cwd\": \"$CWD\",
    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" 2>/dev/null || true

exit 0
