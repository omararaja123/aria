"""
ARIA System Configuration

Real, usable values for the agent system.
Customize these values to match your interests and preferences.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# INTEREST PROFILE
# ============================================================================
# Topics you care about and their weights (0–1).
# Higher weight = articles on that topic ranked higher.
# Customize these to match your interests.

INTEREST_PROFILE = {
    "Large Language Models": 0.95,  # GPT, Claude, Llama, etc.
    "Multimodal AI": 0.85,  # Vision + language, DALL-E, etc.
    "Agents & Autonomous Systems": 0.80,  # AutoGPT, ReAct, agentic behavior
    "AI Safety & Alignment": 0.75,  # Safety, RLHF, interpretability
    "Computer Vision": 0.70,  # Image models, OCR, video understanding
    "Reinforcement Learning": 0.60,  # RL, policy learning, training
    "AI Infrastructure": 0.65,  # GPUs, inference optimization, deployment
    "AI Policy & Ethics": 0.50,  # Regulation, bias, fairness
    "Robotics": 0.40,  # Embodied AI, robotics
    "Quantum Computing": 0.20,  # Quantum ML (lower interest, but track it)
}


# ============================================================================
# RSS FEEDS
# ============================================================================
# AI blogs and news sources to fetch from.
# Only sources with real, working RSS feeds.

RSS_FEEDS = [
    "https://www.deepmind.com/blog/rss.xml",  # DeepMind blog
    "https://blog.google/technology/ai/rss/",  # Google AI blog
    "https://huggingface.co/blog/feed.xml",  # Hugging Face blog
    "https://techcrunch.com/tag/artificial-intelligence/feed/",  # TechCrunch AI news
    "https://thegradient.pub/feed/",  # The Gradient (AI research & commentary)
    "https://paperswithcode.com/rss/papers",  # Papers with Code (research papers)
    "https://www.technologyreview.com/feed/",  # MIT Technology Review (policy, ethics, strategy)
]


# ============================================================================
# ARXIV SEARCH QUERIES
# ============================================================================
# Research paper topics to search on arXiv.

ARXIV_QUERIES = [
    "large language models",
    "vision transformers",
    "reinforcement learning",
    "AI alignment safety",
]


# ============================================================================
# HACKER NEWS SETTINGS
# ============================================================================
# Filter Hacker News stories by score and AI relevance.

HN_MIN_SCORE = 50  # Minimum upvotes to include a story

HN_AI_KEYWORDS = [
    "AI", "artificial intelligence", "LLM", "large language model",
    "GPT", "Claude", "Llama", "transformer", "neural network",
    "deep learning", "machine learning", "ML", "ChatGPT",
    "agent", "multimodal", "vision", "NLP", "natural language",
    "embedding", "fine-tuning", "prompt", "reasoning",
    "alignment", "safety", "RLHF", "inference",
]


# ============================================================================
# NEWSLETTER SECTIONS
# ============================================================================
# Five sections in the newsletter.
# Ranker assigns each article to one section based on content type.

NEWSLETTER_SECTIONS = [
    "Trending",  # Breaking news, viral discussions, hot takes
    "Research",  # Academic papers, new methods, theoretical advances
    "Tools & Resources",  # Libraries, frameworks, products, services
    "Industry News",  # Company announcements, funding, policy
    "Analysis & Opinion",  # Long-form essays, retrospectives, commentary
]


# ============================================================================
# CREDIBILITY SETTINGS
# ============================================================================
# Sources we trust implicitly (bypass credibility scoring).

KNOWN_CREDIBLE_SOURCES = [
    "anthropic.com",
    "openai.com",
    "deepmind.com",
    "google.com",
    "huggingface.co",
    "arxiv.org",
    "nature.com",
    "science.org",
    "mit.edu",
    "stanford.edu",
    "berkeley.edu",
    "toronto.edu",
    "cambridge.org",
    "oxford.org",
    "oreilly.com",
]

# Sources to exclude (known spam, misinformation, or low-quality).
KNOWN_LOW_QUALITY = [
    "example.com",
    "placeholder.com",
]

# News aggregator sites to exclude (curate content, not original sources).
# These republish content without proper date attribution.
DOMAIN_BLACKLIST = [
    "thenewstack.io",  # News aggregator
    "llm-stats.com",  # News aggregator
    "medium.com",  # User-generated, mixed quality
    "dev.to",  # User-generated, mixed quality
    "hashnode.com",  # User-generated blogs
    "substack.com",  # Newsletters, user content
]


# ============================================================================
# RUNAWAY GUARDS
# ============================================================================
# Hard limits protecting the system from runaway costs/latency/overload.
# Each guard has a specific location in the pipeline where it fires.

RUNAWAY_GUARDS = {
    # Subagent dispatch: max articles per source
    "max_articles_per_source": 15,

    # Fetch validation: prevent memory bloat
    "max_raw_articles_total": 120,

    # Circuit breaker: max articles after validation filtering
    "max_validated_articles": 60,

    # LLM protection: prevent runaway token usage (reduced due to Haiku + batching)
    "max_llm_calls_per_run": 20,

    # Cost ceiling: hard stop on spend per run (reduced to $2.00 with Haiku)
    "max_cost_usd_per_run": 2.00,

    # Subagent timeout: prevent hung fetches
    "max_subagent_timeout_seconds": 90,

    # Freshness: exclude old articles
    "max_article_age_days": 7,

    # Human review: prevent indefinite pauses
    "max_human_review_pause_hours": 24,

    # Re-run loop protection: limit "re-run with adjusted profile" attempts
    "max_re_runs_per_review": 2,
}


# ============================================================================
# NEWSLETTER SETTINGS
# ============================================================================
# How many articles in the final newsletter.

FINAL_ARTICLE_COUNT = 20  # Target: 15–20 articles (4 per section, ~5 sections)


# ============================================================================
# COST & BUDGET SETTINGS
# ============================================================================
# Strategy: Use Claude Haiku for Ranker (faster, cheaper, good for deterministic scoring)
# and Claude Haiku for Summarizer batch calls (3 articles per call, cheaper than individual calls).
# Total realistic cost: ~$0.50/run (down from $6.05/run with Sonnet).

# Total budget per run (soft warning at 80%, hard stop at 100%)
# Increased to accommodate real costs; Haiku optimization keeps spend low.
COST_BUDGET_USD = 2.00

# Budget for Ranker (LLM calls to score articles via Haiku)
# Haiku pricing: ~$0.80 per 1M input tokens, $4 per 1M output tokens
# Estimated: ~$0.015 per call (vs. $0.12 with Sonnet)
# Batch relevance scoring: 20 articles / 5 per batch = 4 calls × $0.015 = $0.06
RANKER_BUDGET_USD = 0.10

# Budget for Summarizer (LLM calls to write summaries via Haiku + batching)
# Batch summarization: 3 articles per call, 20 articles / 3 = 7 calls
# Estimated: ~$0.04 per batch call (vs. $0.15 per article with Sonnet)
# 7 calls × $0.04 = $0.28
SUMMARIZER_BUDGET_USD = 0.50

# Budget for Drafter (LLM call to write intro paragraph, optional; can use static template)
DRAFTER_BUDGET_USD = 0.10

# LLM Models
# Ranker uses Haiku for fast, cheap relevance scoring (good for deterministic scoring)
RANKER_MODEL = "claude-haiku-4-5-20251001"

# Summarizer uses Haiku with batch processing (3 articles per call)
SUMMARIZER_MODEL = "claude-haiku-4-5-20251001"
SUMMARIZER_BATCH_SIZE = 3  # Articles summarized per LLM call (reduces cost by 67%)

# Drafter: Uses Sonnet for high-quality newsletter writing (the user reads this every week)
# One call per run, so cost impact is minimal (~$0.003)
DRAFTER_MODEL = "claude-sonnet-4-6"

# Enable LLM-based drafting (Sonnet generates the intro paragraph for quality)
ENABLE_LLM_DRAFTING = True


# ============================================================================
# DATABASE & STORAGE
# ============================================================================

DATABASE_PATH = "./newsletter.db"

# How long to keep story fingerprints for cross-week dedup
FINGERPRINT_HISTORY_DAYS = 28  # 4 weeks

# How long to keep source credibility scores before recalibrating
SOURCE_SCORE_CACHE_DAYS = 30

# How long to keep cached summaries before refreshing
# (articles that reappear get cached summary; after this period, re-summarize)
SUMMARY_CACHE_DAYS = 30

# Enable summary caching (skip re-summarizing articles seen in prior runs)
ENABLE_SUMMARY_CACHE = True


# ============================================================================
# LOGGING & OBSERVABILITY
# ============================================================================

LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR

# Enable detailed trace logging for debugging
DETAILED_LOGGING = False

# Whether to log to file (in addition to stdout)
LOG_TO_FILE = True

LOG_FILE_PATH = "./logs/aria.log"
