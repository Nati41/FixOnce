#!/usr/bin/env python3
"""
FixOnce Installation Tests

Tests the installer, preflight checks, and doctor mode.
"""

import os
import sys
import json
import tempfile
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from install import (
    check_python_version,
    check_write_permissions,
    check_install_path,
    check_port_availability,
    check_disk_space,
    get_fixonce_dir,
    get_platform,
    read_runtime_state,
    get_runtime_port,
    wait_for_server_readiness,
    get_windows_launcher_command,
)


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
        self.details = ""

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}: {self.message}"


def test_python_version():
    """Test Python version check."""
    result = TestResult("Python Version Check")
    try:
        preflight = check_python_version()
        result.passed = preflight.passed
        result.message = preflight.message
        if not preflight.passed:
            result.details = preflight.fix_hint
    except Exception as e:
        result.message = f"Exception: {e}"
    return result


def test_write_permissions():
    """Test write permission checks."""
    result = TestResult("Write Permissions Check")
    try:
        preflight = check_write_permissions()
        result.passed = preflight.passed
        result.message = preflight.message
        if not preflight.passed:
            result.details = preflight.fix_hint
    except Exception as e:
        result.message = f"Exception: {e}"
    return result


def test_install_path():
    """Test install path validation."""
    result = TestResult("Install Path Check")
    try:
        preflight = check_install_path()
        result.passed = preflight.passed
        result.message = preflight.message
        if not preflight.passed:
            result.details = preflight.fix_hint
    except Exception as e:
        result.message = f"Exception: {e}"
    return result


def test_port_availability():
    """Test port availability check."""
    result = TestResult("Port Availability Check")
    try:
        preflight = check_port_availability()
        result.passed = preflight.passed
        result.message = preflight.message
    except Exception as e:
        result.message = f"Exception: {e}"
    return result


def test_disk_space():
    """Test disk space check."""
    result = TestResult("Disk Space Check")
    try:
        preflight = check_disk_space()
        result.passed = preflight.passed
        result.message = preflight.message
    except Exception as e:
        result.message = f"Exception: {e}"
    return result


def test_fixonce_directory_structure():
    """Test that required directories exist."""
    result = TestResult("Directory Structure")
    try:
        fixonce_dir = get_fixonce_dir()
        required = [
            fixonce_dir / "src",
            fixonce_dir / "src" / "server.py",
            fixonce_dir / "data",
            fixonce_dir / "scripts",
            fixonce_dir / "scripts" / "install.py",
        ]
        missing = [str(p) for p in required if not p.exists()]
        if missing:
            result.passed = False
            result.message = f"Missing: {', '.join(missing)}"
        else:
            result.passed = True
            result.message = "All required paths exist"
    except Exception as e:
        result.message = f"Exception: {e}"
    return result


def test_fresh_install_simulation():
    """Simulate a fresh install in a temp directory."""
    result = TestResult("Fresh Install Simulation")
    temp_dir = None
    try:
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix="fixonce_test_")
        temp_path = Path(temp_dir)

        # Create minimal structure
        (temp_path / "src").mkdir()
        (temp_path / "data").mkdir()
        (temp_path / "scripts").mkdir()

        # Copy essential files
        fixonce_dir = get_fixonce_dir()
        shutil.copy(fixonce_dir / "src" / "server.py", temp_path / "src" / "server.py")
        shutil.copy(fixonce_dir / "requirements.txt", temp_path / "requirements.txt")

        # Verify structure
        required = ["src/server.py", "data", "requirements.txt"]
        all_exist = all((temp_path / p).exists() for p in required)

        if all_exist:
            result.passed = True
            result.message = f"Simulated install structure OK in {temp_dir}"
        else:
            result.passed = False
            result.message = "Failed to create install structure"

    except Exception as e:
        result.message = f"Exception: {e}"
    finally:
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def test_cross_user_ping():
    """Test that /api/ping returns user ownership info."""
    result = TestResult("Cross-User Ping")
    try:
        import urllib.request
        import getpass

        url = "http://localhost:5000/api/ping"
        try:
            req = urllib.request.urlopen(url, timeout=5)
            data = json.loads(req.read().decode())

            has_user = "user" in data
            has_path = "install_path" in data
            correct_user = data.get("user") == getpass.getuser()

            if has_user and has_path and correct_user:
                result.passed = True
                result.message = f"Ping returns ownership: user={data['user']}"
            else:
                result.passed = False
                result.message = f"Missing ownership fields: {data}"
        except Exception as e:
            result.passed = False
            result.message = f"Server not reachable: {e}"
    except Exception as e:
        result.message = f"Exception: {e}"
    return result


def test_runtime_state_detected_as_ready():
    """Installer readiness should succeed when runtime.json exists and health is up."""
    result = TestResult("Runtime SSOT Readiness")
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix="fixonce_runtime_")
        temp_home = Path(temp_dir)
        runtime_dir = temp_home / ".fixonce"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_file = runtime_dir / "runtime.json"
        runtime_file.write_text(json.dumps({
            "port": 5123,
            "pid": 12345,
            "server_url": "http://localhost:5123",
            "status": "running",
        }))

        with patch("pathlib.Path.home", return_value=temp_home):
            state = read_runtime_state()
            port = get_runtime_port()
            ready, actual_port, reason = wait_for_server_readiness(
                default_port=5000,
                max_attempts=1,
                poll_interval=0,
                health_checker=lambda candidate: candidate == 5123,
            )

        if state and port == 5123 and ready and actual_port == 5123 and not reason:
            result.passed = True
            result.message = "runtime.json is enough for installer readiness"
        else:
            result.message = f"Unexpected readiness result: state={state}, port={port}, ready={ready}, actual_port={actual_port}, reason={reason}"
    except Exception as e:
        result.message = f"Exception: {e}"
    finally:
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def test_windows_launcher_command_prefers_packaged_exe():
    """Windows launcher should prefer FixOnce.exe when available."""
    result = TestResult("Windows Launcher Prefers EXE")
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix="fixonce_win_launcher_")
        temp_path = Path(temp_dir)
        exe_path = temp_path / "FixOnce.exe"
        exe_path.write_text("stub", encoding="utf-8")

        command, working_dir = get_windows_launcher_command(temp_path, server_mode=True)
        if command == [str(exe_path), "--server"] and working_dir == temp_path:
            result.passed = True
            result.message = "Packaged EXE selected for server mode"
        else:
            result.message = f"Unexpected launcher command: {command}, cwd={working_dir}"
    except Exception as e:
        result.message = f"Exception: {e}"
    finally:
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def test_windows_launcher_command_falls_back_to_app_launcher():
    """Windows launcher should fall back to app_launcher.py when EXE is absent."""
    result = TestResult("Windows Launcher Falls Back")
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix="fixonce_win_launcher_")
        temp_path = Path(temp_dir)
        (temp_path / "scripts").mkdir(parents=True, exist_ok=True)
        (temp_path / "scripts" / "app_launcher.py").write_text("print('stub')", encoding="utf-8")

        command, working_dir = get_windows_launcher_command(temp_path, server_mode=True)
        if command[-2:] == [str(temp_path / "scripts" / "app_launcher.py"), "--server"] and working_dir == temp_path:
            result.passed = True
            result.message = "app_launcher.py selected as fallback"
        else:
            result.message = f"Unexpected launcher command: {command}, cwd={working_dir}"
    except Exception as e:
        result.message = f"Exception: {e}"
    finally:
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def test_runtime_state_without_legacy_port_file():
    """Installer should not require current_port.txt when runtime.json exists."""
    result = TestResult("Runtime Without Legacy Port File")
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix="fixonce_no_portfile_")
        temp_home = Path(temp_dir)
        runtime_dir = temp_home / ".fixonce"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_file = runtime_dir / "runtime.json"
        runtime_file.write_text(json.dumps({"port": 5333, "pid": 9876}))

        with patch("pathlib.Path.home", return_value=temp_home):
            ready, actual_port, reason = wait_for_server_readiness(
                default_port=5000,
                max_attempts=1,
                poll_interval=0,
                health_checker=lambda candidate: candidate == 5333,
            )

        if ready and actual_port == 5333 and not reason:
            result.passed = True
            result.message = "Installer startup works without current_port.txt"
        else:
            result.message = f"Legacy port file still required: ready={ready}, port={actual_port}, reason={reason}"
    except Exception as e:
        result.message = f"Exception: {e}"
    finally:
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def test_runtime_readiness_fails_clearly_without_runtime_or_health():
    """Installer should fail clearly when neither runtime.json nor health exists."""
    result = TestResult("Runtime Readiness Clear Failure")
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix="fixonce_runtime_fail_")
        temp_home = Path(temp_dir)

        with patch("pathlib.Path.home", return_value=temp_home):
            ready, actual_port, reason = wait_for_server_readiness(
                default_port=5000,
                max_attempts=1,
                poll_interval=0,
                health_checker=lambda candidate: False,
            )

        expected = "Server did not publish runtime.json and no health endpoint responded"
        if not ready and actual_port is None and reason == expected:
            result.passed = True
            result.message = "Installer reports missing runtime and health clearly"
        else:
            result.message = f"Unexpected failure message: ready={ready}, port={actual_port}, reason={reason}"
    except Exception as e:
        result.message = f"Exception: {e}"
    finally:
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def run_all_installation_tests():
    """Run all installation tests."""
    tests = [
        test_python_version,
        test_write_permissions,
        test_install_path,
        test_port_availability,
        test_disk_space,
        test_fixonce_directory_structure,
        test_fresh_install_simulation,
        test_cross_user_ping,
        test_runtime_state_detected_as_ready,
        test_runtime_state_without_legacy_port_file,
        test_runtime_readiness_fails_clearly_without_runtime_or_health,
    ]

    results = []
    for test_fn in tests:
        result = test_fn()
        results.append(result)
        print(result)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n{'='*50}")
    print(f"Installation Tests: {passed}/{total} passed")

    return results


if __name__ == "__main__":
    run_all_installation_tests()
