#!/usr/bin/env python3
"""
Developer QA harness for the local Windows FixOnce runtime.

The harness does not build an installer and does not require Codex. It launches
the current source runtime over MCP stdio, performs real tool calls, and writes
logs for every stage with strict timeouts.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
APP_LAUNCHER = PROJECT_ROOT / "scripts" / "app_launcher.py"
LOG_ROOT = PROJECT_ROOT / ".fixonce" / "runtime_qa"
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
TEST_CWD = Path(r"C:\TestProject")


@dataclass
class StageResult:
    name: str
    ok: bool
    elapsed_ms: int
    log_path: str
    detail: str = ""
    error: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class StageFailure(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class StageLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def write(self, message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")


def no_window_creationflags() -> int:
    if sys.platform != "win32":
        return 0
    return (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )


def run_stage(
    name: str,
    timeout: float,
    func: Callable[[StageLogger], dict[str, Any] | None],
) -> StageResult:
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.lower())
    log = StageLogger(LOG_ROOT / f"{safe_name}.log")
    started = time.perf_counter()
    result_queue: queue.Queue[tuple[bool, dict[str, Any] | None, BaseException | None]] = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            result_queue.put((True, func(log) or {}, None))
        except BaseException as exc:
            result_queue.put((False, None, exc))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if thread.is_alive():
        log.write(f"TIMEOUT after {timeout:.1f}s")
        return StageResult(name, False, elapsed_ms, str(log.path), error=f"timeout after {timeout:.1f}s")

    ok, data, exc = result_queue.get()
    if ok:
        detail = (data or {}).pop("detail", "ok")
        log.write(f"PASS elapsed_ms={elapsed_ms} detail={detail}")
        return StageResult(name, True, elapsed_ms, str(log.path), detail=detail, data=data or {})

    error = exc.detail if isinstance(exc, StageFailure) else f"{type(exc).__name__}: {exc}"
    log.write(f"FAIL elapsed_ms={elapsed_ms} error={error}")
    return StageResult(name, False, elapsed_ms, str(log.path), error=error)


def load_codex_config() -> dict[str, Any]:
    if not CODEX_CONFIG.exists():
        raise StageFailure(f"Codex config not found: {CODEX_CONFIG}")
    if tomllib is None:
        raise StageFailure("tomllib is unavailable; use Python 3.11+ for TOML parsing")
    try:
        with CODEX_CONFIG.open("rb") as handle:
            return tomllib.load(handle)
    except Exception as exc:
        raise StageFailure(f"Could not parse Codex config {CODEX_CONFIG}: {exc}")


def stage_codex_config(log: StageLogger) -> dict[str, Any]:
    config = load_codex_config()
    server = config.get("mcp_servers", {}).get("fixonce")
    if not isinstance(server, dict):
        raise StageFailure("Missing [mcp_servers.fixonce] in current user Codex config")

    command = server.get("command")
    args = server.get("args")
    env = server.get("env", {})
    log.write(f"config_path={CODEX_CONFIG}")
    log.write(f"command={command!r}")
    log.write(f"args={args!r}")
    log.write(f"env={env!r}")

    errors: list[str] = []
    if not command:
        errors.append("Codex fixonce command is empty")
    command_path = Path(str(command))
    resolved_command = command_path if command_path.is_absolute() else None
    if resolved_command is not None and not resolved_command.exists():
        errors.append(f"Codex command does not exist: {resolved_command}")
    if args != ["--mcp"]:
        errors.append(f"Codex args must be ['--mcp'], got {args!r}")
    if env.get("FIXONCE_ACTOR") != "codex":
        errors.append(f"FIXONCE_ACTOR must be 'codex', got {env.get('FIXONCE_ACTOR')!r}")

    command_lower = str(command).lower()
    project_lower = str(PROJECT_ROOT).lower()
    command_name = Path(str(command)).name.lower()
    if command_name in {"python.exe", "pythonw.exe", "py.exe", "fastmcp.exe", "python", "pythonw", "py", "fastmcp"}:
        errors.append(f"Codex command points to an interpreter/tool, not a FixOnce runtime: {command}")
    elif resolved_command is not None and project_lower not in command_lower and "fixonce" not in command_lower:
        errors.append(f"Codex command does not look like a FixOnce runtime: {command}")

    if errors:
        for error in errors:
            log.write(f"config_error {error}")
        raise StageFailure("; ".join(errors))

    return {
        "detail": "Codex MCP config has command, args, and FIXONCE_ACTOR",
        "config_path": str(CODEX_CONFIG),
        "command": str(command),
        "args": args,
    }


def stage_local_runtime(log: StageLogger) -> dict[str, Any]:
    if not APP_LAUNCHER.exists():
        raise StageFailure(f"Missing local runtime launcher: {APP_LAUNCHER}")
    if not (SRC_DIR / "mcp_server" / "mcp_memory_server_v2.py").exists():
        raise StageFailure("Missing src/mcp_server/mcp_memory_server_v2.py")
    log.write(f"python={sys.executable}")
    log.write(f"launcher={APP_LAUNCHER}")
    return {"detail": "current source runtime files exist", "command": sys.executable, "args": [str(APP_LAUNCHER), "--mcp"]}


class StreamBuffer:
    def __init__(self, stream: Any, sink: Callable[[str], None]):
        self._stream = stream
        self._sink = sink
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        while True:
            chunk = self._stream.readline()
            if not chunk:
                self._queue.put(None)
                return
            self._sink(chunk.decode("utf-8", errors="replace").rstrip())
            self._queue.put(chunk)

    def read_line(self, timeout: float) -> bytes:
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("timed out waiting for MCP stdout")
        if item is None:
            raise RuntimeError("MCP server closed stdout")
        return item


class McpClient:
    def __init__(self, log: StageLogger):
        self.log = log
        self.proc: subprocess.Popen[bytes] | None = None
        self.stdout: StreamBuffer | None = None
        self.stderr_lines: list[str] = []
        self.next_id = 1

    def start(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC_DIR)
        env["FIXONCE_ACTOR"] = "codex"
        env.setdefault("FASTMCP_SHOW_CLI_BANNER", "false")
        env.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")
        command = [sys.executable, str(APP_LAUNCHER), "--mcp"]
        self.log.write(f"launch={' '.join(command)}")
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
            env=env,
            creationflags=no_window_creationflags(),
        )
        assert self.proc.stdout is not None
        assert self.proc.stderr is not None
        self.stdout = StreamBuffer(self.proc.stdout, lambda line: self.log.write(f"stdout {line}"))
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    def _pump_stderr(self) -> None:
        assert self.proc is not None
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", errors="replace").rstrip()
            self.stderr_lines.append(line)
            self.log.write(f"stderr {line}")

    def read_message(self, timeout: float) -> dict[str, Any]:
        assert self.stdout is not None
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            line = self.stdout.read_line(max(0.1, deadline - time.perf_counter()))
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                continue
            self.log.write(f"recv {json.dumps(message)[:1200]}")
            return message
        raise TimeoutError("timed out waiting for MCP JSON message")

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> dict[str, Any]:
        assert self.proc is not None
        assert self.proc.stdin is not None
        request_id = self.next_id
        self.next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        self.log.write(f"send {json.dumps(payload)}")
        self.proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            message = self.read_message(max(0.1, deadline - time.perf_counter()))
            if message.get("id") == request_id:
                if "error" in message:
                    raise StageFailure(f"{method} error: {message['error']}")
                return message
        raise TimeoutError(f"timed out waiting for response to {method}")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.proc is not None
        assert self.proc.stdin is not None
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self.log.write(f"notify {json.dumps(payload)}")
        self.proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def call_tool(self, name: str, arguments: dict[str, Any], timeout: float) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)

    def close(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
        self.log.write(f"process_returncode={self.proc.poll()}")


def tool_text(response: dict[str, Any]) -> str:
    result = response.get("result", {})
    content = result.get("content", [])
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(parts)


def initialize_mcp_session(client: McpClient, log: StageLogger, require_tools: bool = True) -> list[str]:
    init = client.request(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "fixonce-windows-runtime-qa", "version": "1.0"},
        },
        timeout=12.0,
    )
    log.write(f"initialize_result={json.dumps(init.get('result', {}))[:1200]}")
    client.notify("notifications/initialized")

    tools = client.request("tools/list", {}, timeout=8.0)
    tool_names = [tool.get("name", "") for tool in tools.get("result", {}).get("tools", [])]
    log.write(f"tools={tool_names}")
    if require_tools:
        for required in ("fo_init", "fo_search", "fo_errors"):
            if required not in tool_names:
                raise StageFailure(f"Required tool missing from tools/list: {required}")
    return tool_names


def stage_mcp_startup_ready(log: StageLogger) -> dict[str, Any]:
    client = McpClient(log)
    try:
        client.start()
        tool_names = initialize_mcp_session(client, log)
        return {
            "detail": "MCP initialize and tools/list passed",
            "tool_count": len(tool_names),
        }
    finally:
        client.close()


def stage_fo_init(log: StageLogger) -> dict[str, Any]:
    TEST_CWD.mkdir(parents=True, exist_ok=True)
    client = McpClient(log)
    try:
        client.start()
        initialize_mcp_session(client, log)
        step_started = time.perf_counter()
        init_response = client.call_tool("fo_init", {"cwd": str(TEST_CWD)}, timeout=25.0)
        log.write(f"timing fo_init elapsed_ms={int((time.perf_counter() - step_started) * 1000)}")
        init_text = tool_text(init_response)
        if not init_text.strip():
            raise StageFailure("fo_init returned empty content")
        return {
            "detail": "fo_init returned opener content",
            "fo_init_preview": init_text[:240],
        }
    finally:
        client.close()


def stage_fo_search(log: StageLogger) -> dict[str, Any]:
    TEST_CWD.mkdir(parents=True, exist_ok=True)
    client = McpClient(log)
    try:
        client.start()
        initialize_mcp_session(client, log)
        setup_started = time.perf_counter()
        client.call_tool("fo_init", {"cwd": str(TEST_CWD)}, timeout=25.0)
        log.write(f"timing setup_fo_init elapsed_ms={int((time.perf_counter() - setup_started) * 1000)}")
        step_started = time.perf_counter()
        search_response = client.call_tool("fo_search", {"query": "simple query"}, timeout=15.0)
        log.write(f"timing fo_search elapsed_ms={int((time.perf_counter() - step_started) * 1000)}")
        if "error" in search_response:
            raise StageFailure("fo_search returned an MCP error")
        return {
            "detail": "fo_search completed for query 'simple query'",
            "fo_search_preview": tool_text(search_response)[:240],
        }
    finally:
        client.close()


def stage_fo_errors(log: StageLogger) -> dict[str, Any]:
    TEST_CWD.mkdir(parents=True, exist_ok=True)
    client = McpClient(log)
    try:
        client.start()
        initialize_mcp_session(client, log)
        setup_started = time.perf_counter()
        client.call_tool("fo_init", {"cwd": str(TEST_CWD)}, timeout=25.0)
        log.write(f"timing setup_fo_init elapsed_ms={int((time.perf_counter() - setup_started) * 1000)}")
        step_started = time.perf_counter()
        errors_response = client.call_tool("fo_errors", {}, timeout=12.0)
        log.write(f"timing fo_errors elapsed_ms={int((time.perf_counter() - step_started) * 1000)}")
        if "error" in errors_response:
            raise StageFailure("fo_errors returned an MCP error")
        errors_text = tool_text(errors_response)
        if "session not initialized" in errors_text.lower():
            raise StageFailure("fo_errors returned session initialization enforcement instead of tool output")

        return {
            "detail": "fo_errors completed",
            "fo_errors_preview": errors_text[:240],
        }
    finally:
        client.close()


def stage_static_audit(log: StageLogger) -> dict[str, Any]:
    from windows_runtime_audit import run_audit, write_report

    report = LOG_ROOT / "windows_runtime_audit.json"
    payload = run_audit(PROJECT_ROOT)
    write_report(report, payload)
    log.write(f"audit_report={report}")
    log.write(f"finding_count={payload['finding_count']}")
    log.write(f"likely_visible_console_risk_count={payload['likely_visible_console_risk_count']}")
    log.write(f"customer_runtime_high_risk_count={payload['customer_runtime_high_risk_count']}")
    for finding in payload["risky_findings"][:25]:
        log.write(
            "risk "
            f"{finding['path']}:{finding['line']} "
            f"{finding['pattern']} "
            f"terms={','.join(finding['risk_terms']) or '-'} "
            f"no_window={finding['uses_no_window']} "
            f"customer_runtime={finding['customer_runtime']}"
        )
    if not payload["ok"]:
        raise StageFailure(
            "Static audit found "
            f"{payload['customer_runtime_high_risk_count']} customer-runtime high visible-console risks"
        )
    return {
        "detail": "static subprocess audit passed for customer-runtime high risks",
        "report": str(report),
        "finding_count": payload["finding_count"],
        "likely_visible_console_risk_count": payload["likely_visible_console_risk_count"],
        "customer_runtime_high_risk_count": payload["customer_runtime_high_risk_count"],
    }


def write_summary(results: list[StageResult]) -> Path:
    summary_path = LOG_ROOT / "windows_runtime_qa_summary.json"
    payload = {
        "ok": all(result.ok for result in results),
        "project_root": str(PROJECT_ROOT),
        "results": [result.__dict__ for result in results],
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return summary_path


def print_summary(results: list[StageResult], summary_path: Path) -> None:
    ok = all(result.ok for result in results)
    print("")
    print("Windows runtime QA summary")
    print(f"Result: {'PASS' if ok else 'FAIL'}")
    print(f"Summary log: {summary_path}")
    print("")
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        detail = result.detail if result.ok else result.error
        print(f"{status} {result.name} ({result.elapsed_ms} ms)")
        print(f"  {detail}")
        print(f"  log: {result.log_path}")
    if not ok:
        failed = next(result for result in results if not result.ok)
        print("")
        print(f"Failing stage: {failed.name}")
        print(f"Failing log: {failed.log_path}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-config", action="store_true", help="Skip current-user Codex config verification")
    parser.add_argument("--skip-audit", action="store_true", help="Skip static subprocess audit")
    args = parser.parse_args(argv)

    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    stages: list[tuple[str, float, Callable[[StageLogger], dict[str, Any] | None]]] = []
    if not args.skip_config:
        stages.append(("Codex MCP config", 6.0, stage_codex_config))
    stages.extend(
        [
            ("Current source runtime", 4.0, stage_local_runtime),
            ("MCP startup readiness", 25.0, stage_mcp_startup_ready),
            ("fo_init C:\\TestProject", 35.0, stage_fo_init),
            ("fo_search simple query", 45.0, stage_fo_search),
            ("fo_errors", 25.0, stage_fo_errors),
        ]
    )
    if not args.skip_audit:
        stages.append(("Static Windows subprocess audit", 20.0, stage_static_audit))

    results: list[StageResult] = []
    for name, timeout, func in stages:
        print(f"RUN {name} (timeout {timeout:.0f}s)")
        result = run_stage(name, timeout, func)
        results.append(result)
        print(f"{'PASS' if result.ok else 'FAIL'} {name} ({result.elapsed_ms} ms)")
        if not result.ok:
            break

    summary_path = write_summary(results)
    print_summary(results, summary_path)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
