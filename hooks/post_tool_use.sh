#!/bin/bash
# FixOnce Hook: PostToolUse
# Logs file changes to FixOnce activity feed

# Read hook input from stdin
INPUT=$(cat)

# Extract tool info
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Only process file operations
case "$TOOL_NAME" in
  Edit|Write|NotebookEdit)
    FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.file_path // empty')
    if [ -n "$FILE_PATH" ]; then
      # Log to FixOnce
      curl -s -X POST "http://localhost:5000/api/activity/log" \
        -H "Content-Type: application/json" \
        -d "{
          \"type\": \"file_change\",
          \"tool\": \"$TOOL_NAME\",
          \"file\": \"$FILE_PATH\",
          \"cwd\": \"$CWD\",
          \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        }" 2>/dev/null || true
    fi
    ;;
  Bash)
    COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // empty')
    # Log significant commands
    if echo "$COMMAND" | grep -qE "^(npm|yarn|pip|python|node|git)"; then
      curl -s -X POST "http://localhost:5000/api/activity/log" \
        -H "Content-Type: application/json" \
        -d "{
          \"type\": \"command\",
          \"command\": \"$COMMAND\",
          \"cwd\": \"$CWD\",
          \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        }" 2>/dev/null || true
    fi
    ;;
esac

# Always allow (exit 0)
exit 0
