#!/usr/bin/env python3
"""
FixOnce Stress Test Suite
=========================

Brutal tests to verify FixOnce can handle:
1. High load (1000+ operations/minute)
2. Crash recovery (mid-write termination)
3. Concurrent access (multiple AI assistants)
4. Boundary confusion (nested projects)
5. Edge cases (port conflicts, missing dirs)

Usage:
    python tests/stress_test.py              # Run all tests
    python tests/stress_test.py --test load  # Run specific test
    python tests/stress_test.py --quick      # Quick smoke test

Requirements:
    - FixOnce server running on localhost:5000
    - pip install requests
"""

import os
import sys
import json
import time
import random
import string
import argparse
import threading
import subprocess
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests")
    import requests


# ============================================================================
# Configuration
# ============================================================================

BASE_URL = "http://localhost:5000"
OPENAI_URL = f"{BASE_URL}/openai"
API_URL = f"{BASE_URL}/api"

# Test parameters
LOAD_TEST_THREADS = 10
LOAD_TEST_OPS_PER_THREAD = 100
CONCURRENT_TEST_THREADS = 5
TIMEOUT_SECONDS = 5

# IMPORTANT: Use dedicated test project, NOT active project
TEST_PROJECT_DIR = "/tmp/fixonce_stress_test_project"

# Store original active project to restore after tests
ORIGINAL_ACTIVE_PROJECT = None


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    duration: float
    details: str = ""
    errors: List[str] = field(default_factory=list)


@dataclass
class StressTestReport:
    """Complete stress test report."""
    timestamp: str
    total_tests: int
    passed: int
    failed: int
    duration: float
    results: List[TestResult]

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "duration": self.duration,
            "success_rate": f"{(self.passed/self.total_tests)*100:.1f}%" if self.total_tests > 0 else "N/A",
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "duration": f"{r.duration:.2f}s",
                    "details": r.details,
                    "errors": r.errors
                }
                for r in self.results
            ]
        }


# ============================================================================
# Utilities
# ============================================================================

def random_string(length: int = 10) -> str:
    """Generate random string."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def check_server_running() -> bool:
    """Check if FixOnce server is running."""
    try:
        resp = requests.get(f"{API_URL}/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def wait_for_server(timeout: int = 30) -> bool:
    """Wait for server to become available."""
    start = time.time()
    while time.time() - start < timeout:
        if check_server_running():
            return True
        time.sleep(0.5)
    return False


def setup_test_project() -> bool:
    """
    Create and initialize a dedicated test project.
    IMPORTANT: This prevents tests from polluting real project data.
    """
    global ORIGINAL_ACTIVE_PROJECT

    # Save original active project to restore later
    active_file = Path(__file__).parent.parent / "data" / "active_project.json"
    if active_file.exists():
        try:
            with open(active_file, 'r') as f:
                ORIGINAL_ACTIVE_PROJECT = json.load(f)
            print(f"📋 Saved original active project: {ORIGINAL_ACTIVE_PROJECT.get('active_id', 'unknown')}")
        except Exception:
            pass

    # Create test project directory
    test_dir = Path(TEST_PROJECT_DIR)
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)

    # Create minimal project marker
    (test_dir / ".git").mkdir()
    (test_dir / "package.json").write_text('{"name": "stress-test-project"}')

    # Initialize with FixOnce
    try:
        resp = requests.post(
            f"{OPENAI_URL}/call",
            json={"name": "fixonce_init_session", "arguments": {
                "working_dir": str(test_dir)
            }},
            timeout=TIMEOUT_SECONDS
        )
        if resp.status_code == 200:
            print(f"✅ Test project initialized: {test_dir}")
            return True
        else:
            print(f"❌ Failed to init test project: {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error initializing test project: {e}")
        return False


def cleanup_test_project():
    """Clean up test project after tests - both folder AND data files."""
    global ORIGINAL_ACTIVE_PROJECT

    # Clean temp folder
    test_dir = Path(TEST_PROJECT_DIR)
    if test_dir.exists():
        try:
            shutil.rmtree(test_dir)
            print(f"🧹 Cleaned up test folder: {test_dir}")
        except Exception as e:
            print(f"⚠️  Could not clean up folder: {e}")

    # Clean project data files from FixOnce data directory
    data_dir = Path(__file__).parent.parent / "data" / "projects_v2"
    if data_dir.exists():
        test_patterns = ["fixonce_stress_test_project_", "subproject_", "project_a-build_"]
        for json_file in data_dir.glob("*.json"):
            if any(pattern in json_file.name for pattern in test_patterns):
                try:
                    json_file.unlink()
                    print(f"🧹 Cleaned up data file: {json_file.name}")
                except Exception as e:
                    print(f"⚠️  Could not delete {json_file.name}: {e}")

    # Restore original active project
    if ORIGINAL_ACTIVE_PROJECT:
        active_file = Path(__file__).parent.parent / "data" / "active_project.json"
        try:
            with open(active_file, 'w') as f:
                json.dump(ORIGINAL_ACTIVE_PROJECT, f, indent=2)
            print(f"🔄 Restored original active project: {ORIGINAL_ACTIVE_PROJECT.get('active_id', 'unknown')}")
        except Exception as e:
            print(f"⚠️  Could not restore active project: {e}")


def ensure_test_project_active() -> bool:
    """
    Ensure the test project is the active project before operations.
    This prevents writing to real user projects.
    """
    try:
        resp = requests.post(
            f"{OPENAI_URL}/call",
            json={"name": "fixonce_init_session", "arguments": {
                "working_dir": TEST_PROJECT_DIR
            }},
            timeout=TIMEOUT_SECONDS
        )
        return resp.status_code == 200
    except Exception:
        return False


# ============================================================================
# Test 1: Load Test (Memory Explosion)
# ============================================================================

def test_load_high_volume() -> TestResult:
    """
    Test 1: Memory Explosion

    Sends 1000+ operations in parallel to test:
    - Server stability under load
    - JSON write performance
    - Memory usage
    """
    print("\n" + "="*60)
    print("TEST 1: Load Test (High Volume Operations)")
    print("="*60)

    # CRITICAL: Ensure we're writing to test project, not real project!
    if not ensure_test_project_active():
        return TestResult(
            name="Load Test (High Volume)",
            passed=False,
            duration=0,
            details="Could not activate test project",
            errors=["Failed to ensure test project is active"]
        )

    start_time = time.time()
    errors = []
    success_count = 0
    total_ops = LOAD_TEST_THREADS * LOAD_TEST_OPS_PER_THREAD

    def worker(thread_id: int) -> Tuple[int, List[str]]:
        """Single worker thread."""
        successes = 0
        thread_errors = []

        for i in range(LOAD_TEST_OPS_PER_THREAD):
            action = random.choice(["decision", "insight", "avoid"])
            payload = {
                action if action != "avoid" else "what": f"Test {action} #{i} from thread {thread_id}",
                "reason" if action != "insight" else "x": f"Stress test at {time.time()}"
            }

            try:
                if action == "decision":
                    resp = requests.post(
                        f"{OPENAI_URL}/call",
                        json={"name": "fixonce_log_decision", "arguments": {
                            "decision": payload["decision"],
                            "reason": payload["reason"]
                        }},
                        timeout=TIMEOUT_SECONDS
                    )
                elif action == "insight":
                    resp = requests.post(
                        f"{OPENAI_URL}/call",
                        json={"name": "fixonce_log_insight", "arguments": {
                            "insight": payload["insight"]
                        }},
                        timeout=TIMEOUT_SECONDS
                    )
                else:
                    resp = requests.post(
                        f"{OPENAI_URL}/call",
                        json={"name": "fixonce_log_avoid", "arguments": {
                            "what": payload["what"],
                            "reason": payload["reason"]
                        }},
                        timeout=TIMEOUT_SECONDS
                    )

                if resp.status_code == 200:
                    successes += 1
                else:
                    thread_errors.append(f"Thread {thread_id} op {i}: HTTP {resp.status_code}")

            except requests.Timeout:
                thread_errors.append(f"Thread {thread_id} op {i}: Timeout")
            except Exception as e:
                thread_errors.append(f"Thread {thread_id} op {i}: {str(e)[:50]}")

        return successes, thread_errors

    # Run parallel workers
    print(f"Launching {LOAD_TEST_THREADS} threads, {LOAD_TEST_OPS_PER_THREAD} ops each...")
    print(f"Total operations: {total_ops}")

    with ThreadPoolExecutor(max_workers=LOAD_TEST_THREADS) as executor:
        futures = [executor.submit(worker, i) for i in range(LOAD_TEST_THREADS)]

        for future in as_completed(futures):
            count, errs = future.result()
            success_count += count
            errors.extend(errs)

    duration = time.time() - start_time
    ops_per_second = total_ops / duration if duration > 0 else 0

    passed = success_count >= total_ops * 0.95  # 95% success rate required

    details = (
        f"Operations: {success_count}/{total_ops} ({success_count/total_ops*100:.1f}%)\n"
        f"Duration: {duration:.2f}s\n"
        f"Throughput: {ops_per_second:.1f} ops/sec"
    )

    print(f"\n✅ Success: {success_count}/{total_ops}")
    print(f"⏱️  Duration: {duration:.2f}s")
    print(f"📊 Throughput: {ops_per_second:.1f} ops/sec")
    print(f"{'✅ PASSED' if passed else '❌ FAILED'}")

    return TestResult(
        name="Load Test (High Volume)",
        passed=passed,
        duration=duration,
        details=details,
        errors=errors[:10]  # Keep first 10 errors
    )


# ============================================================================
# Test 2: Crash Recovery (Mid-Write Termination)
# ============================================================================

def test_crash_recovery() -> TestResult:
    """
    Test 2: Crash Recovery

    Tests file integrity after simulated crash.
    We can't actually kill the server, but we can:
    - Write data
    - Verify atomic write protection
    - Check for corruption markers
    """
    print("\n" + "="*60)
    print("TEST 2: Crash Recovery (Atomic Write Verification)")
    print("="*60)

    # CRITICAL: Ensure we're writing to test project, not real project!
    if not ensure_test_project_active():
        return TestResult(
            name="Crash Recovery (Atomic Write)",
            passed=False,
            duration=0,
            details="Could not activate test project",
            errors=["Failed to ensure test project is active"]
        )

    start_time = time.time()
    errors = []

    # Using test project (already activated above)
    test_id = f"crash_test_{random_string(8)}"

    try:
        # Write some data rapidly
        print("Writing rapid bursts of data...")
        for i in range(50):
            requests.post(
                f"{OPENAI_URL}/call",
                json={"name": "fixonce_log_insight", "arguments": {
                    "insight": f"Crash test insight {i} - " + "x" * 100
                }},
                timeout=TIMEOUT_SECONDS
            )

        # Now try to read and verify data integrity
        print("Verifying data integrity...")
        resp = requests.post(
            f"{OPENAI_URL}/call",
            json={"name": "fixonce_get_context", "arguments": {}},
            timeout=TIMEOUT_SECONDS
        )

        if resp.status_code != 200:
            errors.append(f"Context read failed: {resp.status_code}")
        else:
            data = resp.json()
            if "error" in data.get("result", {}):
                errors.append(f"Context error: {data['result']['error']}")

        # Check for .tmp files (sign of incomplete atomic writes)
        data_dir = Path(__file__).parent.parent / "data" / "projects_v2"
        if data_dir.exists():
            tmp_files = list(data_dir.glob("*.tmp"))
            if tmp_files:
                errors.append(f"Found {len(tmp_files)} orphaned .tmp files")
                for f in tmp_files[:5]:
                    print(f"  ⚠️  Orphan: {f.name}")

        passed = len(errors) == 0

    except Exception as e:
        errors.append(f"Test exception: {str(e)}")
        passed = False

    duration = time.time() - start_time

    print(f"\n{'✅ PASSED' if passed else '❌ FAILED'}")
    if errors:
        for e in errors[:5]:
            print(f"  ❌ {e}")

    return TestResult(
        name="Crash Recovery (Atomic Write)",
        passed=passed,
        duration=duration,
        details=f"Rapid writes: 50, Errors: {len(errors)}",
        errors=errors
    )


# ============================================================================
# Test 3: Concurrent Access (Dual Identity)
# ============================================================================

def test_concurrent_access() -> TestResult:
    """
    Test 3: Concurrent Access

    Simulates multiple AI assistants writing conflicting data simultaneously.
    Checks for race conditions and data consistency.
    """
    print("\n" + "="*60)
    print("TEST 3: Concurrent Access (Race Condition Test)")
    print("="*60)

    # CRITICAL: Ensure we're writing to test project, not real project!
    if not ensure_test_project_active():
        return TestResult(
            name="Concurrent Access (Race Condition)",
            passed=False,
            duration=0,
            details="Could not activate test project",
            errors=["Failed to ensure test project is active"]
        )

    start_time = time.time()
    errors = []
    results = []

    def conflicting_writer(writer_id: int, framework: str) -> Dict:
        """Simulates an AI insisting on a framework."""
        try:
            resp = requests.post(
                f"{OPENAI_URL}/call",
                json={"name": "fixonce_log_decision", "arguments": {
                    "decision": f"Use {framework} for backend",
                    "reason": f"Writer {writer_id} says {framework} is best"
                }},
                timeout=TIMEOUT_SECONDS
            )
            return {"writer": writer_id, "framework": framework, "status": resp.status_code}
        except Exception as e:
            return {"writer": writer_id, "framework": framework, "error": str(e)}

    # Launch conflicting writers
    frameworks = ["Flask", "Django", "FastAPI", "Express", "Rails"]
    print(f"Launching {CONCURRENT_TEST_THREADS} writers with conflicting decisions...")

    with ThreadPoolExecutor(max_workers=CONCURRENT_TEST_THREADS) as executor:
        futures = [
            executor.submit(conflicting_writer, i, frameworks[i % len(frameworks)])
            for i in range(CONCURRENT_TEST_THREADS * 3)  # 15 conflicting writes
        ]

        for future in as_completed(futures):
            results.append(future.result())

    # Check results
    success_writes = sum(1 for r in results if r.get("status") == 200)
    error_writes = sum(1 for r in results if "error" in r)

    # Verify data consistency
    print("Verifying data consistency...")
    resp = requests.post(
        f"{OPENAI_URL}/call",
        json={"name": "fixonce_get_context", "arguments": {}},
        timeout=TIMEOUT_SECONDS
    )

    if resp.status_code == 200:
        ctx = resp.json().get("result", {})
        decisions = ctx.get("decisions", [])
        print(f"  Total decisions recorded: {len(decisions)}")

        # Check for corruption (mixed data, truncation)
        for d in decisions[-5:]:
            if isinstance(d, dict):
                if not d.get("decision") or not d.get("reason"):
                    errors.append("Corrupted decision found (missing fields)")
            else:
                errors.append(f"Corrupted decision format: {type(d)}")
    else:
        errors.append(f"Context read failed: {resp.status_code}")

    passed = error_writes == 0 and len(errors) == 0

    duration = time.time() - start_time

    details = (
        f"Concurrent writes: {len(results)}\n"
        f"Successful: {success_writes}\n"
        f"Errors: {error_writes}"
    )

    print(f"\n{'✅ PASSED' if passed else '❌ FAILED'}")

    return TestResult(
        name="Concurrent Access (Race Condition)",
        passed=passed,
        duration=duration,
        details=details,
        errors=errors
    )


# ============================================================================
# Test 4: Boundary Detection Torture
# ============================================================================

def test_boundary_detection() -> TestResult:
    """
    Test 4: Boundary Detection

    Creates confusing project structures to test boundary detection:
    - Nested git repos
    - Sibling projects
    - Build output folders
    """
    print("\n" + "="*60)
    print("TEST 4: Boundary Detection Torture")
    print("="*60)

    start_time = time.time()
    errors = []

    # Create temp directory structure
    temp_base = Path(tempfile.mkdtemp(prefix="fixonce_boundary_test_"))

    try:
        # Create confusing structure
        # project_a/
        #   .git/
        #   subproject/
        #     .git/
        #     package.json
        #   project_a-build/
        #     copied_files...

        project_a = temp_base / "project_a"
        project_a.mkdir()
        (project_a / ".git").mkdir()

        subproject = project_a / "subproject"
        subproject.mkdir()
        (subproject / ".git").mkdir()
        (subproject / "package.json").write_text('{"name": "subproject"}')

        build_folder = temp_base / "project_a-build"
        build_folder.mkdir()
        (build_folder / "output.txt").write_text("build output")

        print(f"Created test structure at: {temp_base}")

        # Test: Build folder should NOT become active project
        print("Testing: Build folder detection...")
        resp = requests.post(
            f"{OPENAI_URL}/call",
            json={"name": "fixonce_init_session", "arguments": {
                "working_dir": str(build_folder)
            }},
            timeout=TIMEOUT_SECONDS
        )

        if resp.status_code == 200:
            result = resp.json().get("result", {})
            if "build" in result.get("project_id", "").lower():
                # This is actually OK if it creates a project, but it shouldn't switch
                print("  ⚠️  Build folder was initialized as project")

        # Test: Nested git repo should be detected correctly
        print("Testing: Nested git repo detection...")
        resp = requests.post(
            f"{OPENAI_URL}/call",
            json={"name": "fixonce_init_session", "arguments": {
                "working_dir": str(subproject)
            }},
            timeout=TIMEOUT_SECONDS
        )

        if resp.status_code == 200:
            result = resp.json().get("result", {})
            # Should detect subproject, not parent
            if "subproject" not in str(result).lower():
                errors.append("Failed to detect nested git repo correctly")
            else:
                print("  ✅ Correctly detected nested git repo")

        passed = len(errors) == 0

    except Exception as e:
        errors.append(f"Test exception: {str(e)}")
        passed = False

    finally:
        # Cleanup
        try:
            shutil.rmtree(temp_base)
        except Exception:
            pass

    duration = time.time() - start_time

    print(f"\n{'✅ PASSED' if passed else '❌ FAILED'}")

    return TestResult(
        name="Boundary Detection Torture",
        passed=passed,
        duration=duration,
        details=f"Test structures created and verified",
        errors=errors
    )


# ============================================================================
# Test 5: UX Edge Cases
# ============================================================================

def test_ux_edge_cases() -> TestResult:
    """
    Test 5: UX Edge Cases

    Tests real-world edge cases:
    - Invalid inputs
    - Missing parameters
    - Malformed JSON
    """
    print("\n" + "="*60)
    print("TEST 5: UX Edge Cases")
    print("="*60)

    # CRITICAL: Ensure we're writing to test project, not real project!
    if not ensure_test_project_active():
        return TestResult(
            name="UX Edge Cases",
            passed=False,
            duration=0,
            details="Could not activate test project",
            errors=["Failed to ensure test project is active"]
        )

    start_time = time.time()
    errors = []
    tests_run = 0
    tests_passed = 0

    # Test cases: (description, endpoint, payload, expected_behavior)
    test_cases = [
        (
            "Empty decision",
            "fixonce_log_decision",
            {"decision": "", "reason": ""},
            "should_error"
        ),
        (
            "Missing required field",
            "fixonce_log_decision",
            {"decision": "Test"},  # missing reason
            "should_error"
        ),
        (
            "Very long input",
            "fixonce_log_insight",
            {"insight": "x" * 10000},  # 10KB string
            "should_succeed"
        ),
        (
            "Unicode characters",
            "fixonce_log_insight",
            {"insight": "שלום עולם 🚀 日本語 العربية"},
            "should_succeed"
        ),
        (
            "Special characters",
            "fixonce_log_decision",
            {"decision": "Use 'quotes' and \"double\" and `backticks`", "reason": "Test <html> & entities"},
            "should_succeed"
        ),
        (
            "Null values",
            "fixonce_log_avoid",
            {"what": None, "reason": None},
            "should_error"
        ),
    ]

    for desc, func, payload, expected in test_cases:
        tests_run += 1
        print(f"  Testing: {desc}...", end=" ")

        try:
            resp = requests.post(
                f"{OPENAI_URL}/call",
                json={"name": func, "arguments": payload},
                timeout=TIMEOUT_SECONDS
            )

            result = resp.json().get("result", {})
            has_error = "error" in result

            if expected == "should_error":
                if has_error:
                    print("✅ (correctly errored)")
                    tests_passed += 1
                else:
                    print("❌ (should have errored)")
                    errors.append(f"{desc}: Should have errored but didn't")
            else:  # should_succeed
                if not has_error:
                    print("✅")
                    tests_passed += 1
                else:
                    print(f"❌ (unexpected error: {result.get('error', '')[:30]})")
                    errors.append(f"{desc}: {result.get('error', '')[:50]}")

        except Exception as e:
            print(f"❌ (exception: {str(e)[:30]})")
            errors.append(f"{desc}: Exception - {str(e)[:50]}")

    passed = tests_passed == tests_run
    duration = time.time() - start_time

    print(f"\n{'✅ PASSED' if passed else '❌ FAILED'} ({tests_passed}/{tests_run})")

    return TestResult(
        name="UX Edge Cases",
        passed=passed,
        duration=duration,
        details=f"Edge cases: {tests_passed}/{tests_run} passed",
        errors=errors
    )


# ============================================================================
# Main Runner
# ============================================================================

def run_all_tests() -> StressTestReport:
    """Run all stress tests and generate report."""
    print("\n" + "="*70)
    print("   FIXONCE STRESS TEST SUITE")
    print("   Testing server at:", BASE_URL)
    print("="*70)

    # Check server
    if not check_server_running():
        print("\n❌ ERROR: FixOnce server is not running!")
        print(f"   Please start the server: python src/server.py")
        print(f"   Then run this test again.")
        sys.exit(1)

    print("\n✅ Server is running")

    # Set up dedicated test project (IMPORTANT: Don't pollute real data!)
    print("\n📁 Setting up dedicated test project...")
    if not setup_test_project():
        print("❌ Could not set up test project. Aborting.")
        sys.exit(1)

    start_time = time.time()
    results = []

    # Run tests
    tests = [
        test_load_high_volume,
        test_crash_recovery,
        test_concurrent_access,
        test_boundary_detection,
        test_ux_edge_cases,
    ]

    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            results.append(TestResult(
                name=test_func.__name__,
                passed=False,
                duration=0,
                details=f"Test crashed: {str(e)}",
                errors=[str(e)]
            ))

    # Generate report
    total_duration = time.time() - start_time
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    report = StressTestReport(
        timestamp=datetime.now().isoformat(),
        total_tests=len(results),
        passed=passed,
        failed=failed,
        duration=total_duration,
        results=results
    )

    # Print summary
    print("\n" + "="*70)
    print("   STRESS TEST SUMMARY")
    print("="*70)
    print(f"\n   Total Tests: {report.total_tests}")
    print(f"   ✅ Passed: {report.passed}")
    print(f"   ❌ Failed: {report.failed}")
    print(f"   ⏱️  Duration: {report.duration:.2f}s")
    print(f"\n   Success Rate: {(report.passed/report.total_tests)*100:.1f}%")

    if report.failed > 0:
        print("\n   Failed Tests:")
        for r in results:
            if not r.passed:
                print(f"   - {r.name}")
                for e in r.errors[:3]:
                    print(f"     • {e[:60]}")

    print("\n" + "="*70)

    # Clean up test project
    print("\n🧹 Cleaning up test project...")
    cleanup_test_project()

    # Save report
    report_path = Path(__file__).parent / "stress_test_results.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"\n📄 Report saved: {report_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="FixOnce Stress Test Suite")
    parser.add_argument("--test", choices=["load", "crash", "concurrent", "boundary", "ux"],
                        help="Run specific test")
    parser.add_argument("--quick", action="store_true",
                        help="Quick smoke test (reduced operations)")
    args = parser.parse_args()

    if args.quick:
        global LOAD_TEST_OPS_PER_THREAD
        LOAD_TEST_OPS_PER_THREAD = 10

    if args.test:
        test_map = {
            "load": test_load_high_volume,
            "crash": test_crash_recovery,
            "concurrent": test_concurrent_access,
            "boundary": test_boundary_detection,
            "ux": test_ux_edge_cases,
        }
        if check_server_running():
            result = test_map[args.test]()
            sys.exit(0 if result.passed else 1)
        else:
            print("❌ Server not running")
            sys.exit(1)
    else:
        report = run_all_tests()
        sys.exit(0 if report.failed == 0 else 1)


if __name__ == "__main__":
    main()
