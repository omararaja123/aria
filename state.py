"""
ARIA State Schema

Complete TypedDict definitions for the LangGraph state machine.
Every node in the graph reads and writes to ARIAState.

Key design: Single consolidated `articles` list flows through the pipeline.
Each node enriches the articles with additional fields (status, scores, summaries, etc).
"""

from typing import TypedDict, Annotated, Optional, Any
from datetime import datetime
from operator import add


class Article(TypedDict, total=False):
    """
    A single article/story in the pipeline.
    Each node adds fields as the article flows through processing.
    """
    # Core metadata (set by subagents)
    id: str  # UUID for this article in this run
    url: str  # Canonical URL of the article
    title: str  # Article headline
    source_domain: str  # Domain extracted from URL (e.g., "anthropic.com")
    published_date: datetime  # When the article was published
    summary: str  # Raw text summary from source (RSS, web scrape, or abstract)
    fetch_source: str  # Which subagent fetched: "rss", "hacker_news", "arxiv"

    # Validation phase (set by validator)
    validation_status: str  # "valid", "removed", or "pending"
    credibility_score: float  # 0–1, how trustworthy the source is
    validation_reason: str  # Why article was kept/removed (e.g., "too_old", "low_credibility", "valid")

    # Deduplication phase (set by deduplicator)
    dedup_removed: bool  # True if article is a duplicate
    dedup_reason: str  # "exact_url", "cross_week", "fuzzy_title", or None

    # Ranking phase (set by ranker)
    relevance_score: float  # 0–1, how relevant to user's interests
    section: str  # Newsletter section: "Trending", "Research", "Tools & Resources", "Industry News", "Analysis & Opinion"
    ranking_rank: int  # Position in ranked list (0 = highest)
    ranking_removed: bool  # True if article didn't make final cut
    ranking_reason: str  # Why included/excluded

    # Summarization phase (set by summarizer)
    summary_text: str  # 3-sentence summary from LLM
    why_matters: str  # Single impactful sentence from LLM
    estimated_cost_usd: float  # Estimated cost of LLM calls for this article

    # Human review phase (set by human or after review)
    human_feedback: Optional[str]  # "approved", "removed", or None
    human_notes: str  # Optional human notes on the article

    # Publishing phase
    archived: bool  # True if this article was included in the sent newsletter


class NewsletterSection(TypedDict):
    """
    A section of the newsletter with related articles.
    """
    name: str  # Section name: "Trending", "Research", etc.
    description: str  # Introductory text for this section
    articles: list[Article]  # Articles in this section (max 4)


class Edit(TypedDict, total=False):
    """
    A single edit made by the human during review.
    Tracks feedback for learning and evals.
    """
    article_id: str  # UUID of the article being edited
    action: str  # "remove", "keep", "reorder"
    new_section: Optional[str]  # For reorder: new section assignment
    new_position: Optional[int]  # For reorder: new position in section
    feedback: Optional[str]  # "approved" or "rejected" (thumbs up/down)
    timestamp: datetime  # When the edit was made
    reviewer_notes: str  # Optional human notes on why


class ARIAState(TypedDict):
    """
    Complete state for the LangGraph agent.
    Grouped by pipeline phase for clarity.

    Field Mutability Notes:
    - "Set once at start": Loaded from config/memory, read-only during run.
    - "Set/written by X": Modified by that node; downstream nodes read the result.
    - Fields marked Optional start as None and are populated during pipeline.
    """

    # ========== RUN METADATA ==========
    # Set once at the start of the run
    run_id: str  # UUID for this entire run
    run_timestamp: datetime  # When this run started
    user_id: str  # For multi-user systems (currently unused but reserved)

    # ========== PLANNING PHASE (Set by Supervisor) ==========
    # Base profile from config; may be overridden by human edits (see interest_profile_edits)
    interest_profile: dict[str, float]  # User's topics and weights (e.g., {"LLMs": 0.95, "Vision": 0.7})
    interest_profile_edits: Optional[dict[str, float]]  # Edited profile from human review (overrides interest_profile if present)
    fetch_plan: str  # Human-readable summary of fetch strategy
    priority_topics: list[str]  # Topics to emphasize, ranked by weight
    subagent_instructions: dict[str, Any]  # Per-subagent config overrides (e.g., {"tavily": {"max_results": 5}})
    estimated_budget_remaining: float  # Estimated budget left for Ranker/Summarizer after supervisor planning

    # ========== FETCH PHASE (Written by subagent_dispatcher in parallel via Annotated + operator.add) ==========
    articles: list[Article]  # Single consolidated list, enriched by each node (replaced by each node, not accumulated)
    fetch_errors: Annotated[list[dict], add]  # Errors from subagent fetches (source, error_msg, timestamp)
    total_fetched: int  # Cumulative count of articles fetched before filtering

    # ========== VALIDATION PHASE (Set by Validator) ==========
    # Articles are updated in-place with validation_status, credibility_score, validation_reason
    filtered_article_ids: list[str]  # IDs of articles removed during validation (for audit)
    validation_stats: dict[str, int]  # Counts: filtered_by_date, filtered_by_credibility, circuit_breaker_fired

    # ========== SYNTHESIS PHASE (Set by Deduplicator, Ranker, Summarizer) ==========
    # Articles continue to be updated in-place
    dedup_stats: dict[str, int]  # Counts: exact_dupes, cross_week_dupes, removed_count
    ranking_stats: dict[str, Any]  # Counts: total_scored, sections breakdown {section: count}

    # ========== DRAFT PHASE (Set by Drafter) ==========
    draft_newsletter: Optional[str]  # Full HTML of the newsletter (Jinja2 rendered); None until Drafter runs
    newsletter_metadata: Optional[dict[str, Any]]  # Title, date, highlight_story_id, section_breakdown, article_count; None until Drafter runs

    # ========== HUMAN REVIEW PHASE (Set by review UI and checkpoint) ==========
    human_review_edits: list[Edit]  # All edits made by human in review UI
    review_approved: bool  # True if human approved this version
    review_rejected: bool  # True if human rejected and requested full re-run
    review_re_rank: bool  # True if human wants to re-rank with adjusted profile
    review_timestamp: Optional[datetime]  # When human submitted their decision; None until review completes
    review_notes: Optional[str]  # Human's notes on the review
    re_run_count: int  # Tracks how many times user clicked "Re-run" (limited to max_re_runs)
    max_re_runs: int  # Config: maximum allowed re-runs (default 2) to prevent infinite loops

    # ========== PUBLISHING PHASE (Set by Publisher) ==========
    published: bool  # True if newsletter was successfully sent
    publish_timestamp: Optional[datetime]  # When it was sent; None until Publisher runs
    publish_status: Optional[str]  # "success" or error message; None until Publisher runs
    message_id: Optional[str]  # Gmail message ID (for tracking/archival); None until Publisher runs

    # ========== RUNAWAY PROTECTION (Tracked throughout) ==========
    llm_call_count: int  # Cumulative LLM calls (Ranker, Summarizer, Drafter)
    estimated_cost_usd: float  # Sum of estimated_cost_usd from articles + infrastructure calls
    elapsed_seconds: float  # Wall time of entire run

    # ========== MEMORY/CONTEXT (Loaded at start, used throughout) ==========
    last_newsletter_date: Optional[datetime]  # When the previous newsletter was sent
    topic_history: dict[str, int]  # Topics covered last week: {topic: article_count}
    recent_story_fingerprints: list[str]  # Hashes from last 4 weeks (for cross-week dedup)
    blacklisted_sources: list[str]  # Domains to exclude
