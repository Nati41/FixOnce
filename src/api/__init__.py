"""
FixOnce Flask Routes
Organized route blueprints for the Flask API.
"""

from flask import Blueprint

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
