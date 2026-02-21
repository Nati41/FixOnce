"""
Windows Bootstrap for FixOnce EXE
Handles first-run setup: AppData folder, extension deployment, etc.
"""

import os
import sys
import shutil
from pathlib import Path


def get_appdata_dir() -> Path:
    """Get the FixOnce data directory in AppData (Windows) or home (Mac/Linux)."""
    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
        return Path(appdata) / 'FixOnce'
    elif sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'FixOnce'
    else:
        return Path.home() / '.fixonce'


def get_bundled_dir() -> Path:
    """Get the directory where bundled files are (for PyInstaller)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled EXE
        return Path(sys._MEIPASS)
    else:
        # Running as script
        return Path(__file__).parent.parent


def ensure_appdata_setup() -> Path:
    """
    Ensure AppData directory exists and has required files.
    Returns the AppData path.
    """
    appdata_dir = get_appdata_dir()
    bundled_dir = get_bundled_dir()

    # Create main directory
    appdata_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    (appdata_dir / 'projects_v2').mkdir(exist_ok=True)
    (appdata_dir / 'global').mkdir(exist_ok=True)

    # Copy template files if they don't exist
    template_src = bundled_dir / 'data' / 'project_memory.template.json'
    template_dst = appdata_dir / 'project_memory.template.json'
    if template_src.exists() and not template_dst.exists():
        shutil.copy2(template_src, template_dst)

    # Copy dashboard files (always update to latest version)
    for dashboard in ['dashboard_vnext.html', 'dashboard_v3.html', 'logo.png']:
        src = bundled_dir / 'data' / dashboard
        dst = appdata_dir / dashboard
        if src.exists():
            shutil.copy2(src, dst)

    # Deploy extension to AppData
    extension_src = bundled_dir / 'extension'
    extension_dst = appdata_dir / 'extension'
    if extension_src.exists():
        if extension_dst.exists():
            shutil.rmtree(extension_dst)
        shutil.copytree(extension_src, extension_dst)

    # Create marker file for first-run detection
    marker = appdata_dir / '.fixonce_installed'
    first_run = not marker.exists()
    if first_run:
        marker.touch()
        print(f"FixOnce installed to: {appdata_dir}")
        print(f"Chrome Extension available at: {extension_dst}")

    return appdata_dir


def get_data_dir() -> Path:
    """
    Get the data directory to use.
    - For EXE: Use AppData
    - For development: Use local data/ folder
    """
    if getattr(sys, 'frozen', False):
        return ensure_appdata_setup()
    else:
        return Path(__file__).parent.parent / 'data'


def open_extension_folder():
    """Open the extension folder in file explorer."""
    import subprocess
    extension_dir = get_appdata_dir() / 'extension'

    if sys.platform == 'win32':
        os.startfile(str(extension_dir))
    elif sys.platform == 'darwin':
        subprocess.run(['open', str(extension_dir)])
    else:
        subprocess.run(['xdg-open', str(extension_dir)])


# Convenience exports
DATA_DIR = get_data_dir()
PROJECT_DIR = DATA_DIR / 'projects_v2'
