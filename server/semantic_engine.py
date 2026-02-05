"""
Semantic Engine for Nati-Debugger V2
Uses TF-IDF vectorization and Cosine Similarity for semantic error matching.

This is a lightweight alternative to sentence-transformers that works without PyTorch.
"""

import re
import pickle
import sqlite3
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, List
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class SemanticEngine:
    """
    Semantic search engine for error messages.
    Uses TF-IDF + Cosine Similarity for finding similar errors.
    """

    # Minimum similarity threshold for a match
    # V2.1: Lowered from 0.65 to 0.50 for better recall with TF-IDF
    SIMILARITY_THRESHOLD = 0.30

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 3),  # Use 1-3 word combinations
            stop_words=None,    # Keep all words for code errors
            lowercase=True,
            analyzer='word',
            token_pattern=r'(?u)\b\w+\b'  # Match single characters too
        )
        self._corpus: List[str] = []
        self._ids: List[int] = []
        self._matrix = None
        self._is_fitted = False

        # Load existing solutions on init
        self._load_corpus()

    @staticmethod
    def clean_error(text: str) -> str:
        """
        Normalize error text by removing variable parts.
        This makes matching more robust across different instances.
        """
        if not text:
            return ""

        cleaned = text

        # Remove timestamps (various formats)
        cleaned = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d]*Z?', '', cleaned)
        cleaned = re.sub(r'\d{2}:\d{2}:\d{2}[.\d]*', '', cleaned)

        # Remove line numbers and column numbers
        cleaned = re.sub(r':\d+:\d+', '', cleaned)
        cleaned = re.sub(r'line \d+', 'line X', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'column \d+', 'column X', cleaned, flags=re.IGNORECASE)

        # Remove file paths (keep filename only)
        cleaned = re.sub(r'(/[\w\-./]+/)([\w\-]+\.\w+)', r'\2', cleaned)
        cleaned = re.sub(r'(\\[\w\-\\]+\\)([\w\-]+\.\w+)', r'\2', cleaned)

        # Remove variable IDs (common patterns)
        cleaned = re.sub(r'fld_\d+_\d+', 'fld_ID', cleaned)
        cleaned = re.sub(r'field_\d+_\d+', 'field_ID', cleaned)
        cleaned = re.sub(r'rev_\d+_\d+', 'rev_ID', cleaned)
        cleaned = re.sub(r'_\d{10,}', '_TIMESTAMP', cleaned)
        cleaned = re.sub(r'0x[a-fA-F0-9]+', '0xADDR', cleaned)

        # Remove specific numbers in coords but keep structure
        cleaned = re.sub(r'\((\d+\.?\d*),\s*(\d+\.?\d*)\)', '(X, Y)', cleaned)
        cleaned = re.sub(r'\[(\d+\.?\d*),\s*(\d+\.?\d*)\]', '[X, Y]', cleaned)

        # Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        return cleaned

    def _load_corpus(self):
        """Load all existing solutions and build the TF-IDF matrix."""
        if not self.db_path.exists():
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT id, error_message, error_clean
                FROM solutions
                ORDER BY id
            """)
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            # Table might not have error_clean column yet
            cursor.execute("SELECT id, error_message FROM solutions ORDER BY id")
            rows = [(r[0], r[1], None) for r in cursor.fetchall()]

        conn.close()

        if not rows:
            return

        self._ids = []
        self._corpus = []

        for row in rows:
            solution_id, error_msg, error_clean = row
            # Use cleaned version if available, otherwise clean now
            clean_text = error_clean if error_clean else self.clean_error(error_msg)
            self._ids.append(solution_id)
            self._corpus.append(clean_text)

        # Fit and transform
        if self._corpus:
            self._matrix = self.vectorizer.fit_transform(self._corpus)
            self._is_fitted = True
            print(f"[SemanticEngine] Loaded {len(self._corpus)} solutions into corpus")

    def add_to_corpus(self, solution_id: int, error_clean: str):
        """Add a new solution to the corpus without full rebuild."""
        self._ids.append(solution_id)
        self._corpus.append(error_clean)

        # Rebuild matrix (necessary for TF-IDF)
        if self._corpus:
            self._matrix = self.vectorizer.fit_transform(self._corpus)
            self._is_fitted = True

    def find_similar(self, error_text: str) -> Optional[Tuple[int, float, str]]:
        """
        Find the most similar error in the database.

        Args:
            error_text: The raw error message

        Returns:
            Tuple of (solution_id, similarity_score, matched_error) or None if no match
        """
        if not self._is_fitted or len(self._corpus) == 0:
            print(f"[SemanticEngine] Not fitted or empty corpus")
            return None

        # Clean the input error
        clean_text = self.clean_error(error_text)
        print(f"[SemanticEngine] Searching for: {clean_text[:50]}...")

        if not clean_text:
            return None

        try:
            # Transform using the fitted vectorizer
            query_vector = self.vectorizer.transform([clean_text])

            # Calculate cosine similarity with all stored vectors
            similarities = cosine_similarity(query_vector, self._matrix)[0]

            # Find the best match
            best_idx = np.argmax(similarities)
            best_score = similarities[best_idx]
            print(f"[SemanticEngine] Best match: {self._corpus[best_idx][:50]}... (score: {best_score:.2f})")

            if best_score >= self.SIMILARITY_THRESHOLD:
                return (
                    self._ids[best_idx],
                    float(best_score),
                    self._corpus[best_idx]
                )

        except Exception as e:
            print(f"[SemanticEngine] Error in find_similar: {e}")

        return None

    def get_solution_by_id(self, solution_id: int) -> Optional[dict]:
        """Get a solution by its ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, error_message, solution_text, timestamp, confidence_score, success_count
            FROM solutions WHERE id = ?
        """, (solution_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "id": row[0],
                "error_message": row[1],
                "solution_text": row[2],
                "timestamp": row[3],
                "confidence_score": row[4] or 1.0,
                "success_count": row[5] or 0
            }
        return None

    def increment_success_count(self, solution_id: int):
        """Increment the success count for a solution."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE solutions
            SET success_count = COALESCE(success_count, 0) + 1
            WHERE id = ?
        """, (solution_id,))
        conn.commit()
        conn.close()

    def save_solution(self, error_message: str, solution_text: str) -> int:
        """Save a new solution with cleaned text."""
        error_clean = self.clean_error(error_message)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        from datetime import datetime
        timestamp = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO solutions (error_message, solution_text, timestamp, error_clean, confidence_score, success_count)
            VALUES (?, ?, ?, ?, 1.0, 0)
        """, (error_message, solution_text, timestamp, error_clean))

        solution_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Add to corpus
        self.add_to_corpus(solution_id, error_clean)

        return solution_id


# Singleton instance
_engine: Optional[SemanticEngine] = None


def get_engine(db_path: Path) -> SemanticEngine:
    """Get or create the semantic engine singleton."""
    global _engine
    if _engine is None:
        _engine = SemanticEngine(db_path)
    return _engine


def reset_engine():
    """Reset the engine (useful for testing)."""
    global _engine
    _engine = None
