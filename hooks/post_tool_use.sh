#!/bin/bash
# FixOnce Hook: PostToolUse
# Logs file changes to FixOnce activity feed
# Also checks for browser errors related to the current project

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
      # Log to FixOnce (silent)
      curl -s -X POST "http://localhost:5000/api/activity/log" \
        -H "Content-Type: application/json" \
        -d "{
          \"type\": \"file_change\",
          \"tool\": \"$TOOL_NAME\",
          \"file\": \"$FILE_PATH\",
          \"cwd\": \"$CWD\",
          \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        }" >/dev/null 2>&1 || true
    fi
    ;;
  Bash)
    COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // empty')
    # Log significant commands (silent)
    if echo "$COMMAND" | grep -qE "^(npm|yarn|pip|python|node|git)"; then
      curl -s -X POST "http://localhost:5000/api/activity/log" \
        -H "Content-Type: application/json" \
        -d "{
          \"type\": \"command\",
          \"command\": \"$COMMAND\",
          \"cwd\": \"$CWD\",
          \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        }" >/dev/null 2>&1 || true
    fi
    ;;
esac

# ============================================
# Check for browser errors related to project
# ============================================

# Get active project info from local file (more reliable than API)
FIXONCE_DATA="/Users/haimdayan/Desktop/FixOnce/data"
ACTIVE_PROJECT_FILE="$FIXONCE_DATA/active_project.json"

PROJECT_ID=""
PROJECT_DIR=""
PROJECT_PORT=""

if [ -f "$ACTIVE_PROJECT_FILE" ]; then
  PROJECT_ID=$(jq -r '.active_id // empty' "$ACTIVE_PROJECT_FILE" 2>/dev/null)
  PROJECT_DIR=$(jq -r '.working_dir // empty' "$ACTIVE_PROJECT_FILE" 2>/dev/null)

  # Get port from project memory file
  if [ -n "$PROJECT_ID" ]; then
    PROJECT_FILE="$FIXONCE_DATA/projects_v2/${PROJECT_ID}.json"
    if [ -f "$PROJECT_FILE" ]; then
      PROJECT_PORT=$(jq -r '.connected_server.port // empty' "$PROJECT_FILE" 2>/dev/null)
    fi
  fi
fi

# Only check if we have project info
if [ -n "$PROJECT_PORT" ] || [ -n "$PROJECT_DIR" ]; then

  # Get recent browser errors (last 30 seconds)
  RESPONSE=$(curl -s "http://localhost:5000/api/live-errors?since=30" 2>/dev/null || echo '{"errors":[]}')
  ERROR_COUNT=$(echo "$RESPONSE" | jq '.count // 0')

  if [ "$ERROR_COUNT" -gt 0 ]; then
    # Filter errors related to this project (by port or by checking if it's localhost)
    RELEVANT_ERRORS=""
    RELEVANT_COUNT=0

    while IFS= read -r error; do
      ERROR_URL=$(echo "$error" | jq -r '.url // empty' 2>/dev/null)
      ERROR_FILE=$(echo "$error" | jq -r '.file // empty' 2>/dev/null)
      ERROR_MSG=$(echo "$error" | jq -r '.message // empty' 2>/dev/null)
      ERROR_TYPE=$(echo "$error" | jq -r '.type // "error"' 2>/dev/null)

      # Check if error is related to this project
      IS_RELATED=false

      # Check if URL contains the project port
      if [ -n "$PROJECT_PORT" ]; then
        if echo "$ERROR_URL $ERROR_FILE" | grep -q "localhost:$PROJECT_PORT"; then
          IS_RELATED=true
        fi
      fi

      # Fallback: any localhost error is considered related during active dev
      if [ "$IS_RELATED" = false ] && echo "$ERROR_URL $ERROR_FILE" | grep -q "localhost"; then
        IS_RELATED=true
      fi

      if [ "$IS_RELATED" = true ]; then
        RELEVANT_COUNT=$((RELEVANT_COUNT + 1))
        # Truncate message for readability
        SHORT_MSG=$(echo "$ERROR_MSG" | head -c 150)
        if [ -n "$RELEVANT_ERRORS" ]; then
          RELEVANT_ERRORS="$RELEVANT_ERRORS
  - [$ERROR_TYPE] $SHORT_MSG"
        else
          RELEVANT_ERRORS="  - [$ERROR_TYPE] $SHORT_MSG"
        fi
      fi
    done < <(echo "$RESPONSE" | jq -c '.errors[]')

    # If we have relevant errors, output them to stdout (visible in terminal)
    if [ "$RELEVANT_COUNT" -gt 0 ]; then
      PORT_INFO=""
      [ -n "$PROJECT_PORT" ] && PORT_INFO=" (localhost:$PROJECT_PORT)"
      echo ""
      echo "⚠️ FixOnce: $RELEVANT_COUNT שגיאות דפדפן חדשות$PORT_INFO"
      echo "$RELEVANT_ERRORS"
      echo ""
      echo "📌 Use get_browser_errors() for full details."
    fi
  fi
fi

# Always allow (exit 0)
exit 0
