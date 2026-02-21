"""
OpenAI Function Calling Adapter for FixOnce.

Provides compatibility layer for OpenAI models (GPT-4, Codex, etc.)
that don't support MCP but support Function Calling.

Usage:
1. GET /openai/functions - Get function definitions for OpenAI
2. POST /openai/call - Execute a function call
3. GET /openai/context - Get current context as system prompt
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
import json

openai_bp = Blueprint('openai', __name__, url_prefix='/openai')

# ============================================================================
# OpenAI Function Definitions
# These match the MCP tools but in OpenAI's function calling format
# ============================================================================

FIXONCE_FUNCTIONS = [
    {
        "name": "fixonce_init_session",
        "description": "Initialize FixOnce session for the current project. Call this at the start of every conversation to get project context, decisions, and insights.",
        "parameters": {
            "type": "object",
            "properties": {
                "working_dir": {
                    "type": "string",
                    "description": "The absolute path to the project directory"
                }
            },
            "required": ["working_dir"]
        }
    },
    {
        "name": "fixonce_search_solutions",
        "description": "Search for past solutions in FixOnce memory. Use this BEFORE debugging any error to check if a solution already exists.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - error message, problem description, or keywords"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "fixonce_log_decision",
        "description": "Log an architectural decision that should be permanent. Use for technology choices, patterns, conventions.",
        "parameters": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "description": "The decision made (e.g., 'Use PostgreSQL for database')"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this decision was made"
                }
            },
            "required": ["decision", "reason"]
        }
    },
    {
        "name": "fixonce_log_avoid",
        "description": "Log something to avoid in the future. Use for anti-patterns, things that caused bugs.",
        "parameters": {
            "type": "object",
            "properties": {
                "what": {
                    "type": "string",
                    "description": "What to avoid"
                },
                "reason": {
                    "type": "string",
                    "description": "Why to avoid it"
                }
            },
            "required": ["what", "reason"]
        }
    },
    {
        "name": "fixonce_update_goal",
        "description": "Update the current goal/task. Call this when starting new work.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Description of the current goal"
                },
                "next_step": {
                    "type": "string",
                    "description": "Optional: what's the next step"
                }
            },
            "required": ["goal"]
        }
    },
    {
        "name": "fixonce_log_insight",
        "description": "Log a learned insight about the project. Use when discovering something important.",
        "parameters": {
            "type": "object",
            "properties": {
                "insight": {
                    "type": "string",
                    "description": "The insight learned"
                }
            },
            "required": ["insight"]
        }
    },
    {
        "name": "fixonce_get_context",
        "description": "Get the full current context including decisions, insights, and active goal.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "fixonce_get_browser_errors",
        "description": "Get recent browser errors captured by the FixOnce Chrome extension.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of errors to return (default: 10)"
                }
            },
            "required": []
        }
    }
]


# ============================================================================
# API Endpoints
# ============================================================================

@openai_bp.route('/functions', methods=['GET'])
def get_functions():
    """
    Get OpenAI-compatible function definitions.

    Use these in your OpenAI API call:
    ```python
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[...],
        functions=requests.get("http://localhost:5000/openai/functions").json()["functions"]
    )
    ```
    """
    return jsonify({
        "functions": FIXONCE_FUNCTIONS,
        "instructions": "Include these functions in your OpenAI API call. When the model wants to call a function, POST to /openai/call with the function name and arguments."
    })


@openai_bp.route('/call', methods=['POST'])
def call_function():
    """
    Execute a FixOnce function call from OpenAI.

    Request body:
    {
        "name": "fixonce_init_session",
        "arguments": {"working_dir": "/path/to/project"}
    }
    """
    data = request.get_json() or {}
    func_name = data.get('name', '')
    arguments = data.get('arguments', {})

    # Route to appropriate handler
    handlers = {
        'fixonce_init_session': _handle_init_session,
        'fixonce_search_solutions': _handle_search_solutions,
        'fixonce_log_decision': _handle_log_decision,
        'fixonce_log_avoid': _handle_log_avoid,
        'fixonce_update_goal': _handle_update_goal,
        'fixonce_log_insight': _handle_log_insight,
        'fixonce_get_context': _handle_get_context,
        'fixonce_get_browser_errors': _handle_get_browser_errors,
    }

    handler = handlers.get(func_name)
    if not handler:
        return jsonify({
            "error": f"Unknown function: {func_name}",
            "available_functions": list(handlers.keys())
        }), 400

    try:
        result = handler(arguments)
        return jsonify({
            "function": func_name,
            "result": result
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "function": func_name
        }), 500


@openai_bp.route('/context', methods=['GET'])
def get_context_prompt():
    """
    Get current context as a system prompt for OpenAI.

    Use this as the system message in your OpenAI call:
    ```python
    context = requests.get("http://localhost:5000/openai/context").json()
    messages = [
        {"role": "system", "content": context["system_prompt"]},
        {"role": "user", "content": user_message}
    ]
    ```
    """
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({
                "system_prompt": "FixOnce is available but no project is active. Call fixonce_init_session first.",
                "has_context": False
            })

        memory = load_project_memory(project_id)
        if not memory:
            return jsonify({
                "system_prompt": "FixOnce project found but no memory loaded.",
                "has_context": False
            })

        # Build system prompt
        live = memory.get('live_record', {})
        decisions = memory.get('decisions', [])
        avoid = memory.get('avoid', [])
        insights = live.get('lessons', {}).get('insights', [])
        goal = live.get('intent', {}).get('current_goal', '')
        arch = live.get('architecture', {})

        prompt_parts = ["# FixOnce Context\n"]

        if goal:
            prompt_parts.append(f"## Current Goal\n{goal}\n")

        if arch.get('summary'):
            prompt_parts.append(f"## Project\n{arch['summary']}\n")
            if arch.get('stack'):
                prompt_parts.append(f"**Stack:** {arch['stack']}\n")

        if decisions:
            prompt_parts.append("\n## Decisions (MUST FOLLOW)\n")
            for d in decisions:
                prompt_parts.append(f"- **{d.get('decision')}**: {d.get('reason')}\n")

        if avoid:
            prompt_parts.append("\n## Avoid (DO NOT DO)\n")
            for a in avoid:
                prompt_parts.append(f"- **{a.get('what')}**: {a.get('reason')}\n")

        if insights:
            prompt_parts.append("\n## Key Insights\n")
            for i in insights[:10]:  # Limit to 10
                text = i.get('text', i) if isinstance(i, dict) else i
                prompt_parts.append(f"- {text}\n")

        prompt_parts.append("\n---\n")
        prompt_parts.append("Use FixOnce functions to search solutions, log decisions, and update goals.\n")

        return jsonify({
            "system_prompt": "".join(prompt_parts),
            "has_context": True,
            "project_id": project_id,
            "decisions_count": len(decisions),
            "insights_count": len(insights)
        })

    except Exception as e:
        return jsonify({
            "system_prompt": f"FixOnce error: {str(e)}",
            "has_context": False,
            "error": str(e)
        }), 500


@openai_bp.route('/schema', methods=['GET'])
def get_openai_schema():
    """
    Get the full OpenAI-compatible schema for tools/functions.
    Compatible with both old 'functions' format and new 'tools' format.
    """
    # New tools format (GPT-4-turbo and later)
    tools = [
        {
            "type": "function",
            "function": func
        }
        for func in FIXONCE_FUNCTIONS
    ]

    return jsonify({
        "tools": tools,  # New format
        "functions": FIXONCE_FUNCTIONS,  # Old format (backwards compatibility)
        "usage": {
            "new_format": "Use 'tools' array with OpenAI API (GPT-4-turbo+)",
            "old_format": "Use 'functions' array with older OpenAI API",
            "execution": "POST function calls to /openai/call"
        }
    })


# ============================================================================
# Function Handlers
# ============================================================================

def _handle_init_session(args: dict) -> dict:
    """Handle init_session function call."""
    from managers.multi_project_manager import (
        get_or_create_project,
        set_active_project,
        load_project_memory
    )
    from core.boundary_detector import find_project_root

    working_dir = args.get('working_dir', '')
    if not working_dir:
        return {"error": "working_dir is required"}

    # Find project root
    root, marker, confidence = find_project_root(working_dir)
    if not root:
        root = working_dir

    # Get or create project
    project_id = get_or_create_project(root)
    set_active_project(project_id, detected_from="openai", working_dir=root)

    # Load memory
    memory = load_project_memory(project_id)
    if not memory:
        return {
            "status": "new_project",
            "project_id": project_id,
            "message": "New project initialized"
        }

    # Extract key info
    live = memory.get('live_record', {})
    decisions = memory.get('decisions', [])
    insights = live.get('lessons', {}).get('insights', [])

    return {
        "status": "existing_project",
        "project_id": project_id,
        "current_goal": live.get('intent', {}).get('current_goal', ''),
        "decisions": [d.get('decision') for d in decisions],
        "insights": [i.get('text', i) if isinstance(i, dict) else i for i in insights[:5]],
        "architecture": live.get('architecture', {}).get('summary', '')
    }


def _handle_search_solutions(args: dict) -> dict:
    """Handle search_solutions function call."""
    query = args.get('query', '')
    if not query:
        return {"error": "query is required"}

    try:
        from core.db_solutions import find_solution_hybrid
        results = find_solution_hybrid(query, limit=5)

        if not results:
            return {
                "found": False,
                "message": "No matching solutions found. You may investigate."
            }

        return {
            "found": True,
            "solutions": [
                {
                    "problem": r.get('problem', ''),
                    "solution": r.get('solution', ''),
                    "score": r.get('score', 0)
                }
                for r in results
            ]
        }
    except Exception as e:
        return {"error": str(e)}


def _handle_log_decision(args: dict) -> dict:
    """Handle log_decision function call."""
    decision = args.get('decision', '')
    reason = args.get('reason', '')

    if not decision or not reason:
        return {"error": "decision and reason are required"}

    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory, save_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return {"error": "No active project. Call init_session first."}

        memory = load_project_memory(project_id) or {}
        decisions = memory.setdefault('decisions', [])

        decisions.append({
            "decision": decision,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })

        save_project_memory(project_id, memory)

        return {
            "logged": True,
            "decision": decision,
            "total_decisions": len(decisions)
        }
    except Exception as e:
        return {"error": str(e)}


def _handle_log_avoid(args: dict) -> dict:
    """Handle log_avoid function call."""
    what = args.get('what', '')
    reason = args.get('reason', '')

    if not what or not reason:
        return {"error": "what and reason are required"}

    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory, save_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return {"error": "No active project. Call init_session first."}

        memory = load_project_memory(project_id) or {}
        avoid_list = memory.setdefault('avoid', [])

        avoid_list.append({
            "what": what,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })

        save_project_memory(project_id, memory)

        return {
            "logged": True,
            "what": what,
            "total_avoids": len(avoid_list)
        }
    except Exception as e:
        return {"error": str(e)}


def _handle_update_goal(args: dict) -> dict:
    """Handle update_goal function call."""
    goal = args.get('goal', '')
    next_step = args.get('next_step', '')

    if not goal:
        return {"error": "goal is required"}

    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory, save_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return {"error": "No active project. Call init_session first."}

        memory = load_project_memory(project_id) or {}
        live = memory.setdefault('live_record', {})
        intent = live.setdefault('intent', {})

        # Save old goal to history
        old_goal = intent.get('current_goal')
        if old_goal:
            history = intent.setdefault('goal_history', [])
            history.append({
                "goal": old_goal,
                "completed_at": datetime.now().isoformat()
            })

        intent['current_goal'] = goal
        intent['next_step'] = next_step
        intent['updated_at'] = datetime.now().isoformat()

        save_project_memory(project_id, memory)

        return {
            "updated": True,
            "goal": goal,
            "next_step": next_step
        }
    except Exception as e:
        return {"error": str(e)}


def _handle_log_insight(args: dict) -> dict:
    """Handle log_insight function call."""
    insight = args.get('insight', '')

    if not insight:
        return {"error": "insight is required"}

    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory, save_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return {"error": "No active project. Call init_session first."}

        memory = load_project_memory(project_id) or {}
        live = memory.setdefault('live_record', {})
        lessons = live.setdefault('lessons', {})
        insights = lessons.setdefault('insights', [])

        insights.append({
            "text": insight,
            "timestamp": datetime.now().isoformat(),
            "use_count": 0,
            "importance": "medium"
        })

        save_project_memory(project_id, memory)

        return {
            "logged": True,
            "insight": insight,
            "total_insights": len(insights)
        }
    except Exception as e:
        return {"error": str(e)}


def _handle_get_context(args: dict) -> dict:
    """Handle get_context function call."""
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return {"error": "No active project. Call init_session first."}

        memory = load_project_memory(project_id)
        if not memory:
            return {"error": "Could not load project memory"}

        live = memory.get('live_record', {})

        return {
            "project_id": project_id,
            "current_goal": live.get('intent', {}).get('current_goal', ''),
            "next_step": live.get('intent', {}).get('next_step', ''),
            "architecture": live.get('architecture', {}),
            "decisions": memory.get('decisions', []),
            "avoid": memory.get('avoid', []),
            "insights": live.get('lessons', {}).get('insights', [])[:10]
        }
    except Exception as e:
        return {"error": str(e)}


def _handle_get_browser_errors(args: dict) -> dict:
    """Handle get_browser_errors function call."""
    limit = args.get('limit', 10)

    try:
        from core.error_store import get_error_log
        errors = get_error_log()

        return {
            "errors": errors[:limit],
            "total": len(errors)
        }
    except Exception as e:
        return {"error": str(e)}
