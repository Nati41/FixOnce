"""
Tests for core.error_engine module.

The Error Engine is "Git for debugging history" -
makes developers feel "I've seen this error before."
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.error_engine import (
    normalize_error,
    calculate_error_similarity,
    find_matching_solutions,
    analyze_error,
    select_auto_fix_candidates,
    NormalizedError,
    ErrorMatch,
    ErrorAnalysis,
    AUTO_FIX_THRESHOLD,
    SUGGEST_THRESHOLD,
)


class TestNormalizeError(unittest.TestCase):
    """Tests for error normalization."""

    def test_empty_error(self):
        result = normalize_error("")
        self.assertEqual(result.original, "")
        self.assertEqual(result.normalized, "")

    def test_extracts_error_type_typeerror(self):
        result = normalize_error("TypeError: Cannot read property 'length' of undefined")
        self.assertEqual(result.error_type, "type_error")

    def test_extracts_error_type_reference(self):
        result = normalize_error("ReferenceError: foo is not defined")
        self.assertEqual(result.error_type, "reference_error")

    def test_extracts_error_type_network(self):
        result = normalize_error("Failed to fetch: NetworkError")
        self.assertEqual(result.error_type, "network_error")

    def test_extracts_file_reference_js(self):
        result = normalize_error("Error at src/components/Button.tsx:42")
        self.assertEqual(result.file_reference, "src/components/Button.tsx")
        self.assertEqual(result.line_number, 42)

    def test_extracts_file_reference_python(self):
        result = normalize_error('File "app/views.py", line 123, in handler')
        self.assertEqual(result.file_reference, "app/views.py")
        self.assertEqual(result.line_number, 123)

    def test_extracts_key_tokens(self):
        result = normalize_error("TypeError: Cannot read property 'length' of undefined")
        self.assertIn("property", result.key_tokens)
        self.assertIn("length", result.key_tokens)
        # Noise words should be filtered
        self.assertNotIn("of", result.key_tokens)

    def test_removes_hex_addresses(self):
        result = normalize_error("Error at 0x7fff5fbff8c0")
        self.assertNotIn("0x7fff5fbff8c0", result.normalized)


class TestCalculateSimilarity(unittest.TestCase):
    """Tests for error similarity calculation."""

    def test_exact_match(self):
        error = "TypeError: Cannot read property 'length'"
        similarity = calculate_error_similarity(error, error)
        self.assertEqual(similarity, 100)

    def test_no_match(self):
        similarity = calculate_error_similarity(
            "TypeError: foo is undefined",
            "SyntaxError: unexpected token"
        )
        self.assertLess(similarity, 50)

    def test_partial_match(self):
        similarity = calculate_error_similarity(
            "TypeError: Cannot read property 'length' of undefined",
            "TypeError: Cannot read property 'name' of null"
        )
        self.assertGreater(similarity, 50)
        self.assertLess(similarity, 100)

    def test_same_error_type_bonus(self):
        sim_same = calculate_error_similarity(
            "TypeError: foo undefined",
            "TypeError: bar undefined"
        )
        sim_diff = calculate_error_similarity(
            "TypeError: foo undefined",
            "ReferenceError: bar undefined"
        )
        self.assertGreater(sim_same, sim_diff)

    def test_empty_strings(self):
        self.assertEqual(calculate_error_similarity("", "error"), 0)
        self.assertEqual(calculate_error_similarity("error", ""), 0)


class TestFindMatchingSolutions(unittest.TestCase):
    """Tests for finding matching solutions."""

    def test_finds_matching_debug_session(self):
        debug_sessions = [{
            'problem': "TypeError: Cannot read property 'length' of undefined",
            'solution': "Added null check before accessing array",
            'root_cause': "Array was not initialized",
            'files_changed': ['src/utils.js'],
            'reuse_count': 2,
        }]

        matches = find_matching_solutions(
            "TypeError: Cannot read property 'length' of undefined",
            debug_sessions,
        )

        self.assertGreater(len(matches), 0)
        self.assertIn("null check", matches[0].solution_text)

    def test_matches_by_symptom(self):
        debug_sessions = [{
            'problem': "Authentication token expired causing 401 error",
            'solution': "Fixed token refresh",
            'symptoms': ["401 Unauthorized", "token expired", "authentication failed"],
        }]

        matches = find_matching_solutions(
            "401 Unauthorized authentication token error",
            debug_sessions,
        )

        self.assertGreater(len(matches), 0)

    def test_no_match_returns_empty(self):
        debug_sessions = [{
            'problem': "Database connection failed",
            'solution': "Check credentials",
        }]

        matches = find_matching_solutions(
            "CSS styling broken on mobile",
            debug_sessions,
        )

        self.assertEqual(len(matches), 0)

    def test_respects_limit(self):
        debug_sessions = [
            {'problem': f"Error type {i}", 'solution': f"Fix {i}"}
            for i in range(10)
        ]

        matches = find_matching_solutions(
            "Error type 5",
            debug_sessions,
            limit=3,
        )

        self.assertLessEqual(len(matches), 3)


class TestAnalyzeError(unittest.TestCase):
    """Tests for complete error analysis."""

    def test_analysis_structure(self):
        analysis = analyze_error(
            "TypeError: foo is undefined",
            [],
        )

        self.assertIsInstance(analysis, ErrorAnalysis)
        self.assertIsInstance(analysis.error, NormalizedError)
        self.assertIsInstance(analysis.matches, list)

    def test_auto_fix_ready_when_high_confidence(self):
        debug_sessions = [{
            'problem': "TypeError: Cannot read property 'length'",
            'solution': "Add null check",
            'reuse_count': 5,  # High reuse = high confidence
            'root_cause': "Array undefined",
            'files_changed': ['src/app.js'],
        }]

        analysis = analyze_error(
            "TypeError: Cannot read property 'length'",
            debug_sessions,
        )

        # With exact match + high reuse, should be auto-fix ready
        self.assertTrue(analysis.auto_fix_ready)
        self.assertIsNotNone(analysis.suggested_fix)

    def test_generates_diagnostic(self):
        analysis = analyze_error(
            "ReferenceError: myVariable is not defined",
            [],
        )

        self.assertIsNotNone(analysis.diagnostic)
        self.assertIn("defined", analysis.diagnostic.lower())


class TestSelectAutoFixCandidates(unittest.TestCase):
    """Tests for auto-fix candidate selection."""

    def test_selects_high_confidence_matches(self):
        debug_sessions = [{
            'problem': "Error A exact match",
            'solution': "Fix A",
            'reuse_count': 10,
            'root_cause': "Known issue",
            'files_changed': ['a.js'],
        }]

        errors = ["Error A exact match", "Completely different error"]

        candidates = select_auto_fix_candidates(errors, debug_sessions)

        # Only the first error should have a candidate
        self.assertGreater(len(candidates), 0)
        error, match = candidates[0]
        self.assertIn("Error A", error)

    def test_returns_empty_when_no_matches(self):
        candidates = select_auto_fix_candidates(
            ["Random error"],
            [],
        )

        self.assertEqual(len(candidates), 0)


class TestErrorMatch(unittest.TestCase):
    """Tests for ErrorMatch dataclass."""

    def test_default_fields(self):
        match = ErrorMatch(
            error_text="Error",
            solution_text="Fix",
            similarity=80,
            confidence=85,
            source="debug_session",
        )

        self.assertEqual(match.files_changed, [])
        self.assertIsNone(match.root_cause)
        self.assertEqual(match.reuse_count, 0)


if __name__ == '__main__':
    unittest.main()
