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
  - background server is available after login through scheduled task
  - no visible terminal window appears

Pass criteria:

- FixOnce app launch after reboot works without manual repair

## E. Scheduled Task

- Open Task Scheduler.
- Locate task `FixOnceServer`.
- Verify action target.
- Expected result:
  - task exists
  - target is valid for the installed build
  - packaged install should point to `FixOnce.exe --server`
  - dev fallback install may point to `pythonw ... scripts/app_launcher.py --server`

Pass criteria:

- task exists and target path is correct for the installation mode

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

- Run `uninstall.ps1`.
- Expected result:
  - FixOnce background server stops
  - scheduled task is removed
  - uninstall completes without leaving active FixOnce server process behind

Pass criteria:

- `FixOnceServer` task removed
- no active `FixOnce.exe --server` or matching Python server process remains
