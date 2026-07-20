"""
Tests for Connection Awareness V1.

Tests SessionStart hook, fo_status tool, dashboard recording banner,
and protocol compliance for Claude and Codex.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestSessionStartHook(unittest.TestCase):
    """Tests for the session_start.sh hook."""

    def setUp(self):
        self.hook_path = Path(__file__).parent.parent / "hooks" / "session_start.sh"

    def test_hook_exists(self):
        """Hook file should exist and be executable."""
        self.assertTrue(self.hook_path.exists())
        self.assertTrue(os.access(self.hook_path, os.X_OK))

    def test_hook_reads_runtime_json_port(self):
        """Hook should read port from runtime.json."""
        hook_content = self.hook_path.read_text()
        self.assertIn("runtime.json", hook_content)
        self.assertIn("RUNTIME_PORT", hook_content)
        self.assertIn("jq -r '.port", hook_content)

    def test_hook_checks_server_availability(self):
        """Hook should ping server to check availability."""
        hook_content = self.hook_path.read_text()
        self.assertIn("/api/ping", hook_content)
        self.assertIn("SERVER_AVAILABLE", hook_content)

    def test_hook_warns_when_unavailable(self):
        """Hook should output warning when server is unavailable."""
        hook_content = self.hook_path.read_text()
        self.assertIn("⚠️ FixOnce server is unavailable", hook_content)
        self.assertIn("Project memory may NOT be recorded", hook_content)

    def test_hook_provides_recovery_instructions(self):
        """Hook should tell user how to recover connection."""
        hook_content = self.hook_path.read_text()
        self.assertIn("Ensure FixOnce is running", hook_content)
        self.assertIn("NEW AI conversation", hook_content)

    def test_hook_outputs_fo_init_reminder_when_available(self):
        """Hook should output fo_init reminder when server is available."""
        hook_content = self.hook_path.read_text()
        self.assertIn("fo_init(cwd=", hook_content)
        self.assertIn("MUST call", hook_content)

    def test_hook_never_outputs_html(self):
        """Hook should never output raw HTML or 404 pages."""
        hook_content = self.hook_path.read_text()
        # Should not call endpoints that might return HTML errors
        self.assertNotIn("/api/activity/session", hook_content)
        # Comment confirms this is intentional
        self.assertIn("Never raw HTML", hook_content)

    def test_hook_includes_do_not_continue_silently(self):
        """Hook unavailable path must say 'Do not continue silently'."""
        hook_content = self.hook_path.read_text()
        self.assertIn("Do not continue silently", hook_content)


class TestFoStatusTool(unittest.TestCase):
    """Tests for the fo_status MCP tool."""

    def test_fo_status_exists_in_mcp_server(self):
        """fo_status should be defined in the MCP server."""
        mcp_server_path = Path(__file__).parent.parent / "src" / "mcp_server" / "mcp_memory_server_v2.py"
        content = mcp_server_path.read_text()
        self.assertIn("def fo_status()", content)
        self.assertIn("@mcp.tool()", content.split("def fo_status()")[0][-50:])

    def test_fo_status_in_public_mcp_tools(self):
        """fo_status must be in PUBLIC_MCP_TOOLS to be exposed in live contract."""
        mcp_server_path = Path(__file__).parent.parent / "src" / "mcp_server" / "mcp_memory_server_v2.py"
        content = mcp_server_path.read_text()

        # Find PUBLIC_MCP_TOOLS definition
        start = content.find("PUBLIC_MCP_TOOLS = frozenset({")
        end = content.find("})", start)
        public_tools_block = content[start:end]

        self.assertIn('"fo_status"', public_tools_block,
                     "fo_status must be in PUBLIC_MCP_TOOLS for live MCP contract")

    def test_fo_status_is_read_only(self):
        """fo_status should not write to project memory."""
        mcp_server_path = Path(__file__).parent.parent / "src" / "mcp_server" / "mcp_memory_server_v2.py"
        content = mcp_server_path.read_text()

        # Find the fo_status function
        start_idx = content.find("def fo_status()")
        end_markers = ["@mcp.tool()", "def fo_"]
        end_idx = len(content)
        for marker in end_markers:
            next_idx = content.find(marker, start_idx + 20)
            if next_idx > start_idx:
                end_idx = min(end_idx, next_idx)

        fo_status_code = content[start_idx:end_idx]

        # Should not call any write functions
        write_functions = [
            "save_project_memory",
            "save_memory",
            "_save_",
            "write_text",
            "json.dump",
            "fo_sync",
            "fo_decide",
            "fo_solved",
        ]
        for func in write_functions:
            self.assertNotIn(func, fo_status_code,
                           f"fo_status should not call {func}")

    def test_fo_status_returns_recording_status(self):
        """fo_status should return recording status information.

        Note: fo_status always returns green (🟢) because if the tool executes,
        MCP transport is working. The tool's execution IS the proof of connectivity.
        Red/gray states would only appear if the tool couldn't execute (which means
        we wouldn't get a response at all).
        """
        mcp_server_path = Path(__file__).parent.parent / "src" / "mcp_server" / "mcp_memory_server_v2.py"
        content = mcp_server_path.read_text()

        # Find the fo_status function
        start_idx = content.find("def fo_status()")
        end_idx = content.find("@mcp.tool()", start_idx + 20)
        fo_status_code = content[start_idx:end_idx]

        # Should check MCP session health for context
        self.assertIn("get_session_health", fo_status_code)

        # Should return green status (execution proves connectivity)
        self.assertIn("🟢", fo_status_code)

        # Should explain proof of connectivity
        self.assertIn("PROOF OF CONNECTIVITY", fo_status_code)


class TestDashboardRecordingBanner(unittest.TestCase):
    """Tests for the dashboard recording status banner."""

    def setUp(self):
        self.dashboard_path = Path(__file__).parent.parent / "data" / "dashboard_minimal.html"

    def test_recording_banner_exists(self):
        """Dashboard should have recording banner element."""
        content = self.dashboard_path.read_text()
        self.assertIn("recordingBanner", content)
        self.assertIn("recording-banner", content)

    def test_recording_banner_has_three_states(self):
        """Banner should support recording, not-recording, and unknown states."""
        content = self.dashboard_path.read_text()

        # CSS classes
        self.assertIn(".recording-banner.recording", content)
        self.assertIn(".recording-banner.not-recording", content)
        self.assertIn(".recording-banner.unknown", content)

    def test_recording_banner_shows_correct_colors(self):
        """Banner should use green for recording, red for not recording."""
        content = self.dashboard_path.read_text()
        self.assertIn("var(--green)", content)
        self.assertIn("var(--red)", content)

    def test_recording_banner_updates_from_snapshot(self):
        """Banner should update based on dashboard snapshot data.

        Dashboard uses RECENT activity to confirm recording (not stale state).
        Green requires recent MCP activity within threshold.
        """
        content = self.dashboard_path.read_text()

        # JavaScript should read active_agent and mcp_health
        self.assertIn("active_agent", content)
        self.assertIn("mcp_health", content)

        # Should check for RECENT activity (not stale is_connected state)
        self.assertIn("last_seen", content)
        self.assertIn("isMcpRecentActivity", content)
        self.assertIn("ACTIVE_THRESHOLD_SECONDS", content)

    def test_not_recording_shows_recovery_action(self):
        """Not recording state should show recovery instructions."""
        content = self.dashboard_path.read_text()
        self.assertIn("new AI conversation", content)


class TestClaudeMdProtocol(unittest.TestCase):
    """Tests for CLAUDE.md connection awareness protocol."""

    def test_project_claude_md_has_connection_awareness(self):
        """Project CLAUDE.md should have Connection Awareness section."""
        claude_md_path = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md_path.read_text()
        self.assertIn("## Connection Awareness", content)

    def test_claude_md_has_fo_status_in_tools(self):
        """CLAUDE.md should list fo_status in tools table."""
        claude_md_path = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md_path.read_text()
        self.assertIn("fo_status()", content)
        self.assertIn("Verify connection before commit", content)

    def test_claude_md_has_disconnect_handling(self):
        """CLAUDE.md should describe disconnect handling behavior."""
        claude_md_path = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md_path.read_text()
        self.assertIn("MCP connection loss", content)
        self.assertIn("notify the user", content)

    def test_claude_md_has_completion_verification(self):
        """CLAUDE.md should require verification before completion."""
        claude_md_path = Path(__file__).parent.parent / "CLAUDE.md"
        content = claude_md_path.read_text()
        self.assertIn("Before Completion", content)
        self.assertIn("commit", content.lower())


class TestMcpSessionHealthIntegration(unittest.TestCase):
    """Integration tests for MCP session health module."""

    def test_session_health_module_exists(self):
        """MCP session health module should exist."""
        health_path = Path(__file__).parent.parent / "src" / "core" / "mcp_session_health.py"
        self.assertTrue(health_path.exists())

    def test_session_health_has_required_states(self):
        """Session health should define required states."""
        health_path = Path(__file__).parent.parent / "src" / "core" / "mcp_session_health.py"
        content = health_path.read_text()
        self.assertIn("STATE_CONNECTED", content)
        self.assertIn("STATE_SESSION_LOST", content)

    def test_session_health_has_get_function(self):
        """Session health should have get_session_health function."""
        health_path = Path(__file__).parent.parent / "src" / "core" / "mcp_session_health.py"
        content = health_path.read_text()
        self.assertIn("def get_session_health()", content)


class TestCodexProtocol(unittest.TestCase):
    """Tests for canonical Codex protocol (global-agent-rules.md)."""

    def setUp(self):
        self.codex_rules_path = Path(__file__).parent.parent / "data" / "global-agent-rules.md"

    def test_codex_protocol_exists(self):
        """Canonical Codex protocol file should exist."""
        self.assertTrue(self.codex_rules_path.exists())

    def test_codex_has_fo_status(self):
        """Codex protocol should include fo_status tool."""
        content = self.codex_rules_path.read_text()
        self.assertIn("fo_status", content)

    def test_codex_has_startup_connection_check(self):
        """Codex protocol should check connection at startup."""
        content = self.codex_rules_path.read_text()
        self.assertIn("fo_init", content)
        self.assertIn("fails or is unavailable", content)

    def test_codex_has_disconnect_handling(self):
        """Codex protocol should handle mid-session disconnect."""
        content = self.codex_rules_path.read_text()
        self.assertIn("fo_* tools fail", content)
        self.assertIn("Stop and notify", content)

    def test_codex_has_explicit_approval(self):
        """Codex protocol requires explicit approval to continue without FixOnce."""
        content = self.codex_rules_path.read_text()
        self.assertIn("explicit", content.lower())
        self.assertIn("Do you want to continue without FixOnce", content)

    def test_codex_recovery_mentions_new_task(self):
        """Codex recovery should mention starting a new task (Codex-appropriate)."""
        content = self.codex_rules_path.read_text()
        self.assertIn("new Codex task", content)

    def test_codex_uses_current_tool_names(self):
        """Codex protocol should use current fo_* tool names, not legacy names."""
        content = self.codex_rules_path.read_text()
        # Current tool names
        self.assertIn("fo_init", content)
        self.assertIn("fo_search", content)
        self.assertIn("fo_sync", content)
        self.assertIn("fo_errors", content)
        self.assertIn("fo_solved", content)
        self.assertIn("fo_decide", content)
        # Should NOT have legacy names
        self.assertNotIn("auto_init_session", content)
        self.assertNotIn("search_past_solutions", content)
        self.assertNotIn("log_decision", content)
        self.assertNotIn("log_avoid", content)
        self.assertNotIn("update_live_record", content)
        self.assertNotIn("update_component_status", content)


class TestDashboardWording(unittest.TestCase):
    """Tests for dashboard recording banner wording."""

    def setUp(self):
        self.dashboard_path = Path(__file__).parent.parent / "data" / "dashboard_minimal.html"

    def test_red_state_includes_ensure_fixonce_running(self):
        """Dashboard red state must include 'Ensure FixOnce is running'."""
        content = self.dashboard_path.read_text()
        self.assertIn("Ensure FixOnce is running", content)

    def test_green_requires_recent_activity(self):
        """Dashboard green state requires recent MCP activity."""
        content = self.dashboard_path.read_text()
        self.assertIn("isMcpRecentActivity", content)
        self.assertIn("ACTIVE_THRESHOLD_SECONDS", content)

    def test_gray_is_safe_fallback(self):
        """Dashboard gray state is the safe fallback."""
        content = self.dashboard_path.read_text()
        self.assertIn("Recording status not confirmed", content)


if __name__ == "__main__":
    unittest.main()
