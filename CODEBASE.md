# ARIA Codebase Documentation

**Last updated**: 2026-07-01  
**Status**: Production-ready, Step 13 complete

---

## Quick Reference

| Aspect | Value |
|--------|-------|
| **Language** | Python 3.11+ |
| **Framework** | LangGraph (multi-agent orchestration) |
| **Entry point** | `python main.py` |
| **Graph nodes** | 9 (supervisor → fetch → validate → dedup → rank → summarize → draft → review → publish) |
| **Cost per run** | ~$0.27 (Haiku + batching) |
| **Speed** | ~72 seconds autonomous + human review |
| **Database** | SQLite (8 tables, persistent memory) |
| **Memory** | Cross-run state stored in `newsletter.db` |

---

## Directory Structure

```
ARIA/
├── main.py                      # Entry point: builds LangGraph, runs pipeline, manages Streamlit UI
├── config.py                    # User preferences: interests, feeds, guardrails, budgets
├── state.py                     # ARIAState TypedDict: complete schema for pipeline state
├── smoke_test.py                # LangSmith observability smoke test
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template (copy to .env)
├── README.md                    # User guide (setup, usage, limitations)
├── CLAUDE.md                    # Project specifications (step-by-step build log)
├── CODEBASE.md                  # This file: technical architecture & code guide
│
├── agents/
│   ├── supervisor.py            # Node 1: reads interests + memory, plans fetch strategy
│   └── subagent_dispatcher.py   # Node 2: coordinates 3 parallel fetchers (RSS, HN, ArXiv)
│
├── tools/                       # Nodes 3–9: pipeline stages (validate → publish)
│   ├── validator.py             # Node 3: filters by date, credibility, applies circuit breaker
│   ├── deduplicator.py          # Node 4: removes exact/near/cross-week duplicates
│   ├── ranker.py                # Node 5: scores relevance, assigns sections, selects top 20
│   ├── summarizer.py            # Node 6: batch-summarizes via Claude Haiku + caches
│   ├── drafter.py               # Node 7: assembles HTML newsletter from ranked articles
│   ├── human_review.py          # Node 8: processes human decisions (approve/reject/re-rank)
│   └── publisher.py             # Node 9: sends via Gmail + archives locally
│
├── skills/                      # LLM-based utilities (prompt + LLM call + error handling)
│   ├── skill_interface.py       # SkillResult TypedDict (standard return shape)
│   ├── credibility_skill.py     # Claude Haiku: score domain credibility (0–1)
│   ├── relevance_skill.py       # Claude Haiku: score article relevance (0–1) + section
│   ├── summarization_skill.py   # Claude Haiku: batch-summarize (3 articles per call)
│   ├── drafting_skill.py        # Claude Sonnet: write newsletter intro paragraph
│   ├── newsletter_layout_skill.py # Claude Sonnet: arrange sections & articles
│   ├── date_extraction_skill.py # Extract publish date from URL/meta tags
│   │
│   ├── credibility.md           # Prompt specification for credibility skill
│   ├── relevance.md             # Prompt specification for relevance skill
│   ├── summarization.md         # Prompt specification for summarization skill
│   ├── drafting.md              # Prompt specification for drafting skill
│   └── newsletter_layout.md     # Prompt specification for layout skill
│
├── memory/                      # Persistent state layer (SQLite)
│   ├── db.py                    # Database initialization + connection management
│   ├── source_memory.py         # Table: source_scores (domain credibility tracking)
│   ├── story_memory.py          # Table: story_fingerprints (cross-week dedup)
│   ├── user_feedback.py         # Table: user_feedback (human reviews)
│   ├── topic_memory.py          # Table: topic_history (topics covered per newsletter)
│   └── summary_cache.py         # Table: summary_cache (cached 3-sentence summaries)
│
├── ui/
│   └── review_app.py            # Streamlit app: displays draft, collects human feedback
│
├── evals/                       # Evaluation framework (testing & metrics)
│   ├── run_golden_eval.py       # Runner: executes golden dataset against the system
│   ├── eval_runner.py           # Orchestrator: computes 3 metrics per run
│   ├── relevance_eval.py        # Metric 1: how well articles matched user approvals
│   ├── dedup_eval.py            # Metric 2: how well dedup prevented duplicates
│   ├── source_eval.py           # Metric 3: calibration between agent & human signals
│   ├── GOLDEN_DATASET.md        # Specification: 50 test cases (locked, immutable)
│   ├── GOLDEN_DATASET_REVIEW.md # Deep dive: why dataset is rigorous + authentic
│   ├── DEV_EVAL_PLAN.md         # Development tuning strategy + dev dataset split
│   │
│   ├── golden_dataset.jsonl     # 50 locked test cases (immutable for reporting)
│   ├── dev_dataset.jsonl        # 48 dev test cases (for tuning without overfitting)
│   └── reports/                 # Eval run reports (baseline, dev, final tuned)
│
├── tests/                       # Unit tests
│   ├── test_validator.py        # Validation logic tests
│   ├── test_deduplicator.py     # Dedup logic tests
│   ├── test_state.py            # State schema tests
│   ├── test_newsletter_layout_skill.py # Layout skill tests
│   └── __init__.py
│
├── newsletters/                 # Local archive of sent newsletters
│   ├── YYYY-MM-DD_HH-MM-SS/
│   │   ├── newsletter.html      # Rendered HTML email
│   │   └── metadata.json        # Article count, sections, sources
│   └── ...
│
├── aria/
│   └── langsmith_config.py      # LangSmith tracing setup (optional)
│
├── memory/
│   ├── db.py                    # SQLite connection + schema
│   ├── source_memory.py         # Query/update source credibility scores
│   ├── story_memory.py          # Query/update story fingerprints
│   ├── user_feedback.py         # Log human feedback per article
│   ├── topic_memory.py          # Track topics covered over time
│   └── summary_cache.py         # Query/cache article summaries
│
└── newsletter.db                # SQLite database (created on first run)
```

---

## Data Flow: From Trigger to Delivery

### High-Level Pipeline

```
python main.py
    ↓
[supervisor]           Read interests + memory → plan fetch strategy
    ↓
[subagent_dispatcher]  Parallel fetch: RSS, HN, ArXiv → ~40-50 articles
    ↓
[validator]            Filter by date (7 days), credibility, apply circuit breaker → ~35-40
    ↓
[deduplicator]         Remove exact + cross-week duplicates → ~30 articles
    ↓
[ranker]               Score relevance (Haiku, 5 articles/batch) → select top 20
    ↓
[summarizer]           Batch-summarize (Haiku, 3 articles/call) + cache hits → 20 with summaries
    ↓
[drafter]              Assemble HTML newsletter (Sonnet) → 9KB HTML + 5 sections
    ↓
[PAUSE: human_review]  ⏸️  User opens Streamlit → approves/rejects/re-ranks
    ├─ approve         → [publisher] send via Gmail + archive
    ├─ reject          → back to [supervisor] full re-run
    └─ re-rank         → back to [ranker] with adjusted profile
    ↓
[publisher]            Send email (Gmail API) + save locally + log feedback
    ↓
Done (72-75 seconds total, ~$0.27 cost)
```

### Detailed Stage-by-Stage

#### Stage 1: Supervisor (Node 1, ~2s)
**Input**: `ARIAState` with interest_profile, run metadata  
**Process**:
1. Read topic_history from memory (what was covered last 4 weeks)
2. Read last_newsletter_date
3. Call Claude Sonnet to reason about:
   - Which topics to emphasize
   - Which fetchers to prioritize
   - Fetch strategy based on memory
4. Build subagent_instructions (override any defaults)

**Output**: State with fetch_plan, priority_topics, estimated_budget_remaining

**Error handling**: Memory failures don't block; defaults used

---

#### Stage 2: Subagent Dispatcher (Node 2, ~30-45s)
**Input**: priority_topics, subagent_instructions  
**Process**: 3 parallel fetchers (asyncio.gather) with 90s timeout each
1. **RSS Fetcher**:
   - Polls 7 configured feeds (DeepMind, Google, HuggingFace, TechCrunch, etc.)
   - Extracts title, URL, summary, publish_date, domain
   - Max 15 articles per feed
   - Result: ~45-60 articles

2. **Hacker News Fetcher**:
   - Firebase API (public)
   - Filters top stories by HN_MIN_SCORE (50 upvotes)
   - Regex filters on HN_AI_KEYWORDS
   - Max 15 articles
   - Result: ~15-20 articles

3. **ArXiv Fetcher**:
   - API searches ARXIV_QUERIES (LLMs, vision, RL, safety)
   - Extracts title, abstract, arXiv link, publish_date
   - Max 15 per query (~4 queries)
   - Rate limit (429) handled gracefully; other fetchers continue
   - Result: ~15-30 articles

**Output**: articles list (state.articles = all_articles), fetch_errors (state.fetch_errors = errors)

**Error handling**: Each fetcher wrapped in try/except; logs error, continues

**Runaway guards**:
- max_articles_per_source = 15 (trim each fetcher's results)
- max_subagent_timeout_seconds = 90 (asyncio timeout)

---

#### Stage 3: Validator (Node 3, ~1-2s)
**Input**: ~100 articles  
**Process**: For each article:
1. **Date integrity check**:
   - Parse published_date (string → datetime)
   - Check for future dates (> 12h in future → reject "future_date")
   - Check for stale indicators ("original 2023", "via HN")
   - Reject if date is missing or unparseable

2. **Freshness filter**:
   - Article age = now - published_date
   - If age > max_article_age_days (7) → reject "too_old"

3. **Credibility score**:
   - Lookup domain in source_scores table (memory)
   - If known_credible_sources → credibility_score = 1.0
   - If domain_blacklist → credibility_score = 0.0
   - Else → call credibility_skill (Haiku LLM) → 0–1
   - Cache result in memory for next week

4. **Quality filter**:
   - If credibility_score < 0.3 → reject "low_credibility"

5. **Circuit breaker**:
   - Count articles that passed validation
   - If count > max_validated_articles (60) → trim by credibility

**Output**: articles with validation_status, credibility_score, validation_reason

**Error handling**: Credibility skill failures → default to 0.5 (neutral)

**Runaway guards**:
- max_raw_articles_total = 120 (hard stop before processing)
- max_validated_articles = 60 (circuit breaker; trim if exceeded)

---

#### Stage 4: Deduplicator (Node 4, ~2-3s)
**Input**: ~35-40 validated articles  
**Process**: For each article:
1. **Exact URL dedup**:
   - Lookup URL in story_fingerprints table (cross-week)
   - If found → dedup_removed = True, dedup_reason = "exact_url"

2. **Fingerprint dedup** (title + domain hash):
   - Compute SHA256(title.lower() + source_domain)
   - Lookup in story_fingerprints
   - If found → prefer primary source (earlier published_date)
   - Loser marked dedup_removed = True, dedup_reason = "cross_week_fingerprint"

3. **Near-duplicate detection** (within current run):
   - Normalize titles (lower, strip punctuation)
   - If similarity > 0.85 → check domain
   - If same domain → keep newer only
   - If different domain → keep primary source (higher credibility)

**Output**: articles with dedup_removed flag set; dedup_stats logged

**Memory updates**: Log removed fingerprints to user_feedback (for tracking)

---

#### Stage 5: Ranker (Node 5, ~3-5s)
**Input**: ~30 articles (after dedup)  
**Process**: Batch score by relevance (5 articles per call):
1. **Batch loop**: articles[0:5], articles[5:10], articles[10:15], ...
2. **Per batch**: Call relevance_skill_batch (Haiku LLM):
   - Input: 5 articles + interest_profile
   - Output: [{article_id, relevance_score (0–1), section, reasoning}]
3. **Section guardrail**: Apply deterministic section corrections (code-based) for edge cases
4. **Final selection**:
   - Sort by relevance_score (descending)
   - Select top FINAL_ARTICLE_COUNT (12)
   - Apply constraints:
     - min_relevance_score = 0.55 (don't pad with weak articles)
     - max_articles_per_section = 3
     - max_articles_per_source = 2
   - Articles below threshold ranked_removed = True

**Output**: articles with relevance_score, section, ranking_rank; final_articles list

**Cost tracking**: Increment llm_call_count (4 calls for 20 articles)

**Runaway guards**:
- max_llm_calls_per_run = 20 (skip batches if exceeded)
- max_cost_usd_per_run = $2.00 (skip batches if exceeded)

---

#### Stage 6: Summarizer (Node 6, ~5-10s)
**Input**: 12-20 ranked articles  
**Process**: Batch summarize (3 articles per call):
1. **Summary cache lookup**:
   - For each article: lookup (url, 30-day TTL) in summary_cache
   - If hit: use cached summary_text + why_matters
   - If miss: add to batch for LLM summarization

2. **Batch summarization**:
   - articles_to_summarize grouped in batches of 3
   - Call summarization_skill_batch (Haiku LLM):
     - Input: 3 articles + summaries
     - Output: [{article_id, summary_text (3 sentences), why_matters (1 sentence)}]
   - Validate summary quality:
     - Reject if contains error patterns ("unable to provide", "paywall", etc.)
     - Reject if meta-descriptions ("news aggregation platform")
     - Reject if < 30 characters
   - Cache valid summaries in memory

3. **Cost tracking**: Sum estimated_cost_usd per batch

**Output**: articles with summary_text, why_matters, estimated_cost_usd

**Error handling**: Summarization failures → summary_text = "Summary unavailable"

**Runaway guards**:
- max_llm_calls_per_run checked before each batch
- max_cost_usd_per_run checked before each batch
- Cache hits reduce LLM calls (target 20–30% hit rate)

---

#### Stage 7: Drafter (Node 7, ~3-5s)
**Input**: 12-20 summarized articles, final selection metadata  
**Process**:
1. **Newsletter layout** (optional LLM call):
   - Call newsletter_layout_skill (Sonnet LLM) to arrange sections
   - Output: markdown layout (optional; can use hardcoded template)

2. **Render HTML**:
   - Load Jinja2 template with inline CSS
   - Pass:
     - articles (grouped by section)
     - highlight_article (top-ranked)
     - sections (Trending, Research, Tools, Industry, Analysis)
     - metadata (date, run_id, article count)
   - Render → 9KB email-safe HTML

3. **Newsletter metadata**:
   - article_count, section_breakdown, highlight_story_id, title, date

**Output**: draft_newsletter (HTML), final_articles (12-20), newsletter_metadata

**Error handling**: Template render failures → use minimal HTML fallback

---

#### Stage 8: Human Review (Node 8, ~60s pause)
**Input**: draft_newsletter, final_articles  
**Process**: Streamlit UI at http://localhost:8501
1. **Display**:
   - Show HTML newsletter
   - Show top 20 ranked articles with:
     - Title, source, relevance_score, section
     - 3-sentence summary
     - User feedback boxes (optional notes)

2. **Collect feedback** (per article):
   - Thumbs up (approved) / down (rejected)
   - Optional reviewer notes
   - Reorder articles (future enhancement)

3. **Routing decision**:
   - **Approve & Send**: → publisher node
   - **Re-rank**: → ranker node with adjusted interest_profile
   - **Reject & Restart**: → supervisor node (full re-run)

4. **Save decision** to .aria_review_decision.json

**Output**: human_review_edits (list of Edit objects), review_decision

**Error handling**: Timeout after max_human_review_pause_hours (24) → auto-approve

---

#### Stage 9: Publisher (Node 9, ~2-3s)
**Input**: final_state (articles + draft_newsletter + approval)  
**Process**:
1. **Email send** (Gmail API):
   - Load credentials from gmail_credentials.json + gmail_token.json
   - Send email via gmail_service.users().messages().send()
   - Log message_id (Gmail API response)

2. **Local archive**:
   - Create newsletters/YYYY-MM-DD_HH-MM-SS/ directory
   - Save newsletter.html
   - Save metadata.json (article count, sections, sources)

3. **Memory updates** (8 tables):
   - `source_scores`: Update credibility based on human feedback (approve → +0.05, reject → -0.05)
   - `story_fingerprints`: Log published articles (cross-week dedup next run)
   - `user_feedback`: Log per-article human actions (approved/rejected, reviewer notes)
   - `topic_history`: Increment topic counters for this week
   - `newsletters`: Archive full newsletter metadata
   - `eval_results`: (optional) Compute 3 metrics (relevance_rate, dedup_precision, calibration)

4. **Final state**:
   - published = True
   - message_id = Gmail response
   - publish_timestamp = now

**Output**: published state, logged feedback to memory

**Error handling**:
- Gmail unavailable → message_id = "simulated_" + uuid; email not sent but state saved
- Archive failures → log warning, continue

---

## Architecture & Design Decisions

### Why LangGraph?

**Chosen for**:
- Deterministic multi-step orchestration (9 nodes in strict order)
- Built-in interrupts (human review checkpoint without complex checkpointing code)
- Conditional edges (re-rank vs. reject vs. approve routing)
- Streaming event interface (progress reporting to terminal)
- Optional checkpointing (persist state across Streamlit pause)

**Alternative**: Direct Python class-based orchestration would lack interrupt support; would require manual checkpointing.

---

### Why Haiku for Ranker & Summarizer?

**Cost reduction**:
- Haiku: $0.008/1K input, $0.04/1K output tokens
- Sonnet: $0.12/1K input, $0.60/1K output tokens
- Batch processing: 5 articles/call ranker, 3 articles/call summarizer
- Result: 94% cost reduction ($6.05 → $0.27/run)

**Quality trade-off**:
- Ranker: Deterministic scoring (well-calibrated on interest profile)
- Summarizer: Accuracy sufficient for 3-sentence briefs; LLM is constrained to format
- Drafter: Sonnet for one high-quality intro paragraph (user reads every week)

---

### Why Asyncio for Fetchers?

**Why parallel**:
- RSS (feedparser, I/O-bound, ~8-10s)
- HN (requests, I/O-bound, ~2-3s)
- ArXiv (requests, I/O-bound, ~5-10s)
- **Total serial**: ~23s; **parallel**: ~10s (3s bottleneck per max timeout)

**Implementation**: `asyncio.gather(*fetcher_coroutines, return_exceptions=True)` with 90s timeout

**Graceful degradation**: If ArXiv times out (429 rate limit), RSS + HN still complete

---

### Why SQLite for Memory?

**Chosen for**:
- Persistence: Survives across runs (cross-week dedup, topic tracking)
- ACID: Reliable writes (user feedback logging)
- Zero setup: No external database needed
- Query flexibility: SQL for complex joins (source calibration, topic history)
- File-based: newsletter.db in project root (git-tracked if needed)

**Tables** (8):
1. source_scores: Domain credibility (updated per feedback)
2. story_fingerprints: SHA256(title + domain) for dedup
3. user_feedback: Per-article human actions
4. topic_history: Topics covered per newsletter
5. preference_history: Interest profile drift (reserved for future)
6. eval_results: Performance metrics per run
7. newsletters: Archive of sent newsletters
8. summary_cache: Cached 3-sentence summaries (30-day TTL)

---

### Why @tool Decorator Layer?

**Requirement**: LangGraph certification requires explicit tool definitions (not just Python functions).

**Implementation**:
```python
from langchain.tools import tool

@tool
def credibility_skill(...) -> dict:
    """Tool: score article credibility..."""
    return SkillResult(...)
```

**Benefit**: Exposes skill signatures to LangSmith tracing, enables introspection

---

### Why Streamlit for Review UI?

**Chosen for**:
- Zero-config dev server (python -m streamlit run app.py)
- Built-in state management (st.session_state)
- No frontend build step
- Responsive (works on mobile)
- Integrates easily with Python backend (JSON polling)

**Alternative**: Flask + React would require build step + complexity

---

### Cost Circuit Breaker

**Why needed**: LLM costs scale with article count; unlimited articles = unlimited cost

**Enforcement**:
- Supervisor: Reserve budget for ranker + summarizer + drafter upfront
- Ranker: Check max_cost_usd_per_run before each batch; skip if exceeded
- Summarizer: Same; skip batch if cost exceeded

**Limits** (config.py):
- COST_BUDGET_USD = $2.00 (hard ceiling)
- RANKER_BUDGET_USD = $0.10 (reserve)
- SUMMARIZER_BUDGET_USD = $0.50 (reserve)
- DRAFTER_BUDGET_USD = $0.10 (reserve)
- Realistic spend: ~$0.27/run (buffer = $1.73)

---

### Why 9 Runaway Guards?

**Design principle**: Prevent catastrophic failures (infinite loops, token explosion, cost overruns)

**Guards** (config.py):
1. max_articles_per_source = 15 (per fetcher)
2. max_raw_articles_total = 120 (after fetch)
3. max_validated_articles = 60 (circuit breaker)
4. max_llm_calls_per_run = 20 (skip batches)
5. max_cost_usd_per_run = $2.00 (hard stop)
6. max_subagent_timeout_seconds = 90 (asyncio)
7. max_article_age_days = 7 (freshness)
8. max_human_review_pause_hours = 24 (auto-approve)
9. max_re_runs_per_review = 2 (prevent loops)

---

## Environment Variables

### Required
```bash
ANTHROPIC_API_KEY=sk-ant-...              # Claude API (ranker, summarizer, drafter)
GMAIL_SENDER_EMAIL=your-email@gmail.com   # Sender (must match OAuth credentials)
NEWSLETTER_RECIPIENT_EMAIL=recipient@...  # Recipient
```

### Optional
```bash
LANGSMITH_TRACING=true                    # Enable LangSmith observability
LANGSMITH_API_KEY=lsv2_...                # LangSmith API key
LANGSMITH_PROJECT=ARIA                    # LangSmith project name
LANGSMITH_ENDPOINT=https://api.smith.langchain.com  # LangSmith API endpoint
LANGSMITH_WORKSPACE_ID=...                # If key belongs to multiple workspaces

ARIA_REVIEW_PORT=8501                     # Streamlit port (auto-finds if unavailable)
DATABASE_PATH=./newsletter.db             # SQLite path
LOG_LEVEL=INFO                            # DEBUG, INFO, WARNING, ERROR
```

### What's NOT needed
- **Tavily API**: Disabled (unreliable dates); RSS/HN/ArXiv sufficient
- **External database**: SQLite only
- **Kafka/queue**: No async jobs; runs synchronously on `python main.py`

---

## How to Run Locally

### 1. Setup
```bash
cd ARIA
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure .env
```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
GMAIL_SENDER_EMAIL=your-email@gmail.com
NEWSLETTER_RECIPIENT_EMAIL=recipient@example.com

# Optional
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
```

### 3. Run
```bash
python main.py
```

**What happens**:
1. ~72 seconds: autonomous pipeline (fetch → rank → draft)
2. Browser opens to http://localhost:8501
3. Review newsletter in Streamlit UI
4. Click "Approve & Send" → Gmail delivery + archive
5. Streamlit stays open for you to close manually

### 4. Observe
- Terminal: progress output (nodes, article counts, costs)
- LangSmith dashboard (if enabled): all LLM calls traced
- newsletters/YYYY-MM-DD_HH-MM-SS/: local HTML archive

---

## Key Files for Common Tasks

### Customize interests
- **File**: config.py
- **Section**: INTEREST_PROFILE (line 21–32)
- **Example**: Change weights, add/remove topics

### Add RSS feed
- **File**: config.py
- **Section**: RSS_FEEDS (line 41–49)
- **Format**: https://domain.com/rss or /feed.xml

### Change newsletter sections
- **File**: config.py
- **Section**: NEWSLETTER_SECTIONS (line 88–94)
- **Note**: Also update ranker prompts in skills/relevance.md

### Adjust cost limits
- **File**: config.py
- **Section**: COST & BUDGET SETTINGS (line 186–225)
- **Impact**: Higher budget = more articles selected

### Customize email template
- **File**: tools/drafter.py
- **Note**: HTML generated via Jinja2; template embedded in code

### Update LLM models
- **File**: config.py
- **Models**: RANKER_MODEL, SUMMARIZER_MODEL, DRAFTER_MODEL (lines 211–221)
- **Cost warning**: Changing to Sonnet = 15x cost increase

### Debug a specific node
- **Option 1**: Set LOG_LEVEL=DEBUG in .env
- **Option 2**: Add logging to node function
- **Option 3**: Run smoke_test.py to check LangSmith setup

---

## Testing

### Unit tests
```bash
pytest tests/
```

Tests cover:
- Validator: date parsing, credibility scoring
- Deduplicator: exact/near/cross-week dedup logic
- State: ARIAState schema validation
- Newsletter layout skill: section arrangement

### Integration tests
```bash
# Run golden dataset eval
python -m evals.run_golden_eval --dataset evals/golden_dataset.jsonl --phase final
```

Evaluates system against 50 locked test cases covering:
- Validation accuracy (date, credibility)
- Dedup accuracy (duplicates removed)
- Ranking accuracy (articles scored correctly)
- Grounding accuracy (summaries valid)

### LangSmith observability check
```bash
python smoke_test.py
```

Verifies LangSmith API access and trace write permissions.

---

## Known Limitations (Step 14 — Not Implemented)

- **PDF export**: Newsletters are HTML only (not PDF)
- **Slack/Teams delivery**: Email only; no webhook integration
- **Recurring jobs**: No APScheduler; must run `python main.py` weekly manually
- **Multi-user**: Single-user system (one interest profile)
- **Custom frequencies**: Weekly only; no daily/bi-weekly
- **OAuth flow**: Gmail requires manual credentials.json setup
- **Full re-rank loop**: Limited to 2 re-runs max (prevents infinite loops)

---

## Production Considerations

### Monitoring
- **Cost**: Check estimated_cost_usd per run (target: <$0.30)
- **Quality**: Review relevance_rate per run (target: >70%)
- **Latency**: Total time should be 5-10 minutes (autonomous + human review)

### Maintenance
- **Memory cleanup**: Fingerprints/summaries auto-expire (30 days); manual cleanup not needed
- **Logs**: If LOG_TO_FILE=true, check logs/aria.log periodically
- **Database**: No maintenance; SQLite auto-manages

### Scaling
- **Articles per run**: Currently ~20 selected; can scale to 30 by increasing budget
- **Sources**: Add RSS feeds in config.py; cost impact minimal
- **Frequency**: Run weekly via cron (not implemented; manual for now)

---

## Troubleshooting

### "Gmail not configured" message
- **Check**: GMAIL_SENDER_EMAIL in .env
- **Setup**: First run will create gmail_credentials.json (follow OAuth flow)
- **Note**: Requires 2FA enabled on Gmail account

### Articles missing summaries
- **Cause**: Summarizer failed on those articles (paywall, boilerplate, timeout)
- **Check**: Validator output logs why
- **Fix**: Increase SUMMARIZER_BUDGET_USD to add retries

### Cost exceeded $2.00
- **Cause**: More articles selected than budget allows
- **Fix**: Lower FINAL_ARTICLE_COUNT or increase COST_BUDGET_USD
- **Alternative**: Switch fetchers to RSS-only (fastest, cheapest)

### Streamlit not opening browser
- **Check**: Is Streamlit running? (curl http://localhost:8501)
- **Manual**: Open browser to http://localhost:8501 manually
- **Debug**: Check stderr output for port conflicts

### LangSmith traces not showing up
- **Check**: LANGSMITH_API_KEY set in .env
- **Verify**: Run smoke_test.py to check permissions
- **Note**: Traces appear in https://smith.langchain.com/projects/ARIA with 5-10s delay

---

## Code Quality & Cleanup (Session 1)

**Cleanup log**:
- ✅ Removed duplicate `import json` from main.py
- ✅ Removed Tavily reference from .env.example (disabled in Step 13.4)
- ✅ Renamed test.py → smoke_test.py (clarifies purpose)
- ✅ Created CODEBASE.md (this file)
- ✅ Verified all imports compile (py_compile check)
- ✅ Confirmed 9 runaway guards enforced in code

**Next opportunities** (future cleanup):
- Add type hints to memory/* functions
- Consolidate logging patterns (standardize INFO vs DEBUG)
- Extract Jinja2 template to separate file
- Add function-level docstrings to all skills/*

---

**Version**: 1.0  
**Status**: Production-ready  
**Last verified**: 2026-07-01
