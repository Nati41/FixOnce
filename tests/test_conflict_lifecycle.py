#!/usr/bin/env python3
"""Persistent decision-conflict lifecycle tests."""

import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "mcp_server"))


class _FakeFastMCP:
    def __init__(self, *_args, **_kwargs):
        pass

    def tool(self, *_args, **_kwargs):
        def decorator(func):
            return func
        return decorator


sys.modules.setdefault("fastmcp", types.SimpleNamespace(FastMCP=_FakeFastMCP))

from core.conflict_lifecycle import (
    bound_conflicts,
    resolve_decision_conflicts,
    upsert_decision_conflicts,
)
from core.durable_memory import durable_memory_write
import mcp_memory_server_v2 as server


ATTRIBUTION = {
    "actor": "codex",
    "actor_source": "client_actor",
    "actor_confidence": 1.0,
    "session_id": "session-conflict",
    "tool_name": "fo_decide",
}

HIGH_CONFLICT = {
    "type": "CONTRADICTION",
    "severity": "HIGH",
    "existing_decision": "Always store API data in English",
    "existing_reason": "Integration consistency",
    "existing_actor": "claude",
    "existing_actor_source": "client_actor",
    "timestamp": "2026-06-01T10:00:00",
    "topics": ["api", "data", "language"],
    "message": "Direct contradiction detected",
}


class TestConflictLifecycle(unittest.TestCase):
    def _activate(self, root: Path, memory):
        project_id = "project-conflicts"
        project_file = root / f"{project_id}.json"
        project_file.write_text(json.dumps(memory), encoding="utf-8")
        session = server.SessionContext(project_id=project_id, working_dir=str(root))
        session.initialized_at = "2026-06-07T08:00:00"
        patches = [
            patch.object(server, "DATA_DIR", root),
            patch.object(server, "INDEX_FILE", root / "project_index.json"),
            patch.object(server, "_get_session", return_value=session),
            patch.object(server, "_universal_gate", return_value=("", "")),
            patch.object(server, "_require_session", return_value=None),
            patch.object(server, "_intervention_policy_available", False),
            patch.object(server, "_resolve_actor_identity", return_value={
                "editor": "codex",
                "source": "client_actor",
                "confidence": 1.0,
            }),
            patch.object(server, "_load_project_semantic", return_value=None),
            patch.object(server, "_log_mcp_activity", return_value=None),
            patch.object(server, "_track_roi_event", return_value=None),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return project_file

    def test_repeated_detection_deduplicates_and_increments_count(self):
        memory, ids = upsert_decision_conflicts(
            {},
            [HIGH_CONFLICT],
            "Never store API data in English",
            "Localization requirement",
            attribution=ATTRIBUTION,
            now="2026-06-07T08:00:00",
        )
        memory, repeated_ids = upsert_decision_conflicts(
            memory,
            [HIGH_CONFLICT],
            "Never store API data in English",
            "Localization requirement",
            attribution=ATTRIBUTION,
            now="2026-06-07T09:00:00",
        )

        self.assertEqual(ids, repeated_ids)
        self.assertEqual(len(memory["decision_conflicts"]), 1)
        self.assertEqual(memory["decision_conflicts"][0]["seen_count"], 2)
        self.assertEqual(memory["decision_conflicts"][0]["last_seen"], "2026-06-07T09:00:00")

    def test_blocked_decision_persists_conflict_without_decision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, {
                "decisions": [{
                    "decision": "Always store API data in English",
                    "reason": "Integration consistency",
                    "actor": "claude",
                    "actor_source": "client_actor",
                    "timestamp": "2026-06-01T10:00:00",
                }],
            })

            result = server.log_decision(
                "Never store API data in English",
                "Localization requirement",
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertIn("Decision NOT logged", result)
        self.assertEqual(len(saved["decisions"]), 1)
        self.assertEqual(len(saved["decision_conflicts"]), 1)
        self.assertEqual(saved["decision_conflicts"][0]["status"], "open")

    def test_similar_decision_warning_does_not_block_logging(self):
        """Similarity alone should not block existing warning-level behavior."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, {
                "decisions": [{
                    "decision": "Use REST API for auth",
                    "reason": "Conventional API shape",
                }],
            })

            result = server.log_decision(
                "Use REST API for authentication",
                "Keep auth endpoints conventional",
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertIn("Decision recorded", result)
        self.assertEqual(len(saved["decisions"]), 2)
        self.assertNotIn("Decision NOT logged", result)
        self.assertEqual(saved.get("decision_conflicts", []), [])

    def test_force_resolves_only_matching_conflict(self):
        unrelated_memory, _ = upsert_decision_conflicts(
            {},
            [{
                **HIGH_CONFLICT,
                "existing_decision": "Always use local authentication",
                "existing_reason": "Offline support",
                "topics": ["auth"],
            }],
            "Never use local authentication",
            "Cloud-only product",
            attribution=ATTRIBUTION,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, {
                "decisions": [{
                    "decision": "Always store API data in English",
                    "reason": "Integration consistency",
                }],
                "decision_conflicts": unrelated_memory["decision_conflicts"],
            })

            server.log_decision(
                "Never store API data in English",
                "Localization requirement",
                force=True,
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        statuses = {item["proposed_decision"]["decision"]: item["status"]
                    for item in saved["decision_conflicts"]}
        self.assertEqual(statuses["Never store API data in English"], "resolved")
        self.assertEqual(statuses["Never use local authentication"], "open")
        matching = next(
            item for item in saved["decision_conflicts"]
            if item["proposed_decision"]["decision"] == "Never store API data in English"
        )
        self.assertEqual(matching["resolution"]["action"], "accepted_override")

    def test_supersede_marks_matching_conflict_superseded(self):
        memory, _ = upsert_decision_conflicts(
            {"decisions": [{
                "decision": "Always store API data in English",
                "reason": "Integration consistency",
            }]},
            [HIGH_CONFLICT],
            "Never store API data in English",
            "Localization requirement",
            attribution=ATTRIBUTION,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, memory)

            server.supersede_decision(
                "Always store API data in English",
                "Store API data using locale-neutral keys",
                "Supports localization",
                "Requirements changed",
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        conflict = saved["decision_conflicts"][0]
        self.assertEqual(conflict["status"], "superseded")
        self.assertEqual(conflict["resolution"]["action"], "decision_superseded")

    def test_manual_resolution_persists_attribution(self):
        memory, ids = upsert_decision_conflicts(
            {},
            [HIGH_CONFLICT],
            "Never store API data in English",
            "Localization requirement",
            attribution=ATTRIBUTION,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = self._activate(root, memory)

            result = server.fo_decide(
                "",
                "Reviewed and accepted as non-conflicting.",
                action=f"resolve:{ids[0]}",
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertIn("Resolved conflict", result)
        resolution = saved["decision_conflicts"][0]["resolution"]
        self.assertEqual(resolution["actor"], "codex")
        self.assertEqual(resolution["actor_source"], "client_actor")
        self.assertEqual(resolution["action"], "manual_resolution")

    def test_brief_excludes_terminal_conflicts_and_old_audits(self):
        memory, _ = upsert_decision_conflicts(
            {
                "project_info": {"name": "Demo"},
                "live_record": {
                    "intent": {},
                    "architecture": {"components": []},
                    "lessons": {"insights": []},
                },
                "decisions": [],
                "avoid": [],
                "debug_sessions": [],
                "agent_audit": [{
                    "gate": "decision_conflict_gate",
                    "verdict": "block",
                }],
            },
            [HIGH_CONFLICT],
            "Never store API data in English",
            "Localization requirement",
            attribution=ATTRIBUTION,
        )
        memory, _ = resolve_decision_conflicts(
            memory,
            status="resolved",
            action="manual_resolution",
            reason="Reviewed",
            attribution=ATTRIBUTION,
            conflict_ids=[memory["decision_conflicts"][0]["id"]],
        )

        brief = server._format_deep_project_brief(memory)

        self.assertIn("📊 Project Knowledge: 0 Decisions · 0 Solved Bugs · 0 Avoid Patterns", brief)
        self.assertNotIn("decision conflict(s)", brief)
        self.assertNotIn(memory["decision_conflicts"][0]["id"], brief)

    def test_concurrent_creation_loses_no_conflicts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project.json"
            path.write_text("{}", encoding="utf-8")

            def create(index):
                evidence = [{
                    **HIGH_CONFLICT,
                    "existing_decision": f"Always use storage backend {index}",
                }]

                def mutate(memory):
                    memory, _ = upsert_decision_conflicts(
                        memory,
                        evidence,
                        f"Never use storage backend {index}",
                        "Concurrent proposal",
                        attribution={
                            **ATTRIBUTION,
                            "session_id": f"session-{index}",
                        },
                    )
                    return memory

                durable_memory_write(
                    path,
                    mutator=mutate,
                    attribution=ATTRIBUTION,
                    create_backup=False,
                )

            threads = [threading.Thread(target=create, args=(index,)) for index in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(saved["decision_conflicts"]), 20)

    def test_terminal_records_are_bounded_but_open_records_are_not_trimmed(self):
        conflicts = [
            {
                "id": f"open-{index}",
                "status": "open",
                "updated_at": f"2026-06-07T08:{index:02d}:00",
            }
            for index in range(205)
        ] + [
            {
                "id": f"resolved-{index}",
                "status": "resolved",
                "updated_at": f"2026-06-{(index % 28) + 1:02d}T09:00:00",
            }
            for index in range(250)
        ]

        bounded = bound_conflicts(conflicts)

        self.assertEqual(
            len([item for item in bounded if item["status"] == "open"]),
            205,
        )
        self.assertEqual(
            len([item for item in bounded if item["status"] == "resolved"]),
            200,
        )

    def test_portable_conflict_is_updated_by_id_after_resolution(self):
        memory, ids = upsert_decision_conflicts(
            {},
            [HIGH_CONFLICT],
            "Never store API data in English",
            "Localization requirement",
            attribution=ATTRIBUTION,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            server._persist_portable_team_memory("project-conflicts", temp_dir, memory)
            memory, _ = resolve_decision_conflicts(
                memory,
                status="resolved",
                action="manual_resolution",
                reason="Reviewed",
                attribution=ATTRIBUTION,
                conflict_ids=ids,
            )
            server._persist_portable_team_memory("project-conflicts", temp_dir, memory)
            portable = json.loads(
                (Path(temp_dir) / ".fixonce" / "team_memory.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(len(portable["decision_conflicts"]), 1)
        self.assertEqual(portable["decision_conflicts"][0]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
