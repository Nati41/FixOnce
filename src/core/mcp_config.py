"""
Shared MCP configuration helpers.
"""

from __future__ import annotations

import json
import re
import tomllib
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


def looks_like_python_interpreter(command: str) -> bool:
    name = str(command or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return bool(re.fullmatch(r"python(?:w)?(?:\d+(?:\.\d+)*)?(?:\.exe)?", name))


def extract_codex_server_config(content: str, server_name: str) -> dict | None:
    if not content.strip():
        return None

    toml_decode_error = False
    try:
        parsed = tomllib.loads(content)
        servers = parsed.get("mcp_servers", {})
        server = servers.get(server_name)
        return server if isinstance(server, dict) else None
    except tomllib.TOMLDecodeError:
        toml_decode_error = True

    section = re.search(
        rf"(?ms)^\[mcp_servers\.{re.escape(server_name)}\]\s*\n(?P<body>.*?)(?=^\[|\Z)",
        content,
    )
    if not section:
        return None

    body = section.group("body")
    command_match = re.search(r'(?m)^\s*command\s*=\s*"(?P<command>(?:\\.|[^"])*)"\s*$', body)
    args_match = re.search(r"(?m)^\s*args\s*=\s*\[(?P<args>[^\]]*)\]\s*$", body)
    result: dict = {}
    if command_match:
        result["command"] = command_match.group("command").replace('\\"', '"').replace("\\\\", "\\")
    if args_match:
        result["args"] = re.findall(r'"((?:\\.|[^"])*)"', args_match.group("args"))
    if result and toml_decode_error:
        result["_toml_decode_error"] = True
    return result or None


def is_broken_python_mcp_config(server_config: dict | None) -> bool:
    if not isinstance(server_config, dict):
        return False

    args = server_config.get("args", [])
    if isinstance(args, str):
        args = [args]
    if not isinstance(args, list):
        return False

    normalized_args = [str(arg).strip() for arg in args if str(arg).strip()]
    command_name = str(server_config.get("command", "") or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    packaged_with_script_args = command_name in {"fixonce.exe", "fixoncemcp.exe"} and any(
        str(arg).lower().endswith(".py") for arg in normalized_args
    )
    return (
        bool(server_config.get("_toml_decode_error"))
        or (looks_like_python_interpreter(str(server_config.get("command", ""))) and normalized_args == ["--mcp"])
        or packaged_with_script_args
    )


def validate_codex_repair_config(config: dict) -> tuple[bool, str]:
    command = str(config.get("command", "") or "")
    args = config.get("args", [])
    if isinstance(args, str):
        args = [args]
    if not command:
        return False, "replacement command is empty"
    if is_broken_python_mcp_config({"command": command, "args": args}):
        return False, "replacement would still launch Python with --mcp and no script"
    if looks_like_python_interpreter(command) and not any(str(arg).endswith(".py") for arg in args):
        return False, "source replacement must pass the MCP server .py path to Python"
    return True, ""


def remove_codex_server_blocks(content: str, server_name: str) -> str:
    target_sections = {
        f"mcp_servers.{server_name}",
        f"mcp_servers.{server_name}.env",
    }
    kept_lines = []
    skipping = False

    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section_name = stripped[1:-1].strip()
            skipping = section_name in target_sections

        if not skipping:
            kept_lines.append(line)

    return "".join(kept_lines).rstrip()


def write_codex_config(path: Path, server_name: str, config: dict, include_actor_env: bool = True) -> str:
    """Create missing Codex config or repair only the known broken Python --mcp form."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    current = extract_codex_server_config(existing, server_name)
    if current is not None and not is_broken_python_mcp_config(current):
        return "unchanged"

    valid_repair, reason = validate_codex_repair_config(config)
    if not valid_repair:
        expected = (
            "Expected a source stdio command with the MCP server .py path, "
            "or a packaged FixOnce executable that owns --mcp."
        )
        actual = current or {"command": config.get("command"), "args": config.get("args")}
        raise ValueError(
            f"Cannot repair Codex MCP config. Wrong: {actual!r}. {expected} "
            f"Automatic repair failed because {reason}."
        )

    existing = remove_codex_server_blocks(existing, server_name)

    lines = [
        f"[mcp_servers.{server_name}]",
        f"command = {toml_quote(config['command'])}",
        f"args = [{', '.join(toml_quote(arg) for arg in config.get('args', []))}]",
    ]
    if "startup_timeout_sec" in config:
        lines.append(f"startup_timeout_sec = {int(config['startup_timeout_sec'])}")

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
    return "created" if current is None else "repaired"


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
