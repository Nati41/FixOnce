"""
Agent MCP registration adapters.

FixOnce can register itself with multiple MCP-capable clients. Keep client
specific config formats here so bootstrap remains agent-agnostic.
"""

from __future__ import annotations

from pathlib import Path

from .mcp_config import write_codex_config


SERVER_NAME = "fixonce"


def build_packaged_stdio_config(fixonce_exe: Path) -> dict:
    """Return the packaged stdio command shared by agent adapters."""
    return {
        "command": str(fixonce_exe),
        "args": ["--mcp"],
    }


def register_codex_mcp(home_dir: Path, fixonce_exe: Path, server_name: str = SERVER_NAME) -> Path:
    """Create or update the per-user Codex MCP config for FixOnce."""
    config_path = home_dir / ".codex" / "config.toml"
    write_codex_config(config_path, server_name, build_packaged_stdio_config(fixonce_exe), include_actor_env=False)
    return config_path


WINDOWS_MCP_CLIENT_ADAPTERS = (
    register_codex_mcp,
)


def register_windows_mcp_clients(home_dir: Path, fixonce_exe: Path) -> list[Path]:
    """Register FixOnce with supported Windows MCP clients."""
    return [adapter(home_dir, fixonce_exe) for adapter in WINDOWS_MCP_CLIENT_ADAPTERS]
