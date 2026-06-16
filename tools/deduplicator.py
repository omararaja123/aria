"""
ARIA Deduplicator Node

Removes duplicate stories within this run and across weeks.
Uses three strategies:
1. Exact URL matching (within run)
2. Cryptographic fingerprinting (title + domain, within run and cross-week)
3. Optional: Fuzzy title similarity (Phase 14 enhancement, not in Phase 1)
"""

import logging
from typing import Dict, List, Set

from state import ARIAState, Article
from memory.story_memory import (
    compute_fingerprint,
    is_story_seen,
    get_recent_fingerprints,
)

logger = logging.getLogger(__name__)


def deduplicator_node(state: ARIAState) -> ARIAState:
    """
    Deduplicator: Remove duplicate stories.

    Error handling: Memory lookups that fail are handled gracefully.
    Pipeline continues without cross-week dedup if needed.
    """

    try:
        logger.info("Deduplicator starting")

        articles = state.get("articles", [])
        fetch_errors = state.get("fetch_errors", [])

        # Filter to only valid articles
        valid_articles = [a for a in articles if a.get("validation_status") == "valid"]

        # Load cross-week fingerprints (with error handling)
        try:
            recent_fingerprints = get_recent_fingerprints(weeks_back=4)
        except Exception as fp_error:
            logger.warning(f"Failed to load fingerprints from memory: {fp_error}; continuing without cross-week dedup")
            recent_fingerprints = set()

        # Initialize stats
        stats = {
            "exact_dupes": 0,
            "cross_week_dupes": 0,
            "removed_count": 0,
            "valid_count": len(valid_articles),
        }

        # Track seen URLs and fingerprints in this run
        seen_urls: Set[str] = set()
        seen_fingerprints: Set[str] = set()

        for article in articles:
            try:
                # Skip already-removed articles
                if article.get("validation_status") != "valid":
                    continue

                url = article.get("url", "")
                title = article.get("title", "")
                domain = article.get("source_domain", "")

                # Strategy 1: Exact URL dedup
                if url in seen_urls:
                    article["dedup_removed"] = True
                    article["dedup_reason"] = "exact_url"
                    stats["exact_dupes"] += 1
                    stats["removed_count"] += 1
                    continue

                if url:
                    seen_urls.add(url)

                # Strategy 2: Fingerprint (within run)
                try:
                    fingerprint = compute_fingerprint(title, domain)
                except Exception as fp_compute_error:
                    logger.warning(f"Fingerprint computation error: {fp_compute_error}; marking as unique")
                    fingerprint = None

                if fingerprint and fingerprint in seen_fingerprints:
                    article["dedup_removed"] = True
                    article["dedup_reason"] = "title_match"
                    stats["exact_dupes"] += 1
                    stats["removed_count"] += 1
                    continue

                if fingerprint:
                    seen_fingerprints.add(fingerprint)

                # Strategy 3: Cross-week check
                if fingerprint and fingerprint in recent_fingerprints:
                    article["dedup_removed"] = True
                    article["dedup_reason"] = "cross_week"
                    stats["cross_week_dupes"] += 1
                    stats["removed_count"] += 1
                    continue

                # Article passed all checks
                article["dedup_removed"] = False

            except Exception as article_error:
                logger.warning(f"Error deduplicating article: {article_error}; keeping article")
                article["dedup_removed"] = False

        logger.info(
            f"Deduplicator: {len(valid_articles)} valid → "
            f"{len(valid_articles) - stats['removed_count']} after dedup "
            f"({stats['exact_dupes']} exact, {stats['cross_week_dupes']} cross-week)"
        )

        state["articles"] = articles
        state["dedup_stats"] = stats
        state["fetch_errors"] = fetch_errors

        return state

    except Exception as e:
        logger.error(f"Deduplicator node failed: {e}")
        state.setdefault("fetch_errors", []).append({
            "node": "deduplicator",
            "error": str(e),
        })
        return state
