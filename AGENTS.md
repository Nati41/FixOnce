# FixOnce Project - Codex Instructions

This IS the FixOnce project itself - a persistent memory layer for AI coding assistants.

## On Session Start

```
auto_init_session(cwd="/Users/haimdayan/Desktop/FixOnce")
```

## Project Structure

- `src/server.py` - Flask main server
- `src/mcp_server/mcp_memory_server_v2.py` - MCP tools
- `src/core/` - Business logic
- `src/api/` - REST endpoints
- `data/dashboard_vnext.html` - Dashboard UI

## Active Decisions

Check `auto_init_session` response for current decisions. Key ones:
- Per-project semantic index with provider abstraction
- Atomic file writes with FileLock
- Store data in English, display in user's language

## Testing

Run stress tests:
```bash
python3 tests/stress_test.py --quick
```

Tests use isolated `/tmp` project - won't affect real data.
