#!/usr/bin/env python3
"""
Static audit for Windows subprocess console risks.

This is a developer QA check, not product behavior. It scans Python source for
risky subprocess patterns and reports whether calls use the shared no-window
helpers before Windows runtime changes are installed.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = PROJECT_ROOT / ".fixonce" / "runtime_qa" / "windows_runtime_audit.json"
SCAN_DIRS = ("src", "scripts")
RISK_TERMS = ("git", "powershell", "schtasks", "cmd.exe")
RISK_PATTERNS = (
    "subprocess.run",
    "subprocess.Popen",
    "os.system",
    "git",
    "powershell",
    "schtasks",
    "cmd.exe",
)
CUSTOMER_RUNTIME_PREFIXES = ("src/",)
CUSTOMER_RUNTIME_FILES = {"scripts/app_launcher.py"}
SKIP_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
    "installer",
    "FixOnce.app",
}


@dataclass
class Finding:
    path: str
    line: int
    pattern: str
    command: str
    uses_no_window: bool
    risk_terms: list[str]
    likely_visible_console_risk: bool
    customer_runtime: bool
    high_customer_runtime_risk: bool
    detail: str


def iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirname in SCAN_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            files.append(path)
    return sorted(files)


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def command_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        value = ast.literal_eval(node)
    except Exception:
        return ast.unparse(node) if hasattr(ast, "unparse") else type(node).__name__
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value)
    return str(value)


def contains_no_window(node: ast.AST) -> bool:
    text = ast.unparse(node) if hasattr(ast, "unparse") else ""
    return "no_window_creationflags" in text or "no_window_kwargs" in text


def call_uses_no_window(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg == "creationflags" and contains_no_window(keyword.value):
            return True
        if keyword.arg is None and contains_no_window(keyword.value):
            return True
    return False


def extract_risk_terms(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in RISK_TERMS if term in lowered]


def audit_file(path: Path, root: Path) -> list[Finding]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="replace")

    relpath = path.relative_to(root).as_posix()
    customer_runtime = relpath.startswith(CUSTOMER_RUNTIME_PREFIXES) or relpath in CUSTOMER_RUNTIME_FILES
    findings: list[Finding] = []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        findings.append(
            Finding(
                path=relpath,
                line=exc.lineno or 1,
                pattern="syntax",
                command="",
                uses_no_window=False,
                risk_terms=[],
                likely_visible_console_risk=False,
                customer_runtime=customer_runtime,
                high_customer_runtime_risk=False,
                detail=f"Could not parse file: {exc}",
            )
        )
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = dotted_name(node.func)
        if func not in {"subprocess.run", "subprocess.Popen", "os.system"}:
            continue

        command = command_text(node.args[0] if node.args else None)
        risk_terms = extract_risk_terms(command)
        uses_no_window = call_uses_no_window(node)
        is_windows_command = bool(risk_terms)
        is_console_spawn = func in {"subprocess.run", "subprocess.Popen", "os.system"}
        likely_risk = is_console_spawn and is_windows_command and not uses_no_window
        if func == "os.system":
            likely_risk = True

        findings.append(
            Finding(
                path=relpath,
                line=getattr(node, "lineno", 1),
                pattern=func,
                command=command,
                uses_no_window=uses_no_window,
                risk_terms=risk_terms,
                likely_visible_console_risk=likely_risk,
                customer_runtime=customer_runtime,
                high_customer_runtime_risk=likely_risk and customer_runtime,
                detail=(
                    "uses no-window helper"
                    if uses_no_window
                    else "missing no_window_creationflags/no_window_kwargs"
                ),
            )
        )

    for lineno, line in enumerate(source.splitlines(), start=1):
        lowered = line.lower()
        for term in RISK_PATTERNS:
            if term in lowered:
                if any(f.line == lineno and f.pattern == term for f in findings):
                    continue
                if term in {"subprocess.run", "subprocess.Popen", "os.system"}:
                    continue
                if re.search(r"\b(subprocess\.run|subprocess\.Popen|os\.system)\b", line):
                    continue
                findings.append(
                    Finding(
                        path=relpath,
                        line=lineno,
                        pattern=term,
                        command=line.strip()[:240],
                        uses_no_window="no_window_creationflags" in line or "no_window_kwargs" in line,
                        risk_terms=[term],
                        likely_visible_console_risk=False,
                        customer_runtime=customer_runtime,
                        high_customer_runtime_risk=False,
                        detail="text reference only",
                    )
                )

    return findings


def run_audit(root: Path) -> dict[str, Any]:
    findings: list[Finding] = []
    for path in iter_python_files(root):
        findings.extend(audit_file(path, root))

    risky = [finding for finding in findings if finding.likely_visible_console_risk]
    customer_risky = [finding for finding in findings if finding.high_customer_runtime_risk]
    by_pattern: dict[str, int] = {}
    for finding in findings:
        by_pattern[finding.pattern] = by_pattern.get(finding.pattern, 0) + 1

    return {
        "ok": not customer_risky,
        "project_root": str(root),
        "scanned_dirs": list(SCAN_DIRS),
        "patterns": list(RISK_PATTERNS),
        "finding_count": len(findings),
        "likely_visible_console_risk_count": len(risky),
        "customer_runtime_high_risk_count": len(customer_risky),
        "counts_by_pattern": by_pattern,
        "findings": [asdict(finding) for finding in findings],
        "risky_findings": [asdict(finding) for finding in risky],
        "customer_runtime_high_risks": [asdict(finding) for finding in customer_risky],
    }


def write_report(report: Path, payload: dict[str, Any]) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report = Path(args.report).resolve()
    payload = run_audit(root)
    write_report(report, payload)

    if args.json:
        print(json.dumps(payload))
    else:
        print(f"Audit report: {report}")
        print(f"Patterns scanned: {', '.join(RISK_PATTERNS)}")
        print(f"Findings: {payload['finding_count']}")
        print(f"Likely visible-console risks: {payload['likely_visible_console_risk_count']}")
        print(f"Customer-runtime high risks: {payload['customer_runtime_high_risk_count']}")
        for finding in payload["risky_findings"][:20]:
            print(
                "RISK "
                f"{finding['path']}:{finding['line']} "
                f"{finding['pattern']} "
                f"terms={','.join(finding['risk_terms']) or '-'} "
                f"no_window={finding['uses_no_window']}"
            )
        if len(payload["risky_findings"]) > 20:
            print(f"... {len(payload['risky_findings']) - 20} more risks in report")

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
