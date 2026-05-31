# Windows Recovery Plan

## 1. Kill Background Server

Step:

- Start FixOnce successfully.
- Kill the background server process from Task Manager or PowerShell.
- Launch `FixOnce.exe` again.

Expected result:

- launcher detects missing healthy server
- launcher starts background server again
- native app opens

Pass criteria:

- relaunch succeeds without terminal or browser auto-open

## 2. Corrupt runtime.json

Step:

- Edit `%USERPROFILE%\.fixonce\runtime.json` and make it invalid JSON.
- Launch `FixOnce.exe`.

Expected result:

- launcher ignores invalid runtime state
- launcher falls back to health probing / restart path
- app still opens if recovery succeeds

Pass criteria:

- invalid runtime file does not hard-break startup

## 3. Occupied Port

Step:

- Bind another service to `5000` before launching FixOnce.
- Launch `FixOnce.exe`.

Expected result:

- FixOnce allocates another allowed port
- runtime/config reflect the chosen live port
- app opens normally

Pass criteria:

- FixOnce starts even when default port is unavailable

## 4. Delete config

Step:

- Remove `%USERPROFILE%\.fixonce\config.json`.
- Launch `FixOnce.exe`.

Expected result:

- launcher still discovers or starts the server
- new runtime/config state is regenerated as needed

Pass criteria:

- missing config does not block startup

## 5. Launcher Retry

Step:

- Induce a temporary startup issue, then resolve it.
- Click `Retry` in the failure window.

Expected result:

- launcher re-attempts startup
- app opens after issue is fixed

Pass criteria:

- Retry path works without restarting Windows

## 6. Diagnostics Flow

Step:

- Force startup failure.
- Open `Diagnostics` from the failure flow.

Expected result:

- logs folder opens
- user can inspect launcher/server logs without terminal usage

Pass criteria:

- diagnostics route is reachable and useful

## 7. Restart Recovery

Step:

- Start FixOnce.
- Reboot the machine.
- Launch the app after login.

Expected result:

- scheduled task or launcher recovery restores service availability
- app opens cleanly

Pass criteria:

- no manual Python/server command is required after reboot

## 8. Stale PID

Step:

- Leave a stale PID in `%USERPROFILE%\.fixonce\runtime.json` or `server.lock`.
- Ensure the referenced process is not actually running.
- Launch `FixOnce.exe`.

Expected result:

- launcher clears stale runtime/lock state
- fresh background server starts

Pass criteria:

- stale PID files do not permanently block startup

## 9. Orphan Process

Step:

- Create a situation where a FixOnce-related process remains but health endpoint is unavailable.
- Launch `FixOnce.exe`.

Expected result:

- launcher treats unhealthy state as failed startup
- retry or repair can recover

Pass criteria:

- unhealthy orphaned process does not trap the app in a false warm-start state
