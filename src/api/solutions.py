"""
FixOnce Solutions Routes
Solutions database API endpoints.
"""

from flask import jsonify, request
from datetime import datetime

from . import solutions_bp


@solutions_bp.route("/solutions/<scope>")
def api_get_solutions(scope: str):
    """API endpoint to get solutions by scope."""
    from core.db_solutions import get_all_solutions
    from config import PERSONAL_DB_PATH, TEAM_DB_PATH

    if scope == "personal":
        solutions = get_all_solutions(PERSONAL_DB_PATH)
    elif scope == "team":
        if TEAM_DB_PATH:
            solutions = get_all_solutions(TEAM_DB_PATH)
        else:
            return jsonify({"error": "Team DB not configured", "solutions": []}), 200
    else:
        return jsonify({"error": "Invalid scope"}), 400

    return jsonify({"solutions": solutions, "scope": scope})


@solutions_bp.route("/solutions/<scope>/<int:solution_id>", methods=["DELETE"])
def api_delete_solution(scope: str, solution_id: int):
    """API endpoint to delete a solution."""
    from core.db_solutions import delete_solution
    from config import PERSONAL_DB_PATH, TEAM_DB_PATH

    if scope == "personal":
        db_path = PERSONAL_DB_PATH
    elif scope == "team":
        if not TEAM_DB_PATH:
            return jsonify({"error": "Team DB not configured"}), 400
        db_path = TEAM_DB_PATH
    else:
        return jsonify({"error": "Invalid scope"}), 400

    deleted = delete_solution(solution_id, db_path)

    if deleted:
        return jsonify({"status": "ok", "message": f"Solution {solution_id} deleted"})
    return jsonify({"error": "Solution not found"}), 404


@solutions_bp.route("/save-solution", methods=["POST"])
def api_save_solution():
    """API endpoint to save a solution to the learning database."""
    from core.db_solutions import save_solution
    from config import PERSONAL_DB_PATH, TEAM_DB_PATH

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    error_message = data.get("error_message", "")
    solution_text = data.get("solution_text", "")
    scope = data.get("scope", "personal")

    if not error_message or not solution_text:
        return jsonify({"status": "error", "message": "Missing error_message or solution_text"}), 400

    if scope == "team":
        if not TEAM_DB_PATH:
            return jsonify({"status": "error", "message": "Team database not configured"}), 400
        db_path = TEAM_DB_PATH
    else:
        db_path = PERSONAL_DB_PATH

    # Try to use semantic engine if available
    try:
        from core.semantic_engine import get_engine
        engine = get_engine(db_path)
        result = save_solution(error_message, solution_text, db_path, engine)
    except ImportError:
        result = save_solution(error_message, solution_text, db_path)

    result["scope"] = scope
    return jsonify(result)
