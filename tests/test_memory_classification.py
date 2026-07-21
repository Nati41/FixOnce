#!/usr/bin/env python3
"""Regression tests for solved bug classification and category-agnostic recall."""

import json
import sys
import tempfile
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

import mcp_memory_server_v2 as server


class TestMemoryClassification(unittest.TestCase):
    def _activate_temp_session(self, temp_root: Path, memory=None):
        projects_dir = temp_root / "projects_v2"
        projects_dir.mkdir()
        project_id = "proj-memory-classification"
        project_file = projects_dir / f"{project_id}.json"
        project_file.write_text(json.dumps(memory or {
            "project_info": {"name": "Memory Classification", "working_dir": str(temp_root)},
            "live_record": {
                "intent": {},
                "architecture": {"summary": "Test project", "components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }), encoding="utf-8")

        patches = [
            patch.object(server, "DATA_DIR", projects_dir),
            patch.object(server, "USER_DATA_DIR", temp_root),
            patch.object(server, "SESSION_FILE", temp_root / "mcp_session.json"),
            patch.object(server, "COMPLIANCE_FILE", temp_root / "mcp_compliance.json"),
            patch.object(server, "AI_CONNECTIONS_FILE", temp_root / "ai_connections.json"),
            patch.object(server, "INDEX_FILE", temp_root / "project_index.json"),
            patch.object(server, "_session_registry_available", False),
            patch.object(server, "_load_project_semantic", return_value=None),
            patch.object(server, "_track_roi_event", return_value=None),
            patch.object(server, "_log_mcp_activity", return_value=None),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        server._set_session(project_id, str(temp_root))
        server._persist_session(project_id, str(temp_root))
        server._mark_session_initialized()
        return project_file

    def test_search_finds_solved_bug_stored_as_insight(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {
                    "insights": [{
                        "text": "Windows TestUser login crash was fixed by removing login auto-start and requiring manual open.",
                        "timestamp": "2026-06-01T10:00:00",
                        "use_count": 0,
                    }],
                    "failed_attempts": [],
                },
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("TestUser login crash")

        self.assertIn("Found 1 match", result)
        self.assertIn("TestUser login crash", result)

    def test_search_finds_solved_bug_stored_as_decision(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "Preserve Codex TOML sections during MCP registration repair.",
                "reason": "This fixed Codex MCP reconnect failures without overwriting user config.",
                "timestamp": "2026-06-01T10:00:00",
            }],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("Codex TOML repair")

        self.assertIn("Found 1 match", result)
        self.assertIn("Decision", result)

    def test_search_works_across_component_history(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": [{
                    "name": "MCP reconnect action",
                    "status": "done",
                    "desc": "Committed MCP reconnect console flash fix for packaged Windows startup.",
                    "updated_at": "2026-06-01T10:00:00",
                }]},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("MCP reconnect")

        self.assertIn("Found 1 match", result)
        self.assertIn("Component history", result)

    def test_avoid_patterns_remain_searchable(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [{
                "what": "Do not edit project_context.py without full test cycle",
                "reason": "It previously caused memory context regressions.",
                "timestamp": "2026-06-01T10:00:00",
            }],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("project_context test cycle")

        self.assertIn("Found 1 match", result)
        self.assertIn("Avoid", result)

    def test_normal_context_update_does_not_create_fake_solved_bug(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = self._activate_temp_session(Path(temp_dir))

            result = server.fo_sync(
                goal="Prepare release notes",
                work_area="release docs",
                last_change="Updated dashboard wording",
                next_step="Review copy",
            )

            memory = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertEqual(result, "Synced.")
        self.assertEqual(memory.get("debug_sessions", []), [])

    def test_solved_insight_is_auto_classified_as_debug_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = self._activate_temp_session(Path(temp_dir))

            server.update_live_record("lessons", json.dumps({
                "insight": "NoneType.buffer startup crash was fixed by guarding stdio stream access."
            }))
            memory = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertEqual(len(memory.get("debug_sessions", [])), 1)
        self.assertEqual(memory["debug_sessions"][0]["source"], "auto_classified:insight")

    def test_done_component_fix_is_auto_classified_as_debug_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = self._activate_temp_session(Path(temp_dir))

            server.update_component_status(
                "MCP reconnect",
                "done",
                "Fixed packaged MCP reconnect timeout during Windows startup.",
            )
            memory = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertEqual(len(memory.get("debug_sessions", [])), 1)
        self.assertEqual(memory["debug_sessions"][0]["source"], "auto_classified:component_status")

    def test_deep_brief_includes_core_trust_sections(self):
        memory = {
            "project_info": {"name": "Trust Project", "working_dir": "/tmp/trust"},
            "live_record": {
                "intent": {
                    "current_goal": "Make memory trustworthy for new agents",
                    "work_area": "memory trust",
                    "last_change": "Validated Windows TestUser memory recall",
                    "next_step": "Implement deep onboarding brief",
                    "updated_at": "2026-06-02T19:53:33",
                    "actor": "Codex",
                },
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "Before every Windows build, run runtime QA before TestUser.",
                "reason": "Avoid repeating costly Windows/TestUser debugging loops.",
                "timestamp": "2026-06-02T19:53:20",
                "actor": "Codex",
            }],
            "avoid": [{
                "what": "Do not use TestUser as the primary debugging loop.",
                "reason": "It previously consumed several days.",
                "timestamp": "2026-06-02T19:54:00",
                "actor": "Codex",
            }],
            "debug_sessions": [{
                "problem": "MCP reconnect timeout during packaged Windows startup",
                "solution": "Guarded stdio startup and added packaged --mcp diagnostics.",
                "resolved_at": "2026-06-02T20:00:00",
                "reuse_count": 2,
                "actor": "Codex",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_brief()

        self.assertIn("## Decisions", result)
        self.assertIn("Before every Windows build", result)
        self.assertIn("## Do Not Repeat", result)
        self.assertIn("TestUser as the primary debugging loop", result)
        self.assertIn("## Solved Bugs", result)
        self.assertIn("MCP reconnect timeout", result)
        self.assertIn("Next step: Implement deep onboarding brief", result)

    def test_project_vision_appears_before_tactical_context_in_brief(self):
        memory = {
            "project_info": {"name": "Mario Builder", "working_dir": "/tmp/mario"},
            "live_record": {
                "vision": {
                    "mission": [{
                        "text": "Help players create expressive platforming levels.",
                        "reason": "The project exists to make creative level design accessible.",
                        "created_at": "2026-06-01T10:00:00",
                        "actor": "designer",
                        "status": "active",
                    }],
                    "current_direction": [{
                        "text": "Prioritize a polished editor loop before adding more enemies.",
                        "reason": "The editor loop defines the core product experience.",
                        "created_at": "2026-06-01T10:05:00",
                        "actor": "designer",
                        "status": "active",
                    }],
                    "non_negotiables": [],
                    "success_criteria": [],
                    "long_term_goal": [],
                    "out_of_scope": [],
                },
                "intent": {"current_goal": "Implement tile palette"},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_brief(mode="expanded")

        self.assertLess(result.index("## Project Vision"), result.index("## Project Context"))
        self.assertIn("Help players create expressive platforming levels", result)
        self.assertIn("Prioritize a polished editor loop", result)

    def test_non_negotiables_appear_in_deep_brief(self):
        memory = {
            "live_record": {
                "vision": {
                    "mission": [],
                    "current_direction": [],
                    "non_negotiables": [{
                        "text": "Never store customer secrets in plaintext.",
                        "reason": "Privacy and compliance are product guardrails.",
                        "created_at": "2026-06-01T10:00:00",
                        "actor": "security",
                        "status": "active",
                    }],
                    "success_criteria": [],
                    "long_term_goal": [],
                    "out_of_scope": [],
                },
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_brief(mode="expanded")

        self.assertIn("### Non-Negotiables", result)
        self.assertIn("Never store customer secrets in plaintext", result)

    def test_superseded_vision_remains_traceable_in_expanded_brief(self):
        memory = {
            "live_record": {
                "vision": {},
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = self._activate_temp_session(Path(temp_dir), memory)
            server.update_live_record("vision", json.dumps({
                "mission": "Help teams understand customer health.",
                "reason": "Initial product framing.",
            }))
            server.update_live_record("vision", json.dumps({
                "mission": "Help account teams prevent customer churn.",
                "reason": "Narrowed the mission around retention.",
            }))

            result = server.fo_brief(mode="expanded")
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        mission_items = saved["live_record"]["vision"]["mission"]
        self.assertEqual(mission_items[0]["status"], "superseded")
        self.assertIsNotNone(mission_items[0]["superseded_by"])
        self.assertIn("Help teams understand customer health", result)
        self.assertIn("status=superseded", result)
        self.assertIn("Reason for change: Narrowed the mission around retention", result)

    def test_mission_and_success_criteria_are_distinguishable(self):
        memory = {
            "live_record": {
                "vision": {},
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = self._activate_temp_session(Path(temp_dir), memory)

            server.update_live_record("vision", json.dumps({
                "mission": "Make loan approvals understandable to applicants.",
                "success_criteria": [
                    "Applicants can explain every approval or rejection reason.",
                    "Support tickets about unclear decisions decrease."
                ],
                "reason": "Separate purpose from measurable outcomes.",
            }))
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        vision = saved["live_record"]["vision"]
        self.assertEqual(vision["mission"][0]["text"], "Make loan approvals understandable to applicants.")
        self.assertEqual(len(vision["success_criteria"]), 2)
        self.assertNotEqual(vision["mission"][0]["text"], vision["success_criteria"][0]["text"])

    def test_vision_audit_checks_required_project_purpose_fields(self):
        memory = {
            "live_record": {
                "vision": {
                    "mission": [{
                        "text": "Make operations work visible across teams.",
                        "created_at": "2026-06-01T10:00:00",
                        "actor": "product",
                        "status": "active",
                    }],
                    "success_criteria": [],
                    "non_negotiables": [],
                },
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)
            audit = json.loads(server.fo_vision(action="audit"))

        self.assertEqual(audit["status"], "needs_context")
        self.assertIn("missing_success_criteria", audit["issues"])
        self.assertIn("missing_non_negotiables", audit["issues"])

    def test_vision_platform_logic_has_no_project_specific_content(self):
        forbidden = {
            "fixonce", "mcp", "codex", "claude", "cursor", "testuser",
            "windows", "installer", "startup", "shortcut",
        }
        platform_terms = set(server._VISION_FIELDS) | set(server._TRUST_KEYWORDS_HIGH_VALUE)
        self.assertFalse(platform_terms & forbidden)

    def test_do_not_repeat_digest_includes_avoid_failed_and_solved_bug_lessons(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {
                    "insights": [],
                    "failed_attempts": [{
                        "text": "Tried build-install-TestUser loop first; it was too slow.",
                        "timestamp": "2026-06-02T18:00:00",
                        "actor": "Claude",
                    }],
                },
            },
            "decisions": [],
            "avoid": [{
                "what": "Do not reintroduce login auto-start.",
                "reason": "Clean user startup crashed before health passed.",
                "timestamp": "2026-06-02T18:30:00",
            }],
            "debug_sessions": [{
                "problem": "Windows TestUser login crash",
                "solution": "Removed login auto-start and require manual open.",
                "resolved_at": "2026-06-02T19:00:00",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_do_not_repeat()

        self.assertIn("Do not reintroduce login auto-start", result)
        self.assertIn("build-install-TestUser loop", result)
        self.assertIn("Windows TestUser login crash", result)

    def test_provenance_uses_real_timestamp_and_actor_when_present(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "Preserve Codex TOML sections during repair.",
                "reason": "Avoid overwriting user config.",
                "timestamp": "2026-06-01T10:00:00",
                "actor": "Codex",
            }],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_brief()

        self.assertIn("when=2026-06-01 10:00:00", result)
        self.assertIn("actor=Codex", result)
        self.assertIn("source=decision", result)

    def test_missing_timestamp_and_actor_are_reported_honestly(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "Keep regular fo_init short.",
                "reason": "Deep context belongs in fo_brief.",
            }],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_brief()

        self.assertIn("when=timestamp unavailable", result)
        self.assertIn("actor=source unknown", result)

    def test_regular_fo_init_remains_short(self):
        memory = {
            "project_info": {"name": "Short Init", "working_dir": "/tmp/short"},
            "live_record": {
                "intent": {
                    "current_goal": "Keep opener short",
                    "work_area": "session opening",
                    "last_change": "Added deep brief separately",
                    "next_step": "Run tests",
                    "updated_at": "2026-06-02T19:53:33",
                },
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "Decision that should only appear in fo_brief.",
                "reason": "fo_init must remain minimal.",
            }],
            "avoid": [{
                "what": "Avoid noisy init dumps.",
                "reason": "Agents need a concise opener.",
            }],
            "debug_sessions": [{
                "problem": "Solved bug that should not appear in fo_init",
                "solution": "Use fo_brief for deep context.",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)
            with patch.object(server, "_get_project_id", return_value="proj-memory-classification"), \
                 patch.object(server, "_get_live_errors", return_value=[]), \
                 patch.object(server, "_get_auto_fixes", return_value=[]), \
                 patch.object(server, "_resume_state_available", False):
                result = server._format_minimal_init(str(Path(temp_dir)))

        self.assertLessEqual(len(result.splitlines()), 12)
        self.assertNotIn("## Decisions", result)
        self.assertNotIn("Solved bug that should not appear", result)

    def test_compact_brief_does_not_cut_long_solved_bug_mid_sentence(self):
        long_solution = (
            "Root cause was startup stdio probing reading NoneType.buffer before the packaged MCP stream existed. "
            "Final fix guarded stream access, fell back to safe stderr logging, and kept reconnect diagnostics available. "
            "Avoid lesson is to validate packaged MCP startup before assuming dashboard telemetry is the source of truth."
        )
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [{
                "problem": "NoneType.buffer startup crash during MCP reconnect",
                "solution": long_solution,
                "resolved_at": "2026-06-03T10:00:00",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_brief()

        solved_line = next(line for line in result.splitlines() if "NoneType.buffer startup crash" in line)
        self.assertFalse(solved_line.endswith("tru..."))
        self.assertTrue(solved_line.endswith(".") or solved_line.endswith("..."))

    def test_expanded_brief_returns_complete_long_solved_bug(self):
        final_sentence = "Next action is to keep this regression covered in packaged MCP startup tests."
        long_solution = (
            "Root cause was startup stdio probing reading NoneType.buffer before the packaged MCP stream existed. "
            "Final fix guarded stream access, fell back to safe stderr logging, and kept reconnect diagnostics available. "
            "Avoid lesson is to validate packaged MCP startup before assuming dashboard telemetry is the source of truth. "
            f"{final_sentence}"
        )
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [{
                "problem": "NoneType.buffer startup crash during MCP reconnect",
                "solution": long_solution,
                "resolved_at": "2026-06-03T10:00:00",
                "actor": "Codex",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_brief(mode="expanded")

        self.assertIn(final_sentence, result)
        self.assertIn("source_type=solved bug", result)
        self.assertIn("actor=Codex", result)
        self.assertIn("timestamp=2026-06-03 10:00:00", result)
        self.assertIn("confidence=high", result)

    def test_expanded_brief_marks_historically_incomplete_stored_text(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "update_component_status MCP tool for AI-managed component statuses",
                "reason": "Allows AI to update component statuses (done/in",
                "timestamp": "2026-03-01T10:00:00",
            }],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_brief(mode="expanded")

        self.assertIn("Allows AI to update component statuses (done/in", result)
        self.assertIn("Note: stored text appears incomplete.", result)

    def test_specific_error_query_ranks_root_cause_solution_above_generic_decision(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "Before every Windows build, run runtime QA before TestUser.",
                "reason": "Avoid repeating costly Windows/TestUser debugging loops.",
                "timestamp": "2026-06-02T19:53:20",
            }],
            "avoid": [],
            "debug_sessions": [{
                "problem": "TestUser startup shortcut NoneType.buffer crash",
                "root_cause": "Startup shortcut launched packaged MCP before stdio stream buffering existed.",
                "solution": "Guarded NoneType.buffer access and regenerated the startup shortcut.",
                "symptoms": ["NoneType.buffer"],
                "resolved_at": "2026-06-03T10:00:00",
                "actor": "Codex",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("TestUser startup shortcut NoneType.buffer", mode="expanded")

        first_result_line = next(line for line in result.splitlines() if line.startswith("> "))
        self.assertIn("Problem:** TestUser startup shortcut NoneType.buffer crash", first_result_line)
        self.assertIn("Root cause:** Startup shortcut launched packaged MCP", result)

    def test_specific_error_ranking_uses_generic_terms_not_project_workflow(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "Run broad release validation before customer testing.",
                "reason": "Broad validation prevents repeating costly debugging loops.",
                "timestamp": "2026-06-02T19:53:20",
            }],
            "avoid": [],
            "debug_sessions": [{
                "problem": "Mario level loader NullPointer crash",
                "root_cause": "The level asset manifest omitted a required spawn point.",
                "solution": "Validate manifest fields before creating the player spawn.",
                "lesson_learned": "Specific asset-loading failures need manifest validation before gameplay tests.",
                "symptoms": ["NullPointer crash"],
                "resolved_at": "2026-06-03T10:00:00",
                "actor": "Codex",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("Mario level loader NullPointer crash", mode="expanded")

        first_result_line = next(line for line in result.splitlines() if line.startswith("> "))
        self.assertIn("Problem:** Mario level loader NullPointer crash", first_result_line)
        self.assertIn("Lesson learned:** Specific asset-loading failures", result)

    def test_memory_quality_audit_detects_missing_context_generically(self):
        record = {
            "problem": "Payment reconciliation bug",
            "solution": "fixed bug",
            "resolved_at": "2026-06-03T10:00:00",
        }

        audit = server._audit_memory_record("solution", record)

        self.assertEqual(audit["status"], "needs_context")
        self.assertIn("missing_root_cause", audit["issues"])
        self.assertIn("missing_lesson_learned", audit["issues"])
        self.assertIn("missing_actor", audit["issues"])

    def test_new_solution_records_receive_actor_timestamp_and_quality_audit(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            project_file = self._activate_temp_session(Path(temp_dir), memory)

            result = server.solution_applied(
                "CRM import TypeError on empty contact list",
                "Guarded empty contact lists before import mapping.",
                "src/importer.py",
            )
            saved = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertEqual(result, "Solution saved.")
        solution = saved["debug_sessions"][0]
        self.assertIn("resolved_at", solution)
        self.assertIn("actor", solution)
        self.assertEqual(solution.get("source_type"), "solution")
        self.assertEqual(solution.get("status"), "active")
        self.assertIn("confidence", solution)
        self.assertIn("quality_audit", solution)
        self.assertIn("missing_root_cause", solution["quality_audit"]["issues"])
        self.assertIn("missing_lesson_learned", solution["quality_audit"]["issues"])

    def test_handoff_quality_audit_flags_incomplete_handoff(self):
        handoff = server._create_handoff_record("agent_a", "agent_b", "2026-06-03T10:00:00")

        self.assertIn("quality_audit", handoff)
        self.assertIn("incomplete_handoff", handoff["quality_audit"]["issues"])
        self.assertIn("missing_next_action", handoff["quality_audit"]["issues"])

    def test_expanded_search_includes_provenance_for_all_matches(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [{
                "decision": "Keep startup shortcut QA before release.",
                "reason": "Startup shortcut failures are user-visible.",
                "timestamp": "2026-06-02T19:53:20",
                "actor": "Claude",
            }],
            "avoid": [{
                "what": "Do not trust startup shortcut telemetry alone.",
                "reason": "Manual MCP launch can work while shortcut launch is broken.",
                "timestamp": "2026-06-02T20:00:00",
                "actor": "Codex",
            }],
            "debug_sessions": [{
                "problem": "Startup shortcut reconnect issue",
                "solution": "Regenerated startup shortcut and validated MCP launch.",
                "resolved_at": "2026-06-03T10:00:00",
                "actor": "Codex",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("startup shortcut", mode="expanded")

        trust_lines = [line for line in result.splitlines() if "Trust: source_type=" in line]
        self.assertGreaterEqual(len(trust_lines), 3)
        for line in trust_lines:
            self.assertIn("source_type=", line)
            self.assertIn("actor=", line)
            self.assertIn("timestamp=", line)
            self.assertIn("status=", line)
            self.assertIn("confidence=", line)

    def test_compact_mode_remains_concise(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [{
                "problem": "Startup shortcut reconnect issue",
                "solution": (
                    "Root cause was a stale shortcut target. "
                    "Final fix regenerated the shortcut and validated launch. "
                    "Avoid lesson is to avoid treating dashboard agent detection as proof that the startup shortcut is valid. "
                    "Next action is to keep shortcut validation in the reconnect QA path. "
                    "The full expanded recall should preserve the operational detail that a user-visible shortcut can be stale "
                    "even when the MCP server and dashboard both appear healthy, because the launch path is a separate surface."
                ),
                "resolved_at": "2026-06-03T10:00:00",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            compact = server.fo_search("startup shortcut")
            expanded = server.fo_search("startup shortcut", mode="expanded")

        self.assertLess(len(compact), len(expanded))
        self.assertIn("Trust: source_type=solution", compact)

    def test_high_value_solved_bug_ranks_above_generic_activity(self):
        memory = {
            "live_record": {
                "intent": {},
                "architecture": {"components": []},
                "lessons": {"insights": [], "failed_attempts": []},
            },
            "decisions": [],
            "avoid": [],
            "debug_sessions": [{
                "problem": "MCP reconnect failed after startup shortcut launch",
                "solution": "Final fix regenerated the startup shortcut and preserved MCP config.",
                "resolved_at": "2026-06-03T10:00:00",
            }],
            "activity_log": [{
                "human_name": "Edited startup shortcut docs for MCP reconnect",
                "timestamp": "2026-06-03T11:00:00",
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_search("MCP reconnect startup shortcut", mode="expanded")

        self.assertIn("Best", result)
        first_result_line = next(line for line in result.splitlines() if line.startswith("> "))
        self.assertIn("Problem:** MCP reconnect failed after startup shortcut launch", first_result_line)

    def test_fo_brief_confidence_block_does_not_crash(self):
        """Regression test: fo_brief must not crash with NameError on d_count/s_count."""
        memory = {
            "project_info": {"name": "Confidence Test"},
            "live_record": {
                "intent": {"current_goal": "Test confidence", "next_step": "Verify fix"},
            },
            "decisions": [
                {"decision": f"Decision {i}", "reason": "Test", "timestamp": "2026-06-01T10:00:00"}
                for i in range(7)
            ],
            "avoid": [],
            "debug_sessions": [
                {"problem": f"Bug {i}", "solution": f"Fix {i}", "resolved_at": "2026-06-01T10:00:00"}
                for i in range(5)
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            self._activate_temp_session(Path(temp_dir), memory)

            result = server.fo_brief()

        self.assertNotIn("NameError", result)
        self.assertNotIn("d_count", result)
        self.assertIn("Confidence:", result)
        self.assertIn("high", result.lower())


if __name__ == "__main__":
    unittest.main()
