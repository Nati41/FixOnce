"""
Tests for fo_solved MCP tool schema and resolution flow.

These tests verify the LIVE MCP tool schema, not just the underlying Python function.
This prevents schema/implementation mismatches like the one where resolution parameters
were added to solution_applied() but not exposed in the public fo_solved() schema.
"""

import sys
import unittest
import asyncio
from pathlib import Path

TEST_DIR = Path(__file__).parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))


class TestFoSolvedMCPSchema(unittest.TestCase):
    """Tests that verify the live MCP tool schema for fo_solved."""

    @classmethod
    def setUpClass(cls):
        """Load the MCP server and get the fo_solved tool schema."""
        from mcp_server.mcp_memory_server_v2 import mcp

        async def get_schema():
            tools = await mcp.list_tools()
            for tool in tools:
                if tool.name == "fo_solved":
                    return tool.parameters
            return None

        cls.schema = asyncio.run(get_schema())
        cls.properties = cls.schema.get("properties", {}) if cls.schema else {}

    def test_schema_exists(self):
        """fo_solved tool must be registered with a schema."""
        self.assertIsNotNone(self.schema, "fo_solved schema not found")

    def test_schema_contains_resolution_action(self):
        """Live schema must include resolution_action parameter."""
        self.assertIn(
            "resolution_action",
            self.properties,
            "resolution_action missing from live MCP schema"
        )

    def test_schema_contains_resolution_target_id(self):
        """Live schema must include resolution_target_id parameter."""
        self.assertIn(
            "resolution_target_id",
            self.properties,
            "resolution_target_id missing from live MCP schema"
        )

    def test_resolution_action_is_optional(self):
        """resolution_action must be optional (not in required list)."""
        required = self.schema.get("required", [])
        self.assertNotIn(
            "resolution_action",
            required,
            "resolution_action should be optional, not required"
        )

    def test_resolution_target_id_is_optional(self):
        """resolution_target_id must be optional (not in required list)."""
        required = self.schema.get("required", [])
        self.assertNotIn(
            "resolution_target_id",
            required,
            "resolution_target_id should be optional, not required"
        )

    def test_error_is_required(self):
        """error parameter must be required."""
        required = self.schema.get("required", [])
        self.assertIn("error", required, "error should be required")

    def test_solution_is_required(self):
        """solution parameter must be required."""
        required = self.schema.get("required", [])
        self.assertIn("solution", required, "solution should be required")

    def test_files_is_optional(self):
        """files parameter must be optional."""
        required = self.schema.get("required", [])
        self.assertNotIn("files", required, "files should be optional")

    def test_additional_properties_false(self):
        """Schema must reject unknown properties."""
        self.assertEqual(
            self.schema.get("additionalProperties"),
            False,
            "Schema should reject additional properties"
        )

    def test_resolution_action_description_lists_valid_values(self):
        """resolution_action description should list valid values."""
        desc = self.properties.get("resolution_action", {}).get("description", "")
        self.assertIn("supersede_existing", desc)
        self.assertIn("cancel", desc)


class TestFoSolvedMCPValidation(unittest.TestCase):
    """Tests that verify fo_solved validation at the MCP layer."""

    def test_normal_call_works(self):
        """Normal fo_solved call with just error/solution works."""
        from mcp_server.mcp_memory_server_v2 import fo_solved

        # This would fail in production if MCP schema is wrong
        # We can't fully test MCP invocation without a running server,
        # but we can test the function directly
        # Note: This will fail without a session, which is expected
        result = fo_solved(error="Test error", solution="Test fix")
        # Should either work or fail gracefully, not crash
        self.assertIsInstance(result, str)

    def test_invalid_resolution_action_rejected(self):
        """Invalid resolution_action values are rejected."""
        from mcp_server.mcp_memory_server_v2 import fo_solved

        result = fo_solved(
            error="Test error",
            solution="Test fix",
            resolution_action="invalid_action",
        )
        self.assertIn("Error", result)
        self.assertIn("invalid_action", result.lower())

    def test_supersede_requires_target_id(self):
        """supersede_existing requires resolution_target_id."""
        from mcp_server.mcp_memory_server_v2 import fo_solved

        result = fo_solved(
            error="Test error",
            solution="Test fix",
            resolution_action="supersede_existing",
            # Missing resolution_target_id
        )
        self.assertIn("Error", result)
        self.assertIn("resolution_target_id", result)

    def test_cancel_does_not_require_target_id(self):
        """cancel action does not require resolution_target_id (but does require review_id)."""
        from unittest.mock import patch
        from mcp_server.mcp_memory_server_v2 import fo_solved

        # Mock the session gate to allow the call through
        with patch("mcp_server.mcp_memory_server_v2._universal_gate") as mock_gate:
            mock_gate.return_value = (None, "")

            # Mock solution_applied to return cancel result
            with patch("mcp_server.mcp_memory_server_v2.solution_applied") as mock_sa:
                mock_sa.return_value = "Solution cancelled by user"

                result = fo_solved(
                    error="Test error",
                    solution="Test fix",
                    resolution_action="cancel",
                    resolution_review_id="solrev_test123",  # Required for security
                    # No target ID needed for cancel
                )
                # Should return cancellation message, not validation error
                self.assertNotIn("resolution_target_id", result)
                self.assertIn("cancel", result.lower())

    def test_resolution_action_requires_review_id(self):
        """Resolution actions require resolution_review_id (security)."""
        from unittest.mock import patch
        from mcp_server.mcp_memory_server_v2 import fo_solved

        with patch("mcp_server.mcp_memory_server_v2._universal_gate") as mock_gate:
            mock_gate.return_value = (None, "")

            # Try cancel without review_id
            result = fo_solved(
                error="Test error",
                solution="Test fix",
                resolution_action="cancel",
            )
            # Should reject - no review_id
            self.assertIn("resolution_review_id is required", result)


class TestFoSolvedProductionPath(unittest.TestCase):
    """Production-path tests using the same invocation layer as Codex."""

    def test_schema_matches_function_signature(self):
        """MCP schema parameters must match function signature."""
        import inspect
        from mcp_server.mcp_memory_server_v2 import fo_solved, mcp

        # Get function signature
        sig = inspect.signature(fo_solved)
        func_params = set(sig.parameters.keys())

        # Get MCP schema
        async def get_schema():
            tools = await mcp.list_tools()
            for tool in tools:
                if tool.name == "fo_solved":
                    return tool.parameters
            return None

        schema = asyncio.run(get_schema())
        schema_params = set(schema.get("properties", {}).keys())

        self.assertEqual(
            func_params,
            schema_params,
            f"Schema/function mismatch: schema has {schema_params}, function has {func_params}"
        )

    def test_resolution_parameters_forwarded_to_core(self):
        """Resolution parameters must reach core.solutions.record_solution."""
        from unittest.mock import patch, MagicMock
        from mcp_server.mcp_memory_server_v2 import fo_solved

        # Mock the session gate to allow the call
        with patch("mcp_server.mcp_memory_server_v2._universal_gate") as mock_gate:
            mock_gate.return_value = (None, "")

            # Mock solution_applied to capture arguments
            with patch("mcp_server.mcp_memory_server_v2.solution_applied") as mock_sa:
                mock_sa.return_value = "Test result"

                fo_solved(
                    error="Test error",
                    solution="Test fix",
                    files="test.py",
                    resolution_action="supersede_existing",
                    resolution_target_id="sol_123",
                    resolution_review_id="solrev_test456",  # Required for security
                )

                # Verify resolution parameters were passed
                mock_sa.assert_called_once()
                call_kwargs = mock_sa.call_args[1]
                self.assertEqual(call_kwargs.get("resolution_action"), "supersede_existing")
                self.assertEqual(call_kwargs.get("resolution_target_id"), "sol_123")
                self.assertEqual(call_kwargs.get("resolution_review_id"), "solrev_test456")


class TestFoSolvedBackwardCompatibility(unittest.TestCase):
    """Tests ensuring backward compatibility with existing calls."""

    def test_three_arg_call_still_works(self):
        """Existing calls with just error, solution, files still work."""
        from mcp_server.mcp_memory_server_v2 import fo_solved

        # This is the original call pattern
        result = fo_solved(
            error="TypeError: undefined",
            solution="Added null check",
            files="src/app.ts",
        )
        # Should not crash, even if it fails due to missing session
        self.assertIsInstance(result, str)

    def test_positional_args_still_work(self):
        """Positional arguments for error, solution, files still work."""
        from mcp_server.mcp_memory_server_v2 import fo_solved

        # Old style positional call
        result = fo_solved("Error message", "Fix applied", "file.py")
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
