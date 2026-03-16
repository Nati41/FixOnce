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
    get_platform
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
