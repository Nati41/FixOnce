#!/bin/bash
# FixOnce Feature Test Script
# Run: ./test_all_features.sh

API="http://localhost:5000"
PASS=0
FAIL=0

echo "========================================"
echo "  FixOnce Feature Test Suite"
echo "========================================"
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

test_endpoint() {
    local name="$1"
    local method="$2"
    local endpoint="$3"
    local data="$4"
    local expected="$5"

    if [ "$method" == "GET" ]; then
        result=$(curl -s "$API$endpoint")
    else
        result=$(curl -s -X "$method" -H "Content-Type: application/json" -d "$data" "$API$endpoint")
    fi

    if echo "$result" | grep -q "$expected"; then
        echo -e "${GREEN}✓${NC} $name"
        ((PASS++))
    else
        echo -e "${RED}✗${NC} $name"
        echo "  Expected: $expected"
        echo "  Got: $result"
        ((FAIL++))
    fi
}

echo "--- Core API ---"
test_endpoint "Server Status" "GET" "/api/status" "" "server_running"
test_endpoint "Memory Health" "GET" "/api/memory/health" "" "fullness_percent"
test_endpoint "Get Memory" "GET" "/api/memory" "" "project_info"
test_endpoint "Get Summary" "GET" "/api/memory/summary" "" "Project"

echo ""
echo "--- Auto Detection ---"
test_endpoint "Detect Project" "POST" "/api/memory/detect" "{}" "status"

echo ""
echo "--- Decisions ---"
test_endpoint "Add Decision" "POST" "/api/memory/decisions" '{"decision":"Test decision","reason":"Testing"}' "ok"
test_endpoint "Get Decisions" "GET" "/api/memory/decisions" "" "decisions"

echo ""
echo "--- Avoid Patterns ---"
test_endpoint "Add Avoid" "POST" "/api/memory/avoid" '{"what":"Test avoid","reason":"Testing"}' "ok"
test_endpoint "Get Avoid" "GET" "/api/memory/avoid" "" "avoid"

echo ""
echo "--- Handover ---"
test_endpoint "Save Handover" "POST" "/api/memory/handover" '{"summary":"Test handover summary"}' "ok"
test_endpoint "Get Handover" "GET" "/api/memory/handover" "" "summary"
test_endpoint "Clear Handover" "DELETE" "/api/memory/handover" "" "ok"

echo ""
echo "--- Export/Import ---"
test_endpoint "Export Memory" "GET" "/api/memory/export" "" "project_info"

echo ""
echo "--- Cleanup ---"
# Clean up test data
curl -s -X DELETE "$API/api/memory/decisions/$(curl -s $API/api/memory/decisions | grep -o '"id":"dec_[^"]*"' | head -1 | cut -d'"' -f4)" > /dev/null 2>&1
curl -s -X DELETE "$API/api/memory/avoid/$(curl -s $API/api/memory/avoid | grep -o '"id":"avoid_[^"]*"' | head -1 | cut -d'"' -f4)" > /dev/null 2>&1
echo "Cleaned up test data"

echo ""
echo "========================================"
echo "  Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"
echo "========================================"

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed${NC}"
    exit 1
fi
