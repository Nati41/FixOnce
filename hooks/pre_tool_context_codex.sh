#!/bin/bash
# FixOnce Hook: PreToolUse for Codex
# Injects area-based context when agent touches a file.
#
# Output formats (official Codex PreToolUse spec):
#
# 1. No context: empty output (allow)
#
# 2. Relevant context (non-blocking):
#    {"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"..."}}
#
# 3. Confirmed conflict (blocking):
#    {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}
#    OR legacy: {"decision":"block","reason":"..."}
#
# DO NOT USE: ask, approve, top-level deny

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

# Block output using official hookSpecificOutput format
emit_block() {
  local REASON="$1"
  local REASON_ESCAPED
  REASON_ESCAPED=$(printf '%s' "$REASON" | jq -Rs '.')
  cat <<EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":$REASON_ESCAPED}}
EOF
}

# Context output using official hookSpecificOutput format
emit_context() {
  local CONTEXT="$1"
  local CONTEXT_ESCAPED
  CONTEXT_ESCAPED=$(printf '%s' "$CONTEXT" | jq -Rs '.')
  cat <<EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":$CONTEXT_ESCAPED}}
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
    script_tools = {"python", "python3", "perl", "ruby", "node"}
    write_indicators = {"open(", "write(", "Path(", ".write_text(", ".write_bytes(",
                        "with open", ">>", "> ", "tee ", "sed -i", "shutil.copy",
                        "shutil.move", "os.rename", "pathlib"}

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

    # For python/python3 commands running a script file, parse the script for write targets
    if tool in script_tools:
        script_file = None
        for token in tokens[1:]:
            if not token.startswith("-") and looks_like_path(token):
                script_file = token
                break

        if script_file:
            script_path = Path(script_file) if Path(script_file).is_absolute() else cwd / script_file
            if script_path.exists() and script_path.suffix in {".py", ".js", ".rb", ".pl"}:
                try:
                    script_content = script_path.read_text(encoding="utf-8", errors="ignore")
                    # Check if script contains write operations
                    has_writes = any(ind in script_content for ind in write_indicators)
                    if has_writes:
                        # Extract all file paths from the script content
                        for match in re.findall(r"['\"]([^'\"]+\.(?:py|js|ts|tsx|jsx|sh|html|css|json|yaml|yml|toml))['\"]", script_content):
                            if "/" in match or match.startswith("src"):
                                add_path(paths, match)
                except Exception:
                    pass

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
  _debug_log 'OUTPUT=(empty) reason=no_file_paths'
  # No output = allow
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
      emit_block "FIXONCE_BLOCKING_WARNING: FixOnce context server is unavailable. Cannot verify project memory before editing protected file."
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

  # Check for explicit blocking warning
  if echo "$CONTEXT" | grep -q "FIXONCE_BLOCKING_WARNING"; then
    _debug_log "OUTPUT_BLOCK reason=FIXONCE_BLOCKING_WARNING"
    emit_block "$CONTEXT"
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
  _debug_log 'OUTPUT=(empty) reason=no_combined_context'
  # No output = allow
  exit 0
fi

# Check if this is a write operation that may conflict with active decisions
IS_WRITE_OP="false"
case "$TOOL_NAME" in
  Edit|Write|apply_patch|str_replace_editor|exec_command|exec|Bash|bash|shell)
    IS_WRITE_OP="true"
    ;;
esac

# Detect confirmed conflicts: high-relevance decisions (>=75%) or avoid patterns (>=70%)
CONFLICT_DETECTED="false"
CONFLICT_DECISION=""

if [ "$IS_WRITE_OP" = "true" ]; then
  # Check for high-relevance decisions (75%+)
  if echo "$COMBINED_CONTEXT" | grep -qE '📌 Decision \(([7-9][5-9]|[89][0-9]|100)%\):'; then
    CONFLICT_DETECTED="true"
    # Extract the first high-relevance decision text
    CONFLICT_DECISION=$(echo "$COMBINED_CONTEXT" | grep -oE '📌 Decision \([7-9][0-9]%\): [^.]+' | head -1)
    if [ -z "$CONFLICT_DECISION" ]; then
      CONFLICT_DECISION=$(echo "$COMBINED_CONTEXT" | grep -oE '📌 Decision \(100%\): [^.]+' | head -1)
    fi
  fi

  # Check for avoid patterns (70%+)
  if echo "$COMBINED_CONTEXT" | grep -qE '🚫 Avoid \(([7-9][0-9]|100)%\):'; then
    CONFLICT_DETECTED="true"
    if [ -z "$CONFLICT_DECISION" ]; then
      CONFLICT_DECISION=$(echo "$COMBINED_CONTEXT" | grep -oE '🚫 Avoid \([7-9][0-9]%\): [^.]+' | head -1)
      if [ -z "$CONFLICT_DECISION" ]; then
        CONFLICT_DECISION=$(echo "$COMBINED_CONTEXT" | grep -oE '🚫 Avoid \(100%\): [^.]+' | head -1)
      fi
    fi
  fi
fi

# If confirmed conflict on write operation, BLOCK the edit
if [ "$CONFLICT_DETECTED" = "true" ]; then
  BLOCK_REASON="⚠️ CONFLICT WITH ACTIVE PROJECT DECISION

$CONFLICT_DECISION

This edit is BLOCKED because it conflicts with an active project decision.

⛔ YOU MUST ASK THE USER before proceeding.

Tell the user:
\"This change conflicts with a documented project decision. How would you like to proceed?\"

Options to present to the user:
1. Supersede the old decision (user explicitly confirms replacing it)
2. Add as exception (keep old decision, add scoped exception)
3. Cancel the change

DO NOT call fo_decide(supersede) without explicit user approval.
The original task request is NOT approval to change project decisions."

  _debug_log "OUTPUT_BLOCK conflict_detected decision=$CONFLICT_DECISION"
  emit_block "$BLOCK_REASON"
  exit 0
fi

# No conflict: inject context via additionalContext (non-blocking)
_debug_log "OUTPUT_CONTEXT context=$COMBINED_CONTEXT"
emit_context "$COMBINED_CONTEXT"
exit 0
