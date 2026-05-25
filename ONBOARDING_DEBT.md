# Onboarding Debt

## 1. Corrupted `~/.fixonce/config.json`

- Severity: High
- Root cause: Installer/startup flow writes progress text into the `port` field instead of only writing structured JSON data.
- Files:
  - `installer/macos/build_installer.sh`
  - `scripts/install.py`
- Tests:
  - Generated `~/.fixonce/config.json` is valid JSON
  - `port` is integer or absent
- Priority: Phase A

## 2. Claude MCP Missing

- Severity: High
- Root cause: Claude integration path is not reliably created when Claude CLI is unavailable or skipped during fresh-user install.
- Files:
  - `scripts/install.py`
  - `src/api/installer.py`
- Tests:
  - `~/.claude.json` exists after onboarding
  - `mcpServers.fixonce` exists in config
  - `claude mcp list` sees `fixonce` when CLI is present
- Priority: Phase A

## 3. Missing Claude Hooks

- Severity: High
- Root cause: `~/.claude/settings.json` can reference hook files that were never copied into the install directory.
- Files:
  - `scripts/install.py`
  - install packaging inputs if hooks should exist
- Tests:
  - No generated hook reference points to a missing file
  - If hooks are written, referenced files exist
- Priority: Phase A

## 4. Missing Cursor Rules

- Severity: Medium
- Root cause: Cursor onboarding relied on bundled/project files instead of verified user-level rules in the supported Cursor settings location.
- Files:
  - `scripts/install.py`
  - `data/global-agent-rules.md`
- Tests:
  - Cursor MCP exists
  - Cursor user rules exist in the supported location
- Priority: Phase A

## 5. Missing Windsurf MCP

- Severity: Medium
- Root cause: Windsurf rules were written but its MCP config was not always generated.
- Files:
  - `scripts/install.py`
  - `src/api/installer.py`
- Tests:
  - `~/.codeium/windsurf/mcp_config.json` exists
  - `mcpServers.fixonce` exists
  - `global_rules.md` still exists
- Priority: Phase A

## 6. `fo_init` vs `init_session` Mismatch

- Severity: High
- Root cause: Project validation paths are not fully unified, so the same folder can pass one init entry point and fail the other.
- Files:
  - `src/mcp_server/mcp_memory_server_v2.py`
- Tests:
  - Valid test project passes both `fo_init` and `init_session`
  - Home folder is still rejected
- Priority: Phase A

## 7. Duplicate Opener / Output

- Severity: Low
- Root cause: Some duplicate installer or client-facing messaging is still emitted across installer output and certain client behaviors.
- Files:
  - `installer/macos/build_installer.sh`
  - client-facing init/opening formatters if needed
- Tests:
  - No obvious duplicate “Opening FixOnce...” / “Installation Complete!” output
  - Codex duplication documented separately if it is client-side behavior
- Priority: Phase C
