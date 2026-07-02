"""
Project Librarian - Central Orchestrator for FixOnce.

The librarian continuously asks:
- Do I understand what the engineer is doing?
- Do I know something relevant?
- Is anything important enough to surface?
- What is the minimum knowledge the engineer must know?
- Now can I safely send them to the code?

This module implements the Project Librarian Architecture Contract.

Core guarantees:
- No Critical Knowledge Left Behind
- Knowledge Before Code
- Silence Over Noise
- Context Is Continuous
- Memory Is Authority
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json

from core.intent_detection import (
    Intent,
    IntentSignals,
    IntentResult,
    detect_intent,
)
from core.subject_detection import (
    derive_current_subject_tags,
    calculate_subject_confidence,
)
from core.knowledge_model import (
    KnowledgeItem,
    Criticality,
)
from core.knowledge_selection import (
    KnowledgePackage,
    RetrievalStrategy,
    select_for_briefing,
    select_for_alert,
    select_for_orientation,
    has_relevant_knowledge,
    count_by_tier,
)
from core.briefing_composer import (
    Briefing,
    compose_for_init,
    compose_for_subject_change,
    compose_for_alert,
    compose_for_orientation,
    format_knowledge_stats,
)


# Confidence thresholds
SUBJECT_CONFIDENCE_THRESHOLD = 0.4
INTENT_CONFIDENCE_THRESHOLD = 0.3


@dataclass
class LibrarianContext:
    """
    Full context for a librarian decision.

    This is the complete state the librarian uses to decide what to surface.
    """
    # From Intent Detection
    intent: Intent
    intent_confidence: float

    # From Subject Detection
    subject_tags: List[str]
    subject_confidence: float

    # From Session State
    previously_surfaced: Set[str] = field(default_factory=set)
    last_subject: str = ""
    time_since_last_intervention: Optional[timedelta] = None

    # Trigger info
    trigger: str = ""  # fo_init, fo_sync, fo_search, etc.

    def is_subject_change(self) -> bool:
        """Check if this is a subject change."""
        if not self.last_subject:
            return True
        if not self.subject_tags:
            return False
        return self.subject_tags[0] != self.last_subject

    def primary_subject(self) -> str:
        """Get primary subject tag."""
        return self.subject_tags[0] if self.subject_tags else ""


@dataclass
class LibrarianResponse:
    """
    Response from the librarian.

    Contains the knowledge briefing and navigation guidance.
    """
    # Should the librarian speak?
    should_speak: bool

    # Knowledge briefing (if speaking)
    briefing: str

    # Structured knowledge (for programmatic access)
    knowledge_package: Optional[KnowledgePackage]

    # Code guidance (always last)
    code_guidance: List[Dict[str, str]]

    # Metadata
    reason: str  # Why speaking or silent
    strategy: RetrievalStrategy


@dataclass
class SubjectShelf:
    """
    Presentation cache for one subject.

    This is never authority. The shelf is restorable only when its memory
    fingerprint still matches Project Knowledge.
    """
    subject_key: str
    subject_tags: List[str]
    knowledge_package: KnowledgePackage
    briefing_text: str
    metadata: Dict[str, str]
    memory_fingerprint: str
    created_at: datetime
    restored_at: Optional[datetime] = None


@dataclass
class SubjectShelfCache:
    """In-memory subject shelf cache for one librarian session."""
    shelves: Dict[str, SubjectShelf] = field(default_factory=dict)

    def get(self, subject_key: str, memory_fingerprint: str) -> Optional[SubjectShelf]:
        shelf = self.shelves.get(subject_key)
        if not shelf:
            return None
        if shelf.memory_fingerprint != memory_fingerprint:
            return None
        shelf.restored_at = datetime.now()
        return shelf

    def put(self, shelf: SubjectShelf) -> None:
        self.shelves[shelf.subject_key] = shelf

    def has_subject(self, subject_key: str) -> bool:
        return subject_key in self.shelves

    def clear(self) -> None:
        self.shelves.clear()


class ProjectLibrarian:
    """
    The Project Librarian.

    Central orchestrator that implements the full lifecycle:
    1. Intent Detection
    2. Subject Detection
    3. Intervention Check
    4. Knowledge Selection
    5. Composition
    6. Presentation
    7. Code Guidance (LAST)
    """

    def __init__(self, memory: Dict[str, Any], working_dir: str = ""):
        """
        Initialize librarian with project memory.

        Args:
            memory: Project memory dict
            working_dir: Project working directory
        """
        self.memory = memory
        self.working_dir = working_dir

        # Session state
        self._surfaced_subjects: Set[str] = set()
        self._surfaced_items: Set[str] = set()
        self._last_subject: str = ""
        self._last_intervention: Optional[datetime] = None
        self._shelves = SubjectShelfCache()

    def on_session_start(
        self,
        task_hint: str = "",
        current_file: str = "",
        error_message: str = "",
    ) -> LibrarianResponse:
        """
        Handle session start (fo_init).

        This is the primary briefing scenario.
        """
        # Build context
        context = self._build_context(
            task_hint=task_hint,
            current_file=current_file,
            error_message=error_message,
            trigger="fo_init",
        )

        # Check if we should speak
        should_speak, reason = self._should_intervene(context)

        if not should_speak:
            return LibrarianResponse(
                should_speak=False,
                briefing="",
                knowledge_package=None,
                code_guidance=[],
                reason=reason,
                strategy=RetrievalStrategy.BRIEFING,
            )

        return self._build_and_store_shelf_response(
            context=context,
            composer="init",
            reason="Session start briefing",
        )

    def on_subject_change(
        self,
        new_work_area: str,
        current_file: str = "",
        task_hint: str = "",
    ) -> LibrarianResponse:
        """
        Handle subject/topic change (e.g., fo_sync with new work_area).
        """
        old_subject = self._last_subject

        # Build context
        context = self._build_context(
            task_hint=task_hint or new_work_area,
            current_file=current_file,
            trigger="fo_sync",
        )

        # Check if actually a subject change
        if not context.is_subject_change():
            return LibrarianResponse(
                should_speak=False,
                briefing="",
                knowledge_package=None,
                code_guidance=[],
                reason="No subject change detected",
                strategy=RetrievalStrategy.BRIEFING,
            )

        memory_fingerprint = self._memory_fingerprint()
        restored = self._restore_shelf_response(context, memory_fingerprint)
        if restored:
            return restored

        subject_key = self._subject_key(context.subject_tags)
        if self._shelves.has_subject(subject_key):
            return self._build_and_store_shelf_response(
                context=context,
                composer="subject_change",
                reason="Subject shelf stale; rebuilt from Project Knowledge",
                old_subject=old_subject,
                memory_fingerprint=memory_fingerprint,
            )

        # Check if we should speak
        should_speak, reason = self._should_intervene(context)

        if not should_speak:
            return LibrarianResponse(
                should_speak=False,
                briefing="",
                knowledge_package=None,
                code_guidance=[],
                reason=reason,
                strategy=RetrievalStrategy.BRIEFING,
            )

        return self._build_and_store_shelf_response(
            context=context,
            composer="subject_change",
            reason="Subject change briefing",
            old_subject=old_subject,
            memory_fingerprint=memory_fingerprint,
        )

    def on_error_detected(
        self,
        error_message: str,
        current_file: str = "",
    ) -> LibrarianResponse:
        """
        Handle error detection (fo_errors with auto-fix candidate).

        Uses alert strategy - only must-know, minimal.
        """
        # Build context
        context = self._build_context(
            error_message=error_message,
            current_file=current_file,
            trigger="fo_errors",
        )

        # Select alert-level knowledge
        package = select_for_alert(
            memory=self.memory,
            subject_tags=context.subject_tags,
            intent=Intent.DEBUGGING,  # Errors imply debugging
        )

        if not package.has_must_know():
            return LibrarianResponse(
                should_speak=False,
                briefing="",
                knowledge_package=package,
                code_guidance=[],
                reason="No must-know knowledge for this error",
                strategy=RetrievalStrategy.ALERT,
            )

        # Compose alert
        briefing = compose_for_alert(package)

        return LibrarianResponse(
            should_speak=True,
            briefing=briefing,
            knowledge_package=package,
            code_guidance=[],  # No code guidance for alerts
            reason="Error alert",
            strategy=RetrievalStrategy.ALERT,
        )

    def on_deep_onboarding(self) -> LibrarianResponse:
        """
        Handle deep onboarding request (fo_brief).

        Uses orientation strategy - exhaustive across all tiers.
        """
        # Get all subjects (no filtering)
        context = self._build_context(trigger="fo_brief")

        # Select orientation knowledge (exhaustive)
        package = select_for_orientation(
            memory=self.memory,
            subject_tags=[],  # All subjects for orientation
            intent=context.intent,
        )

        # Compose full orientation
        briefing = compose_for_orientation(package)

        # Get code guidance
        code_guidance = self._get_code_guidance(context, package)

        return LibrarianResponse(
            should_speak=True,
            briefing=briefing,
            knowledge_package=package,
            code_guidance=code_guidance,
            reason="Deep onboarding",
            strategy=RetrievalStrategy.ORIENTATION,
        )

    def get_knowledge_stats(
        self,
        subject_tags: Optional[List[str]] = None,
    ) -> str:
        """Get knowledge statistics for display."""
        tags = subject_tags or []
        counts = count_by_tier(self.memory, tags)

        parts = []
        if counts["must_know"]:
            parts.append(f"{counts['must_know']} Decisions")
        if counts["should_check"]:
            parts.append(f"{counts['should_check']} Solved Bugs")
        if counts["may_help"]:
            parts.append(f"{counts['may_help']} Context")

        if not parts:
            return ""

        return f"📊 Project Knowledge: {' · '.join(parts)}"

    def _build_context(
        self,
        task_hint: str = "",
        current_file: str = "",
        error_message: str = "",
        trigger: str = "",
    ) -> LibrarianContext:
        """Build full librarian context from signals."""
        # Detect intent
        intent_signals = IntentSignals(
            current_file=current_file,
            error_message=error_message,
            task_hint=task_hint,
            time_since_last_activity=self._time_since_last_intervention(),
        )
        intent_result = detect_intent(intent_signals)

        # Detect subject
        signals = {}
        if task_hint:
            signals["query"] = task_hint
            signals["task_hint"] = task_hint
        if current_file:
            signals["intent.last_file"] = current_file

        subject_tags = derive_current_subject_tags(signals)
        subject_confidence = calculate_subject_confidence(subject_tags, signals)

        return LibrarianContext(
            intent=intent_result.intent,
            intent_confidence=intent_result.confidence,
            subject_tags=subject_tags,
            subject_confidence=subject_confidence,
            previously_surfaced=self._surfaced_subjects.copy(),
            last_subject=self._last_subject,
            time_since_last_intervention=self._time_since_last_intervention(),
            trigger=trigger,
        )

    def _should_intervene(self, context: LibrarianContext) -> tuple:
        """
        Decide if librarian should speak.

        Returns (should_speak, reason).
        """
        # Silence over noise: need sufficient confidence
        if context.subject_confidence < SUBJECT_CONFIDENCE_THRESHOLD:
            return False, f"Subject confidence too low: {context.subject_confidence:.2f}"

        # Check if subject already surfaced this session
        primary = context.primary_subject()
        if primary and primary in self._surfaced_subjects:
            return False, f"Subject already surfaced: {primary}"

        # Check if any relevant knowledge exists
        if not has_relevant_knowledge(self.memory, context.subject_tags):
            return False, "No relevant knowledge for this subject"

        return True, "Relevant knowledge exists"

    def _mark_surfaced(
        self,
        context: LibrarianContext,
        package: KnowledgePackage,
    ):
        """Mark knowledge as surfaced in session state."""
        # Mark subject
        if context.subject_tags:
            self._surfaced_subjects.add(context.primary_subject())
            self._last_subject = context.primary_subject()

        # Mark items
        for item in package.get_all_items():
            self._surfaced_items.add(item.id)

        # Update last intervention time
        self._last_intervention = datetime.now()

    def _build_and_store_shelf_response(
        self,
        context: LibrarianContext,
        composer: str,
        reason: str,
        old_subject: str = "",
        memory_fingerprint: Optional[str] = None,
    ) -> LibrarianResponse:
        """Select from Project Knowledge, compose a briefing, and cache presentation."""
        fingerprint = memory_fingerprint or self._memory_fingerprint()
        package = select_for_briefing(
            memory=self.memory,
            subject_tags=context.subject_tags,
            intent=context.intent,
        )

        if composer == "subject_change":
            briefing = compose_for_subject_change(
                package,
                old_subject=old_subject,
                new_subject=context.primary_subject(),
            )
        else:
            briefing = compose_for_init(package)

        code_guidance = self._get_code_guidance(context, package)
        self._store_shelf(context, package, briefing, code_guidance, fingerprint)
        self._mark_surfaced(context, package)

        return LibrarianResponse(
            should_speak=bool(briefing) or package.has_must_know(),
            briefing=briefing,
            knowledge_package=package,
            code_guidance=code_guidance,
            reason=reason,
            strategy=RetrievalStrategy.BRIEFING,
        )

    def _restore_shelf_response(
        self,
        context: LibrarianContext,
        memory_fingerprint: str,
    ) -> Optional[LibrarianResponse]:
        """Restore a subject shelf only when Project Knowledge has not changed."""
        subject_key = self._subject_key(context.subject_tags)
        if not subject_key:
            return None

        shelf = self._shelves.get(subject_key, memory_fingerprint)
        if not shelf:
            return None

        self._last_subject = context.primary_subject()
        self._last_intervention = datetime.now()
        return LibrarianResponse(
            should_speak=True,
            briefing=shelf.briefing_text,
            knowledge_package=shelf.knowledge_package,
            code_guidance=self._get_code_guidance(context, shelf.knowledge_package),
            reason="Restored subject shelf",
            strategy=RetrievalStrategy.BRIEFING,
        )

    def _store_shelf(
        self,
        context: LibrarianContext,
        package: KnowledgePackage,
        briefing: str,
        code_guidance: List[Dict[str, str]],
        memory_fingerprint: str,
    ) -> None:
        """Store only the presentation package for a subject."""
        subject_key = self._subject_key(context.subject_tags)
        if not subject_key or not briefing:
            return

        self._shelves.put(SubjectShelf(
            subject_key=subject_key,
            subject_tags=list(context.subject_tags),
            knowledge_package=package,
            briefing_text=briefing,
            metadata={
                "strategy": RetrievalStrategy.BRIEFING.value,
                "primary_subject": context.primary_subject(),
                "code_guidance_count": str(len(code_guidance)),
            },
            memory_fingerprint=memory_fingerprint,
            created_at=datetime.now(),
        ))

    @staticmethod
    def _subject_key(subject_tags: List[str]) -> str:
        """Stable subject shelf key from normalized subject tags."""
        normalized = sorted({tag.strip().lower() for tag in subject_tags if tag and tag.strip()})
        return "|".join(normalized)

    def _memory_fingerprint(self) -> str:
        """
        Fingerprint authoritative Project Knowledge.

        Shelves are presentation caches only. Any Project Knowledge change
        invalidates the shelf and forces a rebuild from memory.
        """
        projection = {
            "decisions": self.memory.get("decisions", []),
            "debug_sessions": self.memory.get("debug_sessions", []),
            "avoid": self.memory.get("avoid", []),
            "lessons": self.memory.get("live_record", {}).get("lessons", {}),
            "decision_conflicts": self.memory.get("decision_conflicts", []),
        }
        payload = json.dumps(projection, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _time_since_last_intervention(self) -> Optional[timedelta]:
        """Get time since last intervention."""
        if not self._last_intervention:
            return None
        return datetime.now() - self._last_intervention

    def _get_code_guidance(
        self,
        context: LibrarianContext,
        package: KnowledgePackage,
    ) -> List[Dict[str, str]]:
        """
        Get code guidance (file suggestions).

        This is always LAST - after knowledge has been surfaced.
        """
        guidance = []

        # Extract file references from knowledge items
        seen_files = set()
        for item in package.get_all_items():
            files = item.metadata.get('files_changed', [])
            for f in files:
                if f not in seen_files:
                    seen_files.add(f)
                    guidance.append({
                        "file": f,
                        "reason": f"Referenced in: {item.type.value}",
                    })

        # Limit guidance
        return guidance[:5]

    def reset_session(self):
        """Reset session state (for new conversation)."""
        self._surfaced_subjects.clear()
        self._surfaced_items.clear()
        self._last_subject = ""
        self._last_intervention = None
        self._shelves.clear()


def create_librarian(memory: Dict[str, Any], working_dir: str = "") -> ProjectLibrarian:
    """
    Factory function to create a librarian instance.

    Args:
        memory: Project memory dict
        working_dir: Project working directory

    Returns:
        Configured ProjectLibrarian instance
    """
    return ProjectLibrarian(memory, working_dir)


def get_init_briefing(
    memory: Dict[str, Any],
    task_hint: str = "",
    current_file: str = "",
) -> str:
    """
    Convenience function for fo_init integration.

    Returns formatted briefing string or empty string.
    """
    librarian = create_librarian(memory)
    response = librarian.on_session_start(
        task_hint=task_hint,
        current_file=current_file,
    )
    return response.briefing


def get_subject_change_briefing(
    memory: Dict[str, Any],
    new_work_area: str,
    current_file: str = "",
    previous_subject: str = "",
) -> str:
    """
    Convenience function for subject change integration.

    Returns formatted briefing string or empty string.
    """
    librarian = create_librarian(memory)
    librarian._last_subject = previous_subject
    response = librarian.on_subject_change(
        new_work_area=new_work_area,
        current_file=current_file,
    )
    return response.briefing
