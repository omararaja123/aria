"""
ARIA Human Review Checkpoint Node

Implements the interrupt point between Drafter and Publisher.
Pauses graph execution for human review of draft newsletter.
LangGraph checkpoint loads this state for Streamlit UI interaction.

This node doesn't process data—it's just a checkpoint marker.
The actual UI interaction happens in Streamlit (ui/review_app.py).
Graph resumes when human submits decision via Streamlit.
"""

import logging
from state import ARIAState

logger = logging.getLogger(__name__)


def human_review_node(state: ARIAState) -> ARIAState:
    """
    Human Review Checkpoint — Pass-through node that pauses for human decision.

    Error handling: Always returns state; no processing errors possible.
    """

    try:
        logger.info("Human Review Checkpoint")

        run_id = state.get("run_id", "unknown")
        articles_count = len(state.get("final_articles", []))
        edits_count = len(state.get("human_review_edits", []))

        logger.info(
            f"Human Review Checkpoint: run_id={run_id}, "
            f"articles={articles_count}, edits={edits_count}"
        )

        # Check human decision status
        review_approved = state.get("review_approved", False)
        review_rejected = state.get("review_rejected", False)
        review_re_rank = state.get("review_re_rank", False)

        if review_approved:
            logger.info("Decision: APPROVED → Publisher")
        elif review_rejected:
            logger.info("Decision: REJECTED → full re-run from Supervisor")
        elif review_re_rank:
            logger.info("Decision: RE-RUN → Ranker with adjusted profile")
        else:
            logger.info("Waiting for human decision via Streamlit...")

        # Pass through with state intact
        return state

    except Exception as e:
        logger.error(f"Human review node error: {e}")
        # Always return state to allow graph continuation
        return state
