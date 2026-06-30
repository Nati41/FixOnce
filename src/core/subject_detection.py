"""
Subject Detection V1 for FixOnce.

Extracts subject tags from file paths and signals.
Used by Subject Context Engine to connect signals to tag-based retrieval.

Design principles:
1. Deterministic rules only - no LLMs, no inference
2. Extract from observable signals (paths, files)
3. Return normalized, consistent tags
4. Safe fallback for unknown paths
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Set


# Known project folder mappings
# Map path components to subject tags
FOLDER_TO_TAGS = {
    # Top-level areas
    "website": ["website"],
    "src": [],  # Too generic, look deeper
    "scripts": [],  # Look at specific scripts
    "tests": ["tests"],
    "data": ["data"],

    # Core modules
    "core": ["core"],
    "api": ["api", "server"],
    "mcp_server": ["mcp"],
    "managers": ["core"],

    # Platform-specific
    "windows": ["windows"],
    "macos": ["macos"],
    "linux": ["linux"],

    # Components
    "dashboard": ["dashboard"],
    "extension": ["extension"],
    "installer": ["installer"],
}

# Specific file patterns that indicate subjects
FILE_PATTERNS = {
    # macOS specific
    "menubar": ["macos", "tray"],
    "launchagent": ["macos", "installer"],
    "tray": ["tray"],

    # Windows specific
    "windows": ["windows"],
    ".ps1": ["windows"],
    ".bat": ["windows"],

    # Core modules by name
    "search": ["search"],
    "port_manager": ["server", "ports"],
    "session": ["session"],
    "memory": ["memory"],
    "activity": ["activity"],
    "error": ["errors"],
    "install": ["installer"],
    "semantic": ["search", "semantic"],
    "decision": ["decisions"],
    "commit": ["git"],

    # Web/UI
    "index.html": ["website"],
    "dashboard": ["dashboard"],
    ".css": ["website", "styles"],
    ".html": ["website"],
}


def extract_subject_tags_from_path(path: str) -> List[str]:
    """
    Extract subject tags from a file path.

    Uses deterministic rules based on:
    1. Directory names in the path
    2. File name patterns
    3. File extensions

    Args:
        path: File path (absolute or relative)

    Returns:
        List of normalized subject tags, may be empty for unknown paths

    Examples:
        >>> extract_subject_tags_from_path("website/index.html")
        ['website']
        >>> extract_subject_tags_from_path("src/core/search.py")
        ['core', 'search']
        >>> extract_subject_tags_from_path("scripts/menubar_app.py")
        ['macos', 'tray']
    """
    if not path:
        return []

    tags: Set[str] = set()

    # Normalize path
    path_obj = Path(path)
    parts = path_obj.parts
    filename = path_obj.name.lower()
    stem = path_obj.stem.lower()
    suffix = path_obj.suffix.lower()

    # Check each directory part
    for part in parts:
        part_lower = part.lower()
        if part_lower in FOLDER_TO_TAGS:
            tags.update(FOLDER_TO_TAGS[part_lower])

    # Check file patterns (substring match)
    for pattern, pattern_tags in FILE_PATTERNS.items():
        if pattern in filename or pattern in stem:
            tags.update(pattern_tags)

    # Check extension-based patterns
    if suffix in FILE_PATTERNS:
        tags.update(FILE_PATTERNS[suffix])

    # Remove empty strings if any
    tags.discard("")

    return sorted(tags)


def derive_current_subject_tags(
    signals: Dict[str, Any],
    combine_mode: str = "union"
) -> List[str]:
    """
    Derive subject tags from multiple signals.

    Combines tags from various signal sources:
    - activity.file: Current file being worked on
    - intent.last_file: Last file from fo_sync
    - solutions.files_changed: Files changed in a solution
    - intent.work_area: Explicit work area declaration

    Args:
        signals: Dict with signal keys and values
        combine_mode: "union" (all tags) or "intersection" (common tags)

    Returns:
        List of normalized subject tags

    Examples:
        >>> derive_current_subject_tags({
        ...     "activity.file": "website/index.html",
        ...     "intent.last_file": "website/styles.css"
        ... })
        ['styles', 'website']
    """
    all_tags: Set[str] = set()
    tag_sources: List[Set[str]] = []

    # Extract from activity.file
    if signals.get("activity.file"):
        file_tags = set(extract_subject_tags_from_path(signals["activity.file"]))
        if file_tags:
            tag_sources.append(file_tags)
            all_tags.update(file_tags)

    # Extract from intent.last_file
    if signals.get("intent.last_file"):
        file_tags = set(extract_subject_tags_from_path(signals["intent.last_file"]))
        if file_tags:
            tag_sources.append(file_tags)
            all_tags.update(file_tags)

    # Extract from solutions.files_changed (list of files)
    files_changed = signals.get("solutions.files_changed", [])
    if isinstance(files_changed, list):
        for f in files_changed:
            file_tags = set(extract_subject_tags_from_path(f))
            if file_tags:
                tag_sources.append(file_tags)
                all_tags.update(file_tags)

    # Extract from intent.work_area (explicit declaration)
    work_area = signals.get("intent.work_area", "")
    if work_area:
        # Normalize work_area to tags
        area_tags = _normalize_work_area_to_tags(work_area)
        if area_tags:
            tag_sources.append(set(area_tags))
            all_tags.update(area_tags)

    # Extract from query (e.g., task_hint from fo_init)
    query = signals.get("query", "")
    if query:
        query_tags = _extract_tags_from_query(query)
        if query_tags:
            tag_sources.append(set(query_tags))
            all_tags.update(query_tags)

    # Apply combine mode
    if combine_mode == "intersection" and len(tag_sources) >= 2:
        # Only return tags that appear in multiple sources
        result = tag_sources[0]
        for ts in tag_sources[1:]:
            result = result & ts
        return sorted(result) if result else sorted(all_tags)

    return sorted(all_tags)


def _extract_tags_from_query(query: str) -> List[str]:
    """
    Extract subject tags from a query string (e.g., task_hint).

    Handles:
    1. File paths in the query (e.g., "working on website/index.html")
    2. General keywords (like work_area)

    Examples:
        "work on website/index.html" -> ["website"]
        "edit src/core/search.py" -> ["core", "search"]
        "dashboard UX improvements" -> ["dashboard"]
    """
    import re

    if not query:
        return []

    tags: Set[str] = set()

    # Extract file paths from query (patterns like path/to/file.ext)
    # Match paths with at least one slash and a file extension or known folder
    path_pattern = r'[\w\-\.]+/[\w\-\./]+'
    paths = re.findall(path_pattern, query)
    for path in paths:
        path_tags = extract_subject_tags_from_path(path)
        tags.update(path_tags)

    # Also extract like work_area (keywords)
    area_tags = _normalize_work_area_to_tags(query)
    tags.update(area_tags)

    return sorted(tags)


def _normalize_work_area_to_tags(work_area: str) -> List[str]:
    """
    Convert a work_area string to normalized tags.

    Examples:
        "core search" -> ["core", "search"]
        "website landing page" -> ["website"]
        "Windows installer" -> ["windows", "installer"]
    """
    if not work_area:
        return []

    tags: Set[str] = set()
    work_lower = work_area.lower()

    # Check against known folders/patterns
    for folder, folder_tags in FOLDER_TO_TAGS.items():
        if folder in work_lower and folder_tags:
            tags.update(folder_tags)

    for pattern, pattern_tags in FILE_PATTERNS.items():
        if pattern in work_lower:
            tags.update(pattern_tags)

    # Also extract individual words that match known tags
    known_tags = {"website", "dashboard", "core", "search", "server",
                  "macos", "windows", "installer", "tray", "mcp",
                  "api", "extension", "tests", "memory", "session"}

    words = work_lower.replace("/", " ").replace("-", " ").replace("_", " ").split()
    for word in words:
        if word in known_tags:
            tags.add(word)

    return sorted(tags)


def calculate_subject_confidence(tags: List[str], signals: Dict[str, Any]) -> float:
    """
    Calculate confidence score for detected subject.

    Based on observable signal quality:
    - task_hint signal: +0.5 (high confidence - from current user message)
    - File path signal present: +0.5 (strong signal)
    - Explicit work_area/query: +0.4 (declared intent)
    - Multiple tags detected: +0.1 (convergent signals)

    Args:
        tags: Detected subject tags
        signals: Signal dict with activity.file, intent.last_file, etc.

    Returns:
        Confidence score from 0.0 to 1.0

    Examples:
        >>> calculate_subject_confidence([], {})
        0.0
        >>> calculate_subject_confidence(['website'], {'activity.file': 'website/x.html'})
        0.5
        >>> calculate_subject_confidence(['website'], {'intent.work_area': 'website'})
        0.4
        >>> calculate_subject_confidence(['website'], {'task_hint': 'work on website'})
        0.5
    """
    # No tags = no confidence
    if not tags:
        return 0.0

    score = 0.0

    # task_hint is high confidence (from current user message)
    if signals.get("task_hint"):
        score += 0.5

    # File path signals (high confidence - involuntary)
    has_file_signal = bool(
        signals.get("activity.file") or
        signals.get("intent.last_file") or
        signals.get("solutions.files_changed")
    )
    if has_file_signal:
        score += 0.5

    # Explicit declaration signals (medium confidence - voluntary)
    has_explicit_signal = bool(
        signals.get("intent.work_area") or
        signals.get("query")
    )
    if has_explicit_signal:
        score += 0.4

    # Multiple tags = convergent signals (bonus)
    if len(tags) >= 2:
        score += 0.1

    return min(score, 1.0)


# Convenience function for quick subject detection from a single file
def get_file_subject(path: str) -> Optional[str]:
    """
    Get the primary subject for a file path.

    Returns the first (most specific) tag, or None if unknown.

    Examples:
        >>> get_file_subject("website/index.html")
        'website'
        >>> get_file_subject("src/core/search.py")
        'core'
    """
    tags = extract_subject_tags_from_path(path)
    return tags[0] if tags else None
