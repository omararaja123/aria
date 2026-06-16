"""
ARIA Ranker Node

Scores articles by relevance using Claude Haiku with batch processing.
Assigns articles to newsletter sections and selects top 15–20 for final newsletter.

Batch processing: 5 articles per LLM call (reduces cost by 80% vs serial).
"""

import logging
from typing import Any, Dict, List

from state import ARIAState, Article
from config import (
    NEWSLETTER_SECTIONS,
    FINAL_ARTICLE_COUNT,
    RANKER_MODEL,
    RUNAWAY_GUARDS,
)
from skills.relevance_skill import relevance_skill_batch

logger = logging.getLogger(__name__)


def ranker_node(state: ARIAState) -> ARIAState:
    """
    Ranker: Score articles by relevance and select top 15–20.

    Error handling: If skill call fails, uses default values (0.5, "Trending").
    Pipeline continues with degraded results.
    """

    try:
        logger.info("Ranker starting")

        articles = state.get("articles", [])
        llm_call_count = state.get("llm_call_count", 0)
        estimated_cost_usd = state.get("estimated_cost_usd", 0.0)
        fetch_errors = state.get("fetch_errors", [])

        # Get interest profile (human edits take precedence)
        interest_profile = state.get("interest_profile_edits") or state.get("interest_profile", {})

        # Filter to rankable articles (valid + not deduplicated)
        rankable = [
            a for a in articles
            if a.get("validation_status") == "valid" and not a.get("dedup_removed", False)
        ]

        logger.info(f"Ranker: ranking {len(rankable)} articles")

        if not rankable:
            logger.info("Ranker: no rankable articles; returning unchanged")
            return state

        # Batch articles (5 per batch)
        batch_size = 5
        batches = [rankable[i : i + batch_size] for i in range(0, len(rankable), batch_size)]

        # Initialize stats
        stats = {
            "total_scored": len(rankable),
            "batches_processed": 0,
            "llm_calls": 0,
            "sections": {section: 0 for section in NEWSLETTER_SECTIONS},
        }

        max_llm_calls = RUNAWAY_GUARDS.get("max_llm_calls_per_run", 20)
        max_cost = RUNAWAY_GUARDS.get("max_cost_usd_per_run", 2.00)

        # Process batches
        for batch_idx, batch in enumerate(batches):
            try:
                # Check runaway guards before making call
                if llm_call_count >= max_llm_calls:
                    logger.warning(
                        f"Ranker: LLM call limit reached ({llm_call_count}/{max_llm_calls}); "
                        f"skipping remaining {len(batches) - batch_idx} batches"
                    )
                    break

                if estimated_cost_usd + 0.02 > max_cost:
                    logger.warning(
                        f"Ranker: Cost budget reached (${estimated_cost_usd:.2f}/${max_cost:.2f}); "
                        f"skipping remaining batches"
                    )
                    break

                # Call relevance skill on batch
                logger.info(f"Ranker: processing batch {batch_idx + 1}/{len(batches)}")
                result = relevance_skill_batch(batch, interest_profile)

                if not result.get("success"):
                    logger.warning(f"Ranker batch {batch_idx} failed: {result.get('error')}")
                    # Mark batch articles with default values
                    for article in batch:
                        article["relevance_score"] = 0.5
                        article["section"] = "Trending"
                        article["ranking_reason"] = "Default (skill error)"
                    continue

                # Update articles with scores and sections
                for score_result in result.get("results", []):
                    article_id = score_result.get("article_id")
                    relevance_score = score_result.get("relevance_score", 0.5)
                    section = score_result.get("section", "Trending")

                    # Find article and update
                    for article in batch:
                        if article.get("id") == article_id:
                            article["relevance_score"] = relevance_score
                            article["section"] = section
                            article["ranking_reason"] = score_result.get("reasoning", "")
                            stats["sections"][section] = stats["sections"].get(section, 0) + 1
                            break

                # Update counters
                llm_call_count += 1
                estimated_cost_usd += result.get("estimated_cost_usd", 0.0)
                stats["batches_processed"] += 1
                stats["llm_calls"] = llm_call_count

                if llm_call_count > max_llm_calls * 0.8:
                    logger.warning(f"Ranker: approaching LLM limit ({llm_call_count}/{max_llm_calls})")

            except Exception as batch_error:
                logger.error(f"Ranker batch {batch_idx} error: {batch_error}")
                fetch_errors.append({
                    "node": "ranker",
                    "batch": batch_idx,
                    "error": str(batch_error),
                })
                # Mark batch articles with defaults and continue
                for article in batch:
                    article["relevance_score"] = 0.5
                    article["section"] = "Trending"
                continue

        # Sort by relevance and select top N articles
        scored_articles = sorted(
            rankable,
            key=lambda a: a.get("relevance_score", 0.0),
            reverse=True,
        )

        final_count = min(FINAL_ARTICLE_COUNT, len(scored_articles))
        final_articles = scored_articles[:final_count]

        logger.info(
            f"Ranker: selected {len(final_articles)}/{len(rankable)} articles "
            f"({llm_call_count} calls, ${estimated_cost_usd:.2f})"
        )

        # Mark articles not in final list as removed
        final_ids = {a.get("id") for a in final_articles}
        for article in articles:
            if article.get("id") not in final_ids and article.get("validation_status") == "valid":
                if not article.get("dedup_removed", False):
                    article["ranking_removed"] = True

        # Update state
        state["articles"] = articles
        state["ranking_stats"] = stats
        state["llm_call_count"] = llm_call_count
        state["estimated_cost_usd"] = estimated_cost_usd
        state["fetch_errors"] = fetch_errors

        return state

    except Exception as e:
        logger.error(f"Ranker node failed: {e}")
        state.setdefault("fetch_errors", []).append({
            "node": "ranker",
            "error": str(e),
        })
        return state
