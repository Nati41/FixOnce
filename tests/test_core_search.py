"""
Tests for core.search module.

Transport-independent search logic tests.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.search import (
    tokenize,
    calculate_similarity,
    text_matches,
    search_memory,
    SearchMatch,
    SearchResult,
    NOISE_WORDS,
)


class TestTokenize(unittest.TestCase):
    """Tests for tokenize function."""

    def test_empty_string(self):
        self.assertEqual(tokenize(""), set())

    def test_removes_noise_words(self):
        tokens = tokenize("the error is in the file")
        self.assertNotIn("the", tokens)
        self.assertNotIn("is", tokens)
        self.assertNotIn("in", tokens)

    def test_keeps_meaningful_words(self):
        tokens = tokenize("authentication failed login")
        self.assertIn("authentication", tokens)
        self.assertIn("login", tokens)

    def test_handles_mixed_case(self):
        tokens = tokenize("TypeError Cannot Read Property")
        self.assertIn("typeerror", tokens)
        self.assertIn("property", tokens)


class TestCalculateSimilarity(unittest.TestCase):
    """Tests for calculate_similarity function."""

    def test_empty_query(self):
        self.assertEqual(calculate_similarity("", "some text"), 0)

    def test_empty_text(self):
        self.assertEqual(calculate_similarity("query", ""), 0)

    def test_exact_match(self):
        score = calculate_similarity("login error", "login error occurred")
        self.assertGreater(score, 50)

    def test_no_match(self):
        score = calculate_similarity("authentication", "database connection")
        self.assertEqual(score, 0)

    def test_partial_match(self):
        score = calculate_similarity("login authentication", "login failed")
        self.assertGreater(score, 0)
        self.assertLess(score, 100)

    def test_substring_bonus(self):
        score_with_substring = calculate_similarity("login", "the login failed")
        score_without = calculate_similarity("login", "authentication failed")
        self.assertGreater(score_with_substring, score_without)


class TestTextMatches(unittest.TestCase):
    """Tests for text_matches function."""

    def test_exact_substring(self):
        tokens = tokenize("login error")
        self.assertTrue(text_matches("login error", tokens, "A login error occurred"))

    def test_token_overlap(self):
        tokens = tokenize("authentication login")
        self.assertTrue(text_matches("authentication login", tokens, "login authentication failed"))

    def test_no_match(self):
        tokens = tokenize("database")
        self.assertFalse(text_matches("database", tokens, "login failed"))

    def test_single_token_match(self):
        tokens = tokenize("authentication")
        self.assertTrue(text_matches("authentication", tokens, "authentication required"))


class TestSearchMemory(unittest.TestCase):
    """Tests for search_memory function."""

    def test_empty_memory(self):
        result = search_memory({}, "test query")
        self.assertEqual(result.query, "test query")
        self.assertEqual(result.matches, [])

    def test_search_insights(self):
        memory = {
            'live_record': {
                'lessons': {
                    'insights': [
                        {'text': 'Always validate user input before processing'},
                        {'text': 'Use async/await for API calls'},
                    ]
                }
            }
        }
        result = search_memory(memory, "validate input")
        self.assertGreater(len(result.matches), 0)
        self.assertEqual(result.matches[0].match_type, 'insight')

    def test_search_decisions(self):
        memory = {
            'decisions': [
                {'decision': 'Use PostgreSQL for production', 'reason': 'Better scaling'},
            ]
        }
        result = search_memory(memory, "PostgreSQL production")
        self.assertGreater(len(result.matches), 0)
        self.assertEqual(result.matches[0].match_type, 'decision')

    def test_search_solutions(self):
        memory = {
            'debug_sessions': [
                {
                    'problem': 'TypeError: Cannot read property length',
                    'solution': 'Added null check before accessing array',
                    'root_cause': 'Array was undefined on first render',
                }
            ]
        }
        result = search_memory(memory, "TypeError property length")
        self.assertGreater(len(result.matches), 0)
        self.assertEqual(result.matches[0].match_type, 'solution')

    def test_search_avoid_patterns(self):
        memory = {
            'avoid': [
                {'what': 'Direct database queries in components', 'reason': 'Use service layer'},
            ]
        }
        result = search_memory(memory, "database queries components")
        self.assertGreater(len(result.matches), 0)
        self.assertEqual(result.matches[0].match_type, 'avoid')

    def test_skips_superseded_decisions(self):
        memory = {
            'decisions': [
                {'decision': 'Use MySQL production', 'reason': 'Old choice', 'superseded': True},
                {'decision': 'Use PostgreSQL production', 'reason': 'Better choice'},
            ]
        }
        result = search_memory(memory, "production PostgreSQL MySQL")
        # Should only find non-superseded decision
        decision_matches = [m for m in result.matches if m.match_type == 'decision']
        self.assertEqual(len(decision_matches), 1)
        self.assertIn('PostgreSQL', decision_matches[0].text)

    def test_results_sorted_by_priority(self):
        memory = {
            'decisions': [
                {'decision': 'Test decision about auth', 'reason': 'Testing'},
            ],
            'avoid': [
                {'what': 'Test avoid auth pattern', 'reason': 'Testing'},
            ],
            'live_record': {
                'lessons': {
                    'insights': [{'text': 'Test insight about auth'}]
                }
            }
        }
        result = search_memory(memory, "auth test")
        # Avoid should come before decision, decision before insight
        types = [m.match_type for m in result.matches]
        if 'avoid' in types and 'decision' in types:
            self.assertLess(types.index('avoid'), types.index('decision'))
        if 'decision' in types and 'insight' in types:
            self.assertLess(types.index('decision'), types.index('insight'))

    def test_limit_results(self):
        memory = {
            'live_record': {
                'lessons': {
                    'insights': [
                        {'text': f'Insight about testing number {i}'} for i in range(20)
                    ]
                }
            }
        }
        result = search_memory(memory, "testing insight", limit=5)
        self.assertLessEqual(len(result.matches), 5)


class TestSearchMatch(unittest.TestCase):
    """Tests for SearchMatch dataclass."""

    def test_defaults(self):
        match = SearchMatch(
            text="Test",
            match_type="insight",
            similarity=80,
            confidence=75,
        )
        self.assertEqual(match.metadata, {})
        self.assertEqual(match.use_count, 0)
        self.assertEqual(match.files_changed, [])


if __name__ == '__main__':
    unittest.main()
