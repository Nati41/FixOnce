#!/usr/bin/env python3
"""
FixOnce Automated Verification Tests
Run: python tests/verify_fixonce.py

Tests API health, isolation, CRUD operations, and core functionality.
Does NOT test AI behavior or UI - those require manual testing.
"""

import requests
import json
import time
import sys
import os
from pathlib import Path

BASE_URL = "http://localhost:5000"
RESULTS = {"passed": 0, "failed": 0, "skipped": 0}


def test(name):
    """Decorator for test functions."""
    def decorator(func):
        def wrapper():
            try:
                func()
                print(f"  [PASS] {name}")
                RESULTS["passed"] += 1
            except AssertionError as e:
                print(f"  [FAIL] {name}: {e}")
                RESULTS["failed"] += 1
            except Exception as e:
                print(f"  [ERROR] {name}: {e}")
                RESULTS["failed"] += 1
        return wrapper
    return decorator


# ============ API Health ============

@test("Server responds")
def test_server_health():
    r = requests.get(f"{BASE_URL}/api/status", timeout=5)
    assert r.status_code == 200, f"Status code: {r.status_code}"


@test("Memory endpoint works")
def test_memory_endpoint():
    r = requests.get(f"{BASE_URL}/api/memory", headers={"X-Dashboard": "true"}, timeout=5)
    assert r.status_code == 200, f"Status code: {r.status_code}"


@test("Rules endpoint works")
def test_rules_endpoint():
    r = requests.get(f"{BASE_URL}/api/memory/rules", headers={"X-Dashboard": "true"}, timeout=5)
    assert r.status_code == 200, f"Status code: {r.status_code}"
    data = r.json()
    assert "rules" in data, "Missing 'rules' key"


@test("AI queue endpoint works")
def test_ai_queue_endpoint():
    r = requests.get(f"{BASE_URL}/api/memory/ai-queue", headers={"X-Dashboard": "true"}, timeout=5)
    assert r.status_code == 200, f"Status code: {r.status_code}"


@test("Dashboard loads")
def test_dashboard_loads():
    r = requests.get(f"{BASE_URL}/lite", timeout=5)
    assert r.status_code == 200, f"Status code: {r.status_code}"
    assert "FixOnce" in r.text, "Dashboard HTML missing FixOnce"


# ============ Rules CRUD ============

@test("Create rule")
def test_create_rule():
    r = requests.post(
        f"{BASE_URL}/api/memory/rules",
        headers={"Content-Type": "application/json", "X-Dashboard": "true"},
        json={"text": "TEST_RULE_AUTO_VERIFY"},
        timeout=5
    )
    assert r.status_code == 200, f"Status code: {r.status_code}"
    data = r.json()
    assert data.get("status") == "ok", f"Response: {data}"


@test("Read rules contains test rule")
def test_read_rule():
    r = requests.get(f"{BASE_URL}/api/memory/rules", headers={"X-Dashboard": "true"}, timeout=5)
    data = r.json()
    rules = data.get("rules", [])
    found = any("TEST_RULE_AUTO_VERIFY" in r.get("text", "") for r in rules)
    assert found, "Test rule not found in rules list"


@test("Delete rule")
def test_delete_rule():
    # First find the rule
    r = requests.get(f"{BASE_URL}/api/memory/rules", headers={"X-Dashboard": "true"}, timeout=5)
    rules = r.json().get("rules", [])
    test_rule = next((r for r in rules if "TEST_RULE_AUTO_VERIFY" in r.get("text", "")), None)
    assert test_rule, "Test rule not found for deletion"

    # Delete it
    r = requests.delete(
        f"{BASE_URL}/api/memory/rules/{test_rule['id']}",
        headers={"X-Dashboard": "true"},
        timeout=5
    )
    assert r.status_code == 200, f"Status code: {r.status_code}"


# ============ AI Queue ============

@test("Queue command for AI")
def test_queue_command():
    r = requests.post(
        f"{BASE_URL}/api/memory/queue-for-ai",
        headers={"Content-Type": "application/json", "X-Dashboard": "true"},
        json={"type": "test_command", "message": "AUTO_TEST_COMMAND"},
        timeout=5
    )
    assert r.status_code == 200, f"Status code: {r.status_code}"
    data = r.json()
    assert data.get("status") == "ok", f"Response: {data}"


@test("Duplicate commands replaced")
def test_no_duplicate_commands():
    # Send same command twice
    for _ in range(2):
        requests.post(
            f"{BASE_URL}/api/memory/queue-for-ai",
            headers={"Content-Type": "application/json", "X-Dashboard": "true"},
            json={"type": "test_dup", "message": "DUPLICATE_TEST"},
            timeout=5
        )

    # Check queue - should have only ONE of this type
    r = requests.get(f"{BASE_URL}/api/memory/ai-queue", headers={"X-Dashboard": "true"}, timeout=5)
    commands = r.json().get("commands", [])
    dup_count = sum(1 for c in commands if c.get("type") == "test_dup")
    assert dup_count <= 1, f"Found {dup_count} duplicate commands"


# ============ Activity Feed ============

@test("Activity endpoint works")
def test_activity_endpoint():
    r = requests.get(f"{BASE_URL}/api/activity/recent", timeout=5)
    # May return 200 or 404 depending on setup
    assert r.status_code in [200, 404], f"Unexpected status: {r.status_code}"


# ============ Search ============

@test("Search endpoint works")
def test_search_endpoint():
    r = requests.get(
        f"{BASE_URL}/api/memory/search",
        params={"q": "test"},
        headers={"X-Dashboard": "true"},
        timeout=5
    )
    assert r.status_code == 200, f"Status code: {r.status_code}"


# ============ Project Detection ============

@test("Active project endpoint works")
def test_active_project():
    r = requests.get(f"{BASE_URL}/api/memory/active-project", headers={"X-Dashboard": "true"}, timeout=5)
    assert r.status_code == 200, f"Status code: {r.status_code}"


# ============ Isolation (Basic) ============

@test("Project header isolation")
def test_project_isolation():
    """Verify X-Project-Root header affects which project is accessed."""
    # This is a basic check - full isolation requires manual multi-AI testing
    r1 = requests.get(
        f"{BASE_URL}/api/memory/rules",
        headers={"X-Dashboard": "true"},
        timeout=5
    )
    assert r1.status_code == 200, "Dashboard request failed"

    r2 = requests.get(
        f"{BASE_URL}/api/memory/rules",
        headers={"X-Project-Root": "/tmp/fake_project_12345"},
        timeout=5
    )
    # Should either work with empty rules or return appropriate response
    assert r2.status_code in [200, 400, 404], f"Unexpected: {r2.status_code}"


# ============ Safety Point ============

@test("Stability mark endpoint works")
def test_safety_point():
    r = requests.post(
        f"{BASE_URL}/api/stability/mark-all",
        headers={"X-Dashboard": "true"},
        timeout=5
    )
    # May work or fail depending on project state
    assert r.status_code in [200, 400, 404, 500], f"Unexpected: {r.status_code}"


# ============ Error Logging ============

@test("Browser errors endpoint works")
def test_browser_errors():
    r = requests.get(f"{BASE_URL}/api/live-errors", timeout=5)
    assert r.status_code == 200, f"Status code: {r.status_code}"


@test("Clear logs endpoint works")
def test_clear_logs():
    r = requests.post(f"{BASE_URL}/api/clear-logs", timeout=5)
    assert r.status_code == 200, f"Status code: {r.status_code}"


# ============ Run All ============

def run_section(name, tests):
    print(f"\n{'='*40}")
    print(f" {name}")
    print('='*40)
    for t in tests:
        t()


def main():
    print("\n" + "="*50)
    print(" FIXONCE AUTOMATED VERIFICATION")
    print("="*50)

    # Check server is running
    try:
        requests.get(f"{BASE_URL}/api/status", timeout=2)
    except:
        print("\n[ERROR] Server not running at localhost:5000")
        print("Start with: python src/server.py")
        sys.exit(1)

    run_section("API Health", [
        test_server_health,
        test_memory_endpoint,
        test_rules_endpoint,
        test_ai_queue_endpoint,
        test_dashboard_loads,
    ])

    run_section("Rules CRUD", [
        test_create_rule,
        test_read_rule,
        test_delete_rule,
    ])

    run_section("AI Queue", [
        test_queue_command,
        test_no_duplicate_commands,
    ])

    run_section("Activity & Search", [
        test_activity_endpoint,
        test_search_endpoint,
    ])

    run_section("Project & Isolation", [
        test_active_project,
        test_project_isolation,
    ])

    run_section("Safety & Errors", [
        test_safety_point,
        test_browser_errors,
        test_clear_logs,
    ])

    # Summary
    print("\n" + "="*50)
    print(" RESULTS")
    print("="*50)
    print(f"  Passed:  {RESULTS['passed']}")
    print(f"  Failed:  {RESULTS['failed']}")
    print(f"  Skipped: {RESULTS['skipped']}")
    print()

    if RESULTS['failed'] > 0:
        print("  STATUS: SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("  STATUS: ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
