"""
Test Codex MCP config generation.

Ensures Codex config.toml never gets args = ["--mcp"] without a script path.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add project paths
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from install import build_install_stdio_config, _build_stdio_mcp_config
import install as install_module


class TestCodexMcpConfig:
    """Test that Codex MCP config is always valid."""

    def test_build_stdio_config_has_script_path_in_args(self):
        """Config args must contain script path, not just flags."""
        config = build_install_stdio_config()
        args = config.get("args", [])
        
        # Args should not be just ["--mcp"]
        assert args != ["--mcp"], "args should not be just ['--mcp'] without script path"
        
        # Args should contain a .py file path
        has_py_path = any(".py" in str(arg) for arg in args)
        assert has_py_path, f"args should contain .py script path, got: {args}"

    def test_build_stdio_config_without_fastmcp_has_script_path(self):
        """Even without fastmcp, args must have script path."""
        config = _build_stdio_mcp_config(
            command="/usr/bin/python3",
            server_path="/path/to/mcp_memory_server_v2.py",
            pythonpath="/path/to/src",
            fastmcp_path=None
        )
        args = config.get("args", [])
        
        # Args should be ["/path/to/mcp_memory_server_v2.py"]
        assert len(args) >= 1, "args should have at least one element"
        assert args[0].endswith(".py"), f"First arg should be script path, got: {args[0]}"
        assert args != ["--mcp"], "args should not be just ['--mcp']"

    def test_build_stdio_config_with_fastmcp_has_script_path(self):
        """With fastmcp, args must include script path."""
        config = _build_stdio_mcp_config(
            command="/usr/bin/python3",
            server_path="/path/to/mcp_memory_server_v2.py",
            pythonpath="/path/to/src",
            fastmcp_path="/usr/bin/fastmcp"
        )
        args = config.get("args", [])
        
        # Args should be ["run", "/path/to/...", "--transport", "stdio", "--no-banner"]
        assert len(args) >= 2, "fastmcp args should have multiple elements"
        assert any(".py" in str(arg) for arg in args), f"args should contain .py path, got: {args}"
        assert args != ["--mcp"], "args should not be just ['--mcp']"

    def test_codex_args_never_just_mcp_flag(self):
        """Ensure args is never just ['--mcp'] in any config variant."""
        # This is the core regression test
        config = build_install_stdio_config(probe_fastmcp=True)
        assert config.get("args") != ["--mcp"], "Config should not have args=['--mcp']"
        
        config_no_fastmcp = build_install_stdio_config(probe_fastmcp=False)
        assert config_no_fastmcp.get("args") != ["--mcp"], "Config without fastmcp should not have args=['--mcp']"

    def test_packaged_stdio_config_uses_mcp_console_companion(self):
        """Packaged Windows MCP must use the console-subsystem companion exe."""
        with tempfile.TemporaryDirectory(prefix="fixonce-install-mcp-") as temp_dir:
            install_dir = Path(temp_dir)
            fixonce_exe = install_dir / "FixOnce.exe"
            mcp_exe = install_dir / "FixOnceMCP.exe"
            fixonce_exe.write_text("", encoding="utf-8")
            mcp_exe.write_text("", encoding="utf-8")

            with patch.object(install_module, "get_platform", return_value="windows"):
                config = build_install_stdio_config(install_dir)

        assert config["command"] == str(mcp_exe)
        assert config["args"] == ["--mcp"]
