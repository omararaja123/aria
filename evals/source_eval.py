"""
Source Credibility Calibration Evaluation Module

Computes source_calibration metric: how well agent's credibility scores match human approval.
Measures if high-credibility sources had high approval rates (and vice versa).
"""

from typing import Tuple, Dict, Any
from memory.db import get_db


def source_calibration_eval(run_id: str) -> Tuple[float, Dict[str, Any]]:
    """
    Compute source credibility calibration for a given run.

    Calibration = agreement between agent's credibility score and human approval rate.

    For each source domain in the published articles:
    - Get agent's credibility_score from source_scores table
    - Get human's approval rate from user_feedback
    - Compute agreement: 1.0 - |credibility_score - approval_rate|
    - Average agreement across all sources

    This metric measures: Did the agent's credibility assessment match human feedback?
    - 1.0 = Perfect calibration (agent scores matched human approvals)
    - 0.5 = Moderate calibration (some agreement)
    - 0.0 = Terrible calibration (agent scores opposite of human approvals)

    Args:
        run_id: Identifier for this newsletter run

    Returns:
        Tuple of (score: float, details: dict)
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Get feedback by source domain for this run
            cursor.execute("""
                SELECT source_domain, feedback, COUNT(*) as count
                FROM user_feedback
                WHERE run_id = ?
                GROUP BY source_domain, feedback
            """, (run_id,))

            feedback_results = cursor.fetchall()

            # Aggregate feedback by source
            source_feedback = {}
            for source_domain, feedback, count in feedback_results:
                if source_domain not in source_feedback:
                    source_feedback[source_domain] = {"approved": 0, "rejected": 0}
                if feedback == "approved":
                    source_feedback[source_domain]["approved"] += count
                elif feedback == "rejected":
                    source_feedback[source_domain]["rejected"] += count

            # Handle no feedback case
            if not source_feedback:
                return 0.5, {
                    "message": "No source feedback recorded",
                    "sources_analyzed": 0,
                    "score": 0.5,
                }

            # For each source, compute calibration
            calibration_scores = []
            source_details = {}

            for source_domain, stats in source_feedback.items():
                approved = stats["approved"]
                rejected = stats["rejected"]
                total = approved + rejected

                # Human approval rate
                human_approval = approved / total if total > 0 else 0.5

                # Get agent's credibility score
                cursor.execute("""
                    SELECT credibility_score
                    FROM source_scores
                    WHERE domain = ?
                """, (source_domain,))

                score_row = cursor.fetchone()
                agent_score = score_row[0] if score_row else 0.5

                # Calibration: 1.0 - absolute difference
                diff = abs(agent_score - human_approval)
                calibration = 1.0 - diff

                calibration_scores.append(calibration)
                source_details[source_domain] = {
                    "agent_credibility_score": round(agent_score, 2),
                    "human_approval_rate": round(human_approval, 2),
                    "calibration": round(calibration, 2),
                    "articles_approved": approved,
                    "articles_rejected": rejected,
                    "total_articles": total,
                }

            # Average calibration across all sources
            overall_calibration = sum(calibration_scores) / len(calibration_scores)

            return overall_calibration, {
                "overall": round(overall_calibration, 3),
                "sources": source_details,
                "sources_analyzed": len(source_feedback),
                "calibration_range": f"{min(calibration_scores):.2f} - {max(calibration_scores):.2f}",
                "score": round(overall_calibration, 3),
            }

    except Exception as e:
        print(f"Error computing source_calibration_eval for run {run_id}: {e}")
        return 0.5, {"error": str(e), "score": 0.5}
