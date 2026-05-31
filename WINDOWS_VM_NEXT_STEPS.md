# Windows VM Next Steps

1. Build EXE

- Run:

```bat
python scripts\windows_build_check.py
build_windows.bat
```

- Confirm `dist\FixOnce\FixOnce.exe` exists.

2. Cold Launch

- Ensure no FixOnce server is running.
- Double-click `FixOnce.exe`.
- Confirm one native app window opens.
- Confirm no browser auto-open and no terminal window.

3. Warm Launch

- Leave background server alive.
- Launch `FixOnce.exe` again.
- Confirm server reuse and clean second app open.

4. Reboot

- Restart the Windows VM.
- Log back in.

5. Autostart

- Verify `FixOnceServer` scheduled task exists.
- Verify the task target is valid.
- Confirm launch after reboot works without manual Python commands.

6. Uninstall

- Run `uninstall.ps1`.
- Confirm scheduled task removal.
- Confirm background server process stops.

7. Crash Tests

- Execute the scenarios in `tests/windows_recovery_plan.md`.
- Validate Retry / Repair / Diagnostics behavior.

8. Final Release Verdict

- Mark release candidate ready only if:
  - build succeeds
  - cold start passes
  - warm start passes
  - no terminal window appears
  - `Open in Browser` works from inside app
  - reboot/autostart passes
  - uninstall passes
  - recovery scenarios pass at acceptable rate
