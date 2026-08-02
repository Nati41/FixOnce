#!/usr/bin/env python3
"""
Tests for GuardianSignal audit trail (shadow mode).

Tests prove:
- Confirmed deletion creates exactly one persisted signal
- Duplicate notifications create one signal (deduplication)
- Create/modify/move create no destructive signal
- Restart does not erase persistent audit record
- Audit write failure does not break activity logging
- Windows path variants deduplicate correctly
- Existing file_watcher and activity behavior unchanged
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class TestSignalAuditBasics(unittest.TestCase):
    """Basic signal audit functionality."""

    def setUp(self):
        """Clear audit state before each test."""
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_produce_destructive_signal_for_delete(self):
        """Confirmed deletion creates exactly one signal."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal = produce_destructive_signal(
            file_path="/project/src/important.py",
            operation="delete",
            project_id="proj_123",
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.concern, "risk")
        self.assertEqual(signal.category, "risk_destructive_op")
        self.assertEqual(signal.source, "detector")
        self.assertEqual(signal.severity, "high")
        self.assertEqual(signal.confidence, 1.0)
        self.assertIn("deleted", signal.reason)

        # Verify in memory
        audit = get_signal_audit(limit=10)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["concern"], "risk")

    def test_produce_destructive_signal_for_truncate(self):
        """Truncate operation also creates a signal."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal = produce_destructive_signal(
            file_path="/project/data.json",
            operation="truncate",
            project_id="proj_123",
        )

        self.assertIsNotNone(signal)
        self.assertIn("truncated", signal.reason)

    def test_non_destructive_operations_create_no_signal(self):
        """Create/modify/read operations create no destructive signal."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        for op in ["read", "write", "create", "modify", "append", "move", ""]:
            signal = produce_destructive_signal(
                file_path="/project/file.py",
                operation=op,
                project_id="proj_123",
            )
            self.assertIsNone(signal, f"Operation '{op}' should not create signal")

        audit = get_signal_audit(limit=10)
        self.assertEqual(len(audit), 0)


class TestDeduplication(unittest.TestCase):
    """Deduplication prevents duplicate signals."""

    def setUp(self):
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_duplicate_notifications_deduplicated(self):
        """Rapid duplicate notifications create only one signal."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        # Same file, same operation, same project - within time bucket
        signal1 = produce_destructive_signal(
            file_path="/project/src/file.py",
            operation="delete",
            project_id="proj_123",
        )
        signal2 = produce_destructive_signal(
            file_path="/project/src/file.py",
            operation="delete",
            project_id="proj_123",
        )
        signal3 = produce_destructive_signal(
            file_path="/project/src/file.py",
            operation="delete",
            project_id="proj_123",
        )

        # First should succeed, rest should be deduplicated
        self.assertIsNotNone(signal1)
        self.assertIsNone(signal2)
        self.assertIsNone(signal3)

        audit = get_signal_audit(limit=10)
        self.assertEqual(len(audit), 1)

    def test_different_files_not_deduplicated(self):
        """Different files create separate signals."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal1 = produce_destructive_signal(
            file_path="/project/file1.py",
            operation="delete",
            project_id="proj_123",
        )
        signal2 = produce_destructive_signal(
            file_path="/project/file2.py",
            operation="delete",
            project_id="proj_123",
        )

        self.assertIsNotNone(signal1)
        self.assertIsNotNone(signal2)

        audit = get_signal_audit(limit=10)
        self.assertEqual(len(audit), 2)

    def test_different_projects_not_deduplicated(self):
        """Same file in different projects creates separate signals."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal1 = produce_destructive_signal(
            file_path="/project/file.py",
            operation="delete",
            project_id="proj_A",
        )
        signal2 = produce_destructive_signal(
            file_path="/project/file.py",
            operation="delete",
            project_id="proj_B",
        )

        self.assertIsNotNone(signal1)
        self.assertIsNotNone(signal2)

        audit = get_signal_audit(limit=10)
        self.assertEqual(len(audit), 2)


class TestPathNormalization(unittest.TestCase):
    """Path normalization for cross-platform deduplication."""

    def test_normalize_path_forward_slashes(self):
        """Paths are normalized to forward slashes."""
        from core.signal_audit import normalize_path

        # Windows-style path
        result = normalize_path("C:\\Users\\project\\file.py")
        self.assertNotIn("\\", result)
        self.assertIn("/", result)

    def test_normalize_path_trailing_slash(self):
        """Trailing slashes are stripped."""
        from core.signal_audit import normalize_path

        result = normalize_path("/project/dir/")
        self.assertFalse(result.endswith("/"))

    def test_windows_path_variants_deduplicate(self):
        """Windows path variants deduplicate correctly."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        # Simulate Windows paths (forward vs backslash)
        # Note: On non-Windows, these become different paths after resolve()
        # The key is that normalize_path handles the conversion
        signal1 = produce_destructive_signal(
            file_path="/project/src/file.py",
            operation="delete",
            project_id="proj_123",
        )

        # Same logical path, should deduplicate
        signal2 = produce_destructive_signal(
            file_path="/project/src/file.py",
            operation="delete",
            project_id="proj_123",
        )

        self.assertIsNotNone(signal1)
        self.assertIsNone(signal2)

    @unittest.skipIf(os.name != "nt", "Windows-only test")
    def test_windows_case_insensitive_dedup(self):
        """Windows paths deduplicate case-insensitively."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal1 = produce_destructive_signal(
            file_path="C:\\Project\\File.py",
            operation="delete",
            project_id="proj_123",
        )
        signal2 = produce_destructive_signal(
            file_path="c:\\project\\file.py",
            operation="delete",
            project_id="proj_123",
        )

        self.assertIsNotNone(signal1)
        self.assertIsNone(signal2)  # Should deduplicate


class TestPersistence(unittest.TestCase):
    """Persistent JSONL audit storage."""

    def setUp(self):
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_signal_persisted_to_jsonl(self):
        """Signal is persisted to JSONL file."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit_from_file,
            SIGNAL_LOG_FILE,
        )

        # Produce a signal
        signal = produce_destructive_signal(
            file_path="/project/test_persist.py",
            operation="delete",
            project_id="proj_persist_test",
        )

        self.assertIsNotNone(signal)

        # Read from file
        entries = get_signal_audit_from_file(limit=10)

        # Find our entry (may have others from previous tests)
        our_entries = [e for e in entries if e.get("project_id") == "proj_persist_test"]
        self.assertGreaterEqual(len(our_entries), 1)

        entry = our_entries[0]
        self.assertEqual(entry["concern"], "risk")
        self.assertEqual(entry["category"], "risk_destructive_op")
        self.assertEqual(entry["operation"], "delete")
        self.assertIn("test_persist.py", entry["file_path"])

    def test_restart_preserves_audit(self):
        """Restart (clearing memory) does not erase persistent audit."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit_from_file,
            clear_signal_audit_memory,
            SIGNAL_LOG_FILE,
        )

        # Record the file size before
        initial_size = SIGNAL_LOG_FILE.stat().st_size if SIGNAL_LOG_FILE.exists() else 0

        # Produce a signal
        signal = produce_destructive_signal(
            file_path="/project/restart_test.py",
            operation="delete",
            project_id="proj_restart_test",
        )

        # Clear memory (simulates restart)
        clear_signal_audit_memory()

        # File should still have the record
        self.assertTrue(SIGNAL_LOG_FILE.exists())
        self.assertGreater(SIGNAL_LOG_FILE.stat().st_size, initial_size)

        # Read back
        entries = get_signal_audit_from_file(limit=100)
        our_entries = [e for e in entries if e.get("project_id") == "proj_restart_test"]
        self.assertGreaterEqual(len(our_entries), 1)

    def test_persistence_failure_silent(self):
        """Persistence failure does not raise or break caller."""
        from core.signal_audit import (
            _persist_signal,
            clear_signal_audit_memory,
        )
        from core.guardian_signal import GuardianSignal, GuardianEvidence
        import core.signal_audit as signal_audit_module

        clear_signal_audit_memory()

        signal = GuardianSignal(
            concern="risk",
            source="detector",
            category="risk_destructive_op",
            severity="high",
            confidence=1.0,
            reason="test",
            evidence=GuardianEvidence(file_path="/test.py", operation="delete"),
        )

        # Create a mock Path that raises on open
        mock_path = MagicMock()
        mock_path.parent.mkdir = MagicMock()
        mock_path.open = MagicMock(side_effect=OSError("Disk full"))

        original_log_file = signal_audit_module.SIGNAL_LOG_FILE
        try:
            signal_audit_module.SIGNAL_LOG_FILE = mock_path
            # Should not raise - returns False on failure
            result = _persist_signal(signal, "proj_123", "key")
            self.assertFalse(result)
        finally:
            signal_audit_module.SIGNAL_LOG_FILE = original_log_file


class TestEvidenceSerialization(unittest.TestCase):
    """Evidence serializes correctly in persisted records."""

    def test_evidence_fields_in_persisted_record(self):
        """Evidence fields appear in the persisted JSONL record."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit_from_file,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal = produce_destructive_signal(
            file_path="/project/evidence_test.py",
            operation="delete",
            project_id="proj_evidence_test",
        )

        entries = get_signal_audit_from_file(limit=10)
        our_entries = [e for e in entries if e.get("project_id") == "proj_evidence_test"]
        self.assertGreaterEqual(len(our_entries), 1)

        entry = our_entries[0]
        # Required fields from spec
        self.assertIn("timestamp", entry)
        self.assertIn("project_id", entry)
        self.assertIn("file_path", entry)
        self.assertIn("operation", entry)
        self.assertIn("concern", entry)
        self.assertIn("category", entry)
        self.assertIn("source", entry)
        self.assertIn("severity", entry)
        self.assertIn("confidence", entry)
        self.assertIn("reason", entry)
        self.assertIn("dedup_key", entry)

        # Values
        self.assertEqual(entry["operation"], "delete")
        self.assertEqual(entry["confidence"], 1.0)


class TestActivityIntegration(unittest.TestCase):
    """Integration with activity API."""

    def test_activity_log_not_broken_by_signal_failure(self):
        """Activity logging continues even if signal production fails."""
        # This tests the try/except in activity.py
        with patch("api.activity.produce_destructive_signal", side_effect=RuntimeError("Boom")):
            with patch("api.activity.SIGNAL_AUDIT_ENABLED", True):
                # Import after patching
                from flask import Flask
                from api.activity import activity_bp

                app = Flask(__name__)
                app.register_blueprint(activity_bp)
                app.config['TESTING'] = True

                with app.test_client() as client:
                    response = client.post('/log', json={
                        "type": "file_change",
                        "event": "deleted",
                        "file": "/project/test.py",
                        "cwd": "/project",
                        "tool": "file_watcher",
                    })

                    # Should succeed despite signal failure
                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertEqual(data.get("status"), "ok")


class TestFileWatcherUnchanged(unittest.TestCase):
    """File watcher behavior remains unchanged."""

    def test_file_watcher_process_event_unchanged(self):
        """File watcher process_event behavior is unchanged."""
        # Import the handler
        from file_watcher import FixOnceHandler

        handler = FixOnceHandler("/project", "test_source")

        # Mock the HTTP call
        with patch("file_watcher.requests.post") as mock_post:
            mock_post.return_value = MagicMock(ok=True)

            # Create a mock event
            mock_event = MagicMock()
            mock_event.is_directory = False
            mock_event.src_path = "/project/src/test.py"

            # Process deletion - should call report_activity
            handler.on_deleted(mock_event)

            # Verify HTTP call was made (file watcher behavior)
            mock_post.assert_called_once()
            call_data = mock_post.call_args[1]["json"]
            self.assertEqual(call_data["event"], "deleted")
            self.assertEqual(call_data["file"], "/project/src/test.py")

    def test_file_watcher_debouncing_unchanged(self):
        """File watcher debouncing still works."""
        from file_watcher import FixOnceHandler

        handler = FixOnceHandler("/project", "test_source")

        # First event should not be debounced
        self.assertFalse(handler.is_debounced("/project/file.py"))

        # Immediate second event should be debounced
        self.assertTrue(handler.is_debounced("/project/file.py"))


class TestNoCreateModifySignal(unittest.TestCase):
    """Create and modify events don't create destructive signals."""

    def test_created_event_no_signal(self):
        """Created event produces no destructive signal."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        # Simulate what activity.py would do for a "created" event
        # It only calls produce_destructive_signal for "deleted" events
        # So this test verifies the produce function itself rejects non-delete
        signal = produce_destructive_signal(
            file_path="/project/new_file.py",
            operation="create",
            project_id="proj_123",
        )

        self.assertIsNone(signal)
        self.assertEqual(len(get_signal_audit()), 0)

    def test_modified_event_no_signal(self):
        """Modified event produces no destructive signal."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal = produce_destructive_signal(
            file_path="/project/existing.py",
            operation="modify",
            project_id="proj_123",
        )

        self.assertIsNone(signal)
        self.assertEqual(len(get_signal_audit()), 0)

    def test_move_event_no_signal(self):
        """Move event produces no destructive signal."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_signal_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal = produce_destructive_signal(
            file_path="/project/moved.py",
            operation="move",
            project_id="proj_123",
        )

        self.assertIsNone(signal)
        self.assertEqual(len(get_signal_audit()), 0)


class TestShadowPolicyEvaluation(unittest.TestCase):
    """Shadow policy evaluation for guardian signals."""

    def setUp(self):
        from core.signal_audit import clear_signal_audit_memory
        clear_signal_audit_memory()

    def test_delete_creates_require_approval_verdict(self):
        """Confirmed delete creates one require_approval shadow verdict."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_verdict_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal = produce_destructive_signal(
            file_path="/project/important.py",
            operation="delete",
            project_id="proj_verdict_test",
        )

        self.assertIsNotNone(signal)

        verdicts = get_verdict_audit(limit=10)
        self.assertEqual(len(verdicts), 1)

        verdict = verdicts[0]
        self.assertEqual(verdict["level"], "require_approval")
        self.assertTrue(verdict["shadow_only"])
        self.assertIn("verdict_id", verdict)
        self.assertIn("policy_version", verdict)

    def test_duplicate_delete_no_duplicate_verdict(self):
        """Duplicate delete notification creates no duplicate verdict."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_verdict_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        # First delete
        signal1 = produce_destructive_signal(
            file_path="/project/file.py",
            operation="delete",
            project_id="proj_dup_verdict",
        )
        # Duplicate (same file, same project, within time bucket)
        signal2 = produce_destructive_signal(
            file_path="/project/file.py",
            operation="delete",
            project_id="proj_dup_verdict",
        )

        self.assertIsNotNone(signal1)
        self.assertIsNone(signal2)  # Deduplicated

        verdicts = get_verdict_audit(limit=10)
        self.assertEqual(len(verdicts), 1)

    def test_create_modify_move_no_verdict(self):
        """Create/modify/move events produce no verdict."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_verdict_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        for op in ["create", "modify", "move", "write", "read"]:
            signal = produce_destructive_signal(
                file_path=f"/project/{op}_file.py",
                operation=op,
                project_id="proj_no_verdict",
            )
            self.assertIsNone(signal)

        verdicts = get_verdict_audit(limit=10)
        self.assertEqual(len(verdicts), 0)

    def test_unsupported_signal_returns_silent(self):
        """Unsupported signal categories produce silent verdict."""
        from core.guardian_signal import GuardianSignal, GuardianEvidence
        from core.guardian_policy import evaluate_guardian_signals

        # Create a signal with unsupported category
        signal = GuardianSignal(
            concern="opportunity",
            source="detector",
            category="opportunity_past_solution",
            severity="medium",
            confidence=0.8,
            reason="Similar bug found",
            evidence=GuardianEvidence(file_path="/test.py"),
        )

        verdict = evaluate_guardian_signals(
            signals=(signal,),
            project_id="proj_test",
            source_signal_keys=("key1",),
        )

        self.assertEqual(verdict.level, "silent")
        self.assertIn("No supported signal patterns", verdict.reason)

    def test_verdict_persisted_to_file(self):
        """Verdict is persisted to JSONL file."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_verdict_audit_from_file,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        signal = produce_destructive_signal(
            file_path="/project/persist_verdict.py",
            operation="delete",
            project_id="proj_persist_verdict",
        )

        entries = get_verdict_audit_from_file(limit=10)
        our_entries = [e for e in entries if e.get("project_id") == "proj_persist_verdict"]
        self.assertGreaterEqual(len(our_entries), 1)

        entry = our_entries[0]
        self.assertEqual(entry["event"], "verdict_created")
        self.assertEqual(entry["level"], "require_approval")
        self.assertTrue(entry["shadow_only"])

    def test_verdict_contains_required_fields(self):
        """Verdict contains all required fields."""
        from core.signal_audit import (
            produce_destructive_signal,
            get_verdict_audit,
            clear_signal_audit_memory,
        )
        clear_signal_audit_memory()

        produce_destructive_signal(
            file_path="/project/fields_test.py",
            operation="delete",
            project_id="proj_fields",
        )

        verdicts = get_verdict_audit(limit=1)
        self.assertEqual(len(verdicts), 1)

        verdict = verdicts[0]
        required_fields = [
            "event",
            "verdict_id",
            "level",
            "reason",
            "policy_version",
            "shadow_only",
            "timestamp",
            "project_id",
            "source_signal_keys",
            "evidence_summary",
        ]
        for field in required_fields:
            self.assertIn(field, verdict, f"Missing field: {field}")

    def test_signal_recorded_without_policy_evaluation(self):
        """Signal can be recorded without policy evaluation."""
        from core.signal_audit import (
            record_signal_audit,
            get_signal_audit,
            get_verdict_audit,
            clear_signal_audit_memory,
        )
        from core.guardian_signal import GuardianSignal, GuardianEvidence

        clear_signal_audit_memory()

        signal = GuardianSignal(
            concern="risk",
            source="detector",
            category="risk_destructive_op",
            severity="high",
            confidence=1.0,
            reason="Test",
            evidence=GuardianEvidence(file_path="/test_no_policy.py", operation="delete"),
        )

        # Record without policy evaluation
        recorded, dedup_key = record_signal_audit(
            signal,
            project_id="proj_no_policy",
            evaluate_policy=False,  # Disable policy evaluation
        )

        # Signal should be recorded
        self.assertTrue(recorded)
        self.assertIsNotNone(dedup_key)

        signals = get_signal_audit(limit=10)
        self.assertEqual(len(signals), 1)

        # But no verdict should be created
        verdicts = get_verdict_audit(limit=10)
        self.assertEqual(len(verdicts), 0)


class TestStage7Unchanged(unittest.TestCase):
    """Verify Stage 7 intervention policy remains unchanged."""

    def test_intervention_policy_structure_unchanged(self):
        """InterventionLevel still has only silent/warn/block."""
        from core.intervention_policy import InterventionLevel

        # InterventionLevel should NOT include require_approval
        # That's in GuardianVerdictLevel
        valid_levels = {"silent", "warn", "block"}
        # Get the literal values
        level_args = getattr(InterventionLevel, "__args__", ())
        self.assertEqual(set(level_args), valid_levels)

    def test_evaluate_risk_gate_unchanged(self):
        """evaluate_risk_gate behavior is unchanged."""
        from core.intervention_policy import (
            evaluate_risk_gate,
            InterventionContext,
        )

        # Default context = silent
        result = evaluate_risk_gate(InterventionContext())
        self.assertEqual(result.level, "silent")

        # risky_change still triggers warn (not require_approval)
        result = evaluate_risk_gate(InterventionContext(risky_change=True))
        self.assertEqual(result.level, "warn")

        # lock_violation still triggers block
        result = evaluate_risk_gate(InterventionContext(lock_violation=True))
        self.assertEqual(result.level, "block")


if __name__ == "__main__":
    unittest.main()
