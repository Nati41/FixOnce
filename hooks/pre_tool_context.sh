#!/bin/bash
# FixOnce Hook: PreToolUse
# Injects area-based context when agent touches a file.
# This is the "code remembers" feature.

# Debug logging (enable with FIXONCE_HOOK_DEBUG=1)
if [ "${FIXONCE_HOOK_DEBUG:-0}" = "1" ]; then
  DEBUG_LOG="/tmp/fixonce_hook_debug.log"
  exec 2>>"$DEBUG_LOG"
  echo "=== $(date) ===" >&2
fi

# Read hook input from stdin
INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# For Bash commands, extract file path from read-like commands
if [ "$TOOL_NAME" = "Bash" ] && [ -z "$FILE_PATH" ]; then
  COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
  # Extract last argument from cat/head/tail/less/bat commands (typically the file)
  if echo "$COMMAND" | grep -qE '^(cat|head|tail|less|bat)[[:space:]]'; then
    FILE_PATH=$(echo "$COMMAND" | cut -d'|' -f1 | cut -d'&' -f1 | cut -d';' -f1 | awk '{print $NF}')
  fi
fi

# Only process Read/Edit/Bash on actual files
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

if echo "$CONTEXT" | grep -q "FIXONCE_BLOCKING_WARNING"; then
  REASON=$(echo "$CONTEXT" | jq -Rs '.')
  cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $REASON
  }
}
EOF
  exit 0
fi

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
