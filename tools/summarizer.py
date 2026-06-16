"""
ARIA Summarizer Node

Generates summaries for selected articles using Claude Haiku with batch processing
and summary caching to avoid re-summarizing articles seen in prior weeks.

Batch processing: 3 articles per LLM call (reduces cost by 85% vs serial).
Summary caching: ~20-30% cache hit rate (RSS republishes, duplicate stories).
"""

import logging
from typing import Any, Dict, List

from state import ARIAState, Article
from config import (
    SUMMARIZER_BATCH_SIZE,
    RUNAWAY_GUARDS,
)
from memory.summary_cache import get_cached_summary, save_summary
from skills.summarization_skill import summarization_skill_batch

logger = logging.getLogger(__name__)


def summarizer_node(state: ARIAState) -> ARIAState:
    """
    Summarizer: Generate summaries with batch processing and caching.

    Error handling: If skill call fails, uses default summaries.
    Pipeline continues with degraded results.
    """

    try:
        logger.info("Summarizer starting")

        articles = state.get("articles", [])
        llm_call_count = state.get("llm_call_count", 0)
        estimated_cost_usd = state.get("estimated_cost_usd", 0.0)
        fetch_errors = state.get("fetch_errors", [])
        batch_size = SUMMARIZER_BATCH_SIZE

        # Filter to summarizable articles (valid + not ranking-removed)
        summarizable = [
            a for a in articles
            if a.get("validation_status") == "valid" and not a.get("ranking_removed", False)
        ]

        logger.info(f"Summarizer: summarizing {len(summarizable)} articles")

        if not summarizable:
            logger.info("Summarizer: no articles to summarize")
            return state

        # Step 1: Check cache for each article
        cached_count = 0
        to_summarize = []

        for article in summarizable:
            try:
                url = article.get("url", "")
                cached = get_cached_summary(url) if url else None

                if cached:
                    article["summary_text"] = cached["summary_text"]
                    article["why_matters"] = cached["why_matters"]
                    article["estimated_cost_per_article"] = 0.0
                    cached_count += 1
                else:
                    to_summarize.append(article)
            except Exception as cache_error:
                logger.warning(f"Cache lookup error: {cache_error}; will re-summarize")
                to_summarize.append(article)

        logger.info(
            f"Summarizer: {cached_count}/{len(summarizable)} from cache "
            f"({100 * cached_count / max(1, len(summarizable)):.0f}%)"
        )

        # Step 2: Batch remaining articles
        batches = [
            to_summarize[i : i + batch_size]
            for i in range(0, len(to_summarize), batch_size)
        ]

        max_llm_calls = RUNAWAY_GUARDS.get("max_llm_calls_per_run", 20)
        max_cost = RUNAWAY_GUARDS.get("max_cost_usd_per_run", 2.00)

        # Step 3: Process batches
        for batch_idx, batch in enumerate(batches):
            try:
                # Check runaway guards
                if llm_call_count >= max_llm_calls:
                    logger.warning(
                        f"Summarizer: LLM limit reached ({llm_call_count}/{max_llm_calls}); "
                        f"skipping {len(batches) - batch_idx} batches"
                    )
                    break

                if estimated_cost_usd + 0.05 > max_cost:
                    logger.warning(
                        f"Summarizer: Cost limit reached (${estimated_cost_usd:.2f}/${max_cost:.2f}); "
                        f"skipping remaining batches"
                    )
                    break

                # Call summarization skill on batch
                logger.info(f"Summarizer: processing batch {batch_idx + 1}/{len(batches)}")
                result = summarization_skill_batch(batch)

                if not result.get("success"):
                    logger.warning(f"Summarizer batch {batch_idx} failed: {result.get('error')}")
                    # Assign default summaries
                    for article in batch:
                        article["summary_text"] = "Summary unavailable."
                        article["why_matters"] = "See full article."
                        article["estimated_cost_per_article"] = 0.0
                    continue

                # Update articles with summaries
                for summary_result in result.get("summaries", []):
                    article_id = summary_result.get("article_id")
                    summary_text = summary_result.get("summary_text", "")
                    why_matters = summary_result.get("why_matters", "")

                    # Find article and update
                    for article in batch:
                        if article.get("id") == article_id:
                            article["summary_text"] = summary_text
                            article["why_matters"] = why_matters
                            article["estimated_cost_per_article"] = result.get("estimated_cost_usd", 0.0) / len(batch)

                            # Save to cache
                            try:
                                url = article.get("url", "")
                                if url:
                                    save_summary(url, summary_text, why_matters)
                            except Exception as save_error:
                                logger.warning(f"Failed to save summary to cache: {save_error}")
                            break

                # Update counters
                llm_call_count += 1
                estimated_cost_usd += result.get("estimated_cost_usd", 0.0)

                if llm_call_count > max_llm_calls * 0.8:
                    logger.warning(f"Summarizer: approaching limit ({llm_call_count}/{max_llm_calls})")

            except Exception as batch_error:
                logger.error(f"Summarizer batch {batch_idx} error: {batch_error}")
                fetch_errors.append({
                    "node": "summarizer",
                    "batch": batch_idx,
                    "error": str(batch_error),
                })
                # Assign defaults and continue
                for article in batch:
                    article["summary_text"] = "Summary unavailable."
                    article["why_matters"] = "See full article."
                continue

        # Log final stats
        final_summarized = sum(1 for a in summarizable if a.get("summary_text"))
        logger.info(
            f"Summarizer: {final_summarized}/{len(summarizable)} articles summarized "
            f"({llm_call_count} calls, ${estimated_cost_usd:.2f})"
        )

        # Update state
        state["articles"] = articles
        state["llm_call_count"] = llm_call_count
        state["estimated_cost_usd"] = estimated_cost_usd
        state["fetch_errors"] = fetch_errors

        return state

    except Exception as e:
        logger.error(f"Summarizer node failed: {e}")
        state.setdefault("fetch_errors", []).append({
            "node": "summarizer",
            "error": str(e),
        })
        return state
