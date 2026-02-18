"""
Bootstrap Context Generator for FixOnce

Generates a universal context file (.fixonce/CONTEXT.md) that ANY AI can read.
This makes FixOnce editor-agnostic - not dependent on MCP.

Auto-updates whenever memory changes.
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List


def generate_context_file(memory: Dict[str, Any], output_dir: str) -> str:
    """
    Generate a context.md file from project memory.

    Args:
        memory: The project memory dict
        output_dir: The project's working directory

    Returns:
        Path to the generated file
    """
    # Ensure .fixonce directory exists
    fixonce_dir = Path(output_dir) / ".fixonce"
    fixonce_dir.mkdir(exist_ok=True)

    context_path = fixonce_dir / "CONTEXT.md"

    # Generate content
    content = _generate_content(memory)

    # Write file
    with open(context_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return str(context_path)


def _generate_content(memory: Dict[str, Any]) -> str:
    """Generate the markdown content."""

    lines = []

    # Header
    lines.append("# FixOnce Context")
    lines.append("")
    lines.append("> **Auto-generated file.** Do not edit manually.")
    lines.append(f"> Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Project Info
    project_info = memory.get('project_info', {})
    project_name = project_info.get('name', 'Unknown')
    lines.append(f"## Project: {project_name}")
    lines.append("")

    # Current Goal (Intent)
    live_record = memory.get('live_record', {})
    intent = live_record.get('intent', {})
    current_goal = intent.get('current_goal', '')

    if current_goal:
        lines.append("## Current Goal")
        lines.append("")
        lines.append(f"**{current_goal}**")
        lines.append("")

        next_step = intent.get('next_step', '')
        if next_step:
            lines.append(f"Next step: {next_step}")
            lines.append("")

        blockers = intent.get('blockers', '')
        if blockers and blockers != "User has not specified task yet":
            lines.append(f"Blockers: {blockers}")
            lines.append("")

    lines.append("---")
    lines.append("")

    # DECISIONS - Most important section
    decisions = memory.get('decisions', [])
    if decisions:
        lines.append("## Decisions (MUST FOLLOW)")
        lines.append("")
        lines.append("> **These are architectural decisions that MUST be respected.**")
        lines.append("> Before making changes that contradict these, ask for explicit approval.")
        lines.append("")

        for dec in decisions:
            decision_text = dec.get('decision', '')
            reason = dec.get('reason', '')

            lines.append(f"### {decision_text}")
            lines.append("")
            lines.append(f"*Reason:* {reason}")
            lines.append("")

    lines.append("---")
    lines.append("")

    # Architecture
    architecture = live_record.get('architecture', {})
    if architecture:
        lines.append("## Architecture")
        lines.append("")

        summary = architecture.get('summary', '')
        if summary:
            lines.append(summary)
            lines.append("")

        stack = architecture.get('stack', '')
        if stack:
            lines.append(f"**Stack:** {stack}")
            lines.append("")

        key_flows = architecture.get('key_flows', [])
        if key_flows:
            lines.append("**Key Flows:**")
            for flow in key_flows:
                lines.append(f"- {flow}")
            lines.append("")

    lines.append("---")
    lines.append("")

    # AVOID patterns
    avoid = memory.get('avoid', [])
    if avoid:
        lines.append("## Avoid (Anti-Patterns)")
        lines.append("")
        lines.append("> **Do NOT do these things.**")
        lines.append("")

        for item in avoid:
            what = item.get('what', '') if isinstance(item, dict) else str(item)
            reason = item.get('reason', '') if isinstance(item, dict) else ''

            lines.append(f"- **{what}**")
            if reason:
                lines.append(f"  - Reason: {reason}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Key Insights (top 10, most recent first)
    lessons = live_record.get('lessons', {})
    insights = lessons.get('insights', [])

    if insights:
        lines.append("## Key Insights")
        lines.append("")
        lines.append("> Lessons learned from previous work. Search `search_past_solutions()` for more.")
        lines.append("")

        # Get last 10 insights (most useful)
        recent_insights = _get_top_insights(insights, limit=10)

        for insight in recent_insights:
            text = insight if isinstance(insight, str) else insight.get('text', '')
            if text:
                # Truncate very long insights
                if len(text) > 200:
                    text = text[:200] + "..."
                lines.append(f"- {text}")

        lines.append("")

    # Failed attempts (important to not repeat)
    failed = lessons.get('failed_attempts', [])
    if failed:
        lines.append("## Failed Attempts")
        lines.append("")
        lines.append("> These approaches were tried and failed. Don't repeat them.")
        lines.append("")

        for attempt in failed[:5]:  # Last 5
            text = attempt if isinstance(attempt, str) else attempt.get('text', '')
            if text:
                lines.append(f"- {text}")

        lines.append("")

    lines.append("---")
    lines.append("")

    # Debug Sessions (solved problems)
    debug_sessions = memory.get('debug_sessions', [])
    if debug_sessions:
        lines.append("## Solved Problems")
        lines.append("")
        lines.append("> Reference these when encountering similar errors.")
        lines.append("")

        for session in debug_sessions[:5]:  # Last 5
            problem = session.get('problem', '')
            solution = session.get('solution', '')

            if problem and solution:
                lines.append(f"### {problem}")
                lines.append(f"**Solution:** {solution}")
                lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("*Generated by [FixOnce](https://github.com/fixonce) - AI Memory Layer*")

    return '\n'.join(lines)


def _get_top_insights(insights: List, limit: int = 10) -> List:
    """
    Get top insights by importance and recency.
    Prioritizes: high importance > medium > low, then by use_count, then by recency.
    """
    scored = []

    for i, insight in enumerate(insights):
        if isinstance(insight, str):
            # Old format - string only
            scored.append({
                'text': insight,
                'score': len(insights) - i  # Recent = higher score
            })
        else:
            # New format - dict with metadata
            importance = insight.get('importance', 'medium')
            use_count = insight.get('use_count', 0)

            # Calculate score
            importance_score = {'high': 100, 'medium': 50, 'low': 10}.get(importance, 50)
            recency_score = len(insights) - i

            scored.append({
                'text': insight.get('text', ''),
                'score': importance_score + (use_count * 10) + recency_score
            })

    # Sort by score descending
    scored.sort(key=lambda x: x['score'], reverse=True)

    return [item['text'] for item in scored[:limit] if item['text']]


def update_context_on_memory_change(project_id: str, memory: Dict[str, Any]) -> Optional[str]:
    """
    Hook to call after memory changes.
    Updates the context file if working_dir exists.

    Returns the path to the context file, or None if not possible.
    """
    project_info = memory.get('project_info', {})
    working_dir = project_info.get('working_dir', '')

    if not working_dir or not os.path.isdir(working_dir):
        return None

    try:
        return generate_context_file(memory, working_dir)
    except Exception as e:
        print(f"[ContextGen] Failed to generate context: {e}")
        return None
