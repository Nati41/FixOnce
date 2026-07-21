# Install Flow

This document maps the macOS DMG install path for FixOnce as implemented after Installer V2 hardening.

| Step | Trigger | Expected Artifact | Failure Modes | Recovery |
| --- | --- | --- | --- | --- |
| DMG open | User opens `FixOnce-Installer.dmg` | Mounted volume with `FixOnce Installer.app` | Damaged DMG, quarantine issues | Re-download DMG |
| Installer app launch | User opens `FixOnce Installer.app` | `/tmp/fixonce_install.log`, `~/.fixonce/install_state.json` with `NOT_INSTALLED` | App blocked by Gatekeeper | Surface macOS open failure |
| Preflight | Installer welcome continues | Selected Python path, writable home, free disk | No Python 3.10+, no write access, low disk | Installer stops before copy |
| Copy stage | `install_files()` | `~/FixOnce`, copied `src/`, `data/`, `scripts/`, project metadata | Partial copy, wrong bundle contents | Fail immediately with missing-file error |
| Dependency stage | `install_dependencies()` | `~/FixOnce/venv`, installed Python packages | `venv` creation fails, `pip install` fails | Abort install with actionable log path |
| AI tool config | `configure_mcp()` | Editor config updates where available | Missing editor CLIs, write failures | Continue install, keep logs |
| LaunchAgent create | `setup_launchagent()` | `~/Library/LaunchAgents/com.fixonce.server.plist`, `~/.fixonce/logs/server*.log` | Invalid plist, unwritable LaunchAgents dir | Recovery rewrites plist |
| First startup | `verify_and_enable_service()` attempt 1 | `launchctl bootstrap`, `kickstart`, `~/.fixonce/runtime.json`, live `/api/health` | `launchctl` load failure, stale lock/runtime, startup race | Clear stale state, inspect logs, retry |
| Recovery startup | `verify_and_enable_service()` attempt 2 | Rewritten plist, fresh runtime, live health endpoint | LaunchAgent still not loading, server exits early | Mark `FAILED`, keep logs, stop |
| Ready state | Runtime + health confirmed | `install_state.json` = `READY`, `config.json` with port, browser opened | Browser open fails | Install still succeeds; user can reopen later |

## State Transitions

`NOT_INSTALLED` -> `INSTALLING` -> `STARTING` -> `WAITING_HEALTH` -> `READY`

Recovery path:

`WAITING_HEALTH` -> `RECOVERY` -> `WAITING_HEALTH` -> `READY` or `FAILED`

## Current Source Of Truth

- Installer orchestration state: `~/.fixonce/install_state.json`
- Running server identity: `~/.fixonce/runtime.json`
- Effective "installed and usable" decision: explicit state machine resolution in `src/core/install_state_machine.py`
