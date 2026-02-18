# FixOnce v1.0 Clean Release

## Build artifacts

Run:

```bash
python3 scripts/build_release.py --version 1.0.0
```

Artifacts are created in:

- `dist/FixOnce-v1.0.0/FixOnce-macOS-v1.0.0.zip`
- `dist/FixOnce-v1.0.0/FixOnce-Windows-v1.0.0.zip`
- `dist/FixOnce-v1.0.0/checksums.sha256`

## Install in 5 steps

1. Download and extract the platform zip.
2. Run installer:
   - macOS: `./install.sh` (or `install.command`)
   - Windows: `install.ps1` (or `install.bat`)
3. Open `http://localhost:5000`.
4. Restart your editor (Cursor/Claude) so MCP config reloads.
5. Send `היי` and verify project context appears.

## Smoke test

Use `release/SMOKE_TEST.md` inside each built zip and mark PASS/FAIL before publishing.

