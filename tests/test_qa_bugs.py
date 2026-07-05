"""
Regression tests for QA-discovered bugs.

BUG-001: Browser errors are global instead of project-scoped
BUG-002: decisions.json not being updated (local state mismatch)
BUG-003: Corrupted metadata files silently ignored
BUG-004: Similarity scores can exceed 100%
"""

import json
import sys
import tempfile
import pytest
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


class TestBug001BrowserErrorsGlobal:
    """BUG-001: Browser errors should be filtered by project_id."""

    def test_api_live_errors_has_project_id_filter(self):
        """Verify /api/live-errors code includes project_id filtering."""
        errors_path = Path(__file__).parent.parent / 'src' / 'api' / 'errors.py'
        code = errors_path.read_text()

        # Check project_id parameter is added
        assert "project_id = request.args.get('project_id'" in code, \
            "BUG-001: project_id parameter not added to api_live_errors"

        # Check filtering logic is present
        assert "e.get('_project_id') == project_id" in code, \
            "BUG-001: project_id filtering logic not present"

    def test_mcp_get_browser_errors_passes_project_id(self):
        """Verify get_browser_errors passes project_id to API."""
        mcp_path = Path(__file__).parent.parent / 'src' / 'mcp_server' / 'mcp_memory_server_v2.py'
        code = mcp_path.read_text()

        # Find the get_browser_errors function
        assert "project_id={project_id}" in code or "?project_id=" in code, \
            "BUG-001: get_browser_errors doesn't pass project_id to API"


class TestBug002DecisionsJsonSync:
    """BUG-002: Decisions should sync to local .fixonce/decisions.json."""

    def test_save_project_includes_committed_knowledge_sync(self):
        """Verify _save_project calls update_committed_on_save."""
        mcp_path = Path(__file__).parent.parent / 'src' / 'mcp_server' / 'mcp_memory_server_v2.py'
        code = mcp_path.read_text()

        # Find the _save_project function and check for sync call
        save_project_start = code.find('def _save_project(')
        assert save_project_start != -1, "_save_project function not found"

        # Get function body (until next def at same indentation)
        func_end = code.find('\ndef ', save_project_start + 1)
        func_body = code[save_project_start:func_end]

        assert "update_committed_on_save" in func_body, \
            "BUG-002: update_committed_on_save not called in _save_project"


class TestBug003CorruptedMetadata:
    """BUG-003: Corrupted metadata.json should be detected and handled."""

    def test_get_project_metadata_handles_corruption(self):
        """Verify get_project_metadata has corruption handling."""
        ck_path = Path(__file__).parent.parent / 'src' / 'core' / 'committed_knowledge.py'
        code = ck_path.read_text()

        # Find get_project_metadata function
        func_start = code.find('def get_project_metadata(')
        assert func_start != -1, "get_project_metadata function not found"

        func_end = code.find('\ndef ', func_start + 1)
        func_body = code[func_start:func_end]

        # Check for corruption handling
        assert "JSONDecodeError" in func_body or "json.JSONDecodeError" in func_body, \
            "BUG-003: JSONDecodeError handling not present"
        assert "Corrupted" in func_body or "corrupted" in func_body, \
            "BUG-003: Corruption detection message not present"

    def test_corrupted_metadata_detected_and_handled(self):
        """Integration test: corrupted metadata.json is handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixonce_dir = Path(tmpdir) / ".fixonce"
            fixonce_dir.mkdir()
            metadata_path = fixonce_dir / "metadata.json"

            # Write corrupted JSON
            metadata_path.write_text("{corrupted json!!!")

            from core.committed_knowledge import get_project_metadata

            # Should return None and not crash
            result = get_project_metadata(tmpdir)
            assert result is None

            # Corrupted file should be removed (so it can be regenerated)
            assert not metadata_path.exists()


class TestBug004SimilarityCap:
    """BUG-004: Similarity scores should never exceed 100%."""

    def test_calculate_similarity_capped_at_100(self):
        """Verify _calculate_similarity never returns > 100."""
        from mcp_server.mcp_memory_server_v2 import _calculate_similarity

        # Test various inputs
        test_cases = [
            ("hello world", "hello world"),  # Exact match
            ("a b c", "a b c d e f"),  # Subset
            ("test test test", "test"),  # Repetitive
            ("x y z", "a b c"),  # No match
        ]

        for query, text in test_cases:
            result = _calculate_similarity(query, text)
            assert result <= 100, f"Similarity > 100 for query='{query}', text='{text}'"
            assert result >= 0, f"Similarity < 0 for query='{query}', text='{text}'"

    def test_format_smart_override_similarity_capped(self):
        """Verify _format_smart_override caps similarity at 100."""
        from mcp_server.mcp_memory_server_v2 import _format_smart_override

        insight = {
            "text": "Test insight text",
            "timestamp": "2024-01-01T00:00:00",
            "use_count": 10
        }

        result = _format_smart_override(insight, "test")
        assert result["similarity"] <= 100

    def test_similarity_capping_in_source(self):
        """Verify min(100, ...) patterns exist for similarity capping."""
        src_dir = Path(__file__).parent.parent / 'src'

        # Check MCP server for _find_solution_for_error caps
        mcp_path = src_dir / 'mcp_server' / 'mcp_memory_server_v2.py'
        mcp_code = mcp_path.read_text()
        mcp_caps = mcp_code.count("min(100,")

        # Check core/search.py for semantic search caps
        search_path = src_dir / 'core' / 'search.py'
        search_code = search_path.read_text()
        search_caps = search_code.count("min(100,")

        total_caps = mcp_caps + search_caps
        assert total_caps >= 3, \
            f"BUG-004: Only {total_caps} similarity caps found across mcp ({mcp_caps}) and search ({search_caps}), expected >= 3"


class TestRegressionSuite:
    """Combined regression test for all QA bugs."""

    def test_all_bugs_regression_complete(self):
        """Meta-test to ensure all bug fixes are properly in place."""
        src_dir = Path(__file__).parent.parent / 'src'

        # BUG-001: Project-scoped browser errors
        errors_code = (src_dir / 'api' / 'errors.py').read_text()
        assert "project_id = request.args.get('project_id'" in errors_code, \
            "BUG-001 FIX MISSING: project_id parameter in api_live_errors"

        mcp_code = (src_dir / 'mcp_server' / 'mcp_memory_server_v2.py').read_text()
        assert "?project_id=" in mcp_code, \
            "BUG-001 FIX MISSING: project_id not passed in get_browser_errors"

        # BUG-002: Committed knowledge sync
        assert "update_committed_on_save" in mcp_code, \
            "BUG-002 FIX MISSING: update_committed_on_save not called"

        # BUG-003: Corrupted file handling
        ck_code = (src_dir / 'core' / 'committed_knowledge.py').read_text()
        assert "JSONDecodeError" in ck_code, \
            "BUG-003 FIX MISSING: JSONDecodeError handling not present"
        assert "Corrupted metadata" in ck_code, \
            "BUG-003 FIX MISSING: Corruption warning not present"

        # BUG-004: Similarity capping (in MCP and core/search.py)
        search_code = (src_dir / 'core' / 'search.py').read_text()
        total_caps = mcp_code.count("min(100,") + search_code.count("min(100,")
        assert total_caps >= 3, \
            "BUG-004 FIX MISSING: Insufficient similarity capping"

        print("All QA bug fixes verified!")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
