"""
Standard interface for all LLM-based skills.

Every skill function must return a SkillResult TypedDict to ensure consistent
error handling, cost tracking, and debugging across the pipeline.
"""

from typing import TypedDict, Any, Optional


class SkillResult(TypedDict, total=False):
    """
    Standard return type for all skills (relevance, summarization, credibility, drafting).

    Fields:
    - success: True if the skill executed successfully
    - data: dict containing the skill's output (shape depends on skill type)
    - estimated_cost_usd: Estimated cost of the LLM call (for budget tracking)
    - error: Error message if success=False; None otherwise
    - tokens_used: Optional metadata on token usage {input, output, total}
    - reasoning: Optional field for skills to explain their decision
    """
    success: bool
    data: dict[str, Any]
    estimated_cost_usd: float
    error: Optional[str]
    tokens_used: Optional[dict[str, int]]
    reasoning: Optional[str]


# ===== SKILL-SPECIFIC RESULT SHAPES =====

class RelevanceSkillResult(SkillResult):
    """Result from relevance_skill(article, interest_profile)."""
    # data will contain:
    # - relevance_score: float (0-1)
    # - section: str (one of NEWSLETTER_SECTIONS)
    # - reasoning: Optional[str] (why this score/section)


class SummarizationSkillResult(SkillResult):
    """Result from summarization_skill(articles) where articles is a batch."""
    # data will contain:
    # - summaries: list[dict] where each dict has {article_id, summary_text, why_matters}
    # - batch_size: int (how many articles were summarized in this call)


class CredibilitySkillResult(SkillResult):
    """Result from credibility_skill(domain, hints)."""
    # data will contain:
    # - credibility_score: float (0-1)
    # - signals: list[str] (e.g., ["established_domain", "peer_reviewed", "institutional"])
    # - reasoning: Optional[str]


class DraftingSkillResult(SkillResult):
    """Result from drafting_skill(articles_summary, highlight_article, profile)."""
    # data will contain:
    # - intro_text: str (newsletter intro paragraph)
    # - word_count: int
