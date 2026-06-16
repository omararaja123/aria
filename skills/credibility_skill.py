"""
Credibility Skill — Source Domain Scoring

Scores the credibility (0–1) of a news source domain.
Uses cache-first strategy: check memory before calling LLM.
Called rarely (once per new domain per month), heavily cached.

Input: domain (str), context (optional dict with domain metadata)
Output: {credibility_score, signals, confidence}
"""

import json
import logging
from typing import Any, Dict, Optional

from anthropic import Anthropic
from memory.source_memory import get_source_score, update_source_score
from skills.skill_interface import CredibilitySkillResult

logger = logging.getLogger(__name__)


def credibility_skill(domain: str, context: Optional[Dict[str, Any]] = None) -> CredibilitySkillResult:
    """
    Score the credibility of a source domain (0–1).

    Cache-first strategy:
    1. Check source_memory for cached score (if < 30 days old, use it)
    2. If not cached or stale, call Claude Haiku with credibility rubric
    3. Parse JSON response, validate score in [0.0, 1.0]
    4. Update cache in source_memory
    5. Return CredibilitySkillResult

    Args:
        domain: Source domain (e.g., "anthropic.com", "arxiv.org")
        context: Optional dict with metadata:
            - domain_age_years: int
            - article_count: int
            - topics: list[str]
            - known_authors: list[str]

    Returns:
        CredibilitySkillResult with:
        - success: bool (True if skill executed)
        - data: dict with credibility_score, signals, confidence
        - estimated_cost_usd: float (0.0 if cached, ~0.0004 if fresh call)
        - error: Optional error message
        - tokens_used: Optional token counts
    """

    # ===== STEP 1: Check cache =====
    cached_score = get_source_score(domain)
    if cached_score is not None:
        logger.info(f"Credibility cache hit for {domain}: {cached_score:.2f}")
        return {
            "success": True,
            "data": {
                "credibility_score": cached_score,
                "signals": ["cached_score"],
                "confidence": 0.95,
            },
            "estimated_cost_usd": 0.0,
            "error": None,
            "tokens_used": None,
            "reasoning": f"Score retrieved from cache (30-day TTL)",
        }

    # ===== STEP 2: Prepare LLM call =====
    context = context or {}
    context_str = ""
    if context.get("domain_age_years"):
        context_str += f"\n- Domain age: {context['domain_age_years']} years"
    if context.get("article_count"):
        context_str += f"\n- Article count: {context['article_count']}"
    if context.get("topics"):
        context_str += f"\n- Topics covered: {', '.join(context['topics'])}"
    if context.get("known_authors"):
        context_str += f"\n- Known authors: {', '.join(context['known_authors'][:3])}"  # First 3

    system_prompt = """You are an expert evaluating the credibility of AI news and research sources.

For each domain, assess its credibility based on:
- Authorship: Are articles by named experts with verified credentials?
- Fact-checking: Does the publication correct errors? Do readers trust it?
- Bias: Is coverage balanced or heavily promotional?
- Track record: Does it break important stories or mostly echo others?
- Update frequency: Is it current and actively maintained?

Score 0–1:
- 0.9–1.0: Highly credible (peer-reviewed journals, major publications like Nature, ICML)
- 0.7–0.8: Credible (technical blogs by known researchers, reputable tech news)
- 0.5–0.6: Moderate (most tech blogs, medium-sized publications)
- 0.3–0.4: Low credibility (promotional content, unverified claims, outdated info)
- 0.0–0.2: Very low (spam, misinformation, abandoned projects)

Output ONLY a JSON object (no markdown, no explanation)."""

    user_prompt = f"""Score the credibility of this domain:

Domain: {domain}{context_str}

Respond with ONLY a JSON object in this exact format:
{{
  "domain": "{domain}",
  "credibility_score": 0.0,
  "signals": ["signal1", "signal2", "signal3"],
  "confidence": 0.0
}}"""

    # ===== STEP 3: Call Claude Haiku =====
    client = Anthropic()
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            temperature=0.1,  # Very deterministic
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        if not response.content or not response.content[0].text:
            logger.error(f"Credibility skill: Empty response from API for {domain}")
            return {
                "success": False,
                "data": {"credibility_score": 0.5, "signals": ["api_error"], "confidence": 0.0},
                "estimated_cost_usd": 0.0,
                "error": "Empty response from API",
                "tokens_used": None,
            }

        # ===== STEP 4: Parse JSON response =====
        response_text = response.content[0].text.strip()

        # Try to extract JSON if wrapped in markdown code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        result = json.loads(response_text)

        # ===== STEP 5: Validate and extract score =====
        credibility_score = result.get("credibility_score", 0.5)

        # Validate score is in [0.0, 1.0]
        if not isinstance(credibility_score, (int, float)) or not (0.0 <= credibility_score <= 1.0):
            logger.warning(f"Invalid credibility_score {credibility_score} for {domain}, using 0.5")
            credibility_score = 0.5

        signals = result.get("signals", [])
        confidence = result.get("confidence", 0.8)

        # ===== STEP 6: Update cache =====
        try:
            update_source_score(domain, float(credibility_score))
            logger.info(f"Updated credibility cache for {domain}: {credibility_score:.2f}")
        except Exception as e:
            logger.warning(f"Failed to update cache for {domain}: {e}")

        # ===== STEP 7: Return result =====
        input_tokens = len(system_prompt.split()) + len(user_prompt.split())
        output_tokens = len(response_text.split())

        return {
            "success": True,
            "data": {
                "credibility_score": credibility_score,
                "signals": signals,
                "confidence": confidence,
            },
            "estimated_cost_usd": 0.0004,  # ~$0.0004 per domain (negligible, cached)
            "error": None,
            "tokens_used": {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            "reasoning": f"Scored {domain} as {credibility_score:.2f} based on: {'; '.join(signals[:2])}",
        }

    except json.JSONDecodeError as e:
        logger.error(f"Credibility skill: Failed to parse JSON for {domain}: {e}")
        return {
            "success": False,
            "data": {"credibility_score": 0.5, "signals": ["json_parse_error"], "confidence": 0.0},
            "estimated_cost_usd": 0.0,
            "error": f"Failed to parse JSON response: {e}",
            "tokens_used": None,
        }

    except Exception as e:
        logger.error(f"Credibility skill error for {domain}: {e}")
        return {
            "success": False,
            "data": {"credibility_score": 0.5, "signals": ["skill_error"], "confidence": 0.0},
            "estimated_cost_usd": 0.0,
            "error": str(e),
            "tokens_used": None,
        }
