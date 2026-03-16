#!/usr/bin/env python3
"""
FixOnce Fresh Install Simulation

Simulates a complete fresh install in a clean environment.
Tests the full installation flow without affecting the real installation.
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

# Colors
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

PROJECT_ROOT = Path(__file__).parent.parent


def print_step(step: str, status: str, color: str = Colors.GREEN):
    """Print a step result."""
    print(f"  {color}[{status}]{Colors.END} {step}")


def print_header(title: str):
    """Print section header."""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}  {title}{Colors.END}")
    print(f"{Colors.BLUE}{'='*60}{Colors.END}\n")


def simulate_fresh_install():
    """Simulate a complete fresh installation."""
    temp_dir = None
    results = {"passed": 0, "failed": 0, "steps": []}

    try:
        print_header("FRESH INSTALL SIMULATION")
        print(f"  Source: {PROJECT_ROOT}")

        # Step 1: Create clean temp directory
        temp_dir = tempfile.mkdtemp(prefix="fixonce_fresh_")
        temp_path = Path(temp_dir)
        print_step(f"Created temp directory: {temp_dir}", "OK")
        results["steps"].append(("Create temp dir", True))
        results["passed"] += 1

        # Step 2: Copy essential files (simulating git clone)
        print(f"\n  {Colors.BLUE}Copying project files...{Colors.END}")
        dirs_to_copy = ["src", "scripts", "data", "extension"]
        files_to_copy = ["requirements.txt", "CLAUDE.md"]

        for d in dirs_to_copy:
            src = PROJECT_ROOT / d
            dst = temp_path / d
            if src.exists():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
                print_step(f"Copied {d}/", "OK")

        for f in files_to_copy:
            src = PROJECT_ROOT / f
            dst = temp_path / f
            if src.exists():
                shutil.copy2(src, dst)
                print_step(f"Copied {f}", "OK")

        results["steps"].append(("Copy project files", True))
        results["passed"] += 1

        # Step 3: Verify directory structure
        print(f"\n  {Colors.BLUE}Verifying structure...{Colors.END}")
        required = [
            "src/server.py",
            "src/mcp_server/mcp_memory_server_v2.py",
            "scripts/install.py",
            "data/dashboard.html",
            "requirements.txt"
        ]
        missing = []
        for path in required:
            full_path = temp_path / path
            if full_path.exists():
                print_step(path, "OK")
            else:
                print_step(path, "MISSING", Colors.RED)
                missing.append(path)

        if missing:
            results["steps"].append(("Verify structure", False))
            results["failed"] += 1
        else:
            results["steps"].append(("Verify structure", True))
            results["passed"] += 1

        # Step 4: Run preflight checks
        print(f"\n  {Colors.BLUE}Running preflight checks...{Colors.END}")
        try:
            # Add temp dir to path for imports
            sys.path.insert(0, str(temp_path / "scripts"))
            sys.path.insert(0, str(temp_path / "src"))

            # Import preflight checks
            from install import (
                check_python_version,
                check_write_permissions,
                check_disk_space
            )

            preflight_results = [
                ("Python Version", check_python_version()),
                ("Disk Space", check_disk_space()),
            ]

            preflight_passed = True
            for name, result in preflight_results:
                if result.passed:
                    print_step(f"{name}: {result.message}", "PASS")
                else:
                    print_step(f"{name}: {result.message}", "FAIL", Colors.RED)
                    preflight_passed = False

            results["steps"].append(("Preflight checks", preflight_passed))
            if preflight_passed:
                results["passed"] += 1
            else:
                results["failed"] += 1

        except Exception as e:
            print_step(f"Preflight import error: {e}", "FAIL", Colors.RED)
            results["steps"].append(("Preflight checks", False))
            results["failed"] += 1

        # Step 5: Create .fixonce directory (simulating first run)
        print(f"\n  {Colors.BLUE}Creating .fixonce directory...{Colors.END}")
        fixonce_dir = temp_path / ".fixonce"
        try:
            fixonce_dir.mkdir(exist_ok=True)

            # Create metadata.json
            metadata = {
                "fixonce_version": "1.0",
                "project_id": f"test_project_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "name": "Fresh Install Test",
                "created_at": datetime.now().isoformat()
            }
            with open(fixonce_dir / "metadata.json", 'w') as f:
                json.dump(metadata, f, indent=2)

            print_step("Created .fixonce/metadata.json", "OK")
            results["steps"].append(("Create .fixonce", True))
            results["passed"] += 1
        except Exception as e:
            print_step(f"Failed: {e}", "FAIL", Colors.RED)
            results["steps"].append(("Create .fixonce", False))
            results["failed"] += 1

        # Step 6: Test Python import chain
        print(f"\n  {Colors.BLUE}Testing Python imports...{Colors.END}")
        imports_to_test = [
            "config",
            "core.project_context",
            "core.committed_knowledge",
            "managers.multi_project_manager",
        ]

        import_success = True
        for module in imports_to_test:
            try:
                __import__(module)
                print_step(f"import {module}", "OK")
            except Exception as e:
                print_step(f"import {module}: {e}", "FAIL", Colors.RED)
                import_success = False

        results["steps"].append(("Python imports", import_success))
        if import_success:
            results["passed"] += 1
        else:
            results["failed"] += 1

        # Step 7: Test server can start (syntax check only)
        print(f"\n  {Colors.BLUE}Checking server syntax...{Colors.END}")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(temp_path / "src" / "server.py")],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                print_step("server.py syntax", "OK")
                results["steps"].append(("Server syntax", True))
                results["passed"] += 1
            else:
                print_step(f"server.py syntax: {result.stderr}", "FAIL", Colors.RED)
                results["steps"].append(("Server syntax", False))
                results["failed"] += 1
        except Exception as e:
            print_step(f"Syntax check error: {e}", "FAIL", Colors.RED)
            results["steps"].append(("Server syntax", False))
            results["failed"] += 1

        # Step 8: Test MCP server syntax
        print(f"\n  {Colors.BLUE}Checking MCP server syntax...{Colors.END}")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(temp_path / "src" / "mcp_server" / "mcp_memory_server_v2.py")],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                print_step("mcp_memory_server_v2.py syntax", "OK")
                results["steps"].append(("MCP server syntax", True))
                results["passed"] += 1
            else:
                print_step(f"MCP server syntax: {result.stderr}", "FAIL", Colors.RED)
                results["steps"].append(("MCP server syntax", False))
                results["failed"] += 1
        except Exception as e:
            print_step(f"Syntax check error: {e}", "FAIL", Colors.RED)
            results["steps"].append(("MCP server syntax", False))
            results["failed"] += 1

    except Exception as e:
        print(f"\n{Colors.RED}SIMULATION FAILED: {e}{Colors.END}")
        results["steps"].append(("Simulation", False))
        results["failed"] += 1

    finally:
        # Cleanup
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"\n  {Colors.BLUE}Cleaned up temp directory{Colors.END}")

    # Summary
    print_header("SIMULATION RESULTS")
    total = results["passed"] + results["failed"]
    if results["failed"] == 0:
        print(f"  {Colors.GREEN}{Colors.BOLD}ALL {total} STEPS PASSED{Colors.END}")
        print(f"\n  Fresh install simulation: {Colors.GREEN}SUCCESS{Colors.END}")
    else:
        print(f"  {Colors.RED}{results['failed']}/{total} steps failed{Colors.END}")
        print(f"\n  Fresh install simulation: {Colors.RED}FAILED{Colors.END}")
        print(f"\n  Failed steps:")
        for step, passed in results["steps"]:
            if not passed:
                print(f"    - {step}")

    return results["failed"] == 0


if __name__ == "__main__":
    success = simulate_fresh_install()
    sys.exit(0 if success else 1)
