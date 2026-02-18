"""
FixOnce Core Module
Contains core components like boundary detection, error store, semantic engine, and context generation.
"""

from .boundary_detector import (
    detect_boundary_violation,
    handle_boundary_transition,
    find_project_root,
    is_within_boundary,
    get_boundary_status,
    BoundaryEvent
)

from .context_generator import (
    generate_context_file,
    update_context_on_memory_change
)

__all__ = [
    'detect_boundary_violation',
    'handle_boundary_transition',
    'find_project_root',
    'is_within_boundary',
    'get_boundary_status',
    'BoundaryEvent',
    'generate_context_file',
    'update_context_on_memory_change'
]
