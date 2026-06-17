#!/bin/bash
# FixOnce Hook: PreToolUse
# Injects area-based context when agent touches a file.
# This is the "code remembers" feature.

# Read hook input from stdin
INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only process Read/Edit on actual files
if [ -z "$FILE_PATH" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Skip non-source files
case "$FILE_PATH" in
  *.json|*.lock|*.log|*.md|*.txt|*.csv)
    echo '{"continue": true}'
    exit 0
    ;;
esac

# Get canonical port from runtime.json
FIXONCE_PORT=5000
RUNTIME_FILE="$HOME/.fixonce/runtime.json"
if [ -f "$RUNTIME_FILE" ]; then
  RUNTIME_PORT=$(jq -r '.port // empty' "$RUNTIME_FILE" 2>/dev/null)
  if [ -n "$RUNTIME_PORT" ]; then
    FIXONCE_PORT="$RUNTIME_PORT"
  fi
fi

# Query area context
RESPONSE=$(curl -s --max-time 2 "http://localhost:$FIXONCE_PORT/api/activity/area-context?path=$FILE_PATH" 2>/dev/null)

# Check if we got valid context
if [ -z "$RESPONSE" ] || [ "$RESPONSE" = "null" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Extract context text
CONTEXT=$(echo "$RESPONSE" | jq -r '.context // empty')
COUNT=$(echo "$RESPONSE" | jq -r '.count // 0')

if [ -z "$CONTEXT" ] || [ "$COUNT" = "0" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Escape for JSON
CONTEXT_ESCAPED=$(echo "$CONTEXT" | jq -Rs '.')

# Return context for injection
cat <<EOF
{
  "continue": true,
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": $CONTEXT_ESCAPED
  }
}
EOF

exit 0
