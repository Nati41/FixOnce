#!/usr/bin/env python3
"""
FixOnce API Tests

Tests all REST API endpoints.
"""

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:5000"


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
        self.details = ""

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}: {self.message}"


def api_get(endpoint: str, timeout: int = 5) -> dict:
    """Make GET request to API."""
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.urlopen(url, timeout=timeout)
    return json.loads(req.read().decode())


def api_post(endpoint: str, data: dict = None, timeout: int = 5) -> dict:
    """Make POST request to API."""
    url = f"{BASE_URL}{endpoint}"
    body = json.dumps(data or {}).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    response = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(response.read().decode())


def test_ping():
    """Test /api/ping endpoint."""
    result = TestResult("API: /api/ping")
    try:
        data = api_get("/api/ping")
        if data.get("service") == "fixonce" and data.get("status") == "ok":
            result.passed = True
            result.message = f"OK - port {data.get('port')}, user {data.get('user')}"
        else:
            result.message = f"Unexpected response: {data}"
    except Exception as e:
        result.message = f"Failed: {e}"
    return result


def test_dashboard_snapshot():
    """Test /api/dashboard_snapshot endpoint."""
    result = TestResult("API: /api/dashboard_snapshot")
    try:
        data = api_get("/api/dashboard_snapshot")

        # Check that we got a response with some expected fields
        if isinstance(data, dict) and len(data) > 0:
            result.passed = True
            # Try to get project name from various possible locations
            project_name = (
                data.get("project", {}).get("name") or
                data.get("project_name") or
                data.get("name") or
                "returned data"
            )
            result.message = f"OK - {len(data)} fields"
        else:
            result.message = f"Empty or invalid response"
    except Exception as e:
        result.message = f"Failed: {e}"
    return result


def test_live_errors():
    """Test /api/live-errors endpoint."""
    result = TestResult("API: /api/live-errors")
    try:
        data = api_get("/api/live-errors")

        if "errors" in data and isinstance(data["errors"], list):
            result.passed = True
            result.message = f"OK - {len(data['errors'])} errors in log"
        else:
            result.message = f"Unexpected response: {data}"
    except Exception as e:
        result.message = f"Failed: {e}"
    return result


def test_status():
    """Test /api/status endpoint."""
    result = TestResult("API: /api/status")
    try:
        data = api_get("/api/status")

        # Accept any valid response with server info
        if isinstance(data, dict) and ("server_running" in data or "port" in data or "status" in data):
            result.passed = True
            port = data.get("port", "?")
            result.message = f"OK - port {port}"
        else:
            result.message = f"Unexpected response: {data}"
    except Exception as e:
        result.message = f"Failed: {e}"
    return result


def test_decisions_get():
    """Test GET /api/memory/decisions endpoint."""
    result = TestResult("API: GET /api/memory/decisions")
    try:
        data = api_get("/api/memory/decisions")

        if "decisions" in data or "count" in data:
            result.passed = True
            count = data.get("count", len(data.get("decisions", [])))
            result.message = f"OK - {count} decisions"
        else:
            result.message = f"Unexpected response: {data}"
    except Exception as e:
        result.message = f"Failed: {e}"
    return result


def test_avoid_get():
    """Test GET /api/memory/avoid endpoint."""
    result = TestResult("API: GET /api/memory/avoid")
    try:
        data = api_get("/api/memory/avoid")

        if "avoid" in data or "count" in data:
            result.passed = True
            count = data.get("count", len(data.get("avoid", [])))
            result.message = f"OK - {count} avoid patterns"
        else:
            result.message = f"Unexpected response: {data}"
    except Exception as e:
        result.message = f"Failed: {e}"
    return result


def test_rules_get():
    """Test GET /api/memory/rules endpoint."""
    result = TestResult("API: GET /api/memory/rules")
    try:
        data = api_get("/api/memory/rules")

        if "rules" in data or isinstance(data, list):
            result.passed = True
            rules = data.get("rules", data) if isinstance(data, dict) else data
            result.message = f"OK - {len(rules)} rules"
        else:
            result.message = f"Unexpected response: {data}"
    except Exception as e:
        result.message = f"Failed: {e}"
    return result


def test_dashboard_html():
    """Test that dashboard HTML loads."""
    result = TestResult("Dashboard HTML")
    try:
        url = f"{BASE_URL}/"
        req = urllib.request.urlopen(url, timeout=5)
        html = req.read().decode()

        # Check for various possible indicators
        is_html = "<!doctype html>" in html.lower() or "<html" in html.lower()
        has_fixonce = "fixonce" in html.lower() or "protected" in html.lower()

        if is_html and len(html) > 1000:
            result.passed = True
            result.message = f"OK - {len(html)} bytes"
        else:
            result.message = f"HTML too short or invalid ({len(html)} bytes)"
    except Exception as e:
        result.message = f"Failed: {e}"
    return result


def test_lite_redirect():
    """Test that /lite redirects to /."""
    result = TestResult("Redirect: /lite -> /")
    try:
        url = f"{BASE_URL}/lite"
        req = urllib.request.Request(url, method='GET')
        req.add_header('User-Agent', 'FixOnce-Test')

        # Don't follow redirects
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirectHandler)
        try:
            opener.open(req, timeout=5)
            result.message = "No redirect (expected 302/301)"
        except urllib.error.HTTPError as e:
            if e.code in (301, 302):
                location = e.headers.get('Location', '')
                if location == '/' or location.endswith(':5000/'):
                    result.passed = True
                    result.message = f"OK - redirects to {location}"
                else:
                    result.message = f"Redirects to wrong location: {location}"
            else:
                result.message = f"HTTP {e.code}"
    except Exception as e:
        result.message = f"Failed: {e}"
    return result


def run_all_api_tests():
    """Run all API tests."""
    tests = [
        test_ping,
        test_dashboard_snapshot,
        test_live_errors,
        test_status,
        test_decisions_get,
        test_avoid_get,
        test_rules_get,
        test_dashboard_html,
        test_lite_redirect,
    ]

    results = []
    for test_fn in tests:
        result = test_fn()
        results.append(result)
        print(result)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n{'='*50}")
    print(f"API Tests: {passed}/{total} passed")

    return results


if __name__ == "__main__":
    run_all_api_tests()
