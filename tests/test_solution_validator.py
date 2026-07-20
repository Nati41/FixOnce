"""
Tests for Solution Validator - preventing corrupted records.

These tests ensure:
1. Empty problem/solution records are rejected
2. Whitespace-only records are rejected
3. Placeholder values (N/A, none, etc.) are rejected
4. Valid records pass validation and get IDs/timestamps
5. Integrity audit detects corrupted records
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestValidateSolutionRecord:
    """Test the core validation function."""

    def test_rejects_empty_problem(self):
        """Empty problem field should be rejected."""
        from core.solution_validator import validate_solution_record

        record = {
            "problem": "",
            "solution": "Valid solution text",
        }
        result = validate_solution_record(record)

        assert not result.valid
        assert any("problem" in e for e in result.errors)

    def test_rejects_empty_solution(self):
        """Empty solution field should be rejected."""
        from core.solution_validator import validate_solution_record

        record = {
            "problem": "Valid problem text",
            "solution": "",
        }
        result = validate_solution_record(record)

        assert not result.valid
        assert any("solution" in e for e in result.errors)

    def test_rejects_whitespace_only_problem(self):
        """Whitespace-only problem should be rejected."""
        from core.solution_validator import validate_solution_record

        record = {
            "problem": "   \t\n  ",
            "solution": "Valid solution text",
        }
        result = validate_solution_record(record)

        assert not result.valid
        assert any("problem" in e for e in result.errors)

    def test_rejects_whitespace_only_solution(self):
        """Whitespace-only solution should be rejected."""
        from core.solution_validator import validate_solution_record

        record = {
            "problem": "Valid problem text",
            "solution": "   \n\t   ",
        }
        result = validate_solution_record(record)

        assert not result.valid
        assert any("solution" in e for e in result.errors)

    def test_rejects_na_placeholder_problem(self):
        """N/A placeholder in problem should be rejected."""
        from core.solution_validator import validate_solution_record

        for placeholder in ["N/A", "n/a", "NA", "na", "none", "None", "null"]:
            record = {
                "problem": placeholder,
                "solution": "Valid solution text",
            }
            result = validate_solution_record(record)
            assert not result.valid, f"Should reject placeholder: {placeholder}"

    def test_rejects_na_placeholder_solution(self):
        """N/A placeholder in solution should be rejected."""
        from core.solution_validator import validate_solution_record

        for placeholder in ["N/A", "n/a", "NA", "na", "none", "None", "null"]:
            record = {
                "problem": "Valid problem text",
                "solution": placeholder,
            }
            result = validate_solution_record(record)
            assert not result.valid, f"Should reject placeholder: {placeholder}"

    def test_accepts_valid_record(self):
        """Valid record with problem and solution should pass."""
        from core.solution_validator import validate_solution_record

        record = {
            "problem": "Error: Cannot connect to database",
            "solution": "Fixed by adding connection retry logic",
        }
        result = validate_solution_record(record)

        assert result.valid
        assert result.record is not None
        assert "id" in result.record
        assert "timestamp" in result.record
        assert result.record["problem"] == "Error: Cannot connect to database"
        assert result.record["solution"] == "Fixed by adding connection retry logic"

    def test_auto_generates_id(self):
        """ID should be auto-generated if missing."""
        from core.solution_validator import validate_solution_record

        record = {
            "problem": "Valid problem",
            "solution": "Valid solution",
        }
        result = validate_solution_record(record)

        assert result.valid
        assert result.record["id"] is not None
        assert len(result.record["id"]) > 10  # UUID format

    def test_auto_generates_timestamp(self):
        """Timestamp should be auto-generated if missing."""
        from core.solution_validator import validate_solution_record

        record = {
            "problem": "Valid problem",
            "solution": "Valid solution",
        }
        result = validate_solution_record(record)

        assert result.valid
        assert result.record["timestamp"] is not None
        # Should be valid ISO format
        datetime.fromisoformat(result.record["timestamp"])

    def test_preserves_existing_id(self):
        """Existing ID should be preserved."""
        from core.solution_validator import validate_solution_record

        record = {
            "id": "fix_20260720_123456",
            "problem": "Valid problem",
            "solution": "Valid solution",
        }
        result = validate_solution_record(record, auto_generate_id=False)

        assert result.valid
        assert result.record["id"] == "fix_20260720_123456"

    def test_preserves_optional_fields(self):
        """Optional fields should be preserved in validated record."""
        from core.solution_validator import validate_solution_record

        record = {
            "problem": "Valid problem",
            "solution": "Valid solution",
            "files_changed": ["src/api.py", "src/model.py"],
            "importance": "high",
            "actor": "Claude",
            "tags": ["database", "connection"],
        }
        result = validate_solution_record(record)

        assert result.valid
        assert result.record["files_changed"] == ["src/api.py", "src/model.py"]
        assert result.record["importance"] == "high"
        assert result.record["actor"] == "Claude"
        assert result.record["tags"] == ["database", "connection"]


class TestIsValidSolutionContent:
    """Test the quick content validation function."""

    def test_rejects_empty(self):
        """Empty content should be invalid."""
        from core.solution_validator import is_valid_solution_content

        assert not is_valid_solution_content("", "solution")
        assert not is_valid_solution_content("problem", "")
        assert not is_valid_solution_content("", "")

    def test_rejects_none(self):
        """None content should be invalid."""
        from core.solution_validator import is_valid_solution_content

        assert not is_valid_solution_content(None, "solution")
        assert not is_valid_solution_content("problem", None)
        assert not is_valid_solution_content(None, None)

    def test_rejects_placeholders(self):
        """Placeholder values should be invalid."""
        from core.solution_validator import is_valid_solution_content

        assert not is_valid_solution_content("N/A", "solution")
        assert not is_valid_solution_content("problem", "n/a")
        assert not is_valid_solution_content("none", "none")

    def test_accepts_valid(self):
        """Valid content should pass."""
        from core.solution_validator import is_valid_solution_content

        assert is_valid_solution_content("Error occurred", "Fixed it")
        assert is_valid_solution_content("Bug in API", "Added validation")


class TestAuditSolutionRecords:
    """Test the integrity audit function."""

    def test_detects_empty_content(self):
        """Audit should detect empty content records."""
        from core.solution_validator import audit_solution_records

        records = [
            {"id": "1", "problem": "Valid", "solution": "Valid", "timestamp": "2024-01-01"},
            {"id": "2", "problem": "", "solution": "", "timestamp": "2024-01-02"},
            {"id": "3", "problem": "Valid", "solution": "Valid", "timestamp": "2024-01-03"},
        ]
        issues = audit_solution_records(records)

        empty_issues = [i for i in issues if i.category == "empty_content"]
        assert len(empty_issues) == 1
        assert empty_issues[0].record_index == 1

    def test_detects_missing_id(self):
        """Audit should detect missing ID."""
        from core.solution_validator import audit_solution_records

        records = [
            {"problem": "Valid", "solution": "Valid", "timestamp": "2024-01-01"},
        ]
        issues = audit_solution_records(records)

        missing_id = [i for i in issues if i.category == "missing_id"]
        assert len(missing_id) == 1

    def test_detects_duplicate_id(self):
        """Audit should detect duplicate IDs."""
        from core.solution_validator import audit_solution_records

        records = [
            {"id": "same_id", "problem": "Valid 1", "solution": "Valid 1", "timestamp": "2024-01-01"},
            {"id": "same_id", "problem": "Valid 2", "solution": "Valid 2", "timestamp": "2024-01-02"},
        ]
        issues = audit_solution_records(records)

        duplicate = [i for i in issues if i.category == "duplicate_id"]
        assert len(duplicate) == 1
        assert duplicate[0].record_index == 1

    def test_reports_all_issues_in_corrupted_batch(self):
        """Audit should find all issues in a batch with multiple problems."""
        from core.solution_validator import audit_solution_records

        # Simulate the 4 corrupted records we found
        records = [
            {"problem": "", "solution": "", "timestamp": "2026-06-08T11:47:02.886850"},
            {"problem": "", "solution": "", "timestamp": "2026-06-08T11:47:02.886865"},
            {"problem": "", "solution": "", "timestamp": "2026-06-08T11:50:12.915512"},
            {"problem": "", "solution": "", "timestamp": "2026-06-08T11:54:57.724184"},
        ]
        issues = audit_solution_records(records)

        empty_issues = [i for i in issues if i.category == "empty_content"]
        missing_id_issues = [i for i in issues if i.category == "missing_id"]

        assert len(empty_issues) == 4
        assert len(missing_id_issues) == 4


class TestGenerateIntegrityReport:
    """Test the full integrity report generation."""

    def test_report_structure(self):
        """Report should have correct structure."""
        from core.solution_validator import generate_integrity_report

        pm_records = [{"id": "1", "problem": "P1", "solution": "S1", "timestamp": "2024-01-01"}]
        ck_records = [{"id": "1", "problem": "P1", "solution": "S1", "timestamp": "2024-01-01"}]

        report = generate_integrity_report(pm_records, ck_records)

        assert "timestamp" in report
        assert "project_memory" in report
        assert "committed_knowledge" in report
        assert "cross_reference" in report
        assert "summary" in report

    def test_detects_pm_only_records(self):
        """Report should detect records only in Project Memory."""
        from core.solution_validator import generate_integrity_report

        pm_records = [
            {"id": "1", "problem": "P1", "solution": "S1", "timestamp": "2024-01-01"},
            {"id": "2", "problem": "P2", "solution": "S2", "timestamp": "2024-01-02"},
        ]
        ck_records = [
            {"id": "1", "problem": "P1", "solution": "S1", "timestamp": "2024-01-01"},
        ]

        report = generate_integrity_report(pm_records, ck_records)

        assert "2" in report["cross_reference"]["pm_only_ids"]

    def test_counts_invalid_records(self):
        """Report should count invalid records in summary."""
        from core.solution_validator import generate_integrity_report

        pm_records = [
            {"id": "1", "problem": "Valid", "solution": "Valid", "timestamp": "2024-01-01"},
            {"problem": "", "solution": "", "timestamp": "2024-01-02"},  # Invalid
        ]
        ck_records = [
            {"id": "1", "problem": "Valid", "solution": "Valid", "timestamp": "2024-01-01"},
        ]

        report = generate_integrity_report(pm_records, ck_records)

        assert report["summary"]["pm_invalid_records"] == 1
        assert report["summary"]["ck_invalid_records"] == 0
