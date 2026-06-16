"""Unit tests for state.py TypedDicts"""

from datetime import datetime
from state import ARIAState, Article, NewsletterSection, Edit


def test_article_typedict():
    """Test that Article TypedDict has all required fields."""
    article: Article = {
        "id": "test-1",
        "url": "https://example.com/article",
        "title": "Test Article",
        "source_domain": "example.com",
        "published_date": datetime.now(),
        "summary": "Test summary",
        "fetch_source": "rss",
    }

    assert article["id"] == "test-1"
    assert article["url"] == "https://example.com/article"
    assert article["title"] == "Test Article"
    assert article["source_domain"] == "example.com"
    assert article["published_date"] is not None
    assert article["summary"] == "Test summary"
    assert article["fetch_source"] == "rss"


def test_aria_state_instantiation():
    """Test that ARIAState can be instantiated with required fields."""
    state: ARIAState = {
        "run_id": "run-123",
        "run_timestamp": datetime.now(),
        "user_id": "user-1",
        "interest_profile": {"AI": 0.9},
        "interest_profile_edits": None,
        "articles": [],
        "fetch_errors": [],
        "total_fetched": 0,
        "validation_stats": {},
        "dedup_stats": {},
        "ranking_stats": {},
        "human_review_edits": [],
        "review_approved": False,
        "review_rejected": False,
        "review_re_rank": False,
        "re_run_count": 0,
        "llm_call_count": 0,
        "estimated_cost_usd": 0.0,
        "elapsed_seconds": 0.0,
        "published": False,
        "fetch_plan": "",
        "priority_topics": [],
        "subagent_instructions": {},
        "estimated_budget_remaining": 2.0,
        "draft_newsletter": "",
        "newsletter_metadata": {},
        "last_newsletter_date": None,
        "topic_history": {},
        "blacklisted_sources": [],
        "filtered_article_ids": [],
        "message_id": None,
        "publish_timestamp": None,
        "publish_status": None,
        "review_notes": None,
        "review_timestamp": None,
    }

    assert state["run_id"] == "run-123"
    assert state["interest_profile"]["AI"] == 0.9
    assert isinstance(state["articles"], list)


def test_edit_typedict():
    """Test that Edit TypedDict works correctly."""
    edit: Edit = {
        "article_id": "a1",
        "action": "remove",
        "timestamp": datetime.now(),
        "reason": "Not relevant",
    }

    assert edit["article_id"] == "a1"
    assert edit["action"] == "remove"
    assert edit["timestamp"] is not None
    assert edit["reason"] == "Not relevant"
