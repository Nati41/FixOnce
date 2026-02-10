#!/bin/bash
# FixOnce Hook: SessionStart
# Notifies FixOnce when a Claude session starts

# Read hook input from stdin
INPUT=$(cat)

CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
SOURCE=$(echo "$INPUT" | jq -r '.source // "startup"')

# Notify FixOnce
curl -s -X POST "http://localhost:5000/api/activity/session" \
  -H "Content-Type: application/json" \
  -d "{
    \"event\": \"start\",
    \"session_id\": \"$SESSION_ID\",
    \"cwd\": \"$CWD\",
    \"source\": \"$SOURCE\",
    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" 2>/dev/null || true

exit 0
