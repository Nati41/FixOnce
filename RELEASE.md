# FixOnce Release Notes

Current beta: `v1.0.13`

## Public Release Assets

The public beta release should publish these installer assets on GitHub Releases:

- Windows: `FixOnce_Setup_1.0.13.exe`
- macOS: `FixOnce-mac.dmg`

Release page:

```text
https://github.com/Nati41/FixOnce/releases
```

Expected direct URLs:

```text
https://github.com/Nati41/FixOnce/releases/download/v1.0.13/FixOnce_Setup_1.0.13.exe
https://github.com/Nati41/FixOnce/releases/download/v1.0.13/FixOnce-mac.dmg
```

## Release Source Of Truth

- Public landing page source: `website/`
- GitHub Pages source: `docs/`
- Windows installer config: `installer/fixonce_setup.iss`
- macOS installer script: `installer/macos/build_installer.sh`

The website download buttons should point to GitHub Release assets, not local `website/downloads/` files.

## Public Beta Verification

Before publishing the beta:

1. Confirm `https://nati41.github.io/FixOnce/` serves the current landing page.
2. Confirm the Windows installer URL returns the real `FixOnce_Setup_1.0.13.exe` asset.
3. Confirm the macOS installer URL returns the real `FixOnce-mac.dmg` asset.
4. Install FixOnce on a clean machine or VM.
5. Open Claude, Codex, or Cursor from a real project folder.
6. Confirm FixOnce restores the current project state before work continues.
7. Confirm the desktop app shows the active project, connected AI tool, current project state, and recent memories accurately.

## Product Positioning

FixOnce beta is positioned as:

```text
One developer. Multiple AI agents. One project memory.
```

Do not publish release copy that depends on a specific prompt phrase or an old ZIP/script install flow.
