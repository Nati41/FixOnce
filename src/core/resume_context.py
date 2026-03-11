"""
Resume Context Builder - Builds structured context for session opening.

This module provides the "truth layer" for session continuity:
- resume_context: structured object with all session state fields
- suggested_opening: human-readable text derived from the context

The opening message is NOT a template - it's built from real saved state.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List


def build_resume_context(
    project_data: Dict[str, Any],
    working_dir: str,
    git_hash: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build structured resume_context from saved project state.

    All fields are grounded in real saved data.
    Unknown fields are omitted, not hallucinated.

    Args:
        project_data: The full project data dict from storage
        working_dir: Current working directory path
        git_hash: Current git commit hash (optional)

    Returns:
        Structured resume_context object
    """
    context = {}

    # Project info
    project_info = project_data.get('project_info', {})
    context['project'] = project_info.get('name') or Path(working_dir).name
    context['project_path'] = working_dir

    # Git checkpoint
    if git_hash:
        context['checkpoint'] = git_hash[:12]

    # Live record data
    lr = project_data.get('live_record', {})
    intent = lr.get('intent', {})
    arch = lr.get('architecture', {})

    # Work area (from intent or architecture)
    if intent.get('work_area'):
        context['work_area'] = intent['work_area']
    elif intent.get('current_goal'):
        # Derive work area from goal if not explicitly set
        context['work_area'] = _extract_work_area(intent['current_goal'])

    # Intent - what we were trying to achieve
    if intent.get('current_goal'):
        context['intent'] = intent['current_goal']

    # Why - the purpose behind the work
    if intent.get('why'):
        context['why'] = intent['why']
    elif arch.get('summary'):
        # Fall back to architecture summary for context
        context['why'] = arch['summary']

    # Last file worked on
    if intent.get('last_file'):
        context['last_file'] = intent['last_file']

    # Last change description
    if intent.get('last_change'):
        context['last_change'] = intent['last_change']

    # Resume state (operational state)
    resume_state = project_data.get('resume_state', {})
    if resume_state:
        if resume_state.get('last_completed_step'):
            context['last_completed_step'] = resume_state['last_completed_step']
        if resume_state.get('current_status'):
            context['current_status'] = resume_state['current_status']
        if resume_state.get('next_recommended_action'):
            context['next_step'] = resume_state['next_recommended_action']
        if resume_state.get('updated_at'):
            context['updated_at'] = resume_state['updated_at']

    # If no updated_at from resume_state, try intent.updated_at (most common update source)
    if 'updated_at' not in context and intent.get('updated_at'):
        context['updated_at'] = intent['updated_at']

    # Final fallback: last activity time from decisions/insights
    if 'updated_at' not in context:
        context['updated_at'] = _get_last_activity_time(project_data)

    # Open tasks (things still in progress)
    open_tasks = _collect_open_tasks(project_data, intent)
    if open_tasks:
        context['open_tasks'] = open_tasks

    # Decisions (active, non-superseded)
    all_decisions = project_data.get('decisions', [])
    active_decisions = [d for d in all_decisions if not d.get('superseded', False)]
    if active_decisions:
        # Get decision texts (truncated for display)
        context['decisions'] = [
            d.get('decision', '')[:80] for d in active_decisions[-5:]
            if d.get('decision')
        ]

    # Avoid list (critical anti-patterns)
    avoid_list = project_data.get('avoid', [])
    if avoid_list:
        # Get most recent/important avoids
        recent_avoids = [a.get('what', '') for a in avoid_list[-3:] if a.get('what')]
        if recent_avoids:
            context['avoid'] = recent_avoids

    # Key files from architecture
    if arch.get('key_files'):
        context['key_files'] = arch['key_files']

    # Human summary - concise description of current state
    context['human_summary'] = _build_human_summary(context)

    # Debug metadata (optional)
    context['_meta'] = {
        'built_at': datetime.now().isoformat(),
        'derived_from': _list_evidence_sources(context),
        'confidence': _calculate_confidence(context)
    }

    return context


def build_suggested_opening(
    context: Dict[str, Any],
    language: str = 'he'
) -> str:
    """
    Build clean, scannable opening message from structured context.

    New format: Short sections, bullet points, easy to scan.
    Designed for developer tools (like Cursor, Linear, Raycast).

    Args:
        context: The resume_context object
        language: 'he' for Hebrew, 'en' for English

    Returns:
        Clean, scannable opening message
    """
    SEP = "────────────────────────────────────────"
    lines = []

    project = context.get('project', 'Unknown')
    project_path = context.get('project_path', '')

    # === HEADER ===
    lines.append(f"🧠 FixOnce | {project}")
    lines.append("")

    # Basic info
    if project_path:
        lines.append(f"📍 Path: {project_path}")

    checkpoint = context.get('checkpoint')
    if checkpoint:
        lines.append(f"🔖 Version: {checkpoint}")

    updated_at = context.get('updated_at')
    if updated_at:
        time_str = _format_time_specific(updated_at)
        lines.append(f"⏱ Last: {time_str}")

    lines.append("")
    lines.append(SEP)

    # === DECISIONS ===
    decisions = context.get('decisions', [])
    if decisions:
        lines.append("🔒 DECISIONS (must respect)")
        for dec in decisions[:5]:
            lines.append(f"• {dec}")
        lines.append("")
        lines.append(SEP)

    # === AVOID ===
    avoid = context.get('avoid', [])
    if avoid:
        lines.append("⚠️ AVOID (don't repeat)")
        for av in avoid[:3]:
            lines.append(f"• {av}")
        lines.append("")
        lines.append(SEP)

    # === CONTEXT ===
    lines.append("📂 CONTEXT")

    # Current goal/intent
    intent = context.get('intent')
    if intent:
        lines.append(f"Goal: {intent}")

    # Work area
    work_area = context.get('work_area')
    if work_area:
        lines.append(f"Area: {work_area}")

    # Last file
    last_file = context.get('last_file')
    if last_file:
        lines.append(f"File: {last_file}")

    # Last change
    last_change = context.get('last_change')
    if last_change:
        lines.append(f"Last: {last_change}")

    lines.append("")
    lines.append(SEP)

    # === STATE + CLOSING ===
    human_summary = context.get('human_summary')
    if human_summary:
        lines.append(f"📌 STATE: {human_summary}")
    else:
        lines.append("📌 STATE: Ready")

    lines.append("")

    # Clean closing
    if language == 'he':
        lines.append("מה עושים?")
    else:
        lines.append("What's next?")

    return "\n".join(lines)


def build_new_project_opening(
    project_name: str,
    stack: Optional[str] = None,
    working_dir: Optional[str] = None,
    language: str = 'he'
) -> str:
    """
    Build opening message for a new project.
    Clean format matching the existing project style.
    """
    SEP = "────────────────────────────────────────"
    lines = []

    lines.append(f"🧠 FixOnce | {project_name}")
    lines.append("📋 Status: NEW PROJECT")
    lines.append("")

    if working_dir:
        lines.append(f"📍 Path: {working_dir}")

    if stack:
        lines.append(f"📊 Stack: {stack}")

    lines.append("")
    lines.append(SEP)
    lines.append("🔒 DECISIONS: (none yet)")
    lines.append("⚠️ AVOID: (none yet)")
    lines.append(SEP)
    lines.append("")

    if language == 'he':
        lines.append("🎯 מה המטרה לפרויקט הזה?")
    else:
        lines.append("🎯 What's the goal for this project?")

    return "\n".join(lines)


# --- Helper Functions ---

def _extract_work_area(goal: str) -> Optional[str]:
    """Extract work area from goal text (basic heuristic)."""
    if not goal:
        return None

    # Common patterns
    keywords = ['opening', 'resume', 'session', 'dashboard', 'extension',
                'memory', 'search', 'api', 'ui', 'ux', 'protocol']

    goal_lower = goal.lower()
    found = [k for k in keywords if k in goal_lower]

    if found:
        return " / ".join(found[:2])

    # Return truncated goal if no keywords found
    return goal[:30] if len(goal) > 30 else goal


def _get_last_activity_time(project_data: Dict[str, Any]) -> Optional[str]:
    """Get the most recent activity timestamp."""
    timestamps = []

    # Check various timestamp sources
    if project_data.get('last_updated'):
        timestamps.append(project_data['last_updated'])

    # Check decisions
    decisions = project_data.get('decisions', [])
    if decisions:
        last_decision = decisions[-1]
        if last_decision.get('timestamp'):
            timestamps.append(last_decision['timestamp'])

    # Check insights
    lr = project_data.get('live_record', {})
    insights = lr.get('lessons', {}).get('insights', [])
    if insights:
        last_insight = insights[-1]
        if isinstance(last_insight, dict) and last_insight.get('timestamp'):
            timestamps.append(last_insight['timestamp'])

    if timestamps:
        # Return most recent
        return max(timestamps)

    return None


def _collect_open_tasks(project_data: Dict[str, Any], intent: Dict[str, Any]) -> List[str]:
    """Collect open/in-progress tasks."""
    tasks = []

    # From resume state
    resume_state = project_data.get('resume_state', {})
    if resume_state.get('current_status') == 'in_progress':
        if resume_state.get('active_task'):
            tasks.append(resume_state['active_task'])

    # From intent blockers
    blockers = intent.get('blockers', [])
    if blockers:
        tasks.extend(blockers[:2])

    return tasks[:3]  # Max 3 open tasks


def _build_human_summary(context: Dict[str, Any]) -> str:
    """Build a concise human summary of current state."""
    parts = []

    work_area = context.get('work_area')
    intent = context.get('intent')

    if work_area and intent:
        return f"{work_area} - {intent[:50]}"
    elif intent:
        return intent[:60]
    elif work_area:
        return work_area

    return ""


def _format_time_specific(iso_time: str) -> str:
    """Format time to be specific (not just 'today')."""
    try:
        dt = datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
        now = datetime.now()

        # If today, show time
        if dt.date() == now.date():
            return f"{dt.strftime('%H:%M')} היום"

        # If yesterday
        from datetime import timedelta
        if dt.date() == (now - timedelta(days=1)).date():
            return f"{dt.strftime('%H:%M')} אתמול"

        # Otherwise show date + time
        return dt.strftime('%d %b %H:%M')
    except:
        return iso_time[:16] if iso_time else ""


def _list_evidence_sources(context: Dict[str, Any]) -> List[str]:
    """List which data sources contributed to the context."""
    sources = []

    if context.get('intent'):
        sources.append('live_record.intent')
    if context.get('checkpoint'):
        sources.append('git')
    if context.get('last_completed_step'):
        sources.append('resume_state')
    if context.get('avoid'):
        sources.append('avoid_list')
    if context.get('why'):
        sources.append('architecture')

    return sources


def _calculate_confidence(context: Dict[str, Any]) -> str:
    """Calculate confidence level based on available data."""
    required_fields = ['project', 'intent', 'updated_at']
    optional_fields = ['work_area', 'why', 'last_change', 'last_file', 'checkpoint']

    required_present = sum(1 for f in required_fields if context.get(f))
    optional_present = sum(1 for f in optional_fields if context.get(f))

    if required_present == len(required_fields) and optional_present >= 3:
        return 'high'
    elif required_present >= 2:
        return 'medium'
    else:
        return 'low'
