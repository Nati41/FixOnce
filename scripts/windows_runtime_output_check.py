#!/usr/bin/env python3
"""
Validate Windows-safe runtime diagnostics.

Request-time Flask/API code must not write Unicode to stdout. Windows
PowerShell may run under a legacy code page and raise UnicodeEncodeError.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_FILES = [PROJECT_ROOT / "src" / "server.py", *sorted((PROJECT_ROOT / "src" / "api").glob("*.py"))]
LOG_CALL_NAMES = {"print", "debug", "info", "warning", "error", "exception", "critical", "log_runtime_event"}


def call_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def string_parts(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                yield value.value


def has_non_ascii(text: str) -> bool:
    return any(ord(char) > 127 for char in text)


def check_file(path: Path) -> list[str]:
    issues: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    is_api_file = path.parent.name == "api"

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        name = call_name(node.func)
        if name is None:
            continue

        if is_api_file and name == "print":
            issues.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: print() is not allowed in Flask API runtime")

        if name not in LOG_CALL_NAMES:
            continue

        for arg in [*node.args, *[keyword.value for keyword in node.keywords]]:
            for text in string_parts(arg):
                if has_non_ascii(text):
                    issues.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: non-ASCII string in {name}()"
                    )

    return issues


def main() -> int:
    issues: list[str] = []
    for path in RUNTIME_FILES:
        issues.extend(check_file(path))

    if issues:
        print("Windows runtime output check failed:")
        for issue in issues:
            print(f"  {issue}")
        return 1

    print("Windows runtime output check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
