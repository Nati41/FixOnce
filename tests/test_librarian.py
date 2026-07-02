"""
Tests for Project Librarian architecture.

Validates behavior according to the Architecture Contract:
- No Critical Knowledge Left Behind
- Knowledge Before Code
- Silence Over Noise
- Tiered selection (must-know, should-check, may-help)
"""

import sys
import unittest
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.intent_detection import (
    Intent,
    IntentSignals,
    IntentResult,
    detect_intent,
)
from core.knowledge_model import (
    KnowledgeItem,
    KnowledgeType,
    Criticality,
    Scope,
    Trust,
    classify_knowledge,
)
from core.knowledge_selection import (
    KnowledgePackage,
    SelectionContext,
    RetrievalStrategy,
    select_for_briefing,
    select_for_alert,
    has_relevant_knowledge,
)
from core.briefing_composer import (
    compose_for_init,
    compose_for_subject_change,
)
from core.librarian import (
    ProjectLibrarian,
    create_librarian,
    get_init_briefing,
)


class TestIntentDetection(unittest.TestCase):
    """Tests for intent detection."""

    def test_error_message_implies_debugging(self):
        signals = IntentSignals(error_message="TypeError: Cannot read property")
        result = detect_intent(signals)
        self.assertEqual(result.intent, Intent.DEBUGGING)
        self.assertGreater(result.confidence, 0.8)

    def test_task_hint_with_debug_keywords(self):
        signals = IntentSignals(task_hint="fix the login bug")
        result = detect_intent(signals)
        self.assertEqual(result.intent, Intent.DEBUGGING)

    def test_task_hint_with_design_keywords(self):
        signals = IntentSignals(task_hint="refactor the authentication module")
        result = detect_intent(signals)
        self.assertEqual(result.intent, Intent.DESIGNING)

    def test_no_signals_returns_exploring(self):
        signals = IntentSignals()
        result = detect_intent(signals)
        self.assertEqual(result.intent, Intent.EXPLORING)
        self.assertLess(result.confidence, 0.5)


class TestKnowledgeModel(unittest.TestCase):
    """Tests for knowledge model classification."""

    def test_decision_is_must_know(self):
        raw = {"decision": "Use PostgreSQL", "reason": "Better scaling"}
        item = classify_knowledge(raw, "decision")
        self.assertEqual(item.type, KnowledgeType.DECISION)
        self.assertEqual(item.criticality, Criticality.MUST_KNOW)

    def test_avoid_is_must_know(self):
        raw = {"what": "Never use eval()", "reason": "Security risk"}
        item = classify_knowledge(raw, "avoid")
        self.assertEqual(item.type, KnowledgeType.AVOID)
        self.assertEqual(item.criticality, Criticality.MUST_KNOW)

    def test_solution_is_should_check(self):
        raw = {"problem": "Login failed", "solution": "Reset session"}
        item = classify_knowledge(raw, "solution")
        self.assertEqual(item.type, KnowledgeType.SOLUTION)
        self.assertEqual(item.criticality, Criticality.SHOULD_CHECK)

    def test_insight_is_may_help(self):
        raw = {"text": "The auth module is complex"}
        item = classify_knowledge(raw, "insight")
        self.assertEqual(item.type, KnowledgeType.INSIGHT)
        self.assertEqual(item.criticality, Criticality.MAY_HELP)

    def test_critical_marker_elevates_to_must_know(self):
        raw = {"text": "Critical insight", "critical": True}
        item = classify_knowledge(raw, "insight")
        self.assertEqual(item.criticality, Criticality.MUST_KNOW)


class TestKnowledgeSelection(unittest.TestCase):
    """Tests for tiered knowledge selection."""

    def setUp(self):
        """Create test memory with various knowledge types."""
        self.memory = {
            "decisions": [
                {"decision": "Use Windows API for installers", "reason": "Native support", "tags": ["windows", "installer"]},
                {"decision": "Dashboard UI in English", "reason": "User preference", "tags": ["dashboard"]},
            ],
            "avoid": [
                {"what": "Never use SHOW_WINDOW on Windows", "reason": "Creates console flash", "tags": ["windows"]},
            ],
            "debug_sessions": [
                {"problem": "Installer failed on Windows", "solution": "Added manifest", "tags": ["windows", "installer"]},
            ],
            "live_record": {
                "lessons": {
                    "insights": [
                        {"text": "Windows requires special handling", "tags": ["windows"]},
                    ]
                }
            }
        }

    def test_selection_returns_tiered_package(self):
        package = select_for_briefing(
            memory=self.memory,
            subject_tags=["windows"],
            intent=Intent.IMPLEMENTING,
        )
        self.assertIsInstance(package, KnowledgePackage)
        self.assertTrue(len(package.must_know) > 0 or len(package.should_check) > 0)

    def test_must_know_tier_includes_decisions(self):
        package = select_for_briefing(
            memory=self.memory,
            subject_tags=["windows"],
            intent=Intent.IMPLEMENTING,
        )
        decision_types = [item.type for item in package.must_know]
        self.assertIn(KnowledgeType.DECISION, decision_types)

    def test_must_know_tier_includes_avoids(self):
        package = select_for_briefing(
            memory=self.memory,
            subject_tags=["windows"],
            intent=Intent.IMPLEMENTING,
        )
        avoid_types = [item.type for item in package.must_know]
        self.assertIn(KnowledgeType.AVOID, avoid_types)

    def test_should_check_tier_includes_solutions(self):
        package = select_for_briefing(
            memory=self.memory,
            subject_tags=["windows", "installer"],
            intent=Intent.DEBUGGING,
        )
        solution_types = [item.type for item in package.should_check]
        self.assertIn(KnowledgeType.SOLUTION, solution_types)

    def test_unrelated_subject_returns_empty(self):
        package = select_for_briefing(
            memory=self.memory,
            subject_tags=["macos"],  # No macos knowledge in memory
            intent=Intent.IMPLEMENTING,
        )
        self.assertTrue(package.is_empty())

    def test_alert_only_returns_must_know(self):
        package = select_for_alert(
            memory=self.memory,
            subject_tags=["windows"],
            intent=Intent.DEBUGGING,
        )
        self.assertTrue(len(package.should_check) == 0)
        self.assertTrue(len(package.may_help) == 0)

    def test_windows_installer_must_know_excludes_macos_installer_items(self):
        memory = {
            "decisions": [
                {
                    "decision": "Before every Windows build, kill FixOnce-related processes, run scripts/windows_runtime_qa.ps1, and test in TestUser.",
                    "reason": "Validate packaged runtime before installer testing.",
                    "tags": ["windows", "installer"],
                },
                {
                    "decision": "macOS reinstall must kill stale processes before recreating LaunchAgents.",
                    "reason": "Old LaunchAgent processes survive unload.",
                    "tags": ["macos", "installer"],
                },
                {
                    "decision": "Universal must-know applies to all project work.",
                    "scope": "universal",
                },
            ],
        }

        package = select_for_briefing(
            memory=memory,
            subject_tags=["windows", "installer"],
            intent=Intent.DEBUGGING,
        )

        must_know_text = "\n".join(item.text for item in package.must_know)
        self.assertIn("scripts/windows_runtime_qa.ps1", must_know_text)
        self.assertIn("TestUser", must_know_text)
        self.assertNotIn("LaunchAgents", must_know_text)
        self.assertNotIn("macOS reinstall", must_know_text)
        self.assertIn("Universal must-know", must_know_text)


class TestTierInvariants(unittest.TestCase):
    """Tests for tier invariants - tiers must never merge."""

    def test_tiers_are_separate_lists(self):
        memory = {
            "decisions": [{"decision": "Test decision", "tags": ["test"]}],
            "debug_sessions": [{"problem": "Test", "solution": "Fix", "tags": ["test"]}],
        }
        package = select_for_briefing(
            memory=memory,
            subject_tags=["test"],
            intent=Intent.IMPLEMENTING,
        )
        # Must-know and should-check should be separate
        must_know_ids = {item.id for item in package.must_know}
        should_check_ids = {item.id for item in package.should_check}
        self.assertEqual(len(must_know_ids & should_check_ids), 0)

    def test_get_all_items_preserves_order(self):
        memory = {
            "decisions": [{"decision": "D1", "tags": ["test"]}],
            "debug_sessions": [{"problem": "P1", "solution": "S1", "tags": ["test"]}],
            "live_record": {"lessons": {"insights": [{"text": "I1", "tags": ["test"]}]}}
        }
        package = select_for_briefing(
            memory=memory,
            subject_tags=["test"],
            intent=Intent.IMPLEMENTING,
        )
        all_items = package.get_all_items()
        # Must-know should come before should-check
        if package.must_know and package.should_check:
            must_know_first_idx = all_items.index(package.must_know[0])
            should_check_first_idx = all_items.index(package.should_check[0])
            self.assertLess(must_know_first_idx, should_check_first_idx)


class TestBriefingComposition(unittest.TestCase):
    """Tests for briefing composition."""

    def test_compose_for_init_includes_header(self):
        memory = {
            "decisions": [{"decision": "Test", "tags": ["windows"]}]
        }
        package = select_for_briefing(memory, ["windows"], Intent.IMPLEMENTING)
        briefing = compose_for_init(package)
        self.assertIn("windows", briefing.lower())

    def test_empty_package_returns_empty_briefing(self):
        package = KnowledgePackage()
        briefing = compose_for_init(package)
        self.assertEqual(briefing, "")


class TestLibrarianOrchestration(unittest.TestCase):
    """Tests for full librarian orchestration."""

    def setUp(self):
        self.memory = {
            "decisions": [
                {"decision": "Use subprocess timeout", "reason": "Prevent hangs", "tags": ["windows"]},
            ],
            "avoid": [
                {"what": "Never use SHOW_WINDOW flag", "reason": "Console flash", "tags": ["windows"]},
            ],
            "debug_sessions": [
                {"problem": "Console flash on startup", "solution": "Use CREATE_NO_WINDOW", "tags": ["windows"]},
            ],
        }

    def test_session_start_returns_response(self):
        librarian = create_librarian(self.memory)
        response = librarian.on_session_start(task_hint="working on windows installer")
        self.assertTrue(response.should_speak)
        self.assertIsNotNone(response.briefing)

    def test_session_start_silence_without_signals(self):
        librarian = create_librarian(self.memory)
        response = librarian.on_session_start()  # No signals
        self.assertFalse(response.should_speak)

    def test_subject_change_surfaces_new_knowledge(self):
        librarian = create_librarian(self.memory)
        # First session
        librarian.on_session_start(task_hint="working on dashboard")
        # Subject change
        response = librarian.on_subject_change(new_work_area="windows installer")
        self.assertTrue(response.should_speak or response.knowledge_package.has_must_know())

    def test_convenience_function_works(self):
        briefing = get_init_briefing(
            memory=self.memory,
            task_hint="windows installer work"
        )
        self.assertIsInstance(briefing, str)


class TestNoKnowledgeLeftBehind(unittest.TestCase):
    """Tests for 'No Critical Knowledge Left Behind' guarantee."""

    def test_must_know_always_appears(self):
        """Critical avoid pattern must appear even if other items have higher similarity."""
        memory = {
            "avoid": [
                {"what": "Critical security rule", "reason": "Important", "critical": True, "tags": ["auth"]},
            ],
            "live_record": {
                "lessons": {
                    "insights": [
                        {"text": "Auth insight 1", "tags": ["auth"]},
                        {"text": "Auth insight 2", "tags": ["auth"]},
                        {"text": "Auth insight 3", "tags": ["auth"]},
                        {"text": "Auth insight 4", "tags": ["auth"]},
                        {"text": "Auth insight 5", "tags": ["auth"]},
                    ]
                }
            }
        }
        package = select_for_briefing(memory, ["auth"], Intent.IMPLEMENTING, max_per_tier=3)
        # The critical avoid MUST be in must_know, regardless of insights
        avoid_present = any(
            item.type == KnowledgeType.AVOID
            for item in package.must_know
        )
        self.assertTrue(avoid_present, "Critical avoid must appear in must_know tier")


class TestSilenceOverNoise(unittest.TestCase):
    """Tests for 'Silence Over Noise' guarantee."""

    def test_low_confidence_stays_silent(self):
        memory = {"decisions": [{"decision": "Test", "tags": ["specific"]}]}
        librarian = create_librarian(memory)
        # Very generic task hint that won't match
        response = librarian.on_session_start(task_hint="hi")
        self.assertFalse(response.should_speak)

    def test_no_relevant_knowledge_stays_silent(self):
        memory = {"decisions": [{"decision": "Test", "tags": ["python"]}]}
        librarian = create_librarian(memory)
        response = librarian.on_session_start(task_hint="working on rust code")
        self.assertFalse(response.should_speak)


class TestSubjectShelfCache(unittest.TestCase):
    """Tests for subject shelf presentation caching."""

    def setUp(self):
        self.memory = {
            "decisions": [
                {
                    "decision": "Use Windows runtime QA before installer validation.",
                    "reason": "Avoid costly VM loops.",
                    "tags": ["windows", "installer"],
                },
                {
                    "decision": "Dashboard settings stay compact.",
                    "reason": "Keep the UI focused.",
                    "tags": ["dashboard"],
                },
            ],
            "avoid": [
                {
                    "what": "Do not use SHOW_WINDOW for Windows startup.",
                    "reason": "Console flashes.",
                    "tags": ["windows"],
                },
            ],
            "debug_sessions": [
                {
                    "problem": "Dashboard polling noise",
                    "solution": "Ignore transient fetch failures.",
                    "tags": ["dashboard"],
                },
            ],
        }

    def test_subject_a_b_a_restores_a_from_shelf(self):
        librarian = create_librarian(self.memory)

        first = librarian.on_subject_change(new_work_area="windows installer")
        second = librarian.on_subject_change(new_work_area="dashboard")

        with patch("core.librarian.select_for_briefing", wraps=select_for_briefing) as select_mock:
            restored = librarian.on_subject_change(new_work_area="windows installer")

        self.assertTrue(first.should_speak)
        self.assertTrue(second.should_speak)
        self.assertTrue(restored.should_speak)
        self.assertEqual(restored.reason, "Restored subject shelf")
        self.assertEqual(restored.briefing, first.briefing)
        select_mock.assert_not_called()

    def test_same_subject_twice_stays_silent(self):
        librarian = create_librarian(self.memory)

        first = librarian.on_session_start(task_hint="working on windows installer")
        second = librarian.on_session_start(task_hint="working on windows installer")

        self.assertTrue(first.should_speak)
        self.assertFalse(second.should_speak)
        self.assertEqual(second.reason, "Subject already surfaced: installer")

    def test_memory_change_invalidates_shelf(self):
        librarian = create_librarian(self.memory)
        librarian.on_subject_change(new_work_area="windows installer")
        librarian.on_subject_change(new_work_area="dashboard")

        self.memory["live_record"] = {
            "lessons": {
                "insights": [
                    {"text": "Windows installer insight", "tags": ["windows", "installer"]},
                ]
            }
        }

        with patch("core.librarian.select_for_briefing", wraps=select_for_briefing) as select_mock:
            response = librarian.on_subject_change(new_work_area="windows installer")

        self.assertTrue(response.should_speak)
        self.assertEqual(response.reason, "Subject shelf stale; rebuilt from Project Knowledge")
        self.assertGreater(select_mock.call_count, 0)

    def test_added_must_know_invalidates_and_appears_after_rebuild(self):
        librarian = create_librarian(self.memory)
        librarian.on_subject_change(new_work_area="windows installer")
        librarian.on_subject_change(new_work_area="dashboard")

        self.memory["decisions"].append({
            "decision": "New Windows installer release gate must stay visible.",
            "reason": "It is a beta blocker.",
            "tags": ["windows", "installer"],
        })

        response = librarian.on_subject_change(new_work_area="windows installer")

        self.assertTrue(response.should_speak)
        self.assertEqual(response.reason, "Subject shelf stale; rebuilt from Project Knowledge")
        self.assertIn("New Windows installer release gate", response.briefing)

    def test_cache_never_changes_project_knowledge(self):
        original = deepcopy(self.memory)
        librarian = create_librarian(self.memory)

        librarian.on_subject_change(new_work_area="windows installer")
        librarian.on_subject_change(new_work_area="dashboard")
        librarian.on_subject_change(new_work_area="windows installer")

        self.assertEqual(self.memory, original)

    def test_librarian_subject_shelves_do_not_affect_fo_search(self):
        import inspect
        import core.librarian as librarian_module

        source = inspect.getsource(librarian_module.ProjectLibrarian)

        self.assertNotIn("fo_search(", source)
        self.assertNotIn("search_past_solutions", source)


class TestReorientationMode(unittest.TestCase):
    """Tests for reorientation briefing mode."""

    def test_detect_reorientation_hint_long_break(self):
        """Long break task_hint triggers reorientation."""
        from core.briefing_composer import detect_reorientation_hint

        self.assertTrue(detect_reorientation_hint("returning after a long break"))
        self.assertTrue(detect_reorientation_hint("I've been away for a while"))
        self.assertTrue(detect_reorientation_hint("forgot where I stopped"))
        self.assertTrue(detect_reorientation_hint("help me continue"))
        self.assertTrue(detect_reorientation_hint("catch me up"))
        self.assertTrue(detect_reorientation_hint("where were we"))
        self.assertTrue(detect_reorientation_hint("haven't worked on this in weeks"))

    def test_detect_reorientation_hint_normal_work(self):
        """Normal task hints do not trigger reorientation."""
        from core.briefing_composer import detect_reorientation_hint

        self.assertFalse(detect_reorientation_hint("working on the installer"))
        self.assertFalse(detect_reorientation_hint("fix the login bug"))
        self.assertFalse(detect_reorientation_hint("add new feature"))
        self.assertFalse(detect_reorientation_hint(""))
        self.assertFalse(detect_reorientation_hint(None))

    def test_compose_for_reorientation_structure(self):
        """Reorientation output includes project-status sections when available."""
        from core.briefing_composer import compose_for_reorientation

        memory = {
            "decisions": [
                {"decision": "Use PostgreSQL for main DB", "reason": "Better scaling", "blocking": True},
                {"decision": "Dashboard UI in English", "reason": "User preference"},
            ],
            "avoid": [
                {"what": "Never use eval()", "reason": "Security risk"},
            ],
            "debug_sessions": [
                {"problem": "Login timeout", "solution": "Increased timeout to 30s", "resolved_at": "2026-06-15T10:00:00Z"},
            ],
            "decision_conflicts": [
                {"status": "open", "description": "Auth method needs decision"},
            ],
        }

        result = compose_for_reorientation(
            memory=memory,
            project_name="TestProject",
            active_goal="Complete authentication module",
            knowledge_stats="📊 Project Knowledge: 5 Decisions · 3 Solved Bugs · 2 Avoid Patterns",
        )

        # Check new structure - project status briefing format
        self.assertIn("🧠 **Project Status:** TestProject", result)
        self.assertIn("📍 **Current Focus**", result)
        self.assertIn("Complete authentication module", result)
        self.assertIn("🔒 **Active Decisions**", result)
        self.assertIn("PostgreSQL", result)
        self.assertIn("⚠️ **Known Risks**", result)
        self.assertIn("eval()", result)
        self.assertIn("📊 Project Knowledge", result)
        self.assertIn("→ **Next:**", result)
        self.assertIn("Ready.", result)

    def test_reorientation_hides_empty_sections(self):
        """Empty sections are hidden in reorientation."""
        from core.briefing_composer import compose_for_reorientation

        memory = {
            "decisions": [],
            "avoid": [],
            "debug_sessions": [],
        }

        result = compose_for_reorientation(
            memory=memory,
            project_name="EmptyProject",
        )

        # Should not have section headers for empty sections
        self.assertNotIn("📍 **Current Focus**", result)
        self.assertNotIn("🔒 **Active Decisions**", result)
        self.assertNotIn("⚠️ **Known Risks**", result)
        self.assertNotIn("✅ **Recently Completed**", result)
        self.assertNotIn("📂 **Working Tree**", result)
        self.assertNotIn("→ **Next:**", result)
        # Should still have project status header and Ready
        self.assertIn("🧠 **Project Status:** EmptyProject", result)
        self.assertIn("Ready.", result)

    def test_reorientation_not_dominated_by_last_work_area(self):
        """Reorientation prioritizes project-level importance over last-edited topic."""
        from core.briefing_composer import compose_for_reorientation

        memory = {
            "decisions": [
                {"decision": "Critical security fix needed", "reason": "Vulnerability", "blocking": True, "tags": ["security"]},
                {"decision": "Minor UI tweak", "reason": "Polish", "tags": ["dashboard"]},
            ],
            "avoid": [
                {"what": "Never skip auth validation", "reason": "Security", "tags": ["security"]},
            ],
            "live_record": {
                "intent": {
                    "work_area": "dashboard",
                    "last_file": "dashboard.html",
                }
            }
        }

        result = compose_for_reorientation(
            memory=memory,
            project_name="TestProject",
            active_goal="",
        )

        # Security decisions should appear regardless of last work area being "dashboard"
        self.assertIn("security fix", result.lower())
        # The blocking decision should be prioritized
        self.assertIn("Critical security fix", result)

    def test_working_tree_appears_separately(self):
        """Working tree state appears as a separate section from project knowledge."""
        from core.briefing_composer import compose_for_reorientation

        memory = {
            "decisions": [
                {"decision": "Use PostgreSQL", "reason": "Better scaling"},
            ],
            "avoid": [],
            "debug_sessions": [],
        }

        result = compose_for_reorientation(
            memory=memory,
            project_name="TestProject",
            knowledge_stats="📊 Project Knowledge: 5 Decisions",
            working_tree="3 files modified, 1 untracked",
        )

        # Working tree should be separate from knowledge stats
        self.assertIn("📂 **Working Tree**", result)
        self.assertIn("3 files modified", result)
        # Knowledge stats should appear earlier (in header area)
        knowledge_pos = result.find("📊 Project Knowledge")
        working_tree_pos = result.find("📂 **Working Tree**")
        self.assertLess(knowledge_pos, working_tree_pos)

    def test_working_tree_hidden_when_empty(self):
        """Working tree section is hidden when not provided."""
        from core.briefing_composer import compose_for_reorientation

        memory = {"decisions": [], "avoid": [], "debug_sessions": []}

        result = compose_for_reorientation(
            memory=memory,
            project_name="TestProject",
            working_tree="",
        )

        self.assertNotIn("📂 **Working Tree**", result)

    def test_reorientation_does_not_collapse_to_last_next(self):
        """Reorientation output maintains project-status structure, not simple Last/Next."""
        from core.briefing_composer import compose_for_reorientation

        memory = {
            "decisions": [
                {"decision": "Use PostgreSQL", "reason": "Scaling"},
            ],
            "avoid": [
                {"what": "No eval()", "reason": "Security"},
            ],
            "debug_sessions": [],
            "live_record": {
                "intent": {
                    "last_change": "Fixed login",
                    "next_step": "Add tests",
                }
            },
        }

        result = compose_for_reorientation(
            memory=memory,
            project_name="TestProject",
            active_goal="Complete auth module",
        )

        # Should have project-status sections, NOT Last:/Next: format
        self.assertIn("🧠 **Project Status:**", result)
        self.assertNotIn("Last:\n", result)
        self.assertNotIn("Next:\n", result)
        # Should have structured sections
        self.assertIn("📍 **Current Focus**", result)
        self.assertIn("🔒 **Active Decisions**", result)
        self.assertIn("⚠️ **Known Risks**", result)

    def test_reorientation_section_order(self):
        """Reorientation sections appear in correct order."""
        from core.briefing_composer import compose_for_reorientation

        memory = {
            "decisions": [{"decision": "Use PostgreSQL", "reason": "Scaling", "blocking": True}],
            "avoid": [{"what": "No eval()", "reason": "Security"}],
            "debug_sessions": [
                {"problem": "Fixed login", "solution": "Added timeout", "resolved_at": "2026-06-15T10:00:00Z"}
            ],
            "decision_conflicts": [{"status": "open", "description": "Auth method"}],
        }

        result = compose_for_reorientation(
            memory=memory,
            project_name="TestProject",
            active_goal="Complete auth",
            knowledge_stats="📊 5 Decisions",
            working_tree="2 files modified",
        )

        # Verify order: Status -> Focus -> Completed -> Decisions -> Risks -> Tree -> Next
        status_pos = result.find("🧠 **Project Status:**")
        focus_pos = result.find("📍 **Current Focus**")
        completed_pos = result.find("✅ **Recently Completed**")
        decisions_pos = result.find("🔒 **Active Decisions**")
        risks_pos = result.find("⚠️ **Known Risks**")
        tree_pos = result.find("📂 **Working Tree**")
        next_pos = result.find("→ **Next:**")

        self.assertLess(status_pos, focus_pos)
        self.assertLess(focus_pos, completed_pos)
        self.assertLess(completed_pos, decisions_pos)
        self.assertLess(decisions_pos, risks_pos)
        self.assertLess(risks_pos, tree_pos)
        self.assertLess(tree_pos, next_pos)


class TestBriefingModeSelection(unittest.TestCase):
    """Tests for continuation vs reorientation mode selection."""

    def test_extract_priorities_uses_active_goal(self):
        """Active goal appears first in priorities."""
        from core.briefing_composer import _extract_priorities

        memory = {
            "decisions": [{"decision": "Other decision", "blocking": True}],
        }

        priorities = _extract_priorities(memory, active_goal="Main project goal")
        self.assertEqual(priorities[0], "Main project goal")

    def test_extract_risks_includes_avoid_patterns(self):
        """Avoid patterns appear in risks."""
        from core.briefing_composer import _extract_risks

        memory = {
            "avoid": [
                {"what": "Risk 1", "reason": "Because"},
                {"what": "Risk 2", "reason": "Also because"},
            ],
        }

        risks = _extract_risks(memory, limit=2)
        self.assertEqual(len(risks), 2)
        self.assertTrue(all("Avoid:" in r for r in risks))

    def test_extract_active_decisions_excludes_superseded(self):
        """Superseded decisions are excluded."""
        from core.briefing_composer import _extract_active_decisions

        memory = {
            "decisions": [
                {"decision": "Old approach", "superseded": True},
                {"decision": "Current approach", "superseded": False},
            ],
        }

        decisions = _extract_active_decisions(memory)
        self.assertEqual(len(decisions), 1)
        self.assertIn("Current approach", decisions[0])


if __name__ == '__main__':
    unittest.main()
