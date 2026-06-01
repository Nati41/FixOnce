#!/usr/bin/env python3
"""
Pre-build validation for the Windows FixOnce package.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = PROJECT_ROOT / "fixonce.spec"
BUILD_SCRIPT = PROJECT_ROOT / "build_windows.bat"
APP_LAUNCHER = PROJECT_ROOT / "scripts" / "app_launcher.py"
INSTALL_SCRIPT = PROJECT_ROOT / "install.ps1"
PACKAGING_AUDIT = PROJECT_ROOT / "scripts" / "windows_packaging_audit.py"
DASHBOARD_HTML = PROJECT_ROOT / "data" / "dashboard.html"
SERVER_SCRIPT = PROJECT_ROOT / "src" / "server.py"
BUILD_DIRS = [
    PROJECT_ROOT / "build",
    PROJECT_ROOT / "dist",
]
USER_RUNTIME_DIRS = [
    Path.home() / ".fixonce",
    Path.home() / ".fixonce" / "logs",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check(condition: bool, label: str, detail: str, failures: list[str]):
    status = "PASS" if condition else "FAIL"
    print(f"{status}  {label}: {detail}")
    if not condition:
        failures.append(label)


def import_exists(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".fixonce_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def is_ascii(path: Path) -> bool:
    try:
        path.read_text(encoding="ascii")
        return True
    except UnicodeDecodeError:
        return False


def powershell_syntax_ok(path: Path) -> bool:
    powershell = shutil.which("powershell") or shutil.which("powershell.exe") or shutil.which("pwsh")
    if not powershell:
        return True

    command = "$null = [scriptblock]::Create((Get-Content -Raw $args[0])); 'install.ps1 syntax OK'"
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        if details:
            print(details)
    return result.returncode == 0


def main() -> int:
    failures: list[str] = []

    if not SPEC_PATH.exists():
        print("FAIL  fixonce.spec: file missing")
        return 1

    spec_text = read_text(SPEC_PATH)
    build_text = read_text(BUILD_SCRIPT) if BUILD_SCRIPT.exists() else ""
    launcher_text = read_text(APP_LAUNCHER) if APP_LAUNCHER.exists() else ""

    print("FixOnce Windows Build Check")
    print("==========================")

    check(APP_LAUNCHER.exists(), "app_launcher.py", str(APP_LAUNCHER), failures)
    check(BUILD_SCRIPT.exists(), "build_windows.bat", str(BUILD_SCRIPT), failures)
    check(INSTALL_SCRIPT.exists(), "install.ps1", str(INSTALL_SCRIPT), failures)
    check(is_ascii(INSTALL_SCRIPT), "install.ps1 ASCII", "safe for Windows PowerShell 5.1 legacy decoding", failures)
    check(powershell_syntax_ok(INSTALL_SCRIPT), "install.ps1 syntax", "PowerShell parser accepts script when PowerShell is available", failures)
    check(PACKAGING_AUDIT.exists(), "packaging audit", str(PACKAGING_AUDIT), failures)
    check(DASHBOARD_HTML.exists(), "dashboard.html", str(DASHBOARD_HTML), failures)
    check(SERVER_SCRIPT.exists(), "server.py", str(SERVER_SCRIPT), failures)
    check(import_exists("PyInstaller"), "PyInstaller", "importable in current Python", failures)
    check(import_exists("webview"), "pywebview", "importable in current Python", failures)

    check('scripts" / "app_launcher.py' in spec_text, "spec entrypoint", "uses scripts/app_launcher.py", failures)
    check("console=False" in spec_text, "spec console mode", "windowed EXE configured", failures)
    check("data/dashboard.html" in spec_text, "dashboard asset", "dashboard packaged", failures)
    check("data/test_error.html" not in spec_text, "test pages excluded", "test_error.html not packaged", failures)
    check('"extension"), "extension"' not in spec_text, "extension allowlist", "no whole extension directory", failures)
    check('"server"' in spec_text, "server hidden import", "internal server import declared", failures)
    check("copy /Y install.ps1 dist\\FixOnce\\install.ps1" in build_text, "install.ps1 package root", "copied after PyInstaller", failures)
    check("copy /Y uninstall.ps1 dist\\FixOnce\\uninstall.ps1" in build_text, "uninstall.ps1 package root", "copied after PyInstaller", failures)
    check("copy /Y install.bat dist\\FixOnce\\install.bat" in build_text, "install.bat package root", "copied after PyInstaller", failures)
    check("copy /Y requirements.txt dist\\FixOnce\\requirements.txt" in build_text, "requirements.txt package root", "copied after PyInstaller", failures)
    check("[scriptblock]::Create((Get-Content -Raw install.ps1))" in build_text, "install.ps1 build syntax gate", "build_windows.bat parses installer before packaging", failures)

    required_hidden_imports = [
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
        "webview.platforms.winforms",
    ]
    hidden_ok = all(module in spec_text for module in required_hidden_imports)
    check(hidden_ok, "pywebview hidden imports", ", ".join(required_hidden_imports), failures)

    check("--server" in launcher_text, "launcher server mode", "app launcher exposes packaged --server dispatch", failures)
    check("FixOnce could not open its app window." in launcher_text, "friendly startup failure", "friendly error path present", failures)

    for build_dir in BUILD_DIRS:
        check(dir_writable(build_dir), f"build dir writable", str(build_dir), failures)

    for runtime_dir in USER_RUNTIME_DIRS:
        check(dir_writable(runtime_dir), f"runtime dir writable", str(runtime_dir), failures)

    print("--------------------------")
    if failures:
        print(f"FAIL SUMMARY: {len(failures)} issue(s): {', '.join(failures)}")
        return 1

    print("PASS SUMMARY: Windows build prerequisites look ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
