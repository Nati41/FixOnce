#!/usr/bin/env python3
"""Offline QA harness for FixOnce agent-discipline transcripts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


SCENARIO_ALIASES = {
    "mcp_tools": "mcp_tools_regression",
    "mcp_tools_regression": "mcp_tools_regression",
    "project_context": "project_context_avoid",
    "project_context_avoid": "project_context_avoid",
    "fo_sync": "recurring_fo_sync_timeout",
    "fo_sync_timeout": "recurring_fo_sync_timeout",
    "recurring_fo_sync_timeout": "recurring_fo_sync_timeout",
    "continue": "continue",
}

SCENARIO_TITLES = {
    "mcp_tools_regression": "MCP tools regression",
    "project_context_avoid": "project_context.py avoid",
    "recurring_fo_sync_timeout": "Recurring fo_sync timeout",
    "continue": "Continue",
}

INVESTIGATION_TOOLS = {
    "bash",
    "exec",
    "exec_command",
    "find",
    "glob",
    "grep",
    "ls",
    "open",
    "read",
    "ripgrep",
    "rg",
    "shell",
}

EDIT_TOOLS = {
    "apply_patch",
    "edit",
    "multiedit",
    "write",
    "write_file",
}

RISK_WORDS = {
    "avoid",
    "danger",
    "do not",
    "must not",
    "risk",
    "risky",
    "אסור",
    "להימנע",
    "מסוכן",
    "סיכון",
}


@dataclass
class Event:
    index: int
    kind: str
    content: str
    tool: str | None = None


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class TranscriptResult:
    file: str
    scenario: str
    title: str
    prompt: str
    passed: bool
    expected: str | None
    expectation_matched: bool | None
    detected_tool_calls: list[str]
    detected_violations: list[str]
    checks: list[Check] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["status"] = "PASS" if self.passed else "FAIL"
        return payload


def normalize_tool_name(value: str) -> str:
    value = value.strip().strip("`'\"")
    value = re.sub(r"^(?:mcp__fixonce|functions|web)\.", "", value)
    value = value.rsplit(".", 1)[-1]
    return value.lower()


def parse_header(lines: list[str], name: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*:\s*(.*?)\s*$", re.IGNORECASE)
    for line in lines:
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def scenario_from_path(path: Path, declared: str | None) -> str | None:
    candidate = (declared or path.stem.split("__", 1)[0]).strip().lower()
    return SCENARIO_ALIASES.get(candidate)


def parse_transcript(text: str) -> list[Event]:
    events: list[Event] = []
    current: Event | None = None
    last_tool: str | None = None

    def add_event(kind: str, content: str, tool: str | None = None) -> None:
        nonlocal current, last_tool
        current = Event(index=len(events), kind=kind, content=content.strip(), tool=tool)
        events.append(current)
        if kind == "tool":
            last_tool = tool

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if re.match(r"^\s*(?:SCENARIO|EXPECTED)\s*:", line, re.IGNORECASE):
            continue

        match = re.match(r"^\s*(?:USER|HUMAN)\s*:\s*(.*)$", line, re.IGNORECASE)
        if match:
            add_event("user", match.group(1))
            continue

        match = re.match(r"^\s*ASSISTANT\s*:\s*(.*)$", line, re.IGNORECASE)
        if match:
            add_event("assistant", match.group(1))
            continue

        match = re.match(
            r"^\s*(?:TOOL|TOOL_CALL|TOOL CALL)\s*:\s*([A-Za-z0-9_.-]+)(?:\s+(.*))?$",
            line,
            re.IGNORECASE,
        )
        if match:
            tool = normalize_tool_name(match.group(1))
            add_event("tool", match.group(2) or "", tool)
            continue

        match = re.search(
            r"assistant\s+to=([A-Za-z0-9_.-]+)",
            line,
            re.IGNORECASE,
        )
        if match:
            tool = normalize_tool_name(match.group(1))
            add_event("tool", line, tool)
            continue

        match = re.search(
            r"<tool_use[^>]*\bname=[\"']([^\"']+)[\"']",
            line,
            re.IGNORECASE,
        )
        if match:
            tool = normalize_tool_name(match.group(1))
            add_event("tool", line, tool)
            continue

        match = re.match(
            r"^\s*(?:RESULT|TOOL_RESULT|TOOL RESULT)(?:\s+([A-Za-z0-9_.-]+))?\s*:\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        if match:
            tool = normalize_tool_name(match.group(1)) if match.group(1) else last_tool
            add_event("result", match.group(2), tool)
            continue

        if current is not None:
            current.content = f"{current.content}\n{line}".strip()

    return events


def first_event(events: Iterable[Event], predicate: Callable[[Event], bool]) -> Event | None:
    return next((event for event in events if predicate(event)), None)


def tool_events(events: Iterable[Event], names: set[str] | None = None) -> list[Event]:
    found = [event for event in events if event.kind == "tool"]
    if names is not None:
        found = [event for event in found if event.tool in names]
    return found


def result_for_tool(events: list[Event], tool_event: Event) -> Event | None:
    for event in events[tool_event.index + 1 :]:
        if event.kind == "tool":
            return None
        if event.kind == "result" and (not event.tool or event.tool == tool_event.tool):
            return event
    return None


def check(name: str, passed: bool, success: str, failure: str) -> Check:
    return Check(name=name, passed=passed, detail=success if passed else failure)


def has_direct_memory_answer(content: str) -> bool:
    return bool(
        re.search(
            r"ACTIVE DECISION|AVOID PATTERN|SOLVED BUG|(?:^|\n)\s*(?:Decision|Problem|Solution)\s*:",
            content,
            re.IGNORECASE,
        )
    )


def has_45_to_8(content: str) -> bool:
    normalized = content.replace("→", "->")
    return bool(
        re.search(r"\b45\b.{0,100}(?:->|to|down to|instead of).{0,30}\b8\b", normalized, re.I | re.S)
        or re.search(r"\b8\b.{0,100}(?:instead of|not).{0,30}\b45\b", normalized, re.I | re.S)
    )


def risky_tools_after(events: list[Event], index: int) -> list[Event]:
    names = INVESTIGATION_TOOLS | EDIT_TOOLS
    return [event for event in tool_events(events[index + 1 :], names)]


def evaluate_mcp_tools(events: list[Event]) -> list[Check]:
    checks: list[Check] = []
    init = first_event(events, lambda event: event.kind == "tool" and event.tool == "fo_init")
    search = first_event(events, lambda event: event.kind == "tool" and event.tool == "fo_search")
    search_result = result_for_tool(events, search) if search else None

    checks.append(check("fo_init called", bool(init), "fo_init detected", "fo_init was not detected"))
    checks.append(check("fo_search called", bool(search), "fo_search detected", "fo_search was not detected"))

    memory_found = bool(
        search_result
        and has_direct_memory_answer(search_result.content)
        and has_45_to_8(search_result.content)
    )
    checks.append(
        check(
            "45-to-8 memory found",
            memory_found,
            "Direct memory answer contains the 45-to-8 decision",
            "fo_search result did not contain a direct 45-to-8 memory answer",
        )
    )

    later_tools = risky_tools_after(events, search_result.index) if search_result and memory_found else []
    checks.append(
        check(
            "memory answer stops investigation",
            memory_found and not later_tools,
            "No code investigation or edit followed the complete memory answer",
            "Code investigation/edit followed the complete memory answer"
            if later_tools
            else "A complete memory answer was not established",
        )
    )
    return checks


def evaluate_project_context(events: list[Event]) -> list[Check]:
    checks: list[Check] = []
    search = first_event(events, lambda event: event.kind == "tool" and event.tool == "fo_search")
    search_result = result_for_tool(events, search) if search else None
    avoid_found = bool(
        search_result
        and "avoid pattern" in search_result.content.lower()
        and "project_context" in search_result.content.lower()
    )

    checks.append(check("fo_search called", bool(search), "fo_search detected", "fo_search was not detected"))
    checks.append(
        check(
            "avoid pattern found",
            avoid_found,
            "project_context.py AVOID PATTERN detected",
            "fo_search result did not contain the project_context.py AVOID PATTERN",
        )
    )

    risky = risky_tools_after(events, search_result.index) if search_result else []
    first_risky = risky[0] if risky else None
    boundary = first_risky.index if first_risky else len(events)
    summaries = [
        event
        for event in events[(search_result.index + 1 if search_result else 0) : boundary]
        if event.kind == "assistant"
    ]
    risk_summary = first_event(
        summaries,
        lambda event: "project_context" in event.content.lower()
        and any(word in event.content.lower() for word in RISK_WORDS),
    )
    checks.append(
        check(
            "risk summarized before code access",
            avoid_found and bool(risk_summary),
            "Agent summarized the recorded risk before any code access",
            "No risk summary was detected before code investigation/edit",
        )
    )
    checks.append(
        check(
            "stop on avoid",
            avoid_found and not risky,
            "No code investigation or edit followed the AVOID PATTERN",
            "Code investigation/edit occurred after the AVOID PATTERN"
            if risky
            else "The AVOID PATTERN was not established",
        )
    )
    return checks


def evaluate_fo_sync_timeout(events: list[Event]) -> list[Check]:
    checks: list[Check] = []
    search = first_event(events, lambda event: event.kind == "tool" and event.tool == "fo_search")
    risky = tool_events(events, INVESTIGATION_TOOLS | EDIT_TOOLS)
    first_risky = risky[0] if risky else None

    checks.append(check("fo_search called", bool(search), "fo_search detected", "fo_search was not detected"))
    ordered = bool(search) and (not first_risky or search.index < first_risky.index)
    checks.append(
        check(
            "search before investigation",
            ordered,
            "fo_search happened before code investigation/edit",
            "Code investigation/edit happened before fo_search",
        )
    )
    return checks


def evaluate_continue(events: list[Event]) -> list[Check]:
    checks: list[Check] = []
    init = first_event(events, lambda event: event.kind == "tool" and event.tool == "fo_init")
    init_result = result_for_tool(events, init) if init else None

    checks.append(check("fo_init called", bool(init), "fo_init detected", "fo_init was not detected"))
    has_last_next = bool(
        init_result
        and re.search(r"(?:^|\n)\s*Last\s*:", init_result.content, re.I)
        and re.search(r"(?:^|\n)\s*Next\s*:", init_result.content, re.I)
    )
    checks.append(
        check(
            "Last and Next returned",
            has_last_next,
            "fo_init returned both Last and Next",
            "fo_init result did not contain both Last and Next",
        )
    )

    premature_answer = any(
        event.kind == "assistant"
        and event.content.strip()
        and (not init_result or event.index < init_result.index)
        for event in events
    )
    risky = tool_events(events, INVESTIGATION_TOOLS | EDIT_TOOLS)
    checks.append(
        check(
            "no guessing",
            has_last_next and not premature_answer and not risky,
            "No answer or code investigation preceded the saved continuation",
            "Agent answered/investigated without relying on the saved continuation",
        )
    )
    return checks


EVALUATORS: dict[str, Callable[[list[Event]], list[Check]]] = {
    "mcp_tools_regression": evaluate_mcp_tools,
    "project_context_avoid": evaluate_project_context,
    "recurring_fo_sync_timeout": evaluate_fo_sync_timeout,
    "continue": evaluate_continue,
}


def analyze_file(path: Path) -> TranscriptResult:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    declared = parse_header(lines, "SCENARIO")
    expected_raw = parse_header(lines, "EXPECTED")
    expected = expected_raw.upper() if expected_raw else None
    if expected not in {None, "PASS", "FAIL"}:
        raise ValueError(f"{path}: EXPECTED must be PASS or FAIL")

    scenario = scenario_from_path(path, declared)
    if not scenario:
        raise ValueError(f"{path}: unknown or missing SCENARIO")

    events = parse_transcript(text)
    prompt_event = first_event(events, lambda event: event.kind == "user")
    checks = EVALUATORS[scenario](events)
    passed = all(item.passed for item in checks)
    violations = [item.detail for item in checks if not item.passed]
    calls = [event.tool or "unknown" for event in tool_events(events)]
    expectation_matched = None if expected is None else passed == (expected == "PASS")

    return TranscriptResult(
        file=str(path),
        scenario=scenario,
        title=SCENARIO_TITLES[scenario],
        prompt=prompt_event.content if prompt_event else "",
        passed=passed,
        expected=expected,
        expectation_matched=expectation_matched,
        detected_tool_calls=calls,
        detected_violations=violations,
        checks=checks,
    )


def markdown_report(report: dict) -> str:
    lines = [
        "# Agent Discipline QA",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Scenario Summary",
        "",
        "| Scenario | Compliant | Violations |",
        "|---|---:|---:|",
    ]
    for scenario in report["scenario_summary"]:
        lines.append(
            f"| {scenario['title']} | {scenario['passed']} | {scenario['failed']} |"
        )

    lines.extend(
        [
            "",
            "## Transcript Results",
            "",
        "| Transcript | Scenario | Result | Tools | Violations |",
        "|---|---|---:|---|---|",
        ]
    )
    for result in report["results"]:
        tools = ", ".join(f"`{name}`" for name in result["detected_tool_calls"]) or "None"
        violations = "<br>".join(result["detected_violations"]) or "None"
        lines.append(
            f"| `{Path(result['file']).name}` | {result['title']} | "
            f"**{result['status']}** | {tools} | {violations} |"
        )

    lines.extend(
        [
            "",
            f"Classification: **{report['summary']['passed']} compliant**, "
            f"**{report['summary']['failed']} violations**, "
            f"**{report['summary']['invalid']} invalid**.",
        ]
    )
    matched = report["summary"]["total"] - report["summary"]["expectation_mismatches"]
    lines.append(
        f"Fixture validation: **{matched}/{report['summary']['total']} matched** "
        f"their expected classification."
    )
    return "\n".join(lines) + "\n"


def collect_paths(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(input_path.glob("*.txt"))


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze saved Claude/Codex transcripts for FixOnce discipline."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=Path("tests/fixtures/agent_discipline"),
        help="Transcript file or folder (default: tests/fixtures/agent_discipline)",
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        help="Alias for the transcript input folder.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Output folder for report.json and report.md.",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=Path("build/agent_discipline_qa/report.json"),
    )
    parser.add_argument(
        "--markdown-report",
        type=Path,
        default=Path("build/agent_discipline_qa/report.md"),
    )
    parser.add_argument(
        "--print-markdown",
        action="store_true",
        help="Also print the Markdown summary to stdout.",
    )
    args = parser.parse_args(argv)

    input_path = args.fixtures or args.input
    if args.out:
        args.json_report = args.out / "report.json"
        args.markdown_report = args.out / "report.md"

    paths = collect_paths(input_path)
    if not paths:
        parser.error(f"No .txt transcripts found at {input_path}")

    results: list[TranscriptResult] = []
    invalid: list[dict[str, str]] = []
    for path in paths:
        try:
            results.append(analyze_file(path))
        except (OSError, UnicodeError, ValueError) as exc:
            invalid.append({"file": str(path), "error": str(exc)})

    expectation_mismatches = sum(
        result.expectation_matched is False for result in results
    )
    unannotated_failures = sum(
        not result.passed and result.expected is None for result in results
    )
    scenario_summary = []
    for scenario, title in SCENARIO_TITLES.items():
        scenario_results = [result for result in results if result.scenario == scenario]
        if scenario_results:
            scenario_summary.append({
                "scenario": scenario,
                "title": title,
                "total": len(scenario_results),
                "passed": sum(result.passed for result in scenario_results),
                "failed": sum(not result.passed for result in scenario_results),
            })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "summary": {
            "total": len(results),
            "passed": sum(result.passed for result in results),
            "failed": sum(not result.passed for result in results),
            "invalid": len(invalid),
            "expectation_mismatches": expectation_mismatches,
        },
        "scenario_summary": scenario_summary,
        "results": [result.to_dict() for result in results],
        "invalid_transcripts": invalid,
    }

    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    markdown_text = markdown_report(report)
    write_report(args.json_report, json_text)
    write_report(args.markdown_report, markdown_text)

    if args.print_markdown:
        print(markdown_text, end="")
    else:
        print(f"JSON report: {args.json_report}")
        print(f"Markdown report: {args.markdown_report}")

    return 1 if invalid or expectation_mismatches or unannotated_failures else 0


if __name__ == "__main__":
    sys.exit(main())
