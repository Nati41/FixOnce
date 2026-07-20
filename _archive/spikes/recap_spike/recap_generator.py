#!/usr/bin/env python3
"""
Recap Generator - Generate recaps from conversation transcripts.

Uses existing CLI tools (Codex exec) without requiring new API keys.
Falls back to evidence-only recap if AI generation fails.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Import transcript extractor
from transcript_extractor import extract_transcript, TranscriptResult


@dataclass
class RecapResult:
    """Structured recap output."""
    title: str
    summary: str
    user_goal: str
    important_discussion: List[str]
    user_corrections: List[str]
    decisions_and_insights: List[str]
    completed_work: List[str]
    verified_work: List[str]
    attempted_work: List[str]
    open_threads: List[str]
    final_state: str
    uncertainties: List[str]
    generation_method: str  # "ai_codex", "ai_claude", "evidence_only"
    generation_status: str  # "success", "partial", "fallback"
    generation_time_ms: int
    input_messages: int
    input_tokens_approx: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SystemEvidence:
    """Evidence from FixOnce and git."""
    decisions: List[Dict[str, Any]]
    solved_bugs: List[Dict[str, Any]]
    insights: List[Dict[str, Any]]
    commits: List[Dict[str, Any]]
    changed_files: List[str]
    branch: str
    uncommitted_files: List[str]
    time_range: Dict[str, str]

    def to_dict(self) -> dict:
        return asdict(self)


RECAP_PROMPT_TEMPLATE = '''You are generating a structured recap of a work session.

## Input
The following is a transcript of a conversation between a user and an AI assistant working on a software project.

<transcript>
{transcript}
</transcript>

## Task
Generate a structured JSON recap of this session.

## Rules
1. DO NOT invent "Next steps" - only report what was discussed, not recommendations
2. DO NOT present AI suggestions as user intent
3. Separate "completed" (done) from "verified" (tested/confirmed working)
4. Include direction changes and user corrections
5. Use semantic compression - summarize themes, don't list every message
6. When evidence is unclear, note it in "uncertainties"
7. Focus on WHAT HAPPENED, not what should happen next

## Output Format
Return ONLY valid JSON matching this schema:
{{
  "title": "Short descriptive title (max 60 chars)",
  "summary": "2-3 sentence overview of the session",
  "user_goal": "What the user was trying to accomplish",
  "important_discussion": ["Key discussion points"],
  "user_corrections": ["Times the user corrected or redirected the AI"],
  "decisions_and_insights": ["Decisions made or insights gained"],
  "completed_work": ["Work that was done"],
  "verified_work": ["Work that was tested/confirmed working"],
  "attempted_work": ["Work attempted but not completed"],
  "open_threads": ["Unresolved questions or incomplete work"],
  "final_state": "State of the project at session end",
  "uncertainties": ["Things that are unclear from the transcript"]
}}

Output ONLY the JSON, no markdown, no explanation.'''


def _approximate_tokens(text: str) -> int:
    """Rough token count approximation."""
    return len(text) // 4


def _format_transcript_for_recap(messages: List[Dict[str, str]], max_tokens: int = 50000) -> str:
    """Format messages for recap prompt, respecting token limits."""
    lines = []
    total_chars = 0
    char_limit = max_tokens * 4  # Approximate chars from tokens

    for msg in messages:
        role = msg.get("role", "unknown").upper()
        text = msg.get("text", "").strip()

        # Skip very short messages
        if len(text) < 10:
            continue

        # Truncate individual messages if needed
        if len(text) > 2000:
            text = text[:2000] + "..."

        line = f"{role}: {text}\n"

        if total_chars + len(line) > char_limit:
            lines.append("[... earlier messages truncated for length ...]")
            break

        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines)


def _extract_json_from_response(response: str) -> Optional[dict]:
    """Extract JSON from model response, handling markdown code blocks."""
    # Try direct parse first
    response = response.strip()
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding JSON object
    json_match = re.search(r'\{.*\}', response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def generate_recap_with_codex(
    transcript: str,
    timeout_seconds: int = 120,
    cwd: str = "/tmp",
) -> Optional[dict]:
    """Generate recap using Codex exec."""
    prompt = RECAP_PROMPT_TEMPLATE.format(transcript=transcript)

    try:
        # Write prompt to temp file to avoid shell escaping issues
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            result = subprocess.run(
                [
                    "codex", "exec",
                    "--json",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    "-C", cwd,
                    "-",  # Read from stdin
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=cwd,
            )
        finally:
            os.unlink(prompt_file)

        if result.returncode != 0:
            return None

        # Parse JSONL output
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "item.completed":
                    item = event.get("item", {})
                    if item.get("type") == "agent_message":
                        text = item.get("text", "")
                        return _extract_json_from_response(text)
            except json.JSONDecodeError:
                continue

        return None

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def generate_recap_with_claude(
    transcript: str,
    timeout_seconds: int = 120,
    cwd: str = "/tmp",
) -> Optional[dict]:
    """Generate recap using Claude CLI (if available and working)."""
    prompt = RECAP_PROMPT_TEMPLATE.format(transcript=transcript)

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--output-format", "text",
                "--no-session-persistence",
                "--bare",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=cwd,
        )

        if result.returncode != 0:
            return None

        return _extract_json_from_response(result.stdout)

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def collect_system_evidence(
    cwd: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> SystemEvidence:
    """Collect evidence from FixOnce and git."""
    decisions = []
    solved_bugs = []
    insights = []
    commits = []
    changed_files = []
    branch = ""
    uncommitted_files = []

    # Get git branch
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
    except:
        pass

    # Get uncommitted files
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            uncommitted_files = [
                line[3:] for line in result.stdout.strip().split("\n")
                if line.strip()
            ]
    except:
        pass

    # Get recent commits (if time range provided)
    if start_time:
        try:
            result = subprocess.run(
                ["git", "log", f"--since={start_time}", "--oneline", "-20"],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        parts = line.split(" ", 1)
                        if len(parts) == 2:
                            commits.append({
                                "hash": parts[0],
                                "message": parts[1],
                            })
        except:
            pass

    # Try to load FixOnce data
    fixonce_data_dir = Path.home() / ".fixonce"
    if fixonce_data_dir.exists():
        # Find project file
        projects_dir = fixonce_data_dir / "projects_v2"
        if projects_dir.exists():
            for project_file in projects_dir.glob("*.json"):
                try:
                    data = json.loads(project_file.read_text(encoding="utf-8"))
                    project_cwd = data.get("project_info", {}).get("path", "")
                    if project_cwd == cwd:
                        # Found the project
                        live_record = data.get("live_record", {})

                        # Decisions
                        for dec in data.get("decisions", []):
                            decisions.append({
                                "text": dec.get("decision", ""),
                                "reason": dec.get("reason", ""),
                            })

                        # Insights
                        for ins in live_record.get("lessons", {}).get("insights", []):
                            insights.append({
                                "text": ins.get("text", ""),
                            })

                        # Solved bugs
                        for solution in data.get("solutions", []):
                            solved_bugs.append({
                                "error": solution.get("error_signature", ""),
                                "solution": solution.get("solution", ""),
                            })

                        break
                except:
                    continue

    return SystemEvidence(
        decisions=decisions,
        solved_bugs=solved_bugs,
        insights=insights,
        commits=commits,
        changed_files=changed_files,
        branch=branch,
        uncommitted_files=uncommitted_files,
        time_range={
            "start": start_time or "",
            "end": end_time or "",
        },
    )


def generate_evidence_only_recap(
    transcript: TranscriptResult,
    evidence: SystemEvidence,
) -> RecapResult:
    """Generate recap from evidence only, without AI summarization."""
    # Extract user goal from first user message
    user_goal = ""
    for msg in transcript.messages[:3]:
        if msg.get("role") == "user":
            user_goal = msg.get("text", "")[:200]
            break

    # Get last user topic
    last_user_topic = ""
    for msg in reversed(transcript.messages):
        if msg.get("role") == "user":
            last_user_topic = msg.get("text", "")[:200]
            break

    return RecapResult(
        title=f"Work session: {Path(transcript.cwd).name}" if transcript.cwd else "Work session",
        summary=f"Session with {transcript.stats.get('user_messages', 0)} user messages and {transcript.stats.get('assistant_messages', 0)} assistant responses.",
        user_goal=user_goal,
        important_discussion=[],
        user_corrections=[],
        decisions_and_insights=[d.get("text", "") for d in evidence.decisions[:5]],
        completed_work=[f"Commit: {c.get('message', '')}" for c in evidence.commits[:5]],
        verified_work=[],
        attempted_work=[],
        open_threads=[f"Uncommitted: {f}" for f in evidence.uncommitted_files[:5]],
        final_state=f"Branch: {evidence.branch}" if evidence.branch else "Unknown",
        uncertainties=["AI recap unavailable - showing evidence only"],
        generation_method="evidence_only",
        generation_status="fallback",
        generation_time_ms=0,
        input_messages=len(transcript.messages),
        input_tokens_approx=0,
    )


def generate_recap(
    platform: str = "auto",
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
    use_ai: bool = True,
    prefer_codex: bool = True,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """
    Generate recap from conversation transcript.

    Args:
        platform: "claude", "codex", or "auto"
        session_id: Specific session/thread ID
        cwd: Project directory
        use_ai: Whether to attempt AI summarization
        prefer_codex: Prefer Codex over Claude for generation
        timeout_seconds: Timeout for AI generation

    Returns:
        Dict with "recap" and "evidence" keys
    """
    start_time = datetime.now()

    # Extract transcript
    transcript = extract_transcript(
        platform=platform,
        session_id=session_id,
        cwd=cwd,
        include_tool_results=False,
    )

    if transcript.errors and not transcript.messages:
        return {
            "error": transcript.errors[0],
            "transcript": transcript.to_dict(),
            "recap": None,
            "evidence": None,
        }

    # Collect system evidence
    evidence = collect_system_evidence(
        cwd=transcript.cwd or cwd or os.getcwd(),
        start_time=transcript.started_at,
        end_time=transcript.last_activity_at,
    )

    # Format transcript for AI
    formatted_transcript = _format_transcript_for_recap(transcript.messages)
    input_tokens = _approximate_tokens(formatted_transcript)

    # Try AI generation
    recap_data = None
    generation_method = "none"

    if use_ai and formatted_transcript:
        if prefer_codex:
            # Try Codex first
            recap_data = generate_recap_with_codex(
                formatted_transcript,
                timeout_seconds=timeout_seconds,
                cwd=transcript.cwd or cwd or "/tmp",
            )
            if recap_data:
                generation_method = "ai_codex"
            else:
                # Fall back to Claude
                recap_data = generate_recap_with_claude(
                    formatted_transcript,
                    timeout_seconds=timeout_seconds,
                    cwd=transcript.cwd or cwd or "/tmp",
                )
                if recap_data:
                    generation_method = "ai_claude"
        else:
            # Try Claude first
            recap_data = generate_recap_with_claude(
                formatted_transcript,
                timeout_seconds=timeout_seconds,
                cwd=transcript.cwd or cwd or "/tmp",
            )
            if recap_data:
                generation_method = "ai_claude"
            else:
                # Fall back to Codex
                recap_data = generate_recap_with_codex(
                    formatted_transcript,
                    timeout_seconds=timeout_seconds,
                    cwd=transcript.cwd or cwd or "/tmp",
                )
                if recap_data:
                    generation_method = "ai_codex"

    generation_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    if recap_data:
        # AI recap succeeded
        recap = RecapResult(
            title=recap_data.get("title", ""),
            summary=recap_data.get("summary", ""),
            user_goal=recap_data.get("user_goal", ""),
            important_discussion=recap_data.get("important_discussion", []),
            user_corrections=recap_data.get("user_corrections", []),
            decisions_and_insights=recap_data.get("decisions_and_insights", []),
            completed_work=recap_data.get("completed_work", []),
            verified_work=recap_data.get("verified_work", []),
            attempted_work=recap_data.get("attempted_work", []),
            open_threads=recap_data.get("open_threads", []),
            final_state=recap_data.get("final_state", ""),
            uncertainties=recap_data.get("uncertainties", []),
            generation_method=generation_method,
            generation_status="success",
            generation_time_ms=generation_time_ms,
            input_messages=len(transcript.messages),
            input_tokens_approx=input_tokens,
        )
    else:
        # Fall back to evidence-only recap
        recap = generate_evidence_only_recap(transcript, evidence)
        recap.generation_time_ms = generation_time_ms
        recap.input_messages = len(transcript.messages)
        recap.input_tokens_approx = input_tokens

    return {
        "recap": recap.to_dict(),
        "evidence": evidence.to_dict(),
        "transcript_stats": transcript.stats,
        "session_id": transcript.session_id,
        "platform": transcript.platform,
        "cwd": transcript.cwd,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate recap from conversation")
    parser.add_argument("--platform", choices=["auto", "claude", "codex"], default="auto")
    parser.add_argument("--session-id", help="Specific session/thread ID")
    parser.add_argument("--cwd", help="Project directory")
    parser.add_argument("--no-ai", action="store_true", help="Skip AI generation, evidence only")
    parser.add_argument("--prefer-claude", action="store_true", help="Prefer Claude over Codex for generation")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout for AI generation")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    result = generate_recap(
        platform=args.platform,
        session_id=args.session_id,
        cwd=args.cwd,
        use_ai=not args.no_ai,
        prefer_codex=not args.prefer_claude,
        timeout_seconds=args.timeout,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if "error" in result:
            print(f"Error: {result['error']}")
            sys.exit(1)

        recap = result.get("recap", {})
        evidence = result.get("evidence", {})

        print("=" * 60)
        print(f"RECAP: {recap.get('title', 'Untitled')}")
        print("=" * 60)
        print(f"\nSummary: {recap.get('summary', 'N/A')}")
        print(f"\nUser Goal: {recap.get('user_goal', 'N/A')}")

        if recap.get("completed_work"):
            print("\nCompleted Work:")
            for item in recap["completed_work"][:5]:
                print(f"  ✓ {item}")

        if recap.get("decisions_and_insights"):
            print("\nDecisions & Insights:")
            for item in recap["decisions_and_insights"][:5]:
                print(f"  • {item}")

        if recap.get("open_threads"):
            print("\nOpen Threads:")
            for item in recap["open_threads"][:5]:
                print(f"  → {item}")

        print(f"\n--- Generation ---")
        print(f"Method: {recap.get('generation_method', 'N/A')}")
        print(f"Status: {recap.get('generation_status', 'N/A')}")
        print(f"Time: {recap.get('generation_time_ms', 0)}ms")
        print(f"Messages: {recap.get('input_messages', 0)}")

        print(f"\n--- Evidence ---")
        print(f"Branch: {evidence.get('branch', 'N/A')}")
        print(f"Commits: {len(evidence.get('commits', []))}")
        print(f"Uncommitted: {len(evidence.get('uncommitted_files', []))}")
        print(f"FixOnce Decisions: {len(evidence.get('decisions', []))}")
