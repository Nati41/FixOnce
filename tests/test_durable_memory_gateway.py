#!/usr/bin/env python3
"""Tests for the canonical forward-only durable-memory gateway."""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.durable_memory import durable_memory_write
from core.policy_engine import detect_conflicts
from core import resume_state
from managers import multi_project_manager


ATTRIBUTION = {
    "actor": "codex",
    "actor_source": "client_actor",
    "actor_confidence": 1.0,
    "session_id": "session-1",
    "tool_name": "test_tool",
}


class TestDurableMemoryGateway(unittest.TestCase):
    def test_different_record_paths_receive_consistent_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project.json"
            path.write_text(json.dumps({
                "decisions": [],
                "avoid": [],
                "debug_sessions": [],
                "ai_handoffs": [],
                "live_record": {
                    "lessons": {"insights": []},
                    "architecture": {"components": []},
                    "vision": {"mission": []},
                },
            }), encoding="utf-8")

            def add_records(memory):
                memory["decisions"].append({"decision": "Use atomic writes"})
                memory["avoid"].append({"what": "Direct JSON overwrites"})
                memory["debug_sessions"].append({"problem": "Lost update", "solution": "Lock it"})
                memory["ai_handoffs"].append({
                    "from_actor": "claude",
                    "to_actor": "codex",
                    "completed_work": "Gateway design",
                    "remaining_work": "Validation",
                    "risks": "",
                    "next_action": "Run tests",
                })
                memory["live_record"]["lessons"]["insights"].append({"text": "Writes need one path"})
                memory["live_record"]["architecture"]["components"].append({"name": "Memory Gateway"})
                memory["live_record"]["vision"]["mission"].append({"text": "Preserve project knowledge"})
                return memory

            saved = durable_memory_write(
                path,
                mutator=add_records,
                attribution=ATTRIBUTION,
                tool_name="test_tool",
                create_backup=False,
            )

        records = [
            saved["decisions"][0],
            saved["avoid"][0],
            saved["debug_sessions"][0],
            saved["ai_handoffs"][0],
            saved["live_record"]["lessons"]["insights"][0],
            saved["live_record"]["architecture"]["components"][0],
            saved["live_record"]["vision"]["mission"][0],
        ]
        for record in records:
            for field, value in ATTRIBUTION.items():
                self.assertEqual(record[field], value)
            self.assertTrue(record["timestamp"])
            self.assertEqual(record["status"], "active")

    def test_old_records_remain_unattributed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project.json"
            old_record = {"decision": "Historical decision", "reason": "Legacy"}
            path.write_text(json.dumps({"decisions": [old_record]}), encoding="utf-8")

            saved = durable_memory_write(
                path,
                mutator=lambda memory: {
                    **memory,
                    "decisions": memory["decisions"] + [{"decision": "Future decision"}],
                },
                attribution=ATTRIBUTION,
                create_backup=False,
            )

        self.assertEqual(saved["decisions"][0], old_record)
        self.assertEqual(saved["decisions"][1]["actor"], "codex")

    def test_missing_actor_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project.json"
            saved = durable_memory_write(
                path,
                mutator=lambda memory: {
                    **memory,
                    "decisions": [{"decision": "No detected actor"}],
                },
                attribution={"tool_name": "fo_decide"},
                create_backup=False,
            )

        record = saved["decisions"][0]
        self.assertEqual(record["actor"], "unknown")
        self.assertEqual(record["actor_source"], "none")
        self.assertEqual(record["actor_confidence"], 0.0)
        self.assertEqual(record["session_id"], "unknown-session")

    def test_concurrent_gateway_writes_do_not_lose_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project.json"
            path.write_text(json.dumps({"decisions": []}), encoding="utf-8")

            def append_decision(index):
                durable_memory_write(
                    path,
                    mutator=lambda memory: {
                        **memory,
                        "decisions": memory.get("decisions", []) + [{
                            "id": f"decision-{index}",
                            "decision": f"Decision {index}",
                        }],
                    },
                    attribution={
                        **ATTRIBUTION,
                        "session_id": f"session-{index}",
                    },
                    create_backup=False,
                )

            threads = [threading.Thread(target=append_decision, args=(index,)) for index in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            {record["id"] for record in saved["decisions"]},
            {f"decision-{index}" for index in range(20)},
        )

    def test_resume_state_receives_state_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project.json"
            path.write_text("{}", encoding="utf-8")

            saved = durable_memory_write(
                path,
                mutator=lambda memory: {
                    **memory,
                    "resume_state": {
                        "active_task": "Validate gateway",
                        "current_status": "in_progress",
                    },
                },
                attribution=ATTRIBUTION,
                create_backup=False,
            )

        resume = saved["resume_state"]
        self.assertEqual(resume["actor"], "codex")
        self.assertEqual(resume["tool_name"], "test_tool")
        self.assertEqual(resume["status"], "active")
        self.assertTrue(resume["timestamp"])

    def test_conflict_evidence_uses_gateway_attribution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project.json"
            saved = durable_memory_write(
                path,
                mutator=lambda memory: {
                    "decisions": [{
                        "decision": "Always store API data in English",
                        "reason": "Integration requirement",
                    }],
                },
                attribution=ATTRIBUTION,
                create_backup=False,
            )

        conflicts = detect_conflicts(
            "Never store API data in English",
            "Localization requirement",
            saved["decisions"],
        )
        self.assertEqual(conflicts[0]["existing_actor"], "codex")
        self.assertEqual(conflicts[0]["existing_actor_source"], "client_actor")
        self.assertTrue(conflicts[0]["timestamp"])

    def test_project_manager_save_uses_gateway_defaults(self):
        def mock_committed_updater(project_id, memory):
            return "/mock/committed/path"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(multi_project_manager, "PROJECTS_V2_DIR", root):
                with patch.object(
                    multi_project_manager,
                    "_get_committed_knowledge_updater",
                    return_value=mock_committed_updater
                ):
                    saved = multi_project_manager.save_project_memory(
                        "project-manager",
                        {
                            "project_info": {"name": "Demo"},
                            "decisions": [{"decision": "Manager write"}],
                        },
                    )
            memory = json.loads(
                (root / "project-manager.json").read_text(encoding="utf-8")
            )

        self.assertTrue(saved)
        self.assertEqual(memory["decisions"][0]["actor"], "unknown")
        self.assertEqual(memory["decisions"][0]["tool_name"], "save_project_memory")

    def test_snapshot_update_replaces_same_record_without_duplication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project.json"
            path.write_text(json.dumps({
                "decisions": [{"id": "decision-1", "decision": "Use JSON", "status": "active"}],
            }), encoding="utf-8")

            saved = durable_memory_write(
                path,
                updated={
                    "decisions": [{
                        "id": "decision-1",
                        "decision": "Use JSON",
                        "status": "superseded",
                    }],
                },
                attribution=ATTRIBUTION,
                create_backup=False,
            )

        self.assertEqual(len(saved["decisions"]), 1)
        self.assertEqual(saved["decisions"][0]["status"], "superseded")
        self.assertNotIn("actor", saved["decisions"][0])

    def test_resume_state_write_uses_gateway(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = root / "project-resume.json"
            project_file.write_text("{}", encoding="utf-8")
            with patch.object(resume_state, "PROJECTS_DIR", root):
                result = resume_state.save_resume_state(
                    "project-resume",
                    "Continue validation",
                    attribution=ATTRIBUTION,
                )
            memory = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertNotIn("error", result)
        self.assertEqual(memory["resume_state"]["actor"], "codex")
        self.assertEqual(memory["resume_state"]["tool_name"], "test_tool")
        self.assertEqual(memory["resume_state"]["status"], "active")


if __name__ == "__main__":
    unittest.main()
