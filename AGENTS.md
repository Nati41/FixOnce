# FixOnce Project - Codex Instructions

This IS the FixOnce project itself - a persistent memory layer for AI coding assistants.

## On Session Start

```
fo_init(cwd="project-path")  # Mandatory before other FixOnce work
```

## Tools (fo_* workflow)

| Tool | Purpose |
|------|---------|
| `fo_init` | Start session |
| `fo_errors` | Check browser errors |
| `fo_apply` | Apply known fix (when AUTO-FIX READY) |
| `fo_sync` | Update context after changes |
| `fo_search` | Search past solutions |
| `fo_solved` | Record a fix |
| `fo_decide` | Record a decision |

## Project Structure

- `src/server.py` - Flask main server
- `src/mcp_server/mcp_memory_server_v2.py` - MCP tools
- `src/core/` - Business logic
- `src/api/` - REST endpoints
- `data/dashboard.html` - Dashboard UI

## Rules

1. `fo_init()` before anything
2. If AUTO-FIX READY → `fo_apply()` immediately
3. `fo_sync()` after code changes

## Testing

```bash
python3 tests/stress_test.py --quick
```
