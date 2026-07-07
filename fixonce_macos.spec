# -*- mode: python ; coding: utf-8 -*-
"""
FixOnce PyInstaller Spec File (macOS)
Builds the macOS app bundle for distribution.

Usage:
    pyinstaller fixonce_macos.spec

Output:
    dist/FixOnce.app
"""

from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata


PROJECT_ROOT = Path(SPECPATH)


def data_entry(relative_path, target_root=None):
    path = PROJECT_ROOT / relative_path
    target = Path(relative_path).parent if target_root is None else Path(target_root) / Path(relative_path).parent.name
    return (str(path), str(target))


DATA_ALLOWLIST = [
    "data/dashboard.html",
    "data/dashboard_app.html",
    "data/dashboard_minimal.html",
    "data/installer.html",
    "data/privacy.html",
    "data/terms.html",
    "data/security.html",
    "data/logo.png",
    "data/app-icon.png",
    "data/fixonce_logo.svg",
    "data/project_memory.template.json",
    "data/active_project.template.json",
    "data/activity_log.template.json",
    "data/session_registry.template.json",
    "data/global-claude-md.md",
    "data/global-cursor-rules.md",
    "data/global-agent-rules.md",
]

EXTENSION_ALLOWLIST = [
    "extension/manifest.json",
    "extension/background.js",
    "extension/bridge.js",
    "extension/content.js",
    "extension/element-picker.js",
    "extension/icon128.png",
    "extension/icon16.png",
    "extension/icon48.png",
    "extension/injected.js",
    "extension/logger.js",
    "extension/picker-bridge.js",
    "extension/popup.html",
    "extension/popup.js",
]

ASSET_ALLOWLIST = [
    "assets/FixOnce.icns",
    "assets/FixOnce.png",
    "assets/logo.svg",
    "assets/menubar/icon_18x18.png",
    "assets/menubar/icon_18x18@2x.png",
    "assets/menubar/icon_18x18@2x_template.png",
]

HOOK_ALLOWLIST = [
    "hooks/session_start.sh",
    "hooks/session_end.sh",
    "hooks/post_tool_use.sh",
]

SCRIPTS_ALLOWLIST = [
    "scripts/menubar_app.py",
    "scripts/install.py",
    "scripts/semantic_setup.py",
]


def existing_entries(paths):
    entries = []
    for relative_path in paths:
        path = PROJECT_ROOT / relative_path
        if path.exists():
            entries.append(data_entry(relative_path))
    return entries


def tree_entries(root_relative_path, excluded_dirs=()):
    root = PROJECT_ROOT / root_relative_path
    entries = []
    if not root.exists():
        return entries

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(PROJECT_ROOT)
        parts = set(relative.parts)
        if "__pycache__" in parts or any(excluded in parts for excluded in excluded_dirs):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        entries.append((str(path), str(relative.parent)))
    return entries


datas = (
    existing_entries(DATA_ALLOWLIST)
    + existing_entries(EXTENSION_ALLOWLIST)
    + existing_entries(ASSET_ALLOWLIST)
    + existing_entries(HOOK_ALLOWLIST)
    + existing_entries(SCRIPTS_ALLOWLIST)
    + tree_entries("src", excluded_dirs=(".fixonce",))
    + copy_metadata("fastmcp")
)


# macOS-specific hidden imports
hiddenimports = [
    # Flask/web
    "flask",
    "flask_cors",
    "werkzeug",
    "jinja2",
    "markupsafe",
    "itsdangerous",
    "click",
    # macOS menu bar
    "rumps",
    "PyObjCTools",
    "PyObjCTools.AppHelper",
    "objc",
    "AppKit",
    "Foundation",
    # MCP/AI
    "fastmcp",
    "mcp",
    # ML/embeddings
    "fastembed",
    "onnxruntime",
    "onnx",
    "sklearn",
    "sklearn.metrics",
    "sklearn.metrics.pairwise",
    "numpy",
    # File watching
    "watchdog",
    "watchdog.observers",
    "watchdog.events",
    # Standard library
    "json",
    "sqlite3",
    "threading",
    "socket",
    "pathlib",
    # FixOnce modules
    "server",
    "config",
    "core",
    "core.agent_mcp_registration",
    "core.mcp_config",
    "core.lifecycle",
    "api",
    "managers",
    "mcp_server",
    "mcp_server.mcp_memory_server_v2",
]


excludes = [
    "matplotlib",
    "PIL",
    "pandas",
    "scipy",
    "torch",
    "tensorflow",
    "keras",
    # Windows-specific
    "webview",
    "pywin32",
    "win32api",
    "win32con",
    "pystray",
]


a = Analysis(
    [str(PROJECT_ROOT / "scripts" / "app_launcher.py")],
    pathex=[str(PROJECT_ROOT), str(PROJECT_ROOT / "src"), str(PROJECT_ROOT / "scripts")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FixOnce",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX not commonly used on macOS
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FixOnce",
)

# macOS app bundle
app = BUNDLE(
    coll,
    name="FixOnce.app",
    icon=str(PROJECT_ROOT / "assets" / "FixOnce.icns"),
    bundle_identifier="com.fixonce.app",
    info_plist={
        "CFBundleName": "FixOnce",
        "CFBundleDisplayName": "FixOnce",
        "CFBundleIdentifier": "com.fixonce.app",
        "CFBundleVersion": "1.0.13",
        "CFBundleShortVersionString": "1.0.13",
        "CFBundleExecutable": "FixOnce",
        "CFBundleIconFile": "FixOnce.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleSupportedPlatforms": ["MacOSX"],
        "LSMinimumSystemVersion": "10.13",
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "LSUIElement": False,  # Show in Dock when running
        "LSApplicationCategoryType": "public.app-category.developer-tools",
    },
)
