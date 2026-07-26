# Windows Manual QA

## A. Cold Start

- Ensure no FixOnce server is running.
- Ensure no stale `FixOnce.exe` background process remains.
- Double-click `FixOnce.exe`.
- Expected result:
  - one native FixOnce window opens
  - no browser opens automatically
  - no `cmd` or PowerShell window appears
  - dashboard content loads normally

Pass criteria:

- app window opens without manual terminal use
- no browser auto-open
- no visible console window

## B. Warm Start

- Launch FixOnce once and wait for the server to become healthy.
- Close only the app window if possible, leaving the background server alive.
- Double-click `FixOnce.exe` again.
- Expected result:
  - launcher reuses existing server
  - native app opens quickly
  - no extra browser tab opens

Pass criteria:

- second launch succeeds without spawning a second broken server instance

## C. Browser Button

- Inside the app window, click `Open in Browser`.
- Expected result:
  - current dashboard opens in the browser on the active runtime port
  - app window remains usable

Pass criteria:

- browser opens only on button click
- dashboard URL resolves correctly

## D. Restart PC

- Reboot the Windows VM.
- Log back into the same user session.
- Expected result:
  - FixOnce does not auto-start at login
  - opening FixOnce manually starts or reuses the background server
  - no visible terminal window appears

Pass criteria:

- FixOnce app launch after reboot works without manual repair

## E. Login Autostart

- Open Task Scheduler and the per-user Startup folder.
- Expected result:
  - no `FixOnceServer` scheduled task is required for the public beta
  - no legacy `FixOnceServer.lnk` Startup shortcut remains
  - FixOnce starts cleanly when opened manually

Pass criteria:

- Windows login autostart remains disabled and manual launch works

## F. Failure Flow

- Break startup deliberately using the recovery plan.
- Launch `FixOnce.exe`.
- Expected result:
  - friendly failure window appears
  - Retry works when issue is transient
  - Repair attempts recovery
  - Diagnostics opens logs/support folder

Pass criteria:

- no raw Python traceback or terminal dependency is exposed to the user

## G. Uninstall

- Uninstall from Windows Apps & Features / Installed Apps.
- Expected result:
  - FixOnce background server stops
  - FixOnce-owned Claude Code, Codex, and Cursor MCP registrations are removed
  - unrelated MCP server entries remain
  - uninstall completes without leaving active FixOnce server process behind

Pass criteria:

- no active `FixOnce.exe --server` or matching Python server process remains
