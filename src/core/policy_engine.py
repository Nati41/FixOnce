"""
FixOnce Policy Engine - Real Policy Enforcement

This module provides:
1. Conflict detection between decisions
2. Policy validation before changes
3. Blocked state awareness
4. Decision supersession
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime


# ============================================================
# CONFLICT DETECTION PATTERNS
# ============================================================

# Keywords that indicate opposite meanings
ANTONYM_PAIRS = [
    ("english", "hebrew"),
    ("english", "עברית"),
    ("store", "don't store"),
    ("enable", "disable"),
    ("allow", "forbid"),
    ("allow", "prevent"),
    ("use", "avoid"),
    ("always", "never"),
    ("include", "exclude"),
    ("add", "remove"),
    ("sync", "async"),
    ("single", "multiple"),
    ("local", "remote"),
    ("internal", "external"),
]

# Negation patterns that reverse meaning
NEGATION_WORDS = ["never", "not", "don't", "doesn't", "won't", "cannot", "no", "without"]

# Context-sensitive conflict patterns (if both present, it's a conflict)
CONFLICT_PATTERNS = [
    # (pattern1, pattern2) - if text1 matches pattern1 and text2 matches pattern2, conflict
    (r"store.*english", r"store.*hebrew"),
    (r"store.*english", r"never.*english"),
    (r"data.*english", r"data.*hebrew"),
    (r"english.*only", r"hebrew"),
    (r"always.*english", r"never.*english"),
]

# Topic keywords that help identify related decisions
TOPIC_KEYWORDS = {
    "storage": ["store", "storage", "save", "persist", "database", "אחסון"],
    "language": ["english", "hebrew", "language", "עברית", "שפה", "translation"],
    "ui": ["ui", "dashboard", "display", "show", "render", "interface"],
    "api": ["api", "endpoint", "route", "rest", "http"],
    "auth": ["auth", "login", "session", "token", "permission"],
    "data": ["data", "format", "schema", "structure", "json"],
}


def extract_topics(text: str) -> set:
    """Extract topic categories from text."""
    text_lower = text.lower()
    topics = set()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            topics.add(topic)
    return topics


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate word-based similarity between two texts."""
    words1 = set(re.findall(r'\w+', text1.lower()))
    words2 = set(re.findall(r'\w+', text2.lower()))

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union)


def detect_antonym_conflict(text1: str, text2: str) -> Optional[Tuple[str, str]]:
    """Check if two texts contain antonym pairs suggesting conflict."""
    text1_lower = text1.lower()
    text2_lower = text2.lower()

    # Check antonym pairs
    for word1, word2 in ANTONYM_PAIRS:
        if word1 in text1_lower and word2 in text2_lower:
            return (word1, word2)
        if word2 in text1_lower and word1 in text2_lower:
            return (word2, word1)

    # Check negation conflicts (same topic but one negated)
    for neg in NEGATION_WORDS:
        if neg in text1_lower and neg not in text2_lower:
            # text1 has negation, text2 doesn't - potential conflict
            # Find common keywords
            words1 = set(re.findall(r'\w+', text1_lower)) - set(NEGATION_WORDS)
            words2 = set(re.findall(r'\w+', text2_lower))
            common = words1 & words2
            if len(common) >= 2:  # At least 2 common significant words
                return (f"{neg} + context", "positive context")
        if neg in text2_lower and neg not in text1_lower:
            words1 = set(re.findall(r'\w+', text1_lower))
            words2 = set(re.findall(r'\w+', text2_lower)) - set(NEGATION_WORDS)
            common = words1 & words2
            if len(common) >= 2:
                return ("positive context", f"{neg} + context")

    # Check regex-based conflict patterns
    for pattern1, pattern2 in CONFLICT_PATTERNS:
        if re.search(pattern1, text1_lower) and re.search(pattern2, text2_lower):
            return (pattern1, pattern2)
        if re.search(pattern2, text1_lower) and re.search(pattern1, text2_lower):
            return (pattern2, pattern1)

    return None


def detect_conflicts(
    new_decision: str,
    new_reason: str,
    existing_decisions: List[Dict[str, Any]],
    threshold: float = 0.3
) -> List[Dict[str, Any]]:
    """
    Detect potential conflicts between new decision and existing ones.

    Returns list of conflicts with severity and explanation.
    """
    conflicts = []
    new_text = f"{new_decision} {new_reason}"
    new_topics = extract_topics(new_text)

    for existing in existing_decisions:
        # Skip superseded decisions
        if existing.get("superseded"):
            continue

        existing_text = f"{existing.get('decision', '')} {existing.get('reason', '')}"
        existing_topics = extract_topics(existing_text)

        # Check topic overlap
        topic_overlap = new_topics & existing_topics
        if not topic_overlap:
            continue  # Different topics, no conflict

        # Check for antonym conflicts (high severity)
        antonyms = detect_antonym_conflict(new_text, existing_text)
        if antonyms:
            conflicts.append({
                "type": "CONTRADICTION",
                "severity": "HIGH",
                "existing_decision": existing.get("decision", ""),
                "existing_reason": existing.get("reason", ""),
                "timestamp": existing.get("timestamp", ""),
                "topics": list(topic_overlap),
                "antonyms": antonyms,
                "message": f"Direct contradiction detected: '{antonyms[0]}' vs '{antonyms[1]}' on topics: {', '.join(topic_overlap)}"
            })
            continue

        # Check similarity (medium severity)
        similarity = calculate_similarity(new_text, existing_text)
        if similarity > threshold:
            conflicts.append({
                "type": "SIMILAR",
                "severity": "MEDIUM",
                "existing_decision": existing.get("decision", ""),
                "existing_reason": existing.get("reason", ""),
                "timestamp": existing.get("timestamp", ""),
                "topics": list(topic_overlap),
                "similarity": round(similarity, 2),
                "message": f"Similar decision exists ({int(similarity*100)}% overlap) on topics: {', '.join(topic_overlap)}"
            })

    # Sort by severity (HIGH first)
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    conflicts.sort(key=lambda x: severity_order.get(x["severity"], 3))

    return conflicts


def validate_decision(
    decision: str,
    reason: str,
    existing_decisions: List[Dict[str, Any]],
    force: bool = False
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Validate a decision before logging.

    Returns:
        (is_valid, message, conflicts)
        - is_valid: True if decision can be logged
        - message: Explanation
        - conflicts: List of detected conflicts
    """
    conflicts = detect_conflicts(decision, reason, existing_decisions)

    if not conflicts:
        return True, "No conflicts detected", []

    high_severity = [c for c in conflicts if c["severity"] == "HIGH"]

    if high_severity and not force:
        conflict = high_severity[0]
        return False, (
            f"🛑 BLOCKED: {conflict['message']}\n"
            f"Existing decision: \"{conflict['existing_decision']}\"\n"
            f"Use force=true to override, or supersede the existing decision first."
        ), conflicts

    if high_severity and force:
        return True, (
            f"⚠️ OVERRIDE: Logging despite conflict.\n"
            f"Consider superseding the conflicting decision."
        ), conflicts

    # Medium severity - warn but allow
    return True, (
        f"⚠️ WARNING: {conflicts[0]['message']}\n"
        f"Decision logged, but review for consistency."
    ), conflicts


def check_blocked_components(
    goal: str,
    components: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Check if any blocked components are relevant to the goal.

    Returns list of blocked components that might affect the goal.
    """
    blocked = [c for c in components if c.get("status") == "blocked"]
    if not blocked:
        return []

    goal_lower = goal.lower()
    goal_words = set(re.findall(r'\w+', goal_lower))

    relevant_blocked = []
    for comp in blocked:
        comp_name = comp.get("name", "").lower()
        comp_desc = comp.get("desc", "").lower()
        comp_words = set(re.findall(r'\w+', f"{comp_name} {comp_desc}"))

        # Check for word overlap
        overlap = goal_words & comp_words
        if len(overlap) >= 2 or any(word in goal_lower for word in [comp_name]):
            relevant_blocked.append({
                "name": comp.get("name"),
                "desc": comp.get("desc"),
                "overlap": list(overlap)
            })

    return relevant_blocked


def supersede_decision(
    decisions: List[Dict[str, Any]],
    old_decision_text: str,
    new_decision: str,
    new_reason: str,
    supersede_reason: str
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Mark an old decision as superseded and optionally add new one.

    Returns:
        (success, message, updated_decisions)
    """
    # Find the decision to supersede
    found_idx = None
    for idx, dec in enumerate(decisions):
        if dec.get("decision", "").lower() == old_decision_text.lower():
            found_idx = idx
            break
        # Also try partial match
        if old_decision_text.lower() in dec.get("decision", "").lower():
            found_idx = idx
            break

    if found_idx is None:
        return False, f"Decision not found: '{old_decision_text[:50]}...'", decisions

    # Mark as superseded
    decisions[found_idx]["superseded"] = True
    decisions[found_idx]["superseded_at"] = datetime.now().isoformat()
    decisions[found_idx]["superseded_by"] = new_decision
    decisions[found_idx]["supersede_reason"] = supersede_reason

    # Add new decision
    if new_decision:
        decisions.append({
            "type": "decision",
            "decision": new_decision,
            "reason": new_reason,
            "timestamp": datetime.now().isoformat(),
            "importance": "permanent",
            "supersedes": decisions[found_idx]["decision"]
        })

    return True, f"Superseded: '{decisions[found_idx]['decision'][:50]}...'", decisions


def get_active_decisions(decisions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Get only non-superseded decisions."""
    return [d for d in decisions if not d.get("superseded")]


def format_policy_status(
    decisions: List[Dict[str, Any]],
    components: List[Dict[str, Any]]
) -> str:
    """Format current policy status for display."""
    active = get_active_decisions(decisions)
    superseded = [d for d in decisions if d.get("superseded")]
    blocked = [c for c in components if c.get("status") == "blocked"]

    lines = ["## Policy Status\n"]

    lines.append(f"**Active Decisions:** {len(active)}")
    lines.append(f"**Superseded:** {len(superseded)}")
    lines.append(f"**Blocked Components:** {len(blocked)}")

    if blocked:
        lines.append("\n### ⚠️ Blocked Components")
        for comp in blocked:
            lines.append(f"- **{comp.get('name')}**: {comp.get('desc', 'No description')}")

    return "\n".join(lines)
