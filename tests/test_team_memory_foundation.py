#!/usr/bin/env python3
"""Forward-only tests for the Team Memory foundation."""

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

from core.agent_context import AgentContext
from core.policy_engine import detect_conflicts, validate_decision
from core.safe_file import atomic_json_update
import mcp_memory_server_v2 as server


class TestTeamMemoryFoundation(unittest.TestCase):
    def test_agent_context_exposes_canonical_attribution(self):
        context = AgentContext(
            actor_name="codex",
            actor_source="client_actor",
            actor_confidence=1.0,
            tool_name="fo_decide",
            intent="decision",
            session_id="session-1",
            project_id="project-1",
        )

        self.assertEqual(context.attribution(), {
            "actor": "codex",
            "actor_source": "client_actor",
            "actor_confidence": 1.0,
            "session_id": "session-1",
            "tool_name": "fo_decide",
        })

    def test_only_new_records_receive_fallback_attribution(self):
        old_record = {"decision": "Existing decision", "reason": "Existing reason"}
        new_record = {"decision": "New decision", "reason": "New reason"}
        base = {"decisions": [dict(old_record)]}
        updated = {"decisions": [dict(old_record), new_record]}

        with patch.object(server, "_new_record_attribution", return_value={
            "actor": "claude",
            "actor_source": "client_actor",
            "actor_confidence": 1.0,
            "session_id": "session-2",
            "tool_name": "memory_write",
        }):
            server._ensure_new_durable_attribution(base, updated)

        self.assertNotIn("actor", updated["decisions"][0])
        self.assertEqual(updated["decisions"][1]["actor"], "claude")
        self.assertEqual(updated["decisions"][1]["session_id"], "session-2")

    def test_structured_handoff_contains_required_fields(self):
        with patch.object(server, "_new_record_attribution", return_value={
            "actor": "codex",
            "actor_source": "client_actor",
            "actor_confidence": 1.0,
            "session_id": "session-3",
            "tool_name": "fo_init",
        }):
            handoff = server._create_handoff_record(
                "claude",
                "codex",
                completed_work="Implemented authentication.",
                remaining_work="Validate logout behavior.",
                risks="Token expiry edge case remains.",
                next_action="Run authentication integration tests.",
            )

        for field in (
            "from_actor", "to_actor", "completed_work", "remaining_work",
            "risks", "next_action", "actor", "actor_source",
            "actor_confidence", "session_id", "tool_name",
        ):
            self.assertIn(field, handoff)
        self.assertEqual(handoff["quality_audit"]["status"], "pass")

    def test_conflict_evidence_contains_existing_actor_provenance(self):
        decisions = [{
            "decision": "Always store API data in English",
            "reason": "External integrations require English",
            "actor": "claude",
            "actor_source": "client_actor",
            "timestamp": "2026-06-01T10:00:00",
        }]

        conflicts = detect_conflicts(
            "Never store API data in English",
            "New localization requirement",
            decisions,
        )
        self.assertEqual(conflicts[0]["existing_actor"], "claude")
        self.assertEqual(conflicts[0]["existing_actor_source"], "client_actor")

        valid, message, _ = validate_decision(
            "Never store API data in English",
            "New localization requirement",
            decisions,
        )
        self.assertFalse(valid)
        self.assertIn("actor=claude", message)
        self.assertIn("2026-06-01T10:00:00", message)

    def test_supporting_decisions_do_not_create_conflicts(self):
        """Regression test: decisions that support a vision should not conflict."""
        # "No external database" and "Use local storage" are semantically aligned
        supporting_cases = [
            ("No external database in MVP", "Use local JSON file storage"),
            ("No external database", "Use local database"),
            ("No external storage", "Use local storage"),
            ("No external API calls", "Use internal API"),
        ]
        for vision, decision in supporting_cases:
            conflicts = detect_conflicts(
                decision, "", [{"decision": vision, "reason": ""}]
            )
            self.assertEqual(
                len(conflicts), 0,
                f"False positive: {decision!r} should NOT conflict with {vision!r}"
            )

    def test_true_contradictions_still_create_conflicts(self):
        """Ensure real contradictions are still detected after false-positive fix."""
        contradiction_cases = [
            ("No database", "Use database"),
            ("No external API", "Use external API"),
            ("Never store in English", "Store data in English"),
            ("Always store in English", "Never store in English"),
        ]
        for existing, proposed in contradiction_cases:
            conflicts = detect_conflicts(
                proposed, "", [{"decision": existing, "reason": ""}]
            )
            self.assertGreater(
                len(conflicts), 0,
                f"Missing conflict: {proposed!r} SHOULD conflict with {existing!r}"
            )

    def test_conflict_severity_explicit_negation_is_high(self):
        """HIGH severity only for explicit negation where target appears in both texts."""
        high_conflict_cases = [
            ("Use PostgreSQL for storage", "Do not use PostgreSQL"),
            ("Always store in English", "Never store in English"),
            ("Use JSON format", "Don't use JSON"),
        ]
        for decision1, decision2 in high_conflict_cases:
            conflicts = detect_conflicts(
                decision2, "", [{"decision": decision1, "reason": ""}]
            )
            self.assertEqual(len(conflicts), 1, f"Expected conflict: {decision1} vs {decision2}")
            self.assertEqual(
                conflicts[0]["severity"], "HIGH",
                f"Expected HIGH severity for: {decision1} vs {decision2}, got {conflicts[0]['severity']}"
            )

    def test_conflict_severity_antonym_pairs_are_medium_not_high(self):
        """Antonym pair matches (use/avoid) should be MEDIUM, not HIGH."""
        weak_conflict_cases = [
            ("Use JSON storage", "Avoid JSON in production"),
            ("Use local storage", "Prefer remote storage"),
        ]
        for decision1, decision2 in weak_conflict_cases:
            conflicts = detect_conflicts(
                decision2, "", [{"decision": decision1, "reason": ""}]
            )
            if conflicts:
                self.assertNotEqual(
                    conflicts[0]["severity"], "HIGH",
                    f"Antonym match should NOT be HIGH: {decision1} vs {decision2}"
                )

    def test_meta_descriptions_do_not_conflict(self):
        """Meta-descriptions like 'what we avoid' should not trigger conflicts."""
        # The word 'avoid' in 'what we avoid' is describing the document, not a rule
        vision_with_meta = "TaskPilot Vision: simplicity over features"
        vision_reason = "Founding vision - defines what we build and what we explicitly avoid"

        conflicts = detect_conflicts(
            "Use JSON storage", "Local persistence",
            [{"decision": vision_with_meta, "reason": vision_reason}]
        )
        # Should not have HIGH conflict just because reason contains 'avoid'
        high_conflicts = [c for c in conflicts if c["severity"] == "HIGH"]
        self.assertEqual(
            len(high_conflicts), 0,
            f"Meta-description should not cause HIGH conflict, got: {conflicts}"
        )

    def test_no_external_database_vs_use_local_json_no_conflict(self):
        """Specific regression: vision 'No external database' + decision 'Use local JSON' should align."""
        conflicts = detect_conflicts(
            "TaskPilot uses a local JSON file as storage",
            "Local persistence for MVP",
            [{"decision": "No external database in MVP", "reason": "Keep it simple"}]
        )
        high_conflicts = [c for c in conflicts if c["severity"] == "HIGH"]
        self.assertEqual(
            len(high_conflicts), 0,
            f"Supporting decision should not have HIGH conflict: {conflicts}"
        )

    def test_compatible_statements_same_topic_no_conflict(self):
        """Compatible statements on same topic should not conflict."""
        compatible_cases = [
            ("Store data in JSON format", "Use JSON for persistence"),
            ("Use local storage", "Store data locally"),
            ("No external dependencies", "Keep dependencies internal"),
        ]
        for existing, proposed in compatible_cases:
            conflicts = detect_conflicts(
                proposed, "", [{"decision": existing, "reason": ""}]
            )
            high_conflicts = [c for c in conflicts if c["severity"] == "HIGH"]
            self.assertEqual(
                len(high_conflicts), 0,
                f"Compatible statements should not conflict: {existing} vs {proposed}"
            )

    def test_persistent_audit_is_bounded_and_portable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_id = "project-team"
            project_file = root / f"{project_id}.json"
            project_file.write_text(json.dumps({"agent_audit": []}), encoding="utf-8")
            session = server.SessionContext(project_id=project_id, working_dir=temp_dir)
            session.initialized_at = "2026-06-07T08:00:00"
            entries = [
                {
                    "timestamp": f"2026-06-07T08:{index:02d}:00",
                    "session_id": "session-4",
                    "gate": "decision_conflict_gate",
                    "verdict": "warn",
                    "actor_name": "codex",
                }
                for index in range(205)
            ]

            with patch.object(server, "DATA_DIR", root), \
                 patch.object(server, "_get_session", return_value=session):
                server._persist_agent_audit(project_id, entries)

            saved = json.loads(project_file.read_text(encoding="utf-8"))
            portable = json.loads(
                (root / ".fixonce" / "team_memory.json").read_text(encoding="utf-8")
            )

        self.assertEqual(len(saved["agent_audit"]), 200)
        self.assertEqual(len(portable["agent_audit"]), 200)

    def test_atomic_updates_preserve_concurrent_appends(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"
            path.write_text(json.dumps({"decisions": []}), encoding="utf-8")

            def append_decision(index):
                atomic_json_update(
                    str(path),
                    lambda data: {
                        **data,
                        "decisions": list(data.get("decisions", [])) + [{"id": index}],
                    },
                    default={"decisions": []},
                    create_backup=False,
                )

            threads = [threading.Thread(target=append_decision, args=(index,)) for index in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual({item["id"] for item in saved["decisions"]}, set(range(20)))

    def test_portable_team_memory_merges_concurrent_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def persist(index):
                memory = {
                    "agent_audit": [{
                        "timestamp": f"2026-06-07T08:00:{index:02d}",
                        "session_id": f"session-{index}",
                        "gate": "risk_gate",
                    }],
                    "ai_handoffs": [],
                }
                server._persist_portable_team_memory("project-team", temp_dir, memory)

            threads = [threading.Thread(target=persist, args=(index,)) for index in range(10)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            saved = json.loads(
                (root / ".fixonce" / "team_memory.json").read_text(encoding="utf-8")
            )

        self.assertEqual(len(saved["agent_audit"]), 10)

    def test_brief_reports_multi_agent_state(self):
        memory = {
            "project_info": {"name": "Demo"},
            "live_record": {
                "intent": {"current_goal": "Ship", "next_step": "Test"},
                "architecture": {"components": []},
                "lessons": {"insights": []},
            },
            "active_ais": {
                "codex": {
                    "is_primary": True,
                    "actor_source": "client_actor",
                    "actor_confidence": 1.0,
                }
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
            "agent_audit": [{
                "gate": "decision_conflict_gate",
                "verdict": "block",
                "actor_name": "codex",
                "tool_name": "fo_decide",
                "timestamp": "2026-06-07T08:00:00",
                "evidence": {"conflicts": [{
                    "existing_actor": "claude",
                    "existing_actor_source": "client_actor",
                    "timestamp": "2026-06-07T07:00:00",
                }]},
            }],
            "decision_conflicts": [{
                "id": "conflict-demo",
                "status": "open",
                "severity": "HIGH",
                "existing_decision": {
                    "decision": "Use SQLite",
                    "actor": "claude",
                },
                "proposed_decision": {
                    "decision": "Never use SQLite",
                    "actor": "codex",
                },
                "last_seen": "2026-06-07T08:00:00",
            }],
            "ai_handoffs": [{
                "from_actor": "claude",
                "to_actor": "codex",
                "next_action": "Run integration tests.",
            }],
        }

        brief = server._format_deep_project_brief(memory)

        self.assertIn("## Multi-Agent State", brief)
        self.assertIn("Active agents: codex", brief)
        self.assertIn("Attribution coverage:", brief)
        self.assertIn("Recent handoffs: 1", brief)
        self.assertIn("Unresolved conflicts: 1", brief)
        self.assertIn("conflict-demo", brief)


if __name__ == "__main__":
    unittest.main()
