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

Canonical download location:

```text
https://github.com/Nati41/FixOnce/releases
```

## Release Source Of Truth

- GitHub Pages source: `docs/`
- Mirrored landing page copy: `website/`
- Windows installer config: `installer/fixonce_setup.iss`
- macOS installer script: `installer/macos/build_installer.sh`

`docs/` is the public GitHub Pages source. Keep `website/` byte-for-byte aligned while it remains in the repository; do not edit only one copy.

The website download buttons should point to GitHub Release assets, not local `website/downloads/` files. If final RC asset URLs are not live yet, point public copy to the GitHub Releases page instead of a non-existent direct asset.

## Public Beta Verification

Before publishing the beta:

1. Confirm `https://nati41.github.io/FixOnce/` serves the current landing page.
2. Confirm the Windows installer URL returns the real `FixOnce_Setup_1.0.13.exe` asset.
3. Confirm the macOS installer URL returns the real `FixOnce-mac.dmg` asset.
4. Install FixOnce on a clean machine or VM.
5. Open Claude Code, Codex, or Cursor from a real project folder.
6. Confirm FixOnce restores the current project state before work continues.
7. Confirm the desktop app shows the active project, connected AI tool, current project state, and recent memories accurately.
8. On Windows, confirm SmartScreen copy is expected for unsigned beta builds.
9. On macOS, confirm Gatekeeper copy is expected for non-notarized beta builds.

## Public Beta Support Matrix

Public beta support is demonstrated with:

- Claude Code
- Codex
- Cursor

Other AI coding tools may have integration work in the repository, but they should not be presented as public beta supported until they pass clean-machine QA.

## Product Positioning

FixOnce beta is positioned as:

```text
One developer. Multiple AI agents. One project memory.
```

Do not publish release copy that depends on a specific prompt phrase or an old ZIP/script install flow.
