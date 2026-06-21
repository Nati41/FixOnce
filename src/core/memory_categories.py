"""
Memory Categories V1.1 - Universal memory taxonomy.

Categories classify memories by actionability, not just content.
Core question: "What should the developer do now?"

V1.1 adds content-based quality detection:
- Internal product work should NOT surface as SOLVED BEFORE
- Only actionable fixes with clear "do this now" guidance qualify

This module is transport-independent and language-agnostic.
"""

import re
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

# V1.1: Content patterns that indicate internal/product work, NOT actionable fixes
# These describe what was DONE, not what to DO NOW
PRODUCT_WORK_PATTERNS = [
    r'\bexpanded\b.*terms',                # "Expanded _ERROR_INVESTIGATION_TERMS"
    r'\badded\b.*\b(tests?|coverage|regression)\b',  # "Added regression tests"
    r'\bimproved\b.*\b(ranking|search|matching)\b',  # "Improved ranking"
    r'\badded\b.*\bsupport\b',             # "Added synonym support"
    r'\brefactored?\b',                    # "Refactored X"
    r'\bupdated?\b.*\b(module|class|function)\b',    # "Updated the module"
    r'\bimplemented\b.*\b(feature|v\d|phase)\b',     # "Implemented V2"
]

# V1.1: Patterns that indicate actionable fix guidance
# These tell the developer WHAT TO DO NOW
ACTIONABLE_FIX_PATTERNS = [
    r'\bcheck\b.*\bbefore\b',              # "Check status before parsing"
    r'\badd\b.*\b(null|undefined)\b.*\bcheck\b',     # "Add null check"
    r'\buse\b.*\b(optional chaining|\?\.|\.get\()',  # "Use optional chaining"
    r'\bwrap\b.*\b(try|catch)\b',          # "Wrap in try/catch"
    r'\bvalidate\b.*\b(input|response|data)\b',      # "Validate input"
    r'\breplace\b.*\bwith\b',              # "Replace X with Y"
    r'\bensure\b',                         # "Ensure X exists"
    r'\bhandle\b.*\b(error|exception|case)\b',       # "Handle the error case"
]


def _text_matches_patterns(text: str, patterns: list) -> bool:
    """Check if text matches any of the given regex patterns."""
    if not text:
        return False
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def is_product_work(metadata: Dict[str, Any]) -> bool:
    """
    Detect if memory describes internal product work rather than actionable fix.

    Product work examples (should NOT be SOLVED BEFORE):
    - "Expanded _ERROR_INVESTIGATION_TERMS"
    - "Added regression tests"
    - "Improved ranking algorithm"

    Returns True if this looks like product work, not an operational fix.
    """
    solution = str(metadata.get('solution', ''))
    text = str(metadata.get('text', ''))
    combined = f"{solution} {text}"

    return _text_matches_patterns(combined, PRODUCT_WORK_PATTERNS)


def has_actionable_guidance(metadata: Dict[str, Any]) -> bool:
    """
    Detect if memory contains actionable "do this now" guidance.

    Actionable examples (SHOULD be SOLVED BEFORE):
    - "Check response status before parsing"
    - "Use optional chaining for nested access"
    - "Add null check before accessing property"

    Returns True if this contains clear action guidance.
    """
    action_now = str(metadata.get('action_now', ''))
    solution = str(metadata.get('solution', ''))
    text = str(metadata.get('text', ''))

    # action_now field is the primary signal
    if action_now and len(action_now) > 10:
        return True

    # Check solution and text for actionable patterns
    combined = f"{solution} {text}"
    return _text_matches_patterns(combined, ACTIONABLE_FIX_PATTERNS)


def assess_quality(category: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess memory quality based on category requirements and content analysis.

    V1.1: Now checks content patterns to detect product work vs actionable fixes.

    Returns:
        {
            "quality": "high" | "medium" | "low",
            "missing": ["field1", "field2"],
            "actionable": True | False,
            "is_product_work": True | False,  # V1.1
        }
    """
    required = QUALITY_FIELDS.get(category, [])
    missing = [f for f in required if not metadata.get(f)]

    # V1.1: Detect product work vs actionable guidance
    detected_product_work = is_product_work(metadata)
    detected_actionable = has_actionable_guidance(metadata)

    # Check actionability - V1.1: must have actual guidance, not just any text
    # Also check 'text' field for MCP format compatibility
    has_action = bool(
        metadata.get("action_now") or
        metadata.get("solution") or
        metadata.get("next_step") or
        metadata.get("text")  # MCP format has formatted text
    )

    # V1.1: Product work is ALWAYS low quality for fix category
    if category == "fix" and detected_product_work and not detected_actionable:
        return {
            "quality": "low",
            "missing": missing + ["actionable_guidance"],
            "actionable": False,
            "is_product_work": True,
        }

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
        "is_product_work": detected_product_work,
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


def get_display_category(category: str, metadata: Dict[str, Any]) -> str:
    """
    Get the effective category for display purposes.

    V1.1: Product work in 'fix' category should display as 'work' or 'insight',
    not as 'fix' (which shows "SOLVED BEFORE").

    Returns the category to use with format_header().
    """
    if category != "fix":
        return category

    quality = assess_quality(category, metadata)

    # Product work displays as 'work' category
    if quality.get("is_product_work"):
        return "work"

    # Low quality non-product work displays as 'insight'
    if quality["quality"] == "low":
        return "insight"

    return category


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
