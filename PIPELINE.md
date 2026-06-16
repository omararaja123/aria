# ARIA Pipeline Architecture & Execution

## Complete Pipeline Flow with Real Numbers

### Typical Weekly Run (Cost-Optimized with Haiku + Batching)

```
START (0s)
  ↓
Supervisor (1s, $0)
  • Reads topic_history from memory (last 4 weeks)
  • Reads interest_profile from config
  • Sets fetch_plan and priority_topics
  • Returns: fetch_plan, priority_topics, subagent_instructions
  ↓
Subagent Dispatcher (25s, $0) — 3 sources in parallel
  ├─ RSS Fetcher: feedparser.parse(), max 15/feed
  ├─ Hacker News: Firebase API, filters score ≥50, max 15
  └─ ArXiv Fetcher: arxiv.Search(), max 15/query
  
  Raw articles: ~40-50 (trusted sources only, no Tavily)
  Fetched via: RSS (15-20) + HN (10-15) + ArXiv (15-20)
  Max per source: 15, Total cap: 120
  ↓
Validator (5s, $0)
  • Date filter: articles > 7 days old → removed
  • Credibility scoring: domain-based via credibility_skill (cache-first)
  • Credibility floor: < 0.3 → removed (unless in KNOWN_CREDIBLE_SOURCES)
  • Circuit breaker: if > 60 articles, trim by credibility descending
  
  Validated: ~80 articles (20% filtered by date/credibility)
  ↓
Deduplicator (2s, $0)
  • Exact URL dedup: SHA256(url)
  • Fingerprint dedup: SHA256(title + domain)
  • Cross-week dedup: check against story_fingerprints from memory (28 days)
  
  Deduplicated: ~70 articles (12.5% removed)
  ↓
Ranker (15s, $0.06) — Batch: 5 articles per Haiku call
  • Groups articles into batches of 5
  • Calls relevance_skill_batch per batch (4 calls for ~20 articles)
  • Scores 0–1 by relevance against interest_profile
  • Assigns section: Trending|Research|Tools|Industry|Analysis
  • Selects top 15–20 articles
  
  LLM calls: 4 (vs 20 serial = 80% reduction)
  Cost: $0.06 (vs $2.40 with Sonnet serial)
  Final selected: 20 articles (28.6% of validated)
  ↓
Summarizer (20s, $0.14 average, -30% from cache)
  • Cache-first: check summary_cache for each article URL
  • Cache hit (20-30%): use cached summary ($0)
  • Cache miss: group into batches of 3
  • Calls summarization_skill_batch per batch (7 calls for ~20 articles)
  • Generates: 3-sentence summary + "why it matters"
  
  LLM calls: 7 (vs 20 serial = 65% reduction)
  Cost with caching: $0.14 (vs $3.00 with Sonnet serial, $0.80 without cache)
  All 20 articles summarized
  ↓
Drafter (5s, $0.003 optional)
  • Identify highlight story (max relevance_score)
  • Group articles by section (max 4/section)
  • Render Jinja2 template with inline CSS (email-safe)
  • Optionally call drafting_skill for intro paragraph (Claude Sonnet)
  
  Output: Full HTML (~9KB), responsive design
  ↓
AUTONOMOUS PHASE COMPLETE (72s, $0.20–0.24)

  ↓
Human Review (pause at interrupt_before checkpoint)
  • Progressive Streamlit UI with real-time feedback flow
  • Articles appear one at a time (highlight, then preview next 2, then by section)
  • User clicks Approve/Reject → article disappears, next appears automatically
  • Progress bar shows X / Y articles reviewed
  • Feedback automatically collected on each click
  • User can review all articles or make final decision anytime
  
  Possible paths:
    approve all → continue to Publisher
    reject → restart from Supervisor
    re-run → restart from Summarizer (with edited profile)
  ↓
Publisher (10s, $0)
  • Send newsletter via Gmail API (or simulation mode)
  • Update 8 memory stores:
    1. source_scores: boost credibility for published sources
    2. story_fingerprints: save fingerprints for cross-week dedup
    3. topic_history: record topics covered this week
    4. preference_history: track profile weight changes
    5. eval_results: log metrics (relevance_rate, edit_rate)
    6. newsletters: archive full HTML + metadata
    7. user_feedback: save human actions from review
    8. summary_cache: already updated by summarizer
  ↓
END (82s total autonomous + human review)
```

---

## Node Descriptions (Detailed)

### Node 1: Supervisor
**Role**: Intelligent orchestrator; decides fetch priorities and topic focus.

**State Reads**:
- `run_id`, `run_timestamp`
- `interest_profile` (user's topic weights, e.g., {"LLMs": 0.95, "Vision": 0.7})
- `topic_history` from memory (topics covered last 4 weeks)
- `cost_budget` (from config, default $2.00)

**State Writes**:
- `fetch_plan` (human-readable strategy summary)
- `priority_topics` (list of topics ranked by weight)
- `subagent_instructions` (per-subagent overrides)
- `estimated_budget_remaining`

**Logic**:
1. Reads topic_history; identifies topics with > 3 articles last week
2. Deprioritizes heavily-covered topics
3. Decides which subagents to enable (RSS always, Tavily/HN/ArXiv conditional on budget)
4. Sets dynamic fetch budgets per subagent
5. Returns human-readable fetch_plan

**Model**: Claude Sonnet 4.6 (strategic reasoning)
**Cost**: ~$0.003/run
**Time**: ~1 second

---

### Node 2: Subagent Dispatcher (Consolidated)
**Role**: Coordinate 3 parallel data sources; aggregate results.

**Architecture Note**: Single node with 3 internal fetchers (asyncio), not 3 separate LangGraph nodes.

**Why 3 Sources? (Tavily Disabled)**
- Tavily results lacked reliable date extraction (landing pages, aggregators, forum posts)
- 3 trusted sources (RSS, HN, ArXiv) have consistent, verified date metadata
- Reduced from ~100 to ~40-50 articles with higher quality
- No date extraction complexity; all sources have reliable publication dates

**Internal Fetchers**:

1. **RSS Fetcher**
   - Source: feedparser.parse() on RSS feeds (no auth)
   - Feeds: DeepMind, Google AI, Hugging Face, TechCrunch, The Gradient, Papers with Code
   - Max: 15 articles per feed
   - Early date filter: skip articles > 7 days old
   - Fields: url, title, summary, published_date, source_domain

2. **Hacker News Fetcher**
   - Source: Firebase API (hacker-news.firebaseio.com/v0, no auth)
   - Logic: Fetch top 30 stories, filter by score ≥50 + AI keywords
   - Max: 15 articles
   - Keywords: "AI", "LLM", "GPT", "Claude", "transformer", "deep learning", etc.
   - Fields: url, title, hn_score, published_date, source_domain="news.ycombinator.com"

3. **ArXiv Fetcher**
   - Source: arxiv.Search() (no auth)
   - Queries: ["large language models", "vision transformers", "reinforcement learning", "AI alignment safety"]
   - Max: 15 articles per query (3 results × 5 queries)
   - Fields: url, title, summary (abstract), published_date, source_domain="arxiv.org", arxiv_category

**State Reads**:
- `priority_topics` (from supervisor)
- `subagent_instructions` (from supervisor)
- Config: RSS_FEEDS, TAVILY_API_KEY, HN_MIN_SCORE, ARXIV_QUERIES

**State Writes**:
- `articles` (via Annotated[list, operator.add] for thread-safe append)
- `fetch_errors` (appended from any fetcher failures)
- `total_fetched` (count)

**Aggregation**:
- Parallel execution: all 4 fetchers run concurrently
- Results merged via operator.add
- Each article tagged with fetch_source ("rss", "tavily_search", "hacker_news", "arxiv")
- Max enforced: 15/source, 120 total

**Timeout**: 90 seconds (enforced per fetcher)
**Cost**: $0 (APIs are free or free tier)
**Time**: ~25 seconds (max of parallel fetchers)

---

### Node 3: Validator
**Role**: Score, filter, and gate articles by credibility and date.

**State Reads**:
- `articles` (from dispatcher)
- `run_timestamp`
- `source_scores` from memory (cached domain credibility)
- Blacklisted sources from memory

**State Writes**:
- `articles` (updated in-place with validation_status, credibility_score, validation_reason)
- `validation_stats` (filter counts)

**Filtering Steps** (in order):
1. **Runaway check**: if len(articles) > 120, raise error
2. **Date filter**: if published_date < run_timestamp - 7 days, mark "too_old"
3. **Credibility scoring**:
   - Check source_memory cache
   - If cached, use score
   - If not cached, call credibility_skill
   - If credibility < 0.3 AND domain not in KNOWN_CREDIBLE_SOURCES, mark "low_credibility"
4. **Blacklist check**: if domain in blacklisted_sources, mark "blacklisted"
5. **Circuit breaker**: if validated > 60, trim to 60 by credibility descending

**Cost**: ~$0.0004 per new domain × ~5 new domains/month = ~$0.002/run
**Time**: 5–10 seconds
**Output**: ~80 articles (20% filtered)

---

### Node 4: Deduplicator
**Role**: Remove duplicates within run and across weeks.

**Strategies**:

1. **Exact URL dedup**: Track seen_urls set; only first occurrence kept
2. **Fingerprint dedup**: SHA256(title.lower() + ":" + domain.lower()); within-run tracking
3. **Cross-week dedup**: Check fingerprint against story_fingerprints from memory (28 days)

**State Reads**:
- `articles` (from validator)
- `story_fingerprints` from memory (last 4 weeks)

**State Writes**:
- `articles` (marked dedup_removed=True for duplicates)
- `dedup_stats` (filter counts)

**Cost**: $0 (purely algorithmic)
**Time**: 1–2 seconds
**Output**: ~70 articles (12.5% removed)

---

### Node 5: Ranker
**Role**: Score articles by relevance and select top 15–20.

**Batch Processing** (Haiku + Batching):
- Groups articles into batches of 5
- Calls relevance_skill_batch per batch
- 4 batches for ~20 articles (vs 20 serial calls without batching)

**State Reads**:
- `articles` (from deduplicator)
- `interest_profile` or `interest_profile_edits` (human-edited takes precedence)

**State Writes**:
- `articles` (updated with relevance_score, section, ranking_removed)
- `ranking_stats` (section breakdown)
- `llm_call_count` (incremented by 1 per batch, not per article)
- `estimated_cost_usd` (incremented by ~$0.015 per batch)

**Model**: Claude Haiku 4.5
**Cost**: $0.015 × 4 = $0.06 total (vs $2.40 with Sonnet serial)
**Time**: 10–20 seconds
**Output**: 20 articles (28.6% of validated)

---

### Node 6: Summarizer
**Role**: Generate 3-sentence summaries + "why it matters" with caching.

**Cache-First Strategy**:
1. Check summary_cache for each article URL
2. If cached and < 30 days old, use cached summary ($0)
3. If not cached, mark for LLM summarization

**Batch Processing** (Haiku + Batching):
- Groups uncached articles into batches of 3
- Calls summarization_skill_batch per batch
- ~7 batches for ~20 articles (vs 20 serial)

**Cache Hit Rate**: 20–30% (RSS republishes, duplicate stories)

**State Reads**:
- `articles` (from ranker)
- `llm_call_count`, `estimated_cost_usd` (for runaway guards)
- Config: SUMMARIZER_BATCH_SIZE (default 3), ENABLE_SUMMARY_CACHE

**State Writes**:
- `articles` (updated with summary_text, why_matters)
- `llm_call_count`, `estimated_cost_usd` (incremented per batch)

**Model**: Claude Haiku 4.5
**Cost**: $0.04 × ~5 batches = $0.20 (with 30% cache hit, vs $3.00 without cache or Sonnet serial)
**Time**: 10–25 seconds (depends on cache hits)
**Output**: All 20 articles summarized

---

### Node 7: Drafter
**Role**: Assemble full HTML newsletter with Jinja2 templating.

**Logic**:
1. Identify highlight story (max relevance_score)
2. Group articles by section (Trending, Research, Tools, Industry, Analysis; max 4/section)
3. Render Jinja2 template with inline CSS (email-safe)
4. Optionally call drafting_skill for intro paragraph (if ENABLE_LLM_DRAFTING=True)

**State Reads**:
- `articles` (from summarizer)
- `interest_profile`
- `run_timestamp`

**State Writes**:
- `draft_newsletter` (full HTML ~9KB)
- `newsletter_metadata` (title, date, highlight_story_id, section_breakdown, article_count)

**Model**: Claude Sonnet 4.6 (optional intro) or static template
**Cost**: $0.003 (if LLM intro) or $0 (static template)
**Time**: 5–10 seconds
**Output**: Full HTML newsletter

---

### Node 8: Human Review (Interrupt Checkpoint)
**Role**: Pause for human decision and feedback.

**UI** (Streamlit `ui/review_app.py`, 343 lines):
- HTML preview of draft_newsletter
- Article cards with controls (approve, reject, remove, reorder)
- Global buttons: Approve & Send, Reject & Restart, Re-run with adjusted profile
- Optional: interest_profile editor

**State Reads**:
- `draft_newsletter`
- `articles`
- `run_timestamp`

**State Writes**:
- `human_review_edits` (list of Edit TypedDicts)
- `review_approved`, `review_rejected`, `review_re_rank` (booleans)
- `review_timestamp`, `review_notes`
- `interest_profile_edits` (if user adjusted weights)

**Timeout**: 24 hours (auto-reject if no input)
**Cost**: $0
**Time**: Human-driven (median ~5 min)

---

### Node 9: Publisher
**Role**: Send newsletter and update all memory stores.

**Email Flow**:
1. Build MIME message (To, From, Subject, HTML body)
2. Send via Gmail API (or simulation mode if credentials missing)
3. Return message_id

**Memory Updates** (Transactional):
1. **source_scores**: boost credibility for published sources (+0.05, capped at 1.0)
2. **story_fingerprints**: save article fingerprints for cross-week dedup
3. **topic_history**: record topics covered by section
4. **preference_history**: track interest profile weight changes based on human edits
5. **eval_results**: log metrics (relevance_rate, edit_rate, dedup_precision)
6. **newsletters**: archive full HTML + execution metadata
7. **user_feedback**: save human actions from review
8. **summary_cache**: already updated by summarizer

**State Reads**:
- `draft_newsletter`
- `articles`
- `human_review_edits`
- `run_id`, `estimated_cost_usd`

**State Writes**:
- `published` (bool)
- `publish_timestamp`
- `publish_status` (success/error)
- `message_id`

**Cost**: $0 (Gmail API free tier)
**Time**: 5–15 seconds (Gmail API latency)

---

## Summary Statistics (Autonomous Phase)

| Metric | Value |
|--------|-------|
| Raw articles fetched | ~40-50 (3 trusted sources: RSS, HN, ArXiv) |
| After Validator | ~35-40 (12% filtered) |
| After Deduplicator | ~30-35 (10% removed) |
| Final in newsletter | 20 (57-67% selected) |
| LLM calls | 12 (4 ranker + 7 summarizer + 1 drafter optional) |
| Cost | $0.27/run (with caching, down from $6+ without optimization) |
| Autonomous runtime | ~72 seconds |
| With human review | ~6 minutes median |
| Annual cost (52 weeks) | ~$14/year |

---

## Cost Breakdown (Detailed)

| Component | Count | Cost/Unit | Total |
|-----------|-------|-----------|-------|
| Ranker (Haiku batches) | 4 calls × 5 articles | $0.015/call | $0.06 |
| Summarizer (Haiku batches) | 7 calls × 3 articles | $0.04/call | $0.28 |
| Cache hits (30% of summaries) | 6 articles | -$0.04 savings | -$0.06 |
| Drafter (Sonnet, optional) | 1 call | $0.003 | $0.003 |
| Credibility (new domains, ~5/month) | amortized | $0.0004/domain | $0.001 |
| RSS, HN, ArXiv, Gmail | unlimited | $0 | $0 |
| **TOTAL** | | | **$0.27** |

**Comparison to Original Plan**:
- Without Haiku + Batching: ~$6.05/run
- Without Summary Caching: ~$0.33/run
- With optimizations: ~$0.27/run
- **Savings: 95%**

---

## Evaluation Layer Integration (Step 12)

### Evals Metrics

After **Publisher** completes and newsletter is sent, the **Evals Layer** automatically computes performance metrics by querying the database. This enables ARIA to track improvement over time.

**Three Metrics**:

1. **Relevance Rate** — Measures ranking/selection quality
   - Formula: `approved_articles / (approved_articles + rejected_articles)`
   - Query: `SELECT feedback FROM user_feedback WHERE run_id = ?`
   - Interpretation: 0.7+ = good ranking; <0.5 = re-rank needed
   - Insight: Did our model pick articles the human liked?

2. **Dedup Precision** — Measures deduplication effectiveness
   - Formula: `unique_articles / total_articles_published`
   - Query: `SELECT COUNT(*) FROM story_fingerprints WHERE newsletter_id = ?`
   - Interpretation: 1.0 = all unique; <1.0 = duplicates slipped through
   - Insight: Did deduplicator successfully prevent repeats?

3. **Source Calibration** — Measures credibility score accuracy
   - Formula: `mean(1.0 - |agent_score - human_approval_rate|)` by domain
   - Query: `source_scores` + `user_feedback` joined by source_domain
   - Interpretation: 0.7+ = good calibration; <0.5 = scores misaligned
   - Insight: Do high-credibility sources actually get approved by humans?

**Integration Points**:
- **After Publisher sends email**: User feedback captured in `user_feedback` table with source_domain
- **Evals run**: `run_evals(run_id)` queries results and logs to `eval_results` table
- **Streaming**: Metrics available in Streamlit dashboard immediately after publication

### Streamlit Dashboard (ui/review_app.py)

The review UI displays a **Metrics Panel** showing performance trends:

**Components**:
1. **Latest Metrics KPIs** (3 cards)
   - Relevance Rate: % approved (green if >70%, red if <70%)
   - Dedup Precision: % unique (shows % duplicates if any)
   - Source Calibration: agent/human agreement (green if >70%)
   - Delta indicators: "↑ Human approvals", "✅ No duplicates", "⚠️ Recalibrate sources"

2. **Historical Trend Table** (last 4 runs)
   - Run ID, Relevance, Dedup, Calibration, Timestamp
   - Enables visual trending: improving scores = learning signal
   - Base for A/B testing new profiles or ranking algorithms

**Load Flow**:
```
Streamlit loads → call get_recent_eval_runs(limit=4)
  → query eval_results table for 4 most recent runs
  → fetch metrics + supporting details
  → render KPIs + trend table
```

**Real-World Usage**:
- Run 1: Relevance=50% (profile needs tuning) → adjust weights
- Run 2: Relevance=65% (improving) → continue learning
- Run 3: Relevance=75% (good!) → stable profile
- Run 4: Relevance=78% (best yet) → ship this profile

This enables **empirical self-improvement** — the system learns what rankings and credibility scores work.

