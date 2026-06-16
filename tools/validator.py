"""
ARIA Validator Node

Scores articles by credibility, filters by date and quality thresholds,
and applies circuit breaker if too many articles pass through.

Updates each article in-place with validation_status, credibility_score, validation_reason.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List
from dateutil import parser as date_parser

from state import ARIAState, Article
from config import (
    KNOWN_CREDIBLE_SOURCES,
    RUNAWAY_GUARDS,
)
from memory.source_memory import (
    get_source_score,
    get_blacklisted_sources,
)
from skills.credibility_skill import credibility_skill

logger = logging.getLogger(__name__)


def parse_date(date_input: Any) -> datetime:
    """Parse date from string or datetime object."""
    if isinstance(date_input, datetime):
        return date_input
    if isinstance(date_input, str):
        try:
            return date_parser.parse(date_input)
        except Exception:
            return datetime.now()
    return datetime.now()


def validator_node(state: ARIAState) -> ARIAState:
    """
    Validator: Score, filter, and gate articles.

    Error handling: Credibility skill failures fall back to 0.5.
    Hard stop only if zero articles survive.
    """

    try:
        logger.info("Validator starting")

        articles = state.get("articles", [])
        run_timestamp = state.get("run_timestamp", datetime.now())
        fetch_errors = state.get("fetch_errors", [])

        # Config
        max_raw = RUNAWAY_GUARDS.get("max_raw_articles_total", 120)
        max_age_days = RUNAWAY_GUARDS.get("max_article_age_days", 7)
        credibility_floor = 0.3
        max_after_filtering = RUNAWAY_GUARDS.get("max_validated_articles", 60)

        # Load blacklisted sources
        try:
            blacklisted_sources = set(get_blacklisted_sources())
        except Exception as e:
            logger.warning(f"Failed to load blacklist: {e}; continuing without it")
            blacklisted_sources = set()

        # Runaway check
        if len(articles) > max_raw:
            logger.error(f"Runaway: {len(articles)} articles > max {max_raw}")
            raise RuntimeError(
                f"Runaway: Fetched {len(articles)} articles (max {max_raw}). "
                f"One subagent may be returning duplicates."
            )

        # Initialize stats
        stats = {
            "raw_count": len(articles),
            "filtered_by_date": 0,
            "filtered_by_credibility": 0,
            "filtered_by_blacklist": 0,
            "circuit_breaker_fired": False,
            "final_count": 0,
        }

        # Step 1: Score and filter each article
        for article in articles:
            try:
                domain = article.get("source_domain", "")
                published_date = parse_date(article.get("published_date", datetime.now()))

                # Normalize date (remove timezone for comparison)
                if published_date and hasattr(published_date, 'tzinfo') and published_date.tzinfo is not None:
                    published_date = published_date.replace(tzinfo=None)

                article["validation_status"] = "valid"
                article["validation_reason"] = None

                # Check date (must be within 7 days)
                cutoff_date = run_timestamp - timedelta(days=max_age_days)
                if published_date < cutoff_date:
                    article["validation_status"] = "removed"
                    article["validation_reason"] = "too_old"
                    stats["filtered_by_date"] += 1
                    logger.debug(f"Validator: rejecting old article from {published_date.date()}: {article.get('title', 'Unknown')[:60]}")
                    continue

                # Score credibility (with fallback to 0.5 on error)
                try:
                    credibility_score = _score_credibility(domain)
                except Exception as cred_error:
                    logger.warning(f"Credibility error for {domain}: {cred_error}; using 0.5")
                    credibility_score = 0.5

                article["credibility_score"] = credibility_score

                # Check blacklist
                if domain in blacklisted_sources:
                    article["validation_status"] = "removed"
                    article["validation_reason"] = "blacklisted"
                    stats["filtered_by_blacklist"] += 1
                    continue

                # Check credibility floor
                if credibility_score < credibility_floor and domain not in KNOWN_CREDIBLE_SOURCES:
                    article["validation_status"] = "removed"
                    article["validation_reason"] = "low_credibility"
                    stats["filtered_by_credibility"] += 1
                    continue

            except Exception as article_error:
                logger.warning(f"Error validating article: {article_error}; marking as removed")
                article["validation_status"] = "removed"
                article["validation_reason"] = "validation_error"
                fetch_errors.append({
                    "node": "validator",
                    "article_id": article.get("id"),
                    "error": str(article_error),
                })

        # Count validated articles
        validated = [a for a in articles if a.get("validation_status") == "valid"]
        stats["final_count"] = len(validated)

        logger.info(
            f"Validator: {len(articles)} raw → {len(validated)} validated "
            f"({stats['filtered_by_date']} date, {stats['filtered_by_credibility']} credibility)"
        )

        # Hard stop if zero articles survive
        if len(validated) == 0:
            logger.error("Validator: zero articles survived validation (unrecoverable)")
            raise RuntimeError(
                "All articles filtered out during validation. Check article sources and credibility settings."
            )

        # Step 2: Circuit breaker
        if len(validated) > max_after_filtering:
            logger.warning(
                f"Circuit breaker: {len(validated)} > {max_after_filtering}; trimming"
            )
            sorted_articles = sorted(
                validated,
                key=lambda a: a.get("credibility_score", 0.5),
                reverse=True,
            )
            trimmed = sorted_articles[:max_after_filtering]

            for article in validated:
                if article not in trimmed:
                    article["validation_status"] = "removed"
                    article["validation_reason"] = "circuit_breaker"

            stats["circuit_breaker_fired"] = True
            stats["final_count"] = len(trimmed)
            logger.info(f"Circuit breaker: trimmed to {len(trimmed)} articles")

        state["articles"] = articles
        state["validation_stats"] = stats
        state["fetch_errors"] = fetch_errors

        return state

    except Exception as e:
        logger.error(f"Validator node failed: {e}")
        raise  # Hard stop for runaway/validation failures


def _score_credibility(domain: str) -> float:
    """
    Score credibility of a source domain.

    Strategy:
    1. Check memory cache (from prior runs)
    2. If not cached, check KNOWN_CREDIBLE_SOURCES list (→ 0.9)
    3. If still unknown, call credibility_skill for LLM-based scoring
    4. Return the score (cached or fresh from LLM)
    """

    # Check memory cache
    cached_score = get_source_score(domain)
    if cached_score is not None:
        return cached_score

    # Check known credible sources
    if domain in KNOWN_CREDIBLE_SOURCES:
        return 0.9

    # Unknown domain: call credibility_skill (cache-first, calls LLM if not cached)
    try:
        result = credibility_skill(domain)
        if result.get("success"):
            score = result.get("data", {}).get("credibility_score", 0.5)
            return float(score)
        else:
            logger.warning(f"Credibility skill failed for {domain}: {result.get('error')}, using 0.5")
            return 0.5
    except Exception as e:
        logger.warning(f"Error calling credibility_skill for {domain}: {e}, using 0.5")
        return 0.5
