#!/usr/bin/env python3
"""
Audit the Windows PyInstaller output before release.

The Windows package should contain install assets and runtime code only. User
state is created fresh under %USERPROFILE%\\.fixonce at runtime.
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKAGE_DIR = PROJECT_ROOT / "dist" / "FixOnce"
DEFAULT_REPORT = DEFAULT_PACKAGE_DIR / "packaging_audit.txt"

REQUIRED_ROOT_FILES = [
    "FixOnce.exe",
    "install.ps1",
    "uninstall.ps1",
    "install.bat",
]

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


def write_report(
    package_dir: Path,
    report_path: Path,
    files: list[Path],
    forbidden: list[Path],
    missing_required: list[str],
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
    lines.extend(["", "FORBIDDEN_ARTIFACT_SCAN"])
    if forbidden or missing_required:
        lines.append("AUDIT_FAILED")
        lines.extend(f"MISSING_REQUIRED {item}" for item in missing_required)
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
    write_report(package_dir, report_path, files, forbidden, missing_required)

    print(f"Audit report: {report_path}")
    print(f"Included files: {len(files)}")
    print(f"Final package size: {human_size(package_size(package_dir))}")
    if missing_required:
        print("Required root files missing:")
        for item in missing_required:
            print(f"  {item}")
    if forbidden:
        print("Forbidden artifacts found:")
        for path in forbidden:
            print(f"  {path.as_posix()}")
    if missing_required or forbidden:
        return 1

    print("Forbidden artifact scan: AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
