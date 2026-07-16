"""
Regression tests for knowledge_counters.py - the single source of truth
for all knowledge counting in FixOnce.

Tests verify:
1. Core and MCP return identical counters
2. Superseded records are not counted as active
3. All existing knowledge types are counted correctly
4. Empty project returns zero values
5. Missing or malformed data is handled correctly
6. No independent counter implementation remains in MCP
"""

import ast
import json
import pytest
import sys
from pathlib import Path

# Add src to path
_SRC_DIR = Path(__file__).parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from core.knowledge_counters import (
    get_live_project_counters,
    get_full_knowledge_counters,
    get_raw_counts,
    format_project_knowledge_line,
    format_memory_stats_block,
    format_cleanup_report_counts,
)


class TestGetLiveProjectCounters:
    """Tests for the primary counter function."""

    def test_empty_memory_returns_zeros(self):
        """Empty memory should return all zeros, not error."""
        result = get_live_project_counters({})
        assert result == {"decisions": 0, "solved": 0, "avoid": 0}

    def test_none_memory_returns_zeros(self):
        """None memory should return all zeros, not error."""
        result = get_live_project_counters(None)
        assert result == {"decisions": 0, "solved": 0, "avoid": 0}

    def test_counts_active_decisions(self):
        """Should count non-superseded decisions."""
        memory = {
            "decisions": [
                {"text": "Use JSON", "superseded": False},
                {"text": "Use SQLite"},  # No superseded key = active
                {"text": "Old decision", "superseded": True},
            ]
        }
        result = get_live_project_counters(memory)
        assert result["decisions"] == 2

    def test_filters_superseded_decisions(self):
        """Superseded decisions should not be counted."""
        memory = {
            "decisions": [
                {"text": "Active", "superseded": False},
                {"text": "Superseded", "superseded": True},
                {"text": "Also superseded", "superseded": True},
            ]
        }
        result = get_live_project_counters(memory)
        assert result["decisions"] == 1

    def test_counts_active_solved_bugs(self):
        """Should count non-superseded debug_sessions."""
        memory = {
            "debug_sessions": [
                {"error": "Bug 1"},
                {"error": "Bug 2", "superseded": False},
                {"error": "Old bug", "superseded": True},
            ]
        }
        result = get_live_project_counters(memory)
        assert result["solved"] == 2

    def test_filters_superseded_solved_bugs(self):
        """Superseded solutions should not be counted."""
        memory = {
            "debug_sessions": [
                {"error": "Active", "superseded": False},
                {"error": "Superseded", "superseded": True},
            ]
        }
        result = get_live_project_counters(memory)
        assert result["solved"] == 1

    def test_counts_avoid_patterns(self):
        """Should count all avoid patterns (never superseded)."""
        memory = {
            "avoid": [
                {"pattern": "Never use eval"},
                {"pattern": "Don't hardcode secrets"},
            ]
        }
        result = get_live_project_counters(memory)
        assert result["avoid"] == 2

    def test_handles_none_values_in_lists(self):
        """Should handle None values in decision/solution lists."""
        memory = {
            "decisions": None,
            "debug_sessions": None,
            "avoid": None,
        }
        result = get_live_project_counters(memory)
        assert result == {"decisions": 0, "solved": 0, "avoid": 0}

    def test_handles_empty_lists(self):
        """Should handle empty lists."""
        memory = {
            "decisions": [],
            "debug_sessions": [],
            "avoid": [],
        }
        result = get_live_project_counters(memory)
        assert result == {"decisions": 0, "solved": 0, "avoid": 0}


class TestGetFullKnowledgeCounters:
    """Tests for comprehensive counter function."""

    def test_counts_all_knowledge_types(self):
        """Should count all knowledge types from memory."""
        memory = {
            "decisions": [{"text": "D1"}, {"text": "D2"}],
            "debug_sessions": [{"error": "S1"}],
            "avoid": [{"pattern": "A1"}],
            "live_record": {
                "lessons": {
                    "insights": [{"text": "I1"}, {"text": "I2"}],
                    "archived": [{"text": "AR1"}],
                    "failed_attempts": [{"attempt": "F1"}, {"attempt": "F2"}],
                }
            }
        }
        result = get_full_knowledge_counters(memory, use_committed=False)

        assert result["decisions"] == 2
        assert result["solved"] == 1
        assert result["avoid"] == 1
        assert result["insights"] == 2
        assert result["archived_insights"] == 1
        assert result["failed_attempts"] == 2

    def test_filters_superseded_in_full_counts(self):
        """Should filter superseded in full counts too."""
        memory = {
            "decisions": [
                {"text": "Active"},
                {"text": "Superseded", "superseded": True},
            ],
            "debug_sessions": [
                {"error": "Active"},
                {"error": "Superseded", "superseded": True},
            ],
        }
        result = get_full_knowledge_counters(memory, use_committed=False)

        assert result["decisions"] == 1
        assert result["solved"] == 1

    def test_empty_returns_zeros(self):
        """Empty memory should return zeros for all types."""
        result = get_full_knowledge_counters({}, use_committed=False)

        assert result["decisions"] == 0
        assert result["solved"] == 0
        assert result["avoid"] == 0
        assert result["insights"] == 0
        assert result["archived_insights"] == 0
        assert result["failed_attempts"] == 0


class TestGetRawCounts:
    """Tests for raw counts (including superseded)."""

    def test_includes_superseded(self):
        """Raw counts should include superseded items."""
        memory = {
            "decisions": [
                {"text": "Active"},
                {"text": "Superseded", "superseded": True},
            ]
        }
        result = get_raw_counts(memory)
        assert result["decisions_total"] == 2

    def test_empty_returns_zeros(self):
        """Empty memory returns zeros."""
        result = get_raw_counts({})
        assert result == {"decisions_total": 0, "avoid_total": 0}


class TestFormatFunctions:
    """Tests for formatting functions."""

    def test_format_project_knowledge_line(self):
        """Should format compact knowledge line."""
        counters = {"decisions": 5, "solved": 3, "avoid": 2}
        result = format_project_knowledge_line(counters)

        assert "5 Decisions" in result
        assert "3 Solved Bugs" in result
        assert "2 Avoid Patterns" in result
        assert "📊" in result

    def test_format_memory_stats_block(self):
        """Should format full stats block."""
        counters = {
            "decisions": 10,
            "solved": 5,
            "avoid": 3,
            "insights": 8,
            "archived_insights": 2,
            "failed_attempts": 1,
        }
        result = format_memory_stats_block(counters)

        assert "**Decisions:** 10" in result
        assert "**Solved Bugs:** 5" in result
        assert "**Avoid Patterns:** 3" in result
        assert "**Active Insights:** 8" in result
        assert "**Archived Insights:** 2" in result
        assert "**Failed Attempts:** 1" in result

    def test_format_memory_stats_block_with_note(self):
        """Should include source note when provided."""
        counters = {"decisions": 1, "solved": 1, "avoid": 1}
        result = format_memory_stats_block(
            counters,
            include_insights=False,
            source_note="Using fallback source"
        )

        assert "Using fallback source" in result

    def test_format_cleanup_report_counts(self):
        """Should format cleanup report section."""
        memory = {
            "decisions": [{"text": "D1"}, {"text": "D2"}],
            "avoid": [{"pattern": "A1"}],
            "live_record": {
                "lessons": {
                    "failed_attempts": [{"attempt": "F1"}],
                    "archived": [{"text": "AR1"}, {"text": "AR2"}],
                }
            }
        }
        newly_archived = [{"text": "New"}]
        still_active = [{"text": "Active1"}, {"text": "Active2"}]

        result = format_cleanup_report_counts(memory, newly_archived, still_active)

        assert "**Decisions:** 2" in result
        assert "**Avoid Patterns:** 1" in result
        assert "**Failed Attempts:** 1" in result
        assert "**Active:** 2" in result
        assert "**Newly Archived:** 1" in result
        assert "**Total Archived:** 2" in result


class TestMCPNoIndependentCounters:
    """
    Architecture regression test: verify MCP delegates to knowledge_counters.py
    instead of computing counts inline.
    """

    def test_no_len_decisions_in_mcp(self):
        """
        MCP should not have direct len(decisions) or len(avoid) outside imports.

        This is a heuristic check - we scan for patterns that indicate
        independent counting logic.
        """
        mcp_path = Path(__file__).parent.parent / "src" / "mcp_server" / "mcp_memory_server_v2.py"
        content = mcp_path.read_text()

        # Split into lines for analysis
        lines = content.split('\n')

        # Patterns that indicate direct counting (not via knowledge_counters)
        forbidden_patterns = [
            # Direct list comprehension counting that filters superseded
            "len([d for d in",
            "len([s for s in",
            # Direct len() on decisions/avoid without using knowledge_counters
            # We check for these patterns only if they're NOT inside comments or imports
        ]

        violations = []
        for i, line in enumerate(lines, 1):
            # Skip comments and imports
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('from ') or stripped.startswith('import '):
                continue

            # Skip lines that are part of knowledge_counters imports
            if 'knowledge_counters' in line:
                continue

            # Check for direct counting patterns
            for pattern in forbidden_patterns:
                if pattern in line:
                    # Check if it's about decisions, solutions, or avoid
                    if any(kw in line for kw in ['decision', 'avoid', 'solution', 'debug_session']):
                        # This is a potential violation - but we need to be more precise
                        # Let's check if this is in a function we haven't updated
                        violations.append((i, line.strip()[:80]))

        # We should have removed all direct counting - if violations exist,
        # it means we missed something or reintroduced direct counting
        assert len(violations) == 0, (
            f"Found {len(violations)} potential direct counting patterns in MCP:\n" +
            "\n".join(f"  Line {ln}: {code}" for ln, code in violations[:5])
        )

    def test_mcp_imports_knowledge_counters(self):
        """MCP should import from knowledge_counters module."""
        mcp_path = Path(__file__).parent.parent / "src" / "mcp_server" / "mcp_memory_server_v2.py"
        content = mcp_path.read_text()

        # Check that the canonical imports are present
        assert "from core.knowledge_counters import" in content, (
            "MCP should import from core.knowledge_counters"
        )

        # Check specific function imports
        expected_imports = [
            "get_live_project_counters",
            "get_raw_counts",
            "format_cleanup_report_counts",
            "get_full_knowledge_counters",
        ]

        for func in expected_imports:
            assert func in content, f"MCP should use {func} from knowledge_counters"


class TestConsistencyBetweenFunctions:
    """Tests that different counter functions are consistent."""

    def test_live_counters_subset_of_full(self):
        """Live counters should be a subset of full counters."""
        memory = {
            "decisions": [{"text": "D1"}],
            "debug_sessions": [{"error": "S1"}],
            "avoid": [{"pattern": "A1"}],
            "live_record": {
                "lessons": {
                    "insights": [{"text": "I1"}],
                    "archived": [],
                    "failed_attempts": [],
                }
            }
        }

        live = get_live_project_counters(memory)
        full = get_full_knowledge_counters(memory, use_committed=False)

        # Live counters should match the corresponding full counters
        assert live["decisions"] == full["decisions"]
        assert live["solved"] == full["solved"]
        assert live["avoid"] == full["avoid"]

    def test_raw_counts_gte_filtered(self):
        """Raw counts should be >= filtered counts."""
        memory = {
            "decisions": [
                {"text": "Active"},
                {"text": "Superseded", "superseded": True},
            ],
            "avoid": [{"pattern": "A1"}],
        }

        live = get_live_project_counters(memory)
        raw = get_raw_counts(memory)

        assert raw["decisions_total"] >= live["decisions"]
        assert raw["avoid_total"] >= live["avoid"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
