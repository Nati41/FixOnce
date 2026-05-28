# -*- mode: python ; coding: utf-8 -*-
"""
FixOnce PyInstaller Spec File
Builds the Windows app starting from the end-user launcher.

Usage:
    pyinstaller fixonce.spec

Output:
    dist/FixOnce/FixOnce.exe
"""

from pathlib import Path


PROJECT_ROOT = Path(SPECPATH)


def data_entry(relative_path: str):
    path = PROJECT_ROOT / relative_path
    return (str(path), str(Path(relative_path).parent))


datas = [
    data_entry("data/dashboard.html"),
    data_entry("data/dashboard_app.html"),
    data_entry("data/installer.html"),
    data_entry("data/privacy.html"),
    data_entry("data/terms.html"),
    data_entry("data/security.html"),
    data_entry("data/test_error.html"),
    data_entry("data/logo.png"),
    data_entry("data/app-icon.png"),
    data_entry("data/fixonce_logo.svg"),
    data_entry("data/project_memory.template.json"),
    data_entry("data/active_project.template.json"),
    data_entry("data/activity_log.template.json"),
    data_entry("data/session_registry.template.json"),
    data_entry("data/global-claude-md.md"),
    data_entry("data/global-cursor-rules.md"),
    data_entry("data/global-agent-rules.md"),
    (str(PROJECT_ROOT / "extension"), "extension"),
    (str(PROJECT_ROOT / "assets"), "assets"),
]


hiddenimports = [
    "flask",
    "flask_cors",
    "werkzeug",
    "jinja2",
    "markupsafe",
    "itsdangerous",
    "click",
    "waitress",
    "fastmcp",
    "mcp",
    "fastembed",
    "onnxruntime",
    "onnx",
    "sklearn",
    "sklearn.metrics",
    "sklearn.metrics.pairwise",
    "numpy",
    "watchdog",
    "watchdog.observers",
    "watchdog.events",
    "webview",
    "webview.guilib",
    "webview.util",
    "webview.platforms",
    "webview.platforms.edgechromium",
    "webview.platforms.mshtml",
    "webview.platforms.winforms",
    "json",
    "sqlite3",
    "threading",
    "socket",
    "pathlib",
    "server",
    "config",
    "windows_bootstrap",
    "core",
    "api",
    "managers",
    "mcp_server",
]


excludes = [
    "matplotlib",
    "PIL",
    "pandas",
    "scipy",
    "torch",
    "tensorflow",
    "keras",
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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "FixOnce.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FixOnce",
)
