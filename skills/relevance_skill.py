"""
Relevance Skill — Batch Processing

Scores articles by relevance to user's interest profile.
Uses Claude Haiku 4.5 with batch processing (5 articles per call).

Input: articles (list), interest_profile (dict)
Output: {results: [{article_id, relevance_score, section, reasoning}], estimated_cost_usd}
"""

import json
import logging
from typing import Any, Dict, List

from anthropic import Anthropic

logger = logging.getLogger(__name__)


def relevance_skill_batch(
    articles: List[Dict[str, Any]],
    interest_profile: Dict[str, float],
) -> Dict[str, Any]:
    """
    Score a batch of articles (up to 5) by relevance to interest profile.
    Uses Claude Haiku 4.5 exclusively.

    Returns:
    {
        "success": bool,
        "results": [
            {
                "article_id": str,
                "relevance_score": float (0–1),
                "section": str,
                "reasoning": str
            },
            ...
        ],
        "estimated_cost_usd": float,
        "error": Optional[str]
    }
    """

    if not articles:
        return {
            "success": True,
            "results": [],
            "estimated_cost_usd": 0.0,
            "error": None,
        }

    # Build interest profile description for prompt
    profile_str = "\n".join(
        f"  - {topic}: {weight:.2f}" for topic, weight in sorted(
            interest_profile.items(), key=lambda x: x[1], reverse=True
        )
    )

    # Build articles list for prompt
    articles_str = ""
    for i, article in enumerate(articles, 1):
        articles_str += f"\nArticle {i}:\n"
        articles_str += f"  ID: {article.get('id', 'unknown')}\n"
        articles_str += f"  Title: {article.get('title', 'No title')}\n"
        articles_str += f"  Source: {article.get('source_domain', 'unknown')}\n"
        articles_str += f"  Summary: {article.get('summary', 'No summary')[:200]}\n"

    system_prompt = """You are an expert at ranking research articles by relevance to a reader's interests.
Your job is to:
1. Score each article 0–1 by relevance to the reader's topics
2. Assign each article to one of 5 newsletter sections
3. Provide a brief reasoning for the score

Newsletter sections:
- "Trending": Breaking news, trending topics, viral discussions
- "Research": Academic papers, new methods, theoretical advances
- "Tools & Resources": Libraries, frameworks, products, services
- "Industry News": Company announcements, funding, policy changes
- "Analysis & Opinion": Long-form essays, retrospectives, commentary

Score rubric:
- 0.9–1.0: Directly addresses top interests, high signal
- 0.7–0.8: Addresses key interests, good signal
- 0.5–0.6: Related to interests, moderate signal
- 0.3–0.4: Peripherally related, low signal
- 0.0–0.2: Not relevant to interests

Return ONLY a JSON object (no markdown, no explanation)."""

    user_prompt = f"""Reader's Interest Profile:
{profile_str}

Articles to Score:
{articles_str}

Respond with ONLY a JSON object in this format (no markdown):
{{
  "results": [
    {{"article_id": "id", "relevance_score": 0.85, "section": "Trending", "reasoning": "Brief reason"}},
    ...
  ]
}}"""

    try:
        logger.info("Ranker using Claude Haiku [claude-haiku-4-5-20251001]")
        client = Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        if not response.content or not response.content[0].text:
            logger.error("Relevance skill: Empty response from API")
            return {
                "success": False,
                "results": [],
                "estimated_cost_usd": 0.0,
                "error": "Empty response from API",
            }

        response_text = response.content[0].text.strip()

        # Strip markdown code fence if present
        if response_text.startswith("```"):
            lines = response_text.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            response_text = '\n'.join(lines).strip()

        # Parse JSON response
        result = json.loads(response_text)
        results = result.get("results", [])

        # Validate results
        for item in results:
            # Clamp relevance score to 0–1
            score = item.get("relevance_score", 0.5)
            item["relevance_score"] = max(0.0, min(1.0, float(score)))

            # Validate section
            valid_sections = [
                "Trending",
                "Research",
                "Tools & Resources",
                "Industry News",
                "Analysis & Opinion",
            ]
            if item.get("section") not in valid_sections:
                item["section"] = "Trending"  # Default

        # Estimate cost (Haiku: ~$0.80 per 1M input tokens, $4 per 1M output tokens)
        # Typical: 500 input tokens + 200 output tokens = 0.0004 + 0.0008 = ~$0.0012
        # Approximate as $0.015 per batch call
        estimated_cost = 0.015

        logger.info(
            f"Relevance skill batch: scored {len(results)} articles, cost ${estimated_cost:.4f}"
        )

        return {
            "success": True,
            "results": results,
            "estimated_cost_usd": estimated_cost,
            "error": None,
        }

    except json.JSONDecodeError as e:
        logger.error(f"Relevance skill: JSON parsing failed: {e}")
        return {
            "success": False,
            "results": [],
            "estimated_cost_usd": 0.0,
            "error": f"JSON parse error: {e}",
        }
    except Exception as e:
        logger.error(f"Relevance skill: LLM call failed: {e}")
        return {
            "success": False,
            "results": [],
            "estimated_cost_usd": 0.0,
            "error": f"LLM error: {e}",
        }
