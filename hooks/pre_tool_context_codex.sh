#!/bin/bash
# FixOnce Hook: PreToolUse for Codex
# Injects area-based context when agent touches a file.

_debug_log() {
  if [ -z "$FIXONCE_HOOK_DEBUG" ]; then
    return
  fi
  DEBUG_LOG="${FIXONCE_HOOK_DEBUG_LOG:-/tmp/fixonce_codex_pretool_debug.log}"
  {
    printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1"
  } >> "$DEBUG_LOG" 2>/dev/null || true
}

is_protected_path() {
  case "$1" in
    src/core/project_context.py|*/src/core/project_context.py)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

block_context_unavailable() {
  cat <<'EOF'
{"decision":"block","reason":"FIXONCE_BLOCKING_WARNING FixOnce context server is unavailable; refusing to read protected file before context is checked."}
EOF
}

# Read hook input from stdin
INPUT=$(cat)
_debug_log "START raw_stdin=$INPUT"
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
_debug_log "TOOL_NAME=$TOOL_NAME"
FILE_PATHS=$(HOOK_INPUT="$INPUT" python3 - <<'PY'
import json
import os
import re
import shlex
from pathlib import Path

payload = json.loads(os.environ.get("HOOK_INPUT", "{}") or "{}")
tool_input = payload.get("tool_input") or {}
cwd = Path(payload.get("cwd") or os.getcwd())


def looks_like_path(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    if token in {".", ".."}:
        return False
    normalized = token.strip("'\"")
    if not normalized:
        return False
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    if candidate.exists():
        return True
    return bool(
        "/" in normalized
        and re.search(r"\.(py|js|ts|tsx|jsx|sh|html|css|json|yaml|yml|toml|md|txt)$", normalized)
    )


def add_path(paths: list[str], value: str) -> None:
    value = (value or "").strip().strip("'\"")
    if value and value not in paths:
        paths.append(value)


def extract_from_command(command: str, depth: int = 0) -> list[str]:
    if not command or depth > 2:
        return []
    paths: list[str] = []
    if command.startswith("*** Begin Patch"):
        for line in command.splitlines():
            match = re.match(r"\*\*\* (?:Add|Update|Delete) File: (.+)$", line)
            if match and looks_like_path(match.group(1)):
                add_path(paths, match.group(1))
        return paths

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    if not tokens:
        return paths

    tool = Path(tokens[0]).name

    # Shell wrappers: bash -lc "sed ..."
    if tool in {"bash", "sh", "zsh"}:
        for idx, token in enumerate(tokens[:-1]):
            if token in {"-c", "-lc"}:
                for path in extract_from_command(tokens[idx + 1], depth + 1):
                    add_path(paths, path)

    read_tools = {"sed", "cat", "head", "tail", "grep", "rg", "awk"}
    script_tools = {"python", "python3", "perl", "ruby"}

    if tool in read_tools or tool in script_tools:
        for token in tokens[1:]:
            if looks_like_path(token):
                add_path(paths, token)

    # Detect path-like strings inside one-liners, e.g. python -c 'open("src/a.py")'.
    for match in re.findall(r"['\"]([^'\"]+/[^'\"]+\.(?:py|js|ts|tsx|jsx|sh|html|css|json|yaml|yml|toml|md|txt))['\"]", command):
        if looks_like_path(match):
            add_path(paths, match)

    # Detect unquoted paths in patch text or shell snippets.
    for match in re.findall(r"(?<![\w./-])([\w./-]+/[\w./-]+\.(?:py|js|ts|tsx|jsx|sh|html|css|json|yaml|yml|toml|md|txt))(?![\w./-])", command):
        if looks_like_path(match):
            add_path(paths, match)

    return paths


paths: list[str] = []
for key in ("file_path", "path"):
    add_path(paths, str(tool_input.get(key) or ""))

for key in ("cmd", "command"):
    for path in extract_from_command(str(tool_input.get(key) or "")):
        add_path(paths, path)

print("\n".join(paths))
PY
)
_debug_log "FILE_PATHS=$(printf '%s' "$FILE_PATHS" | tr '\n' '|')"

# Only process on actual files
if [ -z "$FILE_PATHS" ]; then
  _debug_log 'OUTPUT={"decision": "approve"} reason=no_file_paths'
  echo '{"decision": "approve"}'
  exit 0
fi

# Get canonical port from runtime.json
FIXONCE_PORT=5000
RUNTIME_FILE="$HOME/.fixonce/runtime.json"
if [ -f "$RUNTIME_FILE" ]; then
  RUNTIME_PORT=$(jq -r '.port // empty' "$RUNTIME_FILE" 2>/dev/null)
  if [ -n "$RUNTIME_PORT" ]; then
    FIXONCE_PORT="$RUNTIME_PORT"
  fi
fi

COMBINED_CONTEXT=""

while IFS= read -r FILE_PATH; do
  [ -z "$FILE_PATH" ] && continue

  # Skip non-source files
  case "$FILE_PATH" in
    *.json|*.lock|*.log|*.md|*.txt|*.csv)
      continue
      ;;
  esac

  # Query area context
  RESPONSE=$(curl -s --max-time 2 -G --data-urlencode "path=$FILE_PATH" "http://localhost:$FIXONCE_PORT/api/activity/area-context" 2>/dev/null)
  CURL_STATUS=$?
  _debug_log "AREA_CONTEXT path=$FILE_PATH port=$FIXONCE_PORT response=$RESPONSE"

  # Check if we got valid context
  if [ "$CURL_STATUS" != "0" ] || [ -z "$RESPONSE" ] || [ "$RESPONSE" = "null" ]; then
    if is_protected_path "$FILE_PATH"; then
      _debug_log "OUTPUT_BLOCK reason=context_unavailable protected_path=$FILE_PATH curl_status=$CURL_STATUS"
      block_context_unavailable
      exit 0
    fi
    continue
  fi

  # Extract context text
  CONTEXT=$(echo "$RESPONSE" | jq -r '.context // empty')
  COUNT=$(echo "$RESPONSE" | jq -r '.count // 0')

  if [ -z "$CONTEXT" ]; then
    continue
  fi

  if echo "$CONTEXT" | grep -q "FIXONCE_BLOCKING_WARNING"; then
    REASON=$(printf '%s' "$CONTEXT" | jq -Rs '.')
    _debug_log "OUTPUT_BLOCK reason=$CONTEXT"
    cat <<EOF
{"decision":"block","reason":$REASON}
EOF
    exit 0
  fi

  if [ "$COUNT" = "0" ]; then
    continue
  fi

  COMBINED_CONTEXT="${COMBINED_CONTEXT}${CONTEXT}
"
done <<EOF
$FILE_PATHS
EOF

if [ -z "$COMBINED_CONTEXT" ]; then
  _debug_log 'OUTPUT={"decision": "approve"} reason=no_combined_context'
  echo '{"decision": "approve"}'
  exit 0
fi

# Escape for JSON
CONTEXT_ESCAPED=$(echo "$COMBINED_CONTEXT" | jq -Rs '.')

# Return context for injection (Codex format - may differ from Claude)
cat <<EOF
{
  "decision": "approve",
  "message": $CONTEXT_ESCAPED
}
EOF
_debug_log "OUTPUT_APPROVE message=$COMBINED_CONTEXT"

exit 0
