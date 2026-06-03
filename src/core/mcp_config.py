"""
Shared MCP configuration helpers.
"""

from __future__ import annotations

import json
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
    target_headers = {
        f"[mcp_servers.{server_name}]",
        f"[mcp_servers.{server_name}.env]",
    }

    kept: list[str] = []
    skip = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            skip = stripped in target_headers
        if not skip:
            kept.append(line)

    return "\n".join(kept).strip()


def write_codex_config(path: Path, server_name: str, config: dict, include_actor_env: bool = True):
    """Write or update a Codex MCP server entry."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    existing = remove_codex_server_blocks(existing, server_name)

    lines = [
        f"[mcp_servers.{server_name}]",
        f"command = {toml_quote(config['command'])}",
        f"args = [{', '.join(toml_quote(arg) for arg in config.get('args', []))}]",
        "startup_timeout_sec = 60",
    ]

    env = dict(config.get("env", {}))
    if include_actor_env:
        env.setdefault("FIXONCE_ACTOR", "codex")
    if env:
        lines.append("")
        lines.append(f"[mcp_servers.{server_name}.env]")
        for key, value in env.items():
            lines.append(f"{key} = {toml_quote(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    new_block = "\n".join(lines).rstrip() + "\n"
    path.write_text((existing + "\n\n" + new_block if existing else new_block), encoding="utf-8")


def write_json_mcp_config(path: Path, server_name: str, config: dict):
    """Write or update an MCP server entry in JSON client configs."""
    existing: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}

    servers = existing.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        existing["mcpServers"] = servers

    servers[server_name] = config

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
