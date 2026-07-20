#!/usr/bin/env python3
"""
Transcript Extractor - Read-only extraction of conversation transcripts.

Supports:
- Claude Code (JSONL in ~/.claude/projects/)
- Codex (JSONL in ~/.codex/sessions/ + SQLite metadata)

Output: Normalized schema regardless of platform.
"""

import json
import os
import re
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import Optional, List, Dict, Any


@dataclass
class Message:
    role: str  # "user" or "assistant"
    text: str
    timestamp: str


@dataclass
class TranscriptResult:
    platform: str
    session_id: str
    cwd: str
    started_at: str
    last_activity_at: str
    messages: List[Dict[str, str]]
    stats: Dict[str, int]
    errors: List[str]

    def to_dict(self) -> dict:
        return asdict(self)


class ClaudeTranscriptExtractor:
    """Extract transcripts from Claude Code conversations."""

    CLAUDE_DIR = Path.home() / ".claude"
    SESSIONS_DIR = CLAUDE_DIR / "sessions"
    PROJECTS_DIR = CLAUDE_DIR / "projects"

    # Patterns to filter out
    SYSTEM_PATTERNS = [
        r"^<permissions",
        r"^<collaboration_mode",
        r"^<skills_instructions",
        r"^<apps_instructions",
        r"^<plugins_instructions",
        r"^<environment_context",
        r"^<system-reminder",
        r"^\s*$",
    ]

    def __init__(self):
        self._system_re = re.compile("|".join(self.SYSTEM_PATTERNS), re.MULTILINE)

    def find_active_session(self, cwd: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Find active Claude Code session, optionally filtered by cwd."""
        if not self.SESSIONS_DIR.exists():
            return None

        sessions = []
        for session_file in self.SESSIONS_DIR.glob("*.json"):
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                if data.get("status") in ("waiting", "running", "permission prompt"):
                    if cwd is None or data.get("cwd") == cwd:
                        sessions.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        if not sessions:
            return None

        # Sort by most recent activity
        sessions.sort(key=lambda s: s.get("updatedAt", 0), reverse=True)
        return sessions[0]

    def find_sessions_by_cwd(self, cwd: str) -> List[Dict[str, Any]]:
        """Find all sessions for a given project directory."""
        project_key = cwd.replace("/", "-")
        project_dir = self.PROJECTS_DIR / project_key

        if not project_dir.exists():
            return []

        # First, check if there's an active session for this cwd
        active = self.find_active_session(cwd)
        active_id = active.get("sessionId") if active else None

        sessions = []
        for jsonl_file in project_dir.glob("*.jsonl"):
            session_id = jsonl_file.stem
            # Skip orphaned files
            if ".orphaned" in session_id:
                continue

            try:
                # Use file modification time as primary sort key
                mtime = jsonl_file.stat().st_mtime

                # Get first and last line for timestamps
                lines = jsonl_file.read_text(encoding="utf-8").strip().split("\n")
                if lines:
                    first = json.loads(lines[0])
                    last = json.loads(lines[-1])
                    sessions.append({
                        "sessionId": session_id,
                        "cwd": cwd,
                        "path": str(jsonl_file),
                        "started_at": first.get("timestamp", ""),
                        "last_activity": last.get("timestamp", ""),
                        "line_count": len(lines),
                        "mtime": mtime,
                        "is_active": session_id == active_id,
                    })
            except (json.JSONDecodeError, OSError):
                continue

        # Sort: active first, then by modification time
        sessions.sort(key=lambda s: (not s.get("is_active", False), -s.get("mtime", 0)))
        return sessions

    def _is_system_text(self, text) -> bool:
        """Check if text is system/metadata content to filter out."""
        if not text:
            return True
        if not isinstance(text, str):
            return True  # Non-string content (lists, etc.)
        text_stripped = text.strip()
        if text_stripped.startswith("<") and ">" in text_stripped[:100]:
            return True
        return bool(self._system_re.match(text_stripped))

    def extract(
        self,
        session_id: Optional[str] = None,
        cwd: Optional[str] = None,
        include_tool_results: bool = False,
    ) -> TranscriptResult:
        """Extract transcript from Claude Code conversation."""
        errors = []
        stats = {
            "total_lines": 0,
            "user_messages": 0,
            "assistant_messages": 0,
            "filtered_system": 0,
            "filtered_tool_results": 0,
            "parse_errors": 0,
        }

        # Find session
        if session_id:
            # Direct session ID lookup
            if cwd:
                project_key = cwd.replace("/", "-")
            else:
                # Search all projects
                for project_dir in self.PROJECTS_DIR.iterdir():
                    if project_dir.is_dir():
                        candidate = project_dir / f"{session_id}.jsonl"
                        if candidate.exists():
                            cwd = project_dir.name.replace("-", "/")
                            break

            if not cwd:
                return TranscriptResult(
                    platform="claude",
                    session_id=session_id,
                    cwd="",
                    started_at="",
                    last_activity_at="",
                    messages=[],
                    stats=stats,
                    errors=[f"Session {session_id} not found"],
                )

            project_key = cwd.replace("/", "-")
            jsonl_path = self.PROJECTS_DIR / project_key / f"{session_id}.jsonl"
        elif cwd:
            # Find most recent session for cwd
            sessions = self.find_sessions_by_cwd(cwd)
            if not sessions:
                return TranscriptResult(
                    platform="claude",
                    session_id="",
                    cwd=cwd,
                    started_at="",
                    last_activity_at="",
                    messages=[],
                    stats=stats,
                    errors=[f"No sessions found for cwd: {cwd}"],
                )
            if len(sessions) > 1:
                errors.append(f"Found {len(sessions)} sessions for cwd, using most recent")
            session_id = sessions[0]["sessionId"]
            jsonl_path = Path(sessions[0]["path"])
        else:
            # Find active session
            active = self.find_active_session()
            if not active:
                return TranscriptResult(
                    platform="claude",
                    session_id="",
                    cwd="",
                    started_at="",
                    last_activity_at="",
                    messages=[],
                    stats=stats,
                    errors=["No active Claude Code session found"],
                )
            session_id = active["sessionId"]
            cwd = active.get("cwd", "")
            project_key = cwd.replace("/", "-")
            jsonl_path = self.PROJECTS_DIR / project_key / f"{session_id}.jsonl"

        if not jsonl_path.exists():
            return TranscriptResult(
                platform="claude",
                session_id=session_id,
                cwd=cwd,
                started_at="",
                last_activity_at="",
                messages=[],
                stats=stats,
                errors=[f"Transcript file not found: {jsonl_path}"],
            )

        # Parse JSONL
        messages = []
        started_at = ""
        last_activity_at = ""

        try:
            content = jsonl_path.read_text(encoding="utf-8")
        except OSError as e:
            return TranscriptResult(
                platform="claude",
                session_id=session_id,
                cwd=cwd,
                started_at="",
                last_activity_at="",
                messages=[],
                stats=stats,
                errors=[f"Failed to read transcript: {e}"],
            )

        for line in content.strip().split("\n"):
            stats["total_lines"] += 1
            if not line.strip():
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats["parse_errors"] += 1
                continue

            timestamp = obj.get("timestamp", "")
            if timestamp:
                if not started_at:
                    started_at = timestamp
                last_activity_at = timestamp

            msg = obj.get("message", {})
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            content = msg.get("content")

            if role == "user":
                # Check if this is a tool result
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "tool_result":
                                stats["filtered_tool_results"] += 1
                                if include_tool_results:
                                    text = item.get("content", "")
                                    if text and not self._is_system_text(text):
                                        messages.append({
                                            "role": "tool_result",
                                            "text": text[:2000],
                                            "timestamp": timestamp,
                                        })
                                continue
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                if self._is_system_text(text):
                                    stats["filtered_system"] += 1
                                    continue
                                messages.append({
                                    "role": "user",
                                    "text": text,
                                    "timestamp": timestamp,
                                })
                                stats["user_messages"] += 1
                elif isinstance(content, str) and content:
                    if self._is_system_text(content):
                        stats["filtered_system"] += 1
                        continue
                    messages.append({
                        "role": "user",
                        "text": content,
                        "timestamp": timestamp,
                    })
                    stats["user_messages"] += 1

            elif role == "assistant":
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "")
                            if text and not self._is_system_text(text):
                                messages.append({
                                    "role": "assistant",
                                    "text": text,
                                    "timestamp": timestamp,
                                })
                                stats["assistant_messages"] += 1

        return TranscriptResult(
            platform="claude",
            session_id=session_id,
            cwd=cwd,
            started_at=started_at,
            last_activity_at=last_activity_at,
            messages=messages,
            stats=stats,
            errors=errors,
        )


class CodexTranscriptExtractor:
    """Extract transcripts from Codex conversations."""

    CODEX_DIR = Path.home() / ".codex"
    STATE_DB = CODEX_DIR / "state_5.sqlite"
    SESSIONS_DIR = CODEX_DIR / "sessions"

    SYSTEM_PATTERNS = [
        r"^<permissions",
        r"^<collaboration_mode",
        r"^<skills_instructions",
        r"^<apps_instructions",
        r"^<plugins_instructions",
        r"^<environment_context",
        r"^<INSTRUCTIONS",
        r"^# AGENTS\.md",
        r"^\s*$",
    ]

    def __init__(self):
        self._system_re = re.compile("|".join(self.SYSTEM_PATTERNS), re.MULTILINE)

    def _find_rollout_file(self, thread_id: str) -> Optional[Path]:
        """Find rollout file for a thread ID."""
        pattern = str(self.SESSIONS_DIR / "*" / "*" / "*" / f"*{thread_id}*.jsonl")
        files = glob(pattern)
        if files:
            return Path(files[0])
        return None

    def find_threads_by_cwd(self, cwd: str) -> List[Dict[str, Any]]:
        """Find all threads for a given project directory."""
        if not self.STATE_DB.exists():
            return []

        threads = []
        try:
            conn = sqlite3.connect(str(self.STATE_DB))
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, title, cwd, created_at, updated_at
                   FROM threads
                   WHERE cwd = ? AND archived = 0
                   ORDER BY updated_at DESC""",
                (cwd,)
            )
            for row in cursor.fetchall():
                threads.append({
                    "id": row[0],
                    "title": row[1],
                    "cwd": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                })
            conn.close()
        except sqlite3.Error:
            pass

        return threads

    def find_active_thread(self, cwd: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Find most recent active Codex thread."""
        if not self.STATE_DB.exists():
            return None

        try:
            conn = sqlite3.connect(str(self.STATE_DB))
            cursor = conn.cursor()
            if cwd:
                cursor.execute(
                    """SELECT id, title, cwd, created_at, updated_at
                       FROM threads
                       WHERE cwd = ? AND archived = 0
                       ORDER BY updated_at DESC LIMIT 1""",
                    (cwd,)
                )
            else:
                cursor.execute(
                    """SELECT id, title, cwd, created_at, updated_at
                       FROM threads
                       WHERE archived = 0
                       ORDER BY updated_at DESC LIMIT 1"""
                )
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    "id": row[0],
                    "title": row[1],
                    "cwd": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                }
        except sqlite3.Error:
            pass

        return None

    def _is_system_text(self, text) -> bool:
        """Check if text is system/metadata content to filter out."""
        if not text:
            return True
        if not isinstance(text, str):
            return True  # Non-string content (lists, etc.)
        text_stripped = text.strip()
        if text_stripped.startswith("<") and ">" in text_stripped[:100]:
            return True
        return bool(self._system_re.match(text_stripped))

    def extract(
        self,
        thread_id: Optional[str] = None,
        cwd: Optional[str] = None,
        include_tool_results: bool = False,
    ) -> TranscriptResult:
        """Extract transcript from Codex conversation."""
        errors = []
        stats = {
            "total_lines": 0,
            "user_messages": 0,
            "assistant_messages": 0,
            "filtered_system": 0,
            "filtered_tool_results": 0,
            "parse_errors": 0,
        }

        # Find thread
        if thread_id:
            rollout_path = self._find_rollout_file(thread_id)
            if not rollout_path:
                return TranscriptResult(
                    platform="codex",
                    session_id=thread_id,
                    cwd=cwd or "",
                    started_at="",
                    last_activity_at="",
                    messages=[],
                    stats=stats,
                    errors=[f"Rollout file not found for thread: {thread_id}"],
                )
        elif cwd:
            threads = self.find_threads_by_cwd(cwd)
            if not threads:
                return TranscriptResult(
                    platform="codex",
                    session_id="",
                    cwd=cwd,
                    started_at="",
                    last_activity_at="",
                    messages=[],
                    stats=stats,
                    errors=[f"No threads found for cwd: {cwd}"],
                )
            if len(threads) > 1:
                errors.append(f"Found {len(threads)} threads for cwd, using most recent")
            thread_id = threads[0]["id"]
            rollout_path = self._find_rollout_file(thread_id)
        else:
            thread = self.find_active_thread()
            if not thread:
                return TranscriptResult(
                    platform="codex",
                    session_id="",
                    cwd="",
                    started_at="",
                    last_activity_at="",
                    messages=[],
                    stats=stats,
                    errors=["No active Codex thread found"],
                )
            thread_id = thread["id"]
            cwd = thread.get("cwd", "")
            rollout_path = self._find_rollout_file(thread_id)

        if not rollout_path or not rollout_path.exists():
            return TranscriptResult(
                platform="codex",
                session_id=thread_id,
                cwd=cwd or "",
                started_at="",
                last_activity_at="",
                messages=[],
                stats=stats,
                errors=[f"Rollout file not found"],
            )

        # Parse JSONL
        messages = []
        started_at = ""
        last_activity_at = ""

        try:
            content = rollout_path.read_text(encoding="utf-8")
        except OSError as e:
            return TranscriptResult(
                platform="codex",
                session_id=thread_id,
                cwd=cwd or "",
                started_at="",
                last_activity_at="",
                messages=[],
                stats=stats,
                errors=[f"Failed to read rollout: {e}"],
            )

        for line in content.strip().split("\n"):
            stats["total_lines"] += 1
            if not line.strip():
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats["parse_errors"] += 1
                continue

            timestamp = obj.get("timestamp", "")
            if timestamp:
                if not started_at:
                    started_at = timestamp
                last_activity_at = timestamp

            obj_type = obj.get("type")
            payload = obj.get("payload", {})

            # User messages in response_item
            if obj_type == "response_item":
                role = payload.get("role")
                content = payload.get("content", [])

                if role == "user":
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "input_text":
                                text = item.get("text", "")
                                if self._is_system_text(text):
                                    stats["filtered_system"] += 1
                                    continue
                                messages.append({
                                    "role": "user",
                                    "text": text,
                                    "timestamp": timestamp,
                                })
                                stats["user_messages"] += 1

            # Agent messages
            elif obj_type == "event_msg":
                if payload.get("type") == "agent_message":
                    text = payload.get("message", "")
                    if text and not self._is_system_text(text):
                        messages.append({
                            "role": "assistant",
                            "text": text,
                            "timestamp": timestamp,
                        })
                        stats["assistant_messages"] += 1

        return TranscriptResult(
            platform="codex",
            session_id=thread_id,
            cwd=cwd or "",
            started_at=started_at,
            last_activity_at=last_activity_at,
            messages=messages,
            stats=stats,
            errors=errors,
        )


def extract_transcript(
    platform: str = "auto",
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    include_tool_results: bool = False,
) -> TranscriptResult:
    """
    Extract transcript from conversation.

    Args:
        platform: "claude", "codex", or "auto" (detect from session_id/cwd)
        session_id: Specific session/thread ID
        cwd: Project directory to find conversation for
        include_tool_results: Include tool execution results

    Returns:
        TranscriptResult with normalized messages
    """
    if platform == "auto":
        # Try to detect platform
        if session_id:
            # Claude UUIDs have specific format
            if "-" in session_id and len(session_id) == 36:
                # Could be either, try Claude first
                result = ClaudeTranscriptExtractor().extract(session_id, cwd, include_tool_results)
                if not result.errors or "not found" not in str(result.errors):
                    return result
                return CodexTranscriptExtractor().extract(session_id, cwd, include_tool_results)

        # Try both, prefer one with active session
        claude_ext = ClaudeTranscriptExtractor()
        codex_ext = CodexTranscriptExtractor()

        claude_active = claude_ext.find_active_session(cwd)
        codex_active = codex_ext.find_active_thread(cwd)

        if claude_active and not codex_active:
            return claude_ext.extract(session_id, cwd, include_tool_results)
        elif codex_active and not claude_active:
            return codex_ext.extract(session_id, cwd, include_tool_results)
        elif claude_active and codex_active:
            # Both active, prefer more recent
            claude_time = claude_active.get("updatedAt", 0)
            codex_time = codex_active.get("updated_at", 0)
            if claude_time >= codex_time:
                return claude_ext.extract(session_id, cwd, include_tool_results)
            else:
                return codex_ext.extract(session_id, cwd, include_tool_results)
        else:
            # Neither active, return error
            return TranscriptResult(
                platform="unknown",
                session_id="",
                cwd=cwd or "",
                started_at="",
                last_activity_at="",
                messages=[],
                stats={},
                errors=["No active session found on any platform"],
            )

    elif platform == "claude":
        return ClaudeTranscriptExtractor().extract(session_id, cwd, include_tool_results)
    elif platform == "codex":
        return CodexTranscriptExtractor().extract(session_id, cwd, include_tool_results)
    else:
        return TranscriptResult(
            platform=platform,
            session_id="",
            cwd="",
            started_at="",
            last_activity_at="",
            messages=[],
            stats={},
            errors=[f"Unknown platform: {platform}"],
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract conversation transcripts")
    parser.add_argument("--platform", choices=["auto", "claude", "codex"], default="auto")
    parser.add_argument("--session-id", help="Specific session/thread ID")
    parser.add_argument("--cwd", help="Project directory")
    parser.add_argument("--include-tool-results", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--list-sessions", action="store_true", help="List available sessions")

    args = parser.parse_args()

    if args.list_sessions:
        print("=== Claude Code Sessions ===")
        if args.cwd:
            sessions = ClaudeTranscriptExtractor().find_sessions_by_cwd(args.cwd)
            for s in sessions[:10]:
                print(f"  {s['sessionId']} | {s['last_activity']} | {s['line_count']} lines")
        else:
            print("  (provide --cwd to list sessions)")

        print("\n=== Codex Threads ===")
        if args.cwd:
            threads = CodexTranscriptExtractor().find_threads_by_cwd(args.cwd)
            for t in threads[:10]:
                print(f"  {t['id']} | {t['title'][:50]}")
        else:
            print("  (provide --cwd to list threads)")
    else:
        result = extract_transcript(
            platform=args.platform,
            session_id=args.session_id,
            cwd=args.cwd,
            include_tool_results=args.include_tool_results,
        )

        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"Platform: {result.platform}")
            print(f"Session: {result.session_id}")
            print(f"CWD: {result.cwd}")
            print(f"Started: {result.started_at}")
            print(f"Last Activity: {result.last_activity_at}")
            print(f"Stats: {result.stats}")
            if result.errors:
                print(f"Errors: {result.errors}")
            print(f"\n=== Messages ({len(result.messages)}) ===")
            for msg in result.messages[:10]:
                role = msg["role"].upper()
                text = msg["text"][:100].replace("\n", " ")
                print(f"{role}: {text}...")
            if len(result.messages) > 10:
                print(f"... and {len(result.messages) - 10} more")
