"""
Relevance Evaluation Module

Computes relevance_rate metric: approved articles / (approved + rejected)
Measures how well the ranking and selection matched human preferences.
"""

from typing import Tuple, Dict, Any
from memory.db import get_db


def relevance_rate_eval(run_id: str) -> Tuple[float, Dict[str, Any]]:
    """
    Compute relevance rate for a given run.

    Relevance rate = approved_count / (approved_count + rejected_count)

    This metric measures: Did our article selection and ranking match the human's preferences?
    - 1.0 = Human approved all articles
    - 0.5 = Human approved half the articles
    - 0.0 = Human rejected all articles

    Args:
        run_id: Identifier for this newsletter run

    Returns:
        Tuple of (score: float, details: dict)
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Query user_feedback for this run, group by feedback type
            cursor.execute("""
                SELECT feedback, COUNT(*) as count
                FROM user_feedback
                WHERE run_id = ?
                GROUP BY feedback
            """, (run_id,))

            results = cursor.fetchall()
            approved = 0
            rejected = 0
            total = 0

            for feedback, count in results:
                if feedback == "approved":
                    approved = count
                elif feedback == "rejected":
                    rejected = count
                total += count

            # Handle edge cases
            if total == 0:
                return 0.5, {
                    "approved": 0,
                    "rejected": 0,
                    "total": 0,
                    "message": "No feedback recorded for this run",
                    "score": 0.5,
                }

            # Compute relevance rate
            score = approved / (approved + rejected) if (approved + rejected) > 0 else 0.5

            return score, {
                "approved": approved,
                "rejected": rejected,
                "total": total,
                "rate": f"{score:.1%}",
                "score": round(score, 3),
            }

    except Exception as e:
        print(f"Error computing relevance_rate_eval for run {run_id}: {e}")
        return 0.5, {"error": str(e), "score": 0.5}
