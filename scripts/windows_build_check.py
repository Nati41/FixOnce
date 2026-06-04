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
INNO_SETUP = PROJECT_ROOT / "installer" / "fixonce_setup.iss"
PACKAGING_AUDIT = PROJECT_ROOT / "scripts" / "windows_packaging_audit.py"
RUNTIME_OUTPUT_CHECK = PROJECT_ROOT / "scripts" / "windows_runtime_output_check.py"
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

    literal_path = str(path).replace("'", "''")
    command = (
        "$null = [scriptblock]::Create("
        f"(Get-Content -Raw -LiteralPath '{literal_path}')"
        "); 'install.ps1 syntax OK'"
    )
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
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
    check(RUNTIME_OUTPUT_CHECK.exists(), "runtime output check", str(RUNTIME_OUTPUT_CHECK), failures)
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
    check('copy_metadata("fastmcp")' in spec_text, "fastmcp package metadata", "metadata copied for importlib.metadata", failures)
    check("copy /Y install.ps1 dist\\FixOnce\\install.ps1" in build_text, "install.ps1 package root", "copied after PyInstaller", failures)
    check("copy /Y uninstall.ps1 dist\\FixOnce\\uninstall.ps1" in build_text, "uninstall.ps1 package root", "copied after PyInstaller", failures)
    check("copy /Y install.bat dist\\FixOnce\\install.bat" in build_text, "install.bat package root", "copied after PyInstaller", failures)
    check("copy /Y requirements.txt dist\\FixOnce\\requirements.txt" in build_text, "requirements.txt package root", "copied after PyInstaller", failures)
    check("[scriptblock]::Create((Get-Content -Raw install.ps1))" in build_text, "install.ps1 build syntax gate", "build_windows.bat parses installer before packaging", failures)
    check("scripts\\windows_runtime_output_check.py" in build_text, "runtime output build gate", "blocks unsafe Flask/API output before packaging", failures)

    required_hidden_imports = [
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
        "webview.platforms.winforms",
        "core.agent_mcp_registration",
        "core.mcp_config",
        "mcp_server.mcp_memory_server_v2",
    ]
    hidden_ok = all(module in spec_text for module in required_hidden_imports)
    check(hidden_ok, "required hidden imports", ", ".join(required_hidden_imports), failures)

    check("--server" in launcher_text, "launcher server mode", "app launcher exposes packaged --server dispatch", failures)
    check("--bootstrap" in launcher_text, "launcher bootstrap mode", "app launcher exposes packaged --bootstrap dispatch", failures)
    check(
        "MCP_STARTUP_LOG" in launcher_text
        and "--mcp startup started" in launcher_text
        and "--mcp entering mcp_server.mcp_memory_server_v2" in launcher_text,
        "launcher MCP startup diagnostics",
        "FixOnce.exe --mcp logs startup before importing the MCP server module",
        failures,
    )
    check("bootstrap.log" in launcher_text, "bootstrap log file", "bootstrap steps logged to ~/.fixonce/logs/bootstrap.log", failures)
    check(
        "MCP registration started" in launcher_text
        and "MCP registration Codex config path" in launcher_text
        and "MCP registration installed exe path" in launcher_text
        and "MCP registration result" in launcher_text,
        "bootstrap MCP diagnostics",
        "bootstrap logs registration start, paths, installed exe, and result",
        failures,
    )
    check(
        "configure_windows_autostart" in launcher_text and "startup_shortcut" in launcher_text,
        "bootstrap startup fallback",
        "tiered autostart includes Startup folder shortcut fallback",
        failures,
    )
    check(
        "FixOnceServer.lnk" in launcher_text,
        "bootstrap startup shortcut name",
        "Startup shortcut uses FixOnceServer.lnk",
        failures,
    )
    check("FixOnce could not open its app window." in launcher_text, "friendly startup failure", "friendly error path present", failures)

    if INNO_SETUP.exists():
        inno_text = read_text(INNO_SETUP)
        inno_flat = inno_text.replace("\r", "").replace("\n", " ")
        check('Parameters: "--bootstrap"' in inno_text, "inno bootstrap run", "installer runs FixOnce.exe --bootstrap", failures)
        check(
            "waituntilterminated" in inno_flat,
            "inno bootstrap wait",
            "installer waits for bootstrap to finish",
            failures,
        )
        check("--minimized" not in inno_text, "inno no minimized autostart", "HKCU Run --minimized removed", failures)
        check("dontcreatekey" in inno_text, "inno legacy run cleanup", "legacy HKCU Run key uses dontcreatekey", failures)
        bootstrap_run_line = next((line for line in inno_text.splitlines() if "--bootstrap" in line and "[Run]" not in line), "")
        check(
            "nowait" not in bootstrap_run_line.lower(),
            "inno bootstrap not fire-and-forget",
            "bootstrap [Run] entry does not use nowait",
            failures,
        )
        check(
            "postinstall" not in bootstrap_run_line.lower(),
            "inno bootstrap mandatory",
            "bootstrap [Run] entry is not an optional postinstall checkbox",
            failures,
        )
        check(
            "ssDone" in inno_text and "FixOnce is ready" in inno_text,
            "inno success after bootstrap",
            "success message shown on ssDone after bootstrap [Run]",
            failures,
        )
        check(
            "installed successfully" not in inno_text.lower() or "ssDone" in inno_text,
            "inno no early success dialog",
            "success is not announced before bootstrap completes",
            failures,
        )
    else:
        check(False, "fixonce_setup.iss", str(INNO_SETUP), failures)

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
