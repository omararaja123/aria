"""
ARIA Evals Layer

Evaluation system for measuring agent performance over time.
- relevance_rate: how well did our ranking match human preferences?
- dedup_precision: how well did we avoid duplicate articles?
- source_calibration: how well did our credibility scores match human feedback?

All metrics are logged to SQLite and tracked across runs.
"""

from evals.eval_runner import run_evals, get_recent_eval_runs
from evals.relevance_eval import relevance_rate_eval
from evals.dedup_eval import dedup_precision_eval
from evals.source_eval import source_calibration_eval

__all__ = [
    "run_evals",
    "get_recent_eval_runs",
    "relevance_rate_eval",
    "dedup_precision_eval",
    "source_calibration_eval",
]
