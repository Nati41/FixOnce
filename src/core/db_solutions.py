"""
FixOnce Solutions Database
SQLite database operations for storing and retrieving solutions.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import PERSONAL_DB_PATH, TEAM_DB_PATH


def init_db(db_path: Path, db_name: str = "Database"):
    """Initialize a SQLite database and create the solutions table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_message TEXT NOT NULL,
            solution_text TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            error_clean TEXT,
            confidence_score REAL DEFAULT 1.0,
            success_count INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    print(f"📚 {db_name} initialized at {db_path}")


def get_all_solutions(db_path: Path) -> list[dict]:
    """Get all solutions from a specific database."""
    if not db_path or not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, error_message, solution_text, timestamp FROM solutions ORDER BY timestamp DESC"
    )
    results = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "error_message": row[1],
            "solution_text": row[2],
            "timestamp": row[3]
        }
        for row in results
    ]


def find_similar_solution(error_message: str, db_path: Path, semantic_engine=None) -> Optional[dict]:
    """
    Search for a similar error in a specific database.
    Uses semantic similarity if available, falls back to LIKE matching.
    """
    if not db_path or not db_path.exists():
        return None

    # Try semantic search first if engine is provided
    if semantic_engine:
        try:
            match = semantic_engine.find_similar(error_message)

            if match:
                solution_id, similarity_score, matched_clean = match
                solution = semantic_engine.get_solution_by_id(solution_id)

                if solution:
                    semantic_engine.increment_success_count(solution_id)

                    return {
                        "matched_error": solution["error_message"],
                        "solution": solution["solution_text"],
                        "saved_at": solution["timestamp"],
                        "similarity_score": similarity_score,
                        "match_type": "semantic",
                        "success_count": solution["success_count"] + 1
                    }
        except Exception as e:
            print(f"[SemanticEngine] Error: {e}, falling back to LIKE matching")

    # Fallback: Traditional LIKE matching
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # First try exact match
    cursor.execute(
        "SELECT error_message, solution_text, timestamp FROM solutions WHERE error_message = ? ORDER BY timestamp DESC LIMIT 1",
        (error_message,)
    )
    result = cursor.fetchone()

    if not result:
        # Try partial match - search for key parts of the error
        search_key = error_message[:100] if len(error_message) > 100 else error_message
        cursor.execute(
            "SELECT error_message, solution_text, timestamp FROM solutions WHERE error_message LIKE ? ORDER BY timestamp DESC LIMIT 1",
            (f"%{search_key}%",)
        )
        result = cursor.fetchone()

    conn.close()

    if result:
        return {
            "matched_error": result[0],
            "solution": result[1],
            "saved_at": result[2],
            "match_type": "exact" if error_message == result[0] else "partial"
        }
    return None


def find_solution_hybrid(error_message: str, semantic_engine=None) -> Optional[dict]:
    """
    Search for a solution in both personal and team databases.
    Returns the solution with its source.
    """
    # Check personal DB first (priority)
    personal_result = find_similar_solution(error_message, PERSONAL_DB_PATH, semantic_engine)
    if personal_result:
        personal_result["source"] = "personal"
        return personal_result

    # Check team DB if configured
    if TEAM_DB_PATH and TEAM_DB_PATH.exists():
        team_result = find_similar_solution(error_message, TEAM_DB_PATH, semantic_engine)
        if team_result:
            team_result["source"] = "team"
            return team_result

    return None


def save_solution(error_message: str, solution_text: str, db_path: Path, semantic_engine=None) -> dict:
    """
    Save a new solution to the database.
    Uses semantic engine if available for cleaning and vectorization.
    """
    if semantic_engine:
        try:
            solution_id = semantic_engine.save_solution(error_message, solution_text)
            return {
                "status": "ok",
                "message": "Solution saved (semantic)",
                "solution_id": solution_id
            }
        except Exception as e:
            print(f"[SemanticEngine] Save error: {e}, falling back to direct insert")

    # Fallback: Direct insert
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()

    cursor.execute(
        "INSERT INTO solutions (error_message, solution_text, timestamp) VALUES (?, ?, ?)",
        (error_message, solution_text, timestamp)
    )
    solution_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "status": "ok",
        "message": "Solution saved",
        "solution_id": solution_id
    }


def delete_solution(solution_id: int, db_path: Path) -> bool:
    """Delete a solution by ID."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM solutions WHERE id = ?", (solution_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


# Initialize databases on module load
def init_all_databases():
    """Initialize all configured databases."""
    init_db(PERSONAL_DB_PATH, "Personal DB")
    if TEAM_DB_PATH:
        init_db(TEAM_DB_PATH, "Team DB")
