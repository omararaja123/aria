"""
ARIA Supervisor Node

Strategic orchestrator that reads memory (topic history), reads the interest profile,
uses Claude Sonnet 4.6 to reason about fetch priorities and budgets, and dispatches
the four parallel subagents with intelligent overrides.

This is the entry point for each weekly run.
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from anthropic import Anthropic
from state import ARIAState
from config import (
    INTEREST_PROFILE,
    COST_BUDGET_USD,
    RANKER_BUDGET_USD,
    SUMMARIZER_BUDGET_USD,
    DRAFTER_BUDGET_USD,
)
from memory.topic_memory import get_topic_history, get_last_newsletter_date

logger = logging.getLogger(__name__)


def supervisor_node(state: ARIAState) -> ARIAState:
    """
    Supervisor: Intelligent orchestrator for the news fetching pipeline.

    Error handling: Memory lookups failures don't block; LLM call failures use defaults.
    """

    try:
        logger.info(f"Supervisor starting run {state.get('run_id')}")

        # Read memory with error handling
        try:
            topic_history = get_topic_history(weeks_back=4)
            last_newsletter_date = get_last_newsletter_date()
        except Exception as mem_error:
            logger.warning(f"Memory lookup failed: {mem_error}; using empty history")
            topic_history = {}
            last_newsletter_date = None

        logger.info(f"Topic history: {topic_history}")

        # Get interest profile
        interest_profile = state.get("interest_profile") or INTEREST_PROFILE

        # Call Claude Sonnet with error handling
        try:
            fetch_plan, priority_topics, subagent_instructions = _call_supervisor_strategy_llm(
                interest_profile=interest_profile,
                topic_history=topic_history,
                cost_budget=COST_BUDGET_USD,
            )
        except Exception as llm_error:
            logger.warning(f"Supervisor LLM failed: {llm_error}; using defaults")
            # Fallback: use all topics by weight
            fetch_plan = "Default fetch plan (LLM unavailable): fetching from all sources"
            priority_topics = sorted(
                interest_profile.keys(),
                key=lambda t: interest_profile[t],
                reverse=True
            )[:5]
            subagent_instructions = {}

        # Estimate downstream cost
        ranker_cost = RANKER_BUDGET_USD
        summarizer_cost = SUMMARIZER_BUDGET_USD
        drafter_cost = DRAFTER_BUDGET_USD if state.get("ENABLE_LLM_DRAFTING") else 0.0

        estimated_downstream_cost = ranker_cost + summarizer_cost + drafter_cost
        estimated_budget_remaining = COST_BUDGET_USD - estimated_downstream_cost

        logger.info(f"Budget remaining for subagents: ${estimated_budget_remaining:.2f}")

        # Update state
        state["fetch_plan"] = fetch_plan
        state["priority_topics"] = priority_topics
        state["subagent_instructions"] = subagent_instructions
        state["estimated_budget_remaining"] = estimated_budget_remaining
        state["last_newsletter_date"] = last_newsletter_date
        state["topic_history"] = topic_history

        return state

    except Exception as e:
        logger.error(f"Supervisor node failed: {e}")
        # Return state with minimal defaults so pipeline can continue
        state["fetch_plan"] = "Default fetch plan (error)"
        state["priority_topics"] = list(INTEREST_PROFILE.keys())[:5]
        state["subagent_instructions"] = {}
        state["estimated_budget_remaining"] = COST_BUDGET_USD * 0.5
        return state


def _call_supervisor_strategy_llm(
    interest_profile: Dict[str, float],
    topic_history: Dict[str, int],
    cost_budget: float,
) -> Tuple[str, List[str], Dict[str, Any]]:
    """
    Call Claude Sonnet 4.6 to reason about:
    1. Which topics to prioritize this week (based on interest profile and recent coverage)
    2. Which subagents to enable (RSS always, HN/ArXiv conditional)
    3. Dynamic fetch budgets per subagent

    Returns:
    - fetch_plan (string): Human-readable summary of the strategy
    - priority_topics (list): Topics ranked by priority (highest weight first)
    - subagent_instructions (dict): Per-subagent config overrides
    """

    client = Anthropic()

    # Build prompt context
    topics_by_weight = sorted(interest_profile.items(), key=lambda x: x[1], reverse=True)
    topics_str = "\n".join(f"  - {topic}: {weight:.2f}" for topic, weight in topics_by_weight)

    topic_history_str = "\n".join(
        f"  - {topic}: {count} articles" for topic, count in sorted(
            topic_history.items(), key=lambda x: x[1], reverse=True
        )
    ) or "  (No prior coverage)"

    system_prompt = """You are the strategic orchestrator for an AI research newsletter.
Your job is to reason about:
1. Which topics should be emphasized this week based on the user's interests and recent coverage
2. Which sources/subagents to activate (RSS, Hacker News, ArXiv)
3. Dynamic fetch budgets per subagent

Guidelines:
- RSS fetcher: Always enabled (low cost, reliable)
- Hacker News: Enable for developer sentiment and hot takes (if budget permits)
- ArXiv: Enable if the interest profile emphasizes research topics (LLMs, Vision, RL, Safety)
- Vary fetch budgets based on cost constraints:
  - High budget ($2.00+): 15 articles per subagent
  - Medium budget ($1.00–$2.00): 10 articles per subagent
  - Low budget (<$1.00): 5 articles per subagent

Return a JSON object with your decision."""

    user_prompt = f"""Current run details:

Interest Profile (weighted topics):
{topics_str}

Topics Covered in Last 4 Weeks:
{topic_history_str}

Cost Budget Available: ${cost_budget:.2f}

Based on this context, decide:
1. Which topics to prioritize this week (list all topics from interest profile, ranked by priority)
2. Which subagents to enable and why
3. Fetch budget per subagent (articles to request)

Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "fetch_plan": "Human-readable 2-3 sentence summary of strategy",
  "priority_topics": ["Topic 1", "Topic 2", ...],
  "subagents": {{
    "rss": {{"enabled": true, "max_articles": N}},
    "hacker_news": {{"enabled": true/false, "max_articles": N}},
    "arxiv": {{"enabled": true/false, "max_articles": N}}
  }}
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = response.content[0].text.strip()

        # Parse JSON response
        strategy = json.loads(response_text)

        fetch_plan = strategy.get("fetch_plan", "Fetch articles across all sources")
        priority_topics = strategy.get("priority_topics", list(interest_profile.keys()))

        subagent_config = strategy.get("subagents", {})
        subagent_instructions = {
            "rss": {
                "enabled": subagent_config.get("rss", {}).get("enabled", True),
                "max_articles": subagent_config.get("rss", {}).get("max_articles", 15),
            },
            "hacker_news": {
                "enabled": subagent_config.get("hacker_news", {}).get("enabled", True),
                "max_articles": subagent_config.get("hacker_news", {}).get("max_articles", 10),
            },
            "arxiv": {
                "enabled": subagent_config.get("arxiv", {}).get("enabled", True),
                "max_articles": subagent_config.get("arxiv", {}).get("max_articles", 10),
            },
        }

        logger.info(f"Supervisor LLM response parsed successfully")
        return fetch_plan, priority_topics, subagent_instructions

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse supervisor LLM response: {e}")
        return (
            "Fetch articles from all sources (fallback strategy)",
            list(interest_profile.keys()),
            {
                "rss": {"enabled": True, "max_articles": 15},
                "hacker_news": {"enabled": True, "max_articles": 10},
                "arxiv": {"enabled": True, "max_articles": 10},
            },
        )
    except Exception as e:
        logger.error(f"Supervisor LLM call failed: {e}")
        # Fallback: use safe defaults
        return (
            "Fetch articles from all sources (fallback strategy)",
            list(interest_profile.keys()),
            {
                "rss": {"enabled": True, "max_articles": 15},
                "tavily": {"enabled": True, "max_articles": 5},
                "hacker_news": {"enabled": True, "max_articles": 5},
                "arxiv": {"enabled": True, "max_articles": 5},
            },
        )
