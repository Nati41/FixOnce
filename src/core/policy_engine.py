"""
FixOnce Policy Engine - Real Policy Enforcement

This module provides:
1. Conflict detection between decisions
2. Policy validation before changes
3. Blocked state awareness
4. Decision supersession
"""

import re
from typing import Callable, List, Dict, Any, Optional, Tuple
from datetime import datetime

from core.intervention_policy import InterventionContext, evaluate_decision_conflict_gate


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
    "storage": ["store", "storage", "save", "persist", "אחסון"],
    "language": ["english", "hebrew", "language", "עברית", "שפה", "translation"],
    "ui": ["ui", "dashboard", "display", "show", "render", "interface"],
    "api": ["api", "endpoint", "route", "rest", "http"],
    "auth": ["auth", "login", "session", "token", "permission"],
    "data": ["data", "format", "schema", "structure", "json"],
    "infrastructure": ["cloud", "firebase", "firestore", "aws", "gcp", "azure", "remote", "server", "hosted"],
    "database": ["database", "db", "sql", "postgres", "postgresql", "mysql", "mongo", "mongodb", "firestore", "sqlite"],
}

# ============================================================
# NON-NEGOTIABLE CONSTRAINT PATTERNS
# ============================================================

# Maps non-negotiable phrases to the decision keywords they block
# Format: (non_negotiable_pattern, blocked_keywords)
NON_NEGOTIABLE_BLOCKERS = [
    # Local-only constraints block cloud/remote services
    (r"\blocal\s+only\b", ["cloud", "firebase", "firestore", "aws", "gcp", "azure", "remote", "hosted", "server"]),
    (r"\bno\s+cloud\b", ["cloud", "firebase", "firestore", "aws", "gcp", "azure", "remote", "hosted"]),
    (r"\bno\s+cloud\s+service", ["cloud", "firebase", "firestore", "aws", "gcp", "azure", "remote", "hosted"]),
    (r"\bno\s+external\s+service", ["cloud", "firebase", "firestore", "aws", "gcp", "azure", "external", "remote", "hosted"]),
    (r"\bno\s+external\s+storage", ["cloud", "firebase", "firestore", "aws", "gcp", "azure", "s3", "remote", "hosted"]),
    # No-database constraints block database usage
    (r"\bno\s+database\b", ["database", "db", "sql", "postgres", "postgresql", "mysql", "mongo", "mongodb", "firestore", "sqlite"]),
    # No-auth constraints
    (r"\bno\s+auth", ["auth", "authentication", "login", "oauth", "session"]),
]


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


def _matches_related_decision(existing_decision: str, related_decision_text: str) -> bool:
    """Return True when relation metadata explicitly targets this decision."""
    existing_normalized = " ".join(re.findall(r'\w+', existing_decision.lower()))
    related_normalized = " ".join(re.findall(r'\w+', (related_decision_text or "").lower()))
    if not existing_normalized or not related_normalized:
        return False
    return (
        existing_normalized == related_normalized
        or existing_normalized in related_normalized
        or related_normalized in existing_normalized
    )


def detect_antonym_conflict(text1: str, text2: str) -> Optional[Tuple[str, str, str]]:
    """
    Check if two texts contain semantic conflicts.

    Returns:
        None if no conflict detected.
        (term1, term2, strength) where strength is:
        - "HIGH": Explicit negation conflict (negated target appears in both texts)
        - "WEAK": Antonym pair match (may be false positive, should not block)
    """
    text1_lower = text1.lower()
    text2_lower = text2.lower()

    # Stop words that should not be considered as negation targets
    STOP_WORDS = {"the", "a", "an", "to", "in", "on", "at", "is", "are", "be", "we", "it",
                  "use", "store", "do", "for", "with", "from", "by", "as", "of", "and", "or",
                  "mvp", "v1", "v2", "phase", "version"}  # Also exclude version/phase markers

    def _get_negated_target(text: str, neg_word: str) -> Optional[str]:
        """Get the primary substantive word being negated (first 1-3 words after negation)."""
        # Match up to 3 words after negation to find the real target
        pattern = rf'\b{re.escape(neg_word)}\s+(\w+)(?:\s+(\w+))?(?:\s+(\w+))?'
        match = re.search(pattern, text.lower())
        if not match:
            return None
        # Check each word in order, return first substantive one
        for group in [match.group(1), match.group(2), match.group(3)]:
            if group and len(group) > 2 and group not in STOP_WORDS:
                return group
        return None

    # HIGH CONFIDENCE: Explicit negation conflicts
    # Only flag when the primary NEGATED TARGET appears in both texts.
    # "Do not use PostgreSQL" vs "Use PostgreSQL" → HIGH (postgresql in both)
    # "No external database" vs "Use local JSON" → None (external not in second)
    # "No external database in MVP" vs "Use local JSON in MVP" → None (MVP is context, not target)
    for neg in NEGATION_WORDS:
        if neg in text1_lower and neg not in text2_lower:
            negated_target = _get_negated_target(text1_lower, neg)
            if negated_target and negated_target in text2_lower:
                return (f"{neg} {negated_target}", negated_target, "HIGH")
        if neg in text2_lower and neg not in text1_lower:
            negated_target = _get_negated_target(text2_lower, neg)
            if negated_target and negated_target in text1_lower:
                return (negated_target, f"{neg} {negated_target}", "HIGH")

    # Check regex-based conflict patterns (explicit contradictions)
    for pattern1, pattern2 in CONFLICT_PATTERNS:
        if re.search(pattern1, text1_lower) and re.search(pattern2, text2_lower):
            return (pattern1, pattern2, "HIGH")
        if re.search(pattern2, text1_lower) and re.search(pattern1, text2_lower):
            return (pattern2, pattern1, "HIGH")

    # WEAK CONFIDENCE: Antonym pair matches
    # These often produce false positives (e.g., "use" + "avoid" in unrelated contexts)
    # Demoted to WEAK - should warn, not block
    def _is_negated(text: str, word: str) -> bool:
        for neg in NEGATION_WORDS:
            if re.search(rf'\b{re.escape(neg)}\b\s+\w*\s*{re.escape(word)}', text):
                return True
        return False

    for word1, word2 in ANTONYM_PAIRS:
        if word1 in text1_lower and word2 in text2_lower:
            if not _is_negated(text1_lower, word1) and not _is_negated(text2_lower, word2):
                return (word1, word2, "WEAK")
        if word2 in text1_lower and word1 in text2_lower:
            if not _is_negated(text1_lower, word2) and not _is_negated(text2_lower, word1):
                return (word2, word1, "WEAK")

    return None


def check_non_negotiable_violations(
    decision_text: str,
    non_negotiables: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Check if a decision violates any active non-negotiable constraints.

    Returns list of HIGH-severity conflicts for each violation.
    """
    if not non_negotiables:
        return []

    violations = []
    decision_lower = decision_text.lower()

    for constraint in non_negotiables:
        if not isinstance(constraint, dict):
            continue
        if constraint.get("status", "active") != "active":
            continue

        constraint_text = constraint.get("text", "").lower()
        if not constraint_text:
            continue

        for pattern, blocked_keywords in NON_NEGOTIABLE_BLOCKERS:
            if not re.search(pattern, constraint_text, re.IGNORECASE):
                continue

            for keyword in blocked_keywords:
                if keyword in decision_lower:
                    violations.append({
                        "type": "NON_NEGOTIABLE_VIOLATION",
                        "severity": "HIGH",
                        "existing_decision": constraint.get("text", ""),
                        "existing_reason": constraint.get("reason", "Project non-negotiable constraint"),
                        "existing_actor": constraint.get("actor", "user"),
                        "existing_actor_source": constraint.get("actor_source", "vision"),
                        "timestamp": constraint.get("timestamp", constraint.get("created_at", "")),
                        "topics": ["infrastructure", "constraint"],
                        "blocked_keyword": keyword,
                        "message": f"Violates non-negotiable: '{constraint.get('text', '')}' (blocked: '{keyword}')"
                    })
                    break
            else:
                continue
            break

    return violations


def check_avoid_pattern_conflicts(
    decision_text: str,
    avoid_patterns: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Check if a decision conflicts with any avoid patterns.

    Returns list of MEDIUM-severity conflicts for matches.
    """
    if not avoid_patterns:
        return []

    conflicts = []
    decision_lower = decision_text.lower()
    decision_words = set(re.findall(r'\w+', decision_lower))

    for pattern in avoid_patterns:
        if not isinstance(pattern, dict):
            continue

        what = (pattern.get("what", "") or "").lower()
        if not what:
            continue

        what_words = set(re.findall(r'\w+', what))
        overlap = decision_words & what_words

        if len(overlap) >= 2 or any(word in decision_lower for word in what_words if len(word) > 4):
            conflicts.append({
                "type": "AVOID_PATTERN_CONFLICT",
                "severity": "MEDIUM",
                "existing_decision": pattern.get("what", ""),
                "existing_reason": pattern.get("reason", "Marked as avoid pattern"),
                "existing_actor": pattern.get("actor", "unknown"),
                "existing_actor_source": pattern.get("actor_source", "avoid"),
                "timestamp": pattern.get("timestamp", ""),
                "topics": list(extract_topics(what)),
                "overlap": list(overlap),
                "message": f"Conflicts with avoid pattern: '{pattern.get('what', '')}'"
            })

    return conflicts


def detect_conflicts(
    new_decision: str,
    new_reason: str,
    existing_decisions: List[Dict[str, Any]],
    non_negotiables: Optional[List[Dict[str, Any]]] = None,
    avoid_patterns: Optional[List[Dict[str, Any]]] = None,
    threshold: float = 0.3,
    relation: str = "",
    related_decision_text: str = "",
) -> List[Dict[str, Any]]:
    """
    Detect potential conflicts between new decision and existing ones,
    non-negotiable constraints, and avoid patterns.

    Returns list of conflicts with severity and explanation.
    """
    conflicts = []
    new_text = f"{new_decision} {new_reason}"
    new_topics = extract_topics(new_text)
    relation = (relation or "").lower()
    relation_relaxes_target = relation in {"refines", "clarifies"}

    # Check non-negotiable violations first (highest priority)
    if non_negotiables:
        violations = check_non_negotiable_violations(new_text, non_negotiables)
        conflicts.extend(violations)

    # Check avoid pattern conflicts
    if avoid_patterns:
        avoid_conflicts = check_avoid_pattern_conflicts(new_text, avoid_patterns)
        conflicts.extend(avoid_conflicts)

    for existing in existing_decisions:
        # Skip superseded decisions
        if existing.get("superseded"):
            continue

        existing_text = f"{existing.get('decision', '')} {existing.get('reason', '')}"
        existing_topics = extract_topics(existing_text)
        topic_overlap = new_topics & existing_topics
        is_related_target = (
            relation_relaxes_target
            and _matches_related_decision(existing.get("decision", ""), related_decision_text)
        )

        # Check for semantic conflicts
        conflict_result = detect_antonym_conflict(new_text, existing_text)
        if conflict_result:
            if is_related_target:
                continue
            term1, term2, strength = conflict_result
            # HIGH strength = explicit negation conflict (block)
            # For HIGH conflicts, the shared word IS the topic (e.g., "postgresql")
            if strength == "HIGH":
                # Use detected topic overlap, or infer from the conflict term
                conflict_topics = list(topic_overlap) if topic_overlap else [term2]
                conflicts.append({
                    "type": "CONTRADICTION",
                    "severity": "HIGH",
                    "existing_decision": existing.get("decision", ""),
                    "existing_reason": existing.get("reason", ""),
                    "existing_actor": existing.get("actor", "unknown"),
                    "existing_actor_source": existing.get("actor_source", "none"),
                    "timestamp": existing.get("timestamp", ""),
                    "topics": conflict_topics,
                    "antonyms": (term1, term2),
                    "message": f"Direct contradiction detected: '{term1}' vs '{term2}' on topics: {', '.join(conflict_topics)}"
                })
                continue

            # WEAK conflicts require topic overlap to be meaningful
            if not topic_overlap:
                continue  # Antonym match without topic overlap - ignore

            # WEAK conflicts get MEDIUM severity - warn but don't block
            conflicts.append({
                "type": "POTENTIAL_CONFLICT",
                "severity": "MEDIUM",
                "existing_decision": existing.get("decision", ""),
                "existing_reason": existing.get("reason", ""),
                "existing_actor": existing.get("actor", "unknown"),
                "existing_actor_source": existing.get("actor_source", "none"),
                "timestamp": existing.get("timestamp", ""),
                "topics": list(topic_overlap),
                "antonyms": (term1, term2),
                "message": f"Potential conflict: '{term1}' and '{term2}' appear in related statements on topics: {', '.join(topic_overlap)}"
            })
            continue

        # For similarity check, require topic overlap
        if not topic_overlap:
            continue

        # Check similarity (medium severity)
        similarity = calculate_similarity(new_text, existing_text)
        if similarity > threshold:
            if is_related_target:
                continue
            conflicts.append({
                "type": "SIMILAR",
                "severity": "MEDIUM",
                "existing_decision": existing.get("decision", ""),
                "existing_reason": existing.get("reason", ""),
                "existing_actor": existing.get("actor", "unknown"),
                "existing_actor_source": existing.get("actor_source", "none"),
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
    non_negotiables: Optional[List[Dict[str, Any]]] = None,
    avoid_patterns: Optional[List[Dict[str, Any]]] = None,
    force: bool = False,
    gate_evaluator: Optional[Callable[[InterventionContext], Any]] = None,
    relation: str = "",
    related_decision_text: str = "",
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Validate a decision before logging.

    Returns:
        (is_valid, message, conflicts)
        - is_valid: True if decision can be logged
        - message: Explanation
        - conflicts: List of detected conflicts
    """
    conflicts = detect_conflicts(
        decision, reason, existing_decisions,
        non_negotiables=non_negotiables,
        avoid_patterns=avoid_patterns,
        relation=relation,
        related_decision_text=related_decision_text,
    )

    if not conflicts:
        return True, "No conflicts detected", []

    top_conflict = conflicts[0]
    evaluator = gate_evaluator or evaluate_decision_conflict_gate
    gate_result = evaluator(
        InterventionContext(
            tool_name="log_decision",
            decision_conflict_severity=top_conflict.get("severity", ""),
            extra={"conflicts": conflicts},
        )
    )

    if gate_result.level == "block" and not force:
        conflict = top_conflict
        provenance = (
            f"actor={conflict.get('existing_actor', 'unknown')}; "
            f"source={conflict.get('existing_actor_source', 'none')}; "
            f"timestamp={conflict.get('timestamp') or 'unknown'}"
        )
        return False, (
            f"🛑 BLOCKED: {conflict['message']}\n"
            f"Existing decision: \"{conflict['existing_decision']}\"\n"
            f"Existing decision provenance: {provenance}\n"
            f"Use force=true to override, or supersede the existing decision first."
        ), conflicts

    if gate_result.level == "block" and force:
        return True, (
            f"⚠️ OVERRIDE: Logging despite conflict.\n"
            f"Consider superseding the conflicting decision."
        ), conflicts

    # Warn-level conflicts are logged but surfaced for review.
    return True, (
        f"⚠️ WARNING: {conflicts[0]['message']}\n"
        f"Existing decision actor: {conflicts[0].get('existing_actor', 'unknown')} "
        f"({conflicts[0].get('existing_actor_source', 'none')}, "
        f"{conflicts[0].get('timestamp') or 'unknown'})\n"
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
    supersede_reason: str,
    attribution: Optional[Dict[str, Any]] = None,
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
    if attribution:
        decisions[found_idx]["superseded_by_actor"] = attribution.get("actor", "unknown")
        decisions[found_idx]["superseded_by_source"] = attribution.get("actor_source", "none")
        decisions[found_idx]["superseded_in_session"] = attribution.get("session_id", "unknown-session")

    # Add new decision
    if new_decision:
        replacement = {
            "type": "decision",
            "decision": new_decision,
            "reason": new_reason,
            "timestamp": datetime.now().isoformat(),
            "importance": "permanent",
            "supersedes": decisions[found_idx]["decision"]
        }
        if attribution:
            replacement.update(attribution)
        decisions.append(replacement)

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
