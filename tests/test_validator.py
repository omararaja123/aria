"""Unit tests for validator.py"""

import pytest
from datetime import datetime, timedelta

from state import Article
from tools.validator import validator_node
from config import RUNAWAY_GUARDS


def create_test_article(
    id: str = "test-1",
    published_date: datetime = None,
) -> Article:
    """Helper to create test articles."""
    if published_date is None:
        published_date = datetime.now()

    return {
        "id": id,
        "url": f"https://anthropic.com/{id}",
        "title": f"Test Article {id}",
        "source_domain": "anthropic.com",
        "published_date": published_date,
        "summary": "Test summary",
        "fetch_source": "test",
        "credibility_score": 0.9,  # High credibility to pass validation
    }


def test_date_filtering():
    """Test that articles older than 7 days are removed."""
    now = datetime.now()

    articles = [
        create_test_article("new", published_date=now),
        create_test_article("old", published_date=now - timedelta(days=8)),
    ]

    state = {
        "articles": articles,
        "run_timestamp": now,
        "fetch_errors": [],
    }

    result = validator_node(state)
    old = next((a for a in result["articles"] if a["id"] == "old"), None)
    assert old.get("validation_status") == "removed"


def test_credibility_floor():
    """Test that articles are scored for credibility."""
    articles = [create_test_article("test")]
    state = {
        "articles": articles,
        "run_timestamp": datetime.now(),
        "fetch_errors": [],
    }

    result = validator_node(state)
    for article in result["articles"]:
        assert "credibility_score" in article


def test_circuit_breaker():
    """Test circuit breaker fires when article count exceeds threshold."""
    max_articles = RUNAWAY_GUARDS.get("max_validated_articles", 60)
    articles = [
        create_test_article(f"article-{i}")
        for i in range(max_articles + 10)
    ]

    state = {
        "articles": articles,
        "run_timestamp": datetime.now(),
        "fetch_errors": [],
    }

    result = validator_node(state)
    stats = result.get("validation_stats", {})
    assert stats.get("circuit_breaker_fired") is True


def test_runaway_check():
    """Test that runaway check fails if too many raw articles."""
    max_raw = RUNAWAY_GUARDS.get("max_raw_articles_total", 120)
    articles = [create_test_article(f"article-{i}") for i in range(max_raw + 1)]

    state = {
        "articles": articles,
        "run_timestamp": datetime.now(),
        "fetch_errors": [],
    }

    with pytest.raises(RuntimeError):
        validator_node(state)
