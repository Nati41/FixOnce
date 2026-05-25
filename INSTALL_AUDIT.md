# Installer Audit

## Root Cause

The backend is not the failing layer. The break is in installer orchestration:

- The packaged macOS installer used a separate startup path from the existing readiness helpers.
- LaunchAgent startup relied on `launchctl load` semantics and a one-shot manual health probe instead of the real background service path.
- Installer state was implicit. Different layers inferred readiness from `install_state.json`, runtime presence, current port scans, or UI assumptions.
- The installer UI exposed internal implementation terms that a normal user should never need.

## Failure Tree

1. Installer says setup is complete before proving that background startup is healthy.
2. LaunchAgent may exist but may never be bootstrapped into the active GUI domain.
3. `runtime.json` never appears, so the dashboard fallback and onboarding become inconsistent.
4. Log files may not exist because the service never starts, leaving the user with no clear recovery path.
5. User lands in a state where manual `./venv/bin/python src/server.py` appears to "fix" the issue, which means packaged install failed.

## Fixes Implemented

- Added explicit installer states in `src/core/install_state_machine.py`:
  - `NOT_INSTALLED`
  - `INSTALLING`
  - `STARTING`
  - `WAITING_HEALTH`
  - `READY`
  - `RECOVERY`
  - `FAILED`
- Moved backend install/readiness decisions onto the state machine instead of a bare boolean install marker.
- Hardened the macOS installer startup path:
  - creates and touches log files before startup
  - clears stale `runtime.json` and `server.lock`
  - uses `launchctl bootstrap` and `kickstart` first
  - retries startup once with a repaired LaunchAgent
  - inspects launchctl output and server logs before final failure
- Simplified installer UX copy so the default experience is product language rather than infrastructure language.

## Remaining Risks

- Fresh-user validation still needs a true clean macOS account or VM; unit tests cannot prove `launchctl` behavior end-to-end.
- The success page can present "Open Claude / Cursor / Codex" actions, but browser-based pages cannot reliably launch every desktop app directly.
- MCP/editor configuration still exists behind the scenes; the wording is simplified, but editor-specific edge cases can still fail independently of server startup.

## Recommended Fresh-User Validation

1. New macOS user account.
2. No `~/FixOnce`.
3. No `~/.fixonce`.
4. No `~/Library/LaunchAgents/com.fixonce.server.plist`.
5. Install only from DMG.
6. Confirm:
   - `~/FixOnce/venv` exists
   - `~/.fixonce/install_state.json` ends at `READY`
   - `~/.fixonce/runtime.json` exists
   - `~/Library/LaunchAgents/com.fixonce.server.plist` exists
   - `curl http://localhost:<runtime_port>/api/health` succeeds
   - browser opens without terminal recovery
