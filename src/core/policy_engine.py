"""
FixOnce Policy Engine - Real Policy Enforcement

This module provides:
1. Conflict detection between decisions
2. Policy validation before changes
3. Blocked state awareness
4. Decision supersession
"""

import re
from dataclasses import dataclass
from typing import Callable, List, Dict, Any, Optional, Tuple
from datetime import datetime

from core.intervention_policy import InterventionContext, evaluate_decision_conflict_gate


# ============================================================
# CONFLICT DETECTION PATTERNS
# ============================================================

# Negation patterns that reverse meaning
NEGATION_WORDS = ["never", "not", "don't", "doesn't", "won't", "cannot", "no", "without"]

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

SCOPE_KEYWORDS = {
    "ui": ["ui", "dashboard", "button", "wording", "label", "interface"],
    "retrieval": ["retrieval", "ranking", "filter", "filtering", "briefing"],
    "briefing": ["briefing", "briefings", "resume", "session resume"],
    "production": ["production", "prod"],
    "storage": ["disk", "persistent", "persist", "memory", "cache", "shelf", "storage"],
    "api": ["api", "endpoint", "route"],
    "global": ["global", "always", "never"],
    "external": ["external", "remote", "cloud"],
    "local": ["local"],
}

NEGATION_RE = re.compile(
    r"\b(?:do\s+not|don't|doesn't|never|cannot|can't|must\s+not|should\s+not|no|without)\b"
)


@dataclass(frozen=True)
class DecisionClaim:
    """Conservative subject+claim extraction for decision conflict checks."""
    domain: str
    target: str
    scope: str
    action: str
    value: str = ""

    @property
    def subject(self) -> str:
        return f"{self.domain}:{self.target}:{self.scope}"

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
        if any(
            re.search(rf'\b{re.escape(kw)}\b', text_lower)
            if len(kw) <= 3 and re.match(r'^\w+$', kw)
            else kw in text_lower
            for kw in keywords
        ):
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


def _normalize_decision_text(text: str) -> str:
    normalized = (text or "").lower()
    normalized = normalized.replace("subject shelf", "subjectshelf")
    normalized = normalized.replace("subject-shelf", "subjectshelf")
    normalized = normalized.replace("project librarian", "projectlibrarian")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _has_negation(text: str) -> bool:
    return bool(NEGATION_RE.search(text))


def _scope_from_text(text: str) -> str:
    matches = []
    for scope, keywords in SCOPE_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            matches.append(scope)
    if "local" in matches and "external" in matches:
        return "mixed"
    return matches[0] if matches else "general"


def _first_match(text: str, patterns: List[Tuple[str, str]]) -> Optional[str]:
    for pattern, value in patterns:
        if re.search(pattern, text):
            return value
    return None


def _extract_target_after_verb(text: str, verbs: Tuple[str, ...]) -> str:
    verb_group = "|".join(re.escape(verb) for verb in verbs)
    match = re.search(rf"\b(?:{verb_group})\s+([a-z0-9_ -]+?)(?:\s+(?:for|in|from|to|as|because|when|with)\b|$)", text)
    if not match:
        return ""
    words = [
        word for word in re.findall(r"[a-z0-9_]+", match.group(1))
        if word not in {"a", "an", "the", "all", "any", "we", "must", "should"}
    ]
    return "_".join(words[:4])


def _extract_decision_claim(text: str) -> Optional[DecisionClaim]:
    """
    Extract one high-confidence claim from a decision.

    This is deliberately pattern-based and conservative. If a decision does
    not match a known subject shape, it returns None and cannot block.
    """
    text = _normalize_decision_text(text)
    if not text:
        return None

    if "subjectshelf" in text:
        if re.search(r"\b(memory|in-memory|stay in memory|must stay)\b", text):
            return DecisionClaim("subjectshelf", "storage", "storage", "memory_only")
        if any(word in text for word in ("disk", "persist", "persistent", "save")):
            action = "persist_disk"
            if _has_negation(text):
                action = "memory_only"
            return DecisionClaim("subjectshelf", "storage", "storage", action)
        if "cache" in text or "presentation" in text or "memory" in text:
            return DecisionClaim("subjectshelf", "presentation_state", _scope_from_text(text), "describe")

    if "project knowledge terminology" in text:
        return DecisionClaim("terminology", "project_knowledge", "ui", "describe")
    if "session resume state" in text:
        return DecisionClaim("session_state", "resume", "briefing", "describe")

    if "ui wording" in text:
        return DecisionClaim("ui", "wording", "ui", "describe")
    if "retrieval behavior" in text or "dashboard retrieval rules" in text:
        return DecisionClaim("retrieval", "behavior", "retrieval", "describe")
    if "repair button" in text:
        return DecisionClaim("ui", "repair_button", "ui", "hide" if "hidden" in text else "show")

    if re.search(r"\brank(?:ing)?\b", text) and ("filter" in text or "filtering" in text):
        if re.search(r"\bglobal\s+ranking\s+first\b", text):
            return DecisionClaim("retrieval", "selection_order", "retrieval", "global_ranking_first")
        if re.search(r"\bsubject\s+filter(?:ing)?\s+first\b", text):
            return DecisionClaim("retrieval", "selection_order", "retrieval", "subject_filtering_first")

    if "stale decision" in text and "briefing" in text:
        action = "hide" if _has_negation(text) or "do not show" in text else "show"
        return DecisionClaim("briefing", "stale_decisions", "briefing", action)

    ui_label = re.search(r"\buse\s+([a-z][a-z0-9 _-]{1,40}?)\s+in\s+ui\b", text)
    if ui_label:
        label = "_".join(re.findall(r"[a-z0-9]+", ui_label.group(1))[:5])
        return DecisionClaim("ui", "product_label", "ui", "use_label", label)

    if "api data" in text and ("english" in text or "hebrew" in text or "עברית" in text):
        if "english" in text:
            value = "english"
        else:
            value = "hebrew"
        action = "forbid_value" if _has_negation(text) else "require_value"
        return DecisionClaim("api_data", "language", "storage", action, value)

    if "store" in text and ("english" in text or "hebrew" in text or "עברית" in text):
        if "english" in text:
            value = "english"
        else:
            value = "hebrew"
        action = "forbid_value" if _has_negation(text) else "require_value"
        return DecisionClaim("data", "language", "storage", action, value)

    if "postgresql" in text or "postgres" in text:
        action = "forbid" if _has_negation(text) or "avoid" in text else "require"
        return DecisionClaim("database", "postgresql", "storage", action)

    if "json" in text and re.search(r"\b(?:use|format|don't|do not|never|avoid)\b", text):
        action = "forbid" if _has_negation(text) or "avoid" in text else "require"
        scope = _scope_from_text(text)
        return DecisionClaim("data", "json_format", "storage" if scope == "general" else scope, action)

    if "external api" in text:
        action = "forbid" if _has_negation(text) else "require"
        return DecisionClaim("api", "api_access", "external", action)
    if "api access" in text:
        action = "forbid" if _has_negation(text) else "require"
        return DecisionClaim("api", "api_access", "api", action)

    if "external database" in text:
        action = "forbid" if _has_negation(text) else "require"
        return DecisionClaim("database", "database", "external", action)
    if re.search(r"\bdatabase\b", text):
        action = "forbid" if _has_negation(text) else "require"
        scope = "local" if "local" in text else "general"
        return DecisionClaim("database", "database", scope, action)

    target = _extract_target_after_verb(text, ("use", "provide"))
    if target and _has_negation(text):
        return DecisionClaim("general", target, _scope_from_text(text), "forbid")
    if target and re.search(r"\b(?:use|provide)\b", text):
        return DecisionClaim("general", target, _scope_from_text(text), "require")

    return None


def _claims_share_subject(claim1: DecisionClaim, claim2: DecisionClaim) -> bool:
    if claim1.domain != claim2.domain or claim1.target != claim2.target:
        return False
    if claim1.scope == claim2.scope:
        return True
    if "general" in {claim1.scope, claim2.scope}:
        return True
    return False


def _claim_incompatibility(claim1: DecisionClaim, claim2: DecisionClaim) -> Optional[str]:
    if not _claims_share_subject(claim1, claim2):
        return None

    opposite_actions = {
        ("require", "forbid"),
        ("persist_disk", "memory_only"),
        ("global_ranking_first", "subject_filtering_first"),
        ("show", "hide"),
    }
    actions = (claim1.action, claim2.action)
    if actions in opposite_actions or actions[::-1] in opposite_actions:
        return f"actions are incompatible: {claim1.action} vs {claim2.action}"

    if claim1.action == claim2.action == "require_value" and claim1.value and claim2.value and claim1.value != claim2.value:
        return f"required values differ: {claim1.value} vs {claim2.value}"
    if {claim1.action, claim2.action} == {"require_value", "forbid_value"} and claim1.value == claim2.value:
        return f"one claim requires {claim1.value}; the other forbids it"
    if claim1.action == claim2.action == "use_label" and claim1.value and claim2.value and claim1.value != claim2.value:
        return f"UI labels differ: {claim1.value} vs {claim2.value}"

    return None


def detect_antonym_conflict(text1: str, text2: str) -> Optional[Tuple[str, str, str]]:
    """
    Backward-compatible wrapper around Conflict Detection v2.

    v2 does not use generic antonym pairs. It only reports a high-confidence
    conflict when two extracted claims share the same subject and have
    incompatible normalized actions/values.
    """
    claim1 = _extract_decision_claim(text1)
    claim2 = _extract_decision_claim(text2)
    if not claim1 or not claim2:
        return None
    reason = _claim_incompatibility(claim1, claim2)
    if not reason:
        return None
    return (claim1.action or claim1.value, claim2.action or claim2.value, "HIGH")


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

        new_claim = _extract_decision_claim(new_text)
        existing_claim = _extract_decision_claim(existing_text)
        conflict_reason = (
            _claim_incompatibility(new_claim, existing_claim)
            if new_claim and existing_claim
            else None
        )
        if conflict_reason:
            if is_related_target:
                continue
            subject = existing_claim.subject
            conflicts.append({
                "type": "CONTRADICTION",
                "severity": "HIGH",
                "existing_decision": existing.get("decision", ""),
                "existing_reason": existing.get("reason", ""),
                "existing_actor": existing.get("actor", "unknown"),
                "existing_actor_source": existing.get("actor_source", "none"),
                "timestamp": existing.get("timestamp", ""),
                "topics": [existing_claim.domain, existing_claim.target],
                "subject": {
                    "domain": existing_claim.domain,
                    "target": existing_claim.target,
                    "scope": existing_claim.scope,
                },
                "existing_claim": {
                    "action": existing_claim.action,
                    "value": existing_claim.value,
                },
                "new_claim": {
                    "action": new_claim.action,
                    "value": new_claim.value,
                },
                "message": (
                    f"Direct contradiction on subject {subject}. "
                    f"Existing claim: {existing_claim.action}"
                    f"{':' + existing_claim.value if existing_claim.value else ''}. "
                    f"New claim: {new_claim.action}"
                    f"{':' + new_claim.value if new_claim.value else ''}. "
                    f"Why incompatible: {conflict_reason}."
                )
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
