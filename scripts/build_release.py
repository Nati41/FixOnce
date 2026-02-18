#!/usr/bin/env python3
"""
Build clean FixOnce release artifacts for macOS and Windows.

Outputs:
- dist/FixOnce-v<version>/FixOnce-macOS-v<version>.zip
- dist/FixOnce-v<version>/FixOnce-Windows-v<version>.zip
- dist/FixOnce-v<version>/checksums.sha256
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

COMMON_FILES = [
    "README.md",
    "INSTALL-WINDOWS.md",
    "requirements.txt",
    "install.ps1",
    "install.sh",
    "install.bat",
    "install.command",
    "uninstall.ps1",
    "uninstall.sh",
    "FixOnce.bat",
    "FixOnce.command",
]

COMMON_DIRS = [
    "src",
    "scripts",
    "hooks",
    "extension",
]

COMMON_DATA_FILES = [
    "data/brain_dashboard.html",
    "data/dashboard_v2.html",
    "data/project_memory.template.json",
    "data/active_project.json",
    "data/project_index.json",
    "data/current_port.txt",
]

MAC_ONLY = [
    "FixOnce.app",
    "Install FixOnce.app",
    "FixOnce.icns",
    "Install-Mac.icns",
]

WINDOWS_ONLY = [
    "FixOnce-Icon.png",
]


def copy_file(src_rel: str, dst_root: Path) -> None:
    src = ROOT / src_rel
    if not src.exists():
        print(f"[warn] missing file: {src_rel}")
        return
    dst = dst_root / src_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src_rel: str, dst_root: Path) -> None:
    src = ROOT / src_rel
    if not src.exists():
        print(f"[warn] missing dir: {src_rel}")
        return
    dst = dst_root / src_rel
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".DS_Store",
            ".git",
            ".pytest_cache",
            "node_modules",
            "dist",
        ),
    )


def write_release_docs(dst_root: Path, version: str) -> None:
    release_dir = dst_root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    bootstrap = f"""# FixOnce v{version} Bootstrap

## 5-step install

1. Extract archive to a writable folder.
2. Install dependencies:
   - Windows: run `install.ps1` (or `install.bat` fallback)
   - macOS: run `./install.sh` (or `install.command`)
3. Open dashboard at `http://localhost:5000`.
4. Restart Cursor/Claude so MCP config reloads.
5. In your AI editor, send: `היי` and verify context is returned.

## Quick verification

- `http://localhost:5000/api/ping` returns `{{"service":"fixonce"}}`
- `http://localhost:5000/v2` loads dashboard v2
- MCP server path points to `src/mcp_server/mcp_memory_server_v2.py`
"""

    smoke = """# Smoke Test Checklist

Mark each item PASS/FAIL before publishing.

## Common
- [ ] `python -m py_compile scripts/install.py src/server.py` passes
- [ ] `python src/server.py --flask-only` starts successfully
- [ ] `GET /api/ping` returns 200
- [ ] `GET /v2` returns 200

## macOS
- [ ] `FixOnce.app` launches
- [ ] `FixOnce.command` launches app/URL
- [ ] `install.sh` completes without fatal errors
- [ ] Auto-start LaunchAgent created (`~/Library/LaunchAgents/com.fixonce.server.plist`)

## Windows
- [ ] `install.ps1` completes (or `install.bat` fallback)
- [ ] `FixOnce.bat` launches app/dashboard
- [ ] Scheduled task `FixOnceServer` created
- [ ] MCP entries exist in `%APPDATA%\\Cursor\\mcp.json` and `%USERPROFILE%\\.claude.json`
"""

    notes = f"""# FixOnce v{version} – Clean Release

## Package contents
- macOS bundle: `FixOnce-macOS-v{version}.zip`
- Windows bundle: `FixOnce-Windows-v{version}.zip`
- Checksums: `checksums.sha256`

## Release scope
- Clean install scripts for macOS + Windows
- MCP bootstrap and dashboard v2 included
- Smoke-test checklist provided

## Known limitations
- Windows UI launch depends on installed editor CLIs (`claude`, `cursor`, `code`)
- Chrome extension install remains manual (`chrome://extensions`)
"""

    (release_dir / "README_BOOTSTRAP.md").write_text(bootstrap, encoding="utf-8")
    (release_dir / "SMOKE_TEST.md").write_text(smoke, encoding="utf-8")
    (release_dir / "RELEASE_NOTES.md").write_text(notes, encoding="utf-8")


def ensure_empty_runtime_dirs(dst_root: Path) -> None:
    (dst_root / "data" / "projects").mkdir(parents=True, exist_ok=True)
    (dst_root / "data" / "projects_v2").mkdir(parents=True, exist_ok=True)
    (dst_root / "data" / "projects" / ".keep").write_text("", encoding="utf-8")
    (dst_root / "data" / "projects_v2" / ".keep").write_text("", encoding="utf-8")


def zip_folder(folder: Path, out_zip: Path) -> None:
    # Create zip with a stable top-level directory: FixOnce/
    base_name = out_zip.with_suffix("")
    if out_zip.exists():
        out_zip.unlink()
    shutil.make_archive(str(base_name), "zip", root_dir=folder.parent, base_dir=folder.name)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_platform(version: str, platform_name: str, platform_only: list[str], out_dir: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix=f"fixonce-{platform_name}-") as td:
        staging_root = Path(td) / "FixOnce"
        staging_root.mkdir(parents=True, exist_ok=True)

        for f in COMMON_FILES:
            copy_file(f, staging_root)
        for d in COMMON_DIRS:
            copy_tree(d, staging_root)
        for f in COMMON_DATA_FILES:
            copy_file(f, staging_root)
        for p in platform_only:
            src = ROOT / p
            if src.is_dir():
                copy_tree(p, staging_root)
            else:
                copy_file(p, staging_root)

        ensure_empty_runtime_dirs(staging_root)
        write_release_docs(staging_root, version)

        out_zip = out_dir / f"FixOnce-{platform_name}-v{version}.zip"
        zip_folder(staging_root, out_zip)
        return out_zip


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FixOnce release artifacts.")
    parser.add_argument("--version", default="1.0.0", help="Release version (default: 1.0.0)")
    args = parser.parse_args()

    out_dir = ROOT / "dist" / f"FixOnce-v{args.version}"
    out_dir.mkdir(parents=True, exist_ok=True)

    mac_zip = build_platform(args.version, "macOS", MAC_ONLY, out_dir)
    win_zip = build_platform(args.version, "Windows", WINDOWS_ONLY, out_dir)

    checksums = out_dir / "checksums.sha256"
    checksums.write_text(
        f"{sha256(mac_zip)}  {mac_zip.name}\n{sha256(win_zip)}  {win_zip.name}\n",
        encoding="utf-8",
    )

    print("[ok] build complete")
    print(f"      {mac_zip}")
    print(f"      {win_zip}")
    print(f"      {checksums}")


if __name__ == "__main__":
    main()

