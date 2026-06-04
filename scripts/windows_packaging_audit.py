#!/usr/bin/env python3
"""
Audit the Windows PyInstaller output before release.

The Windows package should contain install assets and runtime code only. User
state is created fresh under %USERPROFILE%\\.fixonce at runtime.
"""

from __future__ import annotations

import fnmatch
import struct
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKAGE_DIR = PROJECT_ROOT / "dist" / "FixOnce"
DEFAULT_REPORT = DEFAULT_PACKAGE_DIR / "packaging_audit.txt"

REQUIRED_ROOT_FILES = [
    "FixOnce.exe",
    "FixOnce.ico",
    "install.ps1",
    "uninstall.ps1",
    "install.bat",
    "requirements.txt",
]

REQUIRED_PACKAGE_METADATA = {
    "fastmcp metadata": [
        "fastmcp-*.dist-info/METADATA",
        "*/fastmcp-*.dist-info/METADATA",
    ],
}
REQUIRED_ICON_SIZES = {16, 32, 48, 256}

FORBIDDEN_PATTERNS = [
    ".git/*",
    ".codex/*",
    ".fixonce/*",
    "tests/*",
    "data/projects_v2/*",
    "*/data/projects_v2/*",
    "data/global/*.db",
    "*/data/global/*.db",
    "extension/store/*",
    "*/extension/store/*",
    "extension/package.sh",
    "*/extension/package.sh",
    "scripts/clean_for_test.sh",
    "*/scripts/clean_for_test.sh",
    "scripts/run_all_tests.py",
    "*/scripts/run_all_tests.py",
    "scripts/mcp_smoke_test.py",
    "*/scripts/mcp_smoke_test.py",
    "scripts/windows_build_check.py",
    "*/scripts/windows_build_check.py",
    "scripts/windows_packaging_audit.py",
    "*/scripts/windows_packaging_audit.py",
    "scripts/build_release.py",
    "*/scripts/build_release.py",
    "scripts/create_icons.py",
    "*/scripts/create_icons.py",
    "scripts/macos_app_launcher.c",
    "*/scripts/macos_app_launcher.c",
    "scripts/__pycache__/*",
    "*/scripts/__pycache__/*",
    "logs/*",
    "*/logs/*",
    ".DS_Store",
    "*/.DS_Store",
    "*.pyc",
    "*.pyo",
    "*.embeddings",
    "*backup*",
    "*.migrated",
]

FORBIDDEN_NAMES = {
    "active_project.json",
    "activity_log.json",
    "ai_connections.json",
    "boundary_state.json",
    "current_port.txt",
    "fixonce_enabled.json",
    "install_state.json",
    "mcp_compliance.json",
    "mcp_session.json",
    "personal_solutions.db",
    "project_index.json",
    "project_memory.json",
    "server.log",
    "session_registry.json",
    "system_mode.json",
    "test_error.html",
    "test_site.html",
    "dashboard_full_backup.html",
}

EXPECTED_EXCLUDED = [
    "data/projects_v2/",
    "data/global/*.db",
    "data/* runtime JSON state",
    "data/* logs",
    "data/* backups",
    "data/*.migrated",
    "data/test_error.html",
    "data/test_site.html",
    "tests/",
    ".git/",
    ".codex/",
    ".fixonce/",
    "extension/store/",
    "extension/package.sh",
    "developer-only scripts",
]


def relative_files(package_dir: Path) -> list[Path]:
    return sorted(
        path.relative_to(package_dir)
        for path in package_dir.rglob("*")
        if path.is_file() and path.name != "packaging_audit.txt"
    )


def package_size(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def is_forbidden(relative_path: Path) -> bool:
    normalized = relative_path.as_posix()
    if relative_path.name in FORBIDDEN_NAMES:
        return True
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in FORBIDDEN_PATTERNS)


def powershell_syntax_errors(script_path: Path) -> list[str]:
    powershell = shutil.which("powershell") or shutil.which("powershell.exe") or shutil.which("pwsh")
    if not powershell:
        return []

    literal_path = str(script_path).replace("'", "''")
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
    if result.returncode == 0:
        return []

    details = (result.stderr or result.stdout or "PowerShell parser failed").strip()
    return details.splitlines()


def ico_errors(icon_path: Path) -> list[str]:
    if not icon_path.exists():
        return [f"missing icon: {icon_path.name}"]

    data = icon_path.read_bytes()
    if len(data) < 6:
        return [f"{icon_path.name} is too small to be a valid ICO"]

    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or icon_type != 1 or count <= 0:
        return [f"{icon_path.name} has an invalid ICO header"]

    directory_size = 6 + (16 * count)
    if len(data) < directory_size:
        return [f"{icon_path.name} has a truncated ICO directory"]

    sizes = set()
    non_square = []
    for index in range(count):
        offset = 6 + (16 * index)
        width_raw, height_raw = struct.unpack_from("<BB", data, offset)
        width = 256 if width_raw == 0 else width_raw
        height = 256 if height_raw == 0 else height_raw
        sizes.add(width)
        if width != height:
            non_square.append(f"{width}x{height}")

    errors = []
    if non_square:
        errors.append(f"{icon_path.name} contains non-square sizes: {', '.join(non_square)}")

    missing_sizes = sorted(REQUIRED_ICON_SIZES - sizes)
    if missing_sizes:
        errors.append(f"{icon_path.name} missing required sizes: {', '.join(str(size) for size in missing_sizes)}")

    return errors


def write_report(
    package_dir: Path,
    report_path: Path,
    files: list[Path],
    forbidden: list[Path],
    missing_required: list[str],
    missing_metadata: list[str],
    syntax_errors: list[str],
    icon_errors: list[str],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "FixOnce Windows packaging audit",
        f"PACKAGE_DIR {package_dir}",
        f"FINAL_PACKAGE_SIZE {human_size(package_size(package_dir))}",
        "",
        "INCLUDED_FILES",
    ]
    lines.extend(f"INCLUDED {path.as_posix()}" for path in files)
    lines.extend(["", "EXCLUDED_FILES"])
    lines.extend(f"EXCLUDED {item}" for item in EXPECTED_EXCLUDED)
    lines.extend(["", "REQUIRED_ROOT_FILES"])
    for item in REQUIRED_ROOT_FILES:
        status = "MISSING" if item in missing_required else "PRESENT"
        lines.append(f"{status} {item}")
    lines.extend(["", "REQUIRED_PACKAGE_METADATA"])
    for item in REQUIRED_PACKAGE_METADATA:
        status = "MISSING" if item in missing_metadata else "PRESENT"
        lines.append(f"{status} {item}")
    lines.extend(["", "POWERSHELL_SYNTAX"])
    if syntax_errors:
        lines.append("INSTALL_PS1_SYNTAX_FAILED")
        lines.extend(f"SYNTAX_ERROR {line}" for line in syntax_errors)
    else:
        lines.append("INSTALL_PS1_SYNTAX_OK")
    lines.extend(["", "WINDOWS_ICON"])
    if icon_errors:
        lines.append("ICON_CHECK_FAILED")
        lines.extend(f"ICON_ERROR {line}" for line in icon_errors)
    else:
        lines.append("ICON_CHECK_OK")
    lines.extend(["", "FORBIDDEN_ARTIFACT_SCAN"])
    if forbidden or missing_required or missing_metadata or syntax_errors or icon_errors:
        lines.append("AUDIT_FAILED")
        lines.extend(f"MISSING_REQUIRED {item}" for item in missing_required)
        lines.extend(f"MISSING_METADATA {item}" for item in missing_metadata)
        lines.extend(f"SYNTAX_ERROR {line}" for line in syntax_errors)
        lines.extend(f"ICON_ERROR {line}" for line in icon_errors)
        lines.extend(f"FORBIDDEN {path.as_posix()}" for path in forbidden)
    else:
        lines.append("AUDIT_OK")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    package_dir = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_PACKAGE_DIR
    report_path = Path(argv[2]).resolve() if len(argv) > 2 else DEFAULT_REPORT

    if not package_dir.exists():
        print(f"FAIL: package directory does not exist: {package_dir}")
        return 1

    files = relative_files(package_dir)
    forbidden = [path for path in files if is_forbidden(path)]
    file_names = {path.as_posix() for path in files}
    missing_required = [item for item in REQUIRED_ROOT_FILES if item not in file_names]
    missing_metadata = [
        name
        for name, patterns in REQUIRED_PACKAGE_METADATA.items()
        if not any(fnmatch.fnmatch(file_name, pattern) for pattern in patterns for file_name in file_names)
    ]
    syntax_errors = []
    install_script = package_dir / "install.ps1"
    if install_script.exists():
        syntax_errors = powershell_syntax_errors(install_script)
    icon_errors = ico_errors(package_dir / "FixOnce.ico")
    write_report(package_dir, report_path, files, forbidden, missing_required, missing_metadata, syntax_errors, icon_errors)

    print(f"Audit report: {report_path}")
    print(f"Included files: {len(files)}")
    print(f"Final package size: {human_size(package_size(package_dir))}")
    if missing_required:
        print("Required root files missing:")
        for item in missing_required:
            print(f"  {item}")
    if missing_metadata:
        print("Required package metadata missing:")
        for item in missing_metadata:
            print(f"  {item}")
    if forbidden:
        print("Forbidden artifacts found:")
        for path in forbidden:
            print(f"  {path.as_posix()}")
    if syntax_errors:
        print("install.ps1 PowerShell syntax errors:")
        for line in syntax_errors:
            print(f"  {line}")
    if icon_errors:
        print("Windows icon errors:")
        for line in icon_errors:
            print(f"  {line}")
    if missing_required or missing_metadata or forbidden or syntax_errors or icon_errors:
        return 1

    print("Forbidden artifact scan: AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
