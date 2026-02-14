"""
FixOnce Core Module
Contains core components like boundary detection, error store, and semantic engine.
"""

from .boundary_detector import (
    detect_boundary_violation,
    handle_boundary_transition,
    find_project_root,
    is_within_boundary,
    get_boundary_status,
    BoundaryEvent
)

__all__ = [
    'detect_boundary_violation',
    'handle_boundary_transition',
    'find_project_root',
    'is_within_boundary',
    'get_boundary_status',
    'BoundaryEvent'
]
