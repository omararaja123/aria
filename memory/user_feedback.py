"""
User Feedback Module

Tracks human actions during newsletter review (approvals, rejections, removals).
Used by evals layer to compute relevance and calibration metrics.
"""

from typing import List, Optional
import uuid
from datetime import datetime

from memory.db import get_db


def save_feedback(
    run_id: str,
    article_id: str,
    source_domain: str,
    action: str,
    feedback: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Save a user feedback action for an article in a run.

    Args:
        run_id: Identifier for this newsletter run
        article_id: Identifier for the article
        source_domain: Domain of the article source (for calibration evals)
        action: "remove", "keep", "reorder", etc.
        feedback: "approved" or "rejected" (sentiment from human)
        notes: Optional reviewer notes

    Returns:
        feedback_id (UUID)
    """
    feedback_id = str(uuid.uuid4())

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_feedback
                (feedback_id, run_id, article_id, source_domain, action, feedback, timestamp, reviewer_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (feedback_id, run_id, article_id, source_domain, action, feedback, datetime.now(), notes))
    except Exception as e:
        print(f"Warning: Failed to save feedback: {e}")
        return feedback_id

    return feedback_id


def get_feedback_for_run(run_id: str) -> List[dict]:
    """Get all feedback records for a given run."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT feedback_id, run_id, article_id, source_domain, action, feedback, timestamp, reviewer_notes
                FROM user_feedback
                WHERE run_id = ?
                ORDER BY timestamp
            """, (run_id,))

            rows = cursor.fetchall()
            return [
                {
                    "feedback_id": row[0],
                    "run_id": row[1],
                    "article_id": row[2],
                    "source_domain": row[3],
                    "action": row[4],
                    "feedback": row[5],
                    "timestamp": row[6],
                    "reviewer_notes": row[7],
                }
                for row in rows
            ]
    except Exception as e:
        print(f"Warning: Failed to read feedback for run {run_id}: {e}")
        return []


def get_all_feedback(limit: int = 1000) -> List[dict]:
    """Get all feedback records (across all runs)."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT feedback_id, run_id, article_id, source_domain, action, feedback, timestamp, reviewer_notes
                FROM user_feedback
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()
            return [
                {
                    "feedback_id": row[0],
                    "run_id": row[1],
                    "article_id": row[2],
                    "source_domain": row[3],
                    "action": row[4],
                    "feedback": row[5],
                    "timestamp": row[6],
                    "reviewer_notes": row[7],
                }
                for row in rows
            ]
    except Exception as e:
        print(f"Warning: Failed to read all feedback: {e}")
        return []
