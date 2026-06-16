# ARIA 14-Step Build Plan

This document details every build step in order. For each step:
- **What gets built**: Features and components.
- **Files touched**: Which files are created or modified.
- **What "done" looks like**: Acceptance criteria.
- **Verification**: Exact command or check to confirm it works.

---

## Step 1: Foundation — State, Config, and Memory Schema

### What Gets Built
- Complete ARIAState TypedDict with all fields and docstrings (including new interest_profile_edits, re_run_count, and Optional type fixes).
- config.py with interest profiles, RSS feeds, runaway guards, credible sources, sections, ArXiv queries, HN settings, Haiku model options, and summary cache settings.
- memory/db.py with SQLite schema initialization and connection pooling for all 8 tables (including new summary_cache table).

### Files Touched
- **state.py** — Updated with Article, NewsletterSection, Edit, and ARIAState TypedDicts; added Optional type hints, interest_profile_edits field, re_run_count field, and mutability docstrings.
- **config.py** — Updated with INTEREST_PROFILE, RSS_FEEDS, RUNAWAY_GUARDS, cost & budget settings with Haiku models, summary cache settings (ENABLE_SUMMARY_CACHE, SUMMARY_CACHE_DAYS).
- **memory/db.py** — Create with init_db(), get_connection(), and schema definitions for all 8 tables including summary_cache.
- **skills/skill_interface.py** — New file with SkillResult TypedDict and skill-specific return types.

### What "Done" Looks Like
- state.py imports without errors; all TypedDicts are valid; Optional types properly specified.
- config.py imports without errors; all config dicts populated with real values; Haiku models configured.
- memory/db.py initializes a SQLite database with all 8 tables (newsletters, source_scores, story_fingerprints, user_feedback, topic_history, preference_history, eval_results, summary_cache).
- skills/skill_interface.py defines standard SkillResult contract for all skills.
- No syntax errors in any file.

### Verification
```bash
python -c "from state import ARIAState; print('state.py valid')"
python -c "from config import INTEREST_PROFILE, RSS_FEEDS; print(f'{len(RSS_FEEDS)} feeds loaded')"
python -c "from memory.db import init_db, get_connection; init_db(); conn = get_connection(); print('DB initialized')"
```

---

## Step 2: Subagent Dispatcher (Consolidated)

### What Gets Built
- agents/subagent_dispatcher.py: Consolidated node that coordinates RSS, HN, and ArXiv fetches in parallel.
- Internal parallelization via asyncio or concurrent.futures (not LangGraph edges).
- Eliminates code duplication from 3 separate agent nodes.
- Error handling and 90-second timeout wrapper.
- Parallel-safe appends to articles via Annotated + operator.add.
- **Tavily disabled**: Free-tier web search lacked reliable date extraction; 3 trusted sources (RSS, HN, ArXiv) with verified dates sufficient for weekly curation.

### Files Touched
- **agents/subagent_dispatcher.py** — Implement subagent_dispatcher_node(state) that:
  1. Spawns 3 fetchers in parallel (RSS, HN, ArXiv)
  2. Each fetcher uses the same approach as the prior individual agents
  3. Collects results and appends to articles list
  4. Logs errors without crashing individual fetchers
  5. Returns updated state with articles and fetch_errors

### What "Done" Looks Like
- RSS feeds are successfully parsed.
- Articles include: url, title, summary, published_date, source_domain, fetch_source="rss".
- Max 15 articles per feed enforced.
- Errors are logged without crashing.
- No articles older than 7 days are included (optional, date filter in validator).

### Verification
```bash
python -c "
from agents.rss_agent import rss_agent_node
from state import ARIAState
from config import RSS_FEEDS
import datetime

state = {
    'run_id': 'test-1',
    'run_timestamp': datetime.datetime.now(),
    'raw_articles': [],
    'fetch_errors': [],
    'priority_topics': ['AI'],
    'subagent_instructions': {}
}
result = rss_agent_node(state)
print(f'Fetched {len(result[\"raw_articles\"])} articles from RSS')
print(f'Errors: {len(result[\"fetch_errors\"])}')
"
```

### What "Done" Looks Like
- subagent_dispatcher runs without errors.
- articles list contains articles from all 3 sources (RSS, HN, ArXiv).
- fetch_errors list correctly accumulates errors from all sources.
- No timeout exceeds 90 seconds.
- Max 15 articles per individual source enforced; total capped at 120.
- Each article has fetch_source set correctly ("rss", "hacker_news", "arxiv").
- Internal parallelization is transparent to LangGraph (handled by asyncio within the node).

### Verification
```bash
python -c "
from agents.subagent_dispatcher import subagent_dispatcher_node
from state import ARIAState
import datetime

state = {
    'run_id': 'test-dispatcher',
    'run_timestamp': datetime.datetime.now(),
    'articles': [],
    'fetch_errors': [],
    'priority_topics': ['AI', 'LLM'],
    'subagent_instructions': {}
}

result = subagent_dispatcher_node(state)
print(f'Total articles: {len(result[\"articles\"])}')
sources = set(a.get('fetch_source') for a in result['articles'])
print(f'Sources: {sources}')  # Should show: {\"rss\", \"hacker_news\", \"arxiv\"}
print(f'Errors: {len(result[\"fetch_errors\"])}')
"
```

---

## Step 3: Supervisor Node

### What Gets Built
- agents/supervisor.py: Read memory (topic_history), read config (interest_profile), decide fetch priorities, dispatch subagents.
- Returns fetch_plan (string), priority_topics (list), subagent_instructions (dict).

### Files Touched
- **agents/supervisor.py** — Implement supervisor_node(state) with logic to avoid topic repetition.
- **memory/preference_memory.py** — Stub with get_preference_history() signature.
- **memory/preference_memory.py** — Stub with get_interest_profile() signature.

### What "Done" Looks Like
- Supervisor reads interest_profile from config.
- Supervisor reads topic_history from memory (last 4 weeks).
- Supervisor deprioritizes topics with > 3 articles in prior weeks.
- fetch_plan string is human-readable and explains the strategy.
- priority_topics list is sorted by weight (highest first).
- subagent_instructions may contain overrides (e.g., {"tavily": {"max_results": 3}}).

### Verification
```bash
python -c "
from agents.supervisor import supervisor_node
from config import INTEREST_PROFILE
from state import ARIAState
import datetime

state = {
    'run_id': 'test-supervisor',
    'run_timestamp': datetime.datetime.now(),
    'interest_profile': INTEREST_PROFILE,
    'last_newsletter_date': None,  # First run
}

result = supervisor_node(state)
print(f'Fetch plan: {result[\"fetch_plan\"]}')
print(f'Priority topics: {result[\"priority_topics\"]}')
print('Supervisor works!')
"
```

---

## Step 4: Validator and Circuit Breaker

### What Gets Built
- tools/validator.py: Score articles by credibility (using cached domain scores + signals), filter by date, apply credibility floor, check blacklist, fire circuit breaker.
- Memory lookups: source_scores from memory/source_memory (cached scores for previously-seen domains).
- Updates articles list in-place: mark each article with validation_status, credibility_score, validation_reason.

### Files Touched
- **tools/validator.py** — Implement validator_node(state) with all filter logic.
- **memory/source_memory.py** — Stub with get_source_score(), get_blacklisted_sources() signatures.

### What "Done" Looks Like
- Articles older than 7 days are marked validation_status=removed, validation_reason="too_old".
- Articles from blacklisted domains are marked removed, reason="blacklisted".
- Credibility scores assigned from memory (cache hit) OR set to fallback 0.5 for new domains (credibility_skill call deferred to Phase 14).
- Articles with credibility < 0.3 are marked removed (unless domain in KNOWN_CREDIBLE_SOURCES).
- If removal count < target (60 articles), all pass through.
- If removal count would exceed 60, circuit breaker fires: sort by credibility descending, keep top 60, mark rest removed.
- validation_stats dict includes: {filtered_by_date: N, filtered_by_credibility: M, circuit_breaker_fired: bool, removed_total: K}.
- articles list reflects all status updates; downstream steps filter by validation_status="valid".

### Verification
```bash
python -c "
from tools.validator import validator_node
from state import Article
import datetime

# Create test articles
now = datetime.datetime.now()
articles = [
    {
        'id': f'test-{i}',
        'url': f'https://example{i}.com/article',
        'title': f'Article {i}',
        'source_domain': f'example{i}.com',
        'published_date': now - datetime.timedelta(days=i),
        'summary': 'Test summary',
        'fetch_source': 'test',
    }
    for i in range(5)
]

state = {
    'raw_articles': articles,
    'run_timestamp': now,
    'fetch_errors': [],
}

result = validator_node(state)
print(f'Raw articles: {len(state[\"raw_articles\"])}')
print(f'Validated: {len(result[\"validated_articles\"])}')
print(f'Validation stats: {result[\"validation_stats\"]}')
"
```

---

## Step 5: Deduplicator

### What Gets Built
- tools/deduplicator.py: Exact URL dedup and cross-week fingerprint checking.
- Memory lookups: story_fingerprints from memory/story_memory.
- Updates articles list in-place, marking duplicates as dedup_removed=True.
- **Fuzzy title dedup (sentence-transformers) moves to Step 14 (polish).**

### Files Touched
- **tools/deduplicator.py** — Implement deduplicator_node(state) with exact and cross-week fingerprint logic (no fuzzy for Phase 1).
- **memory/story_memory.py** — Stub with is_story_seen(), get_recent_fingerprints() signatures.

### What "Done" Looks Like
- Exact URL duplicates are removed (only first occurrence kept).
- Articles with matching fingerprints (title hash + domain) from prior weeks are removed.
- Articles marked dedup_removed=True are filtered from articles list.
- dedup_stats dict includes: {exact_dupes: N, cross_week_dupes: K, removed_count: total}.
- articles list is shorter than input (at least some dupes detected in test).
- **No fuzzy dedup in Phase 1; sentence-transformers import not needed yet.**

### Verification
```bash
python -c "
from tools.deduplicator import deduplicator_node
from state import Article
import datetime

# Create test articles with duplicates
now = datetime.datetime.now()
articles = [
    {
        'id': 'a1',
        'url': 'https://example.com/story1',
        'title': 'New AI Breakthrough',
        'source_domain': 'example.com',
        'published_date': now,
        'summary': 'Test',
        'fetch_source': 'test',
    },
    {
        'id': 'a2',
        'url': 'https://example.com/story1',  # exact duplicate
        'title': 'New AI Breakthrough',
        'source_domain': 'example.com',
        'published_date': now,
        'summary': 'Test',
        'fetch_source': 'test',
    },
    {
        'id': 'a3',
        'url': 'https://other.com/story2',
        'title': 'Different story',
        'source_domain': 'other.com',
        'published_date': now,
        'summary': 'Test',
        'fetch_source': 'test',
    },
]

state = {'validated_articles': articles}
result = deduplicator_node(state)
print(f'Validated: {len(articles)}, Deduplicated: {len(result[\"deduplicated_articles\"])}')
print(f'Dedup stats: {result[\"dedup_stats\"]}')
assert len(result['deduplicated_articles']) < len(articles)
"
```

---

## Step 6: Ranker and Summarizer (with Batching and Caching)

### What Gets Built
- tools/ranker.py: Batch LLM relevance scoring (5 articles per call using Claude Haiku), section assignment, top 15–20 selection, LLM call budget tracking.
- tools/summarizer.py: Batch LLM summarization (3 articles per call using Claude Haiku) + summary caching (reuse summaries from prior runs).
- Both track llm_call_count and estimated_cost_usd.
- memory/summary_cache.py: Summary cache module (get/save cached summaries by URL).

### Files Touched
- **tools/ranker.py** — Implement ranker_node(state) with **batch** relevance_skill LLM calls (5 articles per call, using Claude Haiku).
- **tools/summarizer.py** — Implement summarizer_node(state) with **batch** summarization_skill LLM calls (3 articles per call, using Claude Haiku) + summary cache lookup.
- **skills/relevance_skill.py** — Implement with batch signature relevance_skill_batch(articles, interest_profile) → {results: [{article_id, relevance_score, section}]}.
- **skills/summarization_skill.py** — Implement with batch signature summarization_skill_batch(articles) → {summaries: [{article_id, summary_text, why_matters}], estimated_cost_usd}.
- **memory/summary_cache.py** — New module with get_cached_summary(url), save_summary(url, summary_text, why_matters, expires_date).

### What "Done" Looks Like
- **Ranker**: 
  - Groups articles into batches of 5.
  - Calls relevance_skill_batch per batch (4 batches for ~20 articles = 4 LLM calls instead of 20).
  - Updates relevance_score, section, ranking_reason for each article.
  - Marks articles outside top 15–20 with ranking_removed=True.
  - LLM call count: ~4 calls instead of 20; estimated cost: ~$0.06 instead of $2.40.
- **Summarizer**:
  - Checks summary_cache for each article URL (if ENABLE_SUMMARY_CACHE=True).
  - Uses cached summary if found and not expired (30 days old).
  - For uncached articles, groups into batches of 3.
  - Calls summarization_skill_batch per batch (7 batches for ~20 articles = 7 LLM calls instead of 20).
  - Saves new summaries to cache for future runs.
  - Estimated cost: ~$0.28 instead of $3.00 (and 20–30% further savings from cache hits).
- articles list includes: summary_text, why_matters, relevance_score, section (fully populated).
- ranking_stats dict shows section breakdown and total articles ranked.
- Cache hit stats logged (e.g., "8 of 20 summaries from cache, saved $0.08").

### Verification
```bash
python -c "
from tools.ranker import ranker_node
from config import INTEREST_PROFILE
from state import Article
import datetime

# Create test articles
articles = [
    {
        'id': f'test-{i}',
        'url': f'https://example.com/{i}',
        'title': f'Article {i}',
        'source_domain': 'example.com',
        'published_date': datetime.datetime.now(),
        'summary': 'Test',
        'fetch_source': 'test',
        'credibility_score': 0.8,
    }
    for i in range(10)
]

state = {
    'deduplicated_articles': articles,
    'interest_profile': INTEREST_PROFILE,
    'llm_call_count': 0,
    'estimated_cost_usd': 0.0,
}

result = ranker_node(state)
print(f'Ranked: {len(result[\"ranked_articles\"])}, Final: {len(result[\"final_articles\"])}')
print(f'LLM calls: {result[\"llm_call_count\"]}, Cost: \${result[\"estimated_cost_usd\"]:.2f}')
"
```

---

## Step 7: Newsletter Drafter

### What Gets Built
- tools/drafter.py: Assemble summarized articles into full HTML newsletter using Jinja2 templating.
- Select highlight story (highest relevance).
- Group articles by section.
- Return draft_newsletter (full HTML) and newsletter_metadata.

### Files Touched
- **tools/drafter.py** — Implement drafter_node(state) with Jinja2 templating.
- **skills/drafting_skill.py** — Stub with signature drafting_skill(articles, highlight_story, interest_profile) → {html, metadata}.

### What "Done" Looks Like
- draft_newsletter is valid HTML (renderable in email client).
- Highlight story is featured at the top with expanded summary.
- 5 sections are present (Trending, Research, Tools, Industry, Analysis) with articles grouped correctly.
- Each article card includes: title, summary_text, why_matters, link to full article.
- newsletter_metadata includes: title, date, highlight_story_id, section_breakdown (article count per section).
- HTML has inline styles (no external CSS; email-safe).

### Verification
```bash
python -c "
from tools.drafter import drafter_node
from state import Article
import datetime

# Create test articles
articles = [
    {
        'id': f'test-{i}',
        'url': f'https://example.com/{i}',
        'title': f'Article {i}',
        'source_domain': 'example.com',
        'published_date': datetime.datetime.now(),
        'summary': 'Test',
        'fetch_source': 'test',
        'relevance_score': 0.9 - i * 0.1,
        'section': ['Trending', 'Research', 'Tools', 'Industry', 'Analysis'][i % 5],
        'summary_text': f'Summary of article {i}',
        'why_matters': 'Because it matters',
        'estimated_cost_usd': 0.15,
    }
    for i in range(10)
]

state = {
    'summarized_articles': articles,
    'final_articles': articles,
    'interest_profile': {},
    'run_timestamp': datetime.datetime.now(),
}

result = drafter_node(state)
print(f'Draft newsletter length: {len(result[\"draft_newsletter\"])} chars')
print(f'Metadata: {result[\"newsletter_metadata\"]}')
assert '<html' in result['draft_newsletter'].lower()
"
```

---

## Step 8: Human Review UI (Progressive Flow)

### What Gets Built
- ui/review_app.py: Streamlit app with progressive article review flow
- Articles displayed one at a time (highlight → preview → by section)
- Approve/Reject buttons trigger article removal and next article appearance
- Progress bar tracks review status
- Integrates with LangGraph interrupt checkpoint

### Files Touched
- **ui/review_app.py** — Implement progressive Streamlit app with:
  - Session state tracking for reviewed_article_ids
  - Progress bar showing "X / Y articles reviewed"
  - Highlight article displayed first with full controls
  - Preview section for next 2-3 articles (collapsible)
  - Remaining articles grouped by section (one visible per section)
  - Approve/Reject buttons trigger st.rerun() to show next article
  - Automatic feedback collection on button click
  - Global approve/reject/re-run buttons (available anytime)
  - Decision feedback form with 500-char limit

### What "Done" Looks Like
- Streamlit app starts without errors
- Progress bar shows "0 / 22 articles reviewed" initially
- Highlight article displays with title, source, relevance, summary
- 300-char feedback box available
- Approve/Reject buttons have large, visible styling
- Clicking Approve/Reject:
  - Saves feedback to human_review_edits
  - Marks article as reviewed
  - Progress bar updates
  - Next unreviewed article appears
  - No page reload needed (smooth UX)
- Preview section shows next 2-3 articles (optional)
- Remaining articles grouped by section (collapsed/expandable)
- When all articles reviewed: "🎉 All articles reviewed!" message
- Global buttons (Approve All, Re-rank, Reject) visible throughout
- Clicking global button shows decision feedback form
- Submitting decision writes .aria_review_decision.json

### Verification
```bash
# Start the Streamlit app
streamlit run ui/review_app.py

# Then in browser: http://localhost:8501
# - See progress bar starting at 0 / 22
# - See highlight article with feedback box and buttons
# - Click Approve/Reject
# - Verify article disappears and next appears
# - Verify progress bar updates
# - Click global button
# - Verify decision feedback form appears
# - Submit decision
# - Check that .aria_review_decision.json created
```

---

## Step 9: Publisher

### What Gets Built
- tools/publisher.py: Send newsletter via Gmail API, update memory stores (source_scores, story_fingerprints, preference_history, topic_history), save to archive, log eval results.

### Files Touched
- **tools/publisher.py** — Implement publisher_node(state) with:
  - Gmail API integration (send message).
  - Updates to source_memory, story_memory, preference_memory.
  - Newsletter archive save.
  - Eval results logging.
- **memory/newsletter_archive.py** — Stub with save_newsletter(), get_last_newsletter() signatures.

### What "Done" Looks Like
- Newsletter is sent via Gmail to NEWSLETTER_RECIPIENT_EMAIL from GMAIL_SENDER_EMAIL.
- published=True, publish_timestamp is set, publish_status="success".
- source_scores are updated (articles kept → positive signal on source domain).
- story_fingerprints are saved (for dedup in future runs).
- preference_history is updated (topic weights adjusted based on human edits).
- newsletter is archived in newsletters table with HTML, metadata, and cost.
- eval_results are logged in eval_results table.

### Verification
```bash
python -c "
# Test without actually sending email
from tools.publisher import publisher_node
from state import Article
import datetime

articles = [
    {
        'id': f'test-{i}',
        'url': f'https://example.com/{i}',
        'title': f'Article {i}',
        'source_domain': 'example.com',
        'section': 'Trending',
        'human_feedback': 'approved' if i % 2 == 0 else 'removed',
    }
    for i in range(5)
]

state = {
    'summarized_articles': articles,
    'final_articles': articles,
    'human_review_edits': [],
    'draft_newsletter': '<html><body>Test</body></html>',
    'run_id': 'test-pub',
    'run_timestamp': datetime.datetime.now(),
}

# Note: This will fail without Gmail credentials, which is expected
# Just verify the function exists and has correct signature
print('Publisher node function exists and loads')
"
```

---

## Step 10: Memory Layer — Full CRUD

### What Gets Built
- memory/source_memory.py: get_source_score, update_source_score, blacklist_source, get_blacklisted_sources.
- memory/story_memory.py: is_story_seen, save_story_fingerprints, get_recent_fingerprints.
- memory/preference_memory.py: get_interest_profile, update_from_edits, get_preference_history.
- memory/newsletter_archive.py: save_newsletter, get_last_newsletter, get_all_newsletters.

### Files Touched
- **memory/source_memory.py** — Implement all 4 functions with SQL queries against source_scores table.
- **memory/story_memory.py** — Implement all 3 functions with SQL queries against story_fingerprints table.
- **memory/preference_memory.py** — Implement all 3 functions with SQL queries against preference_history table.
- **memory/newsletter_archive.py** — Implement all 3 functions with SQL queries against newsletters table.

### What "Done" Looks Like
- source_memory.get_source_score(domain) returns a float (0–1) or None if domain never seen.
- source_memory.update_source_score(domain, score) increments an internal counter and updates score.
- source_memory.blacklist_source(domain) marks a domain as blacklisted.
- source_memory.get_blacklisted_sources() returns a list of blacklisted domains.
- story_memory.is_story_seen(fingerprint) returns True if story was in a prior newsletter.
- story_memory.save_story_fingerprints(newsletter_id, fingerprints_list) saves fingerprints to DB.
- story_memory.get_recent_fingerprints(days=30) returns fingerprints from the last N days.
- preference_memory.get_interest_profile() returns the current interest profile (dict).
- preference_memory.update_from_edits(edits_list) adjusts profile weights based on human feedback.
- preference_memory.get_preference_history() returns a list of historical drift events.
- newsletter_archive.save_newsletter(newsletter_id, html, metadata) stores in DB.
- newsletter_archive.get_last_newsletter() returns the most recent sent newsletter.
- newsletter_archive.get_all_newsletters() returns all newsletters (with pagination).

### Verification
```bash
python -c "
from memory.source_memory import get_source_score, update_source_score
from memory.story_memory import is_story_seen, save_story_fingerprints
from memory.newsletter_archive import save_newsletter, get_last_newsletter
import hashlib

# Test source memory
score = get_source_score('anthropic.com')
print(f'Anthropic score (first call): {score}')

update_source_score('anthropic.com', 0.9)
score = get_source_score('anthropic.com')
print(f'Anthropic score (after update): {score}')

# Test story memory
fp = hashlib.sha256('test article'.encode()).hexdigest()
result = is_story_seen(fp)
print(f'Story seen (first call): {result}')

save_story_fingerprints('nl-1', [fp])
result = is_story_seen(fp)
print(f'Story seen (after save): {result}')

print('Memory layer works!')
"
```

---

## Step 11: Skills Layer — Implement Versioned Prompt Templates

### What Gets Built
- Four Python modules that implement the skill specifications from Phase 2
- Each module calls Claude Sonnet 4.6 with the prompt from the corresponding `.md` file
- Includes error handling, cost tracking, and fallback logic

### Files Touched
- **skills/summarization_skill.py** — Implement summarization_skill(article: Article) → {summary_text, why_matters, estimated_cost_usd}
  - Reads system prompt from skills/summarization.md v1.0
  - Calls Claude Sonnet 4.6 with temperature 0.3
  
- **skills/relevance_skill.py** — Implement relevance_skill(article: Article, interest_profile: dict) → {relevance_score, section, reasoning}
  - Reads system prompt from skills/relevance.md v1.0
  - Injects interest_profile into prompt
  - Temperature 0.2
  
- **skills/credibility_skill.py** — Implement credibility_skill(source_domain: str, hints: dict) → {credibility_score, signals}
  - Reads system prompt from skills/credibility.md v1.0
  - Implements caching: cache results in source_memory, reuse if < 30 days old
  - Temperature 0.1
  
- **skills/drafting_skill.py** — Implement drafting_skill(topics_summary: dict, highlight: Article, profile: dict) → {intro_text, word_count}
  - Reads system prompt from skills/drafting.md v1.0
  - Generates intro paragraph only (Jinja2 templates for HTML assembly in drafter.py)
  - Temperature 0.7

### What "Done" Looks Like
- Each skill implements the prompt specification from its `.md` file exactly
- JSON parsing works (error handling for malformed JSON)
- Cost estimation: function returns estimated_cost_usd based on token counts
- Caching works: credibility_skill checks source_memory before calling Claude
- Fallback values: if LLM call fails, function returns safe defaults (0.5 score, generic section, etc.)
- All skills include docstrings and match the `.md` specifications
- All skills tested against the example inputs/outputs in their `.md` files

### Verification
```bash
python -c "
from skills.summarization_skill import summarization_skill
from skills.relevance_skill import relevance_skill
from skills.credibility_skill import credibility_skill
from skills.drafting_skill import drafting_skill
from config import INTEREST_PROFILE
import json

# Test summarization (from skills/summarization.md example)
article = {
    'title': 'OpenAI releases GPT-4o mini',
    'url': 'https://openai.com/blog/gpt-4o-mini',
    'summary': 'OpenAI announced GPT-4o mini...'
}
result = summarization_skill(article)
assert 'summary_text' in result
assert 'why_matters' in result
print(f'✓ Summarization works: {result[\"summary_text\"][:50]}...')

# Test relevance (from skills/relevance.md example)
result = relevance_skill(article, INTEREST_PROFILE)
assert 0.0 <= result['relevance_score'] <= 1.0
assert result['section'] in ['Trending', 'Research', 'Tools & Resources', 'Industry News', 'Analysis & Opinion']
print(f'✓ Relevance works: score {result[\"relevance_score\"]:.2f}, section {result[\"section\"]}')

# Test credibility (from skills/credibility.md example)
result = credibility_skill('thegradient.pub', {})
assert 0.0 <= result['credibility_score'] <= 1.0
assert isinstance(result['signals'], list)
print(f'✓ Credibility works: score {result[\"credibility_score\"]:.2f}')

# Test drafting
topics = {'Trending': 4, 'Research': 3}
result = drafting_skill(topics, article, INTEREST_PROFILE)
assert 'intro_text' in result
assert result['word_count'] <= 100
print(f'✓ Drafting works: intro ({result[\"word_count\"]} words)')

print('✓ All skills implemented and tested!')
"
```

---

## Step 12: Evals Layer — Metrics Collection and Reporting

### What Gets Built
- evals/eval_runner.py: Main runner; aggregates all eval metrics.
- evals/relevance_eval.py: Compute relevance rate (thumbs up %).
- evals/dedup_eval.py: Compute dedup precision (% duplicates that slipped through).
- evals/source_eval.py: Compute source credibility calibration (agent vs. human agreement).

### Files Touched
- **evals/eval_runner.py** — Implement run_evals(run_id) → {relevance_rate, edit_rate, dedup_precision, source_calibration, preference_drift}.
- **evals/relevance_eval.py** — Implement relevance_rate_eval(run_id) → float.
- **evals/dedup_eval.py** — Implement dedup_precision_eval(run_id) → float.
- **evals/source_eval.py** — Implement source_calibration_eval(run_id) → float.

### What "Done" Looks Like
- eval_runner queries eval_results table and user_feedback table.
- relevance_eval computes (thumbs_up_count) / (thumbs_up_count + thumbs_down_count).
- dedup_eval queries manually-logged duplicate slips (or uses feedback to infer).
- source_eval maps final_articles to source domains, computes approval rate per domain.
- All evals return a float (0–1) and a dict of supporting details.
- evals can be run post-publication to analyze a specific run.

### Verification
```bash
python -c "
from evals.eval_runner import run_evals

# Dummy run (no real data, but verify function exists)
# result = run_evals('test-run-1')  # Would fail without data
# print(f'Evals: {result}')

print('Evals layer structure exists')
"
```

---

## Step 13: Polish and Stretch — Error Handling, Logging, Documentation

### What Gets Built
- main.py: Entry point; builds and invokes the full graph.
- Comprehensive error handling in all nodes.
- Rich logging output (progress, warnings, errors).
- Optional stretch features: PDF export, Slack integration, scheduling.

### Files Touched
- **main.py** — Implement main() to:
  1. Load .env variables.
  2. Initialize memory (init_db).
  3. Build LangGraph StateGraph.
  4. Invoke graph.
  5. Handle interrupts (human review).
  6. Report results.
- All agent/tool/skill files — Add error handling with try-except + logging.
- **tests/*.py** — Implement unit tests for validator, deduplicator, and state.

### What "Done" Looks Like
- `python main.py` runs the full pipeline from start to end.
- Errors are caught, logged, and the system degrades gracefully (continues with partial results).
- Progress is printed in real-time (using rich.progress).
- All unit tests pass: pytest tests/ -v.
- README.md includes setup and run instructions.
- Optional: PDF export of newsletter, Slack notification on publish, cron scheduling.

### Verification
```bash
# End-to-end test
python main.py

# Should output:
# - Supervisor running
# - 4 subagents fetching in parallel
# - Articles validated, deduplicated, ranked, summarized
# - HTML draft generated
# - Human review UI started (or waits for approval)
# - Publisher sends email
# - Memory updated
# - All evals logged

# Unit tests
pytest tests/ -v

# Should show all tests passing
```

---

## Build Sequence Summary

| Step | Phase | Component | Est. Time | Cost (Full Run) |
|------|-------|-----------|-----------|-----------------|
| 1 | Foundation | State, config, memory schema, skill interface | 40 min | — |
| 2 | Subagents | Subagent Dispatcher (RSS + HN + ArXiv, Tavily disabled) | 60 min | $0.00–$0.05 |
| 3 | Orchestration | Supervisor | 15 min | — |
| 4 | Filtering | Validator + circuit breaker | 30 min | — |
| 5 | Filtering | Deduplicator (exact + cross-week) | 25 min | — |
| 6 | Synthesis | Ranker + Summarizer (Haiku + batching + caching) | 90 min | **$0.25** |
| 7 | Synthesis | Drafter (static template or LLM) | 15 min | — |
| 8 | Human Loop | Review UI (Streamlit) | 45 min | — |
| 9 | Publishing | Publisher + Gmail | 40 min | — |
| 10 | Persistence | Memory layer + summary cache (full CRUD) | 75 min | — |
| 11 | Skills | Prompt templates (4 skills with batch support) | 70 min | — |
| 12 | Evaluation | Evals layer (5 metrics) | 40 min | — |
| 13 | Polish | main.py, error handling, runaway guards | 60 min | — |
| **Total** | | | **595 min (~10 hours)** | **~$0.25/run** |

**Cost & Performance Notes** (with Haiku + Batching + Summary Caching):
- **Typical weekly run**: $0.25 (Ranker Haiku batch $0.06 + Summarizer Haiku batch $0.28 − cache hits $0.06 + Drafter $0)
- **Yearly cost** (52 weeks): ~$13 (down from ~$314 with original Sonnet serial approach)
- **Autonomous runtime**: ~72 seconds (down from ~150 seconds, faster with 3 sources)
- **With human review**: ~6 minutes median (down from ~7.5 minutes)
- **All APIs** (RSS, HN, ArXiv, Gmail): Free tier
- **Why 3 sources?** Tavily disabled — free-tier results lacked reliable date extraction; 3 trusted sources (RSS, HN, ArXiv) have verified date metadata
- **Embeddings** (dedup): Local sentence-transformers, free, zero API calls
- **Summary cache hit rate**: ~20–30% over time, additional $0.06–$0.10/year savings

---

## Dependencies Between Steps

```
Step 1 (Foundation: State, Config, Memory Schema, Skill Interface)
  ↓
Step 2 (Subagent Dispatcher: RSS + Tavily + HN + ArXiv)
  ↓
Step 3 (Supervisor)
  ↓
Step 4 (Validator) → Step 5 (Deduplicator) → Step 6 (Ranker + Summarizer with Batching + Caching) → Step 7 (Drafter)
  ↓
Step 8 (Human Review UI) → Step 9 (Publisher)
  ↓
Step 10 (Memory Layer + Summary Cache) [Parallel with Step 9]
  ↓
Step 11 (Skills Layer with Batch Support) [Used by Steps 4, 6, 7, 9]
  ↓
Step 12 (Evals Layer)
  ↓
Step 13 (Polish + main.py)
```

**Key insight**: 
- Steps 1–3 are sequential (foundation → consolidated subagents → orchestration).
- Steps 4–9 are mostly sequential (linear pipeline: validate → dedup → rank → summarize → draft → review → publish).
- Steps 10–11 can overlap with 4–9 (memory and skills are called from within those steps).
- Step 12 (evals) post-processes results after publication.
- Step 13 ties everything together with error handling and logging.

