"""
Summarization Skill — Batch Processing

Generates 3-sentence summary + "why it matters" line per article.
Uses Claude Haiku 4.5 with batch processing (3 articles per call).

Input: articles (list of 3)
Output: {summaries: [{article_id, summary_text, why_matters}], estimated_cost_usd}
"""

import json
import logging
from typing import Any, Dict, List

from anthropic import Anthropic

logger = logging.getLogger(__name__)


def summarization_skill_batch(articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarize a batch of articles (up to 3) in a single LLM call.
    
    Returns:
    {
        "success": bool,
        "summaries": [
            {
                "article_id": str,
                "summary_text": str (3 sentences),
                "why_matters": str (1 sentence)
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
            "summaries": [],
            "estimated_cost_usd": 0.0,
            "error": None,
        }

    client = Anthropic()

    # Build articles list for prompt
    articles_str = ""
    for i, article in enumerate(articles, 1):
        articles_str += f"\n{'='*50}\n"
        articles_str += f"Article {i}:\n"
        articles_str += f"Title: {article.get('title', 'No title')}\n"
        articles_str += f"Source: {article.get('source_domain', 'unknown')}\n"
        articles_str += f"Summary: {article.get('summary', 'No summary')[:300]}\n"
        articles_str += f"ID: {article.get('id', 'unknown')}\n"

    system_prompt = """You are an expert at summarizing research articles for busy readers.
Your job is to:
1. Write a concise 3-sentence summary of each article (focus on key insights)
2. Write a single impactful sentence explaining why this matters (relevance to AI/research)

Summary guidelines:
- 3 sentences maximum (tight, focused)
- Lead with the main finding or claim
- Include key context and implications
- Avoid jargon; use clear language

"Why it matters" guidelines:
- 1 sentence only
- Explain significance or impact
- Connect to broader AI/research trends

Return ONLY a JSON object (no markdown, no explanation)."""

    user_prompt = f"""Summarize these articles:
{articles_str}

Respond with ONLY a JSON object in this format:
{{
  "summaries": [
    {{"article_id": "id1", "summary_text": "Sentence 1. Sentence 2. Sentence 3.", "why_matters": "Single sentence."}},
    {{"article_id": "id2", "summary_text": "Sentence 1. Sentence 2. Sentence 3.", "why_matters": "Single sentence."}},
    ...
  ]
}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        if not response.content or not response.content[0].text:
            logger.error(f"Summarization skill: Empty response from API")
            return {
                "success": False,
                "summaries": [],
                "estimated_cost_usd": 0.0,
                "error": "Empty response from API",
            }

        response_text = response.content[0].text.strip()

        if not response_text:
            logger.error(f"Summarization skill: Response text is empty after strip()")
            return {
                "success": False,
                "summaries": [],
                "estimated_cost_usd": 0.0,
                "error": "Empty response text after strip()",
            }

        # Strip markdown code fence if present
        if response_text.startswith("```"):
            # Remove opening fence (```json or ```)
            lines = response_text.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]  # Remove first line
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]  # Remove last line
            response_text = '\n'.join(lines).strip()

        # Parse JSON response
        result = json.loads(response_text)
        summaries = result.get("summaries", [])

        # Validate summaries
        for item in summaries:
            # Ensure fields exist
            if "summary_text" not in item:
                item["summary_text"] = "Unable to summarize."
            if "why_matters" not in item:
                item["why_matters"] = "See full article for details."

            # Trim if too long
            item["summary_text"] = item["summary_text"][:500]
            item["why_matters"] = item["why_matters"][:150]

        # Estimate cost (Haiku: ~$0.80 per 1M input tokens, $4 per 1M output tokens)
        # Typical: 800 input tokens + 300 output tokens = 0.00064 + 0.0012 = ~$0.00184
        # Approximate as $0.04 per batch call (3 articles)
        estimated_cost = 0.04

        logger.info(
            f"Summarization skill batch: summarized {len(summaries)} articles, "
            f"cost ${estimated_cost:.4f}"
        )

        return {
            "success": True,
            "summaries": summaries,
            "estimated_cost_usd": estimated_cost,
            "error": None,
        }

    except json.JSONDecodeError as e:
        logger.error(f"Summarization skill: JSON parsing failed: {e}")
        return {
            "success": False,
            "summaries": [],
            "estimated_cost_usd": 0.0,
            "error": f"JSON parse error: {e}",
        }
    except Exception as e:
        logger.error(f"Summarization skill: LLM call failed: {e}")
        return {
            "success": False,
            "summaries": [],
            "estimated_cost_usd": 0.0,
            "error": f"LLM error: {e}",
        }
