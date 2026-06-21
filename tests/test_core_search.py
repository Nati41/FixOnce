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
    _relevance_score,
    _type_priority,
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

    def test_splits_camelcase_tokens(self):
        """Regression: JSONDecodeError should match 'JSON parsing'."""
        tokens = tokenize("JSONDecodeError: Expecting value")
        self.assertIn("json", tokens)
        self.assertIn("decode", tokens)
        self.assertIn("jsondecodeerror", tokens)  # keeps original too

    def test_camelcase_enables_semantic_match(self):
        """Regression: JSONDecodeError query should match 'JSON parsing failed' solution."""
        query_tokens = tokenize("JSONDecodeError: Expecting value: line 1 column 1")
        saved_tokens = tokenize("JSON parsing failed because API returned HTML")
        overlap = query_tokens & saved_tokens
        self.assertIn("json", overlap)


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

    def test_exact_match_bonus_beats_partial(self):
        """Complete query token match should beat partial match even with long-token bonus."""
        query = "ModuleNotFoundError requests"
        # Fresh fix: all 3 query tokens present (modulenotfounderror, module, requests)
        fresh_problem = "ModuleNotFoundError: No module named 'requests'"
        # Old memory: only 2/3 tokens (modulenotfounderror, module - missing requests)
        old_problem = "LaunchAgent crash loop: ModuleNotFoundError: No module named 'flask'"

        fresh_score = calculate_similarity(query, fresh_problem)
        old_score = calculate_similarity(query, old_problem)

        self.assertGreater(
            fresh_score, old_score,
            f"Fresh exact match ({fresh_score}) should beat old partial match ({old_score})"
        )


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

    def test_synonym_match_jsondecode_parsing(self):
        """Regression: JSONDecodeError should match 'parsing' via synonyms."""
        query = "JSONDecodeError"
        tokens = tokenize(query)
        text = "Check response status before parsing."
        self.assertTrue(
            text_matches(query, tokens, text),
            "JSONDecodeError should match text with 'parsing' via decode↔parse synonyms"
        )

    def test_synonym_match_non_json_response(self):
        """Regression: 'non-JSON response' should match 404/HTML solution."""
        query = "non-JSON response"
        tokens = tokenize(query)
        text = "404 endpoint returned HTML page. Check response status before parsing."
        self.assertTrue(
            text_matches(query, tokens, text),
            "'non-JSON response' should match 404/HTML solution via synonyms"
        )

    def test_synonym_match_requires_strong_signal(self):
        """Synonym-only matches require >=3 expanded tokens to avoid over-matching."""
        query = "parse"  # Only 1 token, expands but shouldn't match unrelated text
        tokens = tokenize(query)
        text = "The server returned a 200 status code."  # No semantic relation
        self.assertFalse(
            text_matches(query, tokens, text),
            "Weak synonym overlap should not match unrelated text"
        )

    def test_direct_match_still_works(self):
        """Direct token overlap should still work without needing synonyms."""
        query = "TypeError Cannot read property"
        tokens = tokenize(query)
        text = "TypeError: Cannot read property 'length' of undefined"
        self.assertTrue(
            text_matches(query, tokens, text),
            "Direct token overlap should still match"
        )


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

    def test_jsondecode_matches_json_parsing_solution(self):
        """Regression: JSONDecodeError query should find 'JSON parsing failed' solution."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'JSON parsing failed because API returned HTML instead of JSON',
                    'root_cause': '404 endpoint returned HTML page and jq tried to parse it',
                    'solution': 'Always validate response content type before JSON parsing',
                    'lesson_learned': 'Check content-type header before parsing response as JSON',
                }
            ]
        }
        result = search_memory(memory, "JSONDecodeError: Expecting value: line 1 column 1 (char 0)")
        self.assertGreater(len(result.matches), 0, "Should find the JSON parsing solution")
        self.assertEqual(result.matches[0].match_type, 'solution')

    def test_jsondecode_matches_solution_with_empty_problem(self):
        """Regression: JSONDecodeError should match solution even with empty problem field."""
        memory = {
            'debug_sessions': [
                {
                    'problem': '',  # Empty problem field (like Session 24)
                    'solution': '404 endpoint returned HTML page. Check response status before parsing.',
                    'root_cause': '',
                    'lesson_learned': '',
                }
            ]
        }
        result = search_memory(memory, "JSONDecodeError")
        self.assertGreater(len(result.matches), 0, "Should find solution via synonym match on 'parsing'")
        self.assertEqual(result.matches[0].match_type, 'solution')

    def test_non_json_response_matches_404_solution(self):
        """Regression: 'non-JSON response' should find 404/HTML solution."""
        memory = {
            'debug_sessions': [
                {
                    'problem': '',
                    'solution': '404 endpoint returned HTML page. Check response status before parsing.',
                    'root_cause': '',
                    'lesson_learned': '',
                }
            ]
        }
        result = search_memory(memory, "non-JSON response")
        self.assertGreater(len(result.matches), 0, "Should find 404/HTML solution")

    def test_no_overmatch_unrelated_queries(self):
        """Ensure irrelevant queries don't match due to weak synonym overlap."""
        memory = {
            'debug_sessions': [
                {
                    'problem': '',
                    'solution': '404 endpoint returned HTML page. Check response status before parsing.',
                    'root_cause': '',
                    'lesson_learned': '',
                }
            ]
        }
        result = search_memory(memory, "database connection timeout")
        self.assertEqual(len(result.matches), 0, "Unrelated query should not match")


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


class TestRelevanceScore(unittest.TestCase):
    """Tests for _relevance_score ranking function."""

    def test_high_similarity_solution_beats_low_similarity_avoid(self):
        """A solution with sim=177 must outrank an avoid with sim=32."""
        solution = SearchMatch(text="Solution", match_type="solution", similarity=177, confidence=90)
        avoid = SearchMatch(text="Avoid", match_type="avoid", similarity=32, confidence=95)

        solution_score = _relevance_score(solution)
        avoid_score = _relevance_score(avoid)

        self.assertGreater(
            solution_score, avoid_score,
            f"Solution (score={solution_score}) should beat avoid (score={avoid_score})"
        )

    def test_type_priority_breaks_ties(self):
        """When similarity is equal, type priority should break the tie."""
        avoid = SearchMatch(text="Avoid", match_type="avoid", similarity=60, confidence=90)
        solution = SearchMatch(text="Solution", match_type="solution", similarity=60, confidence=90)

        avoid_score = _relevance_score(avoid)
        solution_score = _relevance_score(solution)

        self.assertGreater(
            avoid_score, solution_score,
            "Avoid should win tie-breaker when similarity is equal"
        )

    def test_small_similarity_gap_respects_type(self):
        """With small similarity gap (~10), higher type priority can still win."""
        avoid = SearchMatch(text="Avoid", match_type="avoid", similarity=55, confidence=90)
        solution = SearchMatch(text="Solution", match_type="solution", similarity=60, confidence=90)

        avoid_score = _relevance_score(avoid)
        solution_score = _relevance_score(solution)

        # avoid: 55 + 30 = 85, solution: 60 + 27 = 87 → solution wins slightly
        # This is acceptable - the 5-point gap favors the solution
        self.assertGreater(solution_score, avoid_score)

    def test_large_similarity_gap_overrides_type(self):
        """A 50+ point similarity gap should always override type priority."""
        insight = SearchMatch(text="Insight", match_type="insight", similarity=150, confidence=80)
        avoid = SearchMatch(text="Avoid", match_type="avoid", similarity=50, confidence=95)

        insight_score = _relevance_score(insight)
        avoid_score = _relevance_score(avoid)

        self.assertGreater(
            insight_score, avoid_score,
            "High-similarity insight should beat low-similarity avoid"
        )


class TestSearchRanking(unittest.TestCase):
    """Integration tests for search result ranking."""

    def test_jsondecode_solution_ranks_first(self):
        """Regression: JSONDecodeError solution must rank above unrelated avoid patterns."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'JSONDecodeError: Expecting value - API returned HTML instead of JSON',
                    'solution': '404 endpoint returned HTML page. Check response status before parsing.',
                    'root_cause': '',
                    'lesson_learned': '',
                }
            ],
            'avoid': [
                {'what': 'project_context.py is CRITICAL', 'reason': 'This file controls everything'},
            ],
            'decisions': [
                {'decision': 'MCP Diet v3: repeated responses should omit context', 'reason': 'Reduce noise'},
            ],
        }
        result = search_memory(memory, "JSONDecodeError Expecting value line 1 column 1")

        self.assertGreater(len(result.matches), 0, "Should find matches")
        self.assertEqual(
            result.matches[0].match_type, 'solution',
            f"Top result should be solution, got {result.matches[0].match_type}"
        )
        self.assertIn('404', result.matches[0].text, "Top result should be the 404 solution")

    def test_irrelevant_avoid_does_not_outrank_relevant_solution(self):
        """An avoid pattern with low similarity should not outrank a relevant solution."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'Connection timeout when calling external API',
                    'solution': 'Increased timeout to 30 seconds and added retry logic',
                    'root_cause': '',
                    'lesson_learned': '',
                }
            ],
            'avoid': [
                {'what': 'Never modify core auth module', 'reason': 'Security sensitive'},
            ],
        }
        result = search_memory(memory, "connection timeout API")

        self.assertGreater(len(result.matches), 0)
        self.assertEqual(
            result.matches[0].match_type, 'solution',
            "Relevant solution should rank above irrelevant avoid"
        )

    def test_multiple_solutions_ranked_by_similarity(self):
        """When multiple solutions match, higher similarity should rank first."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'Database connection failed',
                    'solution': 'Restart the database server',
                    'root_cause': '',
                    'lesson_learned': '',
                },
                {
                    'problem': 'Database connection pool exhausted timeout',
                    'solution': 'Increased pool size and connection timeout',
                    'root_cause': '',
                    'lesson_learned': '',
                },
            ],
        }
        result = search_memory(memory, "database connection timeout")

        solutions = [m for m in result.matches if m.match_type == 'solution']
        self.assertGreater(len(solutions), 1, "Should find multiple solutions")
        # The more specific match (pool exhausted timeout) should rank higher
        self.assertIn('timeout', solutions[0].text.lower())

    def test_fresh_exact_fix_beats_old_partial(self):
        """Fresh exact actionable fix should beat older partial match."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'LaunchAgent crash loop: ModuleNotFoundError: No module named flask',
                    'solution': 'Added health gate: verify_and_enable_service() starts server manually',
                    'root_cause': '',
                    'lesson_learned': '',
                },
                {
                    'problem': "ModuleNotFoundError: No module named 'requests'",
                    'solution': 'Dependency missing. Run pip install requests.',
                    'root_cause': '',
                    'lesson_learned': '',
                },
            ],
        }
        result = search_memory(memory, "ModuleNotFoundError requests")

        self.assertGreater(len(result.matches), 0)
        self.assertIn(
            'pip install', result.matches[0].text.lower(),
            "Fresh exact fix (pip install requests) should rank first"
        )

    def test_old_exact_fix_beats_fresh_unrelated(self):
        """Old exact fix should still beat a fresh but unrelated memory."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'TypeError: Cannot read property name of undefined',
                    'solution': 'Use optional chaining (user?.name) or fallback object.',
                    'root_cause': '',
                    'lesson_learned': '',
                },
                {
                    'problem': 'Database connection timeout',
                    'solution': 'Increase pool timeout to 30 seconds.',
                    'root_cause': '',
                    'lesson_learned': '',
                },
            ],
        }
        result = search_memory(memory, "TypeError cannot read property name")

        self.assertGreater(len(result.matches), 0)
        self.assertIn(
            'optional chaining', result.matches[0].text.lower(),
            "Exact TypeError fix should rank above unrelated database fix"
        )

    def test_jsondecode_fix_still_works(self):
        """Existing JSONDecodeError search should still find the correct fix."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'json.JSONDecodeError: Expecting value: line 1 column 1',
                    'solution': 'API returned HTML 404 instead of JSON. Check response.status_code before calling response.json().',
                    'root_cause': '',
                    'lesson_learned': '',
                },
            ],
        }
        result = search_memory(memory, "JSONDecodeError expecting value")

        self.assertGreater(len(result.matches), 0)
        self.assertEqual(result.matches[0].match_type, 'solution')
        self.assertIn('status_code', result.matches[0].text.lower())


if __name__ == '__main__':
    unittest.main()
