# Client Onboarding Audit

## Summary

FixOnce now installs both the memory connection and the startup instructions needed to auto-connect on the first meaningful user message across supported AI clients.

| Client | MCP | Rules | Auto-init | Status | Missing Pieces |
| --- | --- | --- | --- | --- | --- |
| Claude | `~/.claude.json` | `~/.claude/CLAUDE.md` plus Claude hooks | Yes | Complete | Restart Claude after install |
| Cursor | `~/.cursor/mcp.json` | Cursor user rules in `settings.json` via `cursor.general.aiRules` | Yes | Complete | Restart Cursor after install |
| Codex | `~/.codex/config.toml` | `~/.codex/AGENTS.md` | Yes | Complete | Restart Codex after install |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `~/.codeium/windsurf/memories/global_rules.md` | Yes | Complete | Restart Windsurf after install |

## Behavior Target

- First meaningful message triggers one `fo_init(...)`
- `fo_init` opener is shown once
- No duplicate opener
- No repeated init unless the session is reset or the user explicitly asks to reconnect
- Manual `fo_init(...)` still works

## Current Integration Notes

- Claude uses both global rules and session hooks, so it has the strongest auto-init path.
- Cursor now receives global user rules directly in Cursor settings instead of relying on project-local `.cursorrules`.
- Codex now receives global startup instructions in `~/.codex/AGENTS.md`.
- Windsurf now receives both global MCP config and global always-on rules.

## QA Matrix

| Scenario | Claude | Cursor | Codex | Windsurf |
| --- | --- | --- | --- | --- |
| Fresh user install writes MCP config | Yes | Yes | Yes | Yes |
| Fresh user install writes startup rules | Yes | Yes | Yes | Yes |
| New session should auto-init once | Yes | Yes | Yes | Yes |
| Manual `fo_init(...)` still allowed | Yes | Yes | Yes | Yes |
| Home folder protection preserved | Yes | Yes | Yes | Yes |

## Remaining Blockers

- End-to-end validation still requires manual fresh-session checks inside each client UI.
- Cursor user rules rely on the currently observed `cursor.general.aiRules` setting key. This is validated locally in this environment and should be watched if Cursor changes its settings schema.
