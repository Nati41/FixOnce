"""
MCP Server for FixOnce AI Project Memory
Exposes tools for Claude to interact with persistent project context.

Usage:
    Add to Claude Code's MCP config:
    {
        "mcpServers": {
            "fixonce": {
                "command": "python3",
                "args": ["/path/to/mcp_memory_server.py"]
            }
        }
    }
"""

import sys
from pathlib import Path

# Add src directory to path for imports
SRC_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SRC_DIR))

from fastmcp import FastMCP
from managers.project_memory_manager import (
    get_context_summary,
    get_project_context,
    resolve_issue,
    update_ai_context,
    add_or_update_issue,
    search_solutions,
    get_issue_by_id,
    clear_active_issues,
    save_memory,
    log_decision,
    log_avoid,
    get_decisions,
    get_avoid_list,
    save_handover,
    get_handover,
    mark_decision_used,
    mark_avoid_used,
    get_memory_health,
    auto_update_project_info,
    get_project_status,
    is_meaningful_project,
    detect_project_info
)

# Create MCP server
mcp = FastMCP("fixonce-memory")


@mcp.tool()
def get_project_context_tool() -> str:
    """
    Get the current project context as a markdown summary.
    Use this at the start of a session to understand the project state,
    active issues, and recent solutions.

    IMPORTANT: Call this FIRST at the start of every conversation!

    Returns:
        Markdown formatted summary of:
        - Project info (name, stack, status)
        - Current AI focus/context
        - Active issues (deduped, with counts)
        - Recent solutions history
        - Stats
    """
    # Auto-detect project info if not set
    auto_update_project_info()

    memory = get_project_context()
    session = memory.get("ai_session", {})

    # Check if this is a new session started from dashboard
    if session.get("active") and not session.get("briefing_sent"):
        # Mark briefing as sent
        session["briefing_sent"] = True
        memory["ai_session"] = session
        save_memory(memory)

        # Generate special session briefing
        issues = memory.get("active_issues", [])
        solutions = memory.get("solutions_history", [])
        project = memory.get("project_info", {})

        # Get handover from last session
        handover = memory.get("handover", {})

        root_path = project.get('root_path', '')
        root_line = f"\n📁 Path: `{root_path}`" if root_path else "\n⚠️ No project root set - use set_project_root() to configure"

        briefing = f"""
🚀 **NEW FIXONCE SESSION STARTED**

## Project: {project.get('name', 'Unknown')}
Stack: {project.get('stack', 'Not specified')}{root_line}

"""
        # Add handover if exists
        if handover and handover.get("summary"):
            briefing += f"""## 📋 Handover from Last Session
{handover.get('summary', '')}
_(Saved: {handover.get('created_at', 'Unknown')})_

"""

        briefing += f"""## Current Status
- **{len(issues)} Active Issues** waiting for fixes
- **{len(solutions)} Solutions** in memory

"""
        if issues:
            briefing += "## Active Issues:\n"
            for issue in issues[:5]:
                issue_id = issue.get("id", "unknown")
                msg = issue.get("message", "")[:60]
                count = issue.get("count", 1)
                recurring = " ⚠️ RECURRING" if count > 1 else ""
                # Show ID so AI can use it directly with update_solution_status()
                briefing += f"- `{issue_id}`: {msg}...{recurring} (x{count})\n"

            # Check if any have solutions
            for issue in issues[:3]:
                msg = issue.get("message", "")
                for sol in solutions:
                    if any(kw in msg.lower() for kw in sol.get("keywords", [])):
                        briefing += f"\n💡 **Solution exists** for similar error: {sol.get('solution', '')[:60]}...\n"
                        break

        briefing += """
## Suggested Action
Start by addressing the most critical or recurring issues.
I'll search FixOnce history before proposing any fixes.

**Ready to assist!**
"""
        return briefing

    # Normal context summary
    return get_context_summary()


@mcp.tool()
def update_solution_status(issue_id: str, solution_description: str, keywords: list = None, worked: bool = True) -> dict:
    """
    Mark an issue as resolved and record the solution.
    This moves the issue from active_issues to solutions_history.

    IMPORTANT: Always provide 3-5 technical keywords related to the problem
    for better searchability. Examples:
    - Network error -> ["api", "fetch", "connection", "timeout", "server"]
    - UI bug -> ["css", "style", "layout", "component", "render"]
    - TypeError -> ["null", "undefined", "type", "validation", "object"]

    Args:
        issue_id: The ID of the issue (e.g., "err_a1b2c3d4")
        solution_description: Description of how the issue was fixed
        keywords: List of 3-5 semantic keywords/tags for search (REQUIRED)
        worked: Whether the solution actually worked (default True)

    Returns:
        Status of the operation
    """
    return resolve_issue(issue_id, solution_description, worked, keywords or [])


@mcp.tool()
def set_current_focus(focus_description: str) -> dict:
    """
    Update the AI context snapshot to describe current work focus.
    Use this when starting work on a specific task or switching focus.

    Args:
        focus_description: Short description of current focus
            (e.g., "Fixing form validation in handler.js")

    Returns:
        Confirmation status
    """
    return update_ai_context(focus_description)


@mcp.tool()
def set_project_root(root_path: str) -> dict:
    """
    Set the project root path so AI knows where to find files.
    Call this if errors show relative paths and you need to locate files.

    Args:
        root_path: Full absolute path to project root directory
            (e.g., "/Users/name/projects/my-app")

    Returns:
        Status with updated project info
    """
    from project_memory_manager import set_project_root as _set_root
    return _set_root(root_path)


@mcp.tool()
def get_active_issues() -> list:
    """
    Get list of all active (unresolved) issues.
    Issues are automatically deduplicated - same errors show as count.

    Returns:
        List of active issues with:
        - id: Unique issue identifier
        - type: Error type (console.error, NetworkError, etc.)
        - message: Error message
        - count: How many times this error occurred
        - severity: critical/error/warning
        - first_seen/last_seen: Timestamps
    """
    ctx = get_project_context()
    return ctx.get('active_issues', [])


@mcp.tool()
def search_past_solutions(query: str) -> list:
    """
    Search through solutions history for relevant past fixes.
    Use this to find how similar issues were resolved before.

    Args:
        query: Search term (matches against problem and solution text)

    Returns:
        List of matching solutions with problem, solution, and status
    """
    results = search_solutions(query)

    # Track ROI if solution found
    if results:
        try:
            from project_memory_manager import track_solution_reused
            track_solution_reused()
        except Exception:
            pass  # ROI tracking is non-critical

    return results


@mcp.tool()
def log_issue_manually(error_type: str, message: str, severity: str = "error") -> dict:
    """
    Manually log an issue to project memory.
    Use this when you identify a problem that wasn't automatically captured.

    Args:
        error_type: Type of error (e.g., "LogicError", "DesignIssue")
        message: Description of the issue
        severity: "critical", "error", or "warning"

    Returns:
        Issue ID and status
    """
    return add_or_update_issue(
        error_type=error_type,
        message=message,
        severity=severity
    )


@mcp.tool()
def get_issue_details(issue_id: str) -> dict:
    """
    Get full details of a specific issue.

    Args:
        issue_id: The issue ID to look up

    Returns:
        Full issue data or error if not found
    """
    issue = get_issue_by_id(issue_id)
    if issue:
        return issue
    return {"error": f"Issue {issue_id} not found"}


# ============================================================================
# PROJECT MEMORY: Decisions, Avoid Patterns & Handover
# ============================================================================

@mcp.tool()
def log_project_decision(decision: str, reason: str, context: str = "") -> dict:
    """
    Log an important architectural or design decision.
    Use this when making choices that future AI sessions should know about.

    Examples:
    - "Use Redux instead of Context" - "Need global state with time-travel debugging"
    - "API uses REST not GraphQL" - "Team more familiar with REST, simpler for this project"
    - "Monorepo structure" - "Shared components between web and mobile"

    Args:
        decision: What was decided (max 200 chars)
        reason: Why this decision was made (max 300 chars)
        context: Optional additional context

    Returns:
        Status and decision ID
    """
    return log_decision(decision, reason, context)


@mcp.tool()
def log_avoid_pattern(what: str, reason: str) -> dict:
    """
    Log something to AVOID in this project.
    Use this for failed attempts, bad patterns, or things that caused problems.

    Examples:
    - "Don't use moment.js" - "Too heavy, use date-fns instead"
    - "Don't query DB in loops" - "Caused N+1 problem, use batch queries"
    - "Avoid inline styles" - "Makes theming impossible, use CSS modules"

    Args:
        what: What to avoid (max 200 chars)
        reason: Why to avoid it (max 300 chars)

    Returns:
        Status and entry ID
    """
    return log_avoid(what, reason)


@mcp.tool()
def get_project_decisions() -> list:
    """
    Get all logged project decisions.
    Review these to understand past architectural choices.

    Returns:
        List of decisions with date, decision text, and reasoning
    """
    decisions = get_decisions()
    # Mark all as used by AI when retrieved and track ROI
    if decisions:
        for d in decisions:
            if d.get('id'):
                mark_decision_used(d['id'])
        try:
            from project_memory_manager import track_decision_used
            track_decision_used()
        except Exception:
            pass  # ROI tracking is non-critical
    return decisions


@mcp.tool()
def get_avoid_patterns() -> list:
    """
    Get all patterns/approaches to avoid in this project.
    Check this before suggesting solutions to avoid repeating mistakes.

    Returns:
        List of things to avoid with reasons
    """
    avoid = get_avoid_list()
    # Mark all as used by AI when retrieved and track ROI
    if avoid:
        for a in avoid:
            if a.get('id'):
                mark_avoid_used(a['id'])
        try:
            from project_memory_manager import track_error_prevented
            track_error_prevented()
        except Exception:
            pass  # ROI tracking is non-critical
    return avoid


@mcp.tool()
def create_handover(summary: str) -> dict:
    """
    Create a handover summary for the next AI session.
    Call this at the end of a work session to preserve context.

    The summary should include:
    - What was worked on
    - What was completed
    - What's still in progress
    - Any blockers or important notes

    Example:
    "Worked on user authentication. Completed: login flow, JWT setup.
     In progress: password reset (email service not configured yet).
     Note: Using bcrypt for hashing, see auth/utils.js"

    Args:
        summary: Session summary for the next AI (max 1000 chars)

    Returns:
        Confirmation status
    """
    return save_handover(summary)


@mcp.tool()
def get_last_handover() -> dict:
    """
    Get the handover summary from the last AI session.
    Check this at the start of a session to continue where the last AI left off.

    Returns:
        Last handover summary with timestamp, or None if no handover exists
    """
    handover = get_handover()

    # Track ROI if handover exists (session with context)
    if handover and handover.get('summary'):
        try:
            from project_memory_manager import track_session_with_context
            track_session_with_context()
        except Exception:
            pass  # ROI tracking is non-critical

    return handover or {"message": "No handover from previous session"}


# ============================================================================
# AUTO-HANDOVER: Exit triggers and context management
# ============================================================================

EXIT_TRIGGERS = [
    "bye", "done", "finish", "end", "stop", "quit", "exit",
    "thanks", "thank you", "night", "later", "goodbye",
    "yalla", "להתראות", "סיימתי", "תודה", "לילה טוב", "ביי"
]


@mcp.tool()
def check_session_end(user_message: str) -> dict:
    """
    Check if user message indicates session end.
    Call this to detect if you should create a handover.

    Args:
        user_message: The user's message to check

    Returns:
        Dict with should_handover (bool) and suggestion
    """
    msg_lower = user_message.lower().strip()

    # Check for exit triggers
    for trigger in EXIT_TRIGGERS:
        if trigger in msg_lower:
            return {
                "should_handover": True,
                "trigger": trigger,
                "suggestion": "User is ending session. Create a handover summary before saying goodbye."
            }

    return {
        "should_handover": False,
        "suggestion": "Session continues normally."
    }


@mcp.tool()
def get_memory_status() -> dict:
    """
    Get current memory health status.
    Use this to check if context is getting too large or stale.

    Returns:
        Dict with fullness, handover status, and recommendations
    """
    health = get_memory_health()

    recommendations = []

    # Check handover freshness
    if health['handover']['status'] == 'stale':
        recommendations.append("Handover is stale (>24h). Consider creating a new one.")
    elif health['handover']['status'] == 'empty':
        recommendations.append("No handover exists. Create one at session end.")

    # Check memory fullness
    if health['fullness_percent'] > 80:
        recommendations.append("Memory is getting full. Consider resolving old issues.")

    # Check unused decisions/avoid
    if health['decisions']['unused'] > 3:
        recommendations.append(f"{health['decisions']['unused']} decisions not used by AI. Review relevance.")

    if health['avoid']['unused'] > 2:
        recommendations.append(f"{health['avoid']['unused']} avoid patterns not used. Review relevance.")

    return {
        "health": health,
        "recommendations": recommendations,
        "status": "healthy" if len(recommendations) == 0 else "needs_attention"
    }


# ============================================================================
# SAFETY SWITCH: Preview, Approve, Undo code changes
# ============================================================================

@mcp.tool()
def preview_file_change(file_path: str, new_content: str, description: str) -> dict:
    """
    Preview a code change before applying it.
    Creates a pending change with diff for user review.

    Use this BEFORE making any file changes to give the user control.
    The change will not be applied until approved.

    Args:
        file_path: Full path to the file to change
        new_content: The new content for the file
        description: Brief description of what this change does
            (e.g., "Added null check to prevent TypeError")

    Returns:
        Dict with:
        - change_id: ID to use for approve/reject/apply
        - diff: Unified diff showing the changes
        - requires_approval: Whether user must approve before applying
    """
    try:
        from managers.safety_manager import create_pending_change
        return create_pending_change(file_path, new_content, description)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def apply_approved_change(change_id: str) -> dict:
    """
    Apply a previously approved change.
    Auto-creates backup before applying if auto_backup is enabled.

    Args:
        change_id: The change ID from preview_file_change

    Returns:
        Dict with:
        - status: ok/error
        - file_path: Path that was changed
        - backup_path: Path to backup file (for undo)
    """
    try:
        from managers.safety_manager import apply_change
        return apply_change(change_id)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def undo_last_change() -> dict:
    """
    Undo the most recent applied change.
    Restores the file from backup.

    Use this when a change caused problems and needs to be reverted.

    Returns:
        Dict with:
        - status: ok/error
        - change_id: ID of the undone change
        - file_path: Path that was restored
    """
    try:
        from managers.safety_manager import undo_last_change as _undo_last
        return _undo_last()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_pending_approvals() -> dict:
    """
    Get list of changes waiting for user approval.

    Returns:
        Dict with:
        - count: Number of pending changes
        - changes: List of pending changes with id, file_path, description, diff_preview
    """
    try:
        from managers.safety_manager import get_pending_changes
        changes = get_pending_changes()
        return {
            "count": len(changes),
            "changes": changes
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_safety_status() -> dict:
    """
    Get current safety switch settings and pending changes count.

    Returns:
        Dict with:
        - enabled: Whether safety system is active
        - auto_backup: Whether backups are created automatically
        - require_approval: Whether changes need approval
        - pending_changes_count: Number of changes awaiting approval
    """
    try:
        from managers.safety_manager import get_safety_settings
        return get_safety_settings()
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# LIVE RECORD: Real-time AI Understanding State
# ============================================================================
# The Live Record captures what the AI needs to know to continue from this point.
# Unlike handover (end of session), this updates DURING work.
# ============================================================================

@mcp.tool()
def update_live_record(section: str, data: dict) -> dict:
    """
    Update the Live Record with new understanding.
    Call this DURING work when you learn something important, not at session end.

    Sections:
    - "gps": Technical context (REPLACE mode)
        {"active_ports": [{"port": 3000, "service": "frontend"}],
         "entry_points": ["src/index.ts"],
         "environment": "dev",
         "working_dir": "/path/to/project"}

    - "architecture": Stack and flows (REPLACE mode)
        {"summary": "React + Express + MongoDB",
         "key_flows": [{"name": "Auth", "path": "login -> JWT -> routes"}]}

    - "lessons": Insights and failed attempts (APPEND mode)
        {"insight": "Project uses strict TypeScript"}
        {"failed_attempt": "axios didn't work, switched to fetch"}

    - "intent": Current developer intent (REPLACE mode)
        {"current_goal": "Implement notifications",
         "last_milestone": "Completed auth flow",
         "next_step": "Add WebSocket"}

    Call this when you:
    - Discover a technical insight
    - Try something that fails
    - Understand the architecture better
    - The developer changes focus

    Args:
        section: One of 'gps', 'architecture', 'lessons', 'intent'
        data: Section-specific data (see above)

    Returns:
        Status with updated data
    """
    try:
        from managers.project_memory_manager import update_live_record as _update
        return _update(section, data)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_live_record() -> dict:
    """
    Get the current Live Record for warm start.
    Call this at session start to continue from where you left off.

    Returns the AI's current understanding of:
    - GPS: Technical context (ports, entry points, environment)
    - Architecture: Stack summary and key flows
    - Lessons: Insights gained and failed attempts
    - Intent: Current goal, last milestone, next step

    This is your "memory" - what you knew before this session.

    Returns:
        Full live_record object with all sections
    """
    try:
        from managers.project_memory_manager import get_live_record as _get
        return _get()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def check_new_errors(minutes: int = 5) -> str:
    """
    Check for new errors that occurred recently.
    Use this when the user says they have an error, or to check if errors occurred
    during your work session.

    Args:
        minutes: How far back to look (default 5 minutes)

    Returns:
        Markdown formatted list of recent errors, or "No new errors" if none found.

    Example:
        User: "יש לי שגיאה"
        You: Call check_new_errors() to see what errors occurred
    """
    try:
        from managers.project_memory_manager import get_recent_errors

        errors = get_recent_errors(minutes=minutes, limit=10)

        if not errors:
            return f"No new errors in the last {minutes} minutes."

        lines = [f"## Recent Errors (last {minutes} min)\n"]

        for err in errors:
            severity_icon = "🔴" if err['severity'] == 'error' else "🟡"
            lines.append(f"{severity_icon} **{err['message']}**")
            if err.get('file') and err.get('line'):
                lines.append(f"   📍 {err['file']}:{err['line']}")
            if err.get('url'):
                lines.append(f"   🌐 {err['url']}")
            if err.get('count', 1) > 1:
                lines.append(f"   🔄 Occurred {err['count']} times")
            lines.append("")

        return '\n'.join(lines)
    except Exception as e:
        return f"Error checking errors: {str(e)}"


@mcp.tool()
def get_warm_start_context() -> str:
    """
    Get a complete warm start context for beginning a new session.
    Combines Live Record with other relevant memory (decisions, avoid patterns).

    Call this FIRST when starting work on a project.
    It gives you everything you need to continue intelligently.

    Returns:
        Markdown formatted context including:
        - project_status: 'new' or 'existing' (IMPORTANT - determines flow!)
        - Live Record summary
        - Key decisions
        - Patterns to avoid

    IMPORTANT: Check project_status to determine the correct flow:
    - 'new': Ask user if they want you to scan the project
    - 'existing': Show resume and ask "נמשיך מכאן?"
    """
    try:
        from managers.project_memory_manager import (
            get_live_record_summary,
            get_decisions,
            get_avoid_list,
            get_project_status,
            get_project_context
        )

        sections = []

        # Project Status (CRITICAL for flow)
        status = get_project_status()
        project = get_project_context().get('project_info', {})
        project_name = project.get('name', 'Unknown')

        sections.append(f"## Project Status: **{status.upper()}**")
        sections.append(f"Project: {project_name}")
        sections.append("")

        if status == 'new':
            sections.append("_This is a new project. Ask user: 'רוצה שאסרוק את הפרויקט?'_")
            sections.append("")
        else:
            # Live Record
            live_summary = get_live_record_summary()
            if live_summary and live_summary != "No Live Record available.":
                sections.append(live_summary)

            # Decisions (last 3)
            decisions = get_decisions()
            if decisions:
                sections.append("\n## Key Decisions")
                for d in decisions[-3:]:
                    sections.append(f"- **{d.get('decision', '')}**: {d.get('reason', '')}")

            # Avoid patterns (last 3)
            avoid = get_avoid_list()
            if avoid:
                sections.append("\n## Patterns to Avoid")
                for a in avoid[-3:]:
                    sections.append(f"- **{a.get('what', '')}**: {a.get('reason', '')}")

            sections.append("\n_This is an existing project. Show resume and ask: 'נמשיך מכאן?'_")

        return '\n'.join(sections)
    except Exception as e:
        return f"Error loading context: {str(e)}"


@mcp.tool()
def set_active_project(project_id: str) -> str:
    """
    Set the active project for this session.
    Use this at the START of a session to ensure you're working on the correct project.

    Args:
        project_id: The project ID to switch to (e.g., 'fixonce', 'localhost-5000')

    Common project IDs:
    - 'fixonce' - The FixOnce project itself
    - 'localhost-5000' - Projects running on port 5000
    - 'localhost-3000' - Projects running on port 3000

    Returns:
        Confirmation message with project details
    """
    try:
        from managers.multi_project_manager import switch_project, get_active_project

        result = switch_project(project_id, detected_from="mcp_session")

        if result.get('status') == 'ok':
            project_name = result.get('memory', {}).get('project_info', {}).get('name', project_id)
            root_path = result.get('memory', {}).get('project_info', {}).get('root_path', '')

            msg = f"✅ Switched to project: **{project_name}**"
            if root_path:
                msg += f"\n📁 Path: `{root_path}`"

            return msg
        else:
            return f"❌ Failed to switch project: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Error switching project: {str(e)}"


@mcp.tool()
def scan_project(project_path: str = "") -> str:
    """
    Scan and analyze the current project structure.
    Use this when onboarding a NEW project.

    Args:
        project_path: Path to scan. If not provided, uses project's root_path or current directory.

    This tool scans:
    - Folder structure
    - Entry points (package.json, requirements.txt, etc.)
    - Technologies and stack
    - Basic configurations

    IMPORTANT: After scanning, you MUST call update_live_record() to save:
    - gps (working_dir, environment)
    - architecture (summary, key_flows)
    - intent (current_goal: "Initial analysis / onboarding")
    - lessons (initial insight about the project)

    Returns:
        Markdown formatted scan results
    """
    try:
        import os
        import glob
        from managers.project_memory_manager import get_project_context

        # Get working directory - priority: parameter > project root_path > gps working_dir > cwd
        cwd = None

        if project_path and os.path.isdir(project_path):
            cwd = project_path
        else:
            # Try to get from project context
            context = get_project_context()
            root_path = context.get('project_info', {}).get('root_path', '')
            if root_path and os.path.isdir(root_path):
                cwd = root_path
            else:
                # Try GPS working_dir
                gps_dir = context.get('live_record', {}).get('gps', {}).get('working_dir', '')
                if gps_dir and os.path.isdir(gps_dir):
                    cwd = gps_dir

        if not cwd:
            return "Error: No valid project path found. Please provide project_path parameter or set project root_path."

        sections = []
        sections.append(f"# Project Scan Results\n")
        sections.append(f"**Path:** `{cwd}`\n")

        # Detect project info
        project_info = detect_project_info()
        if project_info.get('detected'):
            sections.append(f"**Name:** {project_info.get('name', 'Unknown')}")
            if project_info.get('stack'):
                sections.append(f"**Stack:** {', '.join(project_info.get('stack', []))}")
        sections.append("")

        # Check for common project files
        project_files = {
            'package.json': 'Node.js / JavaScript',
            'requirements.txt': 'Python',
            'pyproject.toml': 'Python (modern)',
            'Cargo.toml': 'Rust',
            'go.mod': 'Go',
            'pom.xml': 'Java (Maven)',
            'build.gradle': 'Java (Gradle)',
            'Gemfile': 'Ruby',
            'composer.json': 'PHP',
            'Makefile': 'Make-based build',
            'CMakeLists.txt': 'C/C++ (CMake)',
            'tsconfig.json': 'TypeScript',
            '.env': 'Environment config',
            'docker-compose.yml': 'Docker Compose',
            'Dockerfile': 'Docker',
        }

        found_files = []
        technologies = []

        for file, tech in project_files.items():
            if os.path.exists(os.path.join(cwd, file)):
                found_files.append(file)
                if tech not in technologies:
                    technologies.append(tech)

        if found_files:
            sections.append("## Detected Files")
            for f in found_files:
                sections.append(f"- `{f}`")
            sections.append("")

        if technologies:
            sections.append("## Technologies")
            for t in technologies:
                sections.append(f"- {t}")
            sections.append("")

        # List main directories
        sections.append("## Directory Structure")
        try:
            dirs = [d for d in os.listdir(cwd) if os.path.isdir(os.path.join(cwd, d)) and not d.startswith('.')]
            dirs = sorted(dirs)[:15]  # Limit to 15 directories
            for d in dirs:
                sections.append(f"- 📁 `{d}/`")
        except Exception:
            sections.append("_Could not read directory structure_")
        sections.append("")

        # Check for README
        readme_files = ['README.md', 'README.txt', 'README', 'readme.md']
        readme_content = None
        for rf in readme_files:
            readme_path = os.path.join(cwd, rf)
            if os.path.exists(readme_path):
                try:
                    with open(readme_path, 'r', encoding='utf-8') as f:
                        readme_content = f.read()[:1000]  # First 1000 chars
                    sections.append(f"## README Preview ({rf})")
                    sections.append(f"```\n{readme_content}\n```")
                    break
                except Exception:
                    pass

        sections.append("\n---")
        sections.append("**Next Step:** Call `update_live_record()` to save this information to the project record.")

        return '\n'.join(sections)
    except Exception as e:
        return f"Error scanning project: {str(e)}"


if __name__ == "__main__":
    # Run as standalone MCP server
    mcp.run()
