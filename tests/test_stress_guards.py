import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from api.openai_adapter import _reject_synthetic_stress_write
from tests import stress_test


def test_openai_adapter_rejects_synthetic_stress_payload_for_real_project():
    result = _reject_synthetic_stress_write(
        {
            "decision": "Test decision #68 from thread 7",
            "reason": "Stress test at 1782291685.550764",
        },
        {
            "project_info": {
                "provenance": "user",
                "working_dir": str(PROJECT_ROOT),
            }
        },
    )

    assert result is not None
    assert "Synthetic stress-test memory payload rejected" in result["error"]


def test_openai_adapter_allows_synthetic_stress_payload_for_test_project():
    result = _reject_synthetic_stress_write(
        {
            "what": "Test avoid #1 from thread 2",
            "reason": "Stress test at 1782291685.550764",
        },
        {
            "project_info": {
                "provenance": "test",
                "working_dir": "/tmp/fixonce-stress-123/workspaces/fixonce_stress_test_project",
            }
        },
    )

    assert result is None


def test_stress_write_tests_are_not_pytest_collectable():
    assert stress_test.__test__ is False
    assert stress_test.test_load_high_volume.__test__ is False
    assert stress_test.test_crash_recovery.__test__ is False
    assert stress_test.test_concurrent_access.__test__ is False
    assert stress_test.test_boundary_detection.__test__ is False
    assert stress_test.test_ux_edge_cases.__test__ is False
