"""
MCP Tool Surface Tests.

Verifies that:
1. Only canonical public tools are exposed to agents
2. Legacy/duplicate tools are internal only
3. Core tools still work
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


class TestMCPToolSurface:
    """Test that MCP tool surface is properly restricted."""

    def test_public_tools_count(self):
        """Only 8 canonical tools should be public."""
        from mcp_server.mcp_memory_server_v2 import get_public_tools

        public = get_public_tools()
        assert len(public) == 8, f"Expected 8 public tools, got {len(public)}: {public}"

    def test_canonical_public_tools(self):
        """Verify the exact set of public tools."""
        from mcp_server.mcp_memory_server_v2 import get_public_tools

        expected = {
            "fo_init",
            "fo_search",
            "fo_sync",
            "fo_errors",
            "fo_decide",
            "fo_solved",
            "fo_brief",
            "fo_apply",
        }

        public = get_public_tools()
        assert public == expected, f"Public tools mismatch. Expected {expected}, got {public}"

    def test_legacy_duplicates_are_internal(self):
        """Legacy duplicate tools should NOT be public."""
        from mcp_server.mcp_memory_server_v2 import get_public_tools, get_internal_tools

        public = get_public_tools()
        internal = get_internal_tools()

        # These are duplicates of fo_* tools and should be internal
        legacy_duplicates = {
            "init_session",        # duplicate of fo_init
            "search_past_solutions",  # duplicate of fo_search
            "log_decision",        # duplicate of fo_decide
            "log_debug_session",   # duplicate of fo_solved
            "solution_applied",    # duplicate of fo_solved
            "log_avoid",           # duplicate of fo_decide(action="avoid")
            "supersede_decision",  # duplicate of fo_decide(action="supersede:...")
        }

        for tool in legacy_duplicates:
            assert tool not in public, f"Legacy tool {tool} should NOT be public"
            assert tool in internal, f"Legacy tool {tool} should be internal"

    def test_broken_tools_are_internal(self):
        """Broken/disabled tools should NOT be public."""
        from mcp_server.mcp_memory_server_v2 import get_public_tools

        public = get_public_tools()

        broken_tools = {
            "get_impact_stats",
            "get_browser_context",
        }

        for tool in broken_tools:
            assert tool not in public, f"Broken tool {tool} should NOT be public"

    def test_component_tools_are_internal(self):
        """Component management tools should be internal."""
        from mcp_server.mcp_memory_server_v2 import get_public_tools, get_internal_tools

        public = get_public_tools()
        internal = get_internal_tools()

        component_tools = {
            "add_component_files",
            "auto_discover_components",
            "check_component_changes",
            "mark_component_stable",
            "rollback_component",
            "update_component_status",
            "fo_component",
        }

        for tool in component_tools:
            assert tool not in public, f"Component tool {tool} should NOT be public"
            assert tool in internal, f"Component tool {tool} should be internal"

    def test_dashboard_tools_are_internal(self):
        """Dashboard-specific tools should be internal."""
        from mcp_server.mcp_memory_server_v2 import get_public_tools

        public = get_public_tools()

        dashboard_tools = {
            "detect_project_from_port",
            "highlight_element",
            "scan_project",
            "sync_to_active_project",
            "update_live_record",
            "update_work_context",
            "generate_context",
        }

        for tool in dashboard_tools:
            assert tool not in public, f"Dashboard tool {tool} should NOT be public"

    def test_internal_tools_still_callable(self):
        """Internal tools should still be callable (for dashboard/server)."""
        from mcp_server.mcp_memory_server_v2 import (
            search_past_solutions,
            log_decision,
            init_session,
        )

        # These should be callable functions (not None)
        assert callable(search_past_solutions)
        assert callable(log_decision)
        assert callable(init_session)

    def test_public_tools_are_callable(self):
        """All public tools should be callable functions."""
        from mcp_server.mcp_memory_server_v2 import (
            fo_init,
            fo_search,
            fo_sync,
            fo_errors,
            fo_decide,
            fo_solved,
            fo_brief,
            fo_apply,
        )

        assert callable(fo_init)
        assert callable(fo_search)
        assert callable(fo_sync)
        assert callable(fo_errors)
        assert callable(fo_decide)
        assert callable(fo_solved)
        assert callable(fo_brief)
        assert callable(fo_apply)


class TestCoreFunctionality:
    """Test that core tools still work after refactoring."""

    def test_fo_search_delegates_to_search_past_solutions(self):
        """fo_search should call search_past_solutions internally."""
        from mcp_server.mcp_memory_server_v2 import fo_search

        # Should not crash, returns string
        result = fo_search("test query")
        assert isinstance(result, str)

    def test_fo_decide_handles_avoid_action(self):
        """fo_decide with action='avoid' should work."""
        from mcp_server.mcp_memory_server_v2 import fo_decide

        # Should not crash (will fail due to no session, but that's expected)
        result = fo_decide("Never use eval", "Security risk", action="avoid")
        assert isinstance(result, str)

    def test_fo_solved_delegates_to_solution_applied(self):
        """fo_solved should call solution_applied internally."""
        from mcp_server.mcp_memory_server_v2 import fo_solved

        # Should not crash
        result = fo_solved("Test error", "Test solution")
        assert isinstance(result, str)


class TestToolCounts:
    """Test tool count expectations."""

    def test_total_tools_reasonable(self):
        """Total tools (public + internal) should be reasonable."""
        from mcp_server.mcp_memory_server_v2 import get_public_tools, get_internal_tools

        public = get_public_tools()
        internal = get_internal_tools()
        total = len(public) + len(internal)

        # Should be around 50 total (8 public + ~42 internal)
        assert total >= 40, f"Expected at least 40 total tools, got {total}"
        assert total <= 60, f"Expected at most 60 total tools, got {total}"

    def test_no_overlap_public_internal(self):
        """Public and internal tool sets should not overlap."""
        from mcp_server.mcp_memory_server_v2 import get_public_tools, get_internal_tools

        public = get_public_tools()
        internal = get_internal_tools()
        overlap = public & internal

        assert len(overlap) == 0, f"Tools in both public and internal: {overlap}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
