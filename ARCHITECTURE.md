# ARIA LangGraph Architecture

## Complete Graph Definition

The ARIA system is a LangGraph StateGraph with 9 nodes and conditional edges that implement a news aggregation and curation pipeline. The graph uses `Annotated[list, operator.add]` for parallel-safe writes, `interrupt_before` for human-in-the-loop checkpoints, and optional LangSmith tracing for observability.

**Optional Observability**: Set `LANGSMITH_API_KEY` environment variable to enable production-grade tracing and evals monitoring via LangSmith. If not set, the system functions normally without tracing.

---

## Node Specifications

**Implementation Note: State Design** — While this document references separate states (raw_articles, validated_articles, etc.) for conceptual clarity, the actual implementation uses a single consolidated `articles` list that flows through the pipeline. Each node enriches the list in-place by adding fields (validation_status, credibility_score, relevance_score, summary_text, etc.). Articles marked for filtering are identified by status fields and excluded downstream, rather than moved to separate lists. This approach optimizes memory usage and is better suited to LangGraph's state merging semantics.

### Node 1: Supervisor
- **Function**: `agents/supervisor.py:supervisor_node(state: ARIAState) -> ARIAState`
- **Role**: Intelligent orchestrator; decides which subagents to run, fetch budgets, and topic priorities.
- **State Reads**: 
  - `run_id`, `run_timestamp`
  - `interest_profile` (from config, may be updated from preference_memory)
  - `topic_history` (from memory, last 4 weeks)
  - `cost_budget` (from config, default $5.00)
- **State Writes**:
  - `fetch_plan` (string summary of strategy)
  - `priority_topics` (list of strings, ranked by weight)
  - `subagent_instructions` (dict with per-agent overrides: enabled, max_articles, query_templates)
  - `estimated_budget_remaining` (float, for downstream runaway guards)
- **Logic**:
  1. Reads topic_history from memory; identifies which topics were heavily covered last week (> 3 articles).
  2. Deprioritizes topics with heavy coverage; boost underrepresented topics.
  3. **Intelligent subagent dispatch**: Decides fetch budgets for 3 trusted sources:
     - RSS: Always on (most reliable, low cost, well-structured feeds)
     - Hacker News: On if budget permits (good for developer sentiment and hot takes)
     - ArXiv: On if interest_profile emphasizes research topics (LLMs, Vision, RL, Safety)
  4. **Dynamic fetch budgets**: Allocates articles per subagent based on cost constraints:
     - If cost_budget high ($2.00): request 15 articles per subagent
     - If cost_budget tight (<$1.00): request 5 articles per subagent
  5. Computes a human-readable fetch_plan string.
  6. Estimates cost for Ranker + Summarizer; subtracts from budget to get remaining.
- **Error handling**: If memory lookup fails, uses conservative defaults (all subagents on, 5 articles each).
- **Execution time**: ~2 seconds (memory reads + logic).
- **Cost**: $0 (no LLM calls).

### Node 2: Subagent Dispatcher (3 Parallel Fetchers)
- **Function**: `agents/subagent_dispatcher.py:subagent_dispatcher_node(state: ARIAState) -> ARIAState`
- **Role**: Coordinate 3 trusted data sources (RSS feeds, Hacker News, ArXiv) in parallel via asyncio.
- **State Reads**:
  - `priority_topics`, `subagent_instructions` (from supervisor)
  - Config: `RSS_FEEDS`, `HN_MIN_SCORE`, `HN_AI_KEYWORDS`, `ARXIV_QUERIES`
- **State Writes**:
  - `articles` (appended via `Annotated[list, operator.add]`)
  - `fetch_errors` (appended via `Annotated[list, operator.add]`)
  - `total_fetched` (count of articles fetched across all sources)
- **Sub-Fetchers** (run in parallel within dispatcher):
  1. **RSS Fetcher** — feedparser.parse() on each feed
     - Max 15 articles per feed
     - Extract: url, title, summary, published_date, source_domain
  2. **Hacker News Fetcher** — Firebase API (hacker-news.firebaseio.com/v0)
     - Fetch top 30 stories, filter by score >= HN_MIN_SCORE and AI keywords
     - Max 15 articles
     - Extract: url, title, hn_score, published_date, source_domain="news.ycombinator.com"
  3. **ArXiv Fetcher** — arxiv.Search() per query
     - Max 15 articles per query (3 results per query × 5 queries)
     - Extract: url, title, summary (abstract), published_date, source_domain="arxiv.org", arxiv_category
- **Why 3 Sources (Tavily Disabled)**:
  - Tavily web search results lacked reliable publication date metadata
  - Mix of result types (landing pages, aggregators, posts) with inconsistent date fields
  - 3 trusted sources (RSS, HN, ArXiv) have verified, consistent date extraction
  - Quality > quantity: ~40-50 fresh articles vs ~100 with date extraction issues
- **Aggregation**:
  - Collect articles from all 3 fetchers; errors from any fetcher logged to fetch_errors
  - Each article tagged with fetch_source (e.g., "rss", "hacker_news", "arxiv")
  - Max 15 articles per individual source enforced; total cap at 120 across all sources
- **Timeout**: 90 seconds total (enforced by LangGraph; if exceeded, return partial results from completed fetchers)
- **Cost**: ~$0 (no LLM calls, all APIs are free)
- **Execution time**: ~25 seconds (max of individual fetcher times, due to parallelization)

**Design Note**: Consolidating 3 separate nodes into 1 dispatcher eliminates code duplication, improves maintainability, and makes it easy to add new sources in the future. The internal parallelization is handled by asyncio or concurrent.futures, not by LangGraph edges.

### Node 3: Validator
- **Function**: `tools/validator.py:validator_node(state: ARIAState) -> ARIAState`
- **Role**: Score, filter, and gate articles.
- **State Reads**:
  - `articles` (from all 3 subagents; contains fetch_source, validation_status=pending)
  - `fetch_errors`
  - `run_timestamp`
  - Source scores from memory (source_memory.get_source_score)
  - Blacklisted sources from memory
- **State Writes**:
  - `articles` (updated in-place; mark each article with validation_status, validation_reason, credibility_score)
  - `validation_stats` (dict: {filtered_by_date, filtered_by_credibility, circuit_breaker_fired, removed_count})
- **Logic**:
  1. Check: if len(raw_articles) > 120, raise RunawayError (too many raw articles).
  2. For each article in raw_articles:
     a. Check published_date: if older than run_timestamp - 7 days, mark for filtering (too old).
     b. Look up source_domain credibility score from memory; call credibility_skill if score unavailable.
     c. If credibility_score < 0.3 AND domain not in KNOWN_CREDIBLE_SOURCES, mark for filtering (low credibility).
     d. Check if source_domain is in blacklisted_sources; if yes, mark for filtering (blacklisted).
     e. If not filtered, move to validated_articles.
  3. After filtering: if len(validated_articles) > 60, invoke circuit breaker:
     a. Sort validated_articles by (credibility_score * 0.6 + relevance_proxy * 0.4) descending.
     b. Truncate to 60 articles.
     c. Set validation_stats["circuit_breaker_fired"] = True.
  4. Record all filtered articles in filtered_articles (with reason).
- **Timeout**: None (not a subagent, runs synchronously).
- **Cost**: ~$0.08 per new domain (credibility_skill, called once per domain in a run).
- **Execution time**: 5–10 seconds.

### Node 4: Deduplicator
- **Function**: `tools/deduplicator.py:deduplicator_node(state: ARIAState) -> ARIAState`
- **Role**: Remove duplicate stories within and across weeks.
- **State Reads**:
  - `articles` (from validator)
  - Story fingerprints from memory (story_memory.get_recent_fingerprints)
- **State Writes**:
  - `articles` (updated in-place with dedup_removed=True for duplicates)
  - `dedup_stats` (dict: {exact_dupes, cross_week_dupes, removed_count})
- **Logic**:
  1. **Exact URL dedup**: Track seen_urls (set). For each article, if url in seen_urls, mark dedup_removed=True. Otherwise, add to seen_urls and keep.
  2. **Cross-week fingerprint check**: For each kept article, compute fingerprint = hash(title + source_domain). Check against story_fingerprints from memory (last 4 weeks). If match found, mark dedup_removed=True, increment cross_week_dupes.
  3. Remove articles marked dedup_removed=True from final list.
  4. **Fuzzy dedup (Phase 14 enhancement)**: Optional sentence-transformers-based title similarity (not in Phase 1; added in polish step).
- **Timeout**: None.
- **Cost**: $0 (purely algorithmic; no API calls).
- **Execution time**: 1–2 seconds (tight inner loops, no I/O).

### Node 5: Ranker
- **Function**: `tools/ranker.py:ranker_node(state: ARIAState) -> ARIAState`
- **Role**: Score articles by relevance and select top 15–20.
- **State Reads**:
  - `articles` (articles still in pipeline; validation_status=valid, dedup_removed=false)
  - `interest_profile` or `interest_profile_edits` (human-edited profile takes precedence)
  - `llm_call_count`, `estimated_cost_usd` (for runaway guards)
  - `RANKER_MODEL` (from config; defaults to Claude Haiku for cost efficiency)
- **State Writes**:
  - `articles` (updated in-place; add relevance_score, section, ranking_reason)
  - Keep only top 15–20 (set ranking_removed=true for others)
  - `ranking_stats` (dict: {total_scored, sections: {Trending: N, Research: N, ...}})
  - Increments `llm_call_count`
  - Increments `estimated_cost_usd`
- **Logic**:
  1. **Batch articles for efficiency**: Group articles into batches (5 per batch).
  2. For each batch:
     a. Call relevance_skill_batch(batch, interest_profile) → {results: [relevance_score, section, reasoning]}.
     b. Update each article in batch with relevance_score and section.
     c. Increment llm_call_count by 1 (not per article).
     d. Add estimated_cost_usd from skill result.
  3. Check: if llm_call_count > 18, issue warning (approaching max of 20).
  4. Sort ranked_articles by relevance_score descending.
  5. Select top 15–20 articles (configurable); move to final_articles.
  6. Count articles per section; record in ranking_stats.
- **Timeout**: None.
- **Model**: Claude Haiku (deterministic ranking, minimal reasoning needed).
- **Cost**: ~$0.015 per call (batch of 5) × 4 batches = ~$0.06 total.
- **Execution time**: 10–20 seconds (4 batches × 2–3s per batch).
- **Runaway guards**: LLM call count (max 20), cost budget ($2.00).

### Node 6: Summarizer (with Summary Caching)
- **Function**: `tools/summarizer.py:summarizer_node(state: ARIAState) -> ARIAState`
- **Role**: Generate 3-sentence summary + "why it matters" per article via batch processing, with caching of summaries from prior runs.
- **State Reads**:
  - `articles` (articles with ranking_removed=false; selected for newsletter)
  - `llm_call_count`, `estimated_cost_usd`
  - `SUMMARIZER_BATCH_SIZE` (from config; default 3 articles per call)
  - `SUMMARIZER_MODEL` (from config; defaults to Claude Haiku)
  - Summary cache from memory (summary_memory.get_cached_summary(url))
- **State Writes**:
  - `articles` (updated in-place; add summary_text, why_matters, estimated_cost_per_article)
  - Updates `llm_call_count`
  - Updates `estimated_cost_usd`
  - **Runaway enforcement**: If estimated_cost_usd + next_batch_cost > cost_budget, skip remaining batches and log warning
- **Logic**:
  1. **Check cache first**: For each article, look up URL in summary_cache (from memory).
     - If cached summary found and recent (< 30 days old), use cached summary (cost = $0, no LLM call).
     - If not cached or stale, mark for batch summarization.
  2. **Batch remaining articles**: Group uncached articles into batches of size SUMMARIZER_BATCH_SIZE (default 3).
  3. For each batch:
     a. Check remaining budget: if llm_call_count >= 20 or estimated_cost_usd >= 1.90, skip remaining batches.
     b. Call summarization_skill_batch(batch) → {summaries: [{article_id, summary_text, why_matters}], estimated_cost_usd}.
     c. Update each article in batch with summary_text, why_matters.
     d. Save summaries to cache (summary_memory.save_summary(url, summary_text, why_matters, timestamp)).
     e. Increment llm_call_count by 1 (not per article).
     f. Add batch's estimated_cost_usd to state.estimated_cost_usd.
  4. Return summarized_articles (mix of cached and newly generated summaries).
- **Timeout**: None.
- **Model**: Claude Haiku (creative but brief summarization).
- **Cost**: ~$0.04 per batch call × (7 - cached_count) batches. With caching, typical 20–30% of summaries are cached, reducing cost to ~$0.20 per run.
- **Execution time**: 10–25 seconds (fewer batches due to cached hits).
- **Cache hit rate**: ~20–30% over time (RSS feeds republish articles, minor edits or duplicate stories).
- **Runaway guards**: LLM call count (max 20), cost budget ($2.00), skip on exceeded.

**Caching Strategy**: Articles from RSS feeds sometimes republish or reappear with minor edits. Caching summaries by URL (normalized) eliminates redundant LLM calls. Cache is invalidated after 30 days to allow fresh summaries as context changes.

### Node 7: Drafter
- **Function**: `tools/drafter.py:drafter_node(state: ARIAState) -> ARIAState`
- **Role**: Assemble full HTML newsletter.
- **State Reads**:
  - `articles` (articles with ranking_removed=false; summarized)
  - `interest_profile`
  - `run_timestamp`
- **State Writes**:
  - `draft_newsletter` (full HTML string with inline styles)
  - `newsletter_metadata` (dict: {title, date, highlight_story_id, section_breakdown, article_count, estimated_cost_total})
- **Logic**:
  1. Identify highlight story: article in final_articles with max relevance_score.
  2. Group articles by article.section (Trending, Research, Tools, Industry, Analysis).
  3. Call drafting_skill(summarized_articles, highlight_story, interest_profile) → {html, metadata}.
  4. drafting_skill renders a Jinja2 template with:
     - Header with date and newsletter title.
     - Featured story block for highlight article (expanded summary).
     - 5 sections, each with up to 4 articles (title, summary_text, why_matters, link).
     - Footer with archive link and unsubscribe placeholder.
  5. Return draft_newsletter (full HTML) and metadata.
- **Timeout**: None.
- **Cost**: ~$0.25 (if drafting_skill generates intro paragraph via LLM; otherwise $0).
- **Execution time**: 5–10 seconds.

### Node 8: Human Review (Interrupt Checkpoint)
- **Function**: Streamlit UI in `ui/review_app.py`; graph pauses at this node via `interrupt_before`.
- **Role**: Pause graph, let human review articles progressively, capture feedback, decide next action.
- **State Reads**:
  - `draft_newsletter` (full HTML)
  - `articles` (for feedback capture and progressive display)
  - `run_timestamp` (for timeout check)
- **State Writes**:
  - `human_review_edits` (list of Edit TypedDicts: {article_id, action, feedback, timestamp})
  - `review_approved` (boolean)
  - `review_rejected` (boolean)
  - `review_re_rank` (boolean; re-summarize with new rankings)
  - `review_timestamp` (datetime)
  - `review_notes` (optional string)
  - Updated `interest_profile` (if user adjusted weights)
- **UI Behavior (Progressive Flow)**:
  1. Show **progress bar**: "X / Y articles reviewed"
  2. Display **highlight article** first with:
     - Title, source, relevance score, published date, summary, why it matters
     - 300-char feedback text area (optional)
     - "👍 Approve" button → article disappears, next one appears, progress updates
     - "👎 Reject" button → same behavior
  3. Show **preview of next 2 articles** in collapsible sections (read-only)
  4. Show **remaining articles grouped by section** (one per section visible, others collapsible)
  5. When article receives feedback, auto-refresh to show next unreviewed article
  6. All feedback automatically saved to session state on button click
  7. When all articles reviewed: "🎉 All articles reviewed!" message
  8. **Global decision buttons** (available anytime):
     - "✅ Approve All" → Send to Publisher with feedback
     - "🔄 Re-rank" → Reorder articles, adjust profile, re-summarize
     - "❌ Reject" → Restart from Supervisor
  9. On decision button click:
     - Show decision feedback form (500-char for model learning)
     - Write decision to .aria_review_decision.json
     - Resume graph to appropriate next node
- **Timeout**: 24 hours (auto-reject if no input after 24h; log as timeout).
  ```python
  time_elapsed = (datetime.now() - state['run_timestamp']).total_seconds()
  if time_elapsed > 86400:  # 24 hours
      return {"review_rejected": True, "review_notes": "Auto-rejected: timeout after 24h"}
  ```
- **Cost**: $0.
- **Execution time**: Manual (human decides; auto-reject after 24h).

**Design Rationale**: Progressive flow reduces cognitive load by showing one article at a time, provides visual progress feedback, and enables faster decision-making. Articles disappear after feedback, eliminating the need to scroll or manage state.

### Node 9: Publisher
- **Function**: `tools/publisher.py:publisher_node(state: ARIAState) -> ARIAState`
- **Role**: Send newsletter via Gmail; update all memory stores with transactional semantics.
- **State Reads**:
  - `draft_newsletter`
  - `human_review_edits`
  - `articles` (kept articles; human_feedback field populated)
  - `run_id`, `run_timestamp`
  - `estimated_cost_usd` (for archival)
  - `GMAIL_SENDER_EMAIL`, `GMAIL_RECIPIENT_EMAIL` (from env)
- **State Writes**:
  - `published` (boolean)
  - `publish_timestamp` (datetime)
  - `publish_status` (string: "success" or error message)
- **Logic**:
  1. Build Gmail message: From, To, Subject, Body (HTML draft_newsletter).
  2. **Send first** (risky operation outside transaction):
     - Call gmail_api.users().messages().send(userId="me", body=message) → MessageId.
     - On send failure: log error, set published=False, return early (no memory writes).
  3. **On send success: Update memory (transactional)**:
     ```python
     try:
         with db.transaction():
             # All following writes wrapped in one transaction
             a. Update source_memory: increment credibility score for each kept article's domain (positive signal).
             b. Update story_memory: save story fingerprints for dedup next week.
             c. Update preference_memory: analyze human_review_edits; adjust interest_profile weights.
             d. Save to newsletters table: newsletter_id, send_date, html_content, article_count, cost_usd.
             e. Update topic_history: record topics covered this week.
             f. Record eval_results: relevance_rate, edit_rate, dedup_precision, source_calibration, preference_drift.
     except Exception as e:
         # Transaction rolls back; email was sent but memory not updated
         log_critical(f"Memory update failed after email sent: {e}")
         # Alert human: newsletter sent but memory corrupt; manual recovery needed
         return {"published": True, "publish_status": f"Email sent but DB error: {e}"}
     ```
  4. Set published=True, publish_status="success", publish_timestamp=now.
- **Timeout**: None.
- **Cost**: $0 (Gmail API free tier).
- **Execution time**: 5–15 seconds (dominated by Gmail API latency).

---

## Edge Specifications

### Edge 1: START → Supervisor
- **Condition**: Always (entry point).
- **Reason**: Supervisor is the orchestrator; every run starts here.

### Edge 2: Supervisor → {RSS Agent, HN Agent, ArXiv Agent}
- **Condition**: Always (fan-out).
- **Reason**: All 3 subagents run in parallel; their outputs are aggregated via `Annotated[list, operator.add]`.
- **Concurrency model**: LangGraph's default async concurrency. Each subagent is awaited; raw_articles from all subagents are appended to the same list.

### Edge 3: {All 3 Subagents} → Validator
- **Condition**: All 3 subagents complete (join).
- **Reason**: Validator needs all raw_articles before filtering.
- **Aggregation**: LangGraph automatically merges the state from all 3 subagents. Because raw_articles is `Annotated[list, operator.add]`, the lists are concatenated.

### Edge 4: Validator → Deduplicator
- **Condition**: Always (if no runaway error from validator).
- **Reason**: Sequential dependency; deduplicator needs validated_articles.

### Edge 5: Deduplicator → Ranker
- **Condition**: Always.
- **Reason**: Sequential dependency.

### Edge 6: Ranker → Summarizer
- **Condition**: Always.
- **Reason**: Sequential dependency.

### Edge 7: Summarizer → Drafter
- **Condition**: Always.
- **Reason**: Sequential dependency.

### Edge 8: Drafter → Human Review (Interrupt Checkpoint)
- **Condition**: Always, but with `interrupt_before=["human_review"]` to pause execution.
- **Reason**: Hard boundary between autonomous and human-approved actions.
- **UI**: Progressive flow automatically launches Streamlit UI at http://localhost:8501 with highlight article first, progress bar, and one-article-at-a-time review.

### Edge 9: Human Review → {Publisher | Supervisor | Summarizer} (Conditional)
- **Condition**: Based on review_approved, review_rejected, review_re_rank flags, and re_run_count limit.
  - **Case 1**: `review_approved=True` → go to Publisher (send approved draft).
  - **Case 2**: `review_rejected=True` → go back to Supervisor (full restart: re-fetch, re-validate, re-deduplicate, re-rank, re-summarize; keeps human notes for context; reset re_run_count to 0).
  - **Case 3**: `review_re_rank=True AND re_run_count < max_re_runs` → go back to Summarizer (re-summarize articles with updated interest_profile; increment re_run_count; assumes ranking is still valid; faster than full restart).
  - **Case 4**: `review_re_rank=True AND re_run_count >= max_re_runs` → go to Publisher (max re-runs exceeded; force publish as-is; log warning that further adjustments not allowed).
  - **Case 5 (Timeout)**: If no human decision received within 24 hours, auto-reject: set review_rejected=True, route to Supervisor, log timeout. Allows human to re-review but prevents indefinite pause.
- **Reason**: Human decision determines next action. All paths maintain consistency and cost control:
  - Approve: draft is final.
  - Reject: full fresh run with human feedback noted; resets re-run counter.
  - Re-rank: summaries are re-written to match new rankings (eliminates stale summary risk); limited to 2 attempts to prevent cost overrun.
  - Timeout: auto-reject prevents indefinite human delays while preserving state for review.
- **Cost Impact**:
  - Approve: $0 (just send)
  - Reject: ~$0.40 (full pipeline re-run with Haiku + batching)
  - Re-rank: ~$0.28 (re-summarize only, skip fetch/validate/dedup/rank)
  - Timeout auto-reject: ~$0.40 (restarts from supervisor)

### Edge 10: Publisher → END
- **Condition**: Always (after publishing or error).
- **Reason**: Final node; no further processing after publish attempt.

---

## Parallel-Safe State Management

### The Problem
Four subagents write to `raw_articles` concurrently. Without careful handling, race conditions could occur (list append during iteration, etc.).

### The Solution: Annotated + operator.add
```python
from typing import Annotated, TypedDict
from operator import add

class ARIAState(TypedDict):
    raw_articles: Annotated[list[Article], add]
    fetch_errors: Annotated[list[dict], add]
    # ... other fields
```

**How it works**:
- Each subagent returns a state dict with `raw_articles: [article1, article2, ...]`.
- LangGraph's state merger detects `Annotated[list, add]` and merges by calling `add(existing_list, new_list)`.
- `add([a, b], [c, d]) = [a, b, c, d]` — concatenation, not replacement.
- No explicit locking needed; LangGraph handles serialization.

### Other Fields
All other fields (validated_articles, final_articles, etc.) use direct replacement, not concatenation. This is safe because only one node writes to each of those fields at a time.

---

## Complete Graph Flow (ASCII Diagram)

```
                              ╔═════════════════════════════════╗
                              ║          START                  ║
                              ╚════════════════╤════════════════╝
                                              │
                                              ↓
                              ╔═════════════════════════════════╗
                              ║      SUPERVISOR NODE            ║
                              ║  (reads memory, sets plan)      ║
                              ╚════════════════╤════════════════╝
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ↓                         ↓                         ↓
    ┌────────────────────────────┐ ┌──────────────────────┐ ┌─────────────────────┐
    │  RSS AGENT (Parallel 1)    │ │ HN AGENT (Parallel 2)│ │ ARXIV AGENT (P3)    │
    │ (feedparser RSS feeds)     │ │ (Firebase API)       │ │ (arXiv API)         │
    └────────────┬───────────────┘ └──────────┬───────────┘ └────────────┬────────┘
                 │ raw_articles                │                        │
                 │ + fetch_errors              │                        │
                 └─────────────────────────────┼────────────────────────┘
                                               │
                                               ↓
    [All 3 subagents complete; lists concatenated via operator.add]
                 │
                 ↓
    ╔════════════════════════════════════════╗
    ║   VALIDATOR NODE                       ║
    ║  (credibility, date, circuit breaker)  ║
    ║   → validated_articles                 ║
    ╚════════════════╤═══════════════════════╝
                    │
                    ↓
    ╔════════════════════════════════════════╗
    ║   DEDUPLICATOR NODE                    ║
    ║  (exact + fuzzy + cross-week dedup)    ║
    ║   → deduplicated_articles              ║
    ╚════════════════╤═══════════════════════╝
                    │
                    ↓
    ╔════════════════════════════════════════╗
    ║   RANKER NODE                          ║
    ║  (LLM relevance scoring)               ║
    ║   → final_articles (15–20)             ║
    ╚════════════════╤═══════════════════════╝
                    │
                    ↓
    ╔════════════════════════════════════════╗
    ║   SUMMARIZER NODE                      ║
    ║  (LLM summaries per article)           ║
    ║   → summarized_articles                ║
    ╚════════════════╤═══════════════════════╝
                    │
                    ↓
    ╔════════════════════════════════════════╗
    ║   DRAFTER NODE                         ║
    ║  (Jinja2 HTML assembly)                ║
    ║   → draft_newsletter                   ║
    ╚════════════════╤═══════════════════════╝
                    │
          [interrupt_before="human_review"]
                    │
                    ↓
    ╔════════════════════════════════════════╗
    ║   HUMAN REVIEW (Streamlit UI)          ║
    ║   (pause for edits + approval)         ║
    ║   → human_review_edits, review_*       ║
    ╚════════╤═══════════════╤═══════════════╝
             │               │
    [Conditional Edge based on human decision]
             │               │
        ┌────┴─────┬─────────┴────────────┐
        │           │                     │
        ↓           ↓                     ↓
    [approved] [rejected]    [re_rank with
                             adjusted profile]
        │           │                     │
        │           │                     └──────┐
        │           │                            │
        │           │          ┌────────────────┤
        │           │          │                │
        │           ↓          ↓                │
        │   ┌──────────────────┐               │
        │   │ SUPERVISOR NODE  │               │
        │   │ (restart, reset) │               │
        │   └──────────────────┘       ┌───────────────┐
        │           │                  │ SUMMARIZER    │
        │           │                  │ (re-write     │
        │           │                  │ with new      │
        │           │                  │ rankings)     │
        │           │                  └───────────────┘
        │           │                          │
        ├───────────┴──────────────────────────┘
        │
        ↓
    ┌────────────────────────┐
    │  PUBLISHER NODE        │
    │  (send email)          │
    │  (update memory)       │
    └────────┬───────────────┘
             │
             ↓
    ╔════════════════════════════════════════╗
    ║            END                         ║
    ╚════════════════════════════════════════╝
```

---

## Key Architectural Patterns

### 1. Fan-Out / Fan-In (Parallel Subagents)
```python
graph.add_node("supervisor", supervisor_node)
graph.add_node("rss_agent", rss_agent_node)
graph.add_node("hn_agent", hn_agent_node)
graph.add_node("arxiv_agent", arxiv_agent_node)

graph.add_edge("supervisor", "rss_agent")
graph.add_edge("supervisor", "hn_agent")
graph.add_edge("supervisor", "arxiv_agent")

# All subagents → validator (join)
graph.add_edge("rss_agent", "validator")
graph.add_edge("hn_agent", "validator")
graph.add_edge("arxiv_agent", "validator")
```

### 2. Interrupt Checkpoint
```python
graph.add_node("human_review", human_review_node, interrupt_before=True)
# Graph pauses here; human submits decision via UI
# Resume with updated state (human_review_edits filled)
```

### 3. Conditional Routing
```python
def route_after_review(state):
    if state.get("review_approved"):
        return "publisher"
    elif state.get("review_rejected"):
        return "supervisor"  # restart
    elif state.get("review_re_run"):
        return "ranker"  # re-rank only
    else:
        return "end"  # fallback

graph.add_conditional_edges("human_review", route_after_review)
```

### 4. Parallel-Safe State Merge
```python
class ARIAState(TypedDict):
    raw_articles: Annotated[list[Article], operator.add]
    fetch_errors: Annotated[list[dict], operator.add]
```

When subagent A returns `{"raw_articles": [a1, a2]}` and subagent B returns `{"raw_articles": [b1, b2]}`, LangGraph merges them as:
```python
state["raw_articles"] = operator.add([a1, a2], [b1, b2]) = [a1, a2, b1, b2]
```

---

## Execution Model

### Synchronous (Default)
```python
result = graph.invoke(input_state)
```
Blocks until the graph finishes (or hits an interrupt).

### Streaming (For UI)
```python
for event in graph.stream(input_state):
    print(event)  # Monitor progress in real-time
```

### Resume After Interrupt
```python
# Human submits decision via Streamlit; state is updated with human_review_edits
resumed_result = graph.invoke(
    input_state,
    interrupt_before="human_review"  # Skip past interrupt
)
```

---

## Runaway Guards Positions in Graph

1. **Max articles per source** — enforced in each subagent (RSS, HN, ArXiv); set dynamically by Supervisor.
2. **Max 120 raw articles** — checked at start of Validator.
3. **Circuit breaker (max 60 after filtering)** — enforced in Validator.
4. **Max 40 LLM calls** — tracked across Ranker and Summarizer; Supervisor pre-allocates budget.
5. **Max $5.00 cost** — hard cap enforced in Summarizer before each LLM call; checked after each step.
6. **Max 90 seconds per subagent** — enforced by LangGraph timeout wrapper.
7. **Max 7 days old** — enforced in Validator by date filter.
8. **Max 24 hours in human review** — auto-reject after 24h; prevents indefinite pause.

---

## Error Handling & Retry Strategy

### Subagent Failures (RSS, HN, ArXiv)
- **On feed timeout or API error**: Append error dict to fetch_errors; continue with partial results.
- **Retry**: tenacity.retry(wait=exponential_backoff(), stop=stop_after_attempt(3)) wraps each API call.
- **Graceful degradation**: If 1 subagent fails completely, others still run and produce results.

### Memory Lookup Failures (source_scores, fingerprints)
- **On DB error**: Log warning; use defaults (credibility=0.5 for unknown sources).
- **Continue**: Don't block the pipeline.

### LLM Call Failures (Ranker, Summarizer)
- **On API error or timeout**: Log error; skip that article.
- **On budget exceeded**: Stop processing remaining articles; continue with what you have.

### Graph Execution Errors
- **On unhandled exception in a node**: LangGraph catches it, logs it, and halts. Return error state.

---

## Performance Characteristics

### Typical Run Time (Optimized with Haiku + Batching)
- **Supervisor**: ~1 second
- **Subagent Dispatcher (parallel)**: ~25 seconds (max of RSS 15–20s, HN 10–15s, ArXiv 20–25s)
- **Validator**: ~5 seconds
- **Deduplicator**: ~2 seconds
- **Ranker** (4 batches × 5 articles, Claude Haiku): ~12 seconds (vs. ~40s with Sonnet)
- **Summarizer** (7 batches × 3 articles, Claude Haiku): ~20 seconds (vs. ~60s with Sonnet)
- **Drafter** (static template, no LLM): ~3 seconds (vs. ~5s with LLM)
- **Human Review**: ~5 minutes (human-driven)
- **Publisher**: ~10 seconds
- **Total (auto)**: ~78 seconds (~1.3 minutes)
- **Total (with human review)**: ~6 minutes (median)

### Typical Token Usage (Optimized)
- Ranker: 4 batches × (5 articles × ~300 tokens) = 6,000 input + 400 output = 6,400 tokens (Haiku, $0.06)
- Summarizer: 7 batches × (3 articles × ~400 tokens) = 8,400 input + 2,100 output = 10,500 tokens (Haiku, $0.28)
- Drafter: Static template, no tokens
- **Total**: ~16,900 tokens at Haiku rates ≈ $0.34 USD

### Cost per Run (Standard, Full Pipeline with Haiku + Batching)
- **Anthropic Claude calls** (Ranker + Summarizer + Drafter):
  - Ranker (Haiku, 4 batch calls): ~$0.06 (vs. $2.40 with Sonnet serial)
  - Summarizer (Haiku, 7 batch calls): ~$0.28 (vs. $3.00 with Sonnet serial)
  - Drafter: $0.00 (static template; can enable LLM for ~$0.01)
  - **Subtotal**: ~$0.34
- **RSS/HN/ArXiv**: $0.00 (all free public APIs)
- **Other APIs**: $0.00 (RSS, HN, ArXiv are free)
- **Gmail API**: Free
- **Total**: ~$0.34–$0.39 per full run (weekly cost: ~$18–$20/year)
- **Budget**: $2.00/run (5× headroom; allows future upgrades or optional LLM features)

### Cost per Re-Run (Re-rank from Summarizer, Haiku + Batching)
- Skips: Fetch, Validate, Deduplicate, Rank
- Includes: Summarizer (7 batches) + Drafter
- **Cost**: ~$0.28–$0.29 (much cheaper than full run)

### Development Cost Optimization
- For local development and iteration, mock APIs with pre-recorded responses (no API costs)
- Use batch testing with a fixed set of ~100 articles; iterate on ranking/summarization logic
- Only run full end-to-end with live APIs once per day (development)
- Estimate: 14-step build costs ~$10–20 total for testing; production runs cost ~$3.50/week

---

## Observability & Tracing with LangSmith

**Optional feature**: If `LANGSMITH_API_KEY` environment variable is set, all LLM calls and graph executions are automatically traced to LangSmith.

### Setup
1. Create free account at https://smith.langchain.com/
2. Get API key from Settings
3. Add to `.env`: `LANGSMITH_API_KEY=your-key`

### What Gets Traced
- Every LLM call (ranker, summarizer, drafter) with tokens, latency, cost
- Graph node execution times and state transitions
- Token usage and cost per run
- Error logs and exceptions
- LangGraph checkpoints and interrupts

### Integration with Evals
- LangSmith evals tab shows human feedback (thumbs up/down)
- Compare runs across weeks to track improvement
- Identify which sources, topics, or interest profiles perform best
- Debug failures: see exactly which articles caused issues

### Cost
- Free tier: 1M traces/month (sufficient for 250 weekly runs)
- No additional cost; built into Claude API usage

---

## Extensibility

### Adding a 4th Subagent
1. Create `agents/new_agent.py` with a node function.
2. Add node and edges: `graph.add_edge("supervisor", "new_agent")` and `graph.add_edge("new_agent", "validator")`.
3. Ensure raw_articles is written via `Annotated[list, operator.add]`.
4. **Note**: Tavily web search was disabled in favor of 3 trusted sources (RSS, HN, ArXiv) with verified date metadata. See CLAUDE.md for details.

### Adding a New Filter (e.g., Language Detection)
1. Add a field to Article (language_code).
2. In Validator, add a filter condition: if language_code != "en", move to filtered_articles.
3. Update validation_stats to track this filter.

### Changing Newsletter Format
1. Modify the Jinja2 template in `skills/drafting_skill.py` or `tools/drafter.py`.
2. Update the NEWSLETTER_SECTIONS config if section count changes.
3. Re-render draft_newsletter; human review sees the new format.

