"""
Intent Detection for Project Librarian.

Determines what the engineer is trying to accomplish based on observable signals.

This module answers: "What is the engineer doing right now?"

Design principles:
1. Observable signals only - no inference from memory content
2. Explicit classification - debugging, implementing, designing, etc.
3. Confidence tracking - know when intent is unclear
4. Intent decay - intent doesn't persist forever without refresh
"""

from dataclasses import dataclass
from typing import List, Optional, Set
from enum import Enum
from datetime import datetime, timedelta
import re


class Intent(Enum):
    """Engineer's current workflow stage."""
    DEBUGGING = "debugging"
    IMPLEMENTING = "implementing"
    DESIGNING = "designing"
    REVIEWING = "reviewing"
    EXPLORING = "exploring"
    RESUMING = "resuming"
    UNKNOWN = "unknown"


@dataclass
class IntentSignals:
    """Observable signals for intent detection."""
    current_file: str = ""
    recent_files: List[str] = None
    error_message: str = ""
    stack_trace: str = ""
    task_hint: str = ""
    recent_commands: List[str] = None
    time_since_last_activity: Optional[timedelta] = None
    explicit_declaration: str = ""

    def __post_init__(self):
        if self.recent_files is None:
            self.recent_files = []
        if self.recent_commands is None:
            self.recent_commands = []


@dataclass
class IntentResult:
    """Result of intent detection."""
    intent: Intent
    confidence: float  # 0.0 to 1.0
    signals_used: List[str]  # Which signals contributed

    def is_confident(self, threshold: float = 0.5) -> bool:
        """Check if intent confidence meets threshold."""
        return self.confidence >= threshold


# Signal patterns for intent classification
DEBUGGING_PATTERNS = [
    r'\berror\b',
    r'\bexception\b',
    r'\bfailed\b',
    r'\bcrash\b',
    r'\bbug\b',
    r'\bfix\b',
    r'\bbroken\b',
    r'\btraceback\b',
    r'\bstack\s*trace\b',
    r'\bundefined\b',
    r'\bnull\b',
    r'\bnan\b',
]

DESIGNING_PATTERNS = [
    r'\barchitecture\b',
    r'\bdesign\b',
    r'\bplan\b',
    r'\bproposal\b',
    r'\brefactor\b',
    r'\brestructure\b',
    r'\bnew\s+feature\b',
    r'\bspec\b',
    r'\brfc\b',
]

REVIEWING_PATTERNS = [
    r'\breview\b',
    r'\bcheck\b',
    r'\baudit\b',
    r'\bverify\b',
    r'\bpr\b',
    r'\bpull\s*request\b',
    r'\bcode\s*review\b',
]

IMPLEMENTING_FILE_PATTERNS = [
    r'\.py$',
    r'\.js$',
    r'\.ts$',
    r'\.tsx$',
    r'\.jsx$',
    r'\.go$',
    r'\.rs$',
    r'\.java$',
]

DESIGN_FILE_PATTERNS = [
    r'\.md$',
    r'readme',
    r'design',
    r'spec',
    r'rfc',
    r'proposal',
]

# Time thresholds
RESUMING_THRESHOLD = timedelta(hours=1)
STALE_INTENT_THRESHOLD = timedelta(minutes=30)


def detect_intent(signals: IntentSignals) -> IntentResult:
    """
    Detect engineer's current intent from observable signals.

    Priority order:
    1. Explicit declaration (highest confidence)
    2. Error/stack trace signals (debugging)
    3. Task hint patterns
    4. File type patterns
    5. Time-based signals (resuming)

    Args:
        signals: Observable signals about current activity

    Returns:
        IntentResult with classified intent and confidence
    """
    signals_used = []

    # Check for explicit declaration first
    if signals.explicit_declaration:
        intent, confidence = _classify_from_declaration(signals.explicit_declaration)
        if intent != Intent.UNKNOWN:
            return IntentResult(
                intent=intent,
                confidence=min(confidence + 0.2, 1.0),  # Boost for explicit
                signals_used=["explicit_declaration"]
            )

    # Check for debugging signals (error messages, stack traces)
    if signals.error_message or signals.stack_trace:
        return IntentResult(
            intent=Intent.DEBUGGING,
            confidence=0.9,
            signals_used=["error_message" if signals.error_message else "stack_trace"]
        )

    # Check task hint for patterns
    if signals.task_hint:
        intent, confidence = _classify_from_text(signals.task_hint)
        if intent != Intent.UNKNOWN:
            signals_used.append("task_hint")
            return IntentResult(
                intent=intent,
                confidence=confidence,
                signals_used=signals_used
            )

    # Check for resuming (returning after long absence)
    if signals.time_since_last_activity and signals.time_since_last_activity > RESUMING_THRESHOLD:
        return IntentResult(
            intent=Intent.RESUMING,
            confidence=0.8,
            signals_used=["time_since_last_activity"]
        )

    # Check file patterns
    if signals.current_file:
        intent, confidence = _classify_from_file(signals.current_file)
        if intent != Intent.UNKNOWN:
            return IntentResult(
                intent=intent,
                confidence=confidence,
                signals_used=["current_file"]
            )

    # Default to exploring with low confidence
    return IntentResult(
        intent=Intent.EXPLORING,
        confidence=0.3,
        signals_used=[]
    )


def _classify_from_declaration(declaration: str) -> tuple:
    """Classify intent from explicit declaration."""
    lower = declaration.lower()

    if any(word in lower for word in ['debug', 'fix', 'error', 'bug']):
        return Intent.DEBUGGING, 0.9

    if any(word in lower for word in ['design', 'plan', 'architect', 'refactor']):
        return Intent.DESIGNING, 0.9

    if any(word in lower for word in ['review', 'check', 'audit', 'verify']):
        return Intent.REVIEWING, 0.9

    if any(word in lower for word in ['implement', 'build', 'create', 'add', 'code']):
        return Intent.IMPLEMENTING, 0.8

    if any(word in lower for word in ['explore', 'understand', 'learn', 'look']):
        return Intent.EXPLORING, 0.7

    return Intent.UNKNOWN, 0.0


def _classify_from_text(text: str) -> tuple:
    """Classify intent from task hint or similar text."""
    lower = text.lower()

    # Check debugging patterns
    for pattern in DEBUGGING_PATTERNS:
        if re.search(pattern, lower):
            return Intent.DEBUGGING, 0.7

    # Check designing patterns
    for pattern in DESIGNING_PATTERNS:
        if re.search(pattern, lower):
            return Intent.DESIGNING, 0.6

    # Check reviewing patterns
    for pattern in REVIEWING_PATTERNS:
        if re.search(pattern, lower):
            return Intent.REVIEWING, 0.6

    return Intent.UNKNOWN, 0.0


def _classify_from_file(file_path: str) -> tuple:
    """Classify intent from current file being worked on."""
    lower = file_path.lower()

    # Design files suggest designing intent
    for pattern in DESIGN_FILE_PATTERNS:
        if re.search(pattern, lower):
            return Intent.DESIGNING, 0.4

    # Code files suggest implementing (weak signal)
    for pattern in IMPLEMENTING_FILE_PATTERNS:
        if re.search(pattern, lower):
            return Intent.IMPLEMENTING, 0.3

    return Intent.UNKNOWN, 0.0


def is_debugging_context(signals: IntentSignals) -> bool:
    """Quick check if context suggests debugging."""
    if signals.error_message or signals.stack_trace:
        return True

    if signals.task_hint:
        lower = signals.task_hint.lower()
        return any(re.search(p, lower) for p in DEBUGGING_PATTERNS)

    return False


def get_intent_summary(result: IntentResult) -> str:
    """Get human-readable summary of detected intent."""
    if result.intent == Intent.DEBUGGING:
        return "debugging an issue"
    elif result.intent == Intent.IMPLEMENTING:
        return "implementing code"
    elif result.intent == Intent.DESIGNING:
        return "designing or planning"
    elif result.intent == Intent.REVIEWING:
        return "reviewing code"
    elif result.intent == Intent.EXPLORING:
        return "exploring the codebase"
    elif result.intent == Intent.RESUMING:
        return "resuming previous work"
    else:
        return "working"
