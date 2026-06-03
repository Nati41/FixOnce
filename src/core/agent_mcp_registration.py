"""
Agent MCP registration adapters.

FixOnce can register itself with multiple MCP-capable clients. Keep client
specific config formats here so bootstrap remains agent-agnostic.
"""

from __future__ import annotations

from pathlib import Path

from .mcp_config import write_codex_config, write_json_mcp_config


SERVER_NAME = "fixonce"


def _looks_like_python_interpreter(path: Path) -> bool:
    return path.name.lower() in {"python.exe", "pythonw.exe", "python", "pythonw"}


def build_packaged_stdio_config(fixonce_exe: Path, actor: str | None = None) -> dict:
    """Return the packaged stdio command shared by agent adapters."""
    if _looks_like_python_interpreter(fixonce_exe):
        raise ValueError(f"Packaged MCP registration requires FixOnce.exe, got Python interpreter: {fixonce_exe}")

    config = {
        "command": str(fixonce_exe),
        "args": ["--mcp"],
    }
    if actor:
        config["env"] = {"FIXONCE_ACTOR": actor}
    return config


def register_codex_mcp(home_dir: Path, fixonce_exe: Path, server_name: str = SERVER_NAME) -> Path:
    """Create or update the per-user Codex MCP config for FixOnce."""
    config_path = home_dir / ".codex" / "config.toml"
    write_codex_config(config_path, server_name, build_packaged_stdio_config(fixonce_exe, "codex"))
    return config_path


def register_claude_mcp(home_dir: Path, fixonce_exe: Path, server_name: str = SERVER_NAME) -> Path:
    """Create or update the per-user Claude MCP config for FixOnce."""
    config_path = home_dir / ".claude.json"
    write_json_mcp_config(config_path, server_name, build_packaged_stdio_config(fixonce_exe, "claude"))
    return config_path


def register_cursor_mcp(home_dir: Path, fixonce_exe: Path, server_name: str = SERVER_NAME) -> Path:
    """Create or update the per-user Cursor MCP config for FixOnce."""
    config_path = home_dir / ".cursor" / "mcp.json"
    write_json_mcp_config(config_path, server_name, build_packaged_stdio_config(fixonce_exe, "cursor"))
    return config_path


def register_windsurf_mcp(home_dir: Path, fixonce_exe: Path, server_name: str = SERVER_NAME) -> Path:
    """Create or update the per-user Windsurf MCP config for FixOnce."""
    config_path = home_dir / ".codeium" / "windsurf" / "mcp_config.json"
    write_json_mcp_config(config_path, server_name, build_packaged_stdio_config(fixonce_exe, "windsurf"))
    return config_path


WINDOWS_MCP_CLIENT_ADAPTERS = (
    register_codex_mcp,
    register_claude_mcp,
    register_cursor_mcp,
    register_windsurf_mcp,
)


def register_windows_mcp_clients(home_dir: Path, fixonce_exe: Path) -> list[Path]:
    """Register FixOnce with supported Windows MCP clients."""
    return [adapter(home_dir, fixonce_exe) for adapter in WINDOWS_MCP_CLIENT_ADAPTERS]
