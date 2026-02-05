"""
MCP Server for NatiDebugger AI Project Memory
Exposes tools for Claude to interact with persistent project context.

Usage:
    Add to Claude Code's MCP config:
    {
        "mcpServers": {
            "nati-memory": {
                "command": "python3",
                "args": ["/path/to/mcp_memory_server.py"]
            }
        }
    }
"""

import sys
from pathlib import Path

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP
from project_memory_manager import (
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
    auto_update_project_info
)

# Create MCP server
mcp = FastMCP("nati-memory")


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


if __name__ == "__main__":
    # Run as standalone MCP server
    mcp.run()
