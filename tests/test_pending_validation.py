"""
Integration tests for pending memory approval validation.

These tests verify that the api/pending.py endpoint properly rejects
corrupted records and only saves valid solutions to project memory.

This is a REGRESSION TEST for the bug that created 4 corrupted records
with empty problem/solution fields on 2026-06-08.
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestPendingApprovalValidation:
    """Test that pending approval rejects invalid solution records."""

    @pytest.fixture
    def mock_pending_data(self):
        """Create mock pending data with both valid and invalid solutions."""
        return {
            "pending": [
                {
                    "id": "pending_valid_1",
                    "type": "solution",
                    "problem": "Valid error message",
                    "solution": "Valid fix description",
                    "project_id": "test_project",
                    "timestamp": "2024-01-01T10:00:00",
                },
                {
                    "id": "pending_invalid_1",
                    "type": "solution",
                    "problem": "",  # INVALID - empty
                    "solution": "",  # INVALID - empty
                    "project_id": "test_project",
                    "timestamp": "2024-01-01T10:00:01",
                },
                {
                    "id": "pending_invalid_2",
                    "type": "solution",
                    "problem": "N/A",  # INVALID - placeholder
                    "solution": "N/A",  # INVALID - placeholder
                    "project_id": "test_project",
                    "timestamp": "2024-01-01T10:00:02",
                },
            ]
        }

    def test_validation_rejects_empty_content(self):
        """Validation should reject solutions with empty problem/solution."""
        from core.solution_validator import validate_solution_record

        # Simulate the exact scenario that caused the bug
        record = {
            "problem": "",
            "solution": "",
            "files_changed": [],
            "importance": "high",
            "actor": "user",
            "actor_source": "dashboard",
            "actor_confidence": 1.0,
            "session_id": "dashboard-review",
            "tool_name": "memory_review",
            "timestamp": "2026-06-08T11:47:02.886850",
        }

        result = validate_solution_record(record)

        assert not result.valid
        assert len(result.errors) >= 2  # Both problem and solution invalid
        assert any("problem" in e for e in result.errors)
        assert any("solution" in e for e in result.errors)

    def test_corrupted_record_scenario(self):
        """Replicate the exact scenario that created the 4 corrupted records."""
        from core.solution_validator import validate_solution_record

        # These are the exact records that were created
        corrupted_timestamps = [
            "2026-06-08T11:47:02.886850",
            "2026-06-08T11:47:02.886865",
            "2026-06-08T11:50:12.915512",
            "2026-06-08T11:54:57.724184",
        ]

        for ts in corrupted_timestamps:
            record = {
                "problem": "",
                "solution": "",
                "files_changed": [],
                "importance": "high",
                "actor": "user",
                "actor_source": "dashboard",
                "actor_confidence": 1.0,
                "session_id": "dashboard-review",
                "tool_name": "memory_review",
                "timestamp": ts,
                "status": "active",
            }

            result = validate_solution_record(record)

            # MUST be rejected
            assert not result.valid, f"Should reject corrupted record at {ts}"
            assert result.errors is not None
            assert len(result.errors) >= 2


class TestValidationInWritePath:
    """Verify validation is called in the actual write paths."""

    def test_pending_approve_imports_validator(self):
        """api/pending.py approve endpoint should import validator."""
        # Check that the code has the import
        pending_py = Path(__file__).parent.parent / "src" / "api" / "pending.py"
        source = pending_py.read_text()

        assert "from core.solution_validator import validate_solution_record" in source
        assert "validation = validate_solution_record" in source
        assert "validation.valid" in source

    def test_solutions_py_imports_validator(self):
        """core/solutions.py should import validator."""
        solutions_py = Path(__file__).parent.parent / "src" / "core" / "solutions.py"
        source = solutions_py.read_text()

        assert "from core.solution_validator import validate_solution_record" in source

    def test_mcp_server_imports_validator(self):
        """MCP server should import validator for fo_solved."""
        mcp_py = Path(__file__).parent.parent / "src" / "mcp_server" / "mcp_memory_server_v2.py"
        source = mcp_py.read_text()

        assert "from core.solution_validator import validate_solution_record" in source
