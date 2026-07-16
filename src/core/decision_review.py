"""
General pre-save review for knowledge records (decisions, solved bugs).

The semantic index is used only to retrieve likely related active records.
Canonical state and IDs always come from memory[config.memory_key].
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
import hashlib
import re
import time


@dataclass
class KnowledgeTypeConfig:
    """Field mapping for knowledge type-specific behavior."""
    memory_key: str       # "decisions" or "solutions"
    text_field: str       # "decision" or "problem"
    reason_field: str     # "reason" or "solution"
    doc_type: str         # For semantic search
    id_prefix: str        # "dec_" or "sol_"


DECISION_CONFIG = KnowledgeTypeConfig(
    memory_key="decisions",
    text_field="decision",
    reason_field="reason",
    doc_type="decision",
    id_prefix="dec_",
)

SOLUTION_CONFIG = KnowledgeTypeConfig(
    memory_key="solutions",
    text_field="problem",
    reason_field="solution",
    doc_type="solution",
    id_prefix="sol_",
)


class RelationshipType(str, Enum):
    SAME = "same"
    EXTENDS = "extends"
    EXCEPTION_TO = "exception_to"
    SUPERSEDES = "supersedes"
    POTENTIAL_CONFLICT = "potential_conflict"
    UNRELATED = "unrelated"
    UNDETERMINED = "undetermined"


class ResolutionAction(str, Enum):
    ACKNOWLEDGE_EXISTING = "acknowledge_existing"
    SAVE_AS_EXTENDS = "save_as_extends"
    SAVE_AS_EXCEPTION = "save_as_exception"
    SUPERSEDE_EXISTING = "supersede_existing"
    SAVE_ANYWAY_UNDER_REVIEW = "save_anyway_under_review"
    CANCEL = "cancel"


@dataclass
class CandidateDecision:
    id: str
    text: str
    reason: str
    similarity_score: float
    relationship: RelationshipType
    explanation: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewResult:
    requires_review: bool
    proposed_text: str
    proposed_reason: str
    candidates: List[CandidateDecision]
    primary_candidate: Optional[CandidateDecision] = None
    allowed_actions: List[ResolutionAction] = field(default_factory=list)
    message: str = ""
    retrieval: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "requires_review": self.requires_review,
            "proposed_decision": {
                "text": self.proposed_text,
                "reason": self.proposed_reason,
            },
            "candidates": [
                {
                    "id": candidate.id,
                    "text": candidate.text,
                    "reason": candidate.reason,
                    "similarity_score": round(candidate.similarity_score, 2),
                    "relationship": candidate.relationship.value,
                    "explanation": candidate.explanation,
                    "confidence": round(candidate.confidence, 2),
                }
                for candidate in self.candidates
            ],
            "allowed_actions": [action.value for action in self.allowed_actions],
            "message": self.message,
            "retrieval": self.retrieval,
        }
        if self.primary_candidate:
            result["primary_candidate"] = {
                "id": self.primary_candidate.id,
                "text": self.primary_candidate.text,
                "relationship": self.primary_candidate.relationship.value,
                "explanation": self.primary_candidate.explanation,
            }
        return result


GENERIC_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when",
    "while", "for", "to", "of", "in", "on", "at", "by", "from", "as",
    "with", "without", "into", "before", "after", "over", "under", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "shall",
    "can", "may", "might", "must", "all", "any", "each", "every", "this",
    "that", "these", "those", "it", "its", "we", "our", "use", "uses",
    "using", "used", "via", "per", "new", "old", "existing", "decision",
    "decisions", "system", "project", "data",
}

EXCEPTION_CUES = {
    "bypass", "skip", "omit", "exclude", "except", "exception", "unless",
}

# Past-tense forms of exception cues - when these appear in the problem description,
# they describe a bug (something WAS omitted) rather than proposing an exception
EXCEPTION_PAST_TENSE = {
    "bypassed", "skipped", "omitted", "excluded", "excepted",
}

# Implementation verbs - when solution starts with these, exception cues describe
# code behavior (what the fix DOES) rather than proposing a policy exception
IMPLEMENTATION_VERBS = {
    "added", "add", "adds", "adding",
    "fixed", "fix", "fixes", "fixing",
    "implemented", "implement", "implements", "implementing",
    "updated", "update", "updates", "updating",
    "changed", "change", "changes", "changing",
    "modified", "modify", "modifies", "modifying",
    "included", "include", "includes", "including",
}

REPLACEMENT_CUES = {
    "replace", "replaces", "replaced", "replacement", "instead",
    "supersede", "supersedes", "superseded", "deprecate", "deprecates",
    "migrate", "migrates", "switch", "switches",
}

REASON_REPLACEMENT_CUES = {
    "replace", "replaces", "replaced", "replacement", "instead",
    "supersede", "supersedes", "superseded",
}

REPLACEMENT_PHRASES = [
    "replace previous",
    "replace the previous",
    "replace existing",
    "replace the existing",
    "instead of",
    "rather than",
]

STRICT_CUES = {
    "must", "required", "require", "requires", "mandatory", "always",
    "never", "immutable", "enforced", "only",
}

PERMISSIVE_OR_WEAKENING_CUES = {
    "may", "optional", "allow", "allows", "permit", "permits", "can",
    "bypass", "skip", "without", "plaintext", "regenerate", "regenerating",
}

EXTENSION_CUES = {
    "extend", "extends", "add", "adds", "include", "includes", "also",
    "additional",
}

REVERSAL_CUES = {
    "keep", "keeps", "maintain", "maintains", "stay", "stays", "retain",
    "retains", "continue", "continues", "preserve", "preserves", "remain",
    "remains", "stick", "sticks", "revert", "reverts", "restore", "restores",
}

DECOUPLING_PHRASES = [
    "independent from", "independent of",
    "decoupled from", "decoupled of",
    "separate from", "separated from",
    "agnostic", "transport-agnostic", "framework-agnostic",
    "isolated from", "abstracted from",
]

RULE_VIOLATION_CUES = {
    "bypass", "bypasses", "bypassing",
    "skip", "skips", "skipping",
    "ignore", "ignores", "ignoring",
    "does not apply", "do not apply",
    "not required", "not mandatory",
}

OPPOSITION_PAIRS = [
    ({"automatic", "automatically"}, {"manual", "manually"}),
    ({"always", "every", "all"}, {"only when", "only if", "explicitly requested"}),
    ({"never"}, {"should", "must", "will"}),
    ({"cascade"}, {"not cascade", "never cascade"}),
    ({"backward compatible", "compatible"}, {"breaking", "break"}),
]

SUBJECT_NON_DOMAIN_TERMS = {
    "only", "all", "every", "always", "never",
    "manual", "manually", "automatic", "automatically",
    "explicit", "explicitly", "requested",
    "must", "may", "should", "can",
    # Generic verbs/actions that don't indicate domain overlap
    "include", "includes", "included", "including",
    "add", "adds", "added", "adding",
    "update", "updates", "updated", "updating",
    "show", "shows", "showed", "showing",
    "fix", "fixes", "fixed", "fixing",
    "change", "changes", "changed", "changing",
    # Generic nouns
    "activity", "type", "data", "payload", "row", "final",
    # Timestamps/IDs (numbers) - handled separately
}

STEM_RULES = [
    ("ingly", ""),
    ("edly", ""),
    ("ation", "at"),
    ("tion", "t"),
    ("sion", ""),
    ("ment", ""),
    ("ness", ""),
    ("able", ""),
    ("ible", ""),
    ("ing", ""),
    ("ed", ""),
    ("ly", ""),
    ("es", ""),
    ("s", ""),
]


def _log(message: str) -> None:
    try:
        print(f"[DecisionReview] {message}")
    except Exception:
        pass


def simple_stem(word: str) -> str:
    """Small generic stemmer, extracted from the existing semantic engine style."""
    if len(word) <= 4:
        return word
    for suffix, replacement in STEM_RULES:
        if suffix == "s" and word.endswith("ss"):
            continue
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            stemmed = word[: -len(suffix)] + replacement
            if len(stemmed) > 4 and stemmed.endswith("e"):
                stemmed = stemmed[:-1]
            if len(stemmed) > 4 and stemmed[-1:] == stemmed[-2:-1] and stemmed[-1] not in {"s"}:
                stemmed = stemmed[:-1]
            return stemmed
    return word


def _normalize_text(text: Any) -> str:
    return " ".join(re.findall(r"\w+", str(text or "").lower()))


def _raw_tokens(text: str) -> Set[str]:
    return set(re.findall(r"\b\w+\b", (text or "").lower()))


def _tokens(text: str, *, keep_stopwords: bool = False) -> Set[str]:
    words = re.findall(r"\b\w+\b", (text or "").lower())
    tokens = set()
    for word in words:
        if len(word) < 3:
            continue
        if not keep_stopwords and word in GENERIC_STOPWORDS:
            continue
        tokens.add(simple_stem(word))
    return tokens


def _jaccard(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _overlap_ratio(left: Set[str], right: Set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _suffix_aware_overlap(left: Set[str], right: Set[str], require_direct: bool = True) -> int:
    """
    Count additional overlaps from derivational suffix relationships.

    Handles "-age" suffix (storage/stores) safely:
    - Only matches when the base stem exists in the other set
    - Requires stem length >= 4 to avoid false positives (us/usage)
    - When require_direct=True, only counts if there's already direct overlap
      (prevents package/pack, message/mess false positives on unrelated topics)
    """
    if require_direct and not (left & right):
        return 0
    bonus = 0
    seen_pairs = set()
    for token in left:
        if token.endswith("ag") or token.endswith("age"):
            stem = token[:-2] if token.endswith("ag") else token[:-3]
            if len(stem) >= 4 and stem in right and (token, stem) not in seen_pairs:
                seen_pairs.add((token, stem))
                bonus += 1
    for token in right:
        if token.endswith("ag") or token.endswith("age"):
            stem = token[:-2] if token.endswith("ag") else token[:-3]
            if len(stem) >= 4 and stem in left and (token, stem) not in seen_pairs:
                seen_pairs.add((token, stem))
                bonus += 1
    return bonus


def _overlap_with_suffixes(left: Set[str], right: Set[str]) -> float:
    """Overlap ratio including derivational suffix relationships."""
    if not left or not right:
        return 0.0
    direct = len(left & right)
    suffix_bonus = _suffix_aware_overlap(left, right, require_direct=True)
    total = direct + suffix_bonus
    return total / min(len(left), len(right))


def record_id_for(record: Dict[str, Any], config: KnowledgeTypeConfig) -> str:
    """Generate ID for any knowledge record using config field mapping."""
    if record.get("id"):
        return str(record["id"])
    payload = (
        f"{_normalize_text(record.get(config.text_field, ''))}|"
        f"{_normalize_text(record.get(config.reason_field, ''))}"
    )
    return f"{config.id_prefix}{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def decision_id_for(decision: Dict[str, Any]) -> str:
    """Backward-compatible wrapper for decision ID generation."""
    return record_id_for(decision, DECISION_CONFIG)


def solution_id_for(solution: Dict[str, Any]) -> str:
    """Generate ID for a solved bug record."""
    return record_id_for(solution, SOLUTION_CONFIG)


def _active_records(memory: Dict[str, Any], config: KnowledgeTypeConfig) -> List[Dict[str, Any]]:
    """Get active records of any knowledge type using config field mapping."""
    active = []
    for record in memory.get(config.memory_key, []):
        if not isinstance(record, dict):
            continue
        if record.get("superseded"):
            continue
        if record.get("status") not in (None, "", "active"):
            continue
        active.append(record)
    return active


def _active_decisions(memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Backward-compatible wrapper for active decisions."""
    return _active_records(memory, DECISION_CONFIG)


def _semantic_key(text: str, reason: str = "") -> str:
    return _normalize_text(f"{text} {reason}")[:500]


def _semantic_candidates(
    query: str,
    active: List[Dict[str, Any]],
    project_id: Optional[str],
    semantic_search_fn: Optional[Callable[..., Iterable[Any]]],
    limit: int,
    min_score: float,
    timeout_ms: int,
    config: KnowledgeTypeConfig = DECISION_CONFIG,
) -> Tuple[List[Tuple[Dict[str, Any], float, str]], Dict[str, Any]]:
    meta = {"source": "semantic", "used": False, "elapsed_ms": 0.0, "failures": []}
    if not project_id or not semantic_search_fn:
        meta["failures"].append("semantic_unavailable")
        return [], meta

    by_id = {record_id_for(d, config): d for d in active}
    by_text = {
        _semantic_key(d.get(config.text_field, ""), d.get(config.reason_field, "")): d
        for d in active
    }

    started = time.perf_counter()
    try:
        results = list(semantic_search_fn(
            project_id,
            query,
            k=max(limit * 3, 10),
            doc_type=config.doc_type,
            min_score=min_score,
        ))
    except Exception as exc:
        meta["failures"].append(f"semantic_exception:{exc.__class__.__name__}")
        _log(f"semantic retrieval failed open: {exc}")
        return [], meta
    finally:
        meta["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)

    if meta["elapsed_ms"] > timeout_ms:
        meta["failures"].append("semantic_timeout")
        _log(f"semantic retrieval exceeded budget: {meta['elapsed_ms']}ms")
        return [], meta

    candidates = []
    unmapped = 0
    seen = set()
    for result in results:
        metadata = getattr(result, "metadata", {}) or {}
        score = float(getattr(result, "score", 0.0) or 0.0)
        record = None
        for key in ("decision_id", "solution_id", "id", "canonical_id"):
            if metadata.get(key) and str(metadata[key]) in by_id:
                record = by_id[str(metadata[key])]
                break
        if record is None:
            text = metadata.get(config.text_field) or getattr(result, "text", "")
            reason = metadata.get(config.reason_field, "")
            record = by_text.get(_semantic_key(text, reason))
        if record is None:
            unmapped += 1
            continue
        rec_id = record_id_for(record, config)
        if rec_id in seen:
            continue
        seen.add(rec_id)
        candidates.append((record, score, "semantic"))

    if unmapped:
        meta["failures"].append(f"unmapped_results:{unmapped}")
        _log(f"semantic returned {unmapped} {config.doc_type} result(s) without canonical active mapping")
    meta["used"] = bool(candidates)
    return candidates[:limit], meta


def _lexical_candidates(
    query: str,
    active: List[Dict[str, Any]],
    limit: int,
    config: KnowledgeTypeConfig = DECISION_CONFIG,
) -> List[Tuple[Dict[str, Any], float, str]]:
    query_tokens = _tokens(query)
    proposed_part = query.split(". Reason:")[0] if ". Reason:" in query else query
    proposed_tokens = _tokens(proposed_part)
    scored = []
    for record in active:
        record_text = record.get(config.text_field, "")
        combined = f"{record_text} {record.get(config.reason_field, '')}"
        record_tokens = _tokens(record_text)
        combined_tokens = _tokens(combined)
        score = max(
            _jaccard(query_tokens, combined_tokens),
            _overlap_ratio(query_tokens, combined_tokens) * 0.75,
            _overlap_ratio(query_tokens, record_tokens) * 0.75,
            _overlap_ratio(proposed_tokens, record_tokens) * 0.75,
            _overlap_with_suffixes(proposed_tokens, record_tokens) * 0.75,
        )
        if score >= 0.18:
            scored.append((record, score, "lexical"))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def retrieve_candidates(
    new_text: str,
    new_reason: str,
    memory: Dict[str, Any],
    *,
    project_id: Optional[str] = None,
    semantic_search_fn: Optional[Callable[..., Iterable[Any]]] = None,
    limit: int = 5,
    semantic_min_score: float = 0.45,
    timeout_ms: int = 750,
    config: KnowledgeTypeConfig = DECISION_CONFIG,
) -> Tuple[List[Tuple[Dict[str, Any], float, str]], Dict[str, Any]]:
    active = _active_records(memory, config)
    query = f"{new_text}. Reason: {new_reason}"
    semantic, meta = _semantic_candidates(
        query, active, project_id, semantic_search_fn, limit, semantic_min_score, timeout_ms, config
    )
    if semantic:
        return semantic, meta
    meta["source"] = "lexical_fallback"
    lexical = _lexical_candidates(query, active, limit, config)
    return lexical, meta


def _contains_any(tokens: Set[str], cues: Set[str]) -> bool:
    tokens = {simple_stem(token) for token in tokens}
    cue_tokens = {simple_stem(cue) for cue in cues}
    return bool(tokens & cue_tokens)


def _has_phrase(text: str, phrases: Iterable[str]) -> bool:
    lower = f" {_normalize_text(text)} "
    return any(f" {_normalize_text(phrase)} " in lower for phrase in phrases)


def _has_replacement_signal(text: str) -> bool:
    return _contains_any(_raw_tokens(text), REPLACEMENT_CUES) or _has_phrase(text, REPLACEMENT_PHRASES)


def _has_reason_replacement_signal(text: str) -> bool:
    return _contains_any(_raw_tokens(text), REASON_REPLACEMENT_CUES) or _has_phrase(text, REPLACEMENT_PHRASES)


def _has_meaningful_subject_overlap(left: Set[str], right: Set[str]) -> bool:
    """Return true only when overlap contains at least one domain/content term."""
    excluded = {simple_stem(token) for token in SUBJECT_NON_DOMAIN_TERMS}
    overlap = left & right
    # Also exclude pure numeric tokens (timestamps, IDs, version numbers)
    meaningful = {
        token for token in overlap
        if token not in excluded
        and simple_stem(token) not in excluded
        and not token.isdigit()  # Pure numbers like "20260715"
        and not (len(token) >= 6 and token.replace("-", "").replace("_", "").isdigit())  # Dated IDs
    }
    return bool(meaningful)


def _has_opposition(existing_text: str, new_text: str) -> bool:
    """Check if existing and proposed texts express opposing intents."""
    existing_lower = existing_text.lower()
    new_lower = new_text.lower()
    for side_a, side_b in OPPOSITION_PAIRS:
        a_in_existing = any(term in existing_lower for term in side_a)
        b_in_new = any(term in new_lower for term in side_b)
        a_in_new = any(term in new_lower for term in side_a)
        b_in_existing = any(term in existing_lower for term in side_b)
        if (a_in_existing and b_in_new) or (b_in_existing and a_in_new):
            return True
    return False


def classify_relationship(
    new_text: str,
    new_reason: str,
    existing_text: str,
    existing_reason: str,
    *,
    retrieval_score: float = 0.0,
    retrieval_source: str = "",
) -> Tuple[RelationshipType, str, float]:
    new_combined = f"{new_text} {new_reason}"
    existing_combined = f"{existing_text} {existing_reason}"
    new_tokens = _tokens(new_combined)
    existing_tokens = _tokens(existing_combined)
    new_raw = _raw_tokens(new_text)
    existing_raw = _raw_tokens(existing_combined)
    overlap = new_tokens & existing_tokens
    overlap_strength = _overlap_ratio(new_tokens, existing_tokens)

    # Check replacement signals FIRST - even if text is identical, a replacement
    # solution should trigger review, not silent update
    replacement = _has_replacement_signal(new_text) or _has_reason_replacement_signal(new_reason)

    # Also check if the reason/solution is materially different
    reason_jaccard = _jaccard(_tokens(new_reason), _tokens(existing_reason))
    materially_different_reason = reason_jaccard < 0.5 and len(new_reason) > 20 and len(existing_reason) > 20

    # If replacement signal is present or reason is materially different,
    # skip the SAME early return and evaluate properly
    if not replacement and not materially_different_reason:
        if _normalize_text(new_text) == _normalize_text(existing_text):
            # Also require similar reason for true SAME
            if reason_jaccard >= 0.7:
                return RelationshipType.SAME, "Exact duplicate of active decision", 0.98

        if _jaccard(new_tokens, existing_tokens) >= 0.82 and new_tokens:
            # Also require similar reason for true SAME
            if reason_jaccard >= 0.6:
                return RelationshipType.SAME, "Near duplicate of active decision", 0.9
    # Exception detection: Check if exception cue is in the SOLUTION (proposing to omit)
    # vs just in the PROBLEM description in past tense (describing something WAS omitted)
    problem_raw = _raw_tokens(new_text)
    solution_raw = _raw_tokens(new_reason)

    # Check for exception cues in the solution - but only if NOT describing an implementation
    # "Added code to skip filters" = implementation (not exception proposal)
    # "Health checks may skip auth" = policy proposal (exception)
    solution_has_implementation_verb = _contains_any(solution_raw, IMPLEMENTATION_VERBS)
    exception_in_solution = _contains_any(solution_raw, EXCEPTION_CUES) and not solution_has_implementation_verb

    # Check for exception cues in problem - but only count them if NOT in past tense
    # Past tense in problem = describing a bug, not proposing an exception
    # Note: Check actual word forms (not stemmed) for past tense detection
    problem_text_lower = new_text.lower()
    problem_has_past_tense_exception = any(past in problem_text_lower for past in EXCEPTION_PAST_TENSE)
    exception_in_problem = _contains_any(problem_raw, EXCEPTION_CUES)
    exception_cues_valid = exception_in_solution or (exception_in_problem and not problem_has_past_tense_exception)

    exception_phrase = _has_phrase(new_combined, ["without", "except for"])
    decoupling = _has_phrase(new_combined, DECOUPLING_PHRASES)
    rule_violation = _contains_any(problem_raw, RULE_VIOLATION_CUES)
    exception = (exception_cues_valid or exception_phrase) and (rule_violation or not decoupling)
    strict_existing = _contains_any(existing_raw, STRICT_CUES)
    permissive_new = _contains_any(new_raw, PERMISSIVE_OR_WEAKENING_CUES)
    extension = _contains_any(new_raw, EXTENSION_CUES)
    replacement_existing = _contains_any(existing_raw, REPLACEMENT_CUES)
    reversal_new = _contains_any(new_raw, REVERSAL_CUES)

    has_meaningful_subject = _has_meaningful_subject_overlap(new_tokens, existing_tokens) or retrieval_score >= 0.58

    if replacement and has_meaningful_subject:
        return RelationshipType.SUPERSEDES, "Explicit replacement wording targets a related active decision", 0.86

    if exception and has_meaningful_subject:
        return RelationshipType.EXCEPTION_TO, "Explicit scoped exception wording targets a related active decision", 0.82

    if strict_existing and permissive_new and has_meaningful_subject:
        return RelationshipType.POTENTIAL_CONFLICT, "Strict existing rule and permissive proposed rule are related", 0.74

    if replacement_existing and reversal_new and has_meaningful_subject:
        return RelationshipType.POTENTIAL_CONFLICT, "Existing decision proposes replacing something that the new decision wants to keep", 0.78

    if extension and has_meaningful_subject and not (exception or replacement or permissive_new):
        return RelationshipType.EXTENDS, "Proposed decision appears to add compatible scope to an active decision", 0.72

    existing_text_tokens = _tokens(existing_text)
    new_text_tokens = _tokens(new_text)
    if existing_text_tokens:
        containment = len(existing_text_tokens & new_text_tokens) / len(existing_text_tokens)
        additions = new_text_tokens - existing_text_tokens
        structural_extension = (
            containment >= 0.75
            and len(additions) >= 1
            and not (replacement or exception or permissive_new)
        )
        if structural_extension and has_meaningful_subject:
            return RelationshipType.EXTENDS, "Proposed preserves existing decision and adds additional scope", 0.70

    if retrieval_source == "semantic" and retrieval_score >= 0.62:
        return RelationshipType.UNDETERMINED, "Semantically related but no deterministic relationship evidence", 0.55

    # Same problem but materially different solution approach - potential conflict
    # This catches cases where someone proposes a different fix strategy without
    # explicit replacement wording
    if materially_different_reason and has_meaningful_subject:
        text_jaccard = _jaccard(_tokens(new_text), _tokens(existing_text))
        if text_jaccard >= 0.6:  # Problem is substantially similar
            return RelationshipType.POTENTIAL_CONFLICT, "Same subject with materially different approach - may supersede or conflict with existing", 0.72

    if has_meaningful_subject and _has_opposition(existing_text, new_text):
        return RelationshipType.POTENTIAL_CONFLICT, "Proposed decision expresses opposing intent to existing decision", 0.72

    return RelationshipType.UNRELATED, "No concrete relationship found", 0.8


def _allowed_actions(relationship: RelationshipType) -> List[ResolutionAction]:
    if relationship == RelationshipType.SAME:
        return [ResolutionAction.ACKNOWLEDGE_EXISTING, ResolutionAction.CANCEL]
    if relationship == RelationshipType.EXTENDS:
        return [ResolutionAction.SAVE_AS_EXTENDS, ResolutionAction.CANCEL]
    if relationship == RelationshipType.EXCEPTION_TO:
        return [
            ResolutionAction.SAVE_AS_EXCEPTION,
            ResolutionAction.SAVE_ANYWAY_UNDER_REVIEW,
            ResolutionAction.CANCEL,
        ]
    if relationship == RelationshipType.SUPERSEDES:
        return [ResolutionAction.SUPERSEDE_EXISTING, ResolutionAction.CANCEL]
    if relationship == RelationshipType.POTENTIAL_CONFLICT:
        return [ResolutionAction.SUPERSEDE_EXISTING, ResolutionAction.SAVE_ANYWAY_UNDER_REVIEW, ResolutionAction.CANCEL]
    if relationship == RelationshipType.UNDETERMINED:
        return [ResolutionAction.SAVE_ANYWAY_UNDER_REVIEW, ResolutionAction.CANCEL]
    return []


def find_candidates(
    new_text: str,
    new_reason: str,
    decisions: List[Dict[str, Any]],
    limit: int = 5,
    min_similarity: float = 0.0,
) -> List[CandidateDecision]:
    memory = {"decisions": decisions}
    raw_candidates, _meta = retrieve_candidates(
        new_text,
        new_reason,
        memory,
        limit=limit,
        config=DECISION_CONFIG,
    )
    return _classify_candidates(new_text, new_reason, raw_candidates, limit, DECISION_CONFIG)


def _classify_candidates(
    new_text: str,
    new_reason: str,
    raw_candidates: List[Tuple[Dict[str, Any], float, str]],
    limit: int,
    config: KnowledgeTypeConfig = DECISION_CONFIG,
) -> List[CandidateDecision]:
    candidates: List[CandidateDecision] = []
    for record, score, source in raw_candidates:
        existing_text = record.get(config.text_field, "")
        existing_reason = record.get(config.reason_field, "")
        relationship, explanation, confidence = classify_relationship(
            new_text,
            new_reason,
            existing_text,
            existing_reason,
            retrieval_score=score,
            retrieval_source=source,
        )
        if relationship == RelationshipType.UNRELATED:
            continue
        candidates.append(CandidateDecision(
            id=record_id_for(record, config),
            text=existing_text,
            reason=existing_reason,
            similarity_score=score,
            relationship=relationship,
            explanation=explanation,
            confidence=confidence,
            metadata={
                "actor": record.get("actor", "unknown"),
                "actor_source": record.get("actor_source", "none"),
                "timestamp": record.get("timestamp", ""),
                "retrieval_source": source,
            },
        ))

    priority = {
        RelationshipType.SAME: 0,
        RelationshipType.SUPERSEDES: 1,
        RelationshipType.EXCEPTION_TO: 2,
        RelationshipType.POTENTIAL_CONFLICT: 3,
        RelationshipType.EXTENDS: 4,
        RelationshipType.UNDETERMINED: 5,
    }
    candidates.sort(key=lambda candidate: (
        priority.get(candidate.relationship, 99),
        -candidate.confidence,
        -candidate.similarity_score,
    ))
    return candidates[:limit]


def _review_knowledge(
    config: KnowledgeTypeConfig,
    new_text: str,
    new_reason: str,
    memory: Dict[str, Any],
    candidate_limit: int = 5,
    *,
    project_id: Optional[str] = None,
    semantic_search_fn: Optional[Callable[..., Iterable[Any]]] = None,
    semantic_min_score: float = 0.45,
    timeout_ms: int = 750,
) -> ReviewResult:
    """Internal generic review function for any knowledge type."""
    raw_candidates, retrieval_meta = retrieve_candidates(
        new_text,
        new_reason,
        memory,
        project_id=project_id,
        semantic_search_fn=semantic_search_fn,
        limit=candidate_limit,
        semantic_min_score=semantic_min_score,
        timeout_ms=timeout_ms,
        config=config,
    )
    candidates = _classify_candidates(new_text, new_reason, raw_candidates, candidate_limit, config)
    if not candidates:
        return ReviewResult(
            requires_review=False,
            proposed_text=new_text,
            proposed_reason=new_reason,
            candidates=[],
            message=f"No related active {config.memory_key} found",
            retrieval=retrieval_meta,
        )

    primary = candidates[0]
    actions = _allowed_actions(primary.relationship)
    return ReviewResult(
        requires_review=True,
        proposed_text=new_text,
        proposed_reason=new_reason,
        candidates=candidates,
        primary_candidate=primary,
        allowed_actions=actions,
        message=(
            f"Review required against active {config.doc_type}:\n"
            f"Existing: \"{primary.text[:100]}\"\n"
            f"Relationship: {primary.relationship.value}\n"
            f"Reason: {primary.explanation}"
        ),
        retrieval=retrieval_meta,
    )


def review_decision(
    new_text: str,
    new_reason: str,
    memory: Dict[str, Any],
    candidate_limit: int = 5,
    *,
    project_id: Optional[str] = None,
    semantic_search_fn: Optional[Callable[..., Iterable[Any]]] = None,
    semantic_min_score: float = 0.45,
    timeout_ms: int = 750,
) -> ReviewResult:
    """Review a proposed decision against active decisions."""
    return _review_knowledge(
        DECISION_CONFIG,
        new_text,
        new_reason,
        memory,
        candidate_limit,
        project_id=project_id,
        semantic_search_fn=semantic_search_fn,
        semantic_min_score=semantic_min_score,
        timeout_ms=timeout_ms,
    )


def review_solution(
    new_problem: str,
    new_solution: str,
    memory: Dict[str, Any],
    candidate_limit: int = 5,
    *,
    project_id: Optional[str] = None,
    semantic_search_fn: Optional[Callable[..., Iterable[Any]]] = None,
    semantic_min_score: float = 0.45,
    timeout_ms: int = 750,
) -> ReviewResult:
    """Review a proposed solved bug against active solutions."""
    return _review_knowledge(
        SOLUTION_CONFIG,
        new_problem,
        new_solution,
        memory,
        candidate_limit,
        project_id=project_id,
        semantic_search_fn=semantic_search_fn,
        semantic_min_score=semantic_min_score,
        timeout_ms=timeout_ms,
    )
