#!/usr/bin/env python3
"""
Validation script showing article URLs and extracted dates.
"""

import asyncio
from datetime import datetime, timedelta
from agents.subagent_dispatcher import subagent_dispatcher_node
from state import ARIAState

state: ARIAState = {
    "run_id": "validate-dates",
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

print("=" * 120)
print("ARTICLE VALIDATION - URLS & EXTRACTED DATES")
print("=" * 120)
print()

try:
    result_state = subagent_dispatcher_node(state)
    articles = result_state.get("articles", [])

    # Organize by source
    by_source = {}
    for article in articles:
        source = article.get("fetch_source", "unknown")
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(article)

    # Show articles by source
    for source_name in ["rss", "tavily_search", "hacker_news", "arxiv"]:
        source_articles = by_source.get(source_name, [])
        if not source_articles:
            continue

        print(f"\n{'=' * 120}")
        print(f"{source_name.upper()}: {len(source_articles)} articles")
        print(f"{'=' * 120}")

        for i, article in enumerate(sorted(source_articles, key=lambda a: a.get("published_date"), reverse=True), 1):
            pub_date = article.get("published_date")

            # Normalize timezone
            if pub_date and hasattr(pub_date, 'tzinfo') and pub_date.tzinfo is not None:
                pub_date = pub_date.replace(tzinfo=None)

            date_str = pub_date.strftime('%Y-%m-%d') if pub_date else "UNKNOWN"
            age = (datetime.now() - pub_date).days if pub_date else -1
            status = "✓ FRESH" if age <= 7 else "✗ OLD"

            url = article.get("url", "NO URL")
            title = article.get("title", "No title")[:80]

            print(f"\n{i}. {status} | {date_str} | {age:2d}d old")
            print(f"   Title: {title}")
            print(f"   URL:   {url}")

    print(f"\n\n{'=' * 120}")
    print(f"TOTAL: {len(articles)} articles, all dates extracted")
    print(f"{'=' * 120}\n")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
