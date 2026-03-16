#!/usr/bin/env python3
"""
FixOnce Test Suite Runner

Runs all tests and provides a summary report.

Usage:
    python scripts/run_all_tests.py           # Run all tests
    python scripts/run_all_tests.py --quick   # Skip slow tests
    python scripts/run_all_tests.py --api     # Only API tests
    python scripts/run_all_tests.py --memory  # Only memory tests
    python scripts/run_all_tests.py --install # Only installation tests
"""

import os
import sys
import argparse
import time
from pathlib import Path
from datetime import datetime

# Add paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(title: str):
    """Print a section header."""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}  {title}{Colors.END}")
    print(f"{Colors.BLUE}{'='*60}{Colors.END}\n")


def print_summary(all_results: dict):
    """Print final summary."""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}  FINAL SUMMARY{Colors.END}")
    print(f"{Colors.BLUE}{'='*60}{Colors.END}\n")

    total_passed = 0
    total_tests = 0

    for category, results in all_results.items():
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        total_passed += passed
        total_tests += total

        if passed == total:
            status = f"{Colors.GREEN}PASS{Colors.END}"
        elif passed > 0:
            status = f"{Colors.YELLOW}PARTIAL{Colors.END}"
        else:
            status = f"{Colors.RED}FAIL{Colors.END}"

        print(f"  {category:20} {passed:2}/{total:2}  [{status}]")

    print(f"\n  {'─'*40}")

    if total_passed == total_tests:
        final_status = f"{Colors.GREEN}{Colors.BOLD}ALL TESTS PASSED{Colors.END}"
    else:
        final_status = f"{Colors.RED}{Colors.BOLD}SOME TESTS FAILED{Colors.END}"

    print(f"  TOTAL: {total_passed}/{total_tests}  [{final_status}]")
    print()

    return total_passed == total_tests


def check_server_running():
    """Check if FixOnce server is running."""
    import urllib.request
    try:
        req = urllib.request.urlopen("http://localhost:5000/api/ping", timeout=2)
        return True
    except:
        return False


def run_installation_tests():
    """Run installation tests."""
    from test_installation import run_all_installation_tests
    return run_all_installation_tests()


def run_api_tests():
    """Run API tests."""
    from test_api import run_all_api_tests
    return run_all_api_tests()


def run_memory_tests():
    """Run memory tests."""
    from test_memory import run_all_memory_tests
    return run_all_memory_tests()


def main():
    parser = argparse.ArgumentParser(description="FixOnce Test Suite")
    parser.add_argument("--quick", action="store_true", help="Skip slow tests")
    parser.add_argument("--api", action="store_true", help="Only API tests")
    parser.add_argument("--memory", action="store_true", help="Only memory tests")
    parser.add_argument("--install", action="store_true", help="Only installation tests")
    args = parser.parse_args()

    # Determine which tests to run
    run_all = not (args.api or args.memory or args.install)

    print(f"""
{Colors.BLUE}
  ███████╗██╗██╗  ██╗ ██████╗ ███╗   ██╗ ██████╗███████╗
  ██╔════╝██║╚██╗██╔╝██╔═══██╗████╗  ██║██╔════╝██╔════╝
  █████╗  ██║ ╚███╔╝ ██║   ██║██╔██╗ ██║██║     █████╗
  ██╔══╝  ██║ ██╔██╗ ██║   ██║██║╚██╗██║██║     ██╔══╝
  ██║     ██║██╔╝ ██╗╚██████╔╝██║ ╚████║╚██████╗███████╗
  ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝╚══════╝
{Colors.END}
  {Colors.BOLD}Test Suite v1.0{Colors.END}
  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""")

    # Check server
    if not check_server_running():
        print(f"{Colors.RED}ERROR: FixOnce server not running on port 5000{Colors.END}")
        print(f"Start it with: cd src && python3 server.py --flask-only")
        sys.exit(1)

    print(f"{Colors.GREEN}✓ Server running{Colors.END}\n")

    start_time = time.time()
    all_results = {}

    # Run tests
    if run_all or args.install:
        print_header("INSTALLATION TESTS")
        all_results["Installation"] = run_installation_tests()

    if run_all or args.api:
        print_header("API TESTS")
        all_results["API"] = run_api_tests()

    if run_all or args.memory:
        print_header("MEMORY TESTS")
        all_results["Memory"] = run_memory_tests()

    # Summary
    elapsed = time.time() - start_time
    success = print_summary(all_results)

    print(f"  Time: {elapsed:.1f}s")
    print()

    # Exit code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
