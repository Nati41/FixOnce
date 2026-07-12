"""
General pre-save review for architectural decisions.

The semantic index is used only to retrieve likely related active decisions.
Canonical decision state and IDs always come from memory["decisions"].
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
import hashlib
import re
import time


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

REPLACEMENT_CUES = {
    "replace", "replaces", "replaced", "replacement", "instead",
    "supersede", "supersedes", "superseded", "deprecate", "deprecates",
    "migrate", "migrates", "switch", "switches",
}

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


def decision_id_for(decision: Dict[str, Any]) -> str:
    if decision.get("id"):
        return str(decision["id"])
    payload = (
        f"{_normalize_text(decision.get('decision', ''))}|"
        f"{_normalize_text(decision.get('reason', ''))}"
    )
    return f"dec_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def _active_decisions(memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    active = []
    for decision in memory.get("decisions", []):
        if not isinstance(decision, dict):
            continue
        if decision.get("superseded"):
            continue
        if decision.get("status") not in (None, "", "active"):
            continue
        active.append(decision)
    return active


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
) -> Tuple[List[Tuple[Dict[str, Any], float, str]], Dict[str, Any]]:
    meta = {"source": "semantic", "used": False, "elapsed_ms": 0.0, "failures": []}
    if not project_id or not semantic_search_fn:
        meta["failures"].append("semantic_unavailable")
        return [], meta

    by_id = {decision_id_for(d): d for d in active}
    by_text = {
        _semantic_key(d.get("decision", ""), d.get("reason", "")): d
        for d in active
    }

    started = time.perf_counter()
    try:
        results = list(semantic_search_fn(
            project_id,
            query,
            k=max(limit * 3, 10),
            doc_type="decision",
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
        decision = None
        for key in ("decision_id", "id", "canonical_id"):
            if metadata.get(key) and str(metadata[key]) in by_id:
                decision = by_id[str(metadata[key])]
                break
        if decision is None:
            text = metadata.get("decision") or getattr(result, "text", "")
            reason = metadata.get("reason", "")
            decision = by_text.get(_semantic_key(text, reason))
        if decision is None:
            unmapped += 1
            continue
        dec_id = decision_id_for(decision)
        if dec_id in seen:
            continue
        seen.add(dec_id)
        candidates.append((decision, score, "semantic"))

    if unmapped:
        meta["failures"].append(f"unmapped_results:{unmapped}")
        _log(f"semantic returned {unmapped} decision result(s) without canonical active mapping")
    meta["used"] = bool(candidates)
    return candidates[:limit], meta


def _lexical_candidates(
    query: str,
    active: List[Dict[str, Any]],
    limit: int,
) -> List[Tuple[Dict[str, Any], float, str]]:
    query_tokens = _tokens(query)
    proposed_part = query.split(". Reason:")[0] if ". Reason:" in query else query
    proposed_tokens = _tokens(proposed_part)
    scored = []
    for decision in active:
        decision_text = decision.get("decision", "")
        combined = f"{decision_text} {decision.get('reason', '')}"
        decision_tokens = _tokens(decision_text)
        combined_tokens = _tokens(combined)
        score = max(
            _jaccard(query_tokens, combined_tokens),
            _overlap_ratio(query_tokens, combined_tokens) * 0.75,
            _overlap_ratio(query_tokens, decision_tokens) * 0.75,
            _overlap_ratio(proposed_tokens, decision_tokens) * 0.75,
            _overlap_with_suffixes(proposed_tokens, decision_tokens) * 0.75,
        )
        if score >= 0.18:
            scored.append((decision, score, "lexical"))
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
) -> Tuple[List[Tuple[Dict[str, Any], float, str]], Dict[str, Any]]:
    active = _active_decisions(memory)
    query = f"{new_text}. Reason: {new_reason}"
    semantic, meta = _semantic_candidates(
        query, active, project_id, semantic_search_fn, limit, semantic_min_score, timeout_ms
    )
    if semantic:
        return semantic, meta
    meta["source"] = "lexical_fallback"
    lexical = _lexical_candidates(query, active, limit)
    return lexical, meta


def _contains_any(tokens: Set[str], cues: Set[str]) -> bool:
    tokens = {simple_stem(token) for token in tokens}
    cue_tokens = {simple_stem(cue) for cue in cues}
    return bool(tokens & cue_tokens)


def _has_phrase(text: str, phrases: Iterable[str]) -> bool:
    lower = f" {_normalize_text(text)} "
    return any(f" {_normalize_text(phrase)} " in lower for phrase in phrases)


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

    if _normalize_text(new_text) == _normalize_text(existing_text):
        return RelationshipType.SAME, "Exact duplicate of active decision", 0.98

    if _jaccard(new_tokens, existing_tokens) >= 0.82 and new_tokens:
        return RelationshipType.SAME, "Near duplicate of active decision", 0.9

    replacement = _contains_any(new_raw, REPLACEMENT_CUES)
    exception = _contains_any(new_raw, EXCEPTION_CUES) or _has_phrase(new_combined, ["without", "except for"])
    strict_existing = _contains_any(existing_raw, STRICT_CUES)
    permissive_new = _contains_any(new_raw, PERMISSIVE_OR_WEAKENING_CUES)
    extension = _contains_any(new_raw, EXTENSION_CUES)
    replacement_existing = _contains_any(existing_raw, REPLACEMENT_CUES)
    reversal_new = _contains_any(new_raw, REVERSAL_CUES)

    has_meaningful_subject = bool(overlap) or retrieval_score >= 0.58

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
    )
    return _classify_candidates(new_text, new_reason, raw_candidates, limit)


def _classify_candidates(
    new_text: str,
    new_reason: str,
    raw_candidates: List[Tuple[Dict[str, Any], float, str]],
    limit: int,
) -> List[CandidateDecision]:
    candidates: List[CandidateDecision] = []
    for decision, score, source in raw_candidates:
        existing_text = decision.get("decision", "")
        existing_reason = decision.get("reason", "")
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
            id=decision_id_for(decision),
            text=existing_text,
            reason=existing_reason,
            similarity_score=score,
            relationship=relationship,
            explanation=explanation,
            confidence=confidence,
            metadata={
                "actor": decision.get("actor", "unknown"),
                "actor_source": decision.get("actor_source", "none"),
                "timestamp": decision.get("timestamp", ""),
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
    raw_candidates, retrieval_meta = retrieve_candidates(
        new_text,
        new_reason,
        memory,
        project_id=project_id,
        semantic_search_fn=semantic_search_fn,
        limit=candidate_limit,
        semantic_min_score=semantic_min_score,
        timeout_ms=timeout_ms,
    )
    candidates = _classify_candidates(new_text, new_reason, raw_candidates, candidate_limit)
    if not candidates:
        return ReviewResult(
            requires_review=False,
            proposed_text=new_text,
            proposed_reason=new_reason,
            candidates=[],
            message="No related active decisions found",
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
            "Decision review required against active decision:\n"
            f"Existing: \"{primary.text[:100]}\"\n"
            f"Relationship: {primary.relationship.value}\n"
            f"Reason: {primary.explanation}"
        ),
        retrieval=retrieval_meta,
    )
