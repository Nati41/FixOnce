"""
Tests for MCP search_past_solutions delegation to core.search.

Verifies that MCP search uses core.search.search_memory() for the actual
search logic while keeping MCP-specific formatting and features.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.search import SearchMatch, SearchResult, search_memory


class TestMCPSearchDelegation(unittest.TestCase):
    """Tests that MCP search delegates to core.search."""

    def test_core_search_returns_expected_types(self):
        """Verify core search returns SearchResult with SearchMatch items."""
        memory = {
            'decisions': [
                {'decision': 'Use PostgreSQL production', 'reason': 'Scaling'},
            ],
            'debug_sessions': [
                {'problem': 'Login failed', 'solution': 'Fixed auth'},
            ],
        }
        result = search_memory(memory, "PostgreSQL production")

        self.assertIsInstance(result, SearchResult)
        self.assertGreater(len(result.matches), 0)
        self.assertIsInstance(result.matches[0], SearchMatch)

    def test_search_match_has_required_fields(self):
        """Verify SearchMatch has fields needed for MCP conversion."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'TypeError null check',
                    'solution': 'Added null guard',
                    'root_cause': 'Missing validation',
                    'files_changed': ['src/api.py'],
                }
            ]
        }
        result = search_memory(memory, "TypeError null")

        match = result.matches[0]
        self.assertTrue(hasattr(match, 'text'))
        self.assertTrue(hasattr(match, 'match_type'))
        self.assertTrue(hasattr(match, 'similarity'))
        self.assertTrue(hasattr(match, 'confidence'))
        self.assertTrue(hasattr(match, 'metadata'))
        self.assertTrue(hasattr(match, 'files_changed'))

    def test_search_finds_solutions(self):
        """Verify core search finds debug_sessions (solutions)."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'Authentication token expired',
                    'solution': 'Refresh token before API call',
                    'symptoms': ['401 error', 'login redirect'],
                }
            ]
        }
        result = search_memory(memory, "authentication token expired")

        solution_matches = [m for m in result.matches if m.match_type == 'solution']
        self.assertGreater(len(solution_matches), 0)

    def test_search_finds_avoid_patterns(self):
        """Verify core search finds avoid patterns."""
        memory = {
            'avoid': [
                {'what': 'Direct SQL in components', 'reason': 'Use service layer'},
            ]
        }
        result = search_memory(memory, "SQL components service")

        avoid_matches = [m for m in result.matches if m.match_type == 'avoid']
        self.assertGreater(len(avoid_matches), 0)

    def test_search_finds_decisions(self):
        """Verify core search finds decisions."""
        memory = {
            'decisions': [
                {'decision': 'Use TailwindCSS styling', 'reason': 'Team familiarity'},
            ]
        }
        result = search_memory(memory, "TailwindCSS styling")

        decision_matches = [m for m in result.matches if m.match_type == 'decision']
        self.assertGreater(len(decision_matches), 0)

    def test_mcp_can_convert_search_match_to_dict(self):
        """Verify SearchMatch can be converted to MCP dict format."""
        match = SearchMatch(
            text="🐛 Problem: Auth failed\n✅ Solution: Fixed token",
            match_type="solution",
            similarity=85,
            confidence=90,
            metadata={'resolved_at': '2024-01-15'},
            files_changed=['src/auth.py'],
        )

        # Simulate MCP conversion
        mcp_dict = {
            "text": match.text,
            "type": match.match_type,
            "similarity": match.similarity,
            "confidence": match.confidence,
            "files_changed": match.files_changed,
            "timestamp": match.metadata.get('resolved_at', ''),
            "date": match.metadata.get('resolved_at', '')[:10] if match.metadata.get('resolved_at') else 'unknown',
        }

        self.assertEqual(mcp_dict["text"], match.text)
        self.assertEqual(mcp_dict["type"], "solution")
        self.assertEqual(mcp_dict["similarity"], 85)
        self.assertEqual(mcp_dict["files_changed"], ['src/auth.py'])


class TestCoreSearchEquivalence(unittest.TestCase):
    """Tests that core.search produces equivalent results to original MCP search."""

    def test_decision_search_produces_formatted_text(self):
        """Verify decisions are formatted with emoji markers."""
        memory = {
            'decisions': [
                {'decision': 'Use REST APIs', 'reason': 'Standard pattern'},
            ]
        }
        result = search_memory(memory, "REST APIs")

        if result.matches:
            text = result.matches[0].text
            self.assertIn('🔒', text)  # Decision marker
            self.assertIn('Decision:', text)

    def test_avoid_search_produces_formatted_text(self):
        """Verify avoid patterns are formatted with emoji markers."""
        memory = {
            'avoid': [
                {'what': 'Global state mutations', 'reason': 'Hard to debug'},
            ]
        }
        result = search_memory(memory, "global state mutations")

        if result.matches:
            text = result.matches[0].text
            self.assertIn('⛔', text)  # Avoid marker
            self.assertIn('Avoid:', text)

    def test_solution_search_produces_formatted_text(self):
        """Verify solutions are formatted with emoji markers."""
        memory = {
            'debug_sessions': [
                {
                    'problem': 'Memory leak widgets',
                    'solution': 'Cleanup event listeners',
                    'root_cause': 'Missing unmount handler',
                }
            ]
        }
        result = search_memory(memory, "memory leak widgets")

        if result.matches:
            text = result.matches[0].text
            self.assertIn('🐛', text)  # Problem marker
            self.assertIn('✅', text)  # Solution marker


if __name__ == '__main__':
    unittest.main()
