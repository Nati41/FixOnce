"""
FixOnce Flask Routes
Organized route blueprints for the Flask API.

IMPORTANT: Phase 0 - Project isolation via X-Project-Root header.
API endpoints should use get_project_from_request() to get project_id.
Dashboard requests can fallback to active_project.json.
"""

from flask import Blueprint, request
from typing import Optional, Tuple
import sys
from pathlib import Path

# Add parent path for imports
_SRC_DIR = Path(__file__).parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


def get_project_from_request() -> Tuple[Optional[str], Optional[str]]:
    """
    Get project_id from request using X-Project-Root header.

    This is the NEW standard for API requests.
    - MCP and external clients MUST provide X-Project-Root header
    - Dashboard can use X-Dashboard: true to fallback to active_project.json

    Returns:
        Tuple of (project_id, error_message)
        - (project_id, None) if successful
        - (None, error_message) if failed

    Example:
        project_id, error = get_project_from_request()
        if error:
            return jsonify({"status": "error", "message": error}), 400
    """
    # Check for X-Project-Root header (new standard)
    project_root = request.headers.get('X-Project-Root')

    if project_root:
        # Use ProjectContext to generate ID from path
        try:
            from core.project_context import ProjectContext
            project_id = ProjectContext.from_path(project_root)
            return (project_id, None)
        except Exception as e:
            return (None, f"Invalid X-Project-Root: {e}")

    # Dashboard fallback: Allow if X-Dashboard header is present
    is_dashboard = request.headers.get('X-Dashboard') == 'true'
    if is_dashboard:
        try:
            from managers.multi_project_manager import get_active_project_id
            project_id = get_active_project_id()
            if project_id:
                return (project_id, None)
            return (None, "No active project (dashboard mode)")
        except Exception as e:
            return (None, f"Dashboard fallback failed: {e}")

    # Legacy fallback: For backward compatibility, try active project
    # This will be removed in a future version
    try:
        from managers.multi_project_manager import get_active_project_id
        project_id = get_active_project_id()
        if project_id:
            # Log deprecation warning
            print("[WARN] API called without X-Project-Root header. "
                  "This fallback will be removed. Add X-Project-Root header.")
            return (project_id, None)
    except Exception:
        pass

    return (None, "X-Project-Root header required")

# Create blueprints
errors_bp = Blueprint('errors', __name__)
memory_bp = Blueprint('memory', __name__)
safety_bp = Blueprint('safety', __name__)
status_bp = Blueprint('status', __name__)
solutions_bp = Blueprint('solutions', __name__)
rules_bp = Blueprint('rules', __name__)
projects_bp = Blueprint('projects', __name__)

# Import route handlers to register them
from . import errors
from . import memory
from . import safety
from . import status
from . import solutions
from . import rules
from . import projects

# Activity blueprint (separate file with its own blueprint)
from .activity import activity_bp

# Components blueprint
from .components import components_bp

# OpenAI adapter blueprint (for GPT/Codex compatibility)
from .openai_adapter import openai_bp


def register_blueprints(app):
    """Register all blueprints with the Flask app."""
    app.register_blueprint(errors_bp)
    app.register_blueprint(memory_bp, url_prefix='/api/memory')
    app.register_blueprint(safety_bp, url_prefix='/api/safety')
    app.register_blueprint(status_bp, url_prefix='/api')
    app.register_blueprint(solutions_bp, url_prefix='/api')
    app.register_blueprint(rules_bp, url_prefix='/api/rules')
    app.register_blueprint(projects_bp, url_prefix='/api/projects')
    app.register_blueprint(activity_bp, url_prefix='/api/activity')
    app.register_blueprint(components_bp, url_prefix='/api/components')
    app.register_blueprint(openai_bp)  # /openai/* endpoints
