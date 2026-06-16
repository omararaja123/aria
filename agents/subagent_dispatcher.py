"""
ARIA Subagent Dispatcher

Consolidated node that coordinates 3 parallel data sources:
1. RSS feeds (feedparser) - trusted news sources
2. Hacker News (Firebase API) - community-vetted stories
3. ArXiv research papers - peer-reviewed research

Internal parallelization via asyncio; each fetcher runs concurrently.
Results aggregated via Annotated[list, operator.add] for thread-safe appends.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from state import ARIAState, Article
from config import (
    RSS_FEEDS,
    ARXIV_QUERIES,
    HN_MIN_SCORE,
    HN_AI_KEYWORDS,
    RUNAWAY_GUARDS,
)

logger = logging.getLogger(__name__)

# Optional imports with graceful degradation
try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    logger.warning("feedparser not installed; RSS fetching will be skipped")

try:
    import arxiv
    HAS_ARXIV = True
except ImportError:
    HAS_ARXIV = False
    logger.warning("arxiv not installed; ArXiv fetching will be skipped")


def subagent_dispatcher_node(state: ARIAState) -> ARIAState:
    """
    Coordinator for 3 parallel subagents (RSS, HN, ArXiv).

    Error handling: Each fetcher runs in isolation; failure of one doesn't block others.
    """

    try:
        logger.info("Subagent dispatcher starting")

        subagent_instructions = state.get("subagent_instructions", {})
        priority_topics = state.get("priority_topics", [])

        # Run all 4 fetchers concurrently with error handling
        all_articles = []
        all_errors = []

        try:
            all_articles, all_errors = asyncio.run(
                _run_all_fetchers(subagent_instructions, priority_topics)
            )
        except Exception as fetch_error:
            logger.error(f"Fetcher coordinator error: {fetch_error}")
            all_errors.append({
                "source": "dispatcher",
                "error_msg": str(fetch_error),
                "timestamp": datetime.now().isoformat(),
            })

        # Enforce max total articles
        max_raw = RUNAWAY_GUARDS.get("max_raw_articles_total", 120)
        if len(all_articles) > max_raw:
            logger.warning(f"Fetched {len(all_articles)} > max {max_raw}; trimming")
            all_articles = all_articles[:max_raw]

        logger.info(
            f"Dispatcher: {len(all_articles)} articles, {len(all_errors)} errors"
        )

        # Update state
        if "articles" not in state:
            state["articles"] = []
        if "fetch_errors" not in state:
            state["fetch_errors"] = []

        state["articles"].extend(all_articles)
        state["fetch_errors"].extend(all_errors)
        state["total_fetched"] = len(all_articles)

        return state

    except Exception as e:
        logger.error(f"Dispatcher node failed: {e}")
        state.setdefault("fetch_errors", []).append({
            "source": "dispatcher",
            "error_msg": str(e),
        })
        state["total_fetched"] = 0
        return state


async def _run_all_fetchers(
    subagent_instructions: Dict[str, Any],
    priority_topics: List[str],
) -> tuple[List[Article], List[Dict]]:
    """
    Run all 4 fetchers concurrently, aggregate results.
    Returns (articles_list, errors_list)
    """

    # Create tasks for all 4 fetchers
    tasks = []

    # RSS fetcher
    if HAS_FEEDPARSER and subagent_instructions.get("rss", {}).get("enabled", True):
        max_articles = subagent_instructions.get("rss", {}).get("max_articles", 15)
        tasks.append(("rss", _fetch_rss(max_articles)))

    # Hacker News fetcher
    if subagent_instructions.get("hacker_news", {}).get("enabled", True):
        max_articles = subagent_instructions.get("hacker_news", {}).get("max_articles", 10)
        tasks.append(("hacker_news", _fetch_hacker_news(max_articles)))

    # ArXiv fetcher
    if HAS_ARXIV and subagent_instructions.get("arxiv", {}).get("enabled", True):
        max_articles = subagent_instructions.get("arxiv", {}).get("max_articles", 10)
        tasks.append(("arxiv", _fetch_arxiv(max_articles)))

    # Run all fetchers in parallel
    all_articles = []
    all_errors = []

    if tasks:
        results = await asyncio.gather(
            *[task[1] for task in tasks],
            return_exceptions=True
        )

        for (source_name, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.error(f"{source_name} fetcher failed: {result}")
                all_errors.append({
                    "source": source_name,
                    "error_msg": str(result),
                    "timestamp": datetime.now().isoformat(),
                })
            elif isinstance(result, tuple):
                articles, errors = result
                all_articles.extend(articles)
                all_errors.extend(errors)
                logger.info(f"{source_name}: fetched {len(articles)} articles, {len(errors)} errors")

    return all_articles, all_errors


async def _fetch_rss(max_articles: int = 15) -> tuple[List[Article], List[Dict]]:
    """Fetch from configured RSS feeds. Skip articles older than 7 days."""
    articles = []
    errors = []

    if not HAS_FEEDPARSER:
        logger.warning("feedparser not available; skipping RSS")
        return articles, errors

    max_age_days = RUNAWAY_GUARDS.get("max_article_age_days", 7)

    for feed_url in RSS_FEEDS:
        try:
            logger.info(f"Fetching RSS: {feed_url}")
            feed = await asyncio.to_thread(feedparser.parse, feed_url)

            if feed.bozo:
                logger.warning(f"RSS feed {feed_url} has parsing issues: {feed.bozo_exception}")

            feed_articles = []
            for entry in feed.entries[:max_articles * 2]:  # Fetch more to account for filtering
                published_date = _parse_rss_date(entry.get("published", ""))

                # Skip articles older than max_age_days (early filtering)
                if _is_article_too_old(published_date, max_age_days):
                    continue

                article = {
                    "id": str(uuid.uuid4()),
                    "url": entry.get("link", ""),
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "published_date": published_date,
                    "source_domain": _extract_domain(entry.get("link", "")),
                    "fetch_source": "rss",
                }
                if article["url"]:  # Only include if URL exists
                    feed_articles.append(article)
                    if len(feed_articles) >= max_articles:
                        break

            articles.extend(feed_articles)
            logger.info(f"RSS {feed_url}: fetched {len(feed_articles)} articles (< {max_age_days} days old)")

        except Exception as e:
            logger.error(f"RSS feed {feed_url} failed: {e}")
            errors.append({
                "source": f"rss:{feed_url}",
                "error_msg": str(e),
                "timestamp": datetime.now().isoformat(),
            })

    return articles[:max_articles], errors


async def _fetch_hacker_news(max_articles: int = 10) -> tuple[List[Article], List[Dict]]:
    """Fetch from Hacker News Firebase API. Skip articles older than 7 days."""
    articles = []
    errors = []

    max_age_days = RUNAWAY_GUARDS.get("max_article_age_days", 7)

    try:
        logger.info("Fetching Hacker News top stories")

        # Get top story IDs
        response = await asyncio.to_thread(
            requests.get,
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10,
        )
        response.raise_for_status()
        story_ids = response.json()[:30]  # Get top 30, filter to max_articles

        ai_keywords_lower = [kw.lower() for kw in HN_AI_KEYWORDS]
        count = 0

        for story_id in story_ids:
            if count >= max_articles:
                break

            try:
                # Fetch story details
                story_response = await asyncio.to_thread(
                    requests.get,
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                    timeout=5,
                )
                story_response.raise_for_status()
                story = story_response.json()

                if not story:
                    continue

                # Filter by score and AI relevance
                score = story.get("score", 0)
                title = story.get("title", "").lower()
                published_date = datetime.fromtimestamp(story.get("time", 0))

                if score < HN_MIN_SCORE:
                    continue

                # Check if title contains AI keywords
                if not any(kw in title for kw in ai_keywords_lower):
                    continue

                # Skip articles older than max_age_days (early filtering)
                if _is_article_too_old(published_date, max_age_days):
                    continue

                article = {
                    "id": str(uuid.uuid4()),
                    "url": story.get("url", ""),
                    "title": story.get("title", ""),
                    "summary": "",  # HN doesn't provide summaries
                    "published_date": published_date,
                    "source_domain": "news.ycombinator.com",
                    "fetch_source": "hacker_news",
                    "hn_score": score,
                }

                if article["url"]:
                    articles.append(article)
                    count += 1

            except Exception as e:
                logger.warning(f"HN story {story_id} failed: {e}")
                continue

        logger.info(f"Hacker News: fetched {len(articles)} articles (< {max_age_days} days old)")

    except Exception as e:
        logger.error(f"Hacker News fetch failed: {e}")
        errors.append({
            "source": "hacker_news",
            "error_msg": str(e),
            "timestamp": datetime.now().isoformat(),
        })

    return articles, errors


async def _fetch_arxiv(max_articles: int = 10) -> tuple[List[Article], List[Dict]]:
    """Fetch from ArXiv API. Skip papers older than 7 days."""
    articles = []
    errors = []

    if not HAS_ARXIV:
        logger.warning("arxiv not installed; skipping ArXiv search")
        return articles, errors

    max_age_days = RUNAWAY_GUARDS.get("max_article_age_days", 7)

    try:
        logger.info("Fetching ArXiv papers")

        client = arxiv.Client()
        count = 0

        # Search for each query
        for query_str in ARXIV_QUERIES:
            if count >= max_articles:
                break

            try:
                logger.info(f"Searching ArXiv for: {query_str}")
                search = arxiv.Search(
                    query=query_str,
                    max_results=max_articles // len(ARXIV_QUERIES),
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                    sort_order=arxiv.SortOrder.Descending,
                )

                for paper in client.results(search):
                    if count >= max_articles:
                        break

                    # Skip papers older than max_age_days (early filtering)
                    if _is_article_too_old(paper.published, max_age_days):
                        continue

                    article = {
                        "id": str(uuid.uuid4()),
                        "url": paper.entry_id,
                        "title": paper.title,
                        "summary": paper.summary,
                        "published_date": paper.published,
                        "source_domain": "arxiv.org",
                        "fetch_source": "arxiv",
                        "arxiv_category": paper.primary_category,
                    }

                    articles.append(article)
                    count += 1

                logger.info(f"ArXiv {query_str}: fetched {count} articles (< {max_age_days} days old)")

            except Exception as e:
                logger.error(f"ArXiv search for '{query_str}' failed: {e}")
                errors.append({
                    "source": f"arxiv:{query_str}",
                    "error_msg": str(e),
                    "timestamp": datetime.now().isoformat(),
                })

    except Exception as e:
        logger.error(f"ArXiv initialization failed: {e}")
        errors.append({
            "source": "arxiv",
            "error_msg": str(e),
            "timestamp": datetime.now().isoformat(),
        })

    return articles[:max_articles], errors


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    if not url:
        return ""
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path.split("/")[0]
    return domain.replace("www.", "")


def _parse_rss_date(date_str: str) -> datetime:
    """Parse RSS date string to datetime."""
    if not date_str:
        return datetime.now()

    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now()


def _is_article_too_old(published_date: datetime, max_age_days: int = 7) -> bool:
    """
    Check if an article is older than the max age threshold.
    Early filtering prevents old articles from clogging the pipeline.
    Handles both timezone-aware and timezone-naive datetimes.
    """
    if not published_date:
        return False

    # Make both datetimes timezone-naive for comparison
    cutoff = datetime.now() - timedelta(days=max_age_days)

    # Strip timezone info if present
    if published_date.tzinfo is not None:
        published_date = published_date.replace(tzinfo=None)

    return published_date < cutoff
