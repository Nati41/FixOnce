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


if __name__ == '__main__':
    unittest.main()
