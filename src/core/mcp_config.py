"""
Shared MCP configuration helpers.
"""

from __future__ import annotations

import re
from pathlib import Path


FASTMCP_ENV = {
    "FASTMCP_SHOW_CLI_BANNER": "false",
    "FASTMCP_CHECK_FOR_UPDATES": "off",
}


def build_stdio_mcp_config(mcp_server: Path, src_path: str, fastmcp_path: str | None = None) -> dict:
    """Build a stdio MCP config shared by supported clients."""
    if fastmcp_path:
        return {
            "command": fastmcp_path,
            "args": ["run", str(mcp_server), "--transport", "stdio", "--no-banner"],
            "env": {"PYTHONPATH": src_path, **FASTMCP_ENV},
        }

    return {
        "command": "",
        "args": [str(mcp_server)],
        "env": {"PYTHONPATH": src_path},
    }


def toml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def remove_codex_server_blocks(content: str, server_name: str) -> str:
    patterns = [
        rf'(?ms)^\[mcp_servers\.{re.escape(server_name)}\]\n(?:.*\n)*?(?=^\[|\Z)',
        rf'(?ms)^\[mcp_servers\.{re.escape(server_name)}\.env\]\n(?:.*\n)*?(?=^\[|\Z)',
    ]

    updated = content
    for pattern in patterns:
        updated = re.sub(pattern, "", updated)
    return updated.strip()


def write_codex_config(path: Path, server_name: str, config: dict):
    """Write or update a Codex MCP server entry."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    existing = remove_codex_server_blocks(existing, server_name)

    lines = [
        f"[mcp_servers.{server_name}]",
        f"command = {toml_quote(config['command'])}",
        f"args = [{', '.join(toml_quote(arg) for arg in config.get('args', []))}]",
    ]

    env = dict(config.get("env", {}))
    env.setdefault("FIXONCE_ACTOR", "codex")
    if env:
        lines.append("")
        lines.append(f"[mcp_servers.{server_name}.env]")
        for key, value in env.items():
            lines.append(f"{key} = {toml_quote(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    new_block = "\n".join(lines).rstrip() + "\n"
    path.write_text((existing + "\n\n" + new_block if existing else new_block), encoding="utf-8")
