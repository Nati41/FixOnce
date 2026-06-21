"""
Memory Categories V1 - Universal memory taxonomy.

Categories classify memories by actionability, not just content.
Core question: "What should the developer do now?"

This module is transport-independent and language-agnostic.
"""

from typing import Literal, Dict, Any

# Category type
Category = Literal[
    "fix",        # Operational bug fix - has root_cause, action_now
    "decision",   # Choice made with reasoning
    "avoid",      # Caused problems, don't repeat
    "regression", # Was working, broke again
    "insight",    # Understanding gained, contextual
    "handoff",    # Continuation point for next session
    "work",       # Product work (features, refactors)
    "unknown",    # Not yet categorized
]

# Display mapping: category -> (icon, label)
CATEGORY_DISPLAY: Dict[str, tuple] = {
    "fix":        ("✅", "SOLVED BEFORE"),
    "decision":   ("📌", "ACTIVE DECISION"),
    "avoid":      ("🚫", "AVOID PATTERN"),
    "regression": ("⚠️", "KNOWN REGRESSION"),
    "insight":    ("💡", "RELATED CONTEXT"),
    "handoff":    ("📍", "CONTINUATION POINT"),
    "work":       ("🔧", "RELATED WORK"),
    "unknown":    ("❓", "RELATED MEMORY"),
}


def get_display(category: str) -> tuple:
    """Get (icon, label) for a category."""
    return CATEGORY_DISPLAY.get(category, CATEGORY_DISPLAY["unknown"])


def format_header(category: str) -> str:
    """Format category as display header: '✅ **SOLVED BEFORE**'"""
    icon, label = get_display(category)
    return f"{icon} **{label}**"


# Quality indicators
QUALITY_FIELDS = {
    "fix": ["root_cause", "action_now"],
    "decision": ["reason"],
    "avoid": ["reason"],
    "regression": ["original_fix", "trigger"],
    "insight": [],  # No required fields
    "handoff": ["next_step"],
    "work": [],  # No required fields
    "unknown": [],
}


def assess_quality(category: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess memory quality based on category requirements.

    Returns:
        {
            "quality": "high" | "medium" | "low",
            "missing": ["field1", "field2"],
            "actionable": True | False,
        }
    """
    required = QUALITY_FIELDS.get(category, [])
    missing = [f for f in required if not metadata.get(f)]

    # Check actionability
    has_action = bool(
        metadata.get("action_now") or
        metadata.get("solution") or
        metadata.get("next_step")
    )

    # Determine quality level
    if not missing and has_action:
        quality = "high"
    elif len(missing) <= 1 or has_action:
        quality = "medium"
    else:
        quality = "low"

    return {
        "quality": quality,
        "missing": missing,
        "actionable": has_action,
    }


def should_show_as_fix(category: str, metadata: Dict[str, Any]) -> bool:
    """
    Determine if memory should display as 'SOLVED BEFORE'.

    Only high-quality fixes should show as solved.
    Low-quality fixes downgrade to insight display.
    """
    if category != "fix":
        return False

    quality = assess_quality(category, metadata)
    return quality["quality"] in ("high", "medium")


# Backward compatibility: map old match_types to categories
MATCH_TYPE_TO_CATEGORY: Dict[str, str] = {
    "solution": "fix",
    "decision": "decision",
    "avoid": "avoid",
    "failed_attempt": "avoid",
    "insight": "insight",
    "context": "insight",
    "component": "work",
    "activity": "work",
}


def category_from_match_type(match_type: str) -> str:
    """Map legacy match_type to category."""
    return MATCH_TYPE_TO_CATEGORY.get(match_type, "unknown")
