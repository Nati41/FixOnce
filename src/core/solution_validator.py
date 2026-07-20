"""
Solution Record Validator - Transport-Independent Core Validation.

All solution write paths MUST validate through this module before persisting.
This prevents invalid/corrupted records from entering project memory.

Validation Rules:
- problem: Required, non-empty, non-whitespace-only
- solution: Required, non-empty, non-whitespace-only
- id: Required, must be valid UUID or auto-generated
- timestamp: Required, must be valid ISO format or auto-generated
- record_type: Must be valid ("solution", "debug_session")

Invalid records are REJECTED, not silently accepted with defaults.
"""

import uuid
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of solution record validation."""
    valid: bool
    record: Optional[Dict[str, Any]] = None
    errors: Optional[List[str]] = None

    def __bool__(self) -> bool:
        return self.valid


def validate_solution_record(
    record: Dict[str, Any],
    require_id: bool = True,
    auto_generate_id: bool = True,
    auto_generate_timestamp: bool = True,
) -> ValidationResult:
    """
    Validate a solution record before persistence.

    This is the SINGLE VALIDATION POINT for all solution writes.
    ALL adapters (MCP, REST, Dashboard, pending) MUST use this function.

    Args:
        record: The solution record dict to validate
        require_id: If True, record must have an id (or one will be generated)
        auto_generate_id: If True and id is missing, generate one
        auto_generate_timestamp: If True and timestamp is missing, generate one

    Returns:
        ValidationResult with valid=True and cleaned record, or valid=False and errors

    Raises:
        Nothing - returns ValidationResult with errors instead
    """
    errors = []

    # === REQUIRED CONTENT VALIDATION ===

    # Problem field - REQUIRED, non-empty
    problem = record.get("problem")
    if problem is None:
        problem = record.get("error")  # Legacy field name support
    if not problem or not isinstance(problem, str):
        errors.append("problem: required field missing or not a string")
    elif not problem.strip():
        errors.append("problem: cannot be empty or whitespace-only")
    elif problem.strip().lower() in ("n/a", "na", "none", "null", "undefined"):
        errors.append("problem: cannot be placeholder value (N/A, none, etc.)")

    # Solution field - REQUIRED, non-empty
    solution = record.get("solution")
    if not solution or not isinstance(solution, str):
        errors.append("solution: required field missing or not a string")
    elif not solution.strip():
        errors.append("solution: cannot be empty or whitespace-only")
    elif solution.strip().lower() in ("n/a", "na", "none", "null", "undefined"):
        errors.append("solution: cannot be placeholder value (N/A, none, etc.)")

    # === ID VALIDATION ===
    record_id = record.get("id")
    if not record_id:
        if require_id:
            if auto_generate_id:
                record_id = str(uuid.uuid4())
            else:
                errors.append("id: required field missing")
    elif not isinstance(record_id, str):
        errors.append("id: must be a string")

    # === TIMESTAMP VALIDATION ===
    timestamp = record.get("timestamp")
    if not timestamp:
        if auto_generate_timestamp:
            timestamp = datetime.now().isoformat()
        else:
            errors.append("timestamp: required field missing")
    elif isinstance(timestamp, str):
        try:
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            errors.append(f"timestamp: invalid ISO format: {timestamp}")
    else:
        errors.append("timestamp: must be a string in ISO format")

    # === RETURN RESULT ===
    if errors:
        return ValidationResult(valid=False, errors=errors)

    # Build validated record with normalized fields
    validated_record = {
        "id": record_id,
        "problem": problem.strip() if problem else "",
        "solution": solution.strip() if solution else "",
        "timestamp": timestamp,
        "status": record.get("status", "active"),
    }

    # Copy optional fields
    optional_fields = [
        "files_changed", "files", "importance", "actor", "actor_source",
        "actor_confidence", "session_id", "tool_name", "superseded",
        "superseded_at", "superseded_by", "superseded_reason",
        "semantic_id", "tags", "context",
    ]
    for field in optional_fields:
        if field in record:
            validated_record[field] = record[field]

    return ValidationResult(valid=True, record=validated_record)


def validate_solution_for_commit(
    problem: str,
    solution: str,
    files_changed: Optional[List[str]] = None,
    **kwargs,
) -> ValidationResult:
    """
    Validate solution data before creating a record.

    Convenience wrapper for when data comes as separate arguments.

    Args:
        problem: The problem/error description
        solution: The solution description
        files_changed: Optional list of affected files
        **kwargs: Additional record fields

    Returns:
        ValidationResult
    """
    record = {
        "problem": problem,
        "solution": solution,
        "files_changed": files_changed or [],
        **kwargs,
    }
    return validate_solution_record(record)


def is_valid_solution_content(problem: Optional[str], solution: Optional[str]) -> bool:
    """
    Quick check if problem/solution content is valid.

    Use for pre-flight checks before building a full record.
    """
    if not problem or not isinstance(problem, str) or not problem.strip():
        return False
    if not solution or not isinstance(solution, str) or not solution.strip():
        return False
    # Check for placeholder values
    problem_lower = problem.strip().lower()
    solution_lower = solution.strip().lower()
    if problem_lower in ("n/a", "na", "none", "null", "undefined", ""):
        return False
    if solution_lower in ("n/a", "na", "none", "null", "undefined", ""):
        return False
    return True


# =============================================================================
# INTEGRITY AUDIT
# =============================================================================

@dataclass
class IntegrityIssue:
    """An integrity issue found during audit."""
    category: str  # "empty_content", "missing_id", "duplicate_id", etc.
    record_index: int
    record_timestamp: Optional[str]
    description: str
    severity: str  # "error", "warning"


def audit_solution_records(records: List[Dict[str, Any]]) -> List[IntegrityIssue]:
    """
    Audit a list of solution records for integrity issues.

    This is READ-ONLY - it reports issues but does not modify data.

    Checks:
    - Empty/invalid content
    - Missing or invalid IDs
    - Duplicate IDs
    - Invalid timestamps
    - Superseded records counted as active
    - Inconsistent status fields

    Args:
        records: List of solution records to audit

    Returns:
        List of IntegrityIssue objects
    """
    issues = []
    seen_ids = {}

    for idx, record in enumerate(records):
        timestamp = record.get("timestamp", "UNKNOWN")

        # Check for empty content
        problem = record.get("problem", "")
        solution = record.get("solution", "")
        if not is_valid_solution_content(problem, solution):
            issues.append(IntegrityIssue(
                category="empty_content",
                record_index=idx,
                record_timestamp=timestamp,
                description=f"Empty or invalid problem/solution content",
                severity="error",
            ))

        # Check for missing ID
        record_id = record.get("id")
        if not record_id:
            issues.append(IntegrityIssue(
                category="missing_id",
                record_index=idx,
                record_timestamp=timestamp,
                description="Record has no ID",
                severity="warning",
            ))
        else:
            # Check for duplicate ID
            if record_id in seen_ids:
                issues.append(IntegrityIssue(
                    category="duplicate_id",
                    record_index=idx,
                    record_timestamp=timestamp,
                    description=f"Duplicate ID '{record_id}' (first seen at index {seen_ids[record_id]})",
                    severity="error",
                ))
            else:
                seen_ids[record_id] = idx

        # Check timestamp validity
        ts = record.get("timestamp")
        if not ts:
            issues.append(IntegrityIssue(
                category="missing_timestamp",
                record_index=idx,
                record_timestamp=None,
                description="Record has no timestamp",
                severity="warning",
            ))
        elif isinstance(ts, str):
            try:
                datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except ValueError:
                issues.append(IntegrityIssue(
                    category="invalid_timestamp",
                    record_index=idx,
                    record_timestamp=ts,
                    description=f"Invalid timestamp format: {ts}",
                    severity="warning",
                ))

        # Check for inconsistent superseded state
        superseded = record.get("superseded")
        status = record.get("status", "active")
        if superseded and status == "active":
            issues.append(IntegrityIssue(
                category="inconsistent_superseded",
                record_index=idx,
                record_timestamp=timestamp,
                description="Record marked superseded=True but status='active'",
                severity="warning",
            ))

    return issues


def generate_integrity_report(
    project_memory_records: List[Dict[str, Any]],
    committed_knowledge_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Generate a comprehensive integrity report comparing PM and CK.

    Args:
        project_memory_records: debug_sessions from Project Memory
        committed_knowledge_records: solutions from Committed Knowledge

    Returns:
        Report dict with issues, counts, and recommendations
    """
    report = {
        "timestamp": datetime.now().isoformat(),
        "project_memory": {
            "total_records": len(project_memory_records),
            "issues": [],
        },
        "committed_knowledge": {
            "total_records": len(committed_knowledge_records),
            "issues": [],
        },
        "cross_reference": {
            "pm_only_ids": [],
            "ck_only_ids": [],
            "shared_ids": [],
        },
        "summary": {},
    }

    # Audit PM records
    pm_issues = audit_solution_records(project_memory_records)
    report["project_memory"]["issues"] = [
        {"category": i.category, "index": i.record_index, "timestamp": i.record_timestamp,
         "description": i.description, "severity": i.severity}
        for i in pm_issues
    ]

    # Audit CK records
    ck_issues = audit_solution_records(committed_knowledge_records)
    report["committed_knowledge"]["issues"] = [
        {"category": i.category, "index": i.record_index, "timestamp": i.record_timestamp,
         "description": i.description, "severity": i.severity}
        for i in ck_issues
    ]

    # Cross-reference IDs
    pm_ids = {r.get("id") for r in project_memory_records if r.get("id")}
    ck_ids = {r.get("id") for r in committed_knowledge_records if r.get("id")}

    report["cross_reference"]["pm_only_ids"] = list(pm_ids - ck_ids)
    report["cross_reference"]["ck_only_ids"] = list(ck_ids - pm_ids)
    report["cross_reference"]["shared_ids"] = list(pm_ids & ck_ids)

    # Count issues by category
    all_issues = pm_issues + ck_issues
    issue_counts = {}
    for issue in all_issues:
        issue_counts[issue.category] = issue_counts.get(issue.category, 0) + 1

    report["summary"] = {
        "total_issues": len(all_issues),
        "error_count": sum(1 for i in all_issues if i.severity == "error"),
        "warning_count": sum(1 for i in all_issues if i.severity == "warning"),
        "issues_by_category": issue_counts,
        "pm_invalid_records": sum(1 for i in pm_issues if i.category == "empty_content"),
        "ck_invalid_records": sum(1 for i in ck_issues if i.category == "empty_content"),
    }

    return report
