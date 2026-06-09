#!/bin/bash
# FixOnce Hook: PostToolUse
# Logs file changes to FixOnce activity feed
# Also checks for browser errors related to the current project
# REMINDER: Outputs reminder to AI to update FixOnce after code changes

# Read hook input from stdin
INPUT=$(cat)

# Extract tool info
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
FIXONCE_ACTOR="${FIXONCE_ACTOR:-claude}"

# Get canonical port from runtime.json (SINGLE SOURCE OF TRUTH)
FIXONCE_PORT=5000
RUNTIME_FILE="$HOME/.fixonce/runtime.json"
if [ -f "$RUNTIME_FILE" ]; then
  RUNTIME_PORT=$(jq -r '.port // empty' "$RUNTIME_FILE" 2>/dev/null)
  if [ -n "$RUNTIME_PORT" ]; then
    FIXONCE_PORT="$RUNTIME_PORT"
  fi
fi

# Track activity type for reminder
ACTIVITY_TYPE=""

# Only process file operations
case "$TOOL_NAME" in
  Edit|Write|NotebookEdit|apply_patch)
    FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.file_path // .path // empty')
    ACTIVITY_TYPE="code"
    # apply_patch may affect multiple files, so cwd is sufficient for project attribution.
    PAYLOAD=$(jq -n \
      --arg type "file_change" \
      --arg tool "$TOOL_NAME" \
      --arg file "$FILE_PATH" \
      --arg cwd "$CWD" \
      --arg editor "$FIXONCE_ACTOR" \
      --arg session_id "$SESSION_ID" \
      --arg source "PostToolUse" \
      --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{type:$type, tool:$tool, file:$file, cwd:$cwd, editor:$editor, session_id:$session_id, source:$source, timestamp:$timestamp}')
    curl -s -X POST "http://localhost:$FIXONCE_PORT/api/activity/log" \
      -H "Content-Type: application/json" \
      -d "$PAYLOAD" >/dev/null 2>&1 || true
    ;;
  Bash)
    COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // empty')
    # Detect test/build commands
    if echo "$COMMAND" | grep -qE "(pytest|jest|npm test|yarn test|go test|cargo test|make test)"; then
      ACTIVITY_TYPE="test"
    elif echo "$COMMAND" | grep -qE "(npm run|yarn |make |cargo build|go build)"; then
      ACTIVITY_TYPE="build"
    fi
    # Log significant commands (silent)
    if echo "$COMMAND" | grep -qE "(^|[;&|][[:space:]]*)(npm|yarn|pip|python|node|git|rm|unlink|touch|cp|mv|install|tee)([[:space:]]|$)|>{1,2}"; then
      PAYLOAD=$(jq -n \
        --arg type "command" \
        --arg command "$COMMAND" \
        --arg cwd "$CWD" \
        --arg editor "$FIXONCE_ACTOR" \
        --arg session_id "$SESSION_ID" \
        --arg source "PostToolUse" \
        --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{type:$type, command:$command, cwd:$cwd, editor:$editor, session_id:$session_id, source:$source, timestamp:$timestamp}')
      curl -s -X POST "http://localhost:$FIXONCE_PORT/api/activity/log" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" >/dev/null 2>&1 || true
    fi
    ;;
esac

# ============================================
# Check for browser errors related to project
# ============================================

# Get active project info from local file (more reliable than API)
# Detect FixOnce installation directory from hook location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXONCE_DIR="$(dirname "$SCRIPT_DIR")"
FIXONCE_DATA="$FIXONCE_DIR/data"
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
  RESPONSE=$(curl -s "http://localhost:$FIXONCE_PORT/api/live-errors?since=30" 2>/dev/null || echo '{"errors":[]}')
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
      echo "📌 Use fo_errors() for full details."
    fi
  fi
fi

# ============================================
# REMINDER: Update FixOnce after meaningful work
# ============================================
case "$ACTIVITY_TYPE" in
  code)
    echo "💾 FixOnce: fo_sync() after changes, fo_solved() after fixes, fo_decide() after decisions"
    ;;
  test)
    echo "💾 FixOnce: fo_solved() if you fixed a bug, fo_sync() to record progress"
    ;;
  build)
    echo "💾 FixOnce: fo_sync() to record progress"
    ;;
esac

# Always allow (exit 0)
exit 0
