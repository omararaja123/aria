#!/usr/bin/env python3
"""
Debug Tavily results to see what we're actually getting and why they're being filtered.
"""

import asyncio
from datetime import datetime
from skills.date_extraction_skill import extract_article_date

try:
    from tavily import TavilyClient
    HAS_TAVILY = True
except ImportError:
    HAS_TAVILY = False

async def debug_tavily():
    """Fetch Tavily results and debug date extraction."""

    if not HAS_TAVILY:
        print("❌ Tavily not installed")
        return

    print("=" * 100)
    print("DEBUGGING TAVILY RESULTS")
    print("=" * 100)
    print()

    try:
        tavily = TavilyClient()

        topics = ["Large Language Models", "Multimodal AI", "AI Safety & Alignment"]

        for topic in topics:
            print(f"\n{'=' * 100}")
            print(f"SEARCHING: {topic}")
            print(f"{'=' * 100}\n")

            response = tavily.search(f"{topic} AI research news", max_results=5)

            for i, result in enumerate(response.get("results", []), 1):
                url = result.get("url", "NO URL")
                title = result.get("title", "NO TITLE")[:70]

                print(f"\n{i}. {title}")
                print(f"   URL: {url}")

                # Check if Tavily returns any date info
                if "publish_date" in result:
                    print(f"   Tavily publish_date: {result['publish_date']}")
                if "date" in result:
                    print(f"   Tavily date: {result['date']}")

                # Try to extract date
                print(f"   Attempting date extraction...")
                try:
                    extracted_date = await extract_article_date(url, timeout=3)
                    if extracted_date:
                        age = (datetime.now() - extracted_date).days
                        print(f"   ✓ Extracted: {extracted_date.date()} ({age} days old)")
                    else:
                        print(f"   ✗ Extraction returned None")
                except Exception as e:
                    print(f"   ✗ Extraction failed: {e}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_tavily())
