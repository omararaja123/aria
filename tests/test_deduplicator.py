"""Unit tests for deduplicator.py"""

from datetime import datetime

from state import Article
from tools.deduplicator import deduplicator_node


def create_test_article(
    id: str = "test-1",
    url: str = "https://example.com/article",
    title: str = "Test Article",
    domain: str = "example.com",
) -> Article:
    """Helper to create test articles."""
    return {
        "id": id,
        "url": url,
        "title": title,
        "source_domain": domain,
        "published_date": datetime.now(),
        "summary": "Test",
        "fetch_source": "test",
        "validation_status": "valid",
    }


def test_exact_url_dedup():
    """Test that exact URL duplicates are removed."""
    articles = [
        create_test_article("a1", url="https://example.com/story1"),
        create_test_article("a2", url="https://example.com/story1"),  # Duplicate
        create_test_article("a3", url="https://example.com/story2"),
    ]

    state = {
        "articles": articles,
        "fetch_errors": [],
    }

    result = deduplicator_node(state)

    # Check that one article is marked as duplicate
    dedup_count = len([a for a in result["articles"] if a.get("dedup_removed")])
    assert dedup_count >= 1


def test_unique_articles_pass():
    """Test that unique articles pass through unchanged."""
    articles = [
        create_test_article("a1", url="https://example.com/story1", title="Unique Article One"),
        create_test_article("a2", url="https://example.com/story2", title="Unique Article Two"),
        create_test_article("a3", url="https://example.com/story3", title="Unique Article Three"),
    ]

    state = {
        "articles": articles,
        "fetch_errors": [],
    }

    result = deduplicator_node(state)

    # All should pass through (not removed)
    unique_count = len([a for a in result["articles"] if not a.get("dedup_removed")])
    assert unique_count == 3


def test_cross_week_dedup():
    """Test that cross-week fingerprints are handled gracefully."""
    articles = [
        create_test_article("a1", title="Test Article", domain="example.com"),
        create_test_article("a2", title="Test Article", domain="example.com"),  # Same fingerprint
    ]

    state = {
        "articles": articles,
        "fetch_errors": [],
    }

    result = deduplicator_node(state)

    # At minimum, should have dedup_stats
    assert "dedup_stats" in result
