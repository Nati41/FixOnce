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
from pathlib import Path
import json
import os
import re

openai_bp = Blueprint('openai', __name__, url_prefix='/openai')
SYNTHETIC_STRESS_RE = re.compile(r"^Test (decision|avoid|insight) #\d+ from thread \d+$")

# ============================================================================
# OpenAI Function Definitions
# These match the MCP tools but in OpenAI's function calling format
# ============================================================================

FIXONCE_FUNCTIONS = [
    {
        "name": "fixonce_init_session",
        "description": "Initialize FixOnce session. Returns a 'display' field - show it to the user verbatim.",
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
    },
    # === MCP Fallback Functions (for MCP disconnect scenarios) ===
    {
        "name": "fixonce_status",
        "description": "Check FixOnce connection and recording status. Use to verify recording before commits.",
        "parameters": {
            "type": "object",
            "properties": {
                "cwd": {
                    "type": "string",
                    "description": "Absolute path to the project working directory. Required for accurate project-specific status."
                }
            },
            "required": []
        }
    },
    {
        "name": "fixonce_sync",
        "description": "Sync work context with FixOnce. Call after changes or when starting new work.",
        "parameters": {
            "type": "object",
            "properties": {
                "cwd": {
                    "type": "string",
                    "description": "REQUIRED: Absolute path to the project working directory"
                },
                "goal": {
                    "type": "string",
                    "description": "Current goal (e.g., 'Fix login bug')"
                },
                "work_area": {
                    "type": "string",
                    "description": "Feature/module area (e.g., 'authentication')"
                },
                "last_change": {
                    "type": "string",
                    "description": "What was just done (e.g., 'Added validation')"
                },
                "last_file": {
                    "type": "string",
                    "description": "Last file modified"
                },
                "why": {
                    "type": "string",
                    "description": "Why this work matters"
                },
                "next_step": {
                    "type": "string",
                    "description": "Short continuation prompt (e.g., 'Test the fix')"
                }
            },
            "required": ["cwd"]
        }
    },
    {
        "name": "fixonce_solved",
        "description": "Record that you fixed an error. Saves solution for future use. Supports review/resolution for conflicts.",
        "parameters": {
            "type": "object",
            "properties": {
                "cwd": {
                    "type": "string",
                    "description": "REQUIRED: Absolute path to the project working directory"
                },
                "error": {
                    "type": "string",
                    "description": "The error message that was fixed"
                },
                "solution": {
                    "type": "string",
                    "description": "What you did to fix it (1-2 sentences)"
                },
                "files": {
                    "type": "string",
                    "description": "Comma-separated list of files changed"
                },
                "resolution_action": {
                    "type": "string",
                    "description": "Action to resolve a conflict: 'supersede_existing' or 'cancel'"
                },
                "resolution_target_id": {
                    "type": "string",
                    "description": "ID of existing solution for supersede_existing"
                },
                "resolution_review_id": {
                    "type": "string",
                    "description": "Review ID from initial conflict response"
                }
            },
            "required": ["cwd", "error", "solution"]
        }
    },
    {
        "name": "fixonce_decide",
        "description": "Record a decision, avoid pattern, or resolve a decision conflict. Full MCP parity with pre-save review.",
        "parameters": {
            "type": "object",
            "properties": {
                "cwd": {
                    "type": "string",
                    "description": "REQUIRED: Absolute path to the project working directory"
                },
                "text": {
                    "type": "string",
                    "description": "The decision or avoid text"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this decision was made"
                },
                "action": {
                    "type": "string",
                    "description": "One of: 'add' (default), 'avoid', 'resolve:acknowledge_existing:TARGET_ID', 'resolve:save_as_extends:TARGET_ID', 'resolve:save_as_exception:TARGET_ID', 'resolve:supersede_existing:TARGET_ID', 'resolve:save_anyway_under_review:TARGET_ID', 'resolve:cancel'"
                }
            },
            "required": ["cwd", "text", "reason"]
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
        'fixonce_log_decision': _handle_log_decision,  # Legacy - use fixonce_decide
        'fixonce_log_avoid': _handle_log_avoid,  # Legacy - use fixonce_decide with action='avoid'
        'fixonce_update_goal': _handle_update_goal,
        'fixonce_log_insight': _handle_log_insight,
        'fixonce_get_context': _handle_get_context,
        'fixonce_get_browser_errors': _handle_get_browser_errors,
        # MCP Fallback functions (full parity with MCP tools)
        'fixonce_status': _handle_status,
        'fixonce_sync': _handle_sync,
        'fixonce_solved': _handle_solved,
        'fixonce_decide': _handle_decide,
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
        project_rules = memory.get('project_rules', [])
        enabled_rules = [r for r in project_rules if r.get('enabled', True)]

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

        if enabled_rules:
            prompt_parts.append("\n## Project Rules (FOLLOW THESE)\n")
            for r in enabled_rules:
                prompt_parts.append(f"- {r.get('text')}\n")

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

def _is_isolated_user_data_dir() -> bool:
    override = os.environ.get("FIXONCE_USER_DATA_DIR", "").strip()
    if not override:
        return False

    try:
        return Path(override).expanduser().resolve() != (Path.home() / ".fixonce").resolve()
    except OSError:
        return True


def _is_synthetic_stress_payload(args: dict) -> bool:
    for key in ("decision", "what", "insight"):
        value = args.get(key)
        if isinstance(value, str) and SYNTHETIC_STRESS_RE.match(value):
            return True
    return False


def _allows_synthetic_stress_writes(memory: dict) -> bool:
    project_info = memory.get("project_info", {}) if isinstance(memory, dict) else {}
    provenance = str(project_info.get("provenance", "")).lower()
    working_dir = str(project_info.get("working_dir", "")).lower()

    if provenance == "test":
        return True
    if "fixonce-stress" in working_dir or "fixonce_stress_test_project" in working_dir:
        return True
    return os.environ.get("FIXONCE_RUN_STRESS") == "1" and _is_isolated_user_data_dir()


def _reject_synthetic_stress_write(args: dict, memory: dict):
    if not _is_synthetic_stress_payload(args):
        return None
    if _allows_synthetic_stress_writes(memory):
        return None
    return {
        "error": (
            "Synthetic stress-test memory payload rejected. "
            "Run stress tests with FIXONCE_RUN_STRESS=1 against isolated test storage."
        )
    }


def _handle_init_session(args: dict) -> dict:
    """Handle init_session function call."""
    from managers.multi_project_manager import (
        ensure_dashboard_project,
        load_project_memory
    )
    from core.boundary_detector import find_project_root
    from core.project_context import ProjectContext
    from core.windows_subprocess import no_window_creationflags
    import subprocess

    working_dir = args.get('working_dir', '')
    if not working_dir:
        return {"error": "working_dir is required"}

    # Find project root
    root, marker, confidence = find_project_root(working_dir)
    if not root:
        root = working_dir

    # Use ProjectContext for consistent ID generation (respects git remote)
    project_id = ProjectContext.from_path(root)
    ensure_dashboard_project(project_id, detected_from="openai", working_dir=root)

    # Get git hash
    git_hash = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=root, timeout=5,
            creationflags=no_window_creationflags(),
        )
        if result.returncode == 0:
            git_hash = result.stdout.strip()[:12]
    except:
        pass

    # Load memory
    memory = load_project_memory(project_id)
    if not memory:
        # New project - use clean format
        try:
            from core.resume_context import build_new_project_opening
            opening = build_new_project_opening(
                project_name=project_id.split('_')[0],
                working_dir=root,
                language='he'
            )
        except:
            opening = f"🧠 FixOnce | New Project\n📍 {root}\n🎯 What's the goal?"

        return {
            "display": opening,
            "project_id": project_id,
            "status": "new"
        }

    # Existing project - build clean opening
    try:
        from core.resume_context import build_resume_context, build_suggested_opening
        context = build_resume_context(memory, root, git_hash)
        opening = build_suggested_opening(context, language='he')
    except Exception as e:
        # Fallback
        opening = f"🧠 FixOnce | {project_id}\n📍 {root}\nError building context: {e}"

    # Extract key info for structured response
    live = memory.get('live_record', {})
    decisions = memory.get('decisions', [])
    avoid = memory.get('avoid', [])
    insights = live.get('lessons', {}).get('insights', [])
    project_rules = memory.get('project_rules', [])
    enabled_rules = [r.get('text') for r in project_rules if r.get('enabled', True)]

    # Return ONLY the opening - nothing else for Codex to reformat
    return {
        "display": opening,
        "project_id": project_id,
        "status": "ready"
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
    """
    Handle log_decision function call (LEGACY - routes through core service).

    Now uses the same core.decisions.record_decision() as fixonce_decide
    to ensure review/conflict detection applies.
    REQUIRES explicit cwd for REST fallback.
    """
    cwd = args.get('cwd', '').strip()
    decision = args.get('decision', '')
    reason = args.get('reason', '')

    if not decision or not reason:
        return {"error": "decision and reason are required"}

    # Route through the same core service as fixonce_decide
    result = _handle_decide({
        "cwd": cwd,
        "text": decision,
        "reason": reason,
        "action": "add",
    })

    # Convert to legacy response format for backwards compatibility
    if result.get("success"):
        return {
            "logged": True,
            "decision": decision,
            "decision_id": result.get("decision_id"),
        }
    elif result.get("requires_review"):
        # Return review info in legacy-compatible format
        return {
            "logged": False,
            "requires_review": True,
            "relationship": result.get("relationship"),
            "target_id": result.get("target_id"),
            "target_text": result.get("target_text"),
            "allowed_actions": result.get("allowed_actions"),
            "message": result.get("message"),
        }
    else:
        return {"error": result.get("error", "Decision failed")}


def _handle_log_avoid(args: dict) -> dict:
    """
    Handle log_avoid function call (LEGACY - routes through core service).

    Now uses the same core.decisions.record_avoid() as fixonce_decide(action="avoid")
    to ensure proper actor attribution and storage.
    REQUIRES explicit cwd for REST fallback.
    """
    cwd = args.get('cwd', '').strip()
    what = args.get('what', '')
    reason = args.get('reason', '')

    if not what or not reason:
        return {"error": "what and reason are required"}

    # Route through the same core service as fixonce_decide
    result = _handle_decide({
        "cwd": cwd,
        "text": what,
        "reason": reason,
        "action": "avoid",
    })

    # Convert to legacy response format for backwards compatibility
    if result.get("success"):
        return {
            "logged": True,
            "what": what,
            "decision_id": result.get("decision_id"),
        }
    else:
        return {"error": result.get("error", "Avoid pattern failed")}


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
        rejected = _reject_synthetic_stress_write(args, memory)
        if rejected:
            return rejected

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
        project_rules = memory.get('project_rules', [])
        enabled_rules = [r for r in project_rules if r.get('enabled', True)]

        return {
            "project_id": project_id,
            "current_goal": live.get('intent', {}).get('current_goal', ''),
            "next_step": live.get('intent', {}).get('next_step', ''),
            "architecture": live.get('architecture', {}),
            "decisions": memory.get('decisions', []),
            "project_rules": enabled_rules,
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


# ============================================================================
# MCP Fallback Handlers
# These call the SAME core functions as MCP tools for full parity.
# ============================================================================


def _resolve_project_from_cwd(cwd: str) -> dict:
    """
    Resolve project ID from explicit cwd path.

    Returns dict with:
    - success: bool
    - project_id: str (if success)
    - resolved_cwd: str (normalized path)
    - error: str (if not success)
    - error_code: str (if not success)

    This ensures REST fallback writes ONLY to the explicitly specified project,
    never to the server's global active project state.
    """
    if not cwd:
        return {
            "success": False,
            "error": "cwd is required for REST fallback. Provide the absolute path to your project working directory.",
            "error_code": "missing_cwd",
        }

    cwd = cwd.strip()
    if not cwd:
        return {
            "success": False,
            "error": "cwd cannot be empty",
            "error_code": "empty_cwd",
        }

    # Normalize path
    try:
        from pathlib import Path
        cwd_path = Path(cwd).expanduser().resolve()
        if not cwd_path.exists():
            return {
                "success": False,
                "error": f"cwd path does not exist: {cwd}",
                "error_code": "invalid_cwd",
            }
        if not cwd_path.is_dir():
            return {
                "success": False,
                "error": f"cwd is not a directory: {cwd}",
                "error_code": "invalid_cwd",
            }
        resolved_cwd = str(cwd_path)
    except Exception as e:
        return {
            "success": False,
            "error": f"Invalid cwd path: {e}",
            "error_code": "invalid_cwd",
        }

    # Find project root using boundary detector
    try:
        from core.boundary_detector import find_project_root
        root, marker, confidence = find_project_root(resolved_cwd)
        if not root:
            root = resolved_cwd
    except Exception:
        root = resolved_cwd

    # Use ProjectContext for consistent ID generation (respects git remote)
    try:
        from core.project_context import ProjectContext
        project_id = ProjectContext.from_path(root)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to resolve project ID: {e}",
            "error_code": "project_resolution_failed",
        }

    # Ensure project exists in dashboard
    try:
        from managers.multi_project_manager import ensure_dashboard_project
        ensure_dashboard_project(project_id, detected_from="rest_fallback", working_dir=root)
    except Exception:
        pass  # Non-fatal - project may already exist

    return {
        "success": True,
        "project_id": project_id,
        "resolved_cwd": root,
    }


def _verify_project_id_matches_cwd(supplied_project_id: str, resolved_project_id: str) -> dict:
    """
    Verify that a supplied project_id matches the cwd-resolved one.

    Returns None if match or no supplied_project_id, error dict if mismatch.
    """
    if not supplied_project_id:
        return None

    if supplied_project_id != resolved_project_id:
        return {
            "success": False,
            "error": f"project_id mismatch: supplied '{supplied_project_id}' but cwd resolves to '{resolved_project_id}'",
            "error_code": "project_id_mismatch",
        }

def _log_rest_fallback_activity(
    action: str,
    project_id: str,
    details: dict = None,
) -> None:
    """Log REST fallback activity for dashboard tracking."""
    try:
        import requests
        from pathlib import Path

        # Get runtime port
        runtime_file = Path.home() / ".fixonce" / "runtime.json"
        port = 5000
        if runtime_file.exists():
            import json
            with open(runtime_file, 'r', encoding='utf-8') as f:
                port = json.load(f).get("port", 5000)

        requests.post(
            f"http://localhost:{port}/api/activity/log",
            json={
                "type": "rest_fallback",
                "tool": action,
                "human_name": f"REST fallback: {action}",
                "project_id": project_id,
                "actor": "rest_fallback",
                "actor_source": "rest_api",
                "details": details or {},
            },
            timeout=2,
        )
    except Exception:
        pass


def _handle_status(args: dict) -> dict:
    """
    Handle status check - REST fallback for fo_status.

    If cwd is provided, resolves the project from cwd and reports status for that project.
    If cwd is omitted, returns a warning that status is ambiguous without explicit cwd.

    Returns structured JSON for machine parsing.
    """
    cwd = args.get('cwd', '').strip()

    try:
        if cwd:
            # Resolve project from explicit cwd
            resolution = _resolve_project_from_cwd(cwd)
            if not resolution["success"]:
                return {
                    "success": False,
                    "action": "fixonce_status",
                    "recording": False,
                    "transport": "rest_fallback",
                    "error": resolution["error"],
                    "error_code": resolution["error_code"],
                }

            project_id = resolution["project_id"]
            resolved_cwd = resolution["resolved_cwd"]

            return {
                "success": True,
                "action": "fixonce_status",
                "recording": True,
                "transport": "rest_fallback",
                "project_id": project_id,
                "resolved_cwd": resolved_cwd,
                "message": f"FixOnce can record to project {project_id} via REST fallback.",
            }
        else:
            # No cwd provided - warn about ambiguity
            return {
                "success": True,
                "action": "fixonce_status",
                "recording": True,
                "transport": "rest_fallback",
                "project_id": None,
                "warning": "No cwd provided. Include cwd parameter to verify status for your specific project. Write operations require explicit cwd.",
                "message": "FixOnce REST fallback is available. Provide cwd to verify project-specific recording.",
            }

    except Exception as e:
        return {
            "success": False,
            "action": "fixonce_status",
            "recording": False,
            "transport": "rest_fallback",
            "error": str(e),
            "error_code": "status_check_failed",
        }


def _handle_sync(args: dict) -> dict:
    """
    Handle sync - REST fallback for fo_sync.

    REQUIRES explicit cwd to prevent cross-project writes.
    Calls the same core function as MCP fo_sync for full parity.
    """
    cwd = args.get('cwd', '').strip()
    goal = args.get('goal', '')
    work_area = args.get('work_area', '')
    last_change = args.get('last_change', '')
    last_file = args.get('last_file', '')
    why = args.get('why', '')
    next_step = args.get('next_step', '')

    # Require explicit cwd for REST fallback writes
    resolution = _resolve_project_from_cwd(cwd)
    if not resolution["success"]:
        return {
            "success": False,
            "action": "fixonce_sync",
            "error": resolution["error"],
            "error_code": resolution["error_code"],
        }

    project_id = resolution["project_id"]

    try:
        from managers.multi_project_manager import (
            load_project_memory,
            save_project_memory,
        )

        memory = load_project_memory(project_id) or {}
        live = memory.setdefault('live_record', {})
        intent = live.setdefault('intent', {})

        # Update all sync fields (same as MCP fo_sync)
        now = datetime.now()

        if goal:
            old_goal = intent.get('current_goal')
            if old_goal and old_goal != goal:
                history = intent.setdefault('goal_history', [])
                history.append({
                    "goal": old_goal,
                    "completed_at": now.isoformat()
                })
            intent['current_goal'] = goal

        if work_area:
            intent['work_area'] = work_area
        if last_change:
            intent['last_change'] = last_change
            intent['last_change_at'] = now.isoformat()
        if last_file:
            intent['last_file'] = last_file
        if why:
            intent['why'] = why
        if next_step:
            intent['next_step'] = next_step

        intent['updated_at'] = now.isoformat()
        intent['synced_via'] = 'rest_fallback'

        save_project_memory(project_id, memory)

        # Log activity for dashboard
        _log_rest_fallback_activity("sync", project_id, {
            "goal": goal[:50] if goal else None,
            "last_change": last_change[:50] if last_change else None,
        })

        return {
            "success": True,
            "action": "fixonce_sync",
            "message": "Context synced via REST fallback.",
            "transport": "rest_fallback",
            "project_id": project_id,
            "resolved_cwd": resolution["resolved_cwd"],
            "synced_fields": {
                "goal": bool(goal),
                "work_area": bool(work_area),
                "last_change": bool(last_change),
                "last_file": bool(last_file),
                "why": bool(why),
                "next_step": bool(next_step),
            },
        }
    except Exception as e:
        return {
            "success": False,
            "action": "fixonce_sync",
            "error": str(e),
            "error_code": "sync_failed",
        }


def _handle_solved(args: dict) -> dict:
    """
    Handle solved - REST fallback for fo_solved.

    REQUIRES explicit cwd to prevent cross-project writes.
    Calls core.solutions.record_solution() for full parity with MCP,
    including pre-save review and resolution actions.
    """
    cwd = args.get('cwd', '').strip()
    error_msg = args.get('error', '')
    solution = args.get('solution', '')
    files = args.get('files', '')
    resolution_action = args.get('resolution_action', '')
    resolution_target_id = args.get('resolution_target_id', '')
    resolution_review_id = args.get('resolution_review_id', '')

    # Require explicit cwd for REST fallback writes
    resolution = _resolve_project_from_cwd(cwd)
    if not resolution["success"]:
        return {
            "success": False,
            "action": "fixonce_solved",
            "error": resolution["error"],
            "error_code": resolution["error_code"],
        }

    if not error_msg:
        return {
            "success": False,
            "action": "fixonce_solved",
            "error": "error is required",
            "error_code": "missing_error",
        }

    if not solution:
        return {
            "success": False,
            "action": "fixonce_solved",
            "error": "solution is required",
            "error_code": "missing_solution",
        }

    # Validate resolution_action if provided
    if resolution_action:
        valid_actions = {"supersede_existing", "cancel"}
        if resolution_action not in valid_actions:
            return {
                "success": False,
                "action": "fixonce_solved",
                "error": f"Invalid resolution_action '{resolution_action}'. Must be one of: {', '.join(sorted(valid_actions))}",
                "error_code": "invalid_resolution_action",
            }

        if resolution_action == "supersede_existing" and not resolution_target_id:
            return {
                "success": False,
                "action": "fixonce_solved",
                "error": "resolution_target_id is required for supersede_existing",
                "error_code": "missing_target_id",
            }

        if not resolution_review_id:
            return {
                "success": False,
                "action": "fixonce_solved",
                "error": "resolution_review_id is required for resolution actions. Call fixonce_solved without resolution_action first to get a review_id.",
                "error_code": "missing_review_id",
            }

    project_id = resolution["project_id"]

    try:
        from core.solutions import record_solution

        files_list = [f.strip() for f in files.split(",") if f.strip()] if files else []

        # Call the SAME core function as MCP fo_solved
        result = record_solution(
            project_id=project_id,
            error_message=error_msg,
            solution=solution,
            files_changed=files_list,
            actor="rest_fallback",
            actor_source="rest_api",
            resolution_action=resolution_action,
            resolution_target_id=resolution_target_id,
            resolution_review_id=resolution_review_id,
        )

        if result.requires_review and result.review_result:
            # Return structured review response
            review = result.review_result
            primary = review.get("primary_candidate", {})

            return {
                "success": False,
                "action": "fixonce_solved",
                "requires_review": True,
                "relationship": primary.get("relationship", "unknown"),
                "review_id": review.get("review_id", ""),
                "target_id": primary.get("id", ""),
                "target_text": primary.get("text", "")[:100],
                "explanation": primary.get("explanation", ""),
                "allowed_actions": review.get("allowed_actions", []),
                "expires_at": review.get("expires_at", ""),
                "message": "Solution not logged; review required.",
                "error_code": "review_required",
            }

        if not result.success:
            return {
                "success": False,
                "action": "fixonce_solved",
                "error": result.message,
                "error_code": "solution_failed",
            }

        # Log activity for dashboard
        _log_rest_fallback_activity("solved", project_id, {
            "error": error_msg[:50],
            "is_update": result.is_update,
        })

        return {
            "success": True,
            "action": "fixonce_solved",
            "message": result.message,
            "solution_id": result.solution_id,
            "is_update": result.is_update,
            "transport": "rest_fallback",
            "project_id": project_id,
            "resolved_cwd": resolution["resolved_cwd"],
        }

    except Exception as e:
        return {
            "success": False,
            "action": "fixonce_solved",
            "error": str(e),
            "error_code": "exception",
        }


def _handle_decide(args: dict) -> dict:
    """
    Handle decide - REST fallback for fo_decide.

    REQUIRES explicit cwd to prevent cross-project writes.
    Calls core.decisions.record_decision() or record_avoid() for full parity
    with MCP, including pre-save review and resolution actions.

    Action parsing mirrors MCP fo_decide:
    - "add" (default): Add new decision (may trigger review)
    - "avoid": Add as avoid pattern
    - "resolve:ACTION:TARGET_ID": Resolve review with action
    """
    cwd = args.get('cwd', '').strip()
    text = args.get('text', '')
    reason = args.get('reason', '')
    action = args.get('action', 'add').strip()

    # Require explicit cwd for REST fallback writes
    resolution = _resolve_project_from_cwd(cwd)
    if not resolution["success"]:
        return {
            "success": False,
            "action": "fixonce_decide",
            "error": resolution["error"],
            "error_code": resolution["error_code"],
        }

    project_id = resolution["project_id"]
    resolved_cwd = resolution["resolved_cwd"]

    if not text:
        return {
            "success": False,
            "action": "fixonce_decide",
            "error": "text is required",
            "error_code": "missing_text",
        }

    if not reason:
        return {
            "success": False,
            "action": "fixonce_decide",
            "error": "reason is required",
            "error_code": "missing_reason",
        }

    try:
        # Parse action (mirrors MCP fo_decide action parsing)
        if action == "avoid":
            return _handle_decide_avoid(project_id, text, reason, resolved_cwd)

        if action.startswith("resolve:"):
            return _handle_decide_resolution(project_id, text, reason, action, resolved_cwd)

        # Default: add new decision
        return _handle_decide_add(project_id, text, reason, resolved_cwd)

    except Exception as e:
        return {
            "success": False,
            "action": "fixonce_decide",
            "error": str(e),
            "error_code": "exception",
        }


def _handle_decide_add(project_id: str, text: str, reason: str, resolved_cwd: str) -> dict:
    """Add a new decision using core service."""
    from core.decisions import record_decision

    result = record_decision(
        project_id=project_id,
        text=text,
        reason=reason,
        actor="rest_fallback",
        actor_source="rest_api",
    )

    if result.requires_review and result.review_result:
        review = result.review_result
        primary = review.get("primary_candidate", {})

        return {
            "success": False,
            "action": "fixonce_decide",
            "requires_review": True,
            "relationship": primary.get("relationship", "unknown"),
            "target_id": primary.get("id", ""),
            "target_text": primary.get("text", "")[:100],
            "explanation": primary.get("explanation", ""),
            "allowed_actions": review.get("allowed_actions", []),
            "message": review.get("message", "Decision review required."),
            "error_code": "review_required",
        }

    if not result.success:
        return {
            "success": False,
            "action": "fixonce_decide",
            "error": result.message,
            "conflicts": result.conflicts,
            "error_code": "decision_blocked",
        }

    _log_rest_fallback_activity("decide", project_id, {"text": text[:50]})

    return {
        "success": True,
        "action": "fixonce_decide",
        "message": result.message,
        "decision_id": result.decision_id,
        "transport": "rest_fallback",
        "project_id": project_id,
        "resolved_cwd": resolved_cwd,
        "warning": result.warning if result.warning else None,
    }


def _handle_decide_avoid(project_id: str, text: str, reason: str, resolved_cwd: str) -> dict:
    """Add an avoid pattern using core service."""
    from core.decisions import record_avoid

    result = record_avoid(
        project_id=project_id,
        text=text,
        reason=reason,
        actor="rest_fallback",
        actor_source="rest_api",
    )

    if not result.success:
        return {
            "success": False,
            "action": "fixonce_decide",
            "error": result.message,
            "error_code": "avoid_failed",
        }

    _log_rest_fallback_activity("decide_avoid", project_id, {"text": text[:50]})

    return {
        "success": True,
        "action": "fixonce_decide",
        "message": result.message,
        "decision_id": result.decision_id,
        "transport": "rest_fallback",
        "project_id": project_id,
        "resolved_cwd": resolved_cwd,
    }


def _handle_decide_resolution(project_id: str, text: str, reason: str, action: str, resolved_cwd: str) -> dict:
    """Resolve a decision review using core service."""
    from core.decisions import record_decision

    # Parse resolve action: resolve:ACTION:TARGET or resolve:ACTION
    parts = action[len("resolve:"):].split(":", 1)
    resolution_action = parts[0].strip()
    target_id = parts[1].strip() if len(parts) > 1 else ""

    valid_resolutions = {
        "acknowledge_existing",
        "save_as_extends",
        "save_as_exception",
        "supersede_existing",
        "save_anyway_under_review",
        "cancel",
    }

    if resolution_action not in valid_resolutions:
        return {
            "success": False,
            "action": "fixonce_decide",
            "error": f"Invalid resolution action '{resolution_action}'. Must be one of: {', '.join(sorted(valid_resolutions))}",
            "error_code": "invalid_resolution_action",
        }

    # Most resolutions require target_id
    if resolution_action != "cancel" and not target_id:
        return {
            "success": False,
            "action": "fixonce_decide",
            "error": f"target_id is required for {resolution_action}",
            "error_code": "missing_target_id",
        }

    result = record_decision(
        project_id=project_id,
        text=text,
        reason=reason,
        actor="rest_fallback",
        actor_source="rest_api",
        resolution_action=resolution_action,
        resolution_target_id=target_id,
    )

    if not result.success:
        return {
            "success": False,
            "action": "fixonce_decide",
            "error": result.message,
            "error_code": "resolution_failed",
        }

    _log_rest_fallback_activity("decide_resolution", project_id, {
        "resolution": resolution_action,
        "target_id": target_id,
    })

    return {
        "success": True,
        "action": "fixonce_decide",
        "message": result.message,
        "decision_id": result.decision_id,
        "resolution_action": resolution_action,
        "transport": "rest_fallback",
        "project_id": project_id,
        "resolved_cwd": resolved_cwd,
    }
