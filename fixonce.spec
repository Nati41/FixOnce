# -*- mode: python ; coding: utf-8 -*-
"""
FixOnce PyInstaller Spec File
Builds a standalone Windows EXE with all dependencies bundled.

Usage:
    pyinstaller fixonce.spec

Output:
    dist/FixOnce/FixOnce.exe (one-folder mode)
    or dist/FixOnce.exe (one-file mode, slower startup)
"""

import os
import sys
from pathlib import Path

# Get the project root
PROJECT_ROOT = Path(SPECPATH)

# Collect all data files
datas = [
    # Dashboard HTML files
    (str(PROJECT_ROOT / 'data' / 'dashboard_vnext.html'), 'data'),
    (str(PROJECT_ROOT / 'data' / 'dashboard_v3.html'), 'data'),
    (str(PROJECT_ROOT / 'data' / 'logo.png'), 'data'),

    # Template JSON files (initial state)
    (str(PROJECT_ROOT / 'data' / 'project_memory.template.json'), 'data'),

    # Chrome Extension (will be copied to AppData on first run)
    (str(PROJECT_ROOT / 'extension'), 'extension'),

    # Assets
    (str(PROJECT_ROOT / 'assets'), 'assets'),
]

# Hidden imports that PyInstaller might miss
hiddenimports = [
    # Flask ecosystem
    'flask',
    'flask_cors',
    'werkzeug',
    'jinja2',
    'markupsafe',
    'itsdangerous',
    'click',

    # MCP
    'fastmcp',
    'mcp',

    # Embeddings (heavy!)
    'fastembed',
    'onnxruntime',
    'onnx',

    # ML/Search
    'sklearn',
    'sklearn.metrics',
    'sklearn.metrics.pairwise',
    'numpy',

    # File watching
    'watchdog',
    'watchdog.observers',
    'watchdog.events',

    # Standard lib that might be missed
    'json',
    'sqlite3',
    'threading',
    'socket',
    'pathlib',

    # FixOnce internal modules
    'src.config',
    'src.windows_bootstrap',
    'src.core',
    'src.core.db_solutions',
    'src.core.error_store',
    'src.core.embeddings',
    'src.core.embeddings.fastembed_provider',
    'src.core.embeddings.provider',
    'src.api',
    'src.managers',
    'src.mcp_server',
    'src.mcp_server.mcp_memory_server_v2',
    'src.file_watcher',

    # Also try without src. prefix (PyInstaller path handling)
    'config',
    'windows_bootstrap',
    'core',
    'api',
    'managers',
    'mcp_server',
]

# Exclude unnecessary packages to reduce size
excludes = [
    'tkinter',
    'matplotlib',
    'PIL',
    'pandas',
    'scipy',  # fastembed might pull this, but we can try without
    'torch',  # We use ONNX, not PyTorch
    'tensorflow',
    'keras',
]

# Analysis
a = Analysis(
    [str(PROJECT_ROOT / 'src' / 'server.py')],
    pathex=[str(PROJECT_ROOT), str(PROJECT_ROOT / 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Remove duplicate files
pyz = PYZ(a.pure)

# ============================================================================
# ONE-FOLDER MODE (Recommended for development/testing)
# Faster startup, easier to debug, larger folder size
# ============================================================================
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # One-folder mode
    name='FixOnce',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Compress binaries
    console=True,  # Set to False for GUI-only (no terminal window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / 'FixOnce.ico'),  # Windows icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FixOnce',
)

# ============================================================================
# ONE-FILE MODE (Uncomment below, comment above COLLECT block)
# Single EXE, slower startup (extracts to temp), easier distribution
# ============================================================================
# exe = EXE(
#     pyz,
#     a.scripts,
#     a.binaries,
#     a.datas,
#     [],
#     name='FixOnce',
#     debug=False,
#     bootloader_ignore_signals=False,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     runtime_tmpdir=None,
#     console=True,
#     disable_windowed_traceback=False,
#     argv_emulation=False,
#     target_arch=None,
#     codesign_identity=None,
#     entitlements_file=None,
#     icon=str(PROJECT_ROOT / 'FixOnce.ico'),
# )
