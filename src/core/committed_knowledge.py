"""
Committed Knowledge Manager for FixOnce

Manages knowledge that travels with the Git repository in .fixonce/
Only high-value, durable knowledge is committed - not everything.

Files:
  .fixonce/decisions.json   - Architectural decisions (permanent)
  .fixonce/avoid.json       - Anti-patterns to avoid (permanent)
  .fixonce/CONTEXT.md       - Human/AI readable summary (auto-generated)

Principles:
  1. Only commit QUALITY knowledge (not raw session data)
  2. Sanitize before writing (remove secrets, PII)
  3. Keep files small and focused
  4. Decisions and avoid patterns are permanent institutional knowledge

Version History:
  1.0 - Initial format with decisions.json and avoid.json
"""

# Current format version
FIXONCE_VERSION = "1.0"

import re
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional


def _generate_project_id(working_dir: str) -> str:
    """Generate project ID from working directory path."""
    path_hash = hashlib.md5(working_dir.encode()).hexdigest()[:12]
    name = Path(working_dir).name
    return f"{name}_{path_hash}"

# Safe file operations
try:
    from core.safe_file import atomic_json_write, atomic_json_read
    SAFE_FILE_AVAILABLE = True
except ImportError:
    SAFE_FILE_AVAILABLE = False


# ============================================================
# SANITIZATION
# ============================================================

# Patterns to detect and redact secrets/sensitive data
SECRET_PATTERNS = [
    # API Keys
    (r'sk-[a-zA-Z0-9]{20,}', '[OPENAI_KEY]'),           # OpenAI
    (r'sk-ant-[a-zA-Z0-9\-]{20,}', '[ANTHROPIC_KEY]'),  # Anthropic
    (r'AKIA[A-Z0-9]{16}', '[AWS_ACCESS_KEY]'),          # AWS Access Key
    (r'[a-zA-Z0-9/+]{40}', None),                        # AWS Secret (only if looks like base64)
    (r'ghp_[a-zA-Z0-9]{36}', '[GITHUB_TOKEN]'),         # GitHub Personal Access Token
    (r'gho_[a-zA-Z0-9]{36}', '[GITHUB_OAUTH]'),         # GitHub OAuth
    (r'glpat-[a-zA-Z0-9\-]{20,}', '[GITLAB_TOKEN]'),    # GitLab
    (r'xox[baprs]-[a-zA-Z0-9\-]{10,}', '[SLACK_TOKEN]'), # Slack

    # Generic patterns
    (r'api[_-]?key\s*[:=]\s*["\']?([a-zA-Z0-9\-_]{20,})["\']?', '[API_KEY]'),
    (r'secret[_-]?key\s*[:=]\s*["\']?([a-zA-Z0-9\-_]{20,})["\']?', '[SECRET_KEY]'),
    (r'password\s*[:=]\s*["\']?([^\s"\']{8,})["\']?', '[PASSWORD]'),
    (r'token\s*[:=]\s*["\']?([a-zA-Z0-9\-_]{20,})["\']?', '[TOKEN]'),

    # Connection strings
    (r'mongodb(\+srv)?://[^\s]+', '[MONGODB_URI]'),
    (r'postgres(ql)?://[^\s]+', '[POSTGRES_URI]'),
    (r'mysql://[^\s]+', '[MYSQL_URI]'),
    (r'redis://[^\s]+', '[REDIS_URI]'),

    # Private keys
    (r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----', '[PRIVATE_KEY]'),

    # Email addresses (optional - may want to keep for context)
    # (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]'),
]


def sanitize_text(text: str) -> str:
    """
    Remove secrets and sensitive data from text before committing to Git.

    Args:
        text: The text to sanitize

    Returns:
        Sanitized text with secrets redacted
    """
    if not text:
        return text

    result = text

    for pattern, replacement in SECRET_PATTERNS:
        if replacement:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        else:
            # For patterns without replacement, only redact if high confidence
            # (e.g., AWS secret key pattern is too generic)
            pass

    return result


def sanitize_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a decision object before committing."""
    return {
        "decision": sanitize_text(decision.get("decision", "")),
        "reason": sanitize_text(decision.get("reason", "")),
        "timestamp": decision.get("timestamp", ""),
        "superseded": decision.get("superseded", False),
    }


def sanitize_avoid(avoid: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize an avoid pattern before committing."""
    return {
        "what": sanitize_text(avoid.get("what", "")),
        "reason": sanitize_text(avoid.get("reason", "")),
        "timestamp": avoid.get("timestamp", ""),
    }


# ============================================================
# QUALITY FILTERING
# ============================================================

def is_quality_decision(decision: Dict[str, Any]) -> bool:
    """
    Check if a decision is worth committing to Git.

    GENERIC FILTER - works across any project/technology.

    INCLUDE (high future value):
    - Architectural decisions (HOW the system is designed)
    - Stable project constraints (RULES that must be followed)
    - Proven patterns and approaches

    EXCLUDE (low future value):
    - Test/debug noise
    - Checkpoint/operational logs
    - UI micro-details
    - Temporary implementation chatter
    - Truncated or incomplete entries
    """
    text = decision.get("decision", "")
    reason = decision.get("reason", "")

    # === BASIC REQUIREMENTS ===

    # Skip superseded decisions
    if decision.get("superseded", False):
        return False

    # Must have substantial text
    if len(text) < 15:
        return False

    # Must have a meaningful reason (explains WHY, not just WHAT)
    if len(reason) < 25:
        return False

    text_lower = text.lower()
    reason_lower = reason.lower()

    # === EXCLUSION RULES (Generic) ===

    # 1. Test/debug noise - reason indicates this is FOR testing
    test_patterns = [
        r'^testing\b',
        r'^test\s+for\b',
        r'^debug',
        r'^verify',
        r'^check\s+if\b',
        r'בדיקה',
        r'ניסיון',
    ]
    for pattern in test_patterns:
        if re.search(pattern, reason_lower):
            return False

    # 2. Temporary markers in decision text
    temp_markers = [
        "temporary",
        "temp fix",
        "for now",
        "quick fix",
        "workaround",
        "hack",
        "todo",
        "fixme",
        "זמני",
        "לבינתיים",
    ]
    for marker in temp_markers:
        if marker in text_lower:
            return False

    # 3. Operational/checkpoint logs (not decisions)
    operational_patterns = [
        r"checkpoint(s)?\s+(created|saved)",
        r"bulk\s+(checkpoint|update|operation)",
        r"saved\s+at\s+commit",
        r"migrated?\s+from",
        r"upgraded?\s+to\s+v",
    ]
    for pattern in operational_patterns:
        if re.search(pattern, text_lower) or re.search(pattern, reason_lower):
            return False

    # 4. Single-word or trivial reasons
    trivial_reasons = [
        "added", "removed", "fixed", "updated", "changed",
        "done", "completed", "finished", "works", "working",
        "הוסף", "הוסר", "תוקן", "עודכן", "בוצע",
    ]
    reason_words = reason_lower.strip().split()
    if len(reason_words) <= 2 and reason_words[0] in trivial_reasons:
        return False

    # 5. Truncated/incomplete entries
    truncation_patterns = [
        r'\([^)]*$',      # unclosed paren
        r'\s(done|in)$',  # truncated mid-word
        r'\.\.\.$',       # explicit truncation
        r':\s*$',         # ends with colon (incomplete)
    ]
    for pattern in truncation_patterns:
        if re.search(pattern, reason):
            return False

    # 6. UI micro-details (implementation specifics, not architecture)
    ui_micro_patterns = [
        r"now\s+(shows?|displays?|renders?|hides?|exposes?|includes?|marks?)\b",
        r"(button|modal|tooltip|icon|rail|timeline|snapshot)\s+(now|added|removed)",
        r"css\s+(class|style|rule)",
        r"(color|font|padding|margin)\s+(changed|updated)",
        r"ui\s+(tweak|fix|adjustment)",
    ]
    for pattern in ui_micro_patterns:
        if re.search(pattern, text_lower):
            return False

    # 7. UI refactoring/restructuring (not architectural)
    ui_refactor_patterns = [
        r"merged\s+\w+\s+into",          # "Merged X into Y"
        r"moved\s+\w+\s+(to|from)",       # "Moved X to Y"
        r"split\s+\w+\s+into",            # "Split X into Y"
        r"renamed\s+\w+\s+to",            # "Renamed X to Y"
        r"(status\s+rail|tree\s+summary)", # UI component restructuring
    ]
    for pattern in ui_refactor_patterns:
        if re.search(pattern, text_lower):
            return False

    # 8. Dashboard-specific incremental changes
    is_dashboard_specific = "dashboard" in text_lower and any(w in text_lower for w in [
        " now ", "added", "removed", "updated", "changed"
    ])
    if is_dashboard_specific:
        return False

    # === PASSED ALL EXCLUSION RULES ===
    return True


def is_quality_avoid(avoid: Dict[str, Any]) -> bool:
    """
    Check if an avoid pattern is worth committing to Git.

    Quality criteria:
    - Has meaningful text
    - Has a reason
    """
    what = avoid.get("what", "")
    reason = avoid.get("reason", "")

    # Must have substantial text
    if len(what) < 5:
        return False

    # Must have a reason
    if len(reason) < 5:
        return False

    return True


def is_quality_insight(insight: Dict[str, Any]) -> bool:
    """
    Check if an insight is worth committing to Git.

    STRICT FILTER - only truly valuable insights:
    - importance == "high" or importance > 0.8
    - OR use_count >= 3 (proven useful across sessions)

    Also requires minimum text length.
    """
    text = insight.get("text", "")

    # Must have substantial text
    if len(text) < 20:
        return False

    # Check importance
    importance = insight.get("importance", "medium")
    if importance == "high":
        return True

    # Check numeric importance (if stored as float)
    if isinstance(importance, (int, float)) and importance > 0.8:
        return True

    # Check use_count (proven useful)
    use_count = insight.get("use_count", 0)
    if use_count >= 3:
        return True

    return False


def sanitize_insight(insight: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize an insight before committing."""
    return {
        "text": sanitize_text(insight.get("text", "")),
        "timestamp": insight.get("timestamp", ""),
        "importance": insight.get("importance", "medium"),
        "use_count": insight.get("use_count", 0),
    }


def is_quality_solution(solution: Dict[str, Any]) -> bool:
    """
    Check if a debug session / solution is worth committing to Git.

    Quality criteria:
    - Has problem AND solution text (both required)
    - reuse_count >= 1 (was used at least once)
    - OR importance == "high" (all debug_sessions are high by default)
    - Problem text is substantial (not trivial)
    """
    problem = solution.get("problem", "")
    sol_text = solution.get("solution", "")

    # Must have both problem and solution
    if len(problem) < 10 or len(sol_text) < 10:
        return False

    # Check if it was reused (proven useful)
    reuse_count = solution.get("reuse_count", 0)
    if reuse_count >= 1:
        return True

    # Check importance (debug_sessions default to "high")
    importance = solution.get("importance", "medium")
    if importance == "high":
        return True

    return False


def sanitize_solution(solution: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a solution/debug_session before committing."""
    return {
        "problem": sanitize_text(solution.get("problem", "")),
        "root_cause": sanitize_text(solution.get("root_cause", "")),
        "solution": sanitize_text(solution.get("solution", "")),
        "symptoms": solution.get("symptoms", []),
        "files_changed": solution.get("files_changed", []),
        "timestamp": solution.get("resolved_at", solution.get("timestamp", "")),
        "reuse_count": solution.get("reuse_count", 0),
    }


def _get_solution_key(s: Dict[str, Any]) -> str:
    """Get unique key for a solution (for diff comparison)."""
    return s.get("problem", "")[:100]


# ============================================================
# COMMITTED KNOWLEDGE WRITER
# ============================================================

def get_fixonce_dir(working_dir: str) -> Path:
    """Get the .fixonce directory path for a project."""
    return Path(working_dir) / ".fixonce"


def ensure_fixonce_dir(working_dir: str) -> Path:
    """Ensure .fixonce directory exists and return its path."""
    fixonce_dir = get_fixonce_dir(working_dir)
    fixonce_dir.mkdir(exist_ok=True)

    # Create .gitignore for files that shouldn't be committed
    gitignore_path = fixonce_dir / ".gitignore"
    if not gitignore_path.exists():
        gitignore_content = """# FixOnce - files not for Git
# Embeddings are large binary files - rebuild from text
embeddings/

# Backups are local safety copies
.backups/

# Session data is temporary
session.json

# Project UUID (only needed for non-git projects)
# project.json  # Uncomment if you don't want to track this
"""
        gitignore_path.write_text(gitignore_content)

    return fixonce_dir


# ============================================================
# PROJECT METADATA (Portable Identity)
# ============================================================

def get_project_metadata(working_dir: str) -> Optional[Dict[str, Any]]:
    """
    Read project metadata from .fixonce/metadata.json.

    This is the portable project identity that travels with the repo.
    Contains project_id that remains stable across machines.

    Returns:
        Metadata dict or None if not found
    """
    fixonce_dir = get_fixonce_dir(working_dir)
    metadata_path = fixonce_dir / "metadata.json"

    if not metadata_path.exists():
        return None

    try:
        if SAFE_FILE_AVAILABLE:
            return atomic_json_read(str(metadata_path), default=None)
        else:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        return None


def get_or_create_project_metadata(working_dir: str, display_name: str = None) -> Dict[str, Any]:
    """
    Get existing metadata or create new metadata for a project.

    This ensures every project has a stable project_id that:
    - Is stored IN the project (not derived from path)
    - Remains the same when cloned to another machine
    - Is human-readable (name_uuid format)

    Args:
        working_dir: Project root directory
        display_name: Optional display name (defaults to folder name)

    Returns:
        Metadata dict with project_id, name, created_at, etc.
    """
    import uuid

    # Check for existing metadata
    existing = get_project_metadata(working_dir)
    if existing and existing.get("project_id"):
        return existing

    # Create new metadata
    folder_name = Path(working_dir).name
    name = display_name or folder_name

    # Generate stable project_id: name_uuid8
    # UUID is random, not path-based, so it's truly portable
    project_uuid = uuid.uuid4().hex[:8]
    project_id = f"{folder_name}_{project_uuid}"

    metadata = {
        "fixonce_version": FIXONCE_VERSION,
        "project_id": project_id,
        "name": name,
        "created_at": datetime.now().isoformat(),
        "working_dir_original": working_dir,  # For reference only, not used for identity
    }

    # Write metadata
    fixonce_dir = ensure_fixonce_dir(working_dir)
    metadata_path = fixonce_dir / "metadata.json"

    try:
        if SAFE_FILE_AVAILABLE:
            atomic_json_write(str(metadata_path), metadata, create_backup=False)
        else:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[CommittedKnowledge] Failed to write metadata: {e}")

    return metadata


def get_portable_project_id(working_dir: str) -> Optional[str]:
    """
    Get the portable project_id from .fixonce/metadata.json.

    This is the PREFERRED way to get project_id - it's stable across machines.
    Falls back to None if .fixonce doesn't exist (new project).

    Args:
        working_dir: Project root directory

    Returns:
        project_id string or None
    """
    metadata = get_project_metadata(working_dir)
    if metadata:
        return metadata.get("project_id")
    return None


def _get_decision_key(d: Dict[str, Any]) -> str:
    """Get unique key for a decision (for diff comparison)."""
    return d.get("decision", "")[:100]


def _get_avoid_key(a: Dict[str, Any]) -> str:
    """Get unique key for an avoid pattern (for diff comparison)."""
    return a.get("what", "")[:100]


def _get_insight_key(i: Dict[str, Any]) -> str:
    """Get unique key for an insight (for diff comparison)."""
    return i.get("text", "")[:100]


def write_committed_knowledge(
    working_dir: str,
    decisions: List[Dict[str, Any]],
    avoid_patterns: List[Dict[str, Any]],
    insights: List[Dict[str, Any]] = None,
    solutions: List[Dict[str, Any]] = None,
    project_id: str = None
) -> Dict[str, Any]:
    """
    Write quality, sanitized knowledge to .fixonce/ directory.

    Args:
        working_dir: Project root directory
        decisions: List of decision dicts from memory
        avoid_patterns: List of avoid dicts from memory
        insights: List of insight dicts from memory (optional)
        solutions: List of debug_session/solution dicts (optional)
        project_id: Optional project ID to include in files

    Returns:
        Result dict with status, file paths, and diff info
    """
    if not working_dir or not Path(working_dir).is_dir():
        return {"status": "error", "message": "Invalid working directory"}

    try:
        fixonce_dir = ensure_fixonce_dir(working_dir)
        result = {"status": "ok", "files": [], "stats": {}, "diff": {}}

        # Filter and sanitize decisions
        quality_decisions = [
            sanitize_decision(d) for d in decisions
            if is_quality_decision(d)
        ]

        # Filter and sanitize avoid patterns
        quality_avoids = [
            sanitize_avoid(a) for a in avoid_patterns
            if is_quality_avoid(a)
        ]

        # Filter and sanitize insights (strict filter: high importance or use_count >= 3)
        quality_insights = []
        if insights:
            quality_insights = [
                sanitize_insight(i) for i in insights
                if is_quality_insight(i)
            ]

        # Filter and sanitize solutions (debug_sessions with importance=high or reuse_count >= 1)
        quality_solutions = []
        if solutions:
            quality_solutions = [
                sanitize_solution(s) for s in solutions
                if is_quality_solution(s)
            ]

        # === DIFF DETECTION: Compare with existing ===
        existing = read_committed_knowledge(working_dir)
        existing_decision_keys = {_get_decision_key(d) for d in existing.get("decisions", [])}
        existing_avoid_keys = {_get_avoid_key(a) for a in existing.get("avoid", [])}
        existing_insight_keys = {_get_insight_key(i) for i in existing.get("insights", [])}
        existing_solution_keys = {_get_solution_key(s) for s in existing.get("solutions", [])}

        new_decision_keys = {_get_decision_key(d) for d in quality_decisions}
        new_avoid_keys = {_get_avoid_key(a) for a in quality_avoids}
        new_insight_keys = {_get_insight_key(i) for i in quality_insights}
        new_solution_keys = {_get_solution_key(s) for s in quality_solutions}

        # Calculate diff
        added_decisions = len(new_decision_keys - existing_decision_keys)
        removed_decisions = len(existing_decision_keys - new_decision_keys)
        added_avoids = len(new_avoid_keys - existing_avoid_keys)
        removed_avoids = len(existing_avoid_keys - new_avoid_keys)
        added_insights = len(new_insight_keys - existing_insight_keys)
        removed_insights = len(existing_insight_keys - new_insight_keys)
        added_solutions = len(new_solution_keys - existing_solution_keys)
        removed_solutions = len(existing_solution_keys - new_solution_keys)

        total_changes = (added_decisions + removed_decisions + added_avoids + removed_avoids +
                        added_insights + removed_insights + added_solutions + removed_solutions)

        result["diff"] = {
            "decisions_added": added_decisions,
            "decisions_removed": removed_decisions,
            "avoid_added": added_avoids,
            "avoid_removed": removed_avoids,
            "insights_added": added_insights,
            "insights_removed": removed_insights,
            "solutions_added": added_solutions,
            "solutions_removed": removed_solutions,
            "has_changes": total_changes > 0
        }

        # Write decisions.json
        decisions_path = fixonce_dir / "decisions.json"
        decisions_data = {
            "fixonce_version": FIXONCE_VERSION,
            "project_id": project_id or _generate_project_id(working_dir),
            "updated_at": datetime.now().isoformat(),
            "count": len(quality_decisions),
            "decisions": quality_decisions
        }

        if SAFE_FILE_AVAILABLE:
            atomic_json_write(str(decisions_path), decisions_data, create_backup=False)
        else:
            with open(decisions_path, 'w', encoding='utf-8') as f:
                json.dump(decisions_data, f, ensure_ascii=False, indent=2)

        result["files"].append(str(decisions_path))
        result["stats"]["decisions"] = len(quality_decisions)

        # Write avoid.json
        avoid_path = fixonce_dir / "avoid.json"
        avoid_data = {
            "fixonce_version": FIXONCE_VERSION,
            "project_id": project_id or _generate_project_id(working_dir),
            "updated_at": datetime.now().isoformat(),
            "count": len(quality_avoids),
            "patterns": quality_avoids
        }

        if SAFE_FILE_AVAILABLE:
            atomic_json_write(str(avoid_path), avoid_data, create_backup=False)
        else:
            with open(avoid_path, 'w', encoding='utf-8') as f:
                json.dump(avoid_data, f, ensure_ascii=False, indent=2)

        result["files"].append(str(avoid_path))
        result["stats"]["avoid_patterns"] = len(quality_avoids)

        # Write insights.json (only if we have quality insights)
        if quality_insights:
            insights_path = fixonce_dir / "insights.json"
            insights_data = {
                "fixonce_version": FIXONCE_VERSION,
                "project_id": project_id or _generate_project_id(working_dir),
                "updated_at": datetime.now().isoformat(),
                "count": len(quality_insights),
                "filter_criteria": "importance=high OR use_count>=3",
                "insights": quality_insights
            }

            if SAFE_FILE_AVAILABLE:
                atomic_json_write(str(insights_path), insights_data, create_backup=False)
            else:
                with open(insights_path, 'w', encoding='utf-8') as f:
                    json.dump(insights_data, f, ensure_ascii=False, indent=2)

            result["files"].append(str(insights_path))

        result["stats"]["insights"] = len(quality_insights)

        # Write solutions.json (only if we have quality solutions)
        if quality_solutions:
            solutions_path = fixonce_dir / "solutions.json"
            solutions_data = {
                "fixonce_version": FIXONCE_VERSION,
                "project_id": project_id or _generate_project_id(working_dir),
                "updated_at": datetime.now().isoformat(),
                "count": len(quality_solutions),
                "filter_criteria": "importance=high OR reuse_count>=1",
                "solutions": quality_solutions
            }

            if SAFE_FILE_AVAILABLE:
                atomic_json_write(str(solutions_path), solutions_data, create_backup=False)
            else:
                with open(solutions_path, 'w', encoding='utf-8') as f:
                    json.dump(solutions_data, f, ensure_ascii=False, indent=2)

            result["files"].append(str(solutions_path))

        result["stats"]["solutions"] = len(quality_solutions)

        return result

    except Exception as e:
        return {"status": "error", "message": str(e)}


def read_committed_knowledge(working_dir: str) -> Dict[str, Any]:
    """
    Read committed knowledge from .fixonce/ directory.

    Used when initializing a project to load repo-stored knowledge.

    Args:
        working_dir: Project root directory

    Returns:
        Dict with decisions and avoid patterns from .fixonce/
    """
    result = {
        "decisions": [],
        "avoid": [],
        "insights": [],
        "solutions": [],
        "found": False,
        "fixonce_version": None,
        "project_id": None
    }

    fixonce_dir = get_fixonce_dir(working_dir)
    if not fixonce_dir.exists():
        return result

    # Read decisions
    decisions_path = fixonce_dir / "decisions.json"
    if decisions_path.exists():
        try:
            if SAFE_FILE_AVAILABLE:
                data = atomic_json_read(str(decisions_path), default={})
            else:
                with open(decisions_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            result["decisions"] = data.get("decisions", [])
            result["fixonce_version"] = data.get("fixonce_version")
            result["project_id"] = data.get("project_id")
            result["found"] = True
        except Exception:
            pass

    # Read avoid patterns
    avoid_path = fixonce_dir / "avoid.json"
    if avoid_path.exists():
        try:
            if SAFE_FILE_AVAILABLE:
                data = atomic_json_read(str(avoid_path), default={})
            else:
                with open(avoid_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            result["avoid"] = data.get("patterns", [])
            result["found"] = True
        except Exception:
            pass

    # Read insights
    insights_path = fixonce_dir / "insights.json"
    if insights_path.exists():
        try:
            if SAFE_FILE_AVAILABLE:
                data = atomic_json_read(str(insights_path), default={})
            else:
                with open(insights_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            result["insights"] = data.get("insights", [])
            result["found"] = True
        except Exception:
            pass

    # Read solutions
    solutions_path = fixonce_dir / "solutions.json"
    if solutions_path.exists():
        try:
            if SAFE_FILE_AVAILABLE:
                data = atomic_json_read(str(solutions_path), default={})
            else:
                with open(solutions_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            result["solutions"] = data.get("solutions", [])
            result["found"] = True
        except Exception:
            pass

    return result


def sync_from_committed(working_dir: str, memory: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sync committed knowledge INTO memory (for new sessions on existing repos).

    When a developer clones a repo with .fixonce/, this merges the
    committed knowledge into their local memory.

    Args:
        working_dir: Project root directory
        memory: Current project memory

    Returns:
        Updated memory with merged knowledge
    """
    committed = read_committed_knowledge(working_dir)

    if not committed["found"]:
        return memory

    # Log version info
    version = committed.get("fixonce_version", "unknown")
    source_project = committed.get("project_id", "unknown")
    print(f"[CommittedKnowledge] Syncing from .fixonce/ (version {version}, project {source_project})")

    # Merge decisions (avoid duplicates by text)
    existing_decisions = {d.get("decision", ""): d for d in memory.get("decisions", [])}
    merged_decisions = 0
    for dec in committed["decisions"]:
        text = dec.get("decision", "")
        if text and text not in existing_decisions:
            # Add with marker that it came from repo
            dec["source"] = "repo"
            memory.setdefault("decisions", []).append(dec)
            merged_decisions += 1

    # Merge avoid patterns (avoid duplicates by what)
    existing_avoids = {a.get("what", ""): a for a in memory.get("avoid", [])}
    merged_avoids = 0
    for avoid in committed["avoid"]:
        what = avoid.get("what", "")
        if what and what not in existing_avoids:
            avoid["source"] = "repo"
            memory.setdefault("avoid", []).append(avoid)
            merged_avoids += 1

    # Merge insights (avoid duplicates by text)
    existing_insights = {i.get("text", ""): i for i in memory.get("live_record", {}).get("lessons", {}).get("insights", [])}
    merged_insights = 0
    for insight in committed["insights"]:
        text = insight.get("text", "")
        if text and text not in existing_insights:
            insight["source"] = "repo"
            # Ensure the nested structure exists
            if "live_record" not in memory:
                memory["live_record"] = {}
            if "lessons" not in memory["live_record"]:
                memory["live_record"]["lessons"] = {}
            if "insights" not in memory["live_record"]["lessons"]:
                memory["live_record"]["lessons"]["insights"] = []
            memory["live_record"]["lessons"]["insights"].append(insight)
            merged_insights += 1

    # Merge solutions (debug_sessions - avoid duplicates by problem)
    existing_solutions = {s.get("problem", ""): s for s in memory.get("debug_sessions", [])}
    merged_solutions = 0
    for solution in committed["solutions"]:
        problem = solution.get("problem", "")
        if problem and problem not in existing_solutions:
            solution["source"] = "repo"
            memory.setdefault("debug_sessions", []).append(solution)
            merged_solutions += 1

    if merged_decisions > 0 or merged_avoids > 0 or merged_insights > 0 or merged_solutions > 0:
        print(f"[CommittedKnowledge] Merged {merged_decisions} decisions, {merged_avoids} avoid, {merged_insights} insights, {merged_solutions} solutions")

    return memory


# ============================================================
# HOOK FOR MEMORY SAVE
# ============================================================

def update_committed_on_save(project_id: str, memory: Dict[str, Any]) -> Optional[str]:
    """
    Hook to call after memory changes.
    Updates .fixonce/ files (decisions, avoid, insights, solutions) if working_dir exists.

    This is called from save_project_memory() in multi_project_manager.py

    Returns the .fixonce directory path, or None if not possible.
    """
    project_info = memory.get('project_info', {})
    working_dir = project_info.get('working_dir', '')

    if not working_dir or not Path(working_dir).is_dir():
        return None

    decisions = memory.get('decisions', [])
    avoid = memory.get('avoid', [])
    insights = memory.get('live_record', {}).get('lessons', {}).get('insights', [])
    solutions = memory.get('debug_sessions', [])

    # Only write if there's something to write
    if not decisions and not avoid and not insights and not solutions:
        return None

    try:
        result = write_committed_knowledge(
            working_dir, decisions, avoid,
            insights=insights, solutions=solutions, project_id=project_id
        )
        if result["status"] == "ok":
            return str(get_fixonce_dir(working_dir))
        return None
    except Exception as e:
        print(f"[CommittedKnowledge] Failed to update: {e}")
        return None
