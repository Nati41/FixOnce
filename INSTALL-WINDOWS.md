# FixOnce Windows Installation

This guide is for the public beta Windows installer.

## Download

Download the current Windows installer from GitHub Releases:

```text
FixOnce_Setup_1.0.13.exe
```

Release page:

```text
https://github.com/Nati41/FixOnce/releases
```

Direct installer URL:

```text
https://github.com/Nati41/FixOnce/releases/download/v1.0.13/FixOnce_Setup_1.0.13.exe
```

## Install

1. Download `FixOnce_Setup_1.0.13.exe`.
2. Run the installer.
3. Follow the installer prompts.
4. Open the FixOnce desktop app when installation finishes.
5. Open Claude, Codex, or Cursor from your project and continue work.

FixOnce restores the current project state before work continues, including relevant decisions, solved fixes, avoid patterns, and the next step.

## What Gets Installed

| Component | Purpose |
| --- | --- |
| FixOnce app | Runs the local desktop app and project memory service |
| MCP companion | Connects supported AI coding tools to project memory |
| Desktop app | Shows the active project, connected AI tool, current state, and saved memory |
| Local project memory | Stores project context on your machine and, where enabled, with the project |

## Supported AI Coding Tools

The beta is demonstrated with:

- Claude
- Codex
- Cursor

Support depends on each coding agent's local integration capabilities.

## After Installation

Use FixOnce from a real project folder:

1. Open your project.
2. Start Claude, Codex, or Cursor from that project.
3. Continue the task.

The connected AI tool should receive the current project context before work continues.

## Desktop App

Use the FixOnce desktop app to confirm the active project, connected AI tool, recent memories, saved decisions, solved fixes, and current handoff state.

## Uninstall

Use Windows Apps & Features / Installed Apps to uninstall FixOnce.

Uninstalling removes the app and integrations. Stored project memory is not sent anywhere. You can also delete local FixOnce data folders if you want to remove stored memory from the machine.

## Troubleshooting

If FixOnce does not appear connected:

1. Restart the AI coding tool.
2. Confirm you opened the AI tool from the intended project folder.
3. Open the FixOnce desktop app and check the active project and connection state.
4. Check the release page for the latest installer.

Issues:

```text
https://github.com/Nati41/FixOnce/issues
```
