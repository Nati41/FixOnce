"""
FixOnce Core Module
Contains core components like boundary detection, error store, semantic engine, and context generation.
"""

import os

if os.environ.get("FIXONCE_DISABLE_BOUNDARY") == "1":
    detect_boundary_violation = None
    handle_boundary_transition = None
    find_project_root = None
    is_within_boundary = None
    get_boundary_status = None
    BoundaryEvent = None
else:
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
