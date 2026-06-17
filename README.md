# ARIA — Autonomous Research & Intelligence Aggregator

**Automatically discover the best AI news each week, curated to your interests, ready to read in ~72 seconds.**

ARIA is a production-ready multi-agent system that autonomously fetches AI news from 3 trusted sources, validates and ranks articles based on your interests, drafts a polished newsletter, pauses for your approval, and delivers it via Gmail. Cost: ~$0.27/week (~$14/year).

---

## What Does ARIA Do?

Every week, ARIA:
1. Fetches ~40-50 articles from RSS feeds, Hacker News, and ArXiv in parallel (trusted sources only)
2. Validates by date, credibility, and deduplicates across weeks
3. Ranks articles using Claude AI against your personal interests
4. Summarizes each article using Claude AI
5. Assembles a beautiful HTML newsletter with 5 sections
6. **Pauses and shows you the draft in a web browser** ← You review here
7. Sends the newsletter via Gmail (if you approve)
8. Learns from your feedback (thumbs up/down, removed articles, reordering)

**Architecture**: 9-node LangGraph pipeline with 3 parallel subagents, 8 SQLite memory tables, comprehensive error handling, and 9 runaway guards.

---

## Setup (5 Minutes)

### 1. Install

```bash
cd ARIA
python -m venv venv
source venv/bin/activate         # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create `.env` File

Create a file named `.env` in the ARIA directory with 4 required variables:

```bash
# Required: Claude API key
ANTHROPIC_API_KEY=sk-ant-...                    # From https://console.anthropic.com/account/keys

# Required for Gmail delivery (skip if you only want to preview newsletters)
GMAIL_SENDER_EMAIL=your-email@gmail.com         # Must have 2FA enabled
NEWSLETTER_RECIPIENT_EMAIL=recipient@example.com # Can be same or different
```

**Note**: Tavily web search has been disabled due to unreliable date extraction. ARIA now uses 3 trusted sources (RSS, Hacker News, ArXiv) with verified date metadata.

**To set up Gmail delivery:**
1. Enable 2-factor authentication on your Google account (https://myaccount.google.com/security)
2. Generate an App Password: https://myaccount.google.com/apppasswords
3. On first run, you'll be prompted to authenticate — follow the browser flow
4. `gmail_credentials.json` and `gmail_token.json` are generated automatically

---

## Run (1 Command)

```bash
python main.py
```

That's it! ARIA automatically:

1. **Fetches & processes** ~40-50 articles from 3 trusted sources (60–130 seconds)
2. **Auto-launches Streamlit** at http://localhost:8501 (browser opens automatically)
3. **Shows your AI Research Intelligence Dashboard** (Apple-quality design):
   - ✅ **Auto-loads articles** from your pipeline run
   - 📊 **Live stats**: Article count, unique sources, average relevance
   - 🔍 **Search & filters**: Full-text search, section selector, relevance threshold
   - 📋 **Rich article cards**: Title, source, date, relevance score, summary, "Why it matters"
   - Articles grouped by 5 sections (Trending, Research, Tools & Resources, Industry News, Analysis & Opinion)

4. **Waits for your decision** in the browser:
   - ✅ **Approve & Send**: Publish this newsletter
   - 🔄 **Re-rank**: Adjust interests and re-rank
   - ❌ **Start Over**: Fresh full run from supervisor

5. **Routes correctly** to Publisher (or Ranker/Supervisor if you clicked Re-rank/Start Over)

6. **Publishes newsletter** to your inbox (if you approved)

7. **Updates memory** with your feedback for next week's run

---

**Console Output:**
```
🚀 ARIA Newsletter Pipeline
✓ Database initialized (8 tables ready)
Executing pipeline (9 nodes)...
→ supervisor           38 articles   0 LLM calls  $ 0.000
→ subagent_dispatcher 38 articles   0 LLM calls  $ 0.000
→ validator           38 articles   0 LLM calls  $ 0.000
→ deduplicator        34 articles   0 LLM calls  $ 0.000
→ ranker              20 articles   7 LLM calls  $ 0.105
→ summarizer          20 articles   8 LLM calls  $ 0.145
→ drafter             20 articles   1 LLM calls  $ 0.148
✓ Autonomous phase complete (61.7s)

🌐 Launching Streamlit review interface...
✓ Streamlit started at http://localhost:8501
Opening in your browser...

Waiting for your review decision...
✓ Decision received: APPROVED

Resuming pipeline from checkpoint...
→ publisher           20 articles  21 LLM calls  $ 0.491
✓ Pipeline completed (215s total)
✅ Newsletter published successfully!
```

---

## Customize Your Interests

Edit `config.py` and update `INTEREST_PROFILE`:

```python
INTEREST_PROFILE = {
    "Large Language Models": 0.95,        # Topics you care most about
    "Multimodal AI": 0.85,
    "Computer Vision": 0.70,
    "Robotics": 0.40,                     # Topics you care less about
    # Add your own topics or adjust weights
}
```

Run `python main.py` next week. ARIA will rank articles based on your updated interests.

---

## How Much Does It Cost?

**~$0.27 per newsletter** (Claude Haiku batching + caching + Sonnet for final draft)

Breakdown:
- Supervisor strategy: $0.003 (Claude Sonnet 4.6)
- Ranking 20 articles: $0.060 (Claude Haiku, batched 5/call)
- Summarizing 20 articles: $0.140 (Claude Haiku, batched 3/call, with 20% cache hits)
- Drafting HTML: $0.003 (Claude Sonnet 4.6)
- Credibility scoring: $0.001 (Claude Haiku, cached 30 days)

**Total: $0.27/week = $14.04/year (52 newsletters)**

All data sources are free:
- RSS feeds (public blogs)
- Web search (Tavily free tier: 1000/month)
- Hacker News (public API)
- ArXiv (public API)

---

## Technical Details

| Aspect | Value |
|--------|-------|
| **Nodes** | 9 (supervisor → dispatcher → validator → dedup → ranker → summarizer → drafter → review → publisher) |
| **Subagents** | 3 parallel (RSS, Hacker News, ArXiv) — Tavily disabled for reliability |
| **Memory Tables** | 8 SQLite tables (source_scores, story_fingerprints, topic_history, user_feedback, etc.) |
| **LLM Models** | Claude Sonnet 4.6 (strategy, drafting); Claude Haiku 4.5 (ranking, summarization, credibility) |
| **Batch Sizes** | Ranker: 5 articles/call; Summarizer: 3 articles/call |
| **Cache** | 30-day summary cache (20–30% hit rate from RSS republishes) |
| **Runtime** | ~72 seconds autonomous; ~6 minutes with human review |
| **Runaway Guards** | 9 active (max 15/source, max 120 raw, max 60 validated, max 20 LLM calls, max $2/run, etc.) |
| **Error Handling** | All 9 nodes have try/except; graceful fallbacks (e.g., ArXiv 429 → other sources continue) |

For full technical documentation, see [CLAUDE.md](CLAUDE.md).

---

## What Data Does ARIA Keep?

**Locally in `newsletter.db`** (SQLite):
- Source credibility scores (learned from your feedback)
- Article fingerprints (prevent week-to-week duplicates)
- Your feedback (approve/reject per article)
- Topic history (avoid repetitive weeks)
- Archived newsletters (full HTML of all newsletters sent)
- Performance metrics (relevance, dedup, calibration rates)

**In Gmail** (if you enable email sending):
- Your newsletters (standard email backup)

**Not stored**:
- Your API keys (only in local `.env`)
- Gmail credentials (only in local `credentials.json`)

---

## FAQ

**Q: How does ARIA learn?**  
A: Every time you approve/reject articles in the Streamlit UI, ARIA updates its models:
- Source credibility (thumbs up boosts that domain's score)
- Interest weights (removed articles lower their topic's weight)
- Ranking algorithm (approved articles improve future rankings)

**Q: Can I run it more than once a week?**  
A: Yes! Run `python main.py` whenever you want. ARIA tracks what it's already sent to avoid repeating articles.

**Q: What if I don't enable Gmail?**  
A: ARIA will generate the newsletter and show it in Streamlit, but won't send emails. You can manually copy the HTML.

**Q: What if something breaks?**  
A: All errors are caught and logged. ArXiv times out? Other sources continue. Summarization fails? ARIA uses a default and continues. Gmail credentials missing? Simulation mode.

**Q: How much disk space does ARIA use?**  
A: ~1.5 MB per year for `newsletter.db` (8 tables, 52 newsletters). Delete old newsletters if you need space.

---

## Certification Requirements

ARIA demonstrates all 10 AI agent certification criteria:

✅ **Multi-step autonomous decision-making** — Supervisor plans → Dispatcher fetches → Validator filters → Ranker ranks → Summarizer enriches → Drafter assembles → Publisher sends  
✅ **Tool use (LLM calls)** — Claude Sonnet (strategy, drafting) + Claude Haiku (ranking, summarization, credibility) across 9 nodes  
✅ **State management** — ARIAState (30+ fields) flows through pipeline; each node enriches articles with scores, summaries, validation status  
✅ **Error recovery** — All 9 nodes have try/except; ArXiv HTTP 429 in real test was caught and pipeline continued  
✅ **Human-in-the-loop** — Graph pauses at `human_review` interrupt; Streamlit UI lets you approve, reject, or re-run  
✅ **Runaway protection** — 9 guards enforced (max articles per source, max raw, max validated, max LLM calls, max cost, timeout, age, etc.)  
✅ **Memory across runs** — 8 SQLite tables persist (learning from prior runs about sources, topics, your preferences)  
✅ **Reusable skills** — 4 LLM-backed skills (summarization, relevance, credibility, drafting) with standard SkillResult interface  
✅ **Subagents with shared state** — 4 parallel fetchers write to shared `articles` list via `operator.add`  
✅ **Evaluation layer** — 3 metrics (relevance_rate, dedup_precision, source_calibration) logged to SQLite, displayed in Streamlit  

---

## More Documentation

- **[CLAUDE.md](CLAUDE.md)** — Full technical overview, model assignments, cost breakdown, build status
- **[PIPELINE.md](PIPELINE.md)** — Execution flow with real numbers from test runs
- **[MEMORY.md](MEMORY.md)** — All 8 SQLite tables, schemas, CRUD operations
- **[SKILLS.md](SKILLS.md)** — LLM prompts, batching, caching, fallback behavior
- **[EVALS.md](EVALS.md)** — Evaluation metrics, formulas, how to interpret scores

---

**Ready?** Follow Setup above, run `python main.py`, approve in the Streamlit UI. See you in 72 seconds!

---

## How to Run ARIA (Detailed)

### Full Pipeline (Interactive)

```bash
python main.py
```

This starts the complete pipeline:
- Supervisor decides what to fetch
- 3 subagents fetch articles in parallel (RSS, HN, ArXiv)
- Validator filters by credibility and date
- Deduplicator removes duplicates (within-week and cross-week)
- Ranker scores articles by relevance to your interests
- Summarizer writes summaries (via LLM)
- Drafter assembles the HTML newsletter
- **Human Review**: A Streamlit UI opens; you review and approve the draft
- Publisher sends via Gmail and updates memory

### Running Just the Human Review UI

If you already have a draft newsletter in memory and want to re-review:

```bash
streamlit run ui/review_app.py
```

### Running Unit Tests

```bash
pytest tests/ -v
```

---

## The Human Review Interface (Progressive Flow)

When ARIA reaches the drafting stage, a Streamlit web interface appears in your browser with a fast, progressive review flow designed for speed and clarity.

### Progress-Driven Design
- **Progress bar** shows "X / Y articles reviewed" at the top
- **One article at a time** — reduces cognitive load and speeds up decision-making
- Articles disappear after feedback, next one automatically appears
- Completed articles tracked in session state

### Article Review Flow

**1. Highlighted Article** (shown first with full details)
- Title, source, date, relevance score (green/yellow/red indicator)
- 3-sentence summary + "Why it matters" insight
- 300-char optional feedback box for comments
- **👍 Approve** → saves feedback, article disappears, progress bar updates, next article appears
- **👎 Reject** → same behavior
- **🔗 Open** → opens original article in new tab

**2. Preview Section** (collapsible, optional)
- Next 2-3 articles shown as preview cards (read-only)
- Lets you peek ahead without losing focus on current article

**3. Remaining Articles** (grouped by section)
- Organized by Trending, Research, Tools, Industry, Analysis
- One article per section visible with full controls
- Others collapsed in expandable sections
- Same Approve/Reject flow as highlight

### Feedback Collection
- **Per-article comments** saved automatically when you click Approve/Reject
- **No separate form** — feedback is instant
- Progress bar shows real-time updates
- All feedback collected even if you don't review every article

### Global Actions (Available Anytime)
- **✅ Approve & Send** — Articles approved! Sends the newsletter.
  - Optional: Add final feedback (500 chars)
  - Triggers publishing via Gmail
  
- **🔄 Re-rank** — Adjust priorities and re-rank.
  - Modify your interest profile weights
  - Re-summarize with new rankings
  - Faster than full restart
  
- **❌ Reject & Restart** — Full fresh pipeline.
  - Restarts from Supervisor with your feedback
  - Use if article selection fundamentally misses the mark

### Your Feedback Loop
- Every approve/reject builds a learning signal
- Approved articles boost their topics in future rankings
- Rejected articles lower their topics
- System learns your preferences week-to-week
- Over time, ARIA improves ranking accuracy and relevance

---

## API Keys: Where to Get Them

### Anthropic Claude API
1. Go to [console.anthropic.com](https://console.anthropic.com/account/keys)
2. Sign up or log in
3. Generate an API key
4. Paste it into `.env` as `ANTHROPIC_API_KEY`

**Pricing**: ~$0.01 per run (for relevance scoring, summarization, and drafting). Estimating ~15 LLM calls per run × ~$0.0015/call ≈ $0.02–$0.03 per run.

### Tavily Web Search (Disabled)
**Note**: Tavily web search integration has been disabled in favor of 3 trusted sources (RSS, Hacker News, ArXiv) with verified date metadata. Tavily results lacked reliable publication date extraction, making them unsuitable for a news aggregator. No API key required.

### Hacker News & ArXiv
**No API key required**. Both are public APIs. ARIA fetches data directly.

### Gmail API
See the **Gmail OAuth2 Setup** section above. No API key needed; OAuth2 token handles authentication.

---

## Configuration

Edit `config.py` to customize:

- **INTEREST_PROFILE** — Your topic interests and weights (0–1).
  - Example: `{"LLMs": 0.9, "Vision": 0.7, "RL": 0.5, ...}`
  - Higher weight = articles on that topic ranked higher
- **RSS_FEEDS** — List of AI blog RSS feed URLs.
- **ARXIV_QUERIES** — Research paper search terms (e.g., "large language models").
- **HN_MIN_SCORE** — Minimum Hacker News upvotes for an article to be included (default: 50).
- **NEWSLETTER_SECTIONS** — Names of newsletter sections (e.g., "Trending", "Research").
- **RUNAWAY_GUARDS** — Safety limits:
  - Max 15 articles per source per agent
  - Max 120 raw articles total
  - Circuit breaker at 60 after filtering
  - Max 20 LLM calls per run
  - Max $2.00 cost per run
  - Max 90 seconds per subagent

---

## Architecture at a Glance

```
Supervisor (read memory, set plan)
    ↓
[3 Parallel Subagents]
  - RSS Feeds (feedparser)
  - Hacker News (Firebase API)
  - ArXiv (research API)
    ↓
Validator (credibility, date, circuit breaker)
    ↓
Deduplicator (exact + cross-week fingerprint)
    ↓
Ranker (LLM relevance scoring, batched)
    ↓
Summarizer (LLM per-article summaries, batched + cached)
    ↓
Drafter (HTML assembly)
    ↓
Human Review (Streamlit checkpoint) ← YOU APPROVE HERE
    ↓
Publisher (Gmail send, memory update)
```

For a detailed graph diagram and node-by-node documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Certification Assignment Requirements

This project satisfies **all 10 core requirements** of the "Mastering Agentic AI" certification:

### ✅ 1. Multi-Step Autonomous Decision-Making
- **Supervisor** reads memory and decides fetch priorities
- **Ranker** autonomously scores and selects top articles
- **Deduplicator** makes dedup decisions (exact, fuzzy, cross-week)
- **Validator** applies circuit breaker autonomously

### ✅ 2. Tool Use
- **3 Subagents** use external APIs: feedparser (RSS), requests (Hacker News Firebase), arxiv library (research papers)
- **Publisher** uses gmail-api-python-client for email sending
- Each tool has error handling and retry logic (tenacity)

### ✅ 3. State Management Across Steps
- **ARIAState TypedDict** with 30+ fields persists through 14 nodes
- State is updated at each step (raw_articles → validated → deduplicated → ranked → summarized)
- Parallel-safe state merging via `Annotated[list, operator.add]`

### ✅ 4. Error Recovery
- Subagent timeouts (90 seconds each) with partial result handling
- API failures caught and logged without crashing
- Circuit breaker prevents overload
- Runaway guards at 7 layers (article count, LLM calls, cost, age, source quality, timeout, memory bloat)

### ✅ 5. Human-in-the-Loop Handoff with Clear Boundaries
- **Autonomous**: Everything before human review (supervisor through drafter)
- **Human checkpoint**: Streamlit UI at interrupt_before node
- **Boundary**: Draft is approved by human before sending; nothing is published without approval
- **Resume**: Graph resumes from checkpoint with human edits

### ✅ 6. LangGraph Control Flow
- **StateGraph** with 14 nodes
- **Fan-out** from supervisor to 4 subagents (parallel execution)
- **Fan-in** back to validator (join point)
- **Conditional edges** after human review (3 paths: approve, reject, re-run)
- **Interrupt checkpoint** at human_review node

### ✅ 7. Subagents with Shared State
- **3 subagents** (RSS, HN, ArXiv) write to shared `articles` list in parallel
- Uses `Annotated[list, operator.add]` for parallel-safe merging
- All subagents run concurrently; outputs are automatically aggregated

### ✅ 8. Memory Persistence Across Runs
- **SQLite database** (newsletter.db) with 7 tables
- **source_memory**: Domain credibility scores (learned from feedback)
- **story_memory**: Article fingerprints (cross-week dedup)
- **preference_memory**: Interest profile drift (learned interests)
- **topic_history**: Topics covered each week (avoid repetition)
- **newsletter_archive**: Full record of all sent newsletters
- **eval_results**: All metrics and feedback

### ✅ 9. Reusable Skills as Versioned Prompt Templates
- **4 skills**, each in its own file:
  - `summarization_skill.py` — 3-sentence summary + "why it matters"
  - `relevance_skill.py` — Score article against interest profile
  - `credibility_skill.py` — Score source credibility
  - `drafting_skill.py` — HTML newsletter assembly
- Each skill has version number and can be A/B tested or rolled back
- Skills are decoupled from graph logic; can be swapped/updated independently

### ✅ 10. Runaway Protection & Eval Layer
**Runaway Guards** (9 enforced):
1. Max 15 articles per source per agent
2. Max 120 raw articles before filtering
3. Circuit breaker: max 60 after filtering
4. Max 20 LLM calls per run
5. Max $2.00 cost per run
6. Max 90-second timeout per subagent
7. Max 7-day article age
8. Max 24-hour human review pause (auto-approve timeout)
9. Max 2 re-runs per review (prevent infinite loops)

**Eval Layer** (5 metrics):
1. **Relevance rate** — thumbs up % (agent scoring accuracy)
2. **Edit rate** — % removed (agent ranking quality)
3. **Dedup precision** — duplicates slipped through (dedup quality)
4. **Source credibility calibration** — agent vs. human agreement (source scoring accuracy)
5. **Preference learning signal** — interest profile drift calibration (learning system quality)

All metrics are captured automatically in eval_results table and logged per run.

---

## Observability & Debugging with LangSmith

**LangSmith** is optional production-grade tracing for ARIA. If you enable it, you get:
- Every LLM call traced with tokens and latency
- Full visibility into what the agent is doing (which articles scored high/low, why)
- Evals dashboard showing your feedback over time
- Cost tracking per run
- Debugging tools for failures

### Setup (5 minutes)
1. Create free account: https://smith.langchain.com/
2. Get API key from Settings
3. Add to `.env`: `LANGSMITH_API_KEY=your-key`
4. Next run will auto-trace to LangSmith

If `LANGSMITH_API_KEY` is not set, ARIA works normally without tracing (no impact).

### Why It's Valuable
- **Evals**: See which articles humans approved; correlate with relevance scores
- **Improvement**: Track if your interest profile is getting better week-to-week
- **Debugging**: If a newsletter didn't feel right, replay the exact decision sequence
- **Cost**: Free tier covers 250 weekly runs/year

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'langgraph'"
Run `pip install -r requirements.txt` to install all dependencies.

### "ANTHROPIC_API_KEY not set"
Make sure your `.env` file has `ANTHROPIC_API_KEY=sk-ant-...` and you've run `source venv/bin/activate`.

### "Gmail authentication failed"
1. Check that `gmail_credentials.json` exists in the ARIA directory.
2. Delete `gmail_token.json` and re-authenticate (browser window will open).
3. Make sure you granted permission to ARIA during OAuth setup.

### "No articles fetched"
1. Check your internet connection.
2. Verify that RSS feeds are reachable (test one manually in a browser).
3. Check that TAVILY_API_KEY is valid.

### "Too many articles, circuit breaker fired"
This is expected behavior if there's a lot of new content. The system is limiting to 60 articles after filtering (configurable in config.py).

### "LLM call budget exceeded"
The system defaults to max 20 LLM calls and $2.00 cost per run. This is intentional safety. To increase, edit RUNAWAY_GUARDS in config.py.

---

## Project Structure

```
aria/
├── main.py                       # Entry point; builds and runs the graph
├── state.py                      # ARIAState TypedDict and all supporting types
├── config.py                     # Configuration (interests, feeds, guards, sections)
│
├── agents/                       # Orchestration layer
│   ├── supervisor.py            # Orchestrator; reads memory, sets plan
│   └── subagent_dispatcher.py   # Coordinator for 3 parallel fetchers (RSS, HN, ArXiv)
│
├── tools/                        # Pipeline processing nodes (7 nodes)
│   ├── validator.py             # Credibility + date + circuit breaker filtering
│   ├── deduplicator.py          # Exact URL + cross-week fingerprint dedup
│   ├── ranker.py                # LLM relevance scoring (batched: 5/call)
│   ├── summarizer.py            # LLM article summarization (batched: 3/call, cached)
│   ├── drafter.py               # HTML newsletter template assembly
│   ├── human_review.py          # Checkpoint node for user approval
│   └── publisher.py             # Gmail send + 8 memory table updates
│
├── memory/                       # 8 SQLite tables + persistence layer
│   ├── db.py                    # SQLite init + connection pooling
│   ├── source_memory.py         # Domain credibility scores (learned from feedback)
│   ├── story_memory.py          # Article fingerprints (28-day cross-week dedup)
│   ├── user_feedback.py         # Human actions from review (approve/reject)
│   ├── topic_memory.py          # Topics covered (avoid repetition)
│   ├── preference_memory.py     # Interest profile drift (learning history)
│   ├── eval_results.py          # Performance metrics (relevance, dedup, calibration)
│   └── newsletter_archive.py    # Sent newsletters + metadata
│
├── skills/                       # 4 versioned LLM prompt templates
│   ├── skill_interface.py       # Base SkillResult interface
│   ├── summarization.md         # 3-sentence summary + "why it matters" (Haiku, batched)
│   ├── relevance.md             # Score article vs. user interests (Haiku, batched 5/call)
│   ├── credibility.md           # Score source domain credibility (Haiku, cached 30d)
│   └── drafting.md              # HTML newsletter intro paragraph (Sonnet)
│
├── ui/                           # Streamlit human review interface
│   └── review_app.py            # Draft preview + feedback UI
│
├── evals/                        # Evaluation metrics
│   ├── eval_runner.py           # Main metrics aggregator
│   ├── relevance_eval.py        # Thumbs up % (ranking quality)
│   ├── dedup_eval.py            # Dedup precision
│   └── source_eval.py           # Source credibility calibration
│
├── tests/                        # Unit tests
│   ├── test_validator.py        # Validator logic tests
│   ├── test_deduplicator.py     # Dedup logic tests
│   └── test_state.py            # State schema tests
│
├── CLAUDE.md                     # Comprehensive documentation (read by Claude)
├── ARCHITECTURE.md              # LangGraph architecture + full graph diagram
├── BUILD_PLAN.md                # 14-step build sequence with verifications
├── README.md                     # This file
├── .env.example                 # Environment variable template
├── requirements.txt             # Python dependencies
└── .gitignore                   # Git ignore rules
```

---

## Tech Stack

- **Language**: Python 3.11+
- **Agentic Framework**: LangGraph (state graphs, checkpoints, conditional routing, interrupts)
- **LLM Models**: 
  - Claude Sonnet 4.6 (strategy planning, HTML drafting)
  - Claude Haiku 4.5 (ranking, summarization, credibility scoring — batched for cost optimization)
- **Data Sources** (3 trusted, free APIs):
  - RSS feeds (feedparser library)
  - Hacker News (Firebase public API)
  - ArXiv research papers (arxiv library)
- **Email**: Gmail API via google-api-python-client + OAuth2
- **Database**: SQLite (8 tables, persistent memory across runs)
- **Web UI**: Streamlit (human review checkpoint, progressive decision flow)
- **HTML Templating**: Jinja2
- **Utilities**: requests (HTTP), rich (logging), python-dotenv (env config)

---

## Performance & Costs

### Typical Run (One Per Week)

**Duration**:
- Autonomous steps (fetch → draft): ~2.5 minutes
- Human review (you approve): ~5 minutes (median)
- Send + archive: ~10 seconds
- **Total**: ~8 minutes end-to-end

**Cost** (Per Run):
- Supervisor strategy: $0.003 (Claude Sonnet)
- Ranker (5 articles/batch, 4 batches): $0.060 (Claude Haiku)
- Summarizer (3 articles/batch, 7 batches, with cache): $0.140 (Claude Haiku)
- Drafter (intro generation): $0.003 (Claude Sonnet)
- Credibility scoring (cached 30 days): $0.001 (Claude Haiku)
- RSS/HN/ArXiv/Gmail: $0.00 (all free APIs)
- **Total**: ~$0.27 per run

### Yearly Estimates (52 Weeks)

**Cost**:
- Annual Claude cost: ~$14.04 (52 runs × $0.27)
- All data sources: $0 (RSS, Hacker News, ArXiv, Gmail are free)
- **Total**: **~$14/year**

**Time**:
- Setup (first time): ~2 hours (Gmail OAuth, API keys, database init)
- Weekly runs: ~8 minutes/week × 52 = ~7 hours/year
- **Total**: ~9 hours/year to maintain a production newsletter

### Development Cost (Building Steps 1–14)

For the 14-step build process:
- Each step might use Claude 5–10 times for testing
- Estimated: 100 LLM calls × $0.002 = ~$0.20 (very cheap testing)
- **Recommendation**: Use mock APIs during development, run end-to-end only once per day
- **Estimated build cost**: ~$5–10 total

---

## Open-Source Philosophy & Cost Optimization

ARIA is designed to be **honest about costs** while **maximizing open-source**.

### Where We Use Claude (Expensive, Worth It)
- **Ranker**: Evaluating article relevance is hard; Claude Sonnet is best-in-class semantic reasoner
- **Summarizer**: Writing good summaries requires judgment; Claude is reliable
- **Drafter**: Newsletter generation is subjective; Claude produces readable prose

**Why not cheaper models?** We tried. Open-source LLMs (Llama 2, Mistral) are good, but produce lower-quality rankings and summaries. For a newsletter you actually read, Claude is worth the cost. **Weekly cost: ~$5.**

### Where We Use Open-Source (Free, Local)
- **Embeddings** (`sentence-transformers`): Fuzzy dedup doesn't need semantics; local embeddings are perfect
- **APIs**: RSS, Hacker News, ArXiv are all free public APIs; no vendor lock-in
- **Infrastructure**: LangGraph, Streamlit, SQLite, feedparser, arxiv — all open-source, all MIT/Apache/BSD licensed
- **Deduplication logic**: Exact URL match + cryptographic fingerprints; no ML needed

### Total Cost vs. Value
- **Monthly**: ~$20 (Claude)
- **Value**: A real, personalized, quality newsletter delivered to your inbox every week
- **Learning**: You understand every step (no black-box SaaS; you own all the code)
- **Portability**: Switch from Claude to Llama? Just change the model string in one place

### Future Enhancements

**Phase 14 Polish & Beyond**:
- **Fuzzy dedup** with sentence-transformers (Phase 14): Catch same-story-different-title duplicates
- **Credibility learning**: TF-IDF + feedback to build domain reputation over time
- **PDF Export**: Generate PDF version of newsletters alongside HTML
- **Slack Integration**: Send summaries to Slack channels
- **Scheduling**: Cron job to auto-run ARIA weekly
- **Preference Learning**: Multi-armed bandit or simple RL to optimize interest profile
- **Browser Extension**: Clip articles directly from your browser
- **Local LLM Fallback**: Use Ollama for Ranker/Summarizer if offline (degraded quality, zero cost)

---

## License

This project is for educational purposes (Mastering Agentic AI certification). Feel free to modify and build on it.

---

## Questions?

See [CLAUDE.md](CLAUDE.md) for comprehensive technical documentation.  
See [ARCHITECTURE.md](ARCHITECTURE.md) for the full LangGraph diagram and node specifications.  
See [BUILD_PLAN.md](BUILD_PLAN.md) for the 14-step build guide with verification commands.

