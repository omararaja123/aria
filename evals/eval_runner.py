"""
Evaluation Runner Module

Main orchestrator for the evals layer.
Computes all metrics for a given run, logs to database, returns summary.
"""

from typing import Dict, Any
import uuid
import json
from datetime import datetime

from memory.db import get_db
from evals.relevance_eval import relevance_rate_eval
from evals.dedup_eval import dedup_precision_eval
from evals.source_eval import source_calibration_eval


def run_evals(run_id: str) -> Dict[str, Any]:
    """
    Compute all evaluation metrics for a given run.

    Evals:
    1. Relevance Rate: approved / (approved + rejected)
    2. Dedup Precision: unique_articles / total_articles
    3. Source Calibration: agent_scores vs human_approval

    All metrics are logged to eval_results table in SQLite.

    Args:
        run_id: Identifier for this newsletter run

    Returns:
        {
            "run_id": str,
            "timestamp": str (ISO format),
            "metrics": {
                "relevance_rate": float,
                "dedup_precision": float,
                "source_calibration": float,
            },
            "details": {
                "relevance_rate": dict,
                "dedup_precision": dict,
                "source_calibration": dict,
            },
            "summary": str (human-readable)
        }
    """
    # Compute all evals
    relevance_score, relevance_details = relevance_rate_eval(run_id)
    dedup_score, dedup_details = dedup_precision_eval(run_id)
    calibration_score, calibration_details = source_calibration_eval(run_id)

    timestamp = datetime.now().isoformat()

    # Metrics dict
    metrics = {
        "relevance_rate": round(relevance_score, 3),
        "dedup_precision": round(dedup_score, 3),
        "source_calibration": round(calibration_score, 3),
    }

    # Log to eval_results table
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            for metric_name, value in metrics.items():
                eval_id = str(uuid.uuid4())

                # Determine which details correspond to this metric
                if metric_name == "relevance_rate":
                    details = relevance_details
                elif metric_name == "dedup_precision":
                    details = dedup_details
                else:  # source_calibration
                    details = calibration_details

                details_json = json.dumps(details)

                cursor.execute("""
                    INSERT INTO eval_results
                    (eval_id, run_id, metric_name, value, details, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (eval_id, run_id, metric_name, value, details_json, timestamp))

    except Exception as e:
        print(f"Warning: Failed to log eval results to database: {e}")

    # Generate human-readable summary
    summary = f"""
ARIA Evaluation Results for {run_id}
=====================================
Relevance Rate:        {metrics['relevance_rate']:.1%} ({relevance_details.get('approved', 0)} approved, {relevance_details.get('rejected', 0)} rejected)
Dedup Precision:       {metrics['dedup_precision']:.1%} ({dedup_details.get('unique_articles', 0)} unique articles)
Source Calibration:    {metrics['source_calibration']:.1%} (agent vs human agreement: {calibration_details.get('sources_analyzed', 0)} sources)
Timestamp:             {timestamp}
""".strip()

    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "metrics": metrics,
        "details": {
            "relevance_rate": relevance_details,
            "dedup_precision": dedup_details,
            "source_calibration": calibration_details,
        },
        "summary": summary,
    }


def get_recent_eval_runs(limit: int = 4) -> list[Dict[str, Any]]:
    """
    Get recent eval results for the metrics dashboard.

    Args:
        limit: Number of most recent runs to retrieve (default: 4)

    Returns:
        List of dicts with run_id and latest metrics
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Get unique run_ids with evals, ordered by most recent
            cursor.execute("""
                SELECT DISTINCT run_id, MAX(timestamp) as latest_timestamp
                FROM eval_results
                GROUP BY run_id
                ORDER BY latest_timestamp DESC
                LIMIT ?
            """, (limit,))

            run_rows = cursor.fetchall()

            recent_runs = []
            for run_id, timestamp in run_rows:
                # Get all metrics for this run
                cursor.execute("""
                    SELECT metric_name, value, details
                    FROM eval_results
                    WHERE run_id = ?
                    ORDER BY timestamp DESC
                """, (run_id,))

                metric_rows = cursor.fetchall()

                metrics = {}
                details = {}
                for metric_name, value, details_json in metric_rows:
                    if metric_name not in metrics:  # Take most recent of each metric
                        metrics[metric_name] = value
                        try:
                            details[metric_name] = json.loads(details_json)
                        except Exception:
                            details[metric_name] = {}

                recent_runs.append({
                    "run_id": run_id,
                    "timestamp": timestamp,
                    "metrics": metrics,
                    "details": details,
                })

            return recent_runs

    except Exception as e:
        print(f"Warning: Failed to read recent eval runs: {e}")
        return []
