#!/usr/bin/env python3
"""
Smoke-test a configured MCP server for a specific AI client.

This script loads the MCP config the same way the editor would, launches the
configured stdio command, performs a minimal MCP initialize flow, then asks for
the available tools.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import time
import threading
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_toml(path: Path) -> dict:
    if not path.exists() or tomllib is None:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def resolve_config(client: str) -> tuple[dict | None, str | None]:
    home = Path.home()

    if client == "codex":
        project = PROJECT_ROOT / ".codex" / "config.toml"
        global_path = home / ".codex" / "config.toml"
        for path, scope in ((project, "project"), (global_path, "global")):
            data = _load_toml(path)
            server = data.get("mcp_servers", {}).get("fixonce")
            if server:
                return server, scope
        return None, None

    if client == "cursor":
        project = PROJECT_ROOT / ".mcp.json"
        global_path = home / ".cursor" / "mcp.json"
        for path, scope in ((project, "project"), (global_path, "global")):
            data = _load_json(path)
            server = data.get("mcpServers", {}).get("fixonce")
            if server:
                return server, scope
        return None, None

    if client == "claude":
        candidates = [
            (home / ".claude.json", "global"),
            (home / ".claude" / "settings.json", "global"),
        ]
        for path, scope in candidates:
            data = _load_json(path)
            server = data.get("mcpServers", {}).get("fixonce")
            if server:
                return server, scope
        return None, None

    raise ValueError(f"Unsupported client: {client}")


def encode_message(payload: dict) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


class StreamBuffer:
    """Read subprocess stdout asynchronously with timeout-friendly access."""

    def __init__(self, stream):
        self._stream = stream
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        while True:
            chunk = self._stream.readline()
            if not chunk:
                self._queue.put(None)
                return
            self._queue.put(chunk)

    def read_line(self, timeout: float) -> bytes:
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for MCP response")
            try:
                item = self._queue.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("Timed out waiting for MCP response")
            if item is None:
                raise RuntimeError("MCP server closed stdout before responding")
            return item


def read_message(buffer: StreamBuffer, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = buffer.read_line(max(0.1, deadline - time.time()))
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    raise TimeoutError("Timed out waiting for MCP JSON response")


def request(proc: subprocess.Popen, payload: dict) -> dict:
    if not hasattr(proc, "_mcp_buffer"):
        proc._mcp_buffer = StreamBuffer(proc.stdout)
    proc.stdin.write(encode_message(payload))
    proc.stdin.flush()
    while True:
        message = read_message(proc._mcp_buffer)
        if message.get("id") == payload.get("id"):
            return message


def doctor_for_failure(code: str, detail: str = "") -> dict:
    mapping = {
        "config_missing": {
            "title": "FixOnce is not configured",
            "steps": [
                "Run `python3 scripts/install.py` or `bash setup.sh` from the FixOnce project.",
                "Verify the target AI has a `fixonce` entry in its MCP config.",
            ],
        },
        "command_missing": {
            "title": "Configured command is missing",
            "steps": [
                "Re-run the installer so the config points to the current Python or FastMCP path.",
                "Confirm the configured command exists on disk and is executable.",
            ],
        },
        "server_missing": {
            "title": "MCP server file is missing",
            "steps": [
                "Check that `src/mcp_server/mcp_memory_server_v2.py` still exists.",
                "Reinstall or repair the FixOnce checkout if the file was moved or deleted.",
            ],
        },
        "launch_failed": {
            "title": "FixOnce server did not start",
            "steps": [
                "Inspect stderr from the smoke test for import or dependency failures.",
                "Run `python3 scripts/install.py` to reinstall dependencies.",
            ],
        },
        "handshake_failed": {
            "title": "MCP handshake failed",
            "steps": [
                "The editor can see the config, but the server did not complete initialize/tools/list.",
                "Check Python dependencies and whether FastMCP is installed correctly.",
            ],
        },
        "timeout": {
            "title": "FixOnce did not respond in time",
            "steps": [
                "The server process launched but did not answer MCP requests quickly enough.",
                "Check for startup errors in stderr and verify the configured Python environment.",
            ],
        },
    }
    doctor = mapping.get(code, {
        "title": "Smoke test failed",
        "steps": ["Inspect the returned error details and rerun the installer if needed."],
    })
    return {
        "title": doctor["title"],
        "summary": detail or doctor["title"],
        "steps": doctor["steps"],
    }


def run_smoke_test(client: str) -> dict:
    config, scope = resolve_config(client)
    if not config:
        return {
            "ok": False,
            "code": "config_missing",
            "client": client,
            "doctor": doctor_for_failure("config_missing"),
        }

    command = config.get("command")
    args = config.get("args", [])
    env = dict(os.environ)
    env.update(config.get("env", {}))

    if not command:
        return {
            "ok": False,
            "code": "command_missing",
            "client": client,
            "doctor": doctor_for_failure("command_missing", "The MCP command is empty."),
        }

    command_path = Path(command)
    if command_path.is_absolute() and not command_path.exists():
        return {
            "ok": False,
            "code": "command_missing",
            "client": client,
            "doctor": doctor_for_failure("command_missing", f"Configured command not found: {command}"),
        }

    if args:
        server_path = Path(args[0])
        if server_path.is_absolute() and not server_path.exists():
            return {
                "ok": False,
                "code": "server_missing",
                "client": client,
                "doctor": doctor_for_failure("server_missing", f"Configured server not found: {args[0]}"),
            }

    proc = None
    result = None
    try:
        proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(PROJECT_ROOT),
        )

        init_response = request(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": f"fixonce-smoke-{client}", "version": "1.0"},
            },
        })

        if "error" in init_response:
            detail = init_response["error"].get("message", "initialize failed")
            result = {
                "ok": False,
                "code": "handshake_failed",
                "client": client,
                "scope": scope,
                "doctor": doctor_for_failure("handshake_failed", detail),
            }
            return result

        proc.stdin.write(encode_message({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }))
        proc.stdin.flush()

        tools_response = request(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })

        if "error" in tools_response:
            detail = tools_response["error"].get("message", "tools/list failed")
            result = {
                "ok": False,
                "code": "handshake_failed",
                "client": client,
                "scope": scope,
                "doctor": doctor_for_failure("handshake_failed", detail),
            }
            return result

        tools = tools_response.get("result", {}).get("tools", [])
        result = {
            "ok": True,
            "client": client,
            "scope": scope,
            "tool_count": len(tools),
            "tools_preview": [tool.get("name") for tool in tools[:8]],
        }
        return result

    except TimeoutError as exc:
        result = {
            "ok": False,
            "code": "timeout",
            "client": client,
            "scope": scope,
            "doctor": doctor_for_failure("timeout", str(exc)),
        }
        return result
    except FileNotFoundError as exc:
        result = {
            "ok": False,
            "code": "command_missing",
            "client": client,
            "scope": scope,
            "doctor": doctor_for_failure("command_missing", str(exc)),
        }
        return result
    except Exception as exc:
        result = {
            "ok": False,
            "code": "launch_failed",
            "client": client,
            "scope": scope,
            "doctor": doctor_for_failure("launch_failed", str(exc)),
        }
        return result
    finally:
        if proc:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=2)
            stderr_tail = proc.stderr.read().decode("utf-8", errors="replace")[-1200:].strip()
            if result is not None and stderr_tail:
                result["stderr_tail"] = stderr_tail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True, choices=["codex", "claude", "cursor"])
    args = parser.parse_args()
    result = run_smoke_test(args.client)
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
