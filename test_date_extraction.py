#!/usr/bin/env python3
"""
Test script to verify date extraction is working correctly.
Runs just the dispatcher and shows articles with their extracted dates.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from agents.subagent_dispatcher import subagent_dispatcher_node
from state import ARIAState

# Create minimal state
state: ARIAState = {
    "run_id": "test-date-extraction",
    "run_timestamp": datetime.now(),
    "user_id": "test",
    "interest_profile": {
        "Large Language Models": 0.95,
        "Multimodal AI": 0.85,
        "Agents & Autonomous Systems": 0.80,
        "AI Safety & Alignment": 0.75,
        "Computer Vision": 0.70,
        "Reinforcement Learning": 0.60,
        "AI Infrastructure": 0.65,
        "AI Policy & Ethics": 0.50,
        "Robotics": 0.40,
        "Quantum Computing": 0.20,
    },
    "articles": [],
    "fetch_errors": [],
    "total_fetched": 0,
    "llm_call_count": 0,
    "estimated_cost_usd": 0.0,
    "priority_topics": ["Large Language Models", "Multimodal AI", "AI Safety & Alignment"],
}

print("=" * 80)
print("TESTING DATE EXTRACTION FROM TAVILY/RSS/HN/ARXIV")
print("=" * 80)
print()

# Run dispatcher
try:
    result_state = subagent_dispatcher_node(state)
    articles = result_state.get("articles", [])
    errors = result_state.get("fetch_errors", [])

    print(f"✓ Dispatcher completed")
    print(f"  Total articles fetched: {len(articles)}")
    print(f"  Total errors: {len(errors)}")
    print()

    # Organize by source
    by_source = {}
    for article in articles:
        source = article.get("fetch_source", "unknown")
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(article)

    # Show articles by source with dates
    cutoff_date = datetime.now() - timedelta(days=7)
    print("=" * 80)
    print("ARTICLES BY SOURCE (showing title, date, and age)")
    print("=" * 80)
    print()

    for source in ["rss", "tavily_search", "hacker_news", "arxiv"]:
        source_articles = by_source.get(source, [])
        if not source_articles:
            print(f"❌ {source.upper()}: 0 articles")
            continue

        print(f"✓ {source.upper()}: {len(source_articles)} articles")
        print("-" * 80)

        for article in sorted(source_articles, key=lambda a: a.get("published_date"), reverse=True)[:5]:
            title = article.get("title", "No title")[:60]
            pub_date = article.get("published_date")
            if isinstance(pub_date, str):
                pub_date = datetime.fromisoformat(pub_date.replace('Z', '+00:00')) if 'T' in pub_date else datetime.now()

            # Normalize timezone for comparison
            if pub_date and hasattr(pub_date, 'tzinfo') and pub_date.tzinfo is not None:
                pub_date = pub_date.replace(tzinfo=None)

            age_days = (datetime.now() - pub_date).days if pub_date else -1
            status = "✓ FRESH" if age_days <= 7 else "✗ OLD"

            print(f"  {status}  |  {pub_date.strftime('%Y-%m-%d')}  |  {age_days:2d}d old  |  {title}")

        print()

    # Summary
    print("=" * 80)
    print("FRESHNESS SUMMARY")
    print("=" * 80)
    fresh_count = 0
    for a in articles:
        pub_date = a.get("published_date")
        if pub_date and hasattr(pub_date, 'tzinfo') and pub_date.tzinfo is not None:
            pub_date = pub_date.replace(tzinfo=None)
        if pub_date and (datetime.now() - pub_date).days <= 7:
            fresh_count += 1
    old_count = len(articles) - fresh_count
    print(f"Fresh (0-7 days):  {fresh_count} articles ({fresh_count*100//len(articles) if articles else 0}%)")
    print(f"Old (>7 days):     {old_count} articles ({old_count*100//len(articles) if articles else 0}%)")
    print()

    if old_count > 0:
        print("⚠️  WARNING: Old articles detected! Date extraction may need tuning.")
    else:
        print("✓ All articles are fresh! Date extraction is working correctly.")

    print()
    print("=" * 80)

except Exception as e:
    print(f"✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
