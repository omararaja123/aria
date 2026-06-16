"""
Drafting Skill

Generates a high-quality intro paragraph for the newsletter using Claude Sonnet 4.6.
Also provides helper for Jinja2 template rendering.

Input: topic_summary (dict), highlight_story (Article), interest_profile (dict)
Output: {intro_text, word_count, estimated_cost_usd}
"""

import logging
from typing import Any, Dict, Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)


def drafting_skill(
    topic_summary: Dict[str, int],
    highlight_story: Optional[Dict[str, Any]],
    interest_profile: Dict[str, float],
) -> Dict[str, Any]:
    """
    Generate a compelling intro paragraph for the newsletter.
    Uses Claude Sonnet 4.6 for high-quality writing.
    
    Returns:
    {
        "success": bool,
        "intro_text": str,
        "word_count": int,
        "estimated_cost_usd": float,
        "error": Optional[str]
    }
    """

    client = Anthropic()

    # Build context for prompt
    topics_str = "\n".join(
        f"  - {topic}: {count} articles" for topic, count in sorted(
            topic_summary.items(), key=lambda x: x[1], reverse=True
        )
    )

    highlight_str = ""
    if highlight_story:
        highlight_str = f"""
Highlight Story:
  Title: {highlight_story.get('title', 'N/A')}
  Source: {highlight_story.get('source_domain', 'N/A')}
"""

    system_prompt = """You are an editor writing a brief, engaging intro paragraph for a weekly AI research newsletter.
Your job is to:
1. Summarize this week's theme and key topics (2-3 sentences)
2. Highlight why readers should care about this edition
3. Maintain a professional but conversational tone

Keep it concise (50-100 words) and compelling."""

    user_prompt = f"""This week's newsletter covers:
{topics_str}
{highlight_str}

Reader's Key Interests: {', '.join(sorted(interest_profile.keys(), key=lambda x: interest_profile[x], reverse=True)[:5])}

Write a compelling intro paragraph (50-100 words) that summarizes this edition and invites readers in."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        intro_text = response.content[0].text.strip()
        word_count = len(intro_text.split())

        # Estimate cost (Sonnet: ~$3 per 1M input tokens, $15 per 1M output tokens)
        # Typical: 200 input tokens + 80 output tokens = $0.0006 + $0.0012 = ~$0.002
        # Approximate as $0.003 per call
        estimated_cost = 0.003

        logger.info(
            f"Drafting skill: generated intro ({word_count} words), "
            f"cost ${estimated_cost:.4f}"
        )

        return {
            "success": True,
            "intro_text": intro_text,
            "word_count": word_count,
            "estimated_cost_usd": estimated_cost,
            "error": None,
        }

    except Exception as e:
        logger.error(f"Drafting skill: LLM call failed: {e}")
        return {
            "success": False,
            "intro_text": "This week's newsletter features the latest breakthroughs in AI research, from foundational models to practical applications. Dive in to stay at the forefront of the field.",
            "word_count": 0,
            "estimated_cost_usd": 0.0,
            "error": f"LLM error: {e}",
        }
