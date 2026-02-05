"""
Project Memory Manager for NatiDebugger AI Memory System
Handles persistent project context for AI sessions.
"""

import json
import hashlib
import threading
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Path to the project memory file
MEMORY_FILE = Path(__file__).parent / "project_memory.json"

# Project root detection (look for common project markers)
PROJECT_MARKERS = [
    "package.json", "pyproject.toml", "requirements.txt",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
    ".git", "Makefile", "CMakeLists.txt"
]


# ============================================================================
# AUTO DETECTION: Project Info from filesystem
# ============================================================================

def detect_project_info(project_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Auto-detect project name and stack from filesystem.

    Args:
        project_path: Path to scan. If None, uses current working directory.

    Returns:
        Dict with name, stack (list), and detected (bool)
    """
    if project_path is None:
        # Try to find project root by looking for markers
        project_path = _find_project_root()

    if project_path is None:
        return {"name": "Unknown Project", "stack": [], "detected": False}

    info = {
        "name": project_path.name,
        "stack": [],
        "detected": True,
        "path": str(project_path)
    }

    # JavaScript/TypeScript ecosystem
    pkg_json = project_path / "package.json"
    if pkg_json.exists():
        try:
            with open(pkg_json, 'r', encoding='utf-8') as f:
                pkg = json.load(f)

            # Get project name from package.json if available
            if pkg.get("name"):
                info["name"] = pkg["name"]

            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

            # Detect frameworks
            if "next" in deps:
                info["stack"].append("Next.js")
            elif "react" in deps:
                info["stack"].append("React")
            elif "vue" in deps:
                info["stack"].append("Vue")
            elif "svelte" in deps:
                info["stack"].append("Svelte")
            elif "angular" in deps or "@angular/core" in deps:
                info["stack"].append("Angular")

            # Backend frameworks
            if "express" in deps:
                info["stack"].append("Express")
            if "fastify" in deps:
                info["stack"].append("Fastify")
            if "nestjs" in deps or "@nestjs/core" in deps:
                info["stack"].append("NestJS")

            # TypeScript
            if "typescript" in deps or (project_path / "tsconfig.json").exists():
                info["stack"].append("TypeScript")
            elif not info["stack"] or "Next.js" not in info["stack"]:
                info["stack"].append("Node.js")

        except (json.JSONDecodeError, IOError):
            info["stack"].append("Node.js")

    # Python ecosystem
    pyproject = project_path / "pyproject.toml"
    requirements = project_path / "requirements.txt"

    if pyproject.exists() or requirements.exists():
        info["stack"].append("Python")

        # Read requirements for framework detection
        reqs_text = ""
        if requirements.exists():
            try:
                reqs_text = requirements.read_text().lower()
            except IOError:
                pass

        if pyproject.exists():
            try:
                reqs_text += pyproject.read_text().lower()
            except IOError:
                pass

        if "django" in reqs_text:
            info["stack"].append("Django")
        elif "fastapi" in reqs_text:
            info["stack"].append("FastAPI")
        elif "flask" in reqs_text:
            info["stack"].append("Flask")

        if "pytest" in reqs_text:
            info["stack"].append("pytest")

    # Rust
    if (project_path / "Cargo.toml").exists():
        info["stack"].append("Rust")

    # Go
    if (project_path / "go.mod").exists():
        info["stack"].append("Go")

    # Java
    if (project_path / "pom.xml").exists():
        info["stack"].append("Java/Maven")
    elif (project_path / "build.gradle").exists():
        info["stack"].append("Java/Gradle")

    # Docker
    if (project_path / "Dockerfile").exists() or (project_path / "docker-compose.yml").exists():
        info["stack"].append("Docker")

    return info


def _find_project_root(start_path: Optional[Path] = None) -> Optional[Path]:
    """
    Find project root by searching upward for project markers.
    """
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()

    # Search up to 10 levels
    for _ in range(10):
        for marker in PROJECT_MARKERS:
            if (current / marker).exists():
                return current

        parent = current.parent
        if parent == current:  # Reached root
            break
        current = parent

    return start_path  # Fallback to start path


def auto_update_project_info() -> Dict[str, Any]:
    """
    Auto-detect and update project info if not already set.
    Only updates if current info is default/empty.

    Returns:
        Dict with status and detected info
    """
    with _lock:
        memory = _load_memory()
        info = memory['project_info']

        # Only auto-update if using defaults
        if info['name'] == "My Project" and not info['stack']:
            detected = detect_project_info()

            if detected['detected']:
                memory['project_info']['name'] = detected['name']
                memory['project_info']['stack'] = ", ".join(detected['stack'])
                memory['project_info']['root_path'] = detected.get('path', '')
                _save_memory(memory)

                return {
                    "status": "updated",
                    "name": detected['name'],
                    "stack": detected['stack'],
                    "message": "Project info auto-detected"
                }

        return {
            "status": "unchanged",
            "name": info['name'],
            "stack": info['stack'],
            "message": "Project info already set"
        }


def set_project_root(root_path: str) -> Dict[str, Any]:
    """
    Manually set the project root path.

    Args:
        root_path: Full path to project root directory

    Returns:
        Status dict
    """
    with _lock:
        memory = _load_memory()

        # Validate path exists
        path = Path(root_path)
        if not path.exists():
            return {"status": "error", "message": f"Path does not exist: {root_path}"}
        if not path.is_dir():
            return {"status": "error", "message": f"Path is not a directory: {root_path}"}

        memory['project_info']['root_path'] = str(path.resolve())

        # Also try to detect name and stack if not set
        if memory['project_info']['name'] == "My Project":
            detected = detect_project_info(path)
            if detected['detected']:
                memory['project_info']['name'] = detected['name']
                memory['project_info']['stack'] = ", ".join(detected['stack'])

        _save_memory(memory)

        return {
            "status": "ok",
            "root_path": memory['project_info']['root_path'],
            "name": memory['project_info']['name'],
            "stack": memory['project_info']['stack']
        }


def get_project_root() -> Optional[str]:
    """Get the current project root path."""
    with _lock:
        memory = _load_memory()
        return memory['project_info'].get('root_path', '')


# Thread lock for file operations
_lock = threading.Lock()


def _generate_issue_id(error_type: str, message: str) -> str:
    """Generate a unique ID for an issue based on type and message."""
    # Create hash from type + normalized message (first 100 chars)
    normalized = f"{error_type}:{message[:100].lower().strip()}"
    return "err_" + hashlib.md5(normalized.encode()).hexdigest()[:8]


def _load_memory() -> Dict[str, Any]:
    """Load project memory from JSON file."""
    if not MEMORY_FILE.exists():
        return _create_default_memory()

    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return _create_default_memory()


def _save_memory(memory: Dict[str, Any]) -> bool:
    """Save project memory to JSON file."""
    try:
        memory['stats']['last_updated'] = datetime.now().isoformat()
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        print(f"[ProjectMemory] Save error: {e}")
        return False


def save_memory(memory: Dict[str, Any]) -> bool:
    """Public wrapper for saving memory."""
    with _lock:
        return _save_memory(memory)


def _create_default_memory() -> Dict[str, Any]:
    """Create default memory structure."""
    return {
        "project_info": {
            "name": "My Project",
            "stack": "",
            "status": "Active",
            "description": "",
            "root_path": ""  # Full path to project root
        },
        "active_issues": [],
        "solutions_history": [],
        "ai_context_snapshot": "Initial setup - no active focus yet",
        "decisions": [],  # Architectural/design decisions
        "avoid": [],  # Things NOT to do (failed attempts, bad patterns)
        "handover": "",  # Last session summary for next AI
        "stats": {
            "total_errors_captured": 0,
            "total_solutions_applied": 0,
            "last_updated": None
        },
        "roi": {
            "solutions_reused": 0,           # Times a cached solution was applied
            "tokens_saved": 0,               # Estimated tokens saved (no codebase scan)
            "errors_prevented": 0,           # Errors caught by avoid patterns
            "decisions_referenced": 0,       # Times decisions were used
            "time_saved_minutes": 0,         # Estimated time saved
            "sessions_with_context": 0       # Sessions that started with handover
        }
    }


def add_or_update_issue(
    error_type: str,
    message: str,
    url: str = "",
    severity: str = "error",
    file: str = "",
    line: str = "",
    function: str = "",
    snippet: Optional[List[str]] = None,
    locals_data: Optional[Dict[str, str]] = None,
    stack: str = "",
    extra_data: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Add a new issue or update existing one (deduplicate by incrementing count).

    Returns:
        Dict with status and issue info
    """
    with _lock:
        memory = _load_memory()

        # Generate unique ID based on error signature
        issue_id = _generate_issue_id(error_type, message)

        # Check if issue already exists
        existing_idx = None
        for idx, issue in enumerate(memory['active_issues']):
            if issue['id'] == issue_id:
                existing_idx = idx
                break

        now = datetime.now().isoformat()

        if existing_idx is not None:
            # Update existing issue - increment count
            memory['active_issues'][existing_idx]['count'] += 1
            memory['active_issues'][existing_idx]['last_seen'] = now
            memory['active_issues'][existing_idx]['urls'].append(url) if url and url not in memory['active_issues'][existing_idx]['urls'] else None

            result = {
                "status": "updated",
                "issue_id": issue_id,
                "count": memory['active_issues'][existing_idx]['count'],
                "message": "Issue count incremented"
            }
        else:
            # Create new issue
            new_issue = {
                "id": issue_id,
                "type": error_type,
                "message": message[:500],  # Limit message length
                "severity": severity,
                "count": 1,
                "first_seen": now,
                "last_seen": now,
                "urls": [url] if url else [],
                "file": file,
                "line": line,
                "function": function,
                "snippet": snippet or [],
                "locals": locals_data or {},
                "stack": stack[:2000] if stack else "",
                "extra": extra_data or {}
            }
            memory['active_issues'].append(new_issue)
            memory['stats']['total_errors_captured'] += 1

            result = {
                "status": "created",
                "issue_id": issue_id,
                "count": 1,
                "message": "New issue added"
            }

        _save_memory(memory)
        return result


def resolve_issue(
    issue_id: str,
    solution_description: str,
    worked: bool = True,
    keywords: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Move an issue from active_issues to solutions_history.

    Args:
        issue_id: The ID of the issue to resolve
        solution_description: Description of the fix applied
        worked: Whether the solution worked
        keywords: List of semantic keywords/tags for better searchability

    Returns:
        Dict with status info
    """
    with _lock:
        memory = _load_memory()

        # Find the issue
        issue_idx = None
        issue_data = None
        for idx, issue in enumerate(memory['active_issues']):
            if issue['id'] == issue_id:
                issue_idx = idx
                issue_data = issue
                break

        if issue_idx is None:
            return {
                "status": "error",
                "message": f"Issue {issue_id} not found in active issues"
            }

        # Create solution history entry
        solution_entry = {
            "id": f"sol_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "original_issue_id": issue_id,
            "problem": issue_data['message'],
            "problem_type": issue_data['type'],
            "solution": solution_description,
            "keywords": keywords or [],
            "status": "worked" if worked else "failed",
            "occurrences_before_fix": issue_data['count'],
            "resolved_at": datetime.now().isoformat(),
            "first_seen": issue_data['first_seen']
        }

        # Move to history
        memory['solutions_history'].append(solution_entry)
        memory['active_issues'].pop(issue_idx)
        memory['stats']['total_solutions_applied'] += 1

        _save_memory(memory)

        return {
            "status": "ok",
            "message": f"Issue {issue_id} resolved and moved to history",
            "solution_id": solution_entry['id']
        }


def get_project_context() -> Dict[str, Any]:
    """Get the full project memory context."""
    with _lock:
        return _load_memory()


def get_context_summary() -> str:
    """
    Get a markdown-formatted summary of the project context.
    Designed to be consumed by AI for context loading.
    """
    with _lock:
        memory = _load_memory()

    info = memory['project_info']
    active = memory['active_issues']
    history = memory['solutions_history']
    snapshot = memory['ai_context_snapshot']
    stats = memory['stats']
    decisions = memory.get('decisions', [])
    avoid = memory.get('avoid', [])
    handover = memory.get('handover', {})

    # Build markdown summary
    lines = [
        f"# Project: {info['name']}",
        f"**Stack:** {info['stack']}",
        f"**Status:** {info['status']}",
        "",
    ]

    # Handover from last session (important for continuity!)
    if handover and isinstance(handover, dict) and handover.get('summary'):
        lines.extend([
            "## 📋 Handover from Last Session",
            f"{handover['summary']}",
            "",
        ])

    lines.extend([
        "## Current Focus",
        f"{snapshot}",
        "",
    ])

    # Decisions (what was decided)
    if decisions:
        lines.append(f"## 🎯 Key Decisions ({len(decisions)})")
        for dec in decisions[-5:]:  # Last 5
            lines.append(f"- **{dec['decision']}** - {dec['reason'][:60]}")
        lines.append("")

    # Avoid list (what NOT to do)
    if avoid:
        lines.append(f"## ⚠️ Avoid ({len(avoid)})")
        for item in avoid:
            lines.append(f"- **{item['what']}** - {item['reason'][:60]}")
        lines.append("")

    # Active issues - include ID for easy reference
    lines.append(f"## Active Issues ({len(active)})")
    if active:
        sorted_issues = sorted(active, key=lambda x: x['count'], reverse=True)
        for issue in sorted_issues[:10]:
            lines.append(f"- `{issue['id']}` **[{issue['type']}]** {issue['message'][:70]}... (x{issue['count']})")
    else:
        lines.append("- No active issues")

    lines.extend([
        "",
        f"## Recent Solutions ({len(history)})",
    ])

    if history:
        for sol in history[-5:]:
            status_icon = "v" if sol['status'] == 'worked' else "x"
            lines.append(f"- [{status_icon}] {sol['problem'][:50]}... -> {sol['solution'][:50]}...")
    else:
        lines.append("- No solutions recorded yet")

    lines.extend([
        "",
        f"## Stats",
        f"- Total errors captured: {stats['total_errors_captured']}",
        f"- Solutions applied: {stats['total_solutions_applied']}",
        f"- Last updated: {stats['last_updated'] or 'Never'}",
    ])

    return "\n".join(lines)


def update_ai_context(new_context: str) -> Dict[str, Any]:
    """Update the AI context snapshot."""
    with _lock:
        memory = _load_memory()
        memory['ai_context_snapshot'] = new_context
        _save_memory(memory)
        return {"status": "ok", "message": "Context updated"}


def update_project_info(
    name: Optional[str] = None,
    stack: Optional[str] = None,
    status: Optional[str] = None,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """Update project information."""
    with _lock:
        memory = _load_memory()
        if name:
            memory['project_info']['name'] = name
        if stack:
            memory['project_info']['stack'] = stack
        if status:
            memory['project_info']['status'] = status
        if description:
            memory['project_info']['description'] = description
        _save_memory(memory)
        return {"status": "ok", "message": "Project info updated"}


def clear_active_issues() -> Dict[str, Any]:
    """Clear all active issues (use with caution)."""
    with _lock:
        memory = _load_memory()
        count = len(memory['active_issues'])
        memory['active_issues'] = []
        _save_memory(memory)
        return {"status": "ok", "message": f"Cleared {count} active issues"}


def get_issue_by_id(issue_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific issue by ID."""
    with _lock:
        memory = _load_memory()
        for issue in memory['active_issues']:
            if issue['id'] == issue_id:
                return issue
        return None


def search_solutions(query: str) -> List[Dict[str, Any]]:
    """
    Search solutions history for relevant fixes.
    Uses smart keyword matching - all query words must appear in the text
    (problem, solution, or keywords), but not necessarily adjacent or in order.
    """
    with _lock:
        memory = _load_memory()
        query_parts = query.lower().split()
        results = []

        for sol in memory['solutions_history']:
            # Combine problem, solution, and keywords into searchable text
            keywords_str = ' '.join(sol.get('keywords', []))
            text = (sol['problem'] + ' ' + sol['solution'] + ' ' + keywords_str).lower()
            # All query words must appear somewhere in the text
            if all(part in text for part in query_parts):
                results.append(sol)

        return results


# ============================================================================
# PROJECT MEMORY: Decisions & Avoid Patterns
# ============================================================================

MAX_DECISIONS = 20
MAX_AVOID = 10


def log_decision(decision: str, reason: str, context: str = "") -> Dict[str, Any]:
    """
    Log an architectural or design decision.

    Args:
        decision: What was decided (e.g., "Use Redux instead of Context")
        reason: Why this decision was made
        context: Optional additional context

    Returns:
        Status of the operation
    """
    with _lock:
        memory = _load_memory()

        # Ensure decisions list exists
        if 'decisions' not in memory:
            memory['decisions'] = []

        # Check for duplicates (similar decision)
        decision_lower = decision.lower()
        for existing in memory['decisions']:
            if existing['decision'].lower() == decision_lower:
                return {"status": "exists", "message": "Similar decision already logged"}

        # Add new decision with used_by_ai tracking
        entry = {
            "id": f"dec_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "decision": decision[:200],
            "reason": reason[:300],
            "context": context[:200] if context else "",
            "date": datetime.now().isoformat(),
            "used_by_ai": False,  # Track if AI actually used this
            "use_count": 0  # How many times AI referenced this
        }
        memory['decisions'].append(entry)

        # Keep only the most recent MAX_DECISIONS
        if len(memory['decisions']) > MAX_DECISIONS:
            memory['decisions'] = memory['decisions'][-MAX_DECISIONS:]

        _save_memory(memory)
        return {"status": "ok", "message": "Decision logged", "id": entry['id']}


def log_avoid(what: str, reason: str) -> Dict[str, Any]:
    """
    Log something to avoid (failed attempt, bad pattern, etc.)

    Args:
        what: What to avoid (e.g., "Don't use moment.js")
        reason: Why to avoid it (e.g., "Too heavy, use date-fns instead")

    Returns:
        Status of the operation
    """
    with _lock:
        memory = _load_memory()

        # Ensure avoid list exists
        if 'avoid' not in memory:
            memory['avoid'] = []

        # Check for duplicates
        what_lower = what.lower()
        for existing in memory['avoid']:
            if existing['what'].lower() == what_lower:
                return {"status": "exists", "message": "Already in avoid list"}

        # Add new avoid entry with used_by_ai tracking
        entry = {
            "id": f"avoid_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "what": what[:200],
            "reason": reason[:300],
            "date": datetime.now().isoformat(),
            "used_by_ai": False,  # Track if AI actually used this
            "use_count": 0  # How many times AI checked this
        }
        memory['avoid'].append(entry)

        # Keep only the most recent MAX_AVOID
        if len(memory['avoid']) > MAX_AVOID:
            memory['avoid'] = memory['avoid'][-MAX_AVOID:]

        _save_memory(memory)
        return {"status": "ok", "message": "Added to avoid list", "id": entry['id']}


def get_decisions() -> List[Dict[str, Any]]:
    """Get all logged decisions."""
    with _lock:
        memory = _load_memory()
        return memory.get('decisions', [])


def get_avoid_list() -> List[Dict[str, Any]]:
    """Get all items to avoid."""
    with _lock:
        memory = _load_memory()
        return memory.get('avoid', [])


def save_handover(summary: str) -> Dict[str, Any]:
    """
    Save a handover summary for the next AI session.

    Args:
        summary: Summary of current session for the next AI

    Returns:
        Status of the operation
    """
    with _lock:
        memory = _load_memory()
        memory['handover'] = {
            "summary": summary[:1000],
            "created_at": datetime.now().isoformat()
        }
        _save_memory(memory)
        return {"status": "ok", "message": "Handover saved"}


def get_handover() -> Optional[Dict[str, Any]]:
    """Get the last handover summary."""
    with _lock:
        memory = _load_memory()
        return memory.get('handover')


# ============================================================================
# AI USAGE TRACKING: Mark items as used by AI
# ============================================================================

def mark_decision_used(decision_id: str) -> Dict[str, Any]:
    """
    Mark a decision as used by AI. Increments use_count.

    Args:
        decision_id: The ID of the decision (e.g., "dec_20240204_123456")

    Returns:
        Status of the operation
    """
    with _lock:
        memory = _load_memory()

        for dec in memory.get('decisions', []):
            if dec['id'] == decision_id:
                dec['used_by_ai'] = True
                dec['use_count'] = dec.get('use_count', 0) + 1
                dec['last_used'] = datetime.now().isoformat()
                _save_memory(memory)
                return {"status": "ok", "use_count": dec['use_count']}

        return {"status": "error", "message": f"Decision {decision_id} not found"}


def mark_avoid_used(avoid_id: str) -> Dict[str, Any]:
    """
    Mark an avoid pattern as used/checked by AI.

    Args:
        avoid_id: The ID of the avoid entry (e.g., "avoid_20240204_123456")

    Returns:
        Status of the operation
    """
    with _lock:
        memory = _load_memory()

        for item in memory.get('avoid', []):
            if item['id'] == avoid_id:
                item['used_by_ai'] = True
                item['use_count'] = item.get('use_count', 0) + 1
                item['last_used'] = datetime.now().isoformat()
                _save_memory(memory)
                return {"status": "ok", "use_count": item['use_count']}

        return {"status": "error", "message": f"Avoid pattern {avoid_id} not found"}


def get_memory_health() -> Dict[str, Any]:
    """
    Get memory health status for dashboard display.

    Returns:
        Dict with health metrics and usage stats
    """
    with _lock:
        memory = _load_memory()

    handover = memory.get('handover', {})
    decisions = memory.get('decisions', [])
    avoid = memory.get('avoid', [])
    solutions = memory.get('solutions_history', [])
    issues = memory.get('active_issues', [])

    # Calculate handover freshness
    handover_status = "empty"
    handover_age_hours = None
    if handover and handover.get('created_at'):
        try:
            created = datetime.fromisoformat(handover['created_at'])
            age = datetime.now() - created
            handover_age_hours = age.total_seconds() / 3600
            if handover_age_hours < 2:
                handover_status = "fresh"
            elif handover_age_hours < 24:
                handover_status = "recent"
            else:
                handover_status = "stale"
        except (ValueError, TypeError):
            handover_status = "unknown"

    # Count AI-used items
    decisions_used = sum(1 for d in decisions if d.get('used_by_ai'))
    avoid_used = sum(1 for a in avoid if a.get('used_by_ai'))

    # Memory fullness (rough estimate based on limits)
    memory_items = len(decisions) + len(avoid) + len(solutions) + len(issues)
    max_items = MAX_DECISIONS + MAX_AVOID + 50 + 50  # Rough limits
    fullness_percent = min(100, int((memory_items / max_items) * 100))

    return {
        "fullness_percent": fullness_percent,
        "handover": {
            "status": handover_status,
            "age_hours": round(handover_age_hours, 1) if handover_age_hours else None,
            "exists": bool(handover and handover.get('summary'))
        },
        "decisions": {
            "total": len(decisions),
            "used_by_ai": decisions_used,
            "unused": len(decisions) - decisions_used
        },
        "avoid": {
            "total": len(avoid),
            "used_by_ai": avoid_used,
            "unused": len(avoid) - avoid_used
        },
        "solutions": {
            "total": len(solutions),
            "worked": sum(1 for s in solutions if s.get('status') == 'worked'),
            "failed": sum(1 for s in solutions if s.get('status') == 'failed')
        },
        "issues": {
            "active": len(issues),
            "total_captured": memory.get('stats', {}).get('total_errors_captured', 0)
        },
        "roi": memory.get('roi', {})
    }


# ============================================================================
# ROI TRACKING: Measure value provided to user
# ============================================================================

# Constants for ROI calculations
TOKENS_PER_CODEBASE_SCAN = 5000      # Avg tokens to scan a project
MINUTES_PER_GOOGLE_SEARCH = 15       # Avg time debugging without solution
MINUTES_PER_DECISION_DISCUSSION = 20  # Time saved by documented decision
MINUTES_PER_AVOIDED_MISTAKE = 30      # Time saved by avoid pattern


def track_solution_reused(solution_id: str = None) -> Dict[str, Any]:
    """
    Track when a cached solution was reused instead of debugging from scratch.
    Call this when AI finds and applies an existing solution.
    """
    with _lock:
        memory = _load_memory()
        roi = memory.setdefault('roi', {})

        roi['solutions_reused'] = roi.get('solutions_reused', 0) + 1
        roi['tokens_saved'] = roi.get('tokens_saved', 0) + TOKENS_PER_CODEBASE_SCAN
        roi['time_saved_minutes'] = roi.get('time_saved_minutes', 0) + MINUTES_PER_GOOGLE_SEARCH

        _save_memory(memory)
        return {
            "status": "ok",
            "tokens_saved": TOKENS_PER_CODEBASE_SCAN,
            "minutes_saved": MINUTES_PER_GOOGLE_SEARCH,
            "total_roi": roi
        }


def track_decision_used(decision_id: str = None) -> Dict[str, Any]:
    """
    Track when a documented decision was referenced.
    Call this when AI uses a decision to guide implementation.
    """
    with _lock:
        memory = _load_memory()
        roi = memory.setdefault('roi', {})

        roi['decisions_referenced'] = roi.get('decisions_referenced', 0) + 1
        roi['tokens_saved'] = roi.get('tokens_saved', 0) + (TOKENS_PER_CODEBASE_SCAN // 2)
        roi['time_saved_minutes'] = roi.get('time_saved_minutes', 0) + MINUTES_PER_DECISION_DISCUSSION

        _save_memory(memory)
        return {
            "status": "ok",
            "tokens_saved": TOKENS_PER_CODEBASE_SCAN // 2,
            "minutes_saved": MINUTES_PER_DECISION_DISCUSSION,
            "total_roi": roi
        }


def track_error_prevented() -> Dict[str, Any]:
    """
    Track when an avoid pattern prevented a mistake.
    Call this when AI warns user based on avoid pattern.
    """
    with _lock:
        memory = _load_memory()
        roi = memory.setdefault('roi', {})

        roi['errors_prevented'] = roi.get('errors_prevented', 0) + 1
        roi['time_saved_minutes'] = roi.get('time_saved_minutes', 0) + MINUTES_PER_AVOIDED_MISTAKE

        _save_memory(memory)
        return {
            "status": "ok",
            "minutes_saved": MINUTES_PER_AVOIDED_MISTAKE,
            "total_roi": roi
        }


def track_session_with_context() -> Dict[str, Any]:
    """
    Track when a session started with existing context (handover).
    Call this when AI loads handover at session start.
    """
    with _lock:
        memory = _load_memory()
        roi = memory.setdefault('roi', {})

        roi['sessions_with_context'] = roi.get('sessions_with_context', 0) + 1
        # Context loading saves explaining time + codebase orientation
        roi['tokens_saved'] = roi.get('tokens_saved', 0) + (TOKENS_PER_CODEBASE_SCAN * 2)
        roi['time_saved_minutes'] = roi.get('time_saved_minutes', 0) + 10  # 10 min explaining context

        _save_memory(memory)
        return {
            "status": "ok",
            "tokens_saved": TOKENS_PER_CODEBASE_SCAN * 2,
            "minutes_saved": 10,
            "total_roi": roi
        }


def get_roi_stats() -> Dict[str, Any]:
    """
    Get ROI statistics for dashboard display.
    """
    with _lock:
        memory = _load_memory()
        roi = memory.get('roi', {})

        # Calculate human-readable values
        tokens_saved = roi.get('tokens_saved', 0)
        minutes_saved = roi.get('time_saved_minutes', 0)

        return {
            "solutions_reused": roi.get('solutions_reused', 0),
            "decisions_referenced": roi.get('decisions_referenced', 0),
            "errors_prevented": roi.get('errors_prevented', 0),
            "sessions_with_context": roi.get('sessions_with_context', 0),
            "tokens_saved": tokens_saved,
            "tokens_saved_formatted": f"{tokens_saved:,}",
            "time_saved_minutes": minutes_saved,
            "time_saved_formatted": _format_time(minutes_saved),
            "estimated_cost_saved": round(tokens_saved * 0.00001, 2)  # ~$0.01 per 1000 tokens
        }


def _format_time(minutes: int) -> str:
    """Format minutes as human-readable string."""
    if minutes < 60:
        return f"{minutes} דקות"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    if remaining_minutes == 0:
        return f"{hours} שעות"
    return f"{hours} שעות ו-{remaining_minutes} דקות"


def reset_roi_stats() -> Dict[str, Any]:
    """Reset ROI statistics (for testing)."""
    with _lock:
        memory = _load_memory()
        memory['roi'] = {
            "solutions_reused": 0,
            "tokens_saved": 0,
            "errors_prevented": 0,
            "decisions_referenced": 0,
            "time_saved_minutes": 0,
            "sessions_with_context": 0
        }
        _save_memory(memory)
        return {"status": "ok", "message": "ROI stats reset"}
