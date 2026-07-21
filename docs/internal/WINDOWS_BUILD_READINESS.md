# Windows Build Readiness

## Build Command

Primary build command:

```bat
build_windows.bat
```

Equivalent direct command:

```bat
python -m PyInstaller fixonce.spec --clean
```

## Expected Artifacts

Primary artifact:

- `dist\FixOnce\FixOnce.exe`

Expected one-folder layout:

- `dist\FixOnce\FixOnce.exe`
- `dist\FixOnce\_internal\...` or PyInstaller support files, depending on build environment
- packaged `data\` files bundled through `fixonce.spec`
- packaged `extension\` directory
- packaged `assets\` directory

Runtime contract:

- user entrypoint is `FixOnce.exe`
- packaged EXE entry script is `scripts/app_launcher.py`
- background server in packaged mode is launched through `FixOnce.exe --server`

## Risks

- `pywebview` may require a Windows runtime backend such as WebView2 / Edge WebView support on the VM.
- `fastembed` and `onnxruntime` are heavy dependencies and may extend build time or fail if wheel resolution differs on Windows.
- `assets/FixOnce.ico` must exist for branded Windows output and is copied to `dist/FixOnce/FixOnce.ico`.
- PyInstaller hidden-import drift is possible if `pywebview` changes its internal module layout.
- Actual packaged import resolution for `server`, `config`, and internal modules still requires a real Windows build test.
- Scheduled Task behavior must be validated on a real Windows user session after reboot.

## Missing Deps

Build-time prerequisites:

- Python 3.9+
- `pip`
- `PyInstaller`
- packages from `requirements.txt`
- `fastembed`
- `onnxruntime`

Runtime prerequisites to validate on Windows VM:

- `pywebview` backend compatibility
- WebView2 / supported embedded webview runtime

## Packaged Files List

The current `fixonce.spec` explicitly packages:

### App Entry

- `scripts/app_launcher.py`

### Dashboard / Static Assets

- `data/dashboard.html`
- `data/dashboard_app.html`
- `data/installer.html`
- `data/privacy.html`
- `data/terms.html`
- `data/security.html`
- `data/test_error.html`
- `data/logo.png`
- `data/app-icon.png`
- `data/fixonce_logo.svg`

### Template / Initialization Files

- `data/project_memory.template.json`
- `data/active_project.template.json`
- `data/activity_log.template.json`
- `data/session_registry.template.json`
- `data/global-claude-md.md`
- `data/global-cursor-rules.md`
- `data/global-agent-rules.md`

### Bundled Directories

- `extension/`
- `assets/`

### Hidden Imports Relevant to Windows Packaging

- `server`
- `config`
- `windows_bootstrap`
- `core`
- `api`
- `managers`
- `mcp_server`
- `webview`
- `webview.guilib`
- `webview.util`
- `webview.platforms`
- `webview.platforms.edgechromium`
- `webview.platforms.mshtml`
- `webview.platforms.winforms`

## Current Readiness Verdict

Status: ready for first real Windows build attempt.

What is ready:

- EXE entrypoint points to launcher, not `server.py`
- console window is disabled in packaging
- launcher has `--server` dispatch for packaged warm/cold start behavior
- Windows install flow no longer auto-opens browser
- build script and spec are aligned

What still requires Windows validation:

- actual PyInstaller output
- native window startup
- no-terminal behavior
- scheduled task after reboot
- recovery flow in packaged mode
