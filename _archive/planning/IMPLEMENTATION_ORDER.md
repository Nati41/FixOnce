# Implementation Order

## Phase A — Critical Onboarding Fixes

Fix correctness issues before changing dashboard UX:

1. Fix corrupted `~/.fixonce/config.json`
2. Restore reliable Claude MCP creation
3. Remove or fulfill missing Claude hook references
4. Write Cursor user rules to the verified supported location
5. Write Windsurf MCP config alongside Windsurf rules
6. Unify `fo_init` and `init_session` validation

Goal:
- Fresh-user onboarding becomes correct and deterministic

## Phase B — Dashboard Wizard

Expose onboarding state in the dashboard:

1. Add first-run “Connect your AI tools” screen
2. Show Claude / Cursor / Codex / Windsurf cards
3. Use the shared dashboard status contract
4. Add per-client retry actions where safe
5. Ensure dashboard remains usable even when client onboarding is incomplete

Goal:
- No hidden onboarding failure feeling

## Phase C — Polish

1. Reduce duplicate installer/opening output
2. Improve user-language copy
3. Tighten restart messaging
4. Document client-specific edge cases that cannot be fixed safely

Goal:
- Cleaner first-run experience without changing core runtime/install architecture
